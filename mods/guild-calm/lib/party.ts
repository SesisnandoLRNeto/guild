// The party for guild calm mode: the sessions that are running right now, drawn as adventurers
// walking right through a night forest and fighting what comes at them, packed as Claude Code
// Raster cells.
//
// Each running session is one hero, chosen by its model: Sonnet is an archer, Opus a mage, Fable
// a paladin, Haiku a warrior, Codex an artificer, and a model the guild does not know walks as a
// wanderer with a torch. A warrior always walks at the front: when no session runs on Haiku the
// guild's own guard takes the place, so the party is never without a blade.
//
// Enemies come in from the right. Quests in trouble send their own creature (a goblin for red
// checks, a troll for a blocked quest, an orc for a failed one); on a quiet road a bat, a slime
// or a skeleton wanders in. Each foe has the hero who answers it: the archer shoots the bat, the
// mage melts the slime, the artificer throws a flask at the goblin, the paladin's light drops the
// troll, and the warrior cuts down whatever reaches the front. The scene is a pure function of
// the tick and the party, so a fight always plays out the same way.
//
// The figures are nine rows tall and drawn in profile, like the reference picture: the archer
// with a drawn bow, the mage in a pointed hat with a staff, the warrior with a cape and a raised
// sword. Change the art in SPRITES; every line is raw text, so backslashes are typed as they show.
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

/** Twelve rows: two of sky, nine of forest and figures, and the grass under their feet. */
export const PARTY_ROWS = 12;

const MAX_COLUMNS = 512;
const MARGIN = 2;
const DEFAULT_COLOR = 0x01000000;
const SPACE = 32;
const FEET = PARTY_ROWS - 2;                 // the row the figures and trees stand on
const GROUND = PARTY_ROWS - 1;               // the grass
const FIGURE_ROWS = 9;
const TOP = FEET - FIGURE_ROWS + 1;          // the first row of a figure
const WIDTH = 18;                            // every sprite is this wide, the arrow included
const GAP = 1;
const STEP = WIDTH + GAP;

// ── who walks and what comes at them ──────────────────────────────────────────
export type Hero = "archer" | "mage" | "paladin" | "warrior" | "artificer" | "wanderer";
export type FoeKind = "bat" | "slime" | "skeleton" | "goblin" | "orc" | "troll";
/** What the road shows: the heroes back to front, and the creatures the quests in trouble send. */
export type Party = { heroes: Hero[]; foes: FoeKind[] };

/** The hero a model walks as. The words match bin/lore.py's classes. */
const HERO_OF: Array<[string, Hero]> = [
  ["fable", "paladin"],
  ["codex", "artificer"],                                  // before "gpt": gpt-5-codex is an artificer
  ["opus", "mage"], ["thinking", "mage"], ["gpt", "mage"], ["o3", "mage"], ["o4", "mage"],
  ["sonnet", "archer"], ["deepseek", "archer"], ["qwen", "archer"], ["mistral", "archer"],
  ["haiku", "warrior"], ["flash", "warrior"], ["mini", "warrior"], ["nano", "warrior"], ["gemini", "warrior"],
];
export function heroFor(model: string | undefined): Hero {
  const m = (model ?? "").toLowerCase();
  for (const [word, hero] of HERO_OF) if (m.includes(word)) return hero;
  return "wanderer";
}

/** The creature a quest in trouble sends down the road, or none when the state is no trouble. */
export function foeFor(state: string | undefined): FoeKind | undefined {
  switch (state) {
    case "checks-red": return "goblin";
    case "blocked": return "troll";
    case "failed": return "orc";
    default: return undefined;
  }
}

/** Walking right, back to front: the ranged ones cover the back, the warrior leads. */
const RANK: Record<Hero, number> = { archer: 0, mage: 1, artificer: 2, wanderer: 3, paladin: 4, warrior: 5 };
const MAX_HEROES = 8;

/** The heroes in marching order, with the guild's guard added when no warrior is among them. */
export function marchingOrder(heroes: readonly Hero[]): Hero[] {
  const sorted = [...heroes].sort((a, b) => RANK[a] - RANK[b]);
  if (!sorted.includes("warrior")) sorted.push("warrior");
  return sorted.slice(-MAX_HEROES);        // too many to draw: the back of the line waits at camp
}

