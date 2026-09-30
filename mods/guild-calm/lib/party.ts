// The party for guild calm mode: three tiny adventurers walking right through a night forest,
// fighting what comes at them, packed as Claude Code Raster cells.
//
// Every so often an enemy comes in from the right. Each hero has their own: a bat flies in and
// the archer shoots it, a slime crawls in and the mage throws a spell, a skeleton marches in and
// the knight cuts it down up close. The whole scene is a pure function of the tick, so a fight
// always plays out the same way.
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

/** Five rows: the sky, tall treetops, then heads, bodies and legs on the ground. */
export const PARTY_ROWS = 5;

const MAX_COLUMNS = 512;
const MARGIN = 2;
const DEFAULT_COLOR = 0x01000000;
const SPACE = 32;
const HEAD = 2, BODY = 3, FEET = 4;          // the rows the figures stand on

export type PartyPalette = {
  knight: number; mage: number; archer: number; tree: number; treeFar: number; grass: number; star: number;
  bat: number; slime: number; bones: number; spell: number;
};
export type PartyFamily = "dark" | "light";

export const PARTY_PALETTES: Record<PartyFamily, PartyPalette> = {
  dark: { knight: 0xef4a3c, mage: 0x3ec6ec, archer: 0xf0a430, tree: 0x4fa85a, treeFar: 0x2f5f38, grass: 0x3a6b42,
          star: 0xf2e3a6, bat: 0xb07ad8, slime: 0x9fd04a, bones: 0xe6e1d3, spell: 0x7fe8ff },
  light: { knight: 0xb33a2e, mage: 0x1e7fa0, archer: 0xb5651d, tree: 0x3f7d3a, treeFar: 0x9bb89a, grass: 0x8fb08a,
           star: 0xa8841f, bat: 0x7a3fa8, slime: 0x5a8a1a, bones: 0x6e6a60, spell: 0x0f8fb0 },
};

/** Themes are named like "dark-ansi" or "light"; anything unknown reads well on light. */
export function partyFamily(theme: unknown): PartyFamily {
  return typeof theme === "string" && theme.startsWith("dark") ? "dark" : "light";
}

/** Scene width for a viewport: the working row minus its margin, inside the Raster limit. */
export function partyColumns(viewportColumns: number | undefined): number {
  return Math.max(16, Math.min(MAX_COLUMNS, (viewportColumns ?? 80) - MARGIN));
}

// ── the party: three columns by three rows each, two leg frames make the walk ──
type Figure = { top: string; body: string; color: "archer" | "mage" | "knight" };
const ARCHER: Figure = { top: " o)", body: "/|)", color: "archer" }; // bow
const MAGE: Figure = { top: " o*", body: "/||", color: "mage" };     // staff with a star
const KNIGHT: Figure = { top: " o/", body: "/| ", color: "knight" };  // sword held up
const LEGS = ["/ \\", " | "];                                        // stride, then together

// Walking right, the knight leads and the archer covers the back.
const PARTY: Figure[] = [ARCHER, MAGE, KNIGHT];
const PARTY_WIDTH = PARTY.length * 3 + (PARTY.length - 1); // three figures, one column apart

// ── the forest ────────────────────────────────────────────────────────────────
// Near trees drift faster than far ones, so the forest has depth. Each entry: offset along a
// repeating strip, and what stands there, drawn standing on the ground row.
const TALL = ["  ^  ", " /|\\ ", "//|\\\\", "  |  "];      // rows 1-4
const SMALL = [" ^ ", "/|\\", " | "];                      // rows 2-4
const BUSH = [".^^.", "(  )"];                               // rows 3-4
const NEAR: Array<[number, string[]]> = [[0, TALL], [15, BUSH], [24, SMALL], [40, TALL], [53, BUSH]];
const FAR: Array<[number, string[]]> = [[8, SMALL], [31, SMALL], [47, SMALL]];
const NEAR_LEN = 64, FAR_LEN = 57;
const GRASS = "  \\v/    ,    .   \\v/      ,  .     \\v/   ";

