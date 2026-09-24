#!/usr/bin/env python3
"""Tag the quartermaster on a ticket, and a quest can start from it.

This is the one part of guild that acts without you typing a command, so it is built
around what it must never do:

- It only listens to comments **you** wrote. Anyone else mentioning the trigger is ignored.
- Ticket text never becomes a command. `check:` lines are taken from your comment only;
  the ticket description is context, with any `check:` lines stripped out.
- By default it does not start anything: it puts "start a quest for SARA-812?" on the war
  table with the brief it would use, and starts only when you say so there.
- It never writes to Jira. Drafting the ticket comment stays with you.
- It stays inside the projects you list, and never runs more than `max_active` quests
  it started itself.

Config: ~/.guild/local/jira.json   Token: JIRA_API_TOKEN in ~/.guild/local/env

    jira_watch.py once | watch | status
"""
import base64
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
GUILD = os.path.join(REPO, "bin", "guild")
CONFIG = os.path.join(GUILD_HOME, "local", "jira.json")
STATE = os.path.join(GUILD_HOME, "jira-state.json")
BOARD_QUEST = "jira"


def log(msg):
    print(f"{datetime.datetime.now():%H:%M:%S} {msg}", flush=True)


def load_config():
    if not os.path.exists(CONFIG):
        raise SystemExit(f"jira: no config at {CONFIG} (copy config/jira.example.json)")
    cfg = json.load(open(CONFIG))
    cfg["site"] = os.environ.get("GUILD_JIRA_SITE") or cfg.get("site", "")
    token = os.environ.get("JIRA_API_TOKEN")
    if not token:
        env = os.path.join(GUILD_HOME, "local", "env")
        if os.path.exists(env):
            for line in open(env):
                if line.strip().startswith("JIRA_API_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not token:
        raise SystemExit("jira: no JIRA_API_TOKEN (put it in ~/.guild/local/env)")
    cfg["_auth"] = base64.b64encode(f"{cfg['email']}:{token}".encode()).decode()
    cfg.setdefault("trigger", "@quartermaster")
    cfg.setdefault("projects", [])
    cfg.setdefault("repos", {})
    cfg.setdefault("default_repo", {})
    cfg.setdefault("autostart", False)
    cfg.setdefault("max_active", 2)
    cfg.setdefault("poll_minutes", 5)
    cfg.setdefault("model", "")
    if not cfg["projects"]:
        raise SystemExit("jira: list the projects to watch in jira.json; watching everything is not allowed")
    return cfg


def load_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {"seen": [], "pending": {}, "started": {}}


def save_state(state):
    tmp = STATE + ".tmp"
    json.dump(state, open(tmp, "w"), indent=2)
    os.replace(tmp, STATE)


def api(cfg, method, path, body=None):
    req = urllib.request.Request(cfg["site"].rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Basic {cfg['_auth']}", "Accept": "application/json",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def adf_text(node):
    """Atlassian Document Format to plain text, keeping line breaks between blocks."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if node.get("type") == "text":
        return node.get("text", "")
    if node.get("type") == "mention":
        return node.get("attrs", {}).get("text", "")
    if node.get("type") == "hardBreak":
        return "\n"
    inner = "".join(adf_text(c) for c in node.get("content", []))
    return inner + ("\n" if node.get("type") in ("paragraph", "heading", "listItem", "codeBlock") else "")


def strip_checks(text):
    """Ticket text is context, never commands: drop anything that would become a check."""
    return "\n".join(l for l in text.splitlines() if not re.match(r"^\s*(?:[-*]\s*)?check\s*:", l, re.I))


def slug_for(key, summary):
    """Readable words only: the branch is KEY/slug, so the key must not appear twice.
    If another ticket already owns those words, fall back to key-prefixed."""
    words = [w for w in re.sub(r"[^a-z0-9]+", "-", summary.lower()).strip("-").split("-") if w][:5]
    slug = "-".join(words)[:40].strip("-") or key.lower()
    meta = os.path.join(GUILD_HOME, "quests", slug, "meta.json")
    if os.path.exists(meta) and json.load(open(meta)).get("ticket") != key:
        slug = (key.lower() + "-" + slug)[:44].strip("-")
    return slug


def notify(title, text):
    if sys.platform == "darwin" and os.environ.get("GUILD_NO_NOTIFY") != "1":
        subprocess.run(["osascript", "-e", f'display notification {json.dumps(text)} with title {json.dumps(title)}'],
                       capture_output=True)


def guild(*args, stdin=None, env=None):
    return subprocess.run([GUILD, *args], input=stdin, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


def active_started(state):
    """Quests this watcher started that are still open."""
    live = 0
    for slug in state.get("started", {}):
        if os.path.isdir(os.path.join(GUILD_HOME, "quests", slug)):
            live += 1
    return live


def build_brief(issue_key, fields, instruction, site):
    desc = strip_checks(adf_text(fields.get("description"))).strip()
    mine = [l for l in instruction.splitlines() if l.strip()]
    checks = [l.strip() for l in mine if re.match(r"^\s*(?:[-*]\s*)?check\s*:", l, re.I)]
    intent = " ".join(l.strip() for l in mine if l not in checks) or fields.get("summary", "")
    lines = [f"Intent: {intent}",
             f"Context: {issue_key} {fields.get('summary', '')} ({site.rstrip('/')}/browse/{issue_key})"]
    if desc:
        lines += ["The ticket says:", *["  " + l for l in desc.splitlines()[:60]]]
    lines.append("Acceptance:")
    lines += [f"- {c.lstrip('-* ').strip()}" for c in checks] or ["- the ticket's acceptance criteria, as written above"]
    lines += ["Constraints: started from a Jira mention. Do not post anything to Jira; the guildmaster writes ticket comments.",
              "Quest type: code"]
    return "\n".join(lines) + "\n"


def start_quest(cfg, state, item):
    args = ["quest", item["slug"], "--repo", item["repo"], "--ticket", item["key"]]
    if cfg.get("model"):
        args += ["--model", cfg["model"]]
    r = guild(*args, stdin=item["brief"])
    if r.returncode != 0:
        log(f"could not start {item['slug']}: {r.stderr.strip()[:200]}")
        return False
    state["started"][item["slug"]] = {"key": item["key"], "at": datetime.datetime.now().isoformat(timespec="seconds")}
    log(f"started quest {item['slug']} for {item['key']}")
    notify("guild", f"Quest started for {item['key']}")
    return True


def propose(cfg, state, comment_id, item):
    """Put 'start this?' on the war table instead of starting it."""
    page = os.path.join(GUILD_HOME, "jira-proposals", f"{comment_id}.html")
    os.makedirs(os.path.dirname(page), exist_ok=True)
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    open(page, "w").write(
        "<!doctype html><meta charset=utf-8><style>body{font:15px/1.6 system-ui;margin:28px;color:#e6e8ef;"
        "background:#0f1117}pre{white-space:pre-wrap;background:#161922;padding:14px;border-radius:8px}"
        "@media (prefers-color-scheme: light){body{color:#1b1f2a;background:#f6f7fa}pre{background:#fff}}</style>"
        f"<h1>Start a quest for {esc(item['key'])}?</h1><p>Repo: <b>{esc(os.path.basename(item['repo']))}</b>"
        f" · slug <code>{esc(item['slug'])}</code></p><p>The brief it would get:</p><pre>{esc(item['brief'])}</pre>")
    decisions = page.replace(".html", ".json")
    json.dump({"questions": [{"id": "go", "title": f"Start the quest for {item['key']}?", "type": "single",
                              "recommended": "start",
                              "options": [{"id": "start", "label": "Start it", "why": "the brief above is right"},
                                          {"id": "skip", "label": "Do not start", "why": "I will handle this ticket another way"}]}]},
              open(decisions, "w"))
    r = guild("board", "open", "--quest", BOARD_QUEST, "--html", page, "--decisions", decisions,
              "--title", f"Jira: start {item['key']}?", env={"GUILD_QUEST": ""})
    board = next((l.split(":", 1)[1].strip() for l in r.stdout.splitlines() if l.startswith("board id:")), None)
    if not board:
        log(f"could not open a board for {item['key']}: {r.stderr.strip()[:200]}")
        return False
    state["pending"][comment_id] = {**item, "board": board}
    log(f"asked on the war table: start {item['key']}? (board {board})")
    notify("guild", f"{item['key']}: start a quest? Answer on the war table")
    return True


def settle_pending(cfg, state):
    """Act on proposals the guildmaster has answered."""
    for cid, item in list(state["pending"].items()):
        dec = os.path.join(GUILD_HOME, "quests", BOARD_QUEST, "boards", item["board"], "decision.json")
        if not os.path.exists(dec):
            continue
        choice = json.load(open(dec)).get("answers", {}).get("go")
        if choice == "start":
            if active_started(state) >= cfg["max_active"]:
                log(f"{item['key']} approved, waiting: {cfg['max_active']} auto-started quests already open")
                continue
            start_quest(cfg, state, item)
        else:
            log(f"{item['key']}: you chose not to start it")
        del state["pending"][cid]


def report_finished(state):
    """A quest the watcher started has reported done: say so, once, with its note (the PR)."""
    for slug, info in state.get("started", {}).items():
        if info.get("notified"):
            continue
        status = os.path.join(GUILD_HOME, "quests", slug, "status")
        if not os.path.exists(status):
            archived = os.path.join(GUILD_HOME, "quests", "_archive")
            hits = sorted(n for n in os.listdir(archived) if n.startswith(slug + "-")) if os.path.isdir(archived) else []
            status = os.path.join(archived, hits[-1], "status") if hits else ""
        if not status or not os.path.exists(status):
            continue
        state_, note = (open(status).read().split("\t") + ["", ""])[:2]
        if state_ in ("done", "failed"):
            info["notified"] = True
            log(f"{info['key']}: {slug} is {state_}: {note}")
            notify("guild", f"{info['key']} {state_}: {note[:80]}")


def once(cfg):
    state = load_state()
    if "account_id" not in state:
        state["account_id"] = api(cfg, "GET", "/rest/api/3/myself")["accountId"]
    me = state["account_id"]
    settle_pending(cfg, state)
    report_finished(state)

    projects = ", ".join(json.dumps(p) for p in cfg["projects"])
    word = cfg["trigger"].lstrip("@")
    jql = f'project in ({projects}) AND updated >= "-{int(cfg["poll_minutes"]) * 3}m" AND comment ~ "{word}"'
    found = api(cfg, "POST", "/rest/api/3/search/jql",
                {"jql": jql, "fields": ["summary", "description", "project"], "maxResults": 25}).get("issues", [])
    for issue in found:
        key = issue["key"]
        if key.split("-")[0] not in cfg["projects"]:
            continue
        comments = api(cfg, "GET", f"/rest/api/3/issue/{key}/comment?orderBy=-created&maxResults=20").get("comments", [])
        for c in comments:
            cid = str(c["id"])
            if cid in state["seen"] or cid in state["pending"]:
                continue
            text = adf_text(c.get("body"))
            if cfg["trigger"].lower() not in text.lower():
                continue
            if (c.get("author") or {}).get("accountId") != me:
                state["seen"].append(cid)     # someone else tagged it: ignored, on purpose
                log(f"{key}: ignored a mention by someone else")
                continue
            instruction = text.split(cfg["trigger"], 1)[-1] if cfg["trigger"] in text else text
            m = re.search(r"\brepo:\s*([A-Za-z0-9._-]+)", instruction)
            repo_name = m.group(1) if m else cfg["default_repo"].get(key.split("-")[0], "")
            instruction = re.sub(r"\brepo:\s*[A-Za-z0-9._-]+", "", instruction).strip()
            repo = os.path.expanduser(cfg["repos"].get(repo_name, ""))
            if not repo or not os.path.isdir(repo):
                log(f"{key}: no known repo ('{repo_name or 'none given'}'); add repo:<name> to the comment")
                notify("guild", f"{key}: which repo? Add repo:<name> to your comment")
                state["seen"].append(cid)
                continue
            item = {"key": key, "repo": repo, "slug": slug_for(key, issue["fields"].get("summary", "")),
                    "brief": build_brief(key, issue["fields"], instruction, cfg["site"])}
            if os.path.isdir(os.path.join(GUILD_HOME, "quests", item["slug"])):
                log(f"{key}: a quest for this ticket is already open ({item['slug']})")
                state["seen"].append(cid)
                continue
            if cfg["autostart"]:
                if active_started(state) >= cfg["max_active"]:
                    log(f"{key}: waiting, {cfg['max_active']} auto-started quests already open")
                    continue          # not marked seen, so it is picked up once a slot frees
                if start_quest(cfg, state, item):
                    state["seen"].append(cid)
            elif propose(cfg, state, cid, item):
                pass
    state["seen"] = state["seen"][-500:]
    save_state(state)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "once":
        return once(load_config())
    if cmd == "watch":
        cfg = load_config()
        log(f"watching {', '.join(cfg['projects'])} for {cfg['trigger']} every {cfg['poll_minutes']} min "
            f"({'autostart' if cfg['autostart'] else 'asks first'})")
        while True:
            try:
                once(cfg)
            except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                log(f"poll failed, will retry: {e}")
            time.sleep(float(cfg["poll_minutes"]) * 60)
    if cmd == "status":
        state = load_state()
        print(f"pending on the war table: {len(state['pending'])}")
        for cid, item in state["pending"].items():
            print(f"  {item['key']}  board {item['board']}")
        print(f"started by the watcher: {len(state['started'])}")
        for slug, info in state["started"].items():
            print(f"  {slug}  {info['key']}  {info['at']}")
        return
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
