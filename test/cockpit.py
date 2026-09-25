#!/usr/bin/env python3
"""The cockpit, driven by a real tmux client in a pty: keys, the menu, and mouse clicks on the
status bar and the sidebar. Prints one `ok <name>` or `FAIL <name>` line per check.

  cockpit.py <guild repo> <throwaway GUILD_HOME> <tmux socket>

It runs its own tmux server on its own socket and kills it at the end.
"""
import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time

REPO, HOME, SOCK = sys.argv[1], sys.argv[2], sys.argv[3]
W, H = 140, 36
BAR = 1          # the tab strip is the top line; pane rows start below it
env = dict(os.environ, GUILD_HOME=HOME, GUILD_TMUX_SOCKET=SOCK, PATH=f"{REPO}/bin:" + os.environ["PATH"])

q = f"{HOME}/quests/alpha"
os.makedirs(q, exist_ok=True)
json.dump({"slug": "alpha", "repo": "/tmp/somerepo", "harness": "claude", "model": "sonnet"}, open(f"{q}/meta.json", "w"))
open(f"{q}/status", "w").write("working\tbusy\t2026-09-25T10:00:00\n")


def T(*a):
    return subprocess.run(["tmux", "-L", SOCK, *a], capture_output=True, text=True, env=env).stdout.strip()


subprocess.run(["tmux", "-L", SOCK, "kill-server"], capture_output=True)
T("-f", f"{REPO}/config/guild.tmux.conf", "new-session", "-d", "-s", "guild", "-n", "qm", "-x", str(W), "-y", str(H),
  "guild watch 1")
T("split-window", "-h", "-t", "guild:qm", "sleep 600")
T("new-window", "-d", "-t", "guild", "-n", "alpha", "sleep 600")
T("set", "-g", "status-right", T("show", "-gv", "status-right").replace("#(guild roster --count)", ""))
subprocess.run([f"{REPO}/bin/guild", "layout"], env=env)

pid, fd = pty.fork()
if pid == 0:
    os.environ.update(env, TERM="xterm-256color")
    os.execvp("tmux", ["tmux", "-L", SOCK, "attach", "-t", "guild"])
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", H, W, 0, 0))


def drain(t=0.4):
    end = time.time() + t
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                os.read(fd, 65536)
            except OSError:
                return


def windows():
    return T("list-windows", "-t", "guild", "-F", "#W").split()


def active():
    return T("display", "-p", "-t", "guild", "#W")


def home():
    T("select-window", "-t", "guild:qm")
    drain(0.2)


def click(x, y, wait=0.8):
    os.write(fd, f"\x1b[<0;{x};{y}M\x1b[<0;{x};{y}m".encode())
    drain(wait)


def check(name, cond):
    print(("ok " if cond else "FAIL ") + name, flush=True)