// ── the enemies and the fights ─────────────────────────────────────────────────
// One fight every FIGHT ticks, in turn: bat (the archer shoots), slime (the mage casts),
// skeleton (the knight swings). An enemy starts START columns ahead of the knight and closes
// one column a tick (it walks left while the party walks right).
const FIGHT = 70, START = 34, BURST = 4;
type Foe = { rows: Array<[number, string]>; color: "bat" | "slime" | "bones" };
const FOES: Array<(t: number) => Foe> = [
  (t) => ({ rows: [[HEAD, t % 4 < 2 ? "^o^" : "vov"]], color: "bat" }),                   // flaps its wings
  (t) => ({ rows: [[BODY, t % 4 < 2 ? " __ " : " _  "], [FEET, "(oo)"]], color: "slime" }),
  (t) => ({ rows: [[HEAD, " o "], [BODY, "<|\\"], [FEET, t % 4 < 2 ? "/ \\" : " | "]], color: "bones" }),
];
type Shot = { at: number; speed: number; row: number; glyph: string; color: "archer" | "spell" };
const SHOTS: Array<Shot | undefined> = [          // who answers each foe: when, how fast, what flies
  { at: 4, speed: 2, row: HEAD, glyph: "->", color: "archer" },
  { at: 6, speed: 1.5, row: BODY, glyph: "~*", color: "spell" },
  undefined,                                       // the knight fights up close
];

