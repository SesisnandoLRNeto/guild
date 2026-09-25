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


# ── the look: claude-deck's, one surface, thin panels, titles in the border ──
def bg(hexcolor):
    h = hexcolor.lstrip("#")
    return f"\033[48;2;{int(h[0:2], 16)};{int(h[2:4], 16)};{int(h[4:6], 16)}m"


BASE_BG, SURFACE_BG, SELECT_BG = bg("#1e1e2e"), bg("#313244"), bg("#45475a")
DARK = rgb("#1e1e2e")
CHIP_COLORS = ["#89b4fa", "#cba6f7", "#94e2d5", "#fab387", "#f5c2e7", "#a6e3a1"]
COMMON = {"api", "service", "app", "backend", "frontend", "web", "the"}


def chip(repo):
    """A short colored tag per repo, like the deck's account chip: crowdgen-project-api -> proj."""
    if repo == "qm":
        return f"{bg('#f9e2af')}{DARK} qm   {RESET}"
    words = [w for w in re.split(r"[-_ .]+", repo.lower()) if w and w not in COMMON]
    if len(words) > 1:
        words = words[1:]                 # the org prefix (crowdgen-) says nothing between repos
    tag = (words[0] if words else repo)[:4]
    color = CHIP_COLORS[sum(map(ord, repo)) % len(CHIP_COLORS)]
    return f"{bg(color)}{DARK} {tag:<4} {RESET}"


def fill(text, width, color):
    """A full-width line on one background, surviving the resets inside the text."""
    return color + pad(text, width).replace(RESET, RESET + color) + RESET


def panel(title, rows, width, focused=False):
    """A deck panel: a thin border with the title in it. rows are (text, action, selected)."""
    edge = GREEN if focused else BORDER
    inner = width - 2
    out = [(f"{edge}┌ {RESET}{BOLD}{TEXT}{title}{RESET}{edge} " + "─" * max(0, width - len(title) - 4) + f"┐{RESET}", None)]
    for text, action, selected in rows:
        body = pad(text, inner)
        if selected:
            body = SELECT_BG + body.replace(RESET, RESET + SELECT_BG) + RESET
        out.append((f"{edge}│{RESET}{body}{edge}│{RESET}", action))
    out.append((f"{edge}└" + "─" * (width - 2) + f"┘{RESET}", None))
    return out


# One letter each, like the deck. They work while the sidebar has focus (click it, or Ctrl-g Ctrl-h).
KEYS = [("n", "New", ("new",)), ("t", "Term", ("term",)), ("b", "Board", ("campaign",)),
        ("w", "War", ("board",)), ("p", "Pins", ("pins",)), ("1-9", "Jump", None),
        ("?", "Keys", ("keys",)), ("q", "Back", ("back",))]


def footer(width):
    """The deck's help bar: key:Action pairs on the surface color, wrapped to the width."""
    lines, spans, line, col = [], [], "", 1
    for key, label, action in KEYS:
        chunk = f"{key}:{label}"
        if col + len(chunk) - 1 > width and line:
            lines.append(line); line, col = "", 1
        if action:
            spans.append((len(lines), col, col + len(chunk) - 1, action))
        line += f"{BOLD}{TEXT}{key}{RESET}{SURFACE_BG}{SUBTEXT}:{label}{RESET}{SURFACE_BG} "
        col += len(chunk) + 1
    lines.append(line)
    return [fill(l, width, SURFACE_BG) for l in lines], spans


def items(quests, pins):
    """Everything a number or the selection can open: pins first, then quests."""
    out = []
    for r in pins or []:
        out.append({"kind": "pin", "name": r["name"], "state": r["state"], "repo": "",
                    "action": ("pin", r["key"], r["tab"]), "extra": "" if r["open"] else "closed tab"})
    for q in quests:
        out.append({"kind": "quest", "name": q["slug"], "state": q["state"],
                    "repo": "qm" if q.get("pseudo") else os.path.basename(q["repo"]),
                    "action": ("board",) if q.get("pseudo") else ("quest", q["slug"]), "quest": q,
                    "extra": "board" if q["boards"] else ""})
    return out


def row_for(n, it, width, selected, spend):
    dot_color = COLORS.get(it["state"].split(" +")[0], SUBTEXT)
    dot = "●" if it["state"] in ("working", "your turn", "needs-decision", "blocked", "failed") or it["state"].startswith("working") else "○"
    tag = chip(it["repo"]) + " " if it["repo"] else f"{MAUVE}pin{RESET}  "
    name = f"{TEXT if selected else SUBTEXT}{it['name']}{RESET}"
    mark = f" {YELLOW}*{RESET}" if it["extra"] == "board" else ""
    rows = [(f"{DIM}{n if n < 10 else ' '}{RESET} {dot_color}{dot}{RESET} {tag}{name}{mark}", it["action"], selected)]
    if selected:                                   # the selected row opens up, like a deck preview
        detail = [SHORT_STATE.get(it["state"], it["state"])]
        q = it.get("quest")
        if q:
            if (spend or {}).get(q["slug"]):
                detail.append(money(spend[q["slug"]]))
            if q.get("model"):
                detail.append(q["model"])
        if it["extra"] and it["extra"] != "board":
            detail.append(it["extra"])
        rows.append((f"    {DIM}{' · '.join(detail)}{RESET}", it["action"], selected))
    return rows


