#!/usr/bin/env python3
"""The quest console: read a session's screen and type to it from the phone.

  console.py list               the open tabs (quests and quartermasters), with their state
  console.py screen <tab> [N]   the last N lines of a tab's screen, as plain text
  console.py send <tab> <text>  type a message into a tab and press Enter

The war table serves it at /console (and on your Tailscale address, behind the key). Only
tabs open right now can be read or typed to. Text is typed literally (never as tmux
commands), and only a short list of keys can be pressed, to answer a prompt.
"""
import json
import os
import re
import subprocess
import sys

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
SOCKET = os.environ.get("GUILD_TMUX_SOCKET", "guild")
SESSION = "guild"
BIN = os.path.dirname(os.path.realpath(__file__))
SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
KEYS = {"enter": "Enter", "esc": "Escape", "up": "Up", "down": "Down", "tab": "Tab",
        "1": "1", "2": "2", "3": "3", "y": "y", "n": "n"}
MAX_TEXT = 4000


def tmux(*args):
    try:
        return subprocess.run(["tmux", "-L", SOCKET, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(args, 1, "", "")


def windows():
    """{name: window id} of the tabs open now."""
    out = tmux("list-windows", "-t", SESSION, "-F", "#{window_id}\t#{window_name}").stdout
    return {n: w for w, _, n in (l.partition("\t") for l in out.splitlines()) if n}


def content_pane(window_id):
    out = tmux("list-panes", "-t", window_id, "-F", "#{pane_id} #{@guild_sidebar}").stdout
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[1:] != ["1"]:
            return parts[0]
    return ""


def quest_state(name):
    try:
        state, note = open(os.path.join(QUESTS, name, "status")).read().split("\t")[:2]
        return state, note
    except (OSError, ValueError):
        return "", ""


def tabs():
    out = []
    for name in windows():
        if name == "qm" or name.startswith("qm-"):
            out.append({"name": name, "kind": "quartermaster", "state": "quartermaster", "note": ""})
        elif os.path.isdir(os.path.join(QUESTS, name)):
            state, note = quest_state(name)
            try:
                model = open(os.path.join(QUESTS, name, "model")).read().strip()
            except OSError:
                model = ""
            out.append({"name": name, "kind": "quest", "state": state or "?", "note": note[:140], "model": model})
    order = {"needs-decision": 0, "blocked": 0, "failed": 1, "stopped": 1, "quartermaster": 2, "working": 3}
    return sorted(out, key=lambda t: (order.get(t["state"], 4), t["name"]))


def pane_of(name):
    if not SAFE.match(name or ""):
        raise ValueError("no such tab")
    w = windows().get(name)
    pane = content_pane(w) if w else ""
    if not pane:
        raise ValueError(f"{name} has no open tab")
    return pane


def main_column(text):
    """Calm mode splits the terminal in two: the conversation, a "│", then a side panel. A phone
    wraps each wide line and mixes the two, so keep the conversation only. The column is the one
    where most lines carry the bar; lines that do not reach it (the input box) stay whole."""
    rows = text.splitlines()
    counts = {}
    for l in rows:
        for i, ch in enumerate(l):
            if ch == "│" and i >= 30:
                counts[i] = counts.get(i, 0) + 1
    col, hits = max(counts.items(), key=lambda kv: kv[1], default=(0, 0))
    if hits < max(5, len(rows) * 0.4):
        return text
    return "\n".join(l[:col].rstrip() if len(l) > col and l[col] == "│" else l for l in rows)


def is_art(line):
    """The wide ASCII scene Claude Code draws while it works (stars, trees, little people). It wraps
    into noise on a phone. A wide line that is almost all symbols and no box drawing is art."""
    body = line.replace(" ", "")
    if len(line) < 60 or len(body) < 8 or re.search(r"[─━═│┃╭╮╰╯┌┐└┘├┤]", line):
        return False
    return sum(c.isalnum() for c in body) / len(body) < 0.25


def screen(name, lines=60):
    lines = max(10, min(int(lines), 400))
    text = main_column(tmux("capture-pane", "-p", "-J", "-t", pane_of(name), "-S", f"-{lines}").stdout)
    text = re.sub(r"[─━═—_]{24,}", "─" * 24, text)     # a terminal-wide rule would wrap into rows on a phone
    rows = [l.rstrip() for l in text.splitlines() if not is_art(l)]
    rows = ["  " + l.lstrip() if len(l) - len(l.lstrip()) > 40 else l for l in rows]   # a far-right note
    return "\n".join(rows).strip("\n")


def send(name, text="", key=""):
    """Type text and press Enter, or press one allowed key. Returns what was done."""
    pane = pane_of(name)
    if key:
        if key not in KEYS:
            raise ValueError("that key is not allowed")
        tmux("send-keys", "-t", pane, KEYS[key])
        return f"pressed {key}"
    text = " ".join((text or "").split())             # one line: a newline would send half a message
    if not text:
        raise ValueError("nothing to send")
    if len(text) > MAX_TEXT:
        raise ValueError(f"too long (over {MAX_TEXT} characters)")
    if os.path.isdir(os.path.join(QUESTS, name)):     # a quest: the guild way, so its state and events follow
        r = subprocess.run([os.path.join(BIN, "guild"), "send", name, text], capture_output=True, text=True, timeout=20)
        if r.returncode:
            raise ValueError((r.stderr or r.stdout or "guild send failed").strip()[:200])
    else:
        tmux("send-keys", "-t", pane, "-l", text)
        import time
        time.sleep(0.3)
        tmux("send-keys", "-t", pane, "Enter")
    return "sent"


def main():
    a = sys.argv[1:]
    if not a or a[0] == "list":
        print(json.dumps(tabs(), indent=1))
    elif a[0] == "screen" and len(a) > 1:
        print(screen(a[1], a[2] if len(a) > 2 else 60))
    elif a[0] == "send" and len(a) > 2:
        print(send(a[1], " ".join(a[2:])))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        raise SystemExit(f"console: {e}")
