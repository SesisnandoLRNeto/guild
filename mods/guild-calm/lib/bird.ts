// The blue bird sprite for guild calm mode, packed as Claude Code Raster cells.
//
// A Raster's `cells` prop is base64 of columns * rows little-endian u32 triplets
// [codePoint, foreground, background]. Colors are 0x00RRGGBB, and bit 24 alone
// (0x01000000) asks for the terminal's own default color.
//
// Only narrow glyphs are used (box drawing, a bullet, a tilde). A wide glyph would
// take two terminal columns and shear the whole grid.

/** Name of the Raster inside the working row, so a repaint can find it again. */
export const BIRD_KEY = "guild-calm-bird";

/** How often the bird moves. Slow enough to be calm, fast enough to look alive. */
export const BIRD_TICK_MS = 130;

/** Two rows of sky: the bird glides between them. */
export const BIRD_ROWS = 2;

const MAX_COLUMNS = 512;
const MARGIN = 2;
const DEFAULT_COLOR = 0x01000000;

const SPACE = 32;
const WING_UP = 0x2571;   /* ╱ */
const WING_DOWN = 0x2572; /* ╲ */
const WING_FLAT = 0x2500; /* ─ */
const BODY = 0x2022;      /* • */
const STREAK = 0x007e;    /* ~ */

export type BirdPalette = { bird: number; wind: number };
export type BirdFamily = "dark" | "light";

export const BIRD_PALETTES: Record<BirdFamily, BirdPalette> = {
  dark: { bird: 0x7aa2f7, wind: 0x2f3547 },
  light: { bird: 0x3a63c8, wind: 0xc6ccda },
};

/** Themes are named like "dark-ansi" or "light"; anything unknown reads well on light. */
export function birdFamily(theme: unknown): BirdFamily {
  return typeof theme === "string" && theme.startsWith("dark") ? "dark" : "light";
}

/** Sky width for a viewport: the working row minus its margin, inside the Raster limit. */
export function birdColumns(viewportColumns: number | undefined): number {
  return Math.max(8, Math.min(MAX_COLUMNS, (viewportColumns ?? 80) - MARGIN));
}

/** Wing positions, in order. The bird beats down, glides, beats up, glides. */
const WINGS: Array<[number, number]> = [
  [WING_UP, WING_DOWN],
  [WING_FLAT, WING_FLAT],
  [WING_DOWN, WING_UP],
  [WING_FLAT, WING_FLAT],
];

/** One frame of sky: wind streaks drifting left, a bird gliding right and bobbing. */
export function birdFrame(columns: number, tick: number, palette: BirdPalette): string {
  const size = columns * BIRD_ROWS;
  const cp = new Uint32Array(size).fill(SPACE);
  const fg = new Uint32Array(size).fill(DEFAULT_COLOR);

  const put = (row: number, col: number, code: number, color: number) => {
    if (row < 0 || row >= BIRD_ROWS || col < 0 || col >= columns) return;
    const at = row * columns + col;
    cp[at] = code;
    fg[at] = color;
  };

  // Wind: three short streaks drifting the other way, slower than the bird.
  const drift = Math.floor(tick / 5);
  for (const [seed, row] of [[1, 0], [2, 1], [3, 0]] as Array<[number, number]>) {
    const start = (((seed * Math.floor(columns / 3) - drift) % columns) + columns) % columns;
    for (let i = 0; i < 3; i++) put(row, (start + i) % columns, STREAK, palette.wind);
  }

  // Bird: crosses the sky, then comes back around.
  const span = columns + 6;
  const x = (tick % span) - 3;
  const row = Math.sin(tick / 11) > 0 ? 0 : 1;
  const [left, right] = WINGS[Math.floor(tick / 3) % WINGS.length]!;
  put(row, x, left, palette.bird);
  put(row, x + 1, BODY, palette.bird);
  put(row, x + 2, right, palette.bird);

  const bytes = new Uint8Array(size * 12);
  const view = new DataView(bytes.buffer);
  for (let i = 0; i < size; i++) {
    view.setUint32(i * 12, cp[i]!, true);
    view.setUint32(i * 12 + 4, fg[i]!, true);
    view.setUint32(i * 12 + 8, DEFAULT_COLOR, true);
  }
  return encodeBase64(bytes);
}

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/** Padded base64. Written by hand because the hooks runtime may lack Buffer or btoa. */
export function encodeBase64(bytes: Uint8Array): string {
  let out = "";
  let i = 0;
  for (; i + 2 < bytes.length; i += 3) {
    const word = (bytes[i]! << 16) | (bytes[i + 1]! << 8) | bytes[i + 2]!;
    out += ALPHABET[(word >> 18) & 63]! + ALPHABET[(word >> 12) & 63]! + ALPHABET[(word >> 6) & 63]! + ALPHABET[word & 63]!;
  }
  const left = bytes.length - i;
  if (left === 1) {
    const word = bytes[i]! << 16;
    out += ALPHABET[(word >> 18) & 63]! + ALPHABET[(word >> 12) & 63]! + "==";
  } else if (left === 2) {
    const word = (bytes[i]! << 16) | (bytes[i + 1]! << 8);
    out += ALPHABET[(word >> 18) & 63]! + ALPHABET[(word >> 12) & 63]! + ALPHABET[(word >> 6) & 63]! + "=";
  }
  return out;
}
