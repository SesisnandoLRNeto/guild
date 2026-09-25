// The party for guild calm mode: three adventurers walking through a forest, packed as
// Claude Code Raster cells.
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

/** Three rows: heads and gear, bodies, legs. */
export const PARTY_ROWS = 3;

const MAX_COLUMNS = 512;
const MARGIN = 2;
const DEFAULT_COLOR = 0x01000000;
const SPACE = 32;

export type PartyPalette = { knight: number; mage: number; archer: number; tree: number; grass: number };
export type PartyFamily = "dark" | "light";

export const PARTY_PALETTES: Record<PartyFamily, PartyPalette> = {
  dark: { knight: 0x9fb3d9, mage: 0xc39bd3, archer: 0x93c89a, tree: 0x3f6b4a, grass: 0x2c3a2e },
  light: { knight: 0x3e5a8a, mage: 0x7a4f8f, archer: 0x3f7a4f, tree: 0x6f9e7a, grass: 0xb9cbb9 },
};

/** Themes are named like "dark-ansi" or "light"; anything unknown reads well on light. */
export function partyFamily(theme: unknown): PartyFamily {
  return typeof theme === "string" && theme.startsWith("dark") ? "dark" : "light";
}

/** Scene width for a viewport: the working row minus its margin, inside the Raster limit. */
export function partyColumns(viewportColumns: number | undefined): number {
  return Math.max(16, Math.min(MAX_COLUMNS, (viewportColumns ?? 80) - MARGIN));
}

// Each adventurer is three columns by three rows. Two leg frames make the walk.
type Figure = { top: string; body: string; color: keyof PartyPalette };
const ARCHER: Figure = { top: " o)", body: "/|)", color: "archer" }; // bow
const MAGE: Figure = { top: " o*", body: "/||", color: "mage" };     // staff with a star
const KNIGHT: Figure = { top: " o/", body: "/| ", color: "knight" };  // sword held up
const LEGS = ["/ \\", " | "];                                        // stride, then together

// Walking right, the knight leads and the archer covers the back.
const PARTY: Figure[] = [ARCHER, MAGE, KNIGHT];
const PARTY_WIDTH = PARTY.length * 3 + (PARTY.length - 1); // three figures, one column apart

// A tree is three columns: a crown, a wider crown, a trunk.
const TREE = [" ^ ", "/^\\", " | "];

/** One frame: trees drifting left behind the party, the party walking right. */
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

  // The forest scrolls slowly the other way, which is what makes the party look like it
  // is walking through it rather than across a blank line.
  const drift = Math.floor(tick / 6);
  const spacing = 14;
  for (let base = 0; base < columns + spacing; base += spacing) {
    const x = ((((base - drift) % (columns + spacing)) + columns + spacing) % (columns + spacing)) - 3;
    TREE.forEach((line, row) => [...line].forEach((ch, i) => put(row, x + i, ch, palette.tree)));
    put(2, x + 7, ".", palette.grass);
    put(2, x + 10, ",", palette.grass);
  }

  // The party: one step every other tick, legs swapping as it goes.
  const span = columns + PARTY_WIDTH + 2;
  const left = (Math.floor(tick / 2) % span) - PARTY_WIDTH;
  const legs = LEGS[Math.floor(tick / 2) % 2]!;
  PARTY.forEach((fig, n) => {
    const x = left + n * 4;
    const color = palette[fig.color];
    [...fig.top].forEach((ch, i) => put(0, x + i, ch, color));
    [...fig.body].forEach((ch, i) => put(1, x + i, ch, color));
    // offset the stride per figure, so three people do not march in lockstep
    const own = n === 1 ? LEGS[(Math.floor(tick / 2) + 1) % 2]! : legs;
    [...own].forEach((ch, i) => put(2, x + i, ch, color));
  });

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
