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
HD = True                            # the traced scene; --ascii uses the small hand-drawn figures
MODE = {"now": ""}                   # what the last frame drew, said on exit


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
    if HD:
        # the traced scene scales to the window: 26 rows and 90 columns at full size
        k = min(2.2, (height - 1) / 27, (width - 2) / ((PARTY_RIGHT - PARTY_LEFT) / 12 + 4))
        if k >= 0.5:
            trace_scene(canvas, frame, k)
            MODE["now"] = f"traced scene at {round(k * 100)}% size"
            return canvas
        MODE["now"] = f"small ASCII figures: {width}x{height} is too small for the traced scene"
    else:
        MODE["now"] = "small ASCII figures (--ascii)"
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


# ── the traced scene: the reference picture, redrawn as dashed ASCII outlines ──
# The figures, trees and ground are outlines traced from the reference picture, in its own
# pixel coordinates (1536 x 1024, ground at y = 742). Each outline is drawn with the ASCII
# character closest to its angle (- _ / | \), which gives the dashed look. The whole scene
# scales with the window: at scale 1, 12 pixels are one column and 24 pixels are one row.
import math  # noqa: E402

GROUND_Y = 742
WALK_FRAMES = 12          # frames per full walking cycle (two steps)
SWING = math.radians(24)  # how far a thigh swings forward and back
KNEE = math.radians(42)   # how much the swinging knee bends


def stroke_char(dcol, drow):
    """The ASCII character for a stroke going dcol across and drow down (in cells)."""
    a = math.degrees(math.atan2(-drow * 2, dcol)) % 180     # a row is twice as tall as a column
    if a < 22.5 or a >= 157.5:
        return "-"
    if a < 67.5:
        return "/"
    if a < 112.5:
        return "|"
    return "\\"


class Pen:
    """Draws outlines given in picture pixels onto the canvas."""

    def __init__(self, canvas, x0, y0, scale, color):
        self.c, self.x0, self.y0, self.sx, self.sy, self.color = canvas, x0, y0, scale / 12, scale / 24, color

    def at(self, x, y):
        return self.x0 + x * self.sx, self.y0 + y * self.sy

    def line(self, x0, y0, x1, y1, color=None):
        """One character per row on a steep line, one per column on a flat one: no doubled strokes."""
        (c0, r0), (c1, r1) = self.at(x0, y0), self.at(x1, y1)
        ch = stroke_char(c1 - c0, r1 - r0)
        steep = abs(r1 - r0) * 2 >= abs(c1 - c0)
        if steep:
            a, b = sorted((r0, r1))
            rows = range(int(math.floor(a + 0.5)), int(math.floor(b + 0.5)) + 1)
            for row in rows:
                t = 0.0 if r1 == r0 else (row - r0) / (r1 - r0)
                t = min(1.0, max(0.0, t))
                self.c.put(int(math.floor(c0 + (c1 - c0) * t + 0.5)), row, ch, color or self.color)
        else:
            a, b = sorted((c0, c1))
            for col in range(int(math.floor(a + 0.5)), int(math.floor(b + 0.5)) + 1):
                t = 0.0 if c1 == c0 else min(1.0, max(0.0, (col - c0) / (c1 - c0)))
                rf = r0 + (r1 - r0) * t
                row = int(math.floor(rf + 0.5))
                c = "_" if ch == "-" and rf - row > 0.15 else ch     # a flat stroke low in its cell
                self.c.put(col, row, c, color or self.color)

    def path(self, pts, color=None, closed=False):
        pts = list(pts) + ([pts[0]] if closed else [])
        for (a, b), (c, d) in zip(pts, pts[1:]):
            self.line(a, b, c, d, color)

    def arc(self, cx, cy, rx, ry, t0, t1, steps=24):
        return [(cx + rx * math.cos(math.radians(t0 + (t1 - t0) * i / steps)),
                 cy + ry * math.sin(math.radians(t0 + (t1 - t0) * i / steps))) for i in range(steps + 1)]

    def text(self, x, y, s, color=None):
        c, r = self.at(x, y)
        for i, ch in enumerate(s):
            if ch != " ":
                self.c.put(int(math.floor(c + 0.5)) + i, int(math.floor(r + 0.5)), ch, color or self.color)


