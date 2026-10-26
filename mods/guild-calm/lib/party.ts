// The party for guild calm mode: the sessions that are running right now, drawn as tiny
// adventurers walking right through a night forest and fighting what comes at them, packed as
// Claude Code Raster cells.
//
// Each running session is one hero, chosen by its model: Sonnet is an archer, Opus a mage, Fable
// a paladin, Haiku a warrior, Codex an artificer, and a model the guild does not know walks as a
// wanderer with a torch. Two heroes are always there: the mage, who is the quartermaster itself
// (it runs on Opus), and a warrior at the front, the guild's own guard when no session runs on
// Haiku, so the party is never without a blade.
//
// The road is a sequence of encounters, one every ten seconds. Quests in trouble send their own
// creature (a goblin for red checks, a troll for a blocked quest, an orc for a failed one), and
// between them the road itself brings the rest: bats, slimes, skeletons, wolf packs, spiders,
// wisps, ghosts, a mimic that was never a chest, and now and then a boss (an ogre, a dragon whelp)
// that takes two blows. Some stretches are not creatures but obstacles: a fallen log, a river, a
// locked gate, a web across the path, a chasm, a boulder. Each encounter has the hero who answers
// it: the archer shoots, the mage casts (and freezes the river), the artificer throws a flask (and
// picks the gate's lock), the paladin's light drops what is dark (and bridges the chasm), the
// wanderer's torch burns the web, and the warrior cuts down or clears whatever reaches the front.
// The scene is a pure function of the tick and the party, so a fight always plays out the same way.
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

// ── who walks and what comes at them ──────────────────────────────────────────
export type Hero = "archer" | "mage" | "paladin" | "warrior" | "artificer" | "wanderer";
export type FoeKind = "bat" | "slime" | "skeleton" | "goblin" | "orc" | "troll"
  | "wolves" | "spider" | "wisp" | "ghost" | "mimic" | "ogre" | "whelp"
  | "log" | "river" | "gate" | "web" | "chasm" | "boulder";
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

/**
 * The heroes in marching order. The quartermaster's mage is always among them, and the guild's
 * guard takes the front when no warrior is.
 */
export function marchingOrder(heroes: readonly Hero[]): Hero[] {
  const all: Hero[] = heroes.includes("mage") ? [...heroes] : [...heroes, "mage"];
  const sorted = all.sort((a, b) => RANK[a] - RANK[b]);
  if (!sorted.includes("warrior")) sorted.push("warrior");
  return sorted.slice(-MAX_HEROES);        // too many to draw: the back of the line waits at camp
}

export const DEFAULT_PARTY: Party = { heroes: ["mage", "warrior"], foes: [] };

export type PartyPalette = {
  archer: number; mage: number; paladin: number; warrior: number; artificer: number; wanderer: number;
  tree: number; treeFar: number; grass: number; star: number;
  bat: number; slime: number; bones: number; goblin: number; orc: number; troll: number;
  wolf: number; spider: number; wisp: number; ghost: number; mimic: number; ogre: number; dragon: number;
  wood: number; water: number; ice: number; iron: number; stone: number; web: number;
  spell: number; light: number; flask: number; flame: number;
};
export type PartyFamily = "dark" | "light";

export const PARTY_PALETTES: Record<PartyFamily, PartyPalette> = {
  dark: { archer: 0xf0a430, mage: 0x3ec6ec, paladin: 0xf5d76e, warrior: 0xef4a3c, artificer: 0xd48cf0, wanderer: 0xc8b89a,
          tree: 0x4fa85a, treeFar: 0x2f5f38, grass: 0x3a6b42, star: 0xf2e3a6,
          bat: 0xb07ad8, slime: 0x9fd04a, bones: 0xe6e1d3, goblin: 0x7fc24f, orc: 0x6f9a3a, troll: 0x9a9a84,
          wolf: 0xa7adb8, spider: 0xc0566e, wisp: 0x9ff3e0, ghost: 0xd8e4f0, mimic: 0xc9873a, ogre: 0xb08a5a, dragon: 0xe8553a,
          wood: 0x9a6a3a, water: 0x4f93e0, ice: 0xbfefff, iron: 0x8a8f9a, stone: 0x9a948a, web: 0xd9d9d9,
          spell: 0x7fe8ff, light: 0xfff1b0, flask: 0xe6a8ff, flame: 0xffb347 },
  light: { archer: 0xb5651d, mage: 0x1e7fa0, paladin: 0xa8841f, warrior: 0xb33a2e, artificer: 0x8a4fb0, wanderer: 0x7a6a50,
           tree: 0x3f7d3a, treeFar: 0x9bb89a, grass: 0x8fb08a, star: 0xa8841f,
           bat: 0x7a3fa8, slime: 0x5a8a1a, bones: 0x6e6a60, goblin: 0x4f8a2a, orc: 0x3f6a1a, troll: 0x6a6a58,
           wolf: 0x5a606a, spider: 0x9a2a48, wisp: 0x1f8f7a, ghost: 0x5a6a80, mimic: 0x8a5a1a, ogre: 0x7a5a30, dragon: 0xb3301a,
           wood: 0x7a4a1a, water: 0x1f5fb0, ice: 0x2f8fb0, iron: 0x4a4f5a, stone: 0x6a645a, web: 0x6a6a6a,
           spell: 0x0f8fb0, light: 0xc08a10, flask: 0x9a3fb0, flame: 0xc75a10 },
};

