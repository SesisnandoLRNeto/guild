#!/usr/bin/env python3
"""A party of three walking through a night forest, in colored ASCII.

    python3 party.py                 animate until Ctrl+C
    python3 party.py --fps 12        another speed
    python3 party.py --frames 4      print 4 plain frames and exit (to check the art)

Standard library only. Works in macOS Terminal, iTerm2, Linux terminals and Windows Terminal.
The party stays in the middle; the forest scrolls left, far trees slower than near ones.

To change the look, edit the sections below: PALETTE (colors), the sprites (ARCHER, MAGE,
KNIGHT and their LEG frames), the scenery (PINES, BUSH, TUFTS) and SPEED.
"""
import argparse
import os
import random
import shutil
import signal
import sys
import time

# ── colors: 256-color ANSI codes (every modern terminal has them) ────────────────
PALETTE = {
    "archer": 214,    # orange
    "mage": 81,       # cyan
    "knight": 203,    # red
    "star": 223,      # warm white
    "pine": 71,       # green
    "pine_far": 65,   # dim green, for depth
    "bush": 71,
    "tuft": 65,
    "trail": 223,
}

# ── speed ─────────────────────────────────────────────────────────────────────
FPS = 10
STEP_EVERY = 2        # frames per walking frame: 10 fps / 2 = 5 steps a second
SPEED = {             # cells per frame, for depth: far moves slowest
    "far": 0.15,
    "near": 0.35,
    "ground": 0.5,    # matches the stride, so feet do not slide on the trail
}

# ── the party ─────────────────────────────────────────────────────────────────
# Each figure is 9 rows: 7 of body, then 2 of legs. A body row and a leg frame are the same
# width, so a weapon that reaches the ground (the staff) is drawn in the leg frames too.
# Characters listed in "accent" take another color (the staff's star).


def legs(width, hip, extra=None):
    """Four walking frames for a figure whose torso starts at column `hip`.
    `extra` adds fixed characters (column -> char) to every leg row, like a staff."""
    frames = [
        (" /  \\ ", "/    \\"),     # stride
        (" |  \\ ", " |_  \\"),     # back leg comes forward
        (" |  | ", " |_  |_"),      # passing
        (" /  | ", "/    |_"),      # front leg plants
    ]
    out = []
    for top, bottom in frames:
        rows = []
        for part in (top, bottom):
            row = [" "] * width
            for i, ch in enumerate(part):
                col = hip - 1 + i
                if ch != " " and 0 <= col < width:
                    row[col] = ch
            for col, ch in (extra or {}).items():
                row[col] = ch
            rows.append("".join(row))
        out.append(rows)
    return out


ARCHER = {           # pointed cap, quiver of arrows on the back, bow drawn with an arrow
    "color": "archer",
    "body": [
        "       /\\    )     ",
        "  \\|/ (oo)    \\    ",
        "   #   )(      |   ",
        "   #--/  \\-----|-->",
        "   #  |  |     |   ",
        "      |__|    /    ",
        "      |  |   )     ",
    ],
    "hip": 6,
    "accent": {},
}

MAGE = {             # tall pointed hat, cape flowing behind, staff with a star
    "color": "mage",
    "body": [
        "     /\\     *  ",
        "    /  \\    |  ",
        "   /____\\   |  ",
        "    (oo)    |  ",
        "   //  \\\\--o  ",
        "  //|  |    |  ",
        " //_|__|    |  ",
    ],
    "hip": 4,
    "accent": {"*": "star"},
    "legs_extra": {12: "|"},
}

KNIGHT = {           # plumed helmet with a visor, crossed shield, sword raised
    "color": "knight",
    "body": [
        "      _^_     / ",
        "     [=#=]   /  ",
        "  __  )(    /   ",
        " /##\\/  \\--+    ",
        " |##||  |  '    ",
        " \\##/|__|       ",
        "  \\/ |  |       ",
    ],
    "hip": 5,
    "accent": {},
}

PARTY = [ARCHER, MAGE, KNIGHT]      # left to right; they walk right
GAP = 2                             # columns between two figures
FIGURE_ROWS = 9

for fig in PARTY:
    width = max(len(r) for r in fig["body"])      # rows may differ; they are padded here
    fig["body"] = [r.ljust(width) for r in fig["body"]]
    fig["width"] = width
    fig["legs"] = legs(width, fig["hip"], fig.get("legs_extra"))

