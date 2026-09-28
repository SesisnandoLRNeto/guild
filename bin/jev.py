#!/usr/bin/env python3
"""Jev (TypeSafe AI) for the small judgment calls: typed answers with a confidence, in well
under a second, for a fraction of a cent. Off until you turn a scope on; with no key, or on
any error, guild falls back to what it did before.

  jev.py status                         key, scopes, the repos it may read
  jev.py test                           one call, to prove the key works
  jev.py on|off board|quests|global     turn a scope on or off
  jev.py allow|block <owner or path>    the data rule (Appen is blocked by default)
  jev.py waiting <cwd> <text>           exit 0 if the text waits for a decision (the board uses it in-process)
  jev.py stop <slug> <transcript>       the quest stop check (hooks/worker-stop.sh)
  jev.py risk <slug>                    a 1-5 risk score of the quest's diff (the trial skill)
  jev.py hook                           the global Stop hook: notify when an allowed session waits for you
  jev.py global-install | global-remove add or remove that hook in ~/.claude/settings.json

Scopes:
  board   the campaign board asks "is this session waiting for my decision?" for every
          session on this Mac (cached per message, so a refresh costs nothing)
  quests  a quest that stops without a report: asking you, finished, stuck, or mid-task;
          plus a risk score for the trial
  global  a Stop hook in ~/.claude/settings.json: any allowed session that ends its turn
          waiting for you sends a notification

Data rule: a session's text leaves this Mac only when its folder is allowed. A folder is
blocked when its git remote owner or its path is in "block" (Appen by default), unless it
is also in "allow". Config: ~/.guild/local/jev.json. Key: TYPESAFE_API_KEY in local/env.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
CONFIG = os.path.join(GUILD_HOME, "local", "jev.json")
CACHE = os.path.join(GUILD_HOME, ".jev-cache.json")
ENDPOINT = os.environ.get("GUILD_JEV_URL", "https://api.typesafe.ai/v1/systemone")
BIN = os.path.dirname(os.path.realpath(__file__))
DEFAULT = {"board": False, "quests": False, "global": False, "allow": [], "block": ["Appen"], "model": "jev-latest"}


# ── config, key, data rule ────────────────────────────────────────────────────
def config():
    try:
        return dict(DEFAULT, **json.load(open(CONFIG)))
    except (OSError, ValueError):
        return dict(DEFAULT)


def save(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    json.dump(cfg, open(CONFIG, "w"), indent=2)


def key():
    k = os.environ.get("TYPESAFE_API_KEY", "")
    if not k:
        try:
            for line in open(os.path.join(GUILD_HOME, "local", "env")):
                if line.strip().startswith("TYPESAFE_API_KEY="):
                    k = line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return k


def owner_of(cwd):
    try:
        url = subprocess.run(["git", "-C", cwd, "remote", "get-url", "origin"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"[:/]([^/:]+)/[^/]+?(\.git)?$", url)
    return m.group(1) if m else ""


def allowed(cwd):
    """May text from this folder go to TypeSafe? Blocked owners and paths stay home."""
    cfg = config()
    cwd = os.path.abspath(os.path.expanduser(cwd or "."))
    owner = owner_of(cwd) if os.path.isdir(cwd) else ""
    hit = lambda rules: any((r == owner) or (r.startswith(("/", "~")) and cwd.startswith(os.path.expanduser(r))) for r in rules)
    if hit(cfg["allow"]):
        return True
    return not hit(cfg["block"])


def active(scope):
    return bool(config().get(scope)) and bool(key())


# ── the call ──────────────────────────────────────────────────────────────────
def ask(state, questions, timeout=4):
    """POST to Jev. Returns the answers dict, or None on any problem (callers fall back)."""
    body = json.dumps({"model": config()["model"], "state": state[-6000:], "questions": questions}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("answers")
    except (OSError, ValueError, urllib.error.URLError):
        return None


def cached(tag, state, questions):
    """Ask once per distinct text: the board refreshes every few seconds, Jev is asked once."""
    h = hashlib.sha1((tag + state).encode()).hexdigest()
    try:
        c = json.load(open(CACHE))
    except (OSError, ValueError):
        c = {}
    if h in c:
        return c[h]["answers"]
    answers = ask(state, questions)
    if answers is not None:
        c[h] = {"answers": answers, "at": time.time()}
        if len(c) > 2000:                                   # keep the newest
            c = dict(sorted(c.items(), key=lambda kv: kv[1]["at"])[-1500:])
        json.dump(c, open(CACHE, "w"))
    return answers


WAITING = {"waiting": {"type": "noul", "instructions":
           "This is the last message of an AI coding assistant to its user. Is the assistant stopped and waiting "
           "for the user to make a decision or answer a question before it can go on? A report of finished work, "
           "or a message that only informs, is false.",
           "criteria": {"true": "it asks the user to choose, confirm or answer something", "false": "it informs or reports; nothing is asked"}}}


def waiting(cwd, text):
    """True/False from Jev, or None when Jev is off, not allowed for this folder, or failed."""
    if not active("board") or not text.strip() or not allowed(cwd):
        return None
    a = cached("waiting", text[-3000:], WAITING)
    if not a or "waiting" not in a:
        return None
    return a["waiting"].get("noul", 0) >= 0.5


# ── quests: the stop check and the risk score ─────────────────────────────────
STOP = {"kind": {"type": "choice", "instructions":
        "This is the last message of an AI coding agent that ended its turn without reporting to its orchestrator. What is going on?",
        "criteria": {"asking": "it asks for a decision, a confirmation or information before it can continue",
                     "finished": "it says the work is complete",
                     "stuck": "it hit an error or a blocker it cannot get past alone",
                     "waiting_on_job": "it is waiting for a background job, a test run or a build it started",
                     "mid_task": "it stopped in the middle of the work for no stated reason"}}}


def last_assistant_text(transcript):
    text = ""
    try:
        for line in open(transcript, errors="replace"):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "assistant" and not e.get("isSidechain"):
                c = (e.get("message") or {}).get("content")
                t = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [] if isinstance(x, dict) and x.get("type") == "text")
                if t.strip():
                    text = t
    except OSError:
        pass
    return text


def stop(slug, transcript):
    """Print one of: asking <question> | finished | stuck <why> | waiting_on_job | mid_task | none."""
    meta_p = os.path.join(GUILD_HOME, "quests", slug, "meta.json")
    try:
        wt = json.load(open(meta_p)).get("worktree", "")
    except (OSError, ValueError):
        wt = ""
    text = last_assistant_text(transcript)
    if not active("quests") or not text or not allowed(wt):
        print("none"); return
    a = ask(text[-4000:], STOP)
    if not a or "kind" not in a or (a["kind"].get("confidence") or 0) < 0.55:
        print("none"); return
    kind = a["kind"].get("choice", "")
    summary = re.sub(r"\s+", " ", text).strip()
    q = [s for s in re.split(r"(?<=[.?!])\s+", summary) if s.endswith("?")]
    detail = (q[-1] if q else summary[-200:])[:220]
    print(f"{kind} {detail}" if kind in ("asking", "stuck") else kind)


RISK = {"risk": {"type": "score", "instructions":
        "Rate the risk of merging this code change, from its diff: blast radius, data or schema changes, public API, auth, and how easy it is to undo.",
        "criteria": ["1: trivial, local, easy to undo", "2: small and contained", "3: moderate: touches shared code or behaviour",
                     "4: high: schema, public API, money or auth", "5: very high: hard to undo, wide impact"]}}


def risk(slug):
    meta = json.load(open(os.path.join(GUILD_HOME, "quests", slug, "meta.json")))
    wt, base = meta.get("worktree", ""), meta.get("base", "")
    if not active("quests"):
        raise SystemExit("jev: the quests scope is off (guild jev on quests)")
    if not allowed(wt):
        raise SystemExit(f"jev: {wt} is blocked by the data rule; no risk score")
    mb = subprocess.run(["git", "-C", wt, "merge-base", "HEAD", base], capture_output=True, text=True).stdout.strip() or base
    diff = subprocess.run(["git", "-C", wt, "diff", mb, "--stat", "-p"], capture_output=True, text=True).stdout
    a = ask(diff[-6000:], RISK)
    if not a or "risk" not in a:
        raise SystemExit("jev: no answer (key, network or service); the trial goes on without it")
    r = a["risk"]
    value = r.get("score", r.get("value"))
    print(f"risk {value} (confidence {r.get('confidence', '?')}) from Jev on the diff against {base}")


# ── global: a Stop hook for every Claude session ──────────────────────────────
def hook():
    """Stop hook for every session: notify when an allowed session ends waiting for you.
    Guild quests are skipped (they have their own check). Never blocks the session."""
    try:
        row = json.load(sys.stdin)
    except ValueError:
        return
    if os.environ.get("GUILD_QUEST") or not active("global"):
        return
    cwd = row.get("cwd") or os.getcwd()
    if not allowed(cwd):
        return
    text = last_assistant_text(row.get("transcript_path") or "")
    if not text:
        return
    a = cached("waiting", text[-3000:], WAITING)
    if a and a.get("waiting", {}).get("noul", 0) >= 0.6:
        sys.path.insert(0, BIN)
        import notify
        tail = re.sub(r"\s+", " ", text).strip()[-120:]
        notify.send("guild: a session waits for you", os.path.basename(cwd) + ": " + tail)


SETTINGS = os.path.expanduser("~/.claude/settings.json")
HOOK_CMD = f"python3 {os.path.join(BIN, 'jev.py')} hook"


def global_install():
    s = json.load(open(SETTINGS)) if os.path.exists(SETTINGS) else {}
    backup = SETTINGS + f".before-guild-jev-{time.strftime('%Y%m%d%H%M%S')}"
    if os.path.exists(SETTINGS):
        open(backup, "w").write(open(SETTINGS).read())
    stops = s.setdefault("hooks", {}).setdefault("Stop", [])
    if not any(HOOK_CMD in json.dumps(h) for h in stops):
        stops.append({"hooks": [{"type": "command", "command": HOOK_CMD, "timeout": 10}]})
    json.dump(s, open(SETTINGS, "w"), indent=2)
    print(f"added the Jev Stop hook to {SETTINGS} (backup: {backup}). New sessions load it; running ones do not.")


def global_remove():
    if not os.path.exists(SETTINGS):
        return
    s = json.load(open(SETTINGS))
    stops = s.get("hooks", {}).get("Stop", [])
    kept = [h for h in stops if HOOK_CMD not in json.dumps(h)]
    if len(kept) != len(stops):
        s["hooks"]["Stop"] = kept
        if not kept:
            del s["hooks"]["Stop"]
        json.dump(s, open(SETTINGS, "w"), indent=2)
        print(f"removed the Jev Stop hook from {SETTINGS}")


def main():
    a = sys.argv[1:]
    cmd = a[0] if a else "status"
    cfg = config()
    if cmd == "status":
        print(f"key: {'set' if key() else 'missing (TYPESAFE_API_KEY in ~/.guild/local/env)'}")
        for scope in ("board", "quests", "global"):
            print(f"{scope:<7} {'on' if cfg[scope] else 'off'}")
        print(f"blocked: {', '.join(cfg['block']) or 'nothing'}   allowed anyway: {', '.join(cfg['allow']) or 'nothing'}")
        print(f"this folder ({os.getcwd()}): {'may be sent' if allowed(os.getcwd()) else 'stays on this Mac'}")
    elif cmd == "test":
        if not key():
            raise SystemExit("jev: no key. Put TYPESAFE_API_KEY=... in ~/.guild/local/env")
        ans = ask("Should I keep the old endpoint, or drop it?", WAITING)
        if ans is None:
            raise SystemExit("jev: no answer: check the key, the network, or https://status.typesafe.ai")
        w = ans["waiting"]
        print(f"Jev answers: waiting for a decision = {w.get('noul'):.2f} (confidence {w.get('confidence', '?')})")
    elif cmd in ("on", "off") and len(a) > 1 and a[1] in ("board", "quests", "global"):
        cfg[a[1]] = cmd == "on"
        save(cfg)
        if a[1] == "global":
            global_install() if cmd == "on" else global_remove()
        print(f"jev {a[1]} {cmd}" + ("" if key() else "  (no key yet: it stays silent until TYPESAFE_API_KEY is set)"))
    elif cmd in ("allow", "block") and len(a) > 1:
        rule = a[1]
        cfg[cmd] = sorted(set(cfg[cmd]) | {rule})
        other = "block" if cmd == "allow" else "allow"
        cfg[other] = [r for r in cfg[other] if r != rule]
        save(cfg)
        print(f"{cmd}: {rule}")
    elif cmd == "waiting" and len(a) > 2:
        r = waiting(a[1], a[2])
        print({True: "waiting", False: "not waiting", None: "unknown"}[r])
        sys.exit(0 if r else 1)
    elif cmd == "stop" and len(a) > 2:
        stop(a[1], a[2])
    elif cmd == "risk" and len(a) > 1:
        risk(a[1])
    elif cmd == "hook":
        hook()
    elif cmd == "global-install":
        global_install()
    elif cmd == "global-remove":
        global_remove()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
