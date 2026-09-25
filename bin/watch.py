#!/usr/bin/env python3
"""The cockpit sidebar: every quest grouped by repo, plus the last events.

It also marks the tmux tab of any quest that wants the guildmaster, by setting the
window option @guildstate that config/guild.tmux.conf prints after the window name.
Window names stay exactly the quest slug, so `guild peek` and `guild send` keep working.
"""
import json
import re
import os
import subprocess
import sys
import time

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
EVENTS = os.path.join(GUILD_HOME, "events.log")
SOCKET = os.environ.get("GUILD_TMUX_SOCKET", "guild")
SESSION = "guild"

DIM, RESET, BOLD = "\033[38;5;245m", "\033[0m", "\033[1m"
COLORS = {
    "working": "\033[38;5;111m", "needs-decision": "\033[38;5;179m", "blocked": "\033[38;5;174m",
    "failed": "\033[38;5;174m", "stopped": "\033[38;5;176m", "done": "\033[38;5;114m",
}
# What a tab shows next to its name. Quiet states get no mark at all.
MARKS = {"needs-decision": "*", "blocked": "!", "failed": "!", "stopped": "?", "done": "+"}


def costs():
    """{slug: dollars} from the ledger, which keeps its own cache."""
    repo = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    try:
        out = subprocess.run([sys.executable, os.path.join(repo, "bin", "ledger.py"), "costs"],
                             capture_output=True, text=True, timeout=20).stdout
        return json.loads(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def money(c):
    return f"${c:,.2f}" if c >= 1 else f"${c:.3f}"


def read_quests():
    out = []
    if not os.path.isdir(QUESTS):
        return out
    for slug in sorted(os.listdir(QUESTS)):
        d = os.path.join(QUESTS, slug)
        try:
            meta = json.load(open(os.path.join(d, "meta.json")))
            parts = (open(os.path.join(d, "status")).read().rstrip("\n").split("\t") + ["", "", ""])[:3]
        except (OSError, ValueError):
            continue
        meta["state"], meta["note"], meta["since"] = parts
        meta["boards"] = sum(
            1 for b in os.listdir(os.path.join(d, "boards"))
            if not os.path.exists(os.path.join(d, "boards", b, "decision.json"))
        ) if os.path.isdir(os.path.join(d, "boards")) else 0
        out.append(meta)
    return out


def mark_tabs(quests):
    for q in quests:
        mark = MARKS.get(q["state"], "")
        subprocess.run(["tmux", "-L", SOCKET, "set-window-option", "-t", f"{SESSION}:{q['slug']}",
                        "@guildstate", mark], capture_output=True)


def draw(quests, width, spend=None):
    lines = [f"{BOLD}fleet{RESET}", ""]
    by_repo = {}
    for q in quests:
        by_repo.setdefault(os.path.basename(q["repo"]), []).append(q)
    if not by_repo:
        lines.append(f"{DIM}no quests yet{RESET}")
    for repo, items in sorted(by_repo.items()):
        lines.append(f" {BOLD}{repo[:width - 2]}{RESET}")
        for q in items:
            color = COLORS.get(q["state"], DIM)
            board = f" {COLORS['needs-decision']}[board]{RESET}" if q["boards"] else ""
            lines.append(f"  {color}●{RESET} {q['slug'][:width - 6]}{board}")
            model = q.get("model") or q.get("harness", "")
            price = (spend or {}).get(q["slug"])
            tail = f" · {money(price)}" if price else ""
            lines.append(f"    {DIM}{model} · {q['state']}{tail}{RESET}")
    lines += ["", f"{BOLD}activity{RESET}"]
    lines += activity(width)
    return lines


def short_note(note):
    """Events carry full paths and launch details; the sidebar wants a few words."""
    m = re.match(r"launched \((\S+)(?: ([^)]+))?\)", note)
    if m:
        return "launched · " + (m.group(2) or m.group(1))
    note = re.sub(r"(/[^\s]+)+/([^/\s]+)", r"\2", note)       # a path becomes its last part
    note = re.sub(r"http://127\.0\.0\.1:\d+/\S+", "board", note)
    return note.replace("turn ended without a report; peek to see why", "stopped without a report")


def activity(width, limit=8, hours=24):
    """One line per event, newest first, last day only: time, quest, what happened."""
    try:
        rows = open(EVENTS).read().splitlines()
    except OSError:
        return [f" {DIM}nothing yet{RESET}"]
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - hours * 3600))
    out = []
    for row in reversed(rows):
        parts = row.split("\t")
        if len(parts) < 4 or parts[0] < cutoff:
            continue
        when, slug, state, note = parts[0][11:16], parts[1], parts[2], short_note(parts[3])
        color = COLORS.get(state, DIM)
        head = f"{when} {slug}"
        room = max(0, width - len(head) - len(state) - 3)
        tail = f" {DIM}{note[:room]}{RESET}" if note and room > 4 and state not in ("closed",) else ""
        out.append(f" {DIM}{when}{RESET} {slug[:max(6, width - 20)]} {color}{state}{RESET}{tail}"[: width * 3])
        if len(out) >= limit:
            break
    return out or [f" {DIM}quiet for the last {hours}h{RESET}"]


def count_line():
    """One line for the tmux status bar on the right."""
    quests = read_quests()
    live = sum(1 for q in quests if q["state"] in ("working", "stopped"))
    waiting = sum(1 for q in quests if q["state"] in ("needs-decision", "blocked", "failed"))
    boards = sum(q["boards"] for q in quests)
    spent = sum(costs().values())
    parts = [f"{live} working"]
    if waiting:
        parts.append(f"{waiting} waiting on you")
    if boards:
        parts.append(f"{boards} board{'s' if boards > 1 else ''}")
    if spent:
        parts.append(money(spent))
    return " · ".join(parts)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--count":
        print(count_line())
        return
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    while True:
        width = int(os.environ.get("COLUMNS") or subprocess.run(
            ["tput", "cols"], capture_output=True, text=True).stdout.strip() or 30)
        quests = read_quests()
        mark_tabs(quests)
        spend = costs()
        sys.stdout.write("\033[H\033[2J" + "\n".join(draw(quests, width, spend)) + "\n")
        sys.stdout.flush()
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
