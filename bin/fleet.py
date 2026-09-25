#!/usr/bin/env python3
"""Everything the guild is doing right now, in one place: quests, cockpit tabs, every
Claude session on this machine (with the subagents it is running), your Jira tickets and
your own to-dos. The campaign board and the sidebar's pinned list both read it.

  fleet.py json                 all cards, grouped by column, as JSON
  fleet.py pin|unpin <target>   pin a quest, a cockpit tab or a session (target: tab name or slug)
  fleet.py toggle <target>      pin it if it is not pinned, else unpin it
  fleet.py pins                 pinned items, one per line: key<TAB>name<TAB>state<TAB>tab
  fleet.py todo add <text> | done <n> | list

Sessions are read from Claude Code's own logs (~/.claude/projects/*/*.jsonl): their name,
what they are on, the model, and whether the turn is running or waiting on you.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
TABS = os.path.join(GUILD_HOME, "tabs")
PINS = os.path.join(GUILD_HOME, "pins.json")
TODO = os.path.join(GUILD_HOME, "todo.json")
JIRA_CACHE = os.path.join(GUILD_HOME, ".campaign-jira.json")
PROJECTS = os.environ.get("GUILD_CLAUDE_PROJECTS", os.path.expanduser("~/.claude/projects"))
SOCKET = os.environ.get("GUILD_TMUX_SOCKET", "guild")
REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

WORKING_SECONDS = 300      # a session that wrote in the last 5 minutes and has not ended its turn
SUBAGENT_SECONDS = 120     # a subagent log touched in the last 2 minutes is still running
SESSION_HOURS = 12         # idle sessions older than this leave the board
DONE_DAYS = 7

COLUMNS = [
    ("todo", "Quest board", "Posted, nobody on it yet"),
    ("road", "On the road", "Agents at work"),
    ("waiting", "Awaiting orders", "Your call, your turn, or stuck"),
    ("trial", "Trial", "Reviewed, waiting for the PR"),
    ("done", "Returned", "Finished in the last week"),
]
QUEST_COLUMN = {
    "working": "road", "checks-baseline": "road", "checks-green": "road", "checks-red": "road",
    "acceptance": "road", "message": "road", "planned": "road",
    "needs-decision": "waiting", "blocked": "waiting", "failed": "waiting", "stopped": "waiting",
    "trial-pass": "trial", "trial-skip": "trial", "done": "done",
}


def load_json(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    json.dump(data, open(tmp, "w"), indent=2)
    os.replace(tmp, path)


def windows():
    try:
        out = subprocess.run(["tmux", "-L", SOCKET, "list-windows", "-t", "guild", "-F", "#W"],
                             capture_output=True, text=True, timeout=5).stdout
        return set(out.split())
    except (OSError, subprocess.SubprocessError):
        return set()


def rank(model):
    """A rarity for the card's seal, from the model's weight class."""
    m = (model or "").lower()
    if "fable" in m:
        return "legendary"
    if "opus" in m or "thinking" in m or "gpt-5" in m:
        return "epic"
    if "sonnet" in m or "deepseek" in m:
        return "rare"
    if "haiku" in m or "flash" in m or "mini" in m:
        return "common"
    return ""


def short_model(model):
    m = model or ""
    m = re.sub(r"^claude-", "", m)
    return re.sub(r"-\d{8}$", "", m)


# ── Claude sessions ───────────────────────────────────────────────────────────

def tail_entries(path, size=262144):
    with open(path, "rb") as f:
        f.seek(0, 2)
        end = f.tell()
        f.seek(max(0, end - size))
        data = f.read().decode("utf-8", "replace")
    lines = data.splitlines()
    if end > size:
        lines = lines[1:]          # the first line is cut in half
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def text_of(message):
    content = (message or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def read_session(path):
    entries = tail_entries(path)
    s = {"id": os.path.splitext(os.path.basename(path))[0], "path": path, "name": "", "title": "",
         "prompt": "", "model": "", "cwd": "", "state": "idle", "entrypoint": "", "agents": []}
    last = None
    for e in entries:
        t = e.get("type")
        if t == "custom-title":
            s["name"] = e.get("customTitle", "")
        elif t == "ai-title":
            s["title"] = e.get("aiTitle", "")
        elif t == "last-prompt":
            s["prompt"] = e.get("lastPrompt", "")
        if e.get("cwd"):
            s["cwd"] = e["cwd"]
        if e.get("entrypoint"):
            s["entrypoint"] = e["entrypoint"]
        if t == "assistant" and not e.get("isSidechain"):
            s["model"] = (e.get("message") or {}).get("model", s["model"])
        if t in ("user", "assistant") and not e.get("isSidechain") and not e.get("isMeta"):
            last = e
            if t == "user" and text_of(e.get("message")).strip() and not s["prompt"]:
                s["prompt"] = text_of(e.get("message"))
        elif t == "system" and e.get("subtype") == "turn_duration":
            last = e
    age = time.time() - os.path.getmtime(path)
    s["age"] = age
    ended = last is None or last.get("type") == "system" or (
        last.get("type") == "assistant" and (last.get("message") or {}).get("stop_reason") == "end_turn")
    s["state"] = "idle" if ended or age > WORKING_SECONDS else "working"
    sub = os.path.join(os.path.dirname(path), s["id"], "subagents")
    for log in glob.glob(os.path.join(sub, "*.jsonl")):
        if time.time() - os.path.getmtime(log) > SUBAGENT_SECONDS:
            continue
        meta = load_json(log[:-len(".jsonl")] + ".meta.json", {})
        s["agents"].append({"type": meta.get("agentType", "agent"), "what": meta.get("description", "")})
    if s["agents"]:
        s["state"] = "working"
    return s


def sessions(hours=24):
    cutoff = time.time() - hours * 3600
    out = []
    for path in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        try:
            if os.path.getmtime(path) < cutoff:
                continue
            s = read_session(path)
        except OSError:
            continue
        if s["entrypoint"] and s["entrypoint"] != "cli":
            continue            # claude -p runs and SDK calls are tools, not sessions you talk to
        out.append(s)
    return out


def session_by_id(sid):
    for path in glob.glob(os.path.join(PROJECTS, "*", f"{sid}.jsonl")):
        try:
            return read_session(path)
        except OSError:
            return None
    return None


# ── quests, tabs, Jira, to-dos ────────────────────────────────────────────────

def quests():
    out = []
    if not os.path.isdir(QUESTS):
        return out
    for slug in sorted(os.listdir(QUESTS)):
        d = os.path.join(QUESTS, slug)
        meta = load_json(os.path.join(d, "meta.json"), None)
        if not meta or meta.get("pseudo"):
            continue
        try:
            state, note, since = (open(os.path.join(d, "status")).read().rstrip("\n").split("\t") + ["", "", ""])[:3]
        except OSError:
            continue
        meta.update(state=state, note=note, since=since, dir=d)
        boards = os.path.join(d, "boards")
        meta["open_boards"], meta["wrapup"] = [], ""
        if os.path.isdir(boards):
            for b in sorted(os.listdir(boards)):
                bj = load_json(os.path.join(boards, b, "board.json"), {})
                if bj.get("wrapup"):
                    meta["wrapup"] = b
                elif not os.path.exists(os.path.join(boards, b, "decision.json")):
                    meta["open_boards"].append(b)
        out.append(meta)
    return out


def archived(days=DONE_DAYS):
    out, cutoff = [], time.time() - days * 86400
    for d in glob.glob(os.path.join(QUESTS, "_archive", "*")):
        if os.path.getmtime(d) < cutoff:
            continue
        meta = load_json(os.path.join(d, "meta.json"), None)
        if meta and not meta.get("pseudo") and "/.guild-" not in meta.get("repo", ""):   # not guild's own smoke runs
            meta["closed"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(d)))
            out.append(meta)
    return out


def tabs():
    out = []
    for path in glob.glob(os.path.join(TABS, "*.json")):
        t = load_json(path, None)
        if t:
            out.append(t)
    return out


def jira(ttl=300):
    """Your open tickets, cached for five minutes. Empty when Jira is not set up."""
    cache = load_json(JIRA_CACHE, {})
    if cache and time.time() - cache.get("at", 0) < ttl:
        return cache.get("issues", []), cache.get("note", "")
    sys.path.insert(0, os.path.join(REPO, "bin"))
    try:
        import jira_watch
        cfg = jira_watch.load_config()
        found = jira_watch.api(cfg, "POST", "/rest/api/3/search/jql", {
            "jql": "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC",
            "maxResults": 30, "fields": ["summary", "status", "priority"]})
        issues = [{"key": i["key"], "summary": i["fields"].get("summary", ""),
                   "status": (i["fields"].get("status") or {}).get("name", ""),
                   "url": cfg["site"].rstrip("/") + "/browse/" + i["key"]} for i in found.get("issues", [])]
        note = ""
    except SystemExit as e:
        issues, note = [], str(e)
    except Exception as e:  # network down, token expired: the board still shows the rest
        issues, note = cache.get("issues", []), f"jira: {e}"
    save_json(JIRA_CACHE, {"at": time.time(), "issues": issues, "note": note})
    return issues, note


def todos():
    return load_json(TODO, [])


# ── pins ──────────────────────────────────────────────────────────────────────

def pins():
    return load_json(PINS, [])


def resolve(target):
    """A tab name or quest slug becomes a pin key that survives a restart."""
    if os.path.isfile(os.path.join(QUESTS, target, "meta.json")):
        return {"key": f"quest:{target}", "name": target}
    if target in ("qm", "quartermaster"):
        sid = open(os.path.join(GUILD_HOME, "qm-session")).read().strip() if os.path.exists(
            os.path.join(GUILD_HOME, "qm-session")) else ""
        return {"key": f"session:{sid}", "name": "quartermaster", "tab": "qm"} if sid else {"key": "tab:qm", "name": "qm"}
    for t in tabs():
        if t.get("name") == target and t.get("session"):
            return {"key": f"session:{t['session']}", "name": target, "tab": target}
    if re.fullmatch(r"[0-9a-f-]{36}", target):
        s = session_by_id(target)
        return {"key": f"session:{target}", "name": (s or {}).get("name") or target}
    return {"key": f"tab:{target}", "name": target, "tab": target}


def set_pin_key(key, name, tab, on):
    current = [p for p in pins() if p["key"] != key]
    if on:
        current.append({"key": key, "name": name, **({"tab": tab} if tab else {})})
    save_json(PINS, current)


def set_pin(target, on):
    item, current = resolve(target), pins()
    current = [p for p in current if p["key"] != item["key"]]
    if on:
        current.append(item)
    save_json(PINS, current)
    return item


# ── the board ─────────────────────────────────────────────────────────────────

def card(**kw):
    kw.setdefault("agents", [])
    kw.setdefault("links", [])
    kw.setdefault("rank", rank(kw.get("model")))
    kw["model"] = short_model(kw.get("model"))
    return kw


def board():
    pinned = {p["key"] for p in pins()}
    live = windows()
    qs, ss, ts = quests(), sessions(), tabs()
    qm_sid = open(os.path.join(GUILD_HOME, "qm-session")).read().strip() if os.path.exists(
        os.path.join(GUILD_HOME, "qm-session")) else ""
    tab_of = {t["session"]: t["name"] for t in ts if t.get("session")}
    cards, claimed = [], set()

    for q in qs:
        # the quest's own session: the newest one that ran in its worktree
        mine = [s for s in ss if (q.get("worktree") and s["cwd"].startswith(q["worktree"]))
                or s["cwd"].startswith(q["dir"])]
        for s in mine:
            claimed.add(s["id"])
        main = max(mine, key=lambda s: -s["age"], default=None)
        links = []
        if q["wrapup"]:
            links.append({"label": "wrap-up", "href": f"/b/{q['slug']}/{q['wrapup']}/"})
        for b in q["open_boards"]:
            links.append({"label": "decide", "href": f"/b/{q['slug']}/{b}/"})
        if re.match(r"https?://\S+/pull/\d+", q["note"] or ""):
            links.append({"label": "PR", "href": q["note"].split()[0]})
        cards.append(card(
            id=f"quest:{q['slug']}", kind="quest", column=QUEST_COLUMN.get(q["state"], "road"),
            title=q["slug"], ticket=q.get("ticket", ""), what=q["note"], state=q["state"],
            repo=os.path.basename(q.get("repo", "")), model=q.get("model") or (main or {}).get("model", ""),
            harness=q.get("harness", ""), phase=q.get("phase", ""), since=q["since"],
            agents=(main or {}).get("agents", []), links=links,
            tab=q["slug"] if q["slug"] in live else "", pinned=f"quest:{q['slug']}" in pinned))

    for s in ss:
        if s["id"] in claimed:
            continue
        is_qm = s["id"] == qm_sid
        tab = "qm" if is_qm else tab_of.get(s["id"], "")
        if tab and tab not in live:
            tab = ""
        key = f"session:{s['id']}"
        # a closed quest's session, or guild's own smoke runs, is history, not work
        if key not in pinned and not is_qm and ("/.guild-" in s["cwd"] or s["name"].startswith("quest:")):
            continue
        if s["state"] == "idle" and s["age"] > SESSION_HOURS * 3600 and key not in pinned:
            continue
        name = "quartermaster" if is_qm else (s["name"] or s["title"] or os.path.basename(s["cwd"]) or s["id"][:8])
        what = s["title"] if s["name"] and s["title"] != s["name"] else ""
        prompt = re.sub(r"\s+", " ", s["prompt"]).strip()
        cards.append(card(
            id=key, kind="session", column="road" if s["state"] == "working" else "waiting",
            title=name, what=what or prompt[:140], last=prompt[:140] if what else "",
            state="working" if s["state"] == "working" else "your turn",
            repo=os.path.basename(s["cwd"]), model=s["model"], agents=s["agents"],
            since=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - s["age"])),
            tab=tab, pinned=key in pinned, orchestrator=is_qm))

    quest_tickets = {q.get("ticket") for q in qs if q.get("ticket")}
    issues, jira_note = jira()
    for i in issues:
        if i["key"] in quest_tickets:
            continue
        cards.append(card(id=f"jira:{i['key']}", kind="jira", column="todo", title=i["key"], ticket=i["key"],
                          what=i["summary"], state=i["status"], links=[{"label": "Jira", "href": i["url"]}],
                          pinned=f"jira:{i['key']}" in pinned))
    for n, t in enumerate(todos(), 1):
        cards.append(card(id=f"todo:{n}", kind="todo", column="done" if t.get("done") else "todo",
                          title=t["text"], what="", state="done" if t.get("done") else "to do",
                          since=t.get("at", ""), n=n, pinned=False))
    for a in archived():
        cards.append(card(id=f"closed:{a['slug']}", kind="quest", column="done", title=a["slug"],
                          ticket=a.get("ticket", ""), what="closed", state="closed",
                          repo=os.path.basename(a.get("repo", "")), model=a.get("model", ""), since=a["closed"]))

    by_col = {k: [] for k, _, _ in COLUMNS}
    for c in cards:
        by_col[c["column"]].append(c)
    for k in by_col:      # pinned first, then the newest
        by_col[k].sort(key=lambda c: (0 if c.get("pinned") else 1, _neg(c.get("since", ""))))
    agents_live = sum(1 for c in cards if c["column"] == "road") + sum(len(c["agents"]) for c in cards)
    return {"columns": [{"key": k, "title": t, "hint": h, "cards": by_col[k]} for k, t, h in COLUMNS],
            "counts": {"agents": agents_live, "waiting": len(by_col["waiting"]), "todo": len(by_col["todo"])},
            "jira_note": jira_note, "at": time.strftime("%H:%M:%S")}


def _neg(since):
    """Sort key that puts the newest timestamp first."""
    return "".join(chr(0x10FFFF - ord(ch)) for ch in since)


def pin_rows():
    """key, name, state, tab for every pin, for the sidebar and the jump menu."""
    live, rows = windows(), []
    for p in pins():
        kind, _, ident = p["key"].partition(":")
        state, tab = "", p.get("tab", "")
        if kind == "quest":
            try:
                state = open(os.path.join(QUESTS, ident, "status")).read().split("\t")[0]
            except OSError:
                state = "closed"
            tab = ident
        elif kind == "session":
            s = session_by_id(ident)
            state = ("working" if s["state"] == "working" else "your turn") if s else "gone"
            if s and s["agents"]:
                state += f" +{len(s['agents'])}"
        rows.append({"key": p["key"], "name": p["name"], "state": state,
                     "tab": tab if tab in live else "", "open": tab in live})
    return rows


def main():
    cmd, rest = (sys.argv[1] if len(sys.argv) > 1 else "json"), sys.argv[2:]
    if cmd == "json":
        print(json.dumps(board(), indent=1))
    elif cmd in ("pin", "unpin", "toggle"):
        if not rest:
            raise SystemExit("usage: fleet.py pin|unpin|toggle <tab name or slug>")
        on = cmd == "pin" or (cmd == "toggle" and resolve(rest[0])["key"] not in {p["key"] for p in pins()})
        item = set_pin(rest[0], on)
        print(f"{'pinned' if on else 'unpinned'} {item['name']}")
    elif cmd == "pins":
        for r in pin_rows():
            print("\t".join([r["key"], r["name"], r["state"], r["tab"]]))
    elif cmd == "todo":
        items = todos()
        sub = rest[0] if rest else "list"
        if sub == "add" and len(rest) > 1:
            items.append({"text": " ".join(rest[1:]), "done": False, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
            save_json(TODO, items)
            print(f"to-do {len(items)} added")
        elif sub in ("done", "drop") and len(rest) > 1 and rest[1].isdigit() and 0 < int(rest[1]) <= len(items):
            n = int(rest[1]) - 1
            if sub == "done":
                items[n]["done"] = True
            else:
                items.pop(n)
            save_json(TODO, items)
            print(f"to-do {rest[1]} {sub}")
        elif sub == "list":
            for n, t in enumerate(items, 1):
                print(f"{n:>3}  {'[x]' if t.get('done') else '[ ]'} {t['text']}")
        else:
            raise SystemExit("usage: guild todo [list] | add <text> | done <n> | drop <n>")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
