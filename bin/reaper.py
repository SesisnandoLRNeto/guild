#!/usr/bin/env python3
"""Stop what finished quests leave running, so memory stays free.

  reaper.py run [--dry-run]   reap every finished quest that has been idle past the grace period
  reaper.py maybe             the same, at most every 5 minutes (the war table server calls this)

A quest in done, failed or stopped (or closed in the last week) for GUILD_REAP_AFTER minutes
(default 30) is reaped:
- its tmux window is killed and the quest is marked paused (guild revive <slug> brings it back);
- stray processes tied to its worktree or scratch folders are stopped by exact PID (TERM, then KILL);
- its s<ticket>-* docker containers are stopped, when every quest of that ticket is finished.

Never: guild close, deleting a worktree or a board, a pkill by name. A quest that looks busy
(a recent session log, a tool call in flight, a running command, a hot process) is skipped and
tried again at the next run. A folder owned by a quest that is still active is never touched.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
ARCHIVE = os.path.join(QUESTS, "_archive")
EVENTS = os.path.join(GUILD_HOME, "events.log")
STAMP = os.path.join(GUILD_HOME, ".reap-at")
SOCKET = os.environ.get("GUILD_TMUX_SOCKET", "guild")
SESSION = "guild"
PROJECTS = os.path.expanduser("~/.claude/projects")
FINISHED = ("done", "failed", "stopped")
EVERY_MINUTES = 5
CLOSED_DAYS = 7
BUSY_CPU = 5.0
SCRATCH_ROOTS = ("/private/tmp", "/tmp")
SCRATCH_RE = re.compile(r"(?:/private)?/tmp/(?:claude-\d+/)?[A-Za-z0-9][A-Za-z0-9._-]*")


def grace_minutes():
    try:
        return float(os.environ.get("GUILD_REAP_AFTER", "30"))
    except ValueError:
        return 30.0


def sh(cmd, timeout=20):
    try:
        env = dict(os.environ, LC_ALL="C")        # ps prints "0,6" for cpu in some locales
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def tmux(*args):
    return sh(["tmux", "-L", SOCKET, *args])


def real(path):
    return os.path.realpath(path) if path else ""


def inside(path, folders):
    path = real(path)
    return any(path == f or path.startswith(f + "/") for f in folders)


# ── quests ────────────────────────────────────────────────────────────────────

def read_quest(d, closed=False):
    try:
        meta = json.load(open(os.path.join(d, "meta.json")))
        fields = (open(os.path.join(d, "status")).read().rstrip("\n").split("\t") + ["", "", ""])[:3]
    except (OSError, ValueError):
        return None
    state, since = fields[0], fields[2]
    if closed:
        tail = os.path.basename(d.rstrip("/")).rsplit("-", 1)[-1]
        try:
            since = datetime.strptime(tail, "%Y%m%d%H%M%S").isoformat()
        except ValueError:
            return None
        state = "closed"
    try:
        since_dt = datetime.fromisoformat(since)
    except ValueError:
        since_dt = None
    try:                                          # woken by hand: the idle clock starts again
        woken = datetime.fromisoformat(open(os.path.join(d, "revived")).read().strip())
        since_dt = max(since_dt, woken) if since_dt else woken
    except (OSError, ValueError):
        pass
    return {"slug": meta["slug"], "dir": d, "meta": meta, "state": state, "since": since_dt, "closed": closed}


def all_quests():
    out = []
    if os.path.isdir(QUESTS):
        for name in sorted(os.listdir(QUESTS)):
            if name != "_archive" and os.path.exists(os.path.join(QUESTS, name, "meta.json")):
                q = read_quest(os.path.join(QUESTS, name))
                if q:
                    out.append(q)
    if os.path.isdir(ARCHIVE):
        for name in sorted(os.listdir(ARCHIVE)):
            if os.path.exists(os.path.join(ARCHIVE, name, "meta.json")):
                q = read_quest(os.path.join(ARCHIVE, name), closed=True)
                if q:
                    out.append(q)
    return out


def is_finished(q):
    return q["state"] in FINISHED or q["closed"]


def project_dir(path):
    return os.path.join(PROJECTS, path.replace("/", "-").replace(".", "-"))


def utc(local):
    try:
        return datetime.fromisoformat(local).astimezone().astimezone(
            timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return ""


def session_logs(q):
    d = project_dir(q["meta"].get("worktree", ""))
    if not q["meta"].get("worktree") or not os.path.isdir(d):
        return []
    return sorted((os.path.join(d, n) for n in os.listdir(d) if n.endswith(".jsonl")), key=os.path.getmtime)


def folders_of(q):
    """The folders a quest owns: its worktree, Claude's scratch folder for it, and every scratch
    folder its own session logs name (that is how /private/tmp/claude-501/stack1245 is found)."""
    wt = q["meta"].get("worktree", "")
    out = set()
    if wt:
        out.add(real(wt))
        for root in SCRATCH_ROOTS:
            out.add(real(os.path.join(root, f"claude-{os.getuid()}", wt.replace("/", "-").replace(".", "-"))))
    since = utc(q["meta"].get("created", ""))
    until = ""
    if q["closed"] and q["since"]:
        until = utc(q["since"].isoformat())
    for log in session_logs(q):
        for line in open(log, errors="ignore"):
            if "/tmp/" not in line:
                continue
            try:
                stamp = json.loads(line).get("timestamp") or ""
            except ValueError:
                continue
            if since and (not stamp or stamp[:19] < since):
                continue
            if until and stamp[:19] > until:
                continue
            for m in SCRATCH_RE.findall(line):
                name = m.rsplit("/", 1)[-1]
                if name.startswith("claude-") or name.startswith("-"):
                    continue                      # claude's own task folders, not a place a quest worked
                out.add(real(m))
    out.discard("")
    return out


# ── processes ─────────────────────────────────────────────────────────────────

def process_table():
    """{pid: {ppid, cpu, command}} for the whole machine."""
    table = {}
    for line in sh(["ps", "-axo", "pid=,ppid=,%cpu=,command="]).splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            table[int(parts[0])] = {"ppid": int(parts[1]), "cpu": float(parts[2]), "command": parts[3]}
        except ValueError:
            continue
    return table


def cwd_table():
    """{pid: cwd}, from one lsof for every process."""
    out, pid = {}, None
    for line in sh(["lsof", "-d", "cwd", "-Fpn"], timeout=30).splitlines():
        if line.startswith("p"):
            pid = int(line[1:]) if line[1:].isdigit() else None
        elif line.startswith("n") and pid:
            out[pid] = line[1:]
    return out


def descendants(table, roots):
    found, todo = set(), list(roots)
    while todo:
        p = todo.pop()
        for pid, info in table.items():
            if info["ppid"] == p and pid not in found:
                found.add(pid)
                todo.append(pid)
    return found


def ancestors(table, pid):
    found = set()
    while pid in table and pid not in found:
        found.add(pid)
        pid = table[pid]["ppid"]
    return found


def paths_in(command):
    return re.findall(r"/[^\s:;\"']+", command)


def window_pids(slug):
    """Pane pids of the quest's tmux window, and its window id."""
    for line in tmux("list-windows", "-t", SESSION, "-F", "#{window_id}\t#{window_name}").splitlines():
        wid, _, name = line.partition("\t")
        if name == slug:
            panes = tmux("list-panes", "-t", wid, "-F", "#{pane_pid}").split()
            return wid, [int(p) for p in panes if p.isdigit()]
    return None, []


