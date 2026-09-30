#!/usr/bin/env python3
"""A party of three walking through a night forest, in colored ASCII.

    python3 party.py                 animate until Ctrl+C (fine line art in Braille dots)
    python3 party.py --ascii         plain printable ASCII figures instead
    python3 party.py --fps 12        another speed
    python3 party.py --frames 4      print 4 frames and exit (to check the art)

Standard library only. Works in macOS Terminal, iTerm2, Linux terminals and Windows Terminal.
The default draws the party as line art with Unicode Braille characters (2x4 dots per cell),
which is the only way to get thin, smooth lines in a terminal; --ascii, a small window, or a
terminal that is not UTF-8 uses the hand-drawn ASCII figures.
The party stays in the middle; the forest scrolls left, far trees slower than near ones.

To change the look: PALETTE (colors); the line-art figures in draw_archer, draw_mage and
draw_knight (shapes in units: 1 unit = 1 column across = half a row down), WALK_FRAMES,
SWING and KNEE for the walk; the ASCII figures (ARCHER, MAGE, KNIGHT, LEGS); the scenery
(PINES, BUSH, TUFTS) and SPEED.
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
# Two sets: the full figures (12 rows: 9 of body, 3 of legs) and small ones (9 rows) for
# short or narrow windows. A body row and a leg row are the same width, so gear that reaches
# the ground (the staff) is added to the leg rows with "legs_extra" (column -> char).
# Characters in "accent" take another color (the staff's star). Rows may differ in length.

LEGS = [             # four walking frames, 3 rows, drawn from the hips down; feet point right
    ["  /  \\  ", " /    \\ ", "/_     \\_"],   # stride
    ["  |  \\  ", "  |   \\ ", " _|    \\_"],   # back leg swings forward
    ["  |  |  ", "  |  |  ", " _|  _|  "],     # passing
    ["  /  |  ", " /   |  ", "/_   _|  "],     # front leg plants
]
LEGS_SMALL = [
    [" /  \\ ", "/    \\"],
    [" |  \\ ", " |_  \\"],
    [" |  | ", " |_  |_"],
    [" /  | ", "/    |_"],
]

ARCHER = {           # small cap, one hand up holding arrows, tall bow, arrow on the string
    "color": "archer",
    "body": [
        "         /\\          ",
        "        /__\\   .     ",
        "  \\|/  ( oo )   \\    ",
        "   |    '--'     \\   ",
        "   \\   _|  |_     |  ",
        "    \\_/ |  |o- - -|->",
        "        |  |      |  ",
        "        |==|     /   ",
        "        |/\\|    /    ",
    ],
    "hip": 8,
    "accent": {},
}

MAGE = {             # tall hat with a brim, cape down the back, staff with a star
    "color": "mage",
    "body": [
        "       /\\        *  ",
        "      /  \\       |  ",
        "     /    \\      |  ",
        "   _/______\\_    |  ",
        "     ( oo )      |  ",
        "    / '--' \\     |  ",
        "   //|    |\\\\---o  ",
        "  // |    |      |  ",
        " //__|____|      |  ",
    ],
    "hip": 6,
    "accent": {"*": "star"},
    "legs_extra": {17: "|"},
}

KNIGHT = {           # domed helmet with a visor, oval shield, long sword held high
    "color": "knight",
    "body": [
        "       _^_        /",
        "      /   \\      / ",
        "     | [=] |    /  ",
        "      \\___/    /   ",
        "  .--. |  |   /    ",
        " / #! \\|  |\\-o     ",
        "|  #   |  |        ",
        " \\ +  /|__|        ",
        "  '--' |  |        ",
    ],
    "hip": 7,
    "accent": {},
}

ARCHER_SMALL = {"color": "archer", "hip": 6, "accent": {}, "body": [
    "       /\\    )     ",
    "  \\|/ (oo)    \\    ",
    "   #   )(      |   ",
    "   #--/  \\-----|-->",
    "   #  |  |     |   ",
    "      |__|    /    ",
    "      |  |   )     "]}
MAGE_SMALL = {"color": "mage", "hip": 4, "accent": {"*": "star"}, "legs_extra": {12: "|"}, "body": [
    "     /\\     *  ",
    "    /  \\    |  ",
    "   /____\\   |  ",
    "    (oo)    |  ",
    "   //  \\\\--o  ",
    "  //|  |    |  ",
    " //_|__|    |  "]}
KNIGHT_SMALL = {"color": "knight", "hip": 5, "accent": {}, "body": [
    "      _^_     / ",
    "     [=#=]   /  ",
    "  __  )(    /   ",
    " /##\\/  \\--+    ",
    " |##||  |  '    ",
    " \\##/|__|       ",
    "  \\/ |  |       "]}

PARTIES = {                          # left to right; they walk right
    "full": [ARCHER, MAGE, KNIGHT],
    "small": [ARCHER_SMALL, MAGE_SMALL, KNIGHT_SMALL],
}
GAP = 3                              # columns between two figures
HD = True                            # fine line art in Braille dots (Unicode); --ascii turns it off


def legs(width, hip, frames, extra=None):
    """The leg rows of each walking frame, placed under a torso that starts at column `hip`."""
    out = []
    for frame in frames:
        rows = []
        for part in frame:
            row = [" "] * width
            lead = 2 if len(frame) == 3 else 1          # the full legs start two columns left of the hip
            for i, ch in enumerate(part):
                col = hip - lead + i
                if ch != " " and 0 <= col < width:
                    row[col] = ch
            for col, ch in (extra or {}).items():
                if col < width:
                    row[col] = ch
            rows.append("".join(row))
        out.append(rows)
    return out


for name, party in PARTIES.items():
    for fig in party:
        width = max(len(r) for r in fig["body"])      # rows may differ; they are padded here
        fig["body"] = [r.ljust(width) for r in fig["body"]]
        fig["width"] = width
        fig["legs"] = legs(width, fig["hip"], LEGS if name == "full" else LEGS_SMALL, fig.get("legs_extra"))
        fig["rows"] = len(fig["body"]) + len(fig["legs"][0])


# ── the forest ────────────────────────────────────────────────────────────────
PINES = {            # for the full figures: the tall pines stand above the party, as in a forest
    "tall": ["     ^     ", "    /|\\    ", "   //|\\\\   ", "   //|\\\\   ", "  ///|\\\\\\  ", "  ///|\\\\\\  ",
             " ////|\\\\\\\\ ", " ////|\\\\\\\\ ", "     |     ", "     |     ", "     |     ", "     |     ",
             "     |     "],
    "mid": ["    ^    ", "   /|\\   ", "  //|\\\\  ", "  //|\\\\  ", " ///|\\\\\\ ", " ///|\\\\\\ ",
            "    |    ", "    |    ", "    |    "],
    "small": ["  ^  ", " /|\\ ", "//|\\\\", "//|\\\\", "  |  ", "  |  "],
}
PINES_SMALL = {      # for the small figures
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


def scenery(canvas, frame, ground_row, full, figure_rows, pines=PINES):
    """Stars, two layers of pines, bushes, the dotted trail and grass below it."""
    w = canvas.w
    # stars: fixed places for this width, a few twinkle
    rnd = random.Random(w)
    sky_rows = max(0, ground_row - figure_rows)
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
            for sx in each(x, "far", len(pines[kind][0])):
                solid(canvas, pines[kind], sx, ground_row - len(pines[kind]), "pine_far")
    for x, kind in NEAR:                                 # near trees hide what is behind them
        for sx in each(x, "near", len(pines[kind][0])):
            solid(canvas, pines[kind], sx, ground_row - len(pines[kind]), "pine")
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


def party_width(party):
    return sum(f["width"] for f in party) + GAP * (len(party) - 1)


def scene(width, height, frame):
    """The whole picture for one frame, sized to the terminal: the full figures when they fit,
    the small ones in a short or narrow window, only the warrior when even those do not fit."""
    canvas = Canvas(width, height)
    full, small = PARTIES["full"], PARTIES["small"]
    if HD and height >= HD_ROWS + 5 and width >= hd_party_width() + 6:
        top = (height - (HD_ROWS + 6)) // 2
        ground_row = top + HD_ROWS + 4
        hd_scene(canvas, width, frame, ground_row, width >= hd_party_width() + 30)
        return canvas
    if height >= full[0]["rows"] + 4 and width >= party_width(full) + 6:
        party = full
    elif height >= small[0]["rows"] + 2 and width >= party_width(small) + 4:
        party = small
    elif height >= small[0]["rows"] + 2 and width >= KNIGHT_SMALL["width"] + 2:
        party = [KNIGHT_SMALL]
    else:
        msg = "make the window bigger"
        canvas.text(max(0, (width - len(msg)) // 2), height // 2, msg[:width], "star")
        return canvas
    rows = max(f["rows"] for f in party)
    # the picture: up to 4 rows of sky, the figures, the trail, one row of grass
    scene_h = min(height, rows + 2 + (4 if party is full else 3))
    top = (height - scene_h) // 2
    ground_row = top + scene_h - 2
    deep = party is full and width >= party_width(full) + 24
    scenery(canvas, frame, ground_row, deep, rows, PINES if party is full else PINES_SMALL)
    step = frame // STEP_EVERY
    pw = party_width(party)
    x = (width - pw) // 2
    for y in range(ground_row - rows, ground_row):        # a clear path through the trees
        canvas.clear_span(x - 1, x + pw + 1, y)
    for n, fig in enumerate(party):
        figure(canvas, fig, x, ground_row - fig["rows"], step + n)   # out of step with each other
        x += fig["width"] + GAP
    return canvas


# ── HD mode: the party as fine line art in Braille dots (--hd) ─────────────────
# A Braille character is a 2x4 grid of dots in one terminal cell, so lines can be thin and
# curves smooth: round heads, a real bow, knees that bend. The figures are shapes (lines,
# circles, arcs) in "units": 1 unit = 1 column across = half a row down, so circles are round.
# This mode uses Unicode (U+2800..U+28FF), so it is opt-in; the default stays plain ASCII.
import math  # noqa: E402

WALK_FRAMES = 12          # frames per full walking cycle (two steps)
HIP, THIGH, SHIN = 11.0, 5.5, 5.5
SWING = math.radians(20)  # how far a thigh swings forward and back
KNEE = math.radians(40)   # how much the swinging knee bends
# the stance foot slides back one stride per half cycle; the ground scrolls at that speed
STRIDE = 2 * (THIGH + SHIN) * math.sin(SWING)
HD_SPEED = STRIDE / (WALK_FRAMES / 2)
BRAILLE = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (1, 0): 0x08,
           (1, 1): 0x10, (1, 2): 0x20, (0, 3): 0x40, (1, 3): 0x80}


class Dots:
    """A layer of Braille dots over the canvas: 2 dots across and 4 down per cell."""

    def __init__(self, canvas):
        self.canvas, self.bits, self.color = canvas, {}, {}

    def plot(self, dx, dy, color):
        dx, dy = int(math.floor(dx + 0.5)), int(math.floor(dy + 0.5))
        cell = (dx // 2, dy // 4)
        if 0 <= cell[0] < self.canvas.w and 0 <= cell[1] < self.canvas.h:
            self.bits[cell] = self.bits.get(cell, 0) | BRAILLE[(dx % 2, dy % 4)]
            self.color[cell] = color

    def unplot(self, dx, dy):
        cell = (dx // 2, dy // 4)
        if cell in self.bits:
            self.bits[cell] &= ~BRAILLE[(dx % 2, dy % 4)]

    def clear_cells(self, x0, x1, row):
        for x in range(x0, x1):
            self.bits.pop((x, row), None)

    def flush(self):
        for (x, y), b in self.bits.items():
            if b:
                self.canvas.put(x, y, chr(0x2800 + b), self.color[(x, y)])


class Pen:
    """Draws shapes into the dot layer around an origin (the figure's feet on the ground)."""

    def __init__(self, dots, ox, ground_row, color):
        self.d, self.ox, self.gy, self.color = dots, ox, ground_row, color

    def dot(self, x, y):                       # units -> dot coordinates
        return (self.ox + x) * 2, (self.gy + y / 2) * 4

    def line(self, x0, y0, x1, y1, color=None, dash=False):
        (ax, ay), (bx, by) = self.dot(x0, y0), self.dot(x1, y1)
        n = int(max(abs(bx - ax), abs(by - ay)) * 2) + 1
        for i in range(n + 1):
            if dash and (i * 4 // n if n else 0) % 2 and (i // 3) % 2:
                continue
            t = i / n
            self.d.plot(ax + (bx - ax) * t, ay + (by - ay) * t, color or self.color)

    def dashed(self, x0, y0, x1, y1, on=1.6, off=1.2, color=None):
        length = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while pos < length:
            end = min(length, pos + on)
            self.line(x0 + (x1 - x0) * pos / length, y0 + (y1 - y0) * pos / length,
                      x0 + (x1 - x0) * end / length, y0 + (y1 - y0) * end / length, color)
            pos += on + off

    def path(self, pts, **kw):
        for (a, b), (c, d) in zip(pts, pts[1:]):
            self.line(a, b, c, d, **kw)

    def arc(self, cx, cy, rx, ry, t0=0, t1=360, color=None):
        """An ellipse or part of one; degrees, 0 = right, 90 = down."""
        steps = int(max(rx, ry) * 12) + 12
        for i in range(steps + 1):
            t = math.radians(t0 + (t1 - t0) * i / steps)
            self.d.plot(*self.dot(cx + rx * math.cos(t), cy + ry * math.sin(t)), color or self.color)

    def spot(self, x, y, color=None):
        self.d.plot(*self.dot(x, y), color or self.color)

    def text(self, x, y, s, color=None):
        """Plain characters over the drawing (the shield's marks, the star)."""
        col, row = int(math.floor(self.ox + x + 0.5)), int(math.floor(self.gy + y / 2 + 0.5))
        for i, ch in enumerate(s):
            self.d.bits.pop((col + i, row), None)
            self.d.canvas.put(col + i, row, ch, color or self.color)

    def erase(self, pts):
        """Clear the dots inside a polygon, so what is in front hides what is behind.
        A scanline fill: per dot row, where the edges cross it, cleared in pairs."""
        poly = [self.dot(x, y) for x, y in pts]
        edges = list(zip(poly, poly[1:] + poly[:1]))
        ys = [p[1] for p in poly]
        bits = self.d.bits
        for dy in range(int(math.ceil(min(ys))), int(max(ys)) + 1):
            if not any((x // 2, dy // 4) in bits for x in range(0, self.d.canvas.w * 2, 2)):
                continue
            xs = sorted(xi + (dy - yi) * (xj - xi) / (yj - yi)
                        for (xi, yi), (xj, yj) in edges if (yi > dy) != (yj > dy))
            for x0, x1 in zip(xs[::2], xs[1::2]):
                for dx in range(int(math.ceil(x0)), int(x1) + 1):
                    self.d.unplot(dx, dy)


def walk_legs(pen, phase, spread=1.0):
    """Two legs with boots. `phase` runs 0..1 over a full cycle; the far leg is drawn first."""
    for k, side in ((0.5, -1), (0.0, 1)):
        p = 2 * math.pi * (phase + k)
        a = SWING * math.sin(p)                            # thigh angle, forward is positive
        bend = KNEE * max(0.0, math.cos(p))                 # the knee bends while the leg swings
        for off in (-spread / 2, spread / 2):               # two strokes: a leg with some width
            hx, hy = side * 0.9 + off, -HIP
            kx, ky = hx + THIGH * math.sin(a), hy + THIGH * math.cos(a)
            fx, fy = kx + SHIN * math.sin(a - bend), ky + SHIN * math.cos(a - bend)
            pen.line(hx, hy, kx, ky)
            pen.line(kx, ky, fx, fy)
        pen.line(fx - spread, fy, fx + 2.4, fy)             # the boot
        pen.line(fx + 2.4, fy, fx + 1.6, fy - 1.2)


def draw_archer(pen, phase):
    walk_legs(pen, phase)
    pen.path([(-3.4, -12), (-3.8, -8.5), (3.8, -8.5), (3.4, -12)])     # shorts
    pen.path([(-3, -20), (-3.4, -12), (3.4, -12), (3, -20)])            # tunic
    pen.line(-3.4, -13.4, 3.4, -13.4)                                    # belt
    pen.arc(0, -24.5, 3.1, 3.1)                                         # head
    pen.spot(-1.1, -25), pen.spot(1.1, -25)                             # eyes
    pen.path([(-2.4, -27.3), (0, -31.5), (2.4, -27.3)])                 # cap
    pen.line(-3.6, -27.4, 3.6, -27.4)
    pen.path([(-3, -19.5), (-6.8, -16.5), (-6.8, -23)])                 # arm up, holding arrows
    for dx in (-1.4, 0, 1.4):
        pen.line(-6.8, -23, -6.8 + dx, -26.5)
    pen.line(3, -19, 7.6, -18.6)                                        # arm out to the bow
    pen.arc(8.2, -18.6, 0.7, 0.7)
    pen.dashed(9, -18.6, 16.8, -18.6)                                    # the arrow
    pen.path([(15.6, -20), (17.2, -18.6), (15.6, -17.2)])
    pen.arc(9.4, -18.6, 4.6, 10, -90, 90)                               # the bow


def draw_mage(pen, phase):
    walk_legs(pen, phase, spread=0.9)
    robe = [(-3, -20.5), (-5, -8), (5, -8), (3, -20.5)]
    pen.erase(robe)                                                     # the robe hides the thighs
    pen.path(robe + [robe[0]])
    pen.dashed(-3, -20.5, -10, -0.5, 1.4, 0.9)                          # the cape, down to the ground
    pen.dashed(-10, -0.5, -5.5, -0.5, 1.4, 0.9)
    pen.dashed(-2.4, -17.5, -6.6, -2.5, 1.4, 0.9)
    pen.arc(0, -24, 3, 3)                                               # head
    pen.spot(-1.1, -24.4), pen.spot(1.1, -24.4)
    pen.line(-5.6, -27, 5.6, -27)                                       # hat brim
    pen.path([(-3.2, -27), (-1, -34.5), (1.4, -36.5), (3.8, -35.2)])    # the hat, tip bent over
    pen.path([(3.2, -27), (1.4, -33.6), (1.4, -36.5)])
    pen.line(3, -20, 8.2, -17.4)                                        # arm to the staff
    pen.line(9.2, 0, 9.2, -32)                                          # the staff
    pen.arc(9.2, -17.4, 1, 1)                                           # hand on the staff
    pen.text(9.2, -34, "*", "star")


def draw_knight(pen, phase):
    walk_legs(pen, phase)
    pen.path([(-3.2, -20), (-3, -12), (3, -12), (3.2, -20), (-3.2, -20)])   # body
    pen.line(-3, -13.4, 3, -13.4)
    pen.path([(-3, -12), (-3.6, -9), (3.6, -9), (3, -12)])
    pen.arc(0, -24.6, 3.4, 3.8)                                         # helmet
    pen.line(0, -28.4, 0, -30.6)                                        # crest
    pen.arc(0.8, -31, 1.2, 0.8, 180, 360)
    pen.path([(-2, -25.8), (2.2, -25.8), (2.2, -23.8), (-2, -23.8), (-2, -25.8)])   # visor
    pen.line(0, -25.8, 0, -23.8)
    pen.path([(3.2, -19), (6, -15.6), (8.2, -17.6)])                    # sword arm
    pen.arc(8.2, -17.6, 0.9, 0.9)
    pen.line(9, -19, 18, -34)                                           # the blade, held high
    pen.line(6.6, -20.6, 10.8, -17.2)                                   # crossguard
    shield = [(-6.2 + 4.6 * math.cos(t / 12 * 2 * math.pi), -15 + 9.6 * math.sin(t / 12 * 2 * math.pi)) for t in range(12)]
    pen.erase(shield)                                                   # the shield is in front
    pen.arc(-6.2, -15, 4.6, 9.6)
    pen.text(-7.6, -19, "#!")
    pen.text(-7.6, -15, "#")
    pen.text(-5.2, -11, "+")


HD_PARTY = [         # (draw, color, left, right): the extent in columns around the feet
    (draw_archer, "archer", -9, 18),
    (draw_mage, "mage", -11, 11),
    (draw_knight, "knight", -12, 19),
]
HD_ROWS = 19         # the tallest figure (the mage's hat), in rows
HD_GAP = 3
HD_PINES = {"tall": 40, "mid": 30, "small": 20}


def hd_party_width():
    return sum(r - l + 1 for _, _, l, r in HD_PARTY) + HD_GAP * (len(HD_PARTY) - 1)


def hd_pine(pen, x, height):
    """A pine like the reference: a tip, then a few pairs of branch strokes that widen, and a
    bare trunk below the crown."""
    pen.line(x, 0, x, -height)
    crown, y, n = height * 0.62, -height + 1.5, 0
    while y < -height + crown:
        w = 1.0 + n * 1.15
        for k in (0.0, 1.1):                               # two strokes a side, like a brush
            pen.line(x - 0.5 - k, y + k, x - w - k * 0.6, y + w * 1.35 + k)
            pen.line(x + 0.5 + k, y + k, x + w + k * 0.6, y + w * 1.35 + k)
        y += 3.4
        n += 1


def hd_scene(canvas, width, frame, ground_row, deep):
    """Stars, two layers of pines, bushes, the trail and grass; then the party, all in dots."""
    w, dots = canvas.w, Dots(canvas)
    rnd = random.Random(w)
    for i in range(max(4, w // 8)):
        x, y = rnd.randrange(w), rnd.randrange(max(1, ground_row - HD_ROWS - 1))
        big = rnd.random() < 0.35
        canvas.put(x, y, "*" if big != ((frame // 6 + i) % 7 == 0) else ".", "star")
    speeds = {"far": HD_SPEED * 0.3, "near": HD_SPEED * 0.6, "ground": HD_SPEED}

    def spots(x, layer):
        base = int(x - frame * speeds[layer]) % TILE
        return range(base - TILE * ((base + 24) // TILE + 1), w + 24, TILE)

    far, near = Pen(dots, 0, ground_row, "pine_far"), Pen(dots, 0, ground_row, "pine")
    if deep:
        for x, kind in FAR:
            for sx in spots(x, "far"):
                hd_pine(far, sx, HD_PINES[kind] * 0.65)
    for x, kind in NEAR:
        for sx in spots(x, "near"):
            h = HD_PINES[kind]
            near.erase([(sx - h * 0.5, 0), (sx, -h - 1), (sx + h * 0.5, 0)])   # near pines hide far ones
            hd_pine(near, sx, h)
    pw = hd_party_width()
    px = (width - pw) // 2
    for y in range(ground_row - HD_ROWS - 1, ground_row):                  # a clear path for the party
        dots.clear_cells(px - 1, px + pw + 1, y)
    x = px
    for n, (draw, color, left, right) in enumerate(HD_PARTY):
        phase = ((frame % WALK_FRAMES) / WALK_FRAMES + n * 0.3) % 1.0         # out of step
        draw(Pen(dots, x - left, ground_row, color), phase)
        x += right - left + 1 + HD_GAP
    dots.flush()
    for x in GROUND:
        for sx in spots(x, "ground"):
            if not (px - 8 < sx < px + pw + 2):
                solid(canvas, BUSH, sx, ground_row - len(BUSH), "bush")
    shift = int(frame * speeds["ground"])
    for x in range(w):
        if (x + shift) % 2 == 0:
            canvas.put(x, ground_row, ".", "trail")
    for x, tuft in GRASS:
        for sx in spots(x, "ground"):
            canvas.text(sx, ground_row + 1, tuft, "tuft")


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
    ap.add_argument("--ascii", action="store_true", help="plain ASCII figures instead of the fine line art")
    ap.add_argument("--frames", type=int, default=0, help="print this many plain frames and exit")
    ap.add_argument("--width", type=int, default=0, help="with --frames: the width to draw")
    ap.add_argument("--height", type=int, default=0, help="with --frames: the height to draw")
    a = ap.parse_args()
    global HD
    HD = not a.ascii
    if HD and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")      # Windows consoles default to a code page
        except (ValueError, OSError):
            HD = False
    if HD and not a.frames and os.name != "nt" and "UTF-8" not in (os.environ.get("LC_ALL") or os.environ.get("LC_CTYPE")
                                                                   or os.environ.get("LANG") or "UTF-8").upper().replace("UTF8", "UTF-8"):
        HD = False                                        # a terminal set to another charset: plain ASCII
    if a.frames:
        size = shutil.get_terminal_size((100, 16))
        for f in range(a.frames):
            print(scene(a.width or size.columns, a.height or 16, f * STEP_EVERY).render(color=False))
        return
    play(max(1.0, a.fps))


if __name__ == "__main__":
    main()