def leg(pen, hip, phase, thigh, shin, width=10):
    """One leg with a boot. phase 0..1; the thigh swings, the knee bends while the leg comes forward."""
    p = 2 * math.pi * phase
    a = SWING * math.sin(p)
    bend = KNEE * max(0.0, math.cos(p))
    hx, hy = hip
    kx, ky = hx + thigh * math.sin(a), hy + thigh * math.cos(a)
    ax, ay = kx + shin * math.sin(a - bend), ky + shin * math.cos(a - bend)
    for off in (-width, width):                                  # a leg has two sides
        pen.path([(hx + off, hy), (kx + off, ky), (ax + off * 0.8, ay)])
    pen.path([(kx - width, ky - 4), (kx + width, ky - 4)])       # knee
    boot_y = GROUND_Y - 2 if phase % 1.0 > 0.5 or math.cos(p) <= 0 else ay + 30
    pen.path([(ax - width, ay), (ax - width - 2, boot_y), (ax + width + 30, boot_y),
              (ax + width + 24, boot_y - 12), (ax + width, ay - 6)])
    pen.path([(ax - width, ay + 4), (ax + width, ay)])           # cuff


def cape_hem(pts, phase, amount=7):
    """The cape's last points sway a little as the figure walks."""
    return [(x + (amount * math.sin(2 * math.pi * phase + i) if i >= len(pts) - 4 else 0), y)
            for i, (x, y) in enumerate(pts)]


def draw_archer(pen, phase):
    for k, hip in ((0.5, (398, 600)), (0.0, (442, 600))):          # far leg first
        leg(pen, hip, phase + k, 54, 60)
    pen.path(cape_hem([(378, 452), (345, 500), (310, 555), (278, 598), (252, 616), (286, 620), (300, 640), (332, 642)], phase))
    pen.path([(362, 470), (330, 540), (305, 600)])                 # a fold in the cape
    pen.path([(372, 454), (376, 412), (390, 382), (412, 366), (436, 368), (452, 386), (456, 408), (450, 422),
              (446, 434), (436, 442)])                              # the hood over the head
    pen.path([(426, 372), (440, 396), (438, 424)])                  # the hood's edge by the face
    for x0, x1 in ((340, 350), (348, 357), (356, 364)):             # arrows in the quiver
        pen.line(x0, 432, x1 + 2, 398)
    pen.text(342, 392, "\\|/")
    pen.path([(344, 432), (360, 500)])                              # the quiver
    pen.path([(362, 428), (378, 496)])
    pen.path([(382, 456), (408, 440), (434, 446)])                  # the arm drawing the string
    pen.path([(424, 440), (538, 440)])                              # the arm holding the bow
    pen.path([(428, 466), (520, 462)])
    pen.path([(520, 434), (546, 434), (546, 468), (520, 468)])      # the hand on the grip
    pen.path([(378, 454), (382, 528)])                              # tunic
    pen.path([(438, 470), (440, 528)])
    pen.path([(380, 526), (440, 526)])                              # belt and buckle
    pen.path([(380, 540), (440, 540)])
    pen.path([(402, 526), (402, 540), (418, 540), (418, 526)])
    pen.path([(380, 540), (368, 600), (456, 600), (440, 540)])     # skirt of the tunic
    bow = pen.arc(452, 450, 98, 126, -80, 80)
    pen.path(bow)                                                   # the bow
    pen.path([bow[0], (486, 318), (494, 326), (488, 334)])          # its curled tips
    pen.path([bow[-1], (482, 584)])
    pen.path([bow[0], (436, 448), bow[-1]])                         # the string, drawn back
    pen.path([(436, 448), (578, 448)])                              # the arrow
    pen.path([(566, 440), (580, 448), (566, 456)])


