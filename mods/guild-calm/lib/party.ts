// The party for guild calm mode: three small adventurers walking through a night forest,
// packed as Claude Code Raster cells.
//
// Simple and a bit silly on purpose: big round faces that blink, an archer who now and then
// lets an arrow fly across the screen, a warrior who swings his sword, a wizard whose star
// sparkles. Ten rows, so it stays out of the way.
//
// A Raster's `cells` prop is base64 of columns * rows little-endian u32 triplets
// [codePoint, foreground, background]. Colors are 0x00RRGGBB, and bit 24 alone
// (0x01000000) asks for the terminal's own default color. Only plain ASCII is drawn: a wide
// glyph takes two columns and shears the grid.

/** Name of the Raster inside the working row, so a repaint can find it again. */
export const PARTY_KEY = "guild-calm-party";

/** How often the scene moves. The party steps every other tick. */
export const PARTY_TICK_MS = 140;

/** Ten rows: sky, seven of forest and figures, the trail, and grass. */
export const PARTY_ROWS = 10;

const MAX_COLUMNS = 512;
const MARGIN = 2;
const DEFAULT_COLOR = 0x01000000;
const SPACE = 32;
const GROUND_ROW = PARTY_ROWS - 2;

export type PartyPalette = {
  archer: number; wizard: number; knight: number;
  tree: number; bush: number; ground: number; sky: number;
};
export type PartyFamily = "dark" | "light";