def draw(quests, width, height, spend=None, pins=None, selected=0, focused=False):
    """Every line of the sidebar with what a click on it does."""
    title = " ○ GUILD │ QUARTERMASTER"
    out = [(fill(f"{BLUE}{BOLD}{title}", width, SURFACE_BG), None)]
    listing = items(quests, pins)
    pin_rows, quest_rows = [], []
    for n, it in enumerate(listing, 1):
        (pin_rows if it["kind"] == "pin" else quest_rows).extend(row_for(n, it, width, focused and n - 1 == selected, spend))
    if pin_rows:
        out += panel("Pinned", pin_rows, width, focused)
    out += panel("Quests", quest_rows or [(f"{DIM}no quests yet{RESET}", None, False)], width, focused)
    room = height - len(out) - 2 - 3                   # activity borders, and a footer of up to three lines
    if room > 1:
        acts = [(f"{COLORS.get(st, SUBTEXT)}●{RESET} {t}", ("quest", slug) if slug else None, False)
                for t, slug, st in activity(width - 4, limit=room)]
        out += panel("Activity", acts, width)
    return out, listing


def activity(width, limit=8, hours=24):
    """(line, quest, state) per event, newest first, last day only."""
    try:
        rows = open(EVENTS).read().splitlines()
    except OSError:
        return [(f"{DIM}nothing yet{RESET}", None, "")]
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
        out.append((f"{DIM}{when}{RESET} {TEXT}{slug}{RESET} {COLORS.get(state, SUBTEXT)}{word}{RESET}{tail}", parts[1], state))
        if len(out) >= limit:
            break
    return out or [(f"{DIM}quiet for the last {hours}h{RESET}", None, "")]


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
    elif kind == "back":
        subprocess.run(tmux + ["select-pane", "-t", f"{SESSION}:qm.1"], capture_output=True)
    elif kind == "keys":                      # the same menu as Ctrl-g ?, typed into the newest client
        client = subprocess.run(tmux + ["list-clients", "-F", "#{client_activity} #{client_name}"],
                                capture_output=True, text=True).stdout.split("\n")
        client = sorted([c for c in client if c], reverse=True)[:1]
        if client:
            subprocess.run(tmux + ["send-keys", "-K", "-c", client[0].split(" ", 1)[1], "C-g", "?"], capture_output=True)
    elif kind == "pins":
        subprocess.run(tmux + ["select-pane", "-t", f"{SESSION}:qm.1"], capture_output=True)
        subprocess.run([guild, "pins", "menu"], capture_output=True)


INPUT = re.compile(r"\033\[<(\d+);(\d+);(\d+)([mM])|\033\[([IO])|\033\[([AB])|(.)", re.S)


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
    interactive = sys.stdin.isatty()
    saved = None
    if interactive:        # clicks, focus and keys arrive on stdin: SGR mouse, focus reports, letters
        import termios, tty
        saved = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        sys.stdout.write("\033[?1000h\033[?1006h\033[?1004h\033[?25l")
    selected, focused = 0, False
    try:
        buf = ""
        while True:
            # the pane's real size, read every tick, so a resize never makes lines wrap
            size = shutil.get_terminal_size((30, 20))
            width, height = size.columns, size.lines
            quests = read_quests()
            mark_tabs(quests)
            lines, listing = draw(quests, width, height, costs(), pinned(), selected, focused)
            foot, spans = footer(width)
            lines = lines[:max(0, height - len(foot))]
            body = [l if l.startswith(SURFACE_BG) else fill(l, width, BASE_BG) for l, _ in lines]
            body += [BASE_BG + " " * width + RESET] * max(0, height - len(foot) - len(body))
            sys.stdout.write("\033[H" + "\n".join(body + [f + RESET for f in foot]) + "\033[J")
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
                if buf.endswith("\033") or re.search(r"\033\[[<\d;]*$", buf):
                    continue                              # half an escape sequence: wait for the rest
                redraw = False
                for m in INPUT.finditer(buf):
                    if m.group(1):                        # a mouse report
                        button, x, y, kind = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
                        if kind != "M" or button != 0:
                            continue
                        top = height - len(foot)
                        if y > top:
                            for line_no, a, b, action in spans:
                                if line_no == y - top - 1 and a <= x <= b:
                                    act(action)
                        elif 1 <= y <= len(lines) and lines[y - 1][1]:
                            act(lines[y - 1][1])
                        redraw = True
                    elif m.group(5):                      # focus in or out
                        focused = m.group(5) == "I"; redraw = True
                    elif m.group(6):                      # arrows move the selection
                        selected = max(0, min(len(listing) - 1, selected + (1 if m.group(6) == "B" else -1))); redraw = True
                    elif m.group(7):
                        ch = m.group(7)
                        if ch in "jk":
                            selected = max(0, min(len(listing) - 1, selected + (1 if ch == "j" else -1)))
                        elif ch in "\r\n" and listing:
                            act(listing[selected]["action"])
                        elif ch.isdigit() and ch != "0" and int(ch) <= len(listing):
                            selected = int(ch) - 1
                            act(listing[selected]["action"])
                        else:
                            for key, _, action in KEYS:
                                if key == ch and action:
                                    act(action)
                        redraw = True
                buf = ""
                if redraw:
                    break
    finally:
        if saved is not None:
            import termios
            sys.stdout.write("\033[?1000l\033[?1006l\033[?1004l\033[?25h")
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