def draw_mage(pen, phase):
    for k, hip in ((0.5, (746, 640)), (0.0, (790, 640))):
        leg(pen, hip, phase + k, 42, 50, 8)
    pen.path(cape_hem([(736, 392), (716, 442), (690, 502), (656, 570), (622, 630), (604, 656), (640, 652),
                       (656, 668), (702, 664)], phase, 6))          # the cloak streaming back
    pen.path([(752, 452), (742, 560), (732, 684)])                  # folds of the robe
    pen.path([(772, 456), (776, 560), (780, 690)])
    pen.path([(796, 440), (806, 500), (816, 560), (822, 690)])      # the robe's front
    pen.path([(702, 690), (780, 696), (824, 690)])                  # hem
    pen.path([(742, 540), (792, 540)])                              # belt
    pen.path([(724, 566), (746, 566), (748, 592), (722, 592)], closed=True)   # pouch
    pen.path([(688, 366), (760, 378), (822, 388)])                  # hat brim
    pen.path([(722, 376), (734, 350), (744, 334), (760, 342), (776, 362), (792, 382)])   # the hat, tip bent
    pen.path([(790, 388), (798, 402), (794, 412), (802, 426), (792, 450), (780, 470), (768, 462)])  # face, beard
    pen.path([(790, 446), (816, 496), (848, 500)])                  # the arm to the staff
    pen.path([(796, 472), (810, 516), (846, 516)])
    pen.path([(846, 490), (864, 490), (866, 518), (846, 518)])      # the hand
    pen.path([(876, 394), (868, 442), (860, 490)])                  # the staff
    pen.path([(858, 518), (846, 604), (836, 694)])
    pen.text(877, 378, "*", "star")
    pen.text(862, 356, ".", "star"), pen.text(892, 356, ".", "star")


def draw_knight(pen, phase):
    for k, hip in ((0.5, (1096, 612)), (0.0, (1140, 612))):
        leg(pen, hip, phase + k, 54, 60)
    pen.path(cape_hem([(1100, 432), (1060, 472), (1000, 522), (950, 562), (914, 592), (954, 602), (976, 632),
                       (1002, 652)], phase, 8))                     # the long cape
    pen.path([(1082, 452), (1022, 540), (986, 612)])
    pen.path([(1098, 452), (1104, 402), (1120, 376), (1140, 364), (1160, 372), (1168, 392), (1166, 412),
              (1160, 426), (1150, 434)])                            # hood and face
    pen.path([(1146, 392), (1166, 392)])                            # the eye slit
    pen.path([(1104, 420), (1088, 442)])
    pen.path([(1090, 452), (1086, 524)])                            # tunic
    pen.path([(1146, 456), (1146, 524)])
    pen.path([(1082, 522), (1146, 522)])
    pen.path([(1082, 536), (1146, 536)])
    pen.path([(1084, 536), (1076, 612), (1152, 612), (1146, 536)])
    pen.path([(1140, 462), (1176, 490), (1210, 488)])               # the sword arm
    pen.path([(1140, 488), (1170, 512), (1210, 510)])
    pen.path([(1208, 480), (1230, 480), (1230, 514), (1208, 514)])  # fist
    pen.path([(1224, 476), (1290, 294)])                            # the blade
    pen.path([(1238, 478), (1300, 298)])
    pen.path([(1290, 294), (1298, 284), (1300, 298)])
    pen.path([(1204, 468), (1252, 490)])                            # crossguard
    pen.path([(1220, 514), (1214, 538)])                            # pommel


PARTY_PX = [(draw_archer, "archer"), (draw_mage, "mage"), (draw_knight, "knight")]
PARTY_LEFT, PARTY_RIGHT, SCENE_TOP = 240, 1310, 140     # the party's extent and the sky's top, in pixels
TILE_PX = 1536


def trace_pine(pen, x, top, base, w):
    """A pine as in the picture: a trunk, then chevrons of branches that droop at the tips."""
    pen.line(x, top, x, base)
    layers = max(3, int((base - top) / 70))
    for i in range(layers):
        y = top + 18 + i * (base - top - 100) / layers
        ww = w * (0.35 + 0.65 * (i + 1) / layers)
        pen.path([(x - 5, y), (x - ww, y + 48), (x - ww + 16, y + 50)])
        pen.path([(x + 5, y), (x + ww, y + 48), (x + ww - 16, y + 50)])


TREES = [(125, 265, 660, 82), (230, 405, 680, 46), (1320, 470, 690, 60), (1433, 335, 690, 80),
         (600, 440, 690, 55), (860, 300, 670, 85), (1010, 430, 690, 50)]
