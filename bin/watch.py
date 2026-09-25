#!/usr/bin/env python3
"""The cockpit sidebar: every quest grouped by repo, plus the last events.

It also marks the tmux tab of any quest that wants the guildmaster, by setting the
window option @guildstate that config/guild.tmux.conf prints after the window name.
Window names stay exactly the quest slug, so `guild peek` and `guild send` keep working.
"""
import json
import re
import os
import shutil
import subprocess
import sys
import time

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
EVENTS = os.path.join(GUILD_HOME, "events.log")
SOCKET = os.environ.get("GUILD_TMUX_SOCKET", "guild")
SESSION = "guild"

# Catppuccin Mocha, the palette claude-deck uses, so the cockpit reads as one tool.
def rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return f"\033[38;2;{int(h[0:2], 16)};{int(h[2:4], 16)};{int(h[4:6], 16)}m"


TEXT, SUBTEXT, OVERLAY, BORDER = rgb("#cdd6f4"), rgb("#a6adc8"), rgb("#6c7086"), rgb("#585b70")
BLUE, GREEN, YELLOW, RED, MAUVE, PEACH = (rgb(c) for c in ("#89b4fa", "#a6e3a1", "#f9e2af", "#f38ba8", "#cba6f7", "#fab387"))
DIM, RESET, BOLD = OVERLAY, "\033[0m", "\033[1m"
COLORS = {
    "working": BLUE, "needs-decision": YELLOW, "blocked": RED,
    "failed": RED, "stopped": MAUVE, "done": GREEN, "your turn": YELLOW,
    "checks-green": GREEN, "checks-red": RED, "trial-pass": GREEN, "planned": BLUE,
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


def pinned():
    """Pinned quests and sessions, from fleet.py, which reads the session logs."""
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    try:
        import fleet
        return fleet.pin_rows()
    except Exception:
        return []


ANSI = re.compile(r"\033\[[0-9;]*m")


def visible(text):
    return len(ANSI.sub("", text))


def fit(line, width):
    """Clip a line to a width by visible characters, keeping its colors intact."""
    out, seen, i = [], 0, 0
    while i < len(line):
        m = ANSI.match(line, i)
        if m:
            out.append(m.group(0)); i = m.end(); continue
        if seen >= width:
            break
        out.append(line[i]); seen += 1; i += 1
    return "".join(out) + RESET


def pad(line, width):
    line = fit(line, width)
    return line + " " * max(0, width - visible(line))


# Short words for a narrow sidebar. Colors still carry the state at a glance.
SHORT_STATE = {"checks-baseline": "baseline", "checks-green": "green", "checks-red": "red",
               "needs-decision": "decide", "trial-pass": "trial ok", "trial-skip": "trial skip",
               "acceptance": "resealed", "message": "msg"}


def short_slug(slug):
    """The part that tells quests apart: a ticket prefix like sara-838, else the first word or two."""
    m = re.match(r"^([a-z]+-\d+)", slug)
    return m.group(1) if m else slug[:12]


def short_note(note):
    """Events carry full paths and launch details; the sidebar wants a few words."""
    m = re.match(r"launched \((\S+)(?: ([^)]+))?\)", note)
    if m:
        return "launched · " + (m.group(2) or m.group(1))
    note = re.sub(r"(/[^\s]+)+/([^/\s]+)", r"\2", note)       # a path becomes its last part
    note = re.sub(r"http://127\.0\.0\.1:\d+/\S+", "board", note)
    return note.replace("turn ended without a report; peek to see why", "stopped without a report")


def activity(width, limit=8, hours=24):
    """(line, quest) per event, newest first, last day only."""
    try:
        rows = open(EVENTS).read().splitlines()
    except OSError:
        return [(f"{DIM}nothing yet{RESET}", None)]
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - hours * 3600))
    out = []
    for row in reversed(rows):
        parts = row.split("\t")
        if len(parts) < 4 or parts[0] < cutoff:
            continue
        when, slug, state, note = parts[0][11:16], short_slug(parts[1]), parts[2], short_note(parts[3])
        word = SHORT_STATE.get(state, state)
        room = width - len(f"{when} {slug} {word}") - 1
        tail = f" {DIM}{note[:room]}{RESET}" if note and room > 6 and state != "closed" else ""
        out.append((f"{DIM}{when}{RESET} {TEXT}{slug}{RESET} {COLORS.get(state, SUBTEXT)}{word}{RESET}{tail}", parts[1]))
        if len(out) >= limit:
            break
    return out or [(f"{DIM}quiet for the last {hours}h{RESET}", None)]


