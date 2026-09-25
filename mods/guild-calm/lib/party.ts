// The party for guild calm mode: three adventurers walking through a night forest,
// packed as Claude Code Raster cells.
//
// A Raster's `cells` prop is base64 of columns * rows little-endian u32 triplets
// [codePoint, foreground, background]. Colors are 0x00RRGGBB, and bit 24 alone
// (0x01000000) asks for the terminal's own default color.
//
// Only plain ASCII glyphs are used. A wide glyph takes two terminal columns and shears
// the whole grid, and ASCII is narrow everywhere.

/** Name of the Raster inside the working row, so a repaint can find it again. */
export const PARTY_KEY = "guild-calm-party";

/** How often the scene moves. The party steps every other tick, the forest slower still. */
export const PARTY_TICK_MS = 140;

/** Seven rows: sky, five of forest and figures, and the ground. */
export const PARTY_ROWS = 7;

const MAX_COLUMNS = 512;
const MARGIN = 2;
const DEFAULT_COLOR = 0x01000000;
const SPACE = 32;

export type PartyPalette = {
  archer: number; wizard: number; knight: number;
  tree: number; bush: number; ground: number; sky: number;
};
export type PartyFamily = "dark" | "light";

export const PARTY_PALETTES: Record<PartyFamily, PartyPalette> = {
  dark: { archer: 0xe8a95c, wizard: 0x7fd3e6, knight: 0xe0675a,
          tree: 0x86b97f, bush: 0x6fa66a, ground: 0x5e8c5a, sky: 0xf2e3a6 },
  light: { archer: 0xb5651d, wizard: 0x1e7fa0, knight: 0xb33a2e,
           tree: 0x3f7d3a, bush: 0x4e8a49, ground: 0x7fa37a, sky: 0xa8841f },
};

/** Themes are named like "dark-ansi" or "light"; anything unknown reads well on light. */
export function partyFamily(theme: unknown): PartyFamily {
  return typeof theme === "string" && theme.startsWith("dark") ? "dark" : "light";
}

/** Scene width for a viewport: the working row minus its margin, inside the Raster limit. */
export function partyColumns(viewportColumns: number | undefined): number {
  return Math.max(40, Math.min(MAX_COLUMNS, (viewportColumns ?? 80) - MARGIN));
}

// ── The adventurers: original designs, five rows each (scene rows 2 to 6) ─────
// Each figure has two leg frames; `flip` swaps which frame it starts on so the three do
// not march in lockstep.
type Figure = { rows: string[]; legs: [string, string]; color: keyof PartyPalette; flip: boolean };

const ARCHER: Figure = {            // hooded, bow drawn, arrow on the string
  rows: ["  ,^.  ",
         "  (_) \\",
         " /|--->",
         "  |   /"],
  legs: ["  / \\  ", "  | |  "],
  color: "archer", flip: false,
};

const WIZARD: Figure = {            // pointed hat, long robe, staff (its star is drawn apart)
  rows: ["   /\\ |",
         "  /__\\|",
         "  (..)|",
         "  /||\\|"],
  legs: [" /_/\\_\\", " /_||_\\"],
  color: "wizard", flip: true,
};

const KNIGHT: Figure = {            // helmet with a visor, shield, sword held forward
  rows: ["   _    ",
         "  [=]  /",
         " (|#|\\/ ",
         "  |_|   "],
  legs: ["  / \\   ", "  | |   "],
  color: "knight", flip: false,
};

// Walking right, the knight leads and the archer covers the back.
const PARTY: Figure[] = [ARCHER, WIZARD, KNIGHT];
const GAP = 3;
const PARTY_WIDTH = PARTY.reduce((w, f) => w + f.rows[0]!.length, 0) + GAP * (PARTY.length - 1);

