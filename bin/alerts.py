#!/usr/bin/env python3
"""Tell the guildmaster about things that go wrong while nobody looks, and keep waiting
quests cheap.

  alerts.py check     run the alert checks once (the war table runs them every 2 minutes)
  alerts.py show      what the docket shows now
  alerts.py compact   compact the quests idle with a warm cache (the war table runs it every 30s)

Alerts, each sent once (Mac, ntfy, and email when set), and listed on the docket while true:
  - a quest PR has a merge conflict, failing checks, or a reviewer waits a day for an answer
  - Claude usage passes 80% of the 5-hour or the weekly limit (read from the status line)
  - a board question waits 2 hours while its quest is blocked on it

Compaction: a quest that ended its turn to wait for you, with a big context, gets /compact
typed into its session just before the prompt cache goes cold, so your answer later is read
from a short summary instead of the whole cold context. Never the quartermaster, never a
done quest, never one with "nocompact" in its meta.json.

Settings, all optional, in ~/.guild/local/remote.json under "alerts":
  {"unanswered_hours": 24, "usage_percent": 80, "board_hours": 2,
   "compact": true, "cache_minutes": 60, "compact_tokens": 80000}
Nothing here ever writes to GitHub or Jira.
"""
import datetime
import glob
import json
import os
import subprocess
import sys
import threading
import time

BIN = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, BIN)
import notify  # noqa: E402

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
STATE = os.path.join(GUILD_HOME, "local", "alerts-state.json")
USAGE = os.path.join(GUILD_HOME, "local", "usage.json")
PROJECTS = os.path.expanduser("~/.claude/projects")
SOCKET = os.environ.get("GUILD_TMUX_SOCKET", "guild")
LOCK = threading.Lock()                # the alert loop and the compact loop share STATE
DEFAULTS = {"unanswered_hours": 24, "usage_percent": 80, "board_hours": 2,
            "compact": True, "cache_minutes": 60, "compact_tokens": 80000}


def settings():
    return dict(DEFAULTS, **(notify.config().get("alerts") or {}))


def load(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def save(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    json.dump(state, open(tmp, "w"), indent=1)
    os.replace(tmp, STATE)


def age_hours(stamp):
    """Hours since an ISO time; times without a zone are local."""
    try:
        t = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return 0
    if t.tzinfo is None:
        t = t.astimezone()
    return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 3600


# ---- what is true now -------------------------------------------------------------------

def pr_problems(cfg):
    import prs
    out = []
    for url, p in prs.cache().items():
        if p.get("state") not in ("open", "draft") or not p.get("slug"):
            continue
        head = f"{p['slug']}: PR #{p.get('number')}"
        if p.get("conflict"):
            out.append({"key": f"pr:{url}:conflict", "text": f"{head} has a merge conflict", "url": url})
        if p.get("checks") == "failing":
            out.append({"key": f"pr:{url}:failing", "text": f"{head} has failing checks", "url": url})
        hours = age_hours(p.get("waiting_since", ""))
        if p.get("waiting_since") and hours >= cfg["unanswered_hours"]:
            out.append({"key": f"pr:{url}:unanswered:{p['waiting_since']}",
                        "text": f"{head}: a reviewer has waited {int(hours)}h for an answer", "url": url})
    return out


def usage_problems(cfg):
    u = load(USAGE, {})
    if not u or time.time() - float(u.get("at") or 0) > 6 * 3600:
        return []                     # no fresh reading: say nothing rather than guess
    out = []
    for window, name in (("five_hour", "5-hour"), ("seven_day", "weekly")):
        w = (u.get("rate_limits") or {}).get(window) or {}
        pct = w.get("used_percentage")
        if pct is None or float(pct) < cfg["usage_percent"]:
            continue
        reset = w.get("resets_at", "")
        when = ""
        if isinstance(reset, (int, float)) and reset:
            when = " (resets " + datetime.datetime.fromtimestamp(reset).strftime("%a %H:%M") + ")"
        out.append({"key": f"usage:{window}:{reset}", "url": notify.docket_url(),
                    "text": f"Claude usage at {int(float(pct))}% of the {name} limit{when}: quests may stall"})
    return out


def board_problems(cfg, open_items):
    out = []
    for i in open_items or []:
        if i.get("wrapup") or i.get("pseudo"):
            continue                   # a wrap-up blocks nothing; it waits for your grade
        hours = age_hours(i.get("created", ""))
        if hours >= cfg["board_hours"]:
            out.append({"key": f"board:{i['quest']}/{i['board']}", "url": notify.docket_url(),
                        "text": f"{i['quest']} has waited {int(hours)}h on your answer: {i.get('title', '')}"})
    return out


def current(open_items=None):
    cfg = settings()
    return pr_problems(cfg) + usage_problems(cfg) + board_problems(cfg, open_items)


def check(open_items=None):
    """Send each new problem once. A problem that goes away and comes back is sent again."""
    sent = load(STATE, {}).get("sent", {})
    now_ = current(open_items)
    keys = {p["key"] for p in now_}
    for p in now_:
        if p["key"] not in sent:
            notify.send("guild: " + p["text"].split(":")[0], p["text"], p["url"], email=True)
            sent[p["key"]] = time.time()
    with LOCK:
        state = load(STATE, {})
        state["sent"] = {k: v for k, v in sent.items() if k in keys}
        save(state)
    return now_


# ---- compaction -------------------------------------------------------------------------

def tail_rows(path, size=400_000):
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - size))
        lines = f.read().decode("utf-8", "ignore").splitlines()[1:]
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def idle_session(worktree):
    """(minutes idle, context tokens, turn id) when the newest session ended its turn, else None."""
    d = os.path.join(PROJECTS, worktree.replace("/", "-").replace(".", "-"))
    logs = sorted(glob.glob(os.path.join(d, "*.jsonl")), key=os.path.getmtime)
    if not logs:
        return None
    turns = [r for r in tail_rows(logs[-1]) if r.get("type") in ("user", "assistant")]
    if not turns or turns[-1].get("type") != "assistant":
        return None
    msg = turns[-1].get("message") or {}
    if msg.get("stop_reason") != "end_turn":
        return None                    # mid-turn, or waiting on a tool
    u = msg.get("usage") or {}
    tokens = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    return age_hours(turns[-1].get("timestamp", "")) * 60, tokens, turns[-1].get("uuid", "")


