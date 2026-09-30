// The party for guild calm mode: three small adventurers walking through a night forest,
// packed as Claude Code Raster cells.
//
// Seen from the side like the reference picture: a hooded archer drawing a bow, a wizard in a
// brimmed hat with a staff, a hooded warrior with a cape and a raised sword, all walking right.
// A bit silly too: eyes blink, the archer now and then lets an arrow fly across the screen, the
// warrior swings his sword, the wizard's star sparkles. Eleven rows, so it stays out of the way.
//
// A Raster's `cells` prop is base64 of columns * rows little-endian u32 triplets
// [codePoint, foreground, background]. Colors are 0x00RRGGBB, and bit 24 alone
// (0x01000000) asks for the terminal's own default color. Only plain ASCII is drawn: a wide
// glyph takes two columns and shears the grid.

/** Name of the Raster inside the working row, so a repaint can find it again. */
export const PARTY_KEY = "guild-calm-party";

/** How often the scene moves. The party steps every other tick. */
export const PARTY_TICK_MS = 140;

/** Eleven rows: sky, eight of forest and figures, the trail, and grass. */
export const PARTY_ROWS = 11;

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

// ── the adventurers, seen from the side, walking right ─────────────────────────
// Six rows of body, then two of legs. Change the art here. "o>" is an eye and a nose (it blinks),
// "*" the wizard's star (it sparkles). Rows may differ in length.
type Sprite = { hip: number; rows: string[]; extra?: Record<number, string>; staff?: number };
const ARCHER: Sprite = { hip: 5, rows: [          // hood, quiver on the back, bow drawn, cape behind
  "        __      ,     ",
  " \\|/   /  \\      \\    ",
  "  |   |  o>       |   ",
  "  |   _\\_/o- - - -|-> ",
  "  |  / |==|       |   ",
  " _/_/  |__|      /    ",
] };
const ARCHER_LOOSED: Sprite = { ...ARCHER, rows: ARCHER.rows.map((r, i) => (i === 3 ? "  |   _\\_/o       |   " : r)) };
const MAGE: Sprite = { hip: 6, staff: 21, extra: { 0: "  /", 1: " /_" }, rows: [   // brimmed hat, beard, cloak, staff
  "         /\\          * ",
  "       _/  \\_        | ",
  "    -----------      | ",
  "        ( o>         | ",
  "       / )))\\--------o ",
  "    __/ |   |        | ",
] };
const KNIGHT: Sprite = { hip: 5, rows: [          // hood with a visor, cape behind, sword held high
  "        __        /  ",
  "       /  \\      //  ",
  "      | [=>     //   ",
  "      _\\__/   -+-    ",
  "   __/ |##|--o/      ",
  " _/___ |__|          ",
] };
const KNIGHT_SWING: Sprite = { ...KNIGHT, rows: [   // the sword comes down in front: a mighty swing at nothing
  "        __           ",
  "       /  \\          ",
  "      | [=>          ",
  "      _\\__/          ",
  "   __/ |##|--o-+===- ",
  " _/___ |__|          ",
] };
const LEGS = [                // four walking frames; the boots point the way they walk
  [" /  \\  ", "/_   \\_"],
  [" |  \\  ", " |_  \\_"],
  [" |  |  ", " |_ |_ "],
  [" /  |  ", "/_  |_ "],
];
const COLORS: Array<keyof PartyPalette> = ["archer", "wizard", "knight"];
const WIDTHS = [ARCHER, MAGE, KNIGHT].map((s) => Math.max(...s.rows.map((r) => r.length)) + 1);
const GAP = 2;
const PARTY_WIDTH = WIDTHS.reduce((a, b) => a + b, 0) + GAP * (WIDTHS.length - 1);
const FIGURE_ROWS = 8;

/** The eight rows of a figure for one walking frame. */
function figureRows(sp: Sprite, frame: number, width: number): string[] {
  const rows = sp.rows.map((r) => r.padEnd(width));
  LEGS[frame % 4]!.forEach((leg, i) => {
    const row = [...(" ".repeat(sp.hip) + leg).padEnd(width)];
    [...(sp.extra?.[i] ?? "")].forEach((ch, j) => { if (ch !== " ") row[j] = ch; });   // the cloak down the back
    if (sp.staff !== undefined) row[sp.staff] = "|";                                  // the staff to the ground
    rows.push(row.join(""));
  });
  return rows;
}

// jokes, in ticks
const BLINK_EVERY = 26, ARROW_EVERY = 70, ARROW_FLIGHT = 40, SWING_EVERY = 45, SWING_FOR = 5;

// ── the forest ────────────────────────────────────────────────────────────────
const TALL_PINE = ["    ^    ", "   /|\\   ", "  //|\\\\  ", "  //|\\\\  ", " ///|\\\\\\ ", "////|\\\\\\\\", "    |    ", "    |    "];
const MID_PINE = ["   ^   ", "  /|\\  ", " //|\\\\ ", "///|\\\\\\", "   |   ", "   |   "];
const SMALL_PINE = ["  ^  ", " /|\\ ", "//|\\\\", "  |  "];
const BUSH = [" .^^. ", "(    )"];
const STRIP: Array<[number, "tall" | "mid" | "small" | "bush"]> = [
  [0, "tall"], [11, "small"], [19, "bush"], [29, "mid"], [40, "tall"], [52, "bush"], [60, "small"],
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
  const x0 = Math.floor((columns - PARTY_WIDTH) / 2);
  for (let base = -STRIP_LEN; base < columns + STRIP_LEN; base += STRIP_LEN) {
    for (const [offset, kind] of STRIP) {
      const x = base + shift(offset, STRIP_LEN);
      if (x < -10 || x > columns) continue;
      if (x + 9 > x0 - 1 && x < x0 + PARTY_WIDTH + 1) continue;       // behind the party: hidden whole, never cut in half
      solid(kind === "tall" ? TALL_PINE : kind === "mid" ? MID_PINE : kind === "small" ? SMALL_PINE : BUSH, x,
            kind === "bush" ? palette.bush : palette.tree);
    }
  }
  for (let c = 0; c < columns; c++) {                                 // the dotted trail and the grass under it
    if ((c + drift) % 2 === 0) put(GROUND_ROW, c, ".", palette.sky);
    const g = GRASS[shift(c, GRASS.length)]!;
    if (g !== " ") put(GROUND_ROW + 1, c, g, palette.ground);
  }

  // the party
  const step = Math.floor(tick / 2);
  const blink = tick % BLINK_EVERY < 2;
  const arrowAt = tick % ARROW_EVERY;
  const flying = arrowAt < ARROW_FLIGHT;
  const swinging = tick % SWING_EVERY < SWING_FOR;
  const sparkle = ["*", "+", "x", "+"][Math.floor(tick / 3) % 4]!;
  const sprites = [flying ? ARCHER_LOOSED : ARCHER, MAGE, swinging ? KNIGHT_SWING : KNIGHT];
  let x = x0;
  sprites.forEach((sp, n) => {
    const color = palette[COLORS[n]!];
    const rows = figureRows(sp, step + n, WIDTHS[n]!);
    rows.forEach((line, i) => {
      const row = GROUND_ROW - FIGURE_ROWS + i;
      const text = blink && n < 2 ? line.replace("o>", "->") : line;
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
    draw(GROUND_ROW - FIGURE_ROWS + 3, ax, "-->", palette.archer);
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