// ── The forest: pines of two sizes and bushes, repeating along a long strip ────
const TALL_PINE = ["   ^   ", "  /|\\  ", " //|\\\\ ", "///|\\\\\\", "   |   ", "   |   "]; // rows 1..6
const SMALL_PINE = ["  ^  ", " /|\\ ", "//|\\\\", "  |  "];                             // rows 3..6
const BUSH = "(__)";                                                                   // row 6
const STRIP: Array<[number, "tall" | "small" | "bush"]> = [
  [0, "tall"], [10, "small"], [18, "bush"], [27, "tall"], [38, "small"], [47, "bush"],
];
const STRIP_LEN = 60;
const GROUND = ".,  '. ^  . ,'.  ^. ,  .' ,. ^ '.  ,. '";

/** One frame of the night forest with the party walking through it. */
export function partyFrame(columns: number, tick: number, palette: PartyPalette): string {
  const size = columns * PARTY_ROWS;
  const cp = new Uint32Array(size).fill(SPACE);
  const fg = new Uint32Array(size).fill(DEFAULT_COLOR);

  const put = (row: number, col: number, ch: string, color: number) => {
    if (row < 0 || row >= PARTY_ROWS || col < 0 || col >= columns) return;
    const at = row * columns + col;
    cp[at] = ch.charCodeAt(0);
    fg[at] = color;
  };
  const draw = (row: number, col: number, text: string, color: number) =>
    [...text].forEach((ch, i) => { if (ch !== " ") put(row, col + i, ch, color); });

  // Sky: a few stars that twinkle, and a crescent moon near the right edge.
  for (let c = 3; c < columns; c += 11) {
    const twinkle = (c * 7 + Math.floor(tick / 5)) % 5 === 0;
    put((c * 13) % 2, c, twinkle ? "*" : ".", palette.sky);
  }
  const moon = columns - 9;
  draw(0, moon, " .-", palette.sky);
  draw(1, moon, "(", palette.sky);
  draw(2, moon, " '-", palette.sky);

  // Forest and ground drift left slowly: the world passing a party that walks right.
  const drift = Math.floor(tick / 5);
  const shift = (x: number, span: number) => ((((x - drift) % span) + span) % span);
  for (let c = 0; c < columns; c++) {
    const g = GROUND[shift(c, GROUND.length)]!;
    if (g !== " ") put(6, c, g, palette.ground);
  }
  for (let base = -STRIP_LEN; base < columns + STRIP_LEN; base += STRIP_LEN) {
    for (const [offset, kind] of STRIP) {
      const x = base + shift(offset, STRIP_LEN);
      if (x < -8 || x > columns) continue;
      if (kind === "tall") TALL_PINE.forEach((line, i) => draw(1 + i, x, line, palette.tree));
      else if (kind === "small") SMALL_PINE.forEach((line, i) => draw(3 + i, x, line, palette.tree));
      else draw(6, x, BUSH, palette.bush);
    }
  }

  // The party walks in the foreground: the block it occupies is cleared of trees and
  // bushes (a path through the forest), and only the ground texture comes back under
  // its feet. Without this, trunks and branches mix into the figures.
  const step = Math.floor(tick / 2);
  let x = (step % (columns + PARTY_WIDTH + 4)) - PARTY_WIDTH;
  for (let c = x - 1; c <= x + PARTY_WIDTH; c++) {
    for (let row = 1; row <= 5; row++) put(row, c, " ", DEFAULT_COLOR);
    const g = GROUND[shift(c, GROUND.length)] ?? " ";
    put(6, c, g, g === " " ? DEFAULT_COLOR : palette.ground);
  }
  for (const fig of PARTY) {
    const color = palette[fig.color];
    const legs = fig.legs[(step + (fig.flip ? 1 : 0)) % 2]!;
    [...fig.rows, legs].forEach((line, i) => draw(2 + i, x, line, color));
    if (fig === WIZARD) {                                   // the staff's star, above the hat
      put(1, x + 6, ["*", "+", "."][Math.floor(tick / 3) % 3]!, palette.sky);
    }
    x += fig.rows[0]!.length + GAP;
  }

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