def panel(title, rows, width, accent=BORDER):
    """A claude-deck style box: rows are (text, action). Returns (line, action) pairs."""
    inner = width - 4
    head = f"{accent}┌─ {BOLD}{TEXT}{title}{RESET}{accent} " + "─" * max(0, width - len(title) - 5) + f"┐{RESET}"
    out = [(head, None)]
    for text, action in rows:
        out.append((f"{accent}│{RESET} {pad(text, inner)} {accent}│{RESET}", action))
    out.append((f"{accent}└" + "─" * (width - 2) + f"┘{RESET}", None))
    return out


BUTTONS = [("+claude", ("new",), GREEN), ("+term", ("term",), BLUE), ("board", ("campaign",), PEACH),
           ("pins", ("pins",), MAUVE)]


def buttons(width):
    """One row of clickable buttons; each knows its own column span."""
    line, spans, col = "", [], 1
    gap = 1 if sum(len(b[0]) + 3 for b in BUTTONS) <= width else 0     # squeeze on a narrow sidebar
    for label, action, color in BUTTONS:
        chunk = f"[{label}]"
        if col + len(chunk) - 1 > width:
            break
        spans.append((col, col + len(chunk) - 1, action))
        line += f"{color}{chunk}{RESET}" + " " * gap
        col += len(chunk) + gap
    return line, spans


def draw(quests, width, height, spend=None, pins=None):
    """Every line of the sidebar with what a click on it does."""
    out = []
    if pins:
        rows = []
        for r in pins:
            state = r["state"]
            color = COLORS.get(state.split(" +")[0], SUBTEXT)
            where = "" if r["open"] else f" {DIM}(closed){RESET}"
            rows.append((f"{color}●{RESET} {TEXT}{r['name']}{RESET}{where}", ("pin", r["key"], r["tab"])))
            rows.append((f"  {DIM}{SHORT_STATE.get(state, state)}{RESET}", ("pin", r["key"], r["tab"])))
        out += panel("Pinned", rows, width, MAUVE)
    by_repo = {}
    for q in quests:
        by_repo.setdefault(os.path.basename(q["repo"]), []).append(q)
    rows = [] if by_repo else [(f"{DIM}no quests yet{RESET}", None)]
    for repo, items in sorted(by_repo.items()):
        rows.append((f"{SUBTEXT}{BOLD}{repo}{RESET}", None))
        for q in items:
            color = COLORS.get(q["state"], SUBTEXT)
            board = f" {YELLOW}[board]{RESET}" if q["boards"] else ""
            target = ("board",) if q.get("pseudo") else ("quest", q["slug"])     # the quartermaster's own boards
            rows.append((f"{color}●{RESET} {TEXT}{q['slug']}{RESET}{board}", target))
            price = (spend or {}).get(q["slug"])
            parts = [SHORT_STATE.get(q["state"], q["state"])] + ([money(price)] if price else [])
            model = q.get("model") or q.get("harness", "")
            if model and len(" · ".join(parts + [model])) <= width - 8:
                parts.append(model)                  # the model only when there is room for it
            rows.append((f"  {DIM}{' · '.join(parts)}{RESET}", target))
    out += panel("Fleet", rows, width, BLUE)
    room = height - len(out) - 4                      # activity box borders + buttons + hint
    if room > 1:
        out += panel("Activity", [(t, ("quest", slug) if slug else None) for t, slug in activity(width - 4, limit=room)], width)
    return out