# ── the forest ────────────────────────────────────────────────────────────────
PINES = {
    "tall": ["    ^    ", "   /|\\   ", "  //|\\\\  ", " ///|\\\\\\ ", "////|\\\\\\\\",
             "    |    ", "    |    ", "    |    "],
    "mid": ["   ^   ", "  /|\\  ", " //|\\\\ ", "///|\\\\\\", "   |   ", "   |   "],
    "small": ["  ^  ", " /|\\ ", "//|\\\\", "  |  "],
}
BUSH = [" .^^. ", "(    )"]
TUFTS = ["^^", "_^", ",\"", "''", "^"]

TILE = 140            # the scenery repeats every TILE columns; wider than most windows


def make_layers(seed=7):
    """Where each tree, bush and tuft sits along one tile of scenery."""
    rnd = random.Random(seed)
    far, near, ground, grass = [], [], [], []
    x = 0
    while x < TILE:
        far.append((x, rnd.choice(["small", "small", "mid"])))
        x += rnd.randint(16, 26)
    x = 3
    while x < TILE:
        near.append((x, rnd.choice(["tall", "mid", "tall", "small"])))
        x += rnd.randint(14, 24)
    x = 6
    while x < TILE:
        ground.append(x)
        x += rnd.randint(18, 30)
    x = 1
    while x < TILE:
        grass.append((x, rnd.choice(TUFTS)))
        x += rnd.randint(5, 11)
    return far, near, ground, grass


FAR, NEAR, GROUND, GRASS = make_layers()


