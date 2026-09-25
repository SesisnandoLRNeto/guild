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
    "checks-green": GREEN, "checks-red": RED, "trial-pass": GREEN, "planned": BLUE, "held": OVERLAY,
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
# The same letters work after Ctrl-g from anywhere, so one set of keys to learn.
KEYS = [("n", "New", ("new",)), ("t", "Term", ("term",)), ("b", "Board", ("campaign",)),
        ("g", "Docket", ("board",)), ("p", "Pins", ("pins",)), ("0-9", "Tab", None), ("x", "Close", None),
        ("?", "Keys", ("keys",)), ("q", "Back", ("back",))]


def footer(width, focused=False):
    """The deck's help bar. It says which way the keys work right now: a green dot means this
    menu has the keyboard, so plain letters work; ^g means press Ctrl-g first (from anywhere)."""
    lead = f"{GREEN}●{RESET}{SURFACE_BG} " if focused else f"{BOLD}{YELLOW}^g{RESET}{SURFACE_BG} "
    lines, spans, line, col = [], [], lead, 3
    for key, label, action in KEYS:
        if key == "q" and not focused:
            continue
        chunk = f"{key}:{label}"
        if col + len(chunk) - 1 > width and line.strip():
            lines.append(line); line, col = "   ", 4
        if action:
            spans.append((len(lines), col, col + len(chunk) - 1, action))
        line += f"{BOLD}{TEXT}{key}{RESET}{SURFACE_BG}{SUBTEXT}:{label}{RESET}{SURFACE_BG} "
        col += len(chunk) + 1
    lines.append(line)
    return [fill(l, width, SURFACE_BG) for l in lines], spans