export const DEFAULT_PARTY: Party = { heroes: ["warrior"], foes: [] };

export type PartyPalette = {
  archer: number; mage: number; paladin: number; warrior: number; artificer: number; wanderer: number;
  tree: number; treeFar: number; grass: number; star: number;
  bat: number; slime: number; bones: number; goblin: number; orc: number; troll: number;
  spell: number; light: number; flask: number; flame: number;
};
export type PartyFamily = "dark" | "light";

export const PARTY_PALETTES: Record<PartyFamily, PartyPalette> = {
  dark: { archer: 0xf0a430, mage: 0x3ec6ec, paladin: 0xf5d76e, warrior: 0xef4a3c, artificer: 0xd48cf0, wanderer: 0xc8b89a,
          tree: 0x4fa85a, treeFar: 0x2f5f38, grass: 0x3a6b42, star: 0xf2e3a6,
          bat: 0xb07ad8, slime: 0x9fd04a, bones: 0xe6e1d3, goblin: 0x7fc24f, orc: 0x6f9a3a, troll: 0x9a9a84,
          spell: 0x7fe8ff, light: 0xfff1b0, flask: 0xe6a8ff, flame: 0xffb347 },
  light: { archer: 0xb5651d, mage: 0x1e7fa0, paladin: 0xa8841f, warrior: 0xb33a2e, artificer: 0x8a4fb0, wanderer: 0x7a6a50,
           tree: 0x3f7d3a, treeFar: 0x9bb89a, grass: 0x8fb08a, star: 0xa8841f,
           bat: 0x7a3fa8, slime: 0x5a8a1a, bones: 0x6e6a60, goblin: 0x4f8a2a, orc: 0x3f6a1a, troll: 0x6a6a58,
           spell: 0x0f8fb0, light: 0xc08a10, flask: 0x9a3fb0, flame: 0xc75a10 },
};

/** Themes are named like "dark-ansi" or "light"; anything unknown reads well on light. */
export function partyFamily(theme: unknown): PartyFamily {
  return typeof theme === "string" && theme.startsWith("dark") ? "dark" : "light";
}

/** Scene width for a viewport: the working row minus its margin, inside the Raster limit. */
export function partyColumns(viewportColumns: number | undefined): number {
  return Math.max(40, Math.min(MAX_COLUMNS, (viewportColumns ?? 80) - MARGIN));
}

// ── the heroes: nine rows in profile, walking right; the last two rows are the legs ──
// Each sprite is WIDTH columns. Special cells: the mage's `*` turns and flares, the wanderer's
// `(` and `)(` flicker, the paladin's `+` is the light. The legs sit in columns 5-9 of every
// sprite, so one set of walking frames fits them all.
const R = String.raw;
type Shot = { speed: number; row: number; glyph: string; color: keyof PartyPalette };
type Sprite = { rows: string[]; swing?: string[]; shot?: Shot };
const SPRITES: Record<Hero, Sprite> = {
  archer: {                                               // hood, cape, a drawn bow and the arrow on the string
    rows: [
      R`      __          `,
      R`     (o >     /   `,
      R`   |\ |\ ____/|   `,
      R`   | \| |   (  |->`,
      R`   |  | |    \ |  `,
      R`    \ | |     \|  `,
      R`     \| |      \  `,
    ],
    shot: { speed: 2, row: 3, glyph: "-->", color: "archer" },
  },
  mage: {                                                 // pointed hat, beard, a long robe, the staff with its star
    rows: [
      R`       /\       * `,
      R`      /  \      | `,
      R`    _/____\_    | `,
      R`      (o >~~    | `,
      R`     /|  |\__   | `,
      R`    / |  |   \__| `,
      R`   /  |  |    \ | `,
    ],
    shot: { speed: 1.5, row: 0, glyph: "~*~", color: "spell" },
  },
  warrior: {                                              // helmet, a cape in the wind, the sword held high
    rows: [
      R`              /   `,
      R`       _     /    `,
      R`      [o>   /     `,
      R`  \   /|\__/      `,
      R`   \ / | |        `,
      R`    \  | |        `,
      R`     \ | |        `,
    ],
    swing: [                                              // the sword comes down in front
      R`                  `,
      R`       _          `,
      R`      [o>         `,
      R`  \   /|\__+====> `,
      R`   \ / | |        `,
      R`    \  | |        `,
      R`     \ | |        `,
    ],
  },
  paladin: {                                              // a shield with a cross, the mace raised
    rows: [
      R`       _     _|_  `,
      R`      (o>     |   `,
      R`   __ /|\_____|   `,
      R`  [  ] | |        `,
      R`  [ +] | |        `,
      R`  [  ] | |        `,
      R`   --  | |        `,
    ],
    shot: { speed: 1.5, row: 1, glyph: "+)", color: "light" },
  },
  artificer: {                                            // a toolbox at the hip, a flask held out
    rows: [
      R`       _          `,
      R`      (o>   _     `,
      R`    _ /|\__( )    `,
      R`   | | | |  |     `,
      R`   |_| | |        `,
      R`       | |        `,
      R`       | |        `,
    ],
    shot: { speed: 1.5, row: 2, glyph: "(o)", color: "flask" },
  },
  wanderer: {                                             // a cloak and a torch
    rows: [
      R`            (     `,
      R`       _    )(    `,
      R`      (o>   ||    `,
      R`   |\ /|\___||    `,
      R`   | \ | |  ||    `,
      R`   |  | |  ||     `,
      R`    \ | |         `,
    ],
  },
};
const LEGS: string[][] = [                               // four walking frames, the boots point right
  [R`       / \        `, R`      /   \       `],
  [R`       | \        `, R`       |   \      `],
  [R`       | |        `, R`      _| |_       `],
  [R`       / |        `, R`      /  _|       `],
];