/** Themes are named like "dark-ansi" or "light"; anything unknown reads well on light. */
export function partyFamily(theme: unknown): PartyFamily {
  return typeof theme === "string" && theme.startsWith("dark") ? "dark" : "light";
}

/** Scene width for a viewport: the working row minus its margin, inside the Raster limit. */
export function partyColumns(viewportColumns: number | undefined): number {
  return Math.max(16, Math.min(MAX_COLUMNS, (viewportColumns ?? 80) - MARGIN));
}

// ── the heroes: three columns by three rows each, two leg frames make the walk ──
type Figure = { top: string; body: string; shot?: Shot };
type Shot = { speed: number; row: number; glyph: string; color: keyof PartyPalette };
const FIGURES: Record<Hero, Figure> = {
  archer: { top: " o)", body: "/|)", shot: { speed: 2, row: HEAD, glyph: "->", color: "archer" } },       // bow
  mage: { top: " o*", body: "/||", shot: { speed: 1.5, row: BODY, glyph: "~*", color: "spell" } },        // staff with a star
  paladin: { top: " o+", body: "/|]", shot: { speed: 1.5, row: HEAD, glyph: "+)", color: "light" } },     // mace raised, shield
  artificer: { top: " o%", body: "/|[", shot: { speed: 1.5, row: BODY, glyph: "o%", color: "flask" } },  // a flask, a toolbox
  wanderer: { top: " o'", body: "/|!" },                                                                  // a torch
  warrior: { top: " o/", body: "/| " },                                                                   // sword held up, fights up close
};
const LEGS = ["/ \\", " | "];                                        // stride, then together
const STEP = 4;                                                      // three columns, one apart

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
// One fight every FIGHT ticks. An enemy starts START columns ahead of the front and closes
// one column a tick (it walks left while the party walks right). The hero who answers it
// shoots from where they walk; a foe nobody shoots down reaches the warrior's blade.
const FIGHT = 70, START = 34, BURST = 4;
type Rows = Array<[number, string]>;
/**
 * One encounter. `answer` is the hero who deals with it; a creature nobody answers reaches the
 * warrior's blade. A boss (`tough`) shrugs off the first blow: it staggers, shows `wounded`, and
 * only the warrior finishes it. An obstacle (`solved`) does not fall: the answer turns it into the
 * way across (ice on the river, a bridge of light on the chasm), and the party walks over it.
 */