def tmux_out(*args):
    try:
        return subprocess.run(["tmux", "-L", SOCKET, *args], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def my_window():
    """(is this tab the one on screen, its window id), or (True, None) outside tmux."""
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return True, None
    out = tmux_out("display-message", "-p", "-t", pane,
                   "#{window_active}\t#{window_id}\t#{session_attached}\t#{window_panes}\t#{window_name}").strip().split("\t")
    if len(out) < 5:
        return True, None
    # The program in this tab has exited and left only the menu: close the tab instead of
    # stretching the menu over the whole screen. The quartermaster's tab always stays.
    if out[3] == "1" and out[4] != "qm":
        tmux_out("kill-window", "-t", out[1])
        sys.exit(0)
    return out[0] == "1" and out[2] != "0", out[1]


def tab_kind(name, quests):
    if name == "qm":
        return "qm"
    if name in quests:
        return "quest"
    return {"shell": "term", "deck": "deck", "jira": "jira"}.get(name.split(":")[0].split("-")[0],
            "edit" if name.startswith("edit") else "ai" if name.startswith(("claude", "codex", "openrouter")) else "tab")


KIND_CHIP = {"qm": "#f9e2af", "term": "#89b4fa", "edit": "#a6e3a1", "ai": "#cba6f7", "deck": "#94e2d5",
             "jira": "#fab387", "tab": "#bac2de"}


def kind_chip(kind):
    return f"{bg(KIND_CHIP.get(kind, '#bac2de'))}{DARK} {kind:<4} {RESET}"


def items(quests, pins):
    """Every open tab, numbered like the tab strip, then quests that have no tab yet."""
    by_slug = {q["slug"]: q for q in quests}
    out = []
    for line in tmux_out("list-windows", "-t", SESSION, "-F", "#{window_index}\t#{window_id}\t#{window_name}\t#{window_active}").splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        index, wid, name, active = parts
        kind = tab_kind(name, by_slug)
        q = by_slug.get(name)
        out.append({"n": int(index), "name": name, "kind": kind, "state": q["state"] if q else ("working" if kind in ("qm", "ai") else ""),
                    "repo": os.path.basename(q["repo"]) if q else "", "quest": q, "active": active == "1",
                    "action": ("win", wid), "extra": "board" if q and q["boards"] else "", "tab": True})
    open_names = {it["name"] for it in out}
    for q in quests:
        if q["slug"] not in open_names and not q.get("pseudo") and q["state"] not in ("done",):
            out.append({"n": None, "name": q["slug"], "kind": "quest", "state": q["state"], "repo": os.path.basename(q["repo"]),
                        "quest": q, "active": False, "action": ("quest", q["slug"]), "extra": "no tab", "tab": False})
    return out


def row_for(it, width, highlight, spend):
    state = it["state"]
    dot_color = COLORS.get(state.split(" +")[0], SUBTEXT)
    dot = "●" if state in ("working", "needs-decision", "blocked", "failed") else "○"
    tag = chip(it["repo"]) if it["repo"] else kind_chip(it["kind"])
    parent = (it.get("quest") or {}).get("parent")
    label = f"└ {it['name'][len(parent) + 1:] if it['name'].startswith(parent + '-') else it['name']}" if parent else it["name"]
    name = f"{TEXT if highlight else SUBTEXT}{BOLD if highlight else ''}{label}{RESET}"
    mark = f" {YELLOW}*{RESET}" if it["extra"] == "board" else ""
    num = f"{it['n']}" if it["n"] is not None and it["n"] < 10 else " "
    rows = [(f"{DIM}{num}{RESET} {dot_color}{dot}{RESET} {tag} {name}{mark}", it["action"], highlight)]
    if highlight and it.get("quest"):                   # the current tab opens up, like a deck preview
        q = it["quest"]
        detail = [SHORT_STATE.get(state, state)]
        if (spend or {}).get(q["slug"]):
            detail.append(money(spend[q["slug"]]))
        if q.get("model"):
            detail.append(q["model"])
        rows.append((f"    {DIM}{' · '.join(detail)}{RESET}", it["action"], highlight))
    return rows


def pin_rows(pins, width):
    rows = []
    for r in pins or []:
        color = COLORS.get(r["state"].split(" +")[0], SUBTEXT)
        where = "" if r["open"] else f" {DIM}(closed){RESET}"
        rows.append((f"  {color}●{RESET} {kind_chip('pin')} {SUBTEXT}{r['name']}{RESET}{where}", ("pin", r["key"], r["tab"]), False))
    return rows


def draw(quests, width, height, spend=None, pins=None, selected=None, focused=False):
    """Every line of the side menu with what a click on it does, and the numbered items."""
    title = " ○ GUILD │ QUARTERMASTER"
    out = [(fill(f"{BLUE}{BOLD}{title}", width, SURFACE_BG), None)]
    listing = items(quests, pins)
    if pins:
        out += panel("Pinned", pin_rows(pins, width), width)
    rows = []
    for i, it in enumerate(listing):
        if not it["tab"] and i and listing[i - 1]["tab"]:
            rows.append((f"{DIM}  not open{RESET}", None, False))
        highlight = (i == selected) if (focused and selected is not None) else it["active"]
        rows += row_for(it, width, highlight, spend)
    out += panel("Tabs", rows or [(f"{DIM}no tabs{RESET}", None, False)], width, focused)
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

    def show(target):                      # switch the content, and keep typing in the content, not the menu
        if subprocess.run(tmux + ["select-window", "-t", target], capture_output=True).returncode:
            return False
        panes = subprocess.run(tmux + ["list-panes", "-t", target, "-F", "#{pane_id} #{@guild_sidebar}"],
                               capture_output=True, text=True).stdout.split("\n")
        content = [p.split()[0] for p in panes if p.strip() and not p.strip().endswith(" 1")]
        if content:
            subprocess.run(tmux + ["select-pane", "-t", content[0]], capture_output=True)
        return True

    if kind == "win":
        show(action[1])
    elif kind == "close":
        subprocess.run(tmux + ["kill-window", "-t", action[1]], capture_output=True)
    elif kind == "quest":
        slug = action[1]
        if not show(f"{SESSION}:{slug}"):
            subprocess.run([guild, "revive", slug], capture_output=True)
            show(f"{SESSION}:{slug}")
    elif kind == "pin":
        key, tab = action[1], action[2]
        wid = [l.split("\t")[0] for l in tmux_out("list-windows", "-t", SESSION, "-F", "#{window_id}\t#W").splitlines()
               if l.split("\t")[-1] == tab] if tab else []
        if wid:
            show(wid[0])
        elif key.startswith("session:"):
            subprocess.run([guild, "new", "--resume", key.split(":", 1)[1]], capture_output=True)
        elif key.startswith("quest:"):
            act(("quest", key.split(":", 1)[1]))
    elif kind == "new":
        subprocess.run([guild, "new"], capture_output=True)
    elif kind == "term":
        subprocess.run([guild, "term"], capture_output=True)
    elif kind == "board":
        subprocess.run([guild, "docket"], capture_output=True)
    elif kind == "campaign":
        subprocess.run([guild, "campaign"], capture_output=True)
    elif kind == "back":                     # from the menu back to this tab's content
        subprocess.run(tmux + ["select-pane", "-t", os.environ.get("TMUX_PANE", ""), "-R"], capture_output=True)
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
        shown = False
        while True:
            # Every tab draws this menu; only the tab on screen does the work. The others wait,
            # and draw at once when you switch to them.
            visible, _ = my_window()
            if not visible:
                shown = False
                time.sleep(0.4)
                continue
            if not shown:
                sys.stdout.write("\033[?1000h\033[?1006h\033[?1004h\033[?25l" if interactive else "")
                shown = True
            # the pane's real size, read every tick, so a resize never makes lines wrap
            size = shutil.get_terminal_size((30, 20))
            width, height = size.columns, size.lines
            quests = read_quests()
            mark_tabs(quests)
            lines, listing = draw(quests, width, height, costs(), pinned(), selected, focused)
            foot, spans = footer(width, focused)
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
                        if focused:                       # the selection starts on the tab you are in
                            selected = next((i for i, it in enumerate(listing) if it["active"]), 0)
                    elif m.group(6):                      # arrows move the selection
                        selected = max(0, min(len(listing) - 1, selected + (1 if m.group(6) == "B" else -1))); redraw = True
                    elif m.group(7):
                        ch = m.group(7)
                        if ch in "jk":
                            selected = max(0, min(len(listing) - 1, selected + (1 if ch == "j" else -1)))
                        elif ch in "\r\n" and listing:
                            act(listing[selected]["action"])
                        elif ch.isdigit():                # the same number as the tab strip
                            hit = [i for i, it in enumerate(listing) if it["n"] == int(ch)]
                            if hit:
                                selected = hit[0]
                                act(listing[selected]["action"])
                        elif ch == "x" and listing:       # close a terminal or editor tab, never an agent
                            it = listing[min(selected, len(listing) - 1)]
                            if it["tab"] and it["kind"] in ("term", "edit"):
                                act(("close", it["action"][1]))
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