def act(action):
    """What a click in the sidebar does. Everything goes through tmux or the guild CLI."""
    guild = os.path.join(os.path.dirname(os.path.realpath(__file__)), "guild")
    tmux = ["tmux", "-L", SOCKET]
    kind = action[0]
    if kind == "quest":
        slug = action[1]
        if subprocess.run(tmux + ["select-window", "-t", f"{SESSION}:{slug}"], capture_output=True).returncode:
            subprocess.run([guild, "revive", slug], capture_output=True)
            subprocess.run(tmux + ["select-window", "-t", f"{SESSION}:{slug}"], capture_output=True)
    elif kind == "pin":
        key, tab = action[1], action[2]
        if tab:
            subprocess.run(tmux + ["select-window", "-t", f"{SESSION}:{tab}"], capture_output=True)
        elif key.startswith("session:"):
            subprocess.run([guild, "new", "--resume", key.split(":", 1)[1]], capture_output=True)
        elif key.startswith("quest:"):
            act(("quest", key.split(":", 1)[1]))
    elif kind == "new":
        subprocess.run([guild, "new"], capture_output=True)
    elif kind == "term":
        subprocess.run(tmux + ["new-window", "-t", SESSION, "-n", "shell", "-c", os.environ.get("GUILD_EDIT_ROOT", os.path.expanduser("~/Workspace"))], capture_output=True)
    elif kind == "board":
        subprocess.run(["sh", "-c", f"'{guild}' board url | head -1 | xargs open"], capture_output=True)
    elif kind == "campaign":
        subprocess.run([guild, "campaign"], capture_output=True)
    elif kind == "pins":
        subprocess.run(tmux + ["select-pane", "-t", f"{SESSION}:qm.1"], capture_output=True)
        subprocess.run([guild, "pins", "menu"], capture_output=True)


MOUSE = re.compile(r"\033\[<(\d+);(\d+);(\d+)([mM])")


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


def render(width, height):
    quests = read_quests()
    mark_tabs(quests)
    lines = draw(quests, width, height, costs(), pinned())[:max(0, height - 2)]
    bar, spans = buttons(width)
    hint = f"{DIM}click to jump · ^g ? for keys{RESET}"
    return lines, bar, spans, hint


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--count":
        print(count_line())
        return
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    interactive = sys.stdin.isatty()
    saved = None
    if interactive:                       # clicks arrive as SGR mouse reports on stdin
        import termios, tty
        saved = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        sys.stdout.write("\033[?1000h\033[?1006h\033[?25l")
    try:
        buf = ""
        while True:
            # the pane's real size, read every tick, so a resize never makes lines wrap
            size = shutil.get_terminal_size((30, 20))
            width, height = size.columns, size.lines
            lines, bar, spans, hint = render(width, height)
            body = [pad(l, width) for l, _ in lines]
            body += [""] * max(0, height - 2 - len(body))
            sys.stdout.write("\033[H" + "\n".join(body + [pad(bar, width), pad(hint, width)]) + "\033[J")
            sys.stdout.flush()
            if not interactive:
                time.sleep(interval)
                continue
            import select
            deadline = time.time() + interval
            while time.time() < deadline:
                ready, _, _ = select.select([sys.stdin], [], [], max(0.0, deadline - time.time()))
                if not ready:
                    break
                buf += os.read(sys.stdin.fileno(), 1024).decode("utf-8", "replace")
                clicked = False
                for m in MOUSE.finditer(buf):
                    button, x, y, kind = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
                    if kind != "M" or button != 0:          # left press only; no wheel, no release
                        continue
                    if y == height - 1:
                        for a, b, action in spans:
                            if a <= x <= b:
                                act(action); clicked = True
                    elif 1 <= y <= len(lines) and lines[y - 1][1]:
                        act(lines[y - 1][1]); clicked = True
                buf = buf[buf.rfind("\033"):] if "\033" in buf and not buf.endswith(("M", "m")) else ""
                if clicked:
                    break                                 # redraw at once
    finally:
        if saved is not None:
            import termios
            sys.stdout.write("\033[?1000l\033[?1006l\033[?25h")
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