// ── the forest ────────────────────────────────────────────────────────────────
// Near trees drift faster than far ones, so the forest has depth. Each entry: offset along a
// repeating strip, and what stands there, drawn standing on the FEET row.
const TALL = [R`    ^    `, R`   /|\   `, R`  //|\\  `, R`   /|\   `, R`  //|\\  `, R` ///|\\\ `, R`    |    `, R`    |    `];
const MID = [R`   ^   `, R`  /|\  `, R` //|\\ `, R`///|\\\ `, R`   |    `];
const SMALL = [R`  ^  `, R` /|\ `, R`//|\\ `, R`  |   `];
const BUSH = [R` .^^. `, R`(    )`];
const NEAR: Array<[number, string[]]> = [[0, TALL], [16, BUSH], [27, MID], [44, TALL], [59, BUSH], [68, SMALL]];
const FAR: Array<[number, string[]]> = [[9, SMALL], [36, MID], [55, SMALL], [74, MID]];
const NEAR_LEN = 84, FAR_LEN = 93;
const GRASS = R`  \v/    ,    .   \v/      ,  .     \v/   ,   .  `;

// ── the enemies and the fights ─────────────────────────────────────────────────
// One fight every FIGHT ticks. An enemy starts START columns ahead of the front and closes one
// column a tick (it walks left while the party walks right). The hero who answers it shoots from
// where they walk; a foe nobody shoots down reaches the warrior's blade.
const FIGHT = 90, START = 46, BURST = 4;
type Foe = { rows: string[]; color: keyof PartyPalette; answer: Hero; top: number };
const FOE_ART: Record<FoeKind, { color: keyof PartyPalette; answer: Hero; frames: string[][] }> = {
  bat: { color: "bat", answer: "archer", frames: [                      // flies at head height, flapping
    [R`\    _    /`, R` \__(oo)__/`, R`     \/    `],
    [R`     _     `, R` /''(oo)''\ `, R`/    \/   \ `],
  ] },
  slime: { color: "slime", answer: "mage", frames: [                    // crawls low
    [R`   ____   `, R`  / o o \  `, R` (________)`],
    [R`   ____   `, R`  /o   o\  `, R`(_________)`],
  ] },
  skeleton: { color: "bones", answer: "warrior", frames: [
    [R`  ___  `, R` (x x) `, R`  \_/  `, R` \-|-/ `, R`  -|-  `, R`  -|-  `, R`  / \  `, R` /   \ `],
    [R`  ___  `, R` (x x) `, R`  \_/  `, R` \-|-/ `, R`  -|-  `, R`  -|-  `, R`  | |  `, R` _| |_ `],
  ] },
  goblin: { color: "goblin", answer: "artificer", frames: [            // small, a dagger out front
    [R`   _    `, R`<-<(o<  `, R`   /|\  `, R`    |   `, R`   / \  `, R`  /   \ `],
    [R`   _    `, R`<-<(o<  `, R`   /|\  `, R`    |   `, R`   | |  `, R`  _| |_ `],
  ] },
  orc: { color: "orc", answer: "warrior", frames: [                    // big, a club raised
    [R` \        `, R`  \   __  `, R`   \ <oo] `, R`    \_/|\ `, R`     [###]`, R`     [###]`, R`      | | `, R`      / \ `, R`     /   \ `],
    [R` \        `, R`  \   __  `, R`   \ <oo] `, R`    \_/|\ `, R`     [###]`, R`     [###]`, R`      | | `, R`      | | `, R`     _| |_`],
  ] },
  troll: { color: "troll", answer: "paladin", frames: [                // tall and wide, arms down
    [R`    ___    `, R`   ( o )   `, R` __|___|__ `, R`|  |   |  |`, R`|  |   |  |`, R`|__|   |__|`, R`   |   |   `, R`   /   \   `, R`  /     \  `],
    [R`    ___    `, R`   ( o )   `, R` __|___|__ `, R`|  |   |  |`, R`|  |   |  |`, R`|__|   |__|`, R`   |   |   `, R`   |   |   `, R`  _|   |_  `],
  ] },
};
const QUIET_ROAD: FoeKind[] = ["bat", "slime", "skeleton"];
function foeOf(kind: FoeKind, t: number): Foe {
  const art = FOE_ART[kind];
  const rows = art.frames[Math.floor(t / 3) % art.frames.length]!;
  // the bat flies: its rows sit at head height, everything else stands on the FEET row
  const top = kind === "bat" ? TOP + 1 : FEET - rows.length + 1;
  return { rows, color: art.color, answer: art.answer, top };
}
const foeWidth = (kind: FoeKind) => Math.max(...FOE_ART[kind].frames[0]!.map((r) => r.length));

