#!/usr/bin/env python3
"""A QR code for a short text, with no dependency: the phone camera opens the link.

  qr.py text <text>     print it in the terminal (black on white, any terminal theme)
  qr.py svg <text>      print it as SVG

Byte mode, error correction level M, versions 1 to 10 (up to 213 bytes): enough for any
war table link. It follows the QR standard (ISO 18004) in the shape of Nayuki's
public-domain qrcodegen.
"""
import sys

ECC_PER_BLOCK = [None, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26]   # level M, versions 1..10
BLOCKS = [None, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5]
MASKS = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
         lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
         lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
         lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]


def raw_modules(ver):
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        align = ver // 7 + 2
        n -= (25 * align - 10) * align - 55
        if ver >= 7:
            n -= 36
    return n


def data_capacity(ver):
    return raw_modules(ver) // 8 - ECC_PER_BLOCK[ver] * BLOCKS[ver]


def gf_mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def rs_divisor(degree):
    result, root = [0] * (degree - 1) + [1], 1
    for _ in range(degree):
        for j in range(len(result)):
            result[j] = gf_mul(result[j], root)
            if j + 1 < len(result):
                result[j] ^= result[j + 1]
        root = gf_mul(root, 0x02)
    return result


def rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= gf_mul(coef, factor)
    return result


def codewords(text):
    data = text.encode("utf-8")
    ver = next((v for v in range(1, 11) if 4 + (8 if v < 10 else 16) + 8 * len(data) <= data_capacity(v) * 8), None)
    if not ver:
        raise ValueError("too long for a QR code here (over 213 bytes)")
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in reversed(range(8 if ver < 10 else 16))]
    for b in data:
        bits += [(b >> i) & 1 for i in reversed(range(8))]
    cap = data_capacity(ver) * 8
    bits += [0] * min(4, cap - len(bits))
    bits += [0] * (-len(bits) % 8)
    out = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(out) < data_capacity(ver):
        out.append(pad)
        pad ^= 0xEC ^ 0x11
    # split into blocks, add error correction to each, interleave
    nblocks, ecclen, raw = BLOCKS[ver], ECC_PER_BLOCK[ver], raw_modules(ver) // 8
    nshort, shortlen = nblocks - raw % nblocks, raw // nblocks
    div, blocks, k = rs_divisor(ecclen), [], 0
    for i in range(nblocks):
        dat = out[k:k + shortlen - ecclen + (0 if i < nshort else 1)]
        k += len(dat)
        ecc = rs_remainder(dat, div)
        if i < nshort:
            dat = dat + [0]
        blocks.append(dat + ecc)
    result = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != shortlen - ecclen or j >= nshort:
                result.append(blk[i])
    return ver, result


def alignment_positions(ver):
    if ver == 1:
        return []
    n, size = ver // 7 + 2, ver * 4 + 17
    step = (ver * 4 + n * 2 + 1) // (n * 2 - 2) * 2
    return [6] + [size - 7 - step * i for i in reversed(range(n - 1))]


class Matrix:
    def __init__(self, ver):
        self.ver, self.size = ver, ver * 4 + 17
        self.m = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set_fn(self, x, y, dark):
        self.m[y][x], self.fn[y][x] = dark, True

    def function_patterns(self):
        s = self.size
        for i in range(s):
            self.set_fn(6, i, i % 2 == 0)
            self.set_fn(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (s - 4, 3), (3, s - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < s and 0 <= y < s:
                        self.set_fn(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = alignment_positions(self.ver)
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_fn(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format_bits(0)
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                bit, a, b = (bits >> i) & 1 == 1, s - 11 + i % 3, i // 3
                self.set_fn(a, b, bit)
                self.set_fn(b, a, bit)

    def format_bits(self, mask):
        data = 0 << 3 | mask                    # level M is 0b00
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = lambda i: (bits >> i) & 1 == 1
        s = self.size
        for i in range(6):
            self.set_fn(8, i, bit(i))
        self.set_fn(8, 7, bit(6))
        self.set_fn(8, 8, bit(7))
        self.set_fn(7, 8, bit(8))
        for i in range(9, 15):
            self.set_fn(14 - i, 8, bit(i))
        for i in range(8):
            self.set_fn(s - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_fn(8, s - 15 + i, bit(i))
        self.set_fn(8, s - 8, True)

    def place(self, data):
        s, i, right = self.size, 0, self.size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(s):
                for j in range(2):
                    x = right - j
                    y = s - 1 - vert if ((right + 1) & 2) == 0 else vert
                    if not self.fn[y][x] and i < len(data) * 8:
                        self.m[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def mask(self, k):
        f = MASKS[k]
        for y in range(self.size):
            for x in range(self.size):
                if not self.fn[y][x] and f(x, y):
                    self.m[y][x] = not self.m[y][x]

    def penalty(self):
        """Runs of one color, 2x2 boxes and the dark balance: enough to pick a mask the camera likes."""
        s, m, p = self.size, self.m, 0
        for line in m + [list(c) for c in zip(*m)]:
            run = 1
            for a, b in zip(line, line[1:]):
                run = run + 1 if a == b else 1
                if run == 5:
                    p += 3
                elif run > 5:
                    p += 1
        for y in range(s - 1):
            for x in range(s - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    p += 3
        dark = sum(map(sum, m))
        return p + abs(dark * 20 - s * s * 10) // (s * s) * 10


def make(text):
    """The QR modules as rows of booleans (True = dark), without the quiet zone."""
    ver, data = codewords(text)
    best = None
    for k in range(8):
        q = Matrix(ver)
        q.function_patterns()
        q.place(data)
        q.mask(k)
        q.format_bits(k)
        score = q.penalty()
        if best is None or score < best[0]:
            best = (score, q)
    return best[1].m


def terminal(text, quiet=2):
    """Two rows per line with half blocks, colors set explicitly so a dark theme does not invert it."""
    m = make(text)
    s = len(m) + 2 * quiet
    grid = [[False] * s for _ in range(s)]
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            grid[y + quiet][x + quiet] = v
    if s % 2:
        grid.append([False] * s)
    lines = []
    for y in range(0, len(grid), 2):
        cells = []
        for x in range(s):
            top, bottom = grid[y][x], grid[y + 1][x]
            cells.append(f"\033[{30 if top else 97};{40 if bottom else 107}m▀")
        lines.append("".join(cells) + "\033[0m")
    return "\n".join(lines)


def svg(text, quiet=4, scale=8):
    m = make(text)
    s = len(m) + 2 * quiet
    rects = "".join(f'<rect x="{x + quiet}" y="{y + quiet}" width="1" height="1"/>'
                    for y, row in enumerate(m) for x, v in enumerate(row) if v)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {s} {s}" width="{s * scale}" height="{s * scale}" '
            f'shape-rendering="crispEdges"><rect width="{s}" height="{s}" fill="#fff"/><g fill="#000">{rects}</g></svg>')


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("text", "svg"):
        raise SystemExit(__doc__)
    print(terminal(sys.argv[2]) if sys.argv[1] == "text" else svg(sys.argv[2]))