BUSHES = [(78, 160), (1352, 1425), (560, 640)]
TUFTS = [55, 240, 405, 560, 760, 905, 1120, 1285, 1475]
STARS = [(195, 157, "*"), (318, 250, "*"), (560, 182, "*"), (865, 200, "*"), (1225, 216, "*"),
         (98, 215, "."), (693, 234, "."), (1087, 157, "."), (1008, 273, "."), (1335, 273, "."), (1462, 251, ".")]


def trace_scene(canvas, frame, scale):
    """The whole traced picture for one frame, centered on the party, the ground scrolling."""
    w, h = canvas.w, canvas.h
    px_w = w * 12 / scale                                    # the window's width, in picture pixels
    center = (PARTY_LEFT + PARTY_RIGHT) / 2
    x0 = w / 2 - center * scale / 12                         # picture x -> column
    y0 = (h - (GROUND_Y + 50 - SCENE_TOP) * scale / 24) / 2 - SCENE_TOP * scale / 24
    step = 2 * 114 * math.sin(SWING) / (WALK_FRAMES / 2)     # pixels the ground moves per frame
    pen = Pen(canvas, x0, y0, scale, "pine")
    view0, view1 = center - px_w / 2, center + px_w / 2

    def repeats(x, speed):
        """Every picture x where something at tile position x shows, scrolled."""
        base = (x - frame * step * speed - view0) % TILE_PX + view0
        return [base + k * TILE_PX for k in range(-1, int(px_w / TILE_PX) + 2) if view0 - 200 < base + k * TILE_PX < view1 + 200]

    rnd = random.Random(w)
    for x, y, ch in STARS:                                   # the sky does not scroll
        for sx in range(int(view0 // TILE_PX) - 1, int(view1 // TILE_PX) + 2):
            twinkle = (frame // 6 + x) % 9 == 0
            pen.text(x + sx * TILE_PX, y, "." if twinkle and ch == "*" else ch, "star")
    moon = pen.arc(1398, 182, 26, 34, 95, 265, 10)
    pen.path([(mx + center - 768, my) for mx, my in moon], "star")
    for tx, top, base, tw in TREES:
        for x in repeats(tx, 0.7):
            trace_pine(pen, x, top, base, tw)
    for b0, b1 in BUSHES:
        for x in repeats(b0, 1.0):
            span = b1 - b0
            pen.path([(x, 736), (x + span * 0.12, 708), (x + span * 0.45, 692), (x + span * 0.8, 698), (x + span, 716)], "bush")
    for tx in TUFTS:
        for x in repeats(tx, 1.0):
            pen.text(x - 12, 728, "\\V/", "bush")
    c0, r0 = pen.at(0, GROUND_Y)
    shift = int(frame * step * scale / 12)
    for col in range(w):                                     # the dashed ground
        if (col + shift) % 4 != 3:
            canvas.put(col, int(r0 + 0.5), "_" if (col + shift) % 7 else ".", "trail")
    # a clear path for the party, then the party
    left, right = pen.at(PARTY_LEFT, 0)[0], pen.at(PARTY_RIGHT, 0)[0]
    top_row = pen.at(0, 280)[1]
    for row in range(int(top_row), int(r0 + 0.5)):
        canvas.clear_span(int(left), int(right) + 1, row)
    for n, (draw, color) in enumerate(PARTY_PX):
        pen.color = color
        draw(pen, ((frame % WALK_FRAMES) / WALK_FRAMES + n * 0.3) % 1.0)
    pen.color = "pine"


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
    ap.add_argument("--ascii", action="store_true", help="the small hand-drawn figures instead of the traced scene")
    ap.add_argument("--frames", type=int, default=0, help="print this many plain frames and exit")
    ap.add_argument("--width", type=int, default=0, help="with --frames: the width to draw")
    ap.add_argument("--height", type=int, default=0, help="with --frames: the height to draw")
    a = ap.parse_args()
    global HD
    HD = not a.ascii
    if a.frames:
        size = shutil.get_terminal_size((100, 16))
        for f in range(a.frames):
            print(scene(a.width or size.columns, a.height or 16, f * STEP_EVERY).render(color=False))
        return
    try:
        play(max(1.0, a.fps))
    finally:
        if MODE["now"]:
            print(f"party.py drew: {MODE['now']}")


if __name__ == "__main__":
    main()