type Foe = { rows: Rows; color: keyof PartyPalette; answer: Hero; tough?: Rows; solved?: Rows; solvedColor?: keyof PartyPalette };
const walk = (t: number, a = "/ \\", b = " | ") => (t % 4 < 2 ? a : b);
const FOES: Record<FoeKind, (t: number) => Foe> = {
  // ── creatures ──
  bat: (t) => ({ rows: [[HEAD, t % 4 < 2 ? "^o^" : "vov"]], color: "bat", answer: "archer" }),           // flaps its wings
  slime: (t) => ({ rows: [[BODY, t % 4 < 2 ? " __ " : " _  "], [FEET, "(oo)"]], color: "slime", answer: "mage" }),
  skeleton: (t) => ({ rows: [[HEAD, " o "], [BODY, "<|\\"], [FEET, walk(t)]], color: "bones", answer: "warrior" }),
  goblin: (t) => ({ rows: [[BODY, t % 4 < 2 ? ">o<" : ">o-"], [FEET, walk(t)]], color: "goblin", answer: "artificer" }),
  orc: (t) => ({ rows: [[HEAD, "[o]"], [BODY, "<#\\"], [FEET, walk(t)]], color: "orc", answer: "warrior" }),
  troll: (t) => ({ rows: [[HEAD, " 0 "], [BODY, "<##>"], [FEET, t % 4 < 2 ? "/  \\" : " || "]], color: "troll", answer: "paladin" }),
  // a pack of two: the archer drops the first wolf, the warrior meets the second
  wolves: (t) => ({ rows: [[BODY, "<^^ <^^"], [FEET, t % 4 < 2 ? "/\\/\\ /\\/\\" : "|| |  || |"]], color: "wolf", answer: "archer",
                    tough: [[BODY, "    <^^"], [FEET, t % 4 < 2 ? "     /\\/\\" : "     ||||"]] }),
  // hangs from a thread and swings down at the party
  spider: (t) => ({ rows: [[HEAD, t % 6 < 3 ? " | " : "  |"], [BODY, t % 4 < 2 ? "/o\\" : "\\o/"]], color: "spider", answer: "mage" }),
  wisp: (t) => ({ rows: [[t % 8 < 4 ? HEAD : BODY, t % 2 ? "o" : "*"]], color: "wisp", answer: "artificer" }),       // bobs and flickers
  ghost: (t) => ({ rows: [[HEAD, " .-."], [BODY, "(o o)"], [FEET, t % 4 < 2 ? " ^^^" : "^^^ "]], color: "ghost", answer: "paladin" }),
  // a chest on the road, until it is close enough to bite
  mimic: (t) => ({ rows: t < START - 12 ? [[FEET, "[==]"]] : [[BODY, "/vv\\"], [FEET, "[^^]"]], color: "mimic", answer: "warrior" }),
  // the bosses: the right hero staggers them, the warrior finishes them
  ogre: (t) => ({ rows: [[1, " (o)"], [HEAD, "<###>"], [BODY, " ### "], [FEET, walk(t, "/   \\", " | | ")]], color: "ogre", answer: "paladin",
                  tough: [[1, " (x)"], [HEAD, "<###>"], [BODY, " #!# "], [FEET, " | | "]] }),
  whelp: (t) => ({ rows: [[HEAD, t % 4 < 2 ? "<\\^/ " : "</^\\ "], [BODY, "<{##}~"], [FEET, walk(t, " /  \\", "  ||  ")]], color: "dragon", answer: "mage",
                   tough: [[HEAD, " \\x/ "], [BODY, "<{#!}~"], [FEET, "  ||  "]] }),
  // ── obstacles: the answer opens the way, then the party walks across ──
  log: () => ({ rows: [[FEET, "=##=#="]], color: "wood", answer: "warrior", solved: [[FEET, "=.  .="]], solvedColor: "wood" }),
  river: (t) => ({ rows: [[FEET, t % 4 < 2 ? "~~=~~~~=" : "~=~~~=~~"]], color: "water", answer: "mage", solved: [[FEET, "========"]], solvedColor: "ice" }),
  gate: () => ({ rows: [[1, "_____"], [HEAD, "|###|"], [BODY, "|#o#|"], [FEET, "|###|"]], color: "iron", answer: "artificer",
                 solved: [[1, "_____"], [HEAD, "|   |"], [BODY, "|   |"], [FEET, "|   |"]], solvedColor: "iron" }),
  web: () => ({ rows: [[1, "\\ | /"], [HEAD, " \\|/ "], [BODY, "--*--"], [FEET, " /|\\ "]], color: "web", answer: "wanderer",
                solved: [[FEET, " ' . "]], solvedColor: "flame" }),
  chasm: () => ({ rows: [[FEET, "_      _"]], color: "stone", answer: "paladin", solved: [[FEET, "_======_"]], solvedColor: "light" }),
  boulder: () => ({ rows: [[BODY, " ___ "], [FEET, "(@@@)"]], color: "stone", answer: "warrior", solved: [[FEET, " . o "]], solvedColor: "stone" }),
};
/** The road when no quest is in trouble: a fixed walk, creatures and obstacles in turn, a boss now and then. */
const QUIET_ROAD: FoeKind[] = [
  "bat", "log", "wolves", "slime", "river", "spider", "skeleton", "gate", "wisp", "ogre",
  "web", "mimic", "ghost", "chasm", "bat", "boulder", "slime", "whelp",
];
/** The encounters in order: each creature a troubled quest sends comes first in its turn, the road fills the rest. */
export function roadOf(party: Party): FoeKind[] {
  if (party.foes.length === 0) return QUIET_ROAD;
  const out: FoeKind[] = [];
  const turns = Math.max(party.foes.length, Math.ceil(QUIET_ROAD.length / 2));
  for (let i = 0; i < turns; i++) {
    out.push(party.foes[i % party.foes.length]!);
    out.push(QUIET_ROAD[i % QUIET_ROAD.length]!);
  }
  return out;
}

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
  const heroes = marchingOrder(party.heroes);
  const width = heroes.length * 3 + (heroes.length - 1);
  const span = columns + width + 2;
  const left = (Math.floor(tick / 2) % span) - width;
  const front = left + width;                                // the column just ahead of the warrior
  const heroX = (n: number) => left + n * STEP;

  // the encounter of the moment: a creature a quest in trouble sent, or whatever the road brings
  const t = tick % FIGHT;
  const round = Math.floor(tick / FIGHT);
  const road = roadOf(party);
  const kind = road[round % road.length]!;
  const foeOf = FOES[kind];
  const first = foeOf(0);
  const foeX = (s: number) => front + START - s;
  const wide = Math.max(...first.rows.map(([, r]) => r.length));
  // who answers: the hero this encounter belongs to if they walk with us, else the warrior up close
  const answerer = heroes.lastIndexOf(first.answer);
  const shooter = answerer >= 0 ? answerer : heroes.length - 1;
  const shot = FIGURES[heroes[shooter]!]!.shot;
  const shotAt = 4 + (heroes.length - 1 - shooter);          // the back of the line takes a beat longer to see it
  const melee = START - 3;                                   // it reaches the warrior's blade
  let hit = melee;
  if (shot) {
    for (let s = shotAt; s < melee; s++) {
      if (heroX(shooter) + 3 + Math.floor((s - shotAt) * shot.speed) + shot.glyph.length >= foeX(s)) { hit = s; break; }
    }
  }
  const shotLands = shot !== undefined && hit < melee;
  const tough = first.tough !== undefined && shotLands;      // a boss or a pack: the shot only staggers it
  const end = tough ? melee : hit;                           // when the encounter is over
  const swinging = (!shotLands || tough) && t >= end - 2 && t <= end + 1;
  const casting = shotLands && t >= shotAt - 2 && t <= shotAt + 1;
  const solved = first.solved !== undefined;

  // what stands in the way of the forest: the party, and the foe or its burst
  const boxes: Array<[number, number]> = [[left - 1, left + width + 1]];
  if (solved) boxes.push([foeX(t) - 2, foeX(t) + wide + 1]);                       // terrain stays on the road
  else if (t < end + BURST) boxes.push([foeX(Math.min(t, end)) - 2, foeX(Math.min(t, end)) + wide + 1]);
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

  // an obstacle lies on the road: drawn under the party, so they walk across what the answer made of it
  if (solved) {
    const done = t >= end;
    const art = done ? first.solved! : foeOf(t).rows, color = palette[done ? first.solvedColor ?? first.color : first.color];
    for (const [row, line] of art) text(row, foeX(t), line, color);
    if (done && t < end + BURST) text(HEAD, foeX(end) + 1, t < end + 2 ? "\\*/" : " . ", palette.star);
  }

  const stride = Math.floor(tick / 2) % 2;
  const sparkle = ["*", ".", "x", "'"][Math.floor(tick / 3) % 4]!;   // no "+": that is the paladin's mark
  const flicker = ["'", "`", "'", "\""][Math.floor(tick / 2) % 4]!;
  heroes.forEach((hero, n) => {
    const fig = FIGURES[hero]!;
    const x = heroX(n);
    const color = palette[hero];
    let top = fig.top, body = fig.body;
    if (hero === "warrior" && n === heroes.length - 1 && swinging) { top = " o "; body = "/|-"; put(BODY, x + 3, "-", color); }
    [...top].forEach((ch, i) => {
      // the mage's star turns while they walk and flares when they cast; the torch flickers
      if (hero === "mage" && ch === "*") return put(HEAD, x + i, casting && n === shooter ? "@" : sparkle, palette.star);
      if (hero === "wanderer" && ch === "'") return put(HEAD, x + i, flicker, palette.flame);
      if (hero === "paladin" && ch === "+") return put(HEAD, x + i, casting && n === shooter ? "*" : "+", palette.light);
      put(HEAD, x + i, ch, color);
    });
    [...body].forEach((ch, i) => put(BODY, x + i, ch, color));
    const own = LEGS[(stride + n) % 2]!;                    // not in lockstep
    [...own].forEach((ch, i) => put(FEET, x + i, ch, color));
  });

  // the creature walks in, staggers if it is tough, and falls in a little burst
  if (!solved && t < end) {
    const foe = foeOf(t), x = foeX(t);
    const rows = tough && t >= hit ? first.tough! : foe.rows;
    const color = tough && t >= hit && t < hit + 2 ? palette.star : palette[foe.color];   // flashes when the shot lands
    for (const [row, line] of rows) text(row, x, line, color);
    if (tough && t >= hit && t < hit + 3) text(1, x + 1, "!", palette.star);
  } else if (!solved && t < end + BURST) {
    const x = foeX(end), rows = (tough ? first.tough! : first.rows).map(([r]) => r);
    const row = rows[Math.floor(rows.length / 2)] ?? BODY;
    for (const r of rows) clear(r, x - 1, x + wide);
    text(row, x + Math.max(0, Math.floor(wide / 2) - 2), t < end + 2 ? "\\*/" : " . ", palette.star);
  }
  // the arrow, the spell, the flask or the light in flight
  if (shotLands && shot && t >= shotAt && t < hit) {
    const x = heroX(shooter) + 3 + Math.floor((t - shotAt) * shot.speed);
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