/** One frame: stars and a moon, two layers of forest, the party walking right, a fight. */
export function partyFrame(columns: number, tick: number, palette: PartyPalette): string {
  const size = columns * PARTY_ROWS;
  const cp = new Uint32Array(size).fill(SPACE);
  const fg = new Uint32Array(size).fill(DEFAULT_COLOR);

  const put = (row: number, col: number, ch: string, color: number) => {
    if (ch === " " || row < 0 || row >= PARTY_ROWS || col < 0 || col >= columns) return;
    const at = row * columns + col;
    cp[at] = ch.charCodeAt(0);
    fg[at] = color;
  };
  const clear = (row: number, c0: number, c1: number) => {
    for (let c = Math.max(0, c0); c <= Math.min(columns - 1, c1); c++) { cp[row * columns + c] = SPACE; fg[row * columns + c] = DEFAULT_COLOR; }
  };
  const text = (row: number, col: number, s: string, color: number) => [...s].forEach((ch, i) => put(row, col + i, ch, color));
  const stand = (art: string[], x: number, color: number) =>
    art.forEach((line, i) => text(FEET - art.length + 1 + i, x, line, color));
  const wrap = (x: number, len: number) => ((x % len) + len) % len;

  // the sky: stars that twinkle, and a crescent moon
  for (let c = 3; c < columns - 10; c += 7) {
    const k = (c * 13) % 5;
    if (k === 1) continue;                                     // gaps, so the stars are not a ruler
    const twinkle = (Math.floor(tick / 5) + c) % 9 === 0;
    put(k === 0 ? 1 : 0, c, twinkle ? "*" : k === 3 ? "*" : ".", palette.star);
  }
  text(0, columns - 7, "(", palette.star);

  // the party: one step every other tick, legs swapping as it goes
  const span = columns + PARTY_WIDTH + 2;
  const left = (Math.floor(tick / 2) % span) - PARTY_WIDTH;
  const front = left + PARTY_WIDTH;                          // the column just ahead of the knight

  // the fight of the moment
  const t = tick % FIGHT;
  const kind = Math.floor(tick / FIGHT) % 3;
  const foeX = (s: number) => front + START - s;
  const shot = SHOTS[kind];
  let hit = START - 3;                                       // the skeleton reaches the knight's blade
  if (shot) {
    for (let s = shot.at; s < FIGHT; s++) {
      if (front + 1 + Math.floor((s - shot.at) * shot.speed) + shot.glyph.length >= foeX(s)) { hit = s; break; }
    }
  }
  const swinging = !shot && t >= hit - 2 && t <= hit + 1;
  const casting = kind === 1 && !!shot && t >= shot.at - 2 && t <= shot.at + 1;

  // what stands in the way of the forest: the party, and the foe or its burst
  const boxes: Array<[number, number]> = [[left - 1, left + PARTY_WIDTH + 1]];
  if (t < hit + BURST) boxes.push([foeX(Math.min(t, hit)) - 2, foeX(Math.min(t, hit)) + 4]);
  const blocked = (x: number, w: number) => boxes.some(([b0, b1]) => x + w > b0 && x <= b1);

  // the forest: near pines and bushes first, then far pines only where nothing near stands
  // (they drift slower, so the forest has depth), then grass on the ground that is still bare
  const far = Math.floor(tick / 10), near = Math.floor(tick / 5);
  const taken = new Uint8Array(size);                      // cells the near forest covers, gaps included
  for (let base = -NEAR_LEN; base < columns + NEAR_LEN; base += NEAR_LEN) {
    for (const [off, art] of NEAR) {
      const x = base + wrap(off - near, NEAR_LEN);
      if (blocked(x, art[art.length - 2]!.length)) continue;       // behind the party or a foe: hidden whole
      art.forEach((line, i) => {
        const row = FEET - art.length + 1 + i, first = line.search(/\S/), last = line.trimEnd().length - 1;
        for (let c = x + first - 1; c <= x + last + 1 && first >= 0; c++) if (c >= 0 && c < columns) taken[row * columns + c] = 1;
      });
      stand(art, x, art === BUSH ? palette.grass : palette.tree);
    }
  }
  for (let base = -FAR_LEN; base < columns + FAR_LEN; base += FAR_LEN) {
    for (const [off, art] of FAR) {
      const x = base + wrap(off - far, FAR_LEN);
      if (blocked(x, art[1]!.length)) continue;
      art.forEach((line, i) => [...line].forEach((ch, j) => {
        const row = FEET - art.length + 1 + i, c = x + j;
        if (ch !== " " && c >= 0 && c < columns && !taken[row * columns + c]) put(row, c, ch, palette.treeFar);
      }));
    }
  }
  for (let c = 0; c < columns; c++) {
    const g = GRASS[wrap(c + near, GRASS.length)]!;
    if (g !== " " && cp[FEET * columns + c] === SPACE && !taken[FEET * columns + c] && !blocked(c, 1)) put(FEET, c, g, palette.grass);
  }

  const legs = LEGS[Math.floor(tick / 2) % 2]!;
  const sparkle = ["*", "+", "x", "+"][Math.floor(tick / 3) % 4]!;
  PARTY.forEach((fig, n) => {
    const x = left + n * 4;
    const color = palette[fig.color];
    let top = fig.top, body = fig.body;
    if (fig === KNIGHT && swinging) { top = " o "; body = "/|-"; put(BODY, x + 3, "-", color); }
    [...top].forEach((ch, i) => put(HEAD, x + i, fig === MAGE && ch === "*" ? (casting ? "@" : sparkle) : ch,
                                    fig === MAGE && ch === "*" ? palette.star : color));
    [...body].forEach((ch, i) => put(BODY, x + i, ch, color));
    const own = n === 1 ? LEGS[(Math.floor(tick / 2) + 1) % 2]! : legs;   // not in lockstep
    [...own].forEach((ch, i) => put(FEET, x + i, ch, color));
  });

  // the foe walks in, and falls in a little burst
  if (t < hit) {
    const foe = FOES[kind]!(t), x = foeX(t);
    for (const [row, s] of foe.rows) text(row, x, s, palette[foe.color]);
  } else if (t < hit + BURST) {
    const x = foeX(hit), row = kind === 0 ? HEAD : BODY;
    clear(row, x - 1, x + 3);
    text(row, x - 1, t < hit + 2 ? "\\*/" : " . ", palette.star);
  }
  // the arrow or the spell in flight
  if (shot && t >= shot.at && t < hit) {
    const x = front + 1 + Math.floor((t - shot.at) * shot.speed);
    text(shot.row, x, shot.glyph, palette[shot.color]);
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