try:
    drain(2.5)
    check("every tab gets the side menu, old ones too",
          T("list-panes", "-t", "guild:alpha", "-F", "[#{@guild_sidebar}]").splitlines() == ["[1]", "[]"])
    n = len(windows()); os.write(fd, b"\x07\x14"); drain(1.2)          # Ctrl-g Ctrl-t, Ctrl still held
    check("Ctrl-g Ctrl-t opens a terminal tab", len(windows()) == n + 1 and active() == "shell")
    panes = T("list-panes", "-t", "guild", "-F", "#{@guild_sidebar} #{pane_width} #{pane_active}").splitlines()
    qm_side = T("list-panes", "-t", "guild:qm", "-F", "#{@guild_sidebar} #{pane_width}").splitlines()
    check("the new tab has the same side menu, at the same width",
          any(l.startswith("1 ") for l in panes) and [l for l in panes if l.startswith("1 ")][0].split()[1] == [l for l in qm_side if l.startswith("1 ")][0].split()[1])
    check("and typing goes to the content, not the menu", any(l.endswith(" 1") and not l.startswith("1 ") for l in panes))
    home(); n = len(windows()); os.write(fd, b"\x07t"); drain(0.8)       # Ctrl-g t
    check("Ctrl-g t works too", len(windows()) == n + 1)
    home(); n = len(windows()); os.write(fd, b"\x07?"); drain(0.6); os.write(fd, b"t"); drain(0.8)
    check("the Ctrl-g ? menu runs an action by its letter", len(windows()) == n + 1)

    # Where things sit on the status bar: ask tmux, with a probe binding, what each column is.
    # One click at a time, waiting for its answer: run-shell is asynchronous.
    home()
    probe_log = f"{HOME}/probe"
    T("bind", "-n", "MouseDown1Status", "run-shell", f"echo '#{{mouse_status_range}}' >> {probe_log}")
    probe, seen = {}, 0
    for x in range(W // 3, W + 1):
        click(x, BAR, wait=0.02)
        for _ in range(40):
            lines = open(probe_log).read().splitlines() if os.path.exists(probe_log) else []
            if len(lines) > seen:
                break
            time.sleep(0.02)
        if len(lines) > seen:
            probe.setdefault(lines[-1].strip(), x)
            seen = len(lines)
    T("source-file", f"{REPO}/config/guild.tmux.conf")
    T("set", "-g", "status-right", T("show", "-gv", "status-right").replace("#(guild roster --count)", ""))
    drain(0.5)

    home(); n = len(windows())
    if "newterm" in probe:
        click(probe["newterm"], BAR, wait=0.2)
    for _ in range(30):
        if len(windows()) > n:
            break
        drain(0.2)
    check("the +term button on the status bar opens a tab", len(windows()) == n + 1 and active() == "shell")
    home()
    # a window button: the first column whose range is "window" and whose click lands on alpha
    landed = False
    for x in range(1, W // 2):
        click(x, BAR, wait=0.15)
        if active() == "alpha":
            landed = True
            break
    check("clicking a tab on the status bar switches to it", landed)

    home()
    screen = T("capture-pane", "-p", "-t", "guild:qm.0").splitlines()
    row = next((i + 1 for i, l in enumerate(screen) if "alpha" in l), None)
    if row:
        click(5, row + BAR, wait=0.2)
    for _ in range(30):                    # the sidebar reads clicks between redraws; a busy machine is slower
        if active() == "alpha":
            break
        drain(0.2)
    check("clicking a quest in the sidebar jumps to its tab", active() == "alpha")
    home()
    check("the side menu lists the tabs, deck style", any("┌ Tabs" in l for l in screen))
    check("with the deck's key:Action help bar", any("n:New" in l for l in screen))

    # single letters, like the deck: they work while the sidebar has focus
    def focus_sidebar():
        home(); T("select-pane", "-t", "guild:qm.0"); drain(1.2)
    focus_sidebar(); n = len(windows()); os.write(fd, b"t")
    for _ in range(30):
        if len(windows()) > n:
            break
        drain(0.2)
    check("t in the focused sidebar opens a terminal tab", len(windows()) == n + 1)
    focus_sidebar(); os.write(fd, b"1")
    for _ in range(30):
        if active() == "alpha":
            break
        drain(0.2)
    check("a number in the side menu opens that tab (alpha is tab 1)", active() == "alpha")
    home()
    foot = T("capture-pane", "-p", "-t", "guild:qm.0").splitlines()
    row = next((i + 1 for i, l in enumerate(foot) if "t:Term" in l), None)
    col = foot[row - 1].index("t:Term") + 2 if row else 0
    n = len(windows())
    if row:
        click(col, row + BAR, wait=0.2)
    for _ in range(30):
        if len(windows()) > n:
            break
        drain(0.2)
    check("clicking t:Term on the help bar opens a terminal tab", len(windows()) == n + 1)
finally:
    os.kill(pid, 9)
    subprocess.run(["tmux", "-L", SOCK, "kill-server"], capture_output=True)