def tab_open(slug):
    r = subprocess.run(["tmux", "-L", SOCKET, "list-windows", "-t", "guild", "-F", "#{window_name}"],
                       capture_output=True, text=True, timeout=5)
    return slug in r.stdout.split()


def compact_idle():
    cfg = settings()
    if not cfg["compact"] or not os.path.isdir(QUESTS):
        return []
    state = load(STATE, {})
    done_turns, did = state.get("compacted", {}), []
    # the last 90 seconds before the cache goes cold, so a 30-second loop always lands in it
    lo, hi = cfg["cache_minutes"] - 1.5, cfg["cache_minutes"] - 0.25
    for slug in sorted(os.listdir(QUESTS)):
        meta = load(os.path.join(QUESTS, slug, "meta.json"), None)
        if not meta or meta.get("pseudo") or meta.get("nocompact") or not meta.get("worktree"):
            continue
        try:
            qstate = open(os.path.join(QUESTS, slug, "status")).read().split("\t")[0]
        except OSError:
            continue
        if qstate in ("done", "graded"):
            continue
        s = idle_session(meta["worktree"])
        if not s or not (lo <= s[0] < hi) or s[1] < cfg["compact_tokens"] or done_turns.get(slug) == s[2]:
            continue
        if not tab_open(slug):
            continue
        pane = subprocess.run(["tmux", "-L", SOCKET, "list-panes", "-t", f"guild:{slug}", "-F", "#{pane_id} #{@guild_sidebar}"],
                              capture_output=True, text=True, timeout=5).stdout.split("\n")
        content = [p.split()[0] for p in pane if p.strip() and p.split()[1:] != ["1"]]
        if not content:
            continue
        subprocess.run(["tmux", "-L", SOCKET, "send-keys", "-t", content[0], "-l", "/compact"], timeout=5)
        time.sleep(0.3)
        subprocess.run(["tmux", "-L", SOCKET, "send-keys", "-t", content[0], "Enter"], timeout=5)
        done_turns[slug] = s[2]
        did.append(slug)
        with open(os.path.join(GUILD_HOME, "events.log"), "a") as f:
            f.write(f"{datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\t{slug}\tcompacted\t"
                    f"idle {s[0]:.0f} min with {s[1] // 1000}k tokens: compacted before the cache went cold\n")
    with LOCK:
        state = load(STATE, {})        # check() may have written meanwhile
        state["compacted"] = {k: v for k, v in done_turns.items() if os.path.isdir(os.path.join(QUESTS, k))}
        save(state)
    return did


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "check":
        for p in check():
            print(p["text"])
    elif cmd == "show":
        for p in current():
            print(p["text"])
    elif cmd == "compact":
        print("\n".join(compact_idle()) or "nothing to compact")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
