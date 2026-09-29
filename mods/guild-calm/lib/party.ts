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

/** Thirteen rows: sky, eleven of forest and figures, and the ground. */
export const PARTY_ROWS = 13;

const MAX_COLUMNS = 512;
const MARGIN = 2;
const DEFAULT_COLOR = 0x01000000;
const SPACE = 32;
const GROUND_ROW = PARTY_ROWS - 1;

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
  return Math.max(60, Math.min(MAX_COLUMNS, (viewportColumns ?? 80) - MARGIN));
}

// ── The adventurers: original designs, ten rows each, standing on the ground ──
// Eight body rows and two leg frames; `flip` starts a figure on the other frame so the three
// do not march in lockstep.
type Figure = { rows: string[]; legs: [string[], string[]]; color: keyof PartyPalette; flip: boolean };

const ARCHER: Figure = {            // hooded, a quiver on the back, bow drawn, arrow nocked
  rows: ["     .-.         ",
         "    /  _\\   |\\   ",
         "    \\(o )   | \\  ",
         "   __) (    |  \\ ",
         "  [##]\\|\\---+--->",
         "  [##] |    |  / ",
         "   ''  |    | /  ",
         "      / \\   |/   "],
  legs: [["     /   \\       ", "    /_/ \\_\\      "],
         ["      | |        ", "     _| |_       "]],
  color: "archer", flip: false,
};

const WIZARD: Figure = {            // pointed hat, beard, long robe, staff (its star twinkles)
  rows: ["       /\\    *   ",
         "      /  \\  -+-  ",
         "     / /\\ \\  |   ",
         "    /______\\ |   ",
         "     (o  o) \\|   ",
         "     ( \\/ )  |   ",
         "    /\\\\\\/// \\|   ",
         "   /  |||   \\|   "],
  legs: [["  /   |||    |   ", " /____/ \\____|   "],
         ["  /   |||    |   ", " /____|_|____|   "]],
  color: "wizard", flip: true,
};

const KNIGHT: Figure = {            // helmet with a visor, a cape behind, sword raised forward
  rows: ["      .-.        ",
         "     /___\\    /  ",
         "     |[=]|   /   ",
         "   __|___|__/    ",
         "  / /| ## |/     ",
         " / / | ## |      ",
         "/_/  |____|      ",
         "      |  |       "],
  legs: [["     /    \\      ", "    /_/  \\_\\     "],
         ["      |  |       ", "     _|  |_      "]],
  color: "knight", flip: false,
};

// Walking right: the archer covers the back, the wizard walks in the middle, the knight leads.
const PARTY: Figure[] = [ARCHER, WIZARD, KNIGHT];
const GAP = 3;
const PARTY_WIDTH = PARTY.reduce((w, f) => w + f.rows[0]!.length, 0) + GAP * (PARTY.length - 1);

// ── The forest: tall pines, small pines, bushes with grass, along a long repeating strip ──
const TALL_PINE = ["     ^     ", "    /|\\    ", "   //|\\\\   ", "  ///|\\\\\\  ", "    /|\\    ", "   //|\\\\   ",
                   "  ///|\\\\\\  ", " ////|\\\\\\\\ ", "   //|\\\\   ", "  ///|\\\\\\  ", "     |     ", "     |     "];
const SMALL_PINE = ["   ^   ", "  /|\\  ", " //|\\\\ ", "  /|\\  ", " //|\\\\ ", "   |   "];
const BUSH = [" .--. ", "(____)"];
const STRIP: Array<[number, "tall" | "small" | "bush"]> = [
  [0, "tall"], [14, "small"], [22, "bush"], [34, "tall"], [47, "small"], [56, "bush"],
];
const STRIP_LEN = 64;
const GROUND = ".,  '. ^^  . ,'.  ^. ,  .' ,. ^^ '.  ,. '";

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

  // Sky: stars over the top rows that twinkle, and a crescent moon near the right edge.
  for (let c = 3; c < columns; c += 9) {
    const twinkle = (c * 7 + Math.floor(tick / 5)) % 5 === 0;
    put((c * 13) % 3, c, twinkle ? "*" : ".", palette.sky);
  }
  const moon = columns - 10;
  draw(0, moon, " .-.", palette.sky);
  draw(1, moon, "(  ", palette.sky);
  draw(2, moon, " '-'", palette.sky);

  // Forest and ground drift left slowly: the world passing a party that walks right.
  const drift = Math.floor(tick / 5);
  const shift = (x: number, span: number) => ((((x - drift) % span) + span) % span);
  for (let c = 0; c < columns; c++) {
    const g = GROUND[shift(c, GROUND.length)]!;
    if (g !== " ") put(GROUND_ROW, c, g, palette.ground);
  }
  const standOn = (art: string[], x: number, color: number) =>        // bottom row sits on the ground
    art.forEach((line, i) => draw(GROUND_ROW - art.length + i, x, line, color));
  for (let base = -STRIP_LEN; base < columns + STRIP_LEN; base += STRIP_LEN) {
    for (const [offset, kind] of STRIP) {
      const x = base + shift(offset, STRIP_LEN);
      if (x < -12 || x > columns) continue;
      if (kind === "tall") standOn(TALL_PINE, x, palette.tree);
      else if (kind === "small") standOn(SMALL_PINE, x, palette.tree);
      else standOn(BUSH, x, palette.bush);
    }
  }

  // The party walks in the foreground: its block is cleared of trees and bushes (a path
  // through the forest) and only the ground comes back under its feet. Without this,
  // trunks and branches mix into the figures.
  const step = Math.floor(tick / 2);
  let x = (step % (columns + PARTY_WIDTH + 4)) - PARTY_WIDTH;
  for (let c = x - 1; c <= x + PARTY_WIDTH; c++) {
    for (let row = 1; row < GROUND_ROW; row++) put(row, c, " ", DEFAULT_COLOR);
    const g = GROUND[shift(c, GROUND.length)] ?? " ";
    put(GROUND_ROW, c, g, g === " " ? DEFAULT_COLOR : palette.ground);
  }
  const sparkle = ["*", "+", "."][Math.floor(tick / 3) % 3]!;
  for (const fig of PARTY) {
    const color = palette[fig.color];
    const legs = fig.legs[(step + (fig.flip ? 1 : 0)) % 2]!;
    const art = [...fig.rows, ...legs];
    art.forEach((line, i) => {
      const row = GROUND_ROW - art.length + i;
      [...line].forEach((ch, j) => {
        if (ch === " ") return;
        if (fig === WIZARD && ch === "*") put(row, x + j, sparkle, palette.sky);   // the staff's star
        else put(row, x + j, ch, color);
      });
    });
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