def is_protected_process(info):
    first = os.path.basename(info["command"].split()[0]) if info["command"].split() else ""
    return first.startswith("tmux") or "wartable.py" in info["command"] or "bin/watch.py" in info["command"]


def pane_busy(table, panes):
    """A command in flight in the window: a shell started with -c below the pane (how an agent runs
    a command or a background wait), or a hot process."""
    for pid in descendants(table, panes):
        info = table[pid]
        words = info["command"].split()
        if words and os.path.basename(words[0]) in ("sh", "bash", "zsh") and "-c" in words[1:]:
            return f"a command is running in its window (pid {pid})"
    return ""


def log_busy(q, has_window):
    """The agent is still working after its report: a fresh session log, or a tool call with no result."""
    logs = session_logs(q)
    if not logs:
        return ""
    newest = logs[-1]
    if time.time() - os.path.getmtime(newest) < grace_minutes() * 60:
        return "its session log changed in the last %d minutes" % grace_minutes()
    try:
        with open(newest, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400_000))
            tail = f.read().decode(errors="ignore").splitlines()[1:]
    except OSError:
        return ""
    used, answered = set(), set()
    for line in tail:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        content = (row.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                used.add(block.get("id"))
            elif block.get("type") == "tool_result":
                answered.add(block.get("tool_use_id"))      # a result can be logged before its call
    pending = used - answered
    return "a tool call in its session has no result yet" if pending and has_window else ""


# ── containers ────────────────────────────────────────────────────────────────

def ticket_number(q):
    digits = re.sub(r"\D", "", q["meta"].get("ticket") or "")
    return digits


def running_containers():
    return [n for n in sh(["docker", "ps", "--format", "{{.Names}}"], timeout=20).split() if n]


# ── the reap ──────────────────────────────────────────────────────────────────

def plan(now=None):
    """Everything a reap would do now: [{slug, actions: [...], skipped: str}]."""
    now = now or datetime.now()
    grace = timedelta(minutes=grace_minutes())
    quests = all_quests()
    protected = set()
    for q in quests:
        if not is_finished(q) and not q["meta"].get("pseudo"):
            protected |= folders_of(q)
    active_tickets = {ticket_number(q) for q in quests if not is_finished(q) and ticket_number(q)}
    unfinished_slugs = {q["slug"] for q in quests if not is_finished(q) and not q["closed"]}
    table, cwds = process_table(), cwd_table()
    me = ancestors(table, os.getpid())
    containers = running_containers()
    out, claimed = [], set()
    for q in quests:
        if not is_finished(q) or q["meta"].get("pseudo") or not q["since"]:
            continue
        if q["closed"] and q["since"] < now - timedelta(days=CLOSED_DAYS):
            continue
        if q["meta"].get("parent") in unfinished_slugs:
            continue
        if now - q["since"] < grace:
            continue
        slug = q["slug"]
        item = {"slug": slug, "closed": q["closed"], "dir": q["dir"], "actions": [], "skipped": ""}
        wid, panes = window_pids(slug)
        busy = log_busy(q, bool(wid)) if not q["closed"] else ""
        busy = busy or (pane_busy(table, panes) if panes else "")
        if busy:
            item["skipped"] = busy
            out.append(item)
            continue
        if wid and not q["closed"]:
            item["actions"].append({"kind": "window", "id": wid, "text": f"closed its window ({slug}), revivable"})
        folders = folders_of(q) - protected
        window_tree = descendants(table, panes) | set(panes)
        for pid, info in sorted(table.items()):
            if pid in me or pid in claimed or is_protected_process(info):
                continue
            cwd, where = cwds.get(pid, ""), ""
            if inside(cwd, protected):
                continue
            if inside(cwd, folders):
                where = f"cwd {cwd}"
            else:
                hit = [p for p in paths_in(info["command"]) if inside(p, folders)]
                if hit and not any(inside(p, protected) for p in paths_in(info["command"])):
                    where = f"path {hit[0]}"
            if not where:
                continue
            if info["ppid"] != 1 and pid not in window_tree:
                continue                          # your own terminal, not something the quest left behind
            if info["cpu"] > BUSY_CPU:
                item["actions"].append({"kind": "busy", "text": f"left pid {pid} alone, it is busy "
                                        f"({info['cpu']:.0f}% cpu), will retry"})
                continue
            claimed.add(pid)
            name = os.path.basename(info["command"].split()[0])
            item["actions"].append({"kind": "process", "pid": pid, "command": info["command"],
                                    "text": f"stopped {name} (pid {pid}), {where}"})
        num = ticket_number(q)
        if num and num not in active_tickets:
            for c in containers:
                if c.startswith(f"s{num}-"):
                    item["actions"].append({"kind": "container", "name": c, "text": f"stopped container {c}"})
        out.append(item)
    return out


def alive(pid, command):
    return sh(["ps", "-p", str(pid), "-o", "command="]).strip() == command


def apply(item, dry):
    done = []
    kills = [a for a in item["actions"] if a["kind"] == "process"]
    for a in item["actions"]:
        if a["kind"] == "busy":
            done.append(a["text"])
    for a in item["actions"]:
        if a["kind"] == "window":
            if not dry:
                tmux("kill-window", "-t", a["id"])
                try:
                    open(os.path.join(item["dir"], "paused"), "w").write(time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
                except OSError:
                    pass
            done.append(a["text"])
    if kills and not dry:
        for a in kills:
            if alive(a["pid"], a["command"]):
                try:
                    os.kill(a["pid"], 15)
                except OSError:
                    pass
        deadline = time.time() + 5
        while time.time() < deadline and any(alive(a["pid"], a["command"]) for a in kills):
            time.sleep(0.25)
        for a in kills:
            if alive(a["pid"], a["command"]):      # same pid, same command: still ours
                try:
                    os.kill(a["pid"], 9)
                except OSError:
                    pass
    for a in kills:
        done.append(a["text"])
    for a in item["actions"]:
        if a["kind"] == "container":
            if not dry:
                sh(["docker", "stop", a["name"]], timeout=60)
            done.append(a["text"])
    return done


def log_event(slug, text):
    try:
        with open(EVENTS, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\t{slug}\treaped\t{text}\n")
    except OSError:
        pass


def run(dry=False):
    items = plan()
    lines = 0
    for item in items:
        if item["skipped"]:
            print(f"{item['slug']}: skipped, {item['skipped']}")
            lines += 1
            continue
        done = apply(item, dry)
        for text in done:
            print(f"{item['slug']}: {'would have ' if dry else ''}{text}" if False else
                  f"{item['slug']}: {'would have ' + text if dry else text}")
            lines += 1
        real_actions = [a for a in item["actions"] if a["kind"] != "busy"]
        if real_actions and not dry:
            log_event(item["slug"], "; ".join(a["text"] for a in real_actions)[:300])
    if not lines:
        print("nothing to reap")
    if not dry:
        open(STAMP, "w").write(time.strftime("%Y-%m-%dT%H:%M:%S"))


def maybe():
    try:
        if json.load(open(os.path.join(GUILD_HOME, "local", "dispatch.json"))).get("auto_reap") is False:
            return
    except (OSError, ValueError):
        pass
    try:
        last = datetime.fromisoformat(open(STAMP).read().strip())
    except (OSError, ValueError):
        last = None
    if last and datetime.now() - last < timedelta(minutes=EVERY_MINUTES):
        return
    run()


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["run"])[0]
    if cmd == "run":
        run("--dry-run" in sys.argv)
    elif cmd == "maybe":
        maybe()
    else:
        raise SystemExit(__doc__)