/** One frame: stars and a moon, two layers of forest, the party walking right, a fight. */
export function partyFrame(columns: number, tick: number, palette: PartyPalette, party: Party = DEFAULT_PARTY): string {
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
    if (row < 0 || row >= PARTY_ROWS) return;
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
  text(1, columns - 7, " )", palette.star);

  // the party: as many heroes as the road is wide for, one step every other tick
  const fit = Math.max(1, Math.floor((columns - START - 4) / STEP));
  const heroes = marchingOrder(party.heroes).slice(-fit);
  const width = heroes.length * STEP - GAP;
  const span = columns + width + 2;
  const left = (Math.floor(tick / 2) % span) - width;
  const front = left + width;                                // the column just ahead of the warrior
  const heroX = (n: number) => left + n * STEP;

  // the fight of the moment: a creature a quest in trouble sent, or whatever a quiet road has
  const t = tick % FIGHT;
  const round = Math.floor(tick / FIGHT);
  const road = party.foes.length > 0 ? party.foes : QUIET_ROAD;
  const kind = road[round % road.length]!;
  const foeX = (s: number) => front + START - s;
  // who answers: the hero this foe belongs to if they walk with us, else the warrior up close
  const answerer = heroes.lastIndexOf(FOE_ART[kind].answer);
  const shooter = answerer >= 0 ? answerer : heroes.length - 1;
  const shot = SPRITES[heroes[shooter]!]!.shot;
  const shotAt = 6 + (heroes.length - 1 - shooter);          // the back of the line takes a beat longer to see it
  const melee = START - 4;                                   // the foe reaches the warrior's blade
  let hit = melee;
  if (shot) {
    for (let s = shotAt; s < melee; s++) {
      if (front + 1 + Math.floor((s - shotAt) * shot.speed) + shot.glyph.length >= foeX(s)) { hit = s; break; }
    }
  }
  const shotLands = shot !== undefined && hit < melee;
  const swinging = !shotLands && t >= hit - 3 && t <= hit + 1;
  const casting = shotLands && t >= shotAt - 3 && t <= shotAt + 2;

  // what stands in the way of the forest: the party, and the foe or its burst
  const fw = foeWidth(kind);
  const boxes: Array<[number, number]> = [[left - 1, left + width + 1]];
  if (t < hit + BURST) boxes.push([foeX(Math.min(t, hit)) - 2, foeX(Math.min(t, hit)) + fw + 1]);
  const blocked = (x: number, w: number) => boxes.some(([b0, b1]) => x + w > b0 && x <= b1);

  // the forest: near pines and bushes first, then far pines only where nothing near stands
  // (they drift slower, so the forest has depth), then grass on the ground row
  const far = Math.floor(tick / 10), near = Math.floor(tick / 5);
  const taken = new Uint8Array(size);                      // cells the near forest covers, gaps included
  for (let base = -NEAR_LEN; base < columns + NEAR_LEN; base += NEAR_LEN) {
    for (const [off, art] of NEAR) {
      const x = base + wrap(off - near, NEAR_LEN);
      const w = Math.max(...art.map((r) => r.length));
      if (blocked(x, w)) continue;                           // behind the party or a foe: hidden whole
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
      if (blocked(x, Math.max(...art.map((r) => r.length)))) continue;
      art.forEach((line, i) => [...line].forEach((ch, j) => {
        const row = FEET - art.length + 1 + i, c = x + j;
        if (ch !== " " && c >= 0 && c < columns && !taken[row * columns + c]) put(row, c, ch, palette.treeFar);
      }));
    }
  }
  for (let c = 0; c < columns; c++) {
    const g = GRASS[wrap(c + near, GRASS.length)]!;
    if (g !== " ") put(GROUND, c, g, palette.grass);
  }

  const stride = Math.floor(tick / 2);
  const sparkle = ["*", ".", "x", "'"][Math.floor(tick / 3) % 4]!;   // no "+": that is the paladin's mark
  const flame = [R`(`, R`)`, R`(`, R`'`][Math.floor(tick / 2) % 4]!;
  heroes.forEach((hero, n) => {
    const sprite = SPRITES[hero]!;
    const x = heroX(n);
    const color = palette[hero];
    const isFront = n === heroes.length - 1;
    const body = hero === "warrior" && isFront && swinging && sprite.swing ? sprite.swing : sprite.rows;
    const legs = LEGS[(stride + n) % LEGS.length]!;          // not in lockstep
    [...body, ...legs].forEach((line, i) => {
      const row = TOP + i;
      [...line].forEach((ch, j) => {
        if (ch === " ") return;
        if (hero === "mage" && ch === "*") return put(row, x + j, casting && n === shooter ? "@" : sparkle, palette.star);
        if (hero === "paladin" && ch === "+" && i === 4) return put(row, x + j, casting && n === shooter ? "*" : "+", palette.light);
        if (hero === "wanderer" && i === 0 && ch === "(") return put(row, x + j, flame, palette.flame);
        put(row, x + j, ch, color);
      });
    });
  });

  // the foe walks in, and falls in a little burst
  if (t < hit) {
    const foe = foeOf(kind, t), x = foeX(t);
    foe.rows.forEach((line, i) => text(foe.top + i, x, line, palette[foe.color]));
  } else if (t < hit + BURST) {
    const x = foeX(hit), mid = kind === "bat" ? TOP + 2 : FEET - Math.floor(foeOf(kind, 0).rows.length / 2);
    for (let r = mid - 1; r <= mid + 1; r++) clear(r, x - 1, x + fw + 1);
    const puff = t < hit + 2 ? [R` \ | / `, R`- * -`, R` / | \ `] : [R`  .    `, R`.   .`, R`   .   `];
    puff.forEach((line, i) => text(mid - 1 + i, x + Math.floor(fw / 2) - 3, line, palette.star));
  }
  // the arrow, the spell, the flask or the light in flight: it shows up ahead of the party
  // (it flew over the heads in front) and crosses to the foe
  if (shotLands && shot && t >= shotAt && t < hit) {
    const x = front + 1 + Math.floor((t - shotAt) * shot.speed);
    text(TOP + shot.row, x, shot.glyph, palette[shot.color]);
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