# ── drawing ───────────────────────────────────────────────────────────────────
class Canvas:
    """A grid of (char, color name) cells; turned into one string per frame."""

    def __init__(self, width, height):
        self.w, self.h = width, height
        self.cells = [[(" ", None)] * width for _ in range(height)]

    def put(self, x, y, ch, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.cells[y][x] = (ch, color)

    def text(self, x, y, s, color):
        for i, ch in enumerate(s):
            if ch != " ":
                self.put(x + i, y, ch, color)

    def clear_span(self, x0, x1, y):
        for x in range(max(0, x0), min(self.w, x1)):
            self.put(x, y, " ", None)

    def render(self, color=True):
        out, last = [], "reset"
        for y, row in enumerate(self.cells):
            if color:
                out.append(f"\x1b[{y + 1};1H")
            for ch, c in row:
                if color and c != last:
                    out.append("\x1b[0m" if c is None else f"\x1b[38;5;{PALETTE[c]}m")
                    last = c
                out.append(ch)
            if not color:
                out.append("\n")
        if color:
            out.append("\x1b[0m")
        return "".join(out)


def scenery(canvas, frame, ground_row, full):
    """Stars, two layers of pines, bushes, the dotted trail and grass below it."""
    w = canvas.w
    # stars: fixed places for this width, a few twinkle
    rnd = random.Random(w)
    sky_rows = max(0, ground_row - 9)
    if sky_rows:
        for i in range(max(3, w // (9 if full else 14))):
            x, y = rnd.randrange(w), rnd.randrange(sky_rows + 1)
            big = rnd.random() < 0.35
            twinkle = (frame // 6 + i) % 7 == 0
            canvas.put(x, y, "*" if big != twinkle else ".", "star")

    def scroll(x, layer):
        return int(x - frame * SPEED[layer]) % TILE

    def each(x, layer, width):
        """Every screen column where this tile position shows, across repeats."""
        base = scroll(x, layer)
        start = base - TILE * ((base + width) // TILE + 1)
        return range(start, w + width, TILE) if TILE else []

    if full:
        for x, kind in FAR:
            for sx in each(x, "far", len(PINES[kind][0])):
                solid(canvas, PINES[kind], sx, ground_row - len(PINES[kind]), "pine_far")
    for x, kind in NEAR:                                 # near trees hide what is behind them
        for sx in each(x, "near", len(PINES[kind][0])):
            solid(canvas, PINES[kind], sx, ground_row - len(PINES[kind]), "pine")
    for x in GROUND:
        for sx in each(x, "ground", len(BUSH[0])):
            solid(canvas, BUSH, sx, ground_row - len(BUSH), "bush")
    shift = int(frame * SPEED["ground"])
    for x in range(w):                                   # the dotted trail
        if (x + shift) % 2 == 0:
            canvas.put(x, ground_row, ".", "trail")
    for x, tuft in GRASS:                                # grass under the trail
        for sx in each(x, "ground", len(tuft)):
            canvas.text(sx, ground_row + 1, tuft, "tuft")


def solid(canvas, art, x, top, color):
    """Draw art as an opaque shape: each row is cleared from its first to its last mark."""
    for i, line in enumerate(art):
        filled = [j for j, ch in enumerate(line) if ch != " "]
        if filled:
            canvas.clear_span(x + filled[0], x + filled[-1] + 1, top + i)
            canvas.text(x, top + i, line, color)


def figure(canvas, fig, x, top, step):
    """One adventurer. Its outline is cleared first, so trees pass behind it, not through it."""
    rows = fig["body"] + fig["legs"][step % 4]
    for i, line in enumerate(rows):
        y = top + i
        filled = [j for j, ch in enumerate(line) if ch != " "]
        if filled:
            canvas.clear_span(x + filled[0], x + filled[-1] + 1, y)
        for j, ch in enumerate(line):
            if ch != " ":
                canvas.put(x + j, y, ch, fig["accent"].get(ch, fig["color"]))


def scene(width, height, frame):
    """The whole picture for one frame, sized to the terminal."""
    canvas = Canvas(width, height)
    party_w = sum(f["width"] for f in PARTY) + GAP * (len(PARTY) - 1)
    if height < FIGURE_ROWS + 2 or width < KNIGHT["width"] + 2:
        msg = "make the window bigger"
        canvas.text(max(0, (width - len(msg)) // 2), height // 2, msg[:width], "star")
        return canvas
    # the picture: up to 4 rows of sky, the figures, the trail, one row of grass
    scene_h = min(height, FIGURE_ROWS + 2 + 4)
    top = (height - scene_h) // 2
    ground_row = top + scene_h - 2
    full = width >= party_w + 20 and height >= FIGURE_ROWS + 6
    party = PARTY if width >= party_w + 4 else [KNIGHT]        # a narrow window: only the leader
    scenery(canvas, frame, ground_row, full)
    step = frame // STEP_EVERY
    pw = sum(f["width"] for f in party) + GAP * (len(party) - 1)
    x = (width - pw) // 2
    for y in range(ground_row - FIGURE_ROWS, ground_row):    # a clear path through the trees
        canvas.clear_span(x - 1, x + pw + 1, y)
    for n, fig in enumerate(party):
        figure(canvas, fig, x, ground_row - FIGURE_ROWS, step + n)   # out of step with each other
        x += fig["width"] + GAP
    return canvas


# ── the terminal ──────────────────────────────────────────────────────────────
def enable_windows_vt():
    """Windows Terminal understands ANSI once virtual terminal processing is on."""
    if os.name != "nt":
        return
    import ctypes
    k = ctypes.windll.kernel32
    handle = k.GetStdHandle(-11)
    mode = ctypes.c_uint32()
    if k.GetConsoleMode(handle, ctypes.byref(mode)):
        k.SetConsoleMode(handle, mode.value | 0x0004)


class Terminal:
    """Alternate screen, hidden cursor, no echo; everything put back on exit."""

    def __enter__(self):
        enable_windows_vt()
        self.saved = None
        if os.name != "nt" and sys.stdin.isatty():
            import termios
            fd = sys.stdin.fileno()
            self.saved = termios.tcgetattr(fd)
            quiet = termios.tcgetattr(fd)
            quiet[3] &= ~(termios.ECHO | termios.ICANON)
            termios.tcsetattr(fd, termios.TCSANOW, quiet)
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J")
        sys.stdout.flush()
        return self

    def __exit__(self, *exc):
        sys.stdout.write("\x1b[0m\x1b[2J\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        if self.saved is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, self.saved)
        return exc[0] is KeyboardInterrupt        # Ctrl+C is the normal way out


def play(fps):
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    with Terminal():
        frame, size = 0, None
        tick = 1.0 / fps
        next_at = time.monotonic()
        while True:
            now_size = shutil.get_terminal_size((80, 24))
            if now_size != size:                  # resized: start from a clean screen
                size = now_size
                sys.stdout.write("\x1b[2J")
            sys.stdout.write(scene(size.columns, size.lines, frame).render())
            sys.stdout.flush()
            frame += 1
            next_at += tick
            delay = next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_at = time.monotonic()        # fell behind: do not rush to catch up


def main():
    ap = argparse.ArgumentParser(description="A party walking through a night forest.")
    ap.add_argument("--fps", type=float, default=FPS, help=f"frames per second (default {FPS})")
    ap.add_argument("--frames", type=int, default=0, help="print this many plain frames and exit")
    ap.add_argument("--width", type=int, default=0, help="with --frames: the width to draw")
    ap.add_argument("--height", type=int, default=0, help="with --frames: the height to draw")
    a = ap.parse_args()
    if a.frames:
        size = shutil.get_terminal_size((100, 16))
        for f in range(a.frames):
            print(scene(a.width or size.columns, a.height or 16, f * STEP_EVERY).render(color=False))
        return
    play(max(1.0, a.fps))


if __name__ == "__main__":
    main()