export const PARTY_PALETTES: Record<PartyFamily, PartyPalette> = {
  dark: { archer: 0xf0a430, wizard: 0x3ec6ec, knight: 0xef4a3c,
          tree: 0x6fb86a, bush: 0x5fa85a, ground: 0x4f8f4a, sky: 0xf2e3a6 },
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

// ── the adventurers: five rows of body, two of legs ───────────────────────────
// Change the art here. "o.o" is each face (it blinks), "*" the wizard's star (it sparkles).
const ARCHER = [
  "     _/\\_    .    ",
  "    ( o.o)    \\   ",
  "  \\|/|  |\\----|-> ",
  "   |  |__|     |  ",
  "   |  |  |    /   ",
];
const ARCHER_LOOSED = [       // the arrow is gone: it is flying across the screen
  "     _/\\_    .    ",
  "    ( o.o)    \\   ",
  "  \\|/|  |\\-   |   ",
  "   |  |__|     |  ",
  "   |  |  |    /   ",
];
const MAGE = [
  "      /\\      *  ",
  "     /  \\     |  ",
  "    /____\\    |  ",
  "    ( o.o)    |  ",
  "   /|~~~~|\\---o  ",
];
const KNIGHT = [
  "      _^_      / ",
  "     [o.o]    /  ",
  "  .-. |=| \\__+   ",
  " ( # )|  |       ",
  "  '-' |__|       ",
];
const KNIGHT_SWING = [        // the sword comes down in front: a mighty swing at nothing
  "      _^_        ",
  "     [o.o]       ",
  "  .-. |=| \\__+==-",
  " ( # )|  |       ",
  "  '-' |__|       ",
];
const LEGS = [                // four walking frames
  ["     /  \\  ", "    /    \\ "],
  ["     |  \\  ", "    _|   \\ "],
  ["     |  |  ", "    _| _|  "],
  ["     /  |  ", "    /  _|  "],
];

type Figure = { color: keyof PartyPalette; legOffset: number; staff?: number };
const FIGURES: Figure[] = [
  { color: "archer", legOffset: 1 },
  { color: "wizard", legOffset: 0, staff: 14 },
  { color: "knight", legOffset: 1 },
];
const WIDTHS = [ARCHER, MAGE, KNIGHT].map((art) => Math.max(...art.map((r) => r.length)));
const GAP = 3;
const PARTY_WIDTH = WIDTHS.reduce((a, b) => a + b, 0) + GAP * (WIDTHS.length - 1);

// jokes, in ticks
const BLINK_EVERY = 26, ARROW_EVERY = 70, ARROW_FLIGHT = 40, SWING_EVERY = 45, SWING_FOR = 5;

// ── the forest ────────────────────────────────────────────────────────────────
const TALL_PINE = ["   ^   ", "  /|\\  ", " //|\\\\ ", "///|\\\\\\", "   |   ", "   |   "];
const SMALL_PINE = ["  ^  ", " /|\\ ", "//|\\\\", "  |  "];
const BUSH = [" .^^. ", "(    )"];
const STRIP: Array<[number, "tall" | "small" | "bush"]> = [
  [0, "tall"], [11, "small"], [19, "bush"], [30, "tall"], [42, "small"], [50, "bush"], [58, "tall"],
];
const STRIP_LEN = 70;
const GRASS = "  \\V/      ,      \\V/    .     \\V/        ,   \\V/     ";

/** One frame of the night forest with the party walking through it. */
export function partyFrame(columns: number, tick: number, palette: PartyPalette): string {
  const size = columns * PARTY_ROWS;
  const cp = new Uint32Array(size).fill(SPACE);
  const fg = new Uint32Array(size).fill(DEFAULT_COLOR);
  const put = (row: number, col: number, ch: string, color: number) => {
    if (row < 0 || row >= PARTY_ROWS || col < 0 || col >= columns) return;
    cp[row * columns + col] = ch.charCodeAt(0);
    fg[row * columns + col] = color;
  };
  const draw = (row: number, col: number, text: string, color: number) =>
    [...text].forEach((ch, i) => { if (ch !== " ") put(row, col + i, ch, color); });
  const solid = (art: string[], x: number, color: number) =>          // stands on the ground, hides what is behind
    art.forEach((line, i) => {
      const row = GROUND_ROW - art.length + i;
      const first = line.search(/\S/), last = line.length - 1 - [...line].reverse().join("").search(/\S/);
      for (let c = first; c <= last && first >= 0; c++) put(row, x + c, " ", DEFAULT_COLOR);
      draw(row, x, line, color);
    });

  // sky: stars that twinkle, and a small moon
  for (let c = 4; c < columns; c += 11) {
    const twinkle = (c * 7 + Math.floor(tick / 5)) % 6 === 0;
    put(0, c, twinkle ? "*" : ".", palette.sky);
  }
  draw(0, columns - 8, "(", palette.sky);

  // the forest drifts left: the world passing a party that walks right
  const drift = Math.floor(tick / 2);
  const shift = (x: number, span: number) => ((((x - drift) % span) + span) % span);
  for (let base = -STRIP_LEN; base < columns + STRIP_LEN; base += STRIP_LEN) {
    for (const [offset, kind] of STRIP) {
      const x = base + shift(offset, STRIP_LEN);
      if (x < -8 || x > columns) continue;
      solid(kind === "tall" ? TALL_PINE : kind === "small" ? SMALL_PINE : BUSH, x, kind === "bush" ? palette.bush : palette.tree);
    }
  }
  for (let c = 0; c < columns; c++) {                                 // the dotted trail and the grass under it
    if ((c + drift) % 2 === 0) put(GROUND_ROW, c, ".", palette.sky);
    const g = GRASS[shift(c, GRASS.length)]!;
    if (g !== " ") put(GROUND_ROW + 1, c, g, palette.ground);
  }

  // the party, in a clear path through the trees
  const x0 = Math.floor((columns - PARTY_WIDTH) / 2);
  for (let row = 1; row < GROUND_ROW; row++) for (let c = x0 - 1; c <= x0 + PARTY_WIDTH; c++) put(row, c, " ", DEFAULT_COLOR);
  const step = Math.floor(tick / 2);
  const blink = tick % BLINK_EVERY < 2;
  const arrowAt = tick % ARROW_EVERY;
  const flying = arrowAt < ARROW_FLIGHT;
  const swinging = tick % SWING_EVERY < SWING_FOR;
  const sparkle = ["*", "+", "x", "+"][Math.floor(tick / 3) % 4]!;
  const arts = [flying ? ARCHER_LOOSED : ARCHER, MAGE, swinging ? KNIGHT_SWING : KNIGHT];
  let x = x0;
  FIGURES.forEach((fig, n) => {
    const color = palette[fig.color];
    const legs = LEGS[(step + n) % 4]!;
    const rows = [...arts[n]!, ...legs.map((l) => " ".repeat(fig.legOffset) + l)];
    rows.forEach((line, i) => {
      const row = GROUND_ROW - rows.length + i;
      let text = blink ? line.replace("o.o", "-.-") : line;
      if (fig.staff !== undefined && i >= 5) text = text.padEnd(fig.staff + 1).slice(0, fig.staff) + "|" + text.slice(fig.staff + 1);
      [...text].forEach((ch, j) => {
        if (ch === " ") return;
        if (ch === "*" && n === 1) put(row, x + j, sparkle, palette.sky);   // the wizard's star
        else put(row, x + j, ch, color);
      });
    });
    x += WIDTHS[n]! + GAP;
  });

  // the loosed arrow shows up past the party (it flew over their heads) and leaves the screen
  if (flying) {
    const from = x0 + PARTY_WIDTH + 2;
    const ax = from + Math.floor((arrowAt / ARROW_FLIGHT) * (columns - from + 4));
    draw(GROUND_ROW - 5, ax, "-->", palette.archer);
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
