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
// between them the road brings its own: bats, slimes, skeletons, wolves, spiders, wisps, ghosts,
// rats, harpies, imps, snakes, bandits, kobolds, gargoyles, a golem, a necromancer, a treant, a
// mimic, and bosses (an ogre, a dragon whelp, a hydra, a lich) that take many blows. Some
// stretches are obstacles: a log, a river, a locked gate, a web, a chasm, a boulder.
//
// A fight is an exchange. Every ranged hero fires in volleys as the creature comes: the archer's
// arrows, the mage's spells, the artificer's flasks, the paladin's light, the wanderer's torch.
// A creature has hit points, and some blows do nothing to it (arrows pass through a ghost, a
// sword cannot reach a bat) while others hurt twice (ice on a whelp, light on the undead). What
// is still alive at the front meets the warrior's sword. Whoever lands the last blow gets the
// kill, and a star over their head. An obstacle is cleared by the hero who knows how (the mage
// freezes the river, the artificer picks the gate) and the party walks across. The scene is a
// pure function of the tick and the party, so a fight always plays out the same way.
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
export type FoeKind =
  | "bat" | "slime" | "skeleton" | "goblin" | "orc" | "troll"
  | "wolves" | "spider" | "wisp" | "ghost" | "mimic" | "rats" | "harpy" | "imp" | "snake" | "bandit"
  | "kobold" | "gargoyle" | "golem" | "necromancer" | "treant"
  | "ogre" | "whelp" | "hydra" | "lich"
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
/** A ranged attack: how fast it flies, on which row, what it looks like, and how many ticks between two. */
type Shot = { speed: number; row: number; glyph: string; color: keyof PartyPalette; every: number };
const FIGURES: Record<Hero, Figure> = {
  archer: { top: " o)", body: "/|)", shot: { speed: 3, row: HEAD, glyph: "->", color: "archer", every: 6 } },        // bow: fast and often
  mage: { top: " o*", body: "/||", shot: { speed: 1.5, row: BODY, glyph: "~*", color: "spell", every: 11 } },        // staff with a star
  paladin: { top: " o+", body: "/|]", shot: { speed: 1.5, row: HEAD, glyph: "+)", color: "light", every: 15 } },     // a bolt of light
  artificer: { top: " o%", body: "/|[", shot: { speed: 1.5, row: BODY, glyph: "o%", color: "flask", every: 13 } },   // a flask
  wanderer: { top: " o'", body: "/|!", shot: { speed: 1.5, row: HEAD, glyph: "'", color: "flame", every: 17 } },     // throws the torch, lights another
  warrior: { top: " o/", body: "/| " },                                                                              // sword, fights up close
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
// One encounter every FIGHT ticks. A creature starts START columns ahead of the front and closes
// one column a tick (it walks left while the party walks right). The ranged heroes fire while it
// comes; at MELEE it stands at the warrior's blade. Positions are relative to the front of the
// party, which moves with the tick, so the fight itself does not depend on where the party is.
const FIGHT = 70, START = 34, MELEE = START - 3, BURST = 4, SWING = 3;
type Rows = Array<[number, string]>;
/**
 * One encounter. `art(t, hp)` draws it (a pack loses a head as it loses hp). `hp` is how many
 * blows it takes; `resist` names the heroes whose blows do nothing to it, `weak` the ones whose
 * blows count double. `flying` creatures cannot be reached by the sword: unhurt at the front,
 * they swoop over the party and are gone. An obstacle has `solved` art and an `answer`: only
 * that hero (or the warrior, when the hero is not on the road) can open the way.
 */
type Foe = {
  art: (t: number, hp: number) => Rows; color: keyof PartyPalette; hp: number;
  resist?: Hero[]; weak?: Hero[]; flying?: boolean; boss?: boolean;
  answer?: Hero; solved?: Rows; solvedColor?: keyof PartyPalette;
};
const walk = (t: number, a = "/ \\", b = " | ") => (t % 4 < 2 ? a : b);
const FOES: Record<FoeKind, Foe> = {
  // ── small things ──
  bat: { hp: 1, flying: true, weak: ["archer"], color: "bat", art: (t) => [[HEAD, t % 4 < 2 ? "^o^" : "vov"]] },
  slime: { hp: 2, resist: ["archer"], weak: ["mage"], color: "slime",
           art: (t, hp) => hp > 1 ? [[BODY, t % 4 < 2 ? " __ " : " _  "], [FEET, "(oo)"]] : [[FEET, "(o.)"]] },
  skeleton: { hp: 2, resist: ["archer"], weak: ["paladin"], color: "bones", art: (t) => [[HEAD, " o "], [BODY, "<|\\"], [FEET, walk(t)]] },
  goblin: { hp: 1, color: "goblin", art: (t) => [[BODY, t % 4 < 2 ? ">o<" : ">o-"], [FEET, walk(t)]] },
  kobold: { hp: 1, color: "goblin", art: (t) => [[BODY, t % 4 < 2 ? "'o<" : "'o-"], [FEET, walk(t, "/\\", "||")]] },
  snake: { hp: 1, weak: ["archer"], color: "slime", art: (t) => [[FEET, t % 4 < 2 ? "~~o>" : "_~o>"]] },
  rats: { hp: 3, resist: ["archer"], weak: ["artificer"], color: "wolf",                              // a swarm: one less each blow
          art: (t, hp) => [[FEET, ["", "~o", "~o ~o", "~o ~o ~o"][hp]!.replace(/o/g, t % 4 < 2 ? "o" : "0")]] },
  imp: { hp: 1, flying: true, weak: ["paladin"], color: "spider", art: (t) => [[HEAD, t % 4 < 2 ? ">v<" : "-v-"]] },
  wisp: { hp: 1, flying: true, weak: ["artificer"], color: "wisp", art: (t) => [[t % 8 < 4 ? HEAD : BODY, t % 2 ? "o" : "*"]] },
  spider: { hp: 2, weak: ["mage", "wanderer"], color: "spider", art: (t) => [[HEAD, t % 6 < 3 ? " | " : "  |"], [BODY, t % 4 < 2 ? "/o\\" : "\\o/"]] },
  // ── people and beasts ──
  bandit: { hp: 2, color: "mimic", art: (t) => [[HEAD, " o>"], [BODY, "/|-"], [FEET, walk(t)]] },
  wolves: { hp: 2, weak: ["archer"], color: "wolf",
            art: (t, hp) => hp > 1 ? [[BODY, "<^^ <^^"], [FEET, t % 4 < 2 ? "/\\/\\ /\\/\\" : "|| |  || |"]]
                                   : [[BODY, "    <^^"], [FEET, t % 4 < 2 ? "     /\\/\\" : "     || |"]] },
  harpy: { hp: 2, flying: true, weak: ["archer"], color: "bat", art: (t) => [[1, t % 4 < 2 ? "\\o/" : "/o\\"], [HEAD, " v "]] },
  orc: { hp: 3, color: "orc", art: (t) => [[HEAD, "[o]"], [BODY, "<#\\"], [FEET, walk(t)]] },
  gargoyle: { hp: 3, resist: ["archer"], weak: ["artificer"], color: "stone", art: (t) => [[HEAD, t % 4 < 2 ? "<o>" : "-o-"], [BODY, "/#\\"], [FEET, "/ \\"]] },
  troll: { hp: 4, weak: ["paladin"], color: "troll", art: (t) => [[HEAD, " 0 "], [BODY, "<##>"], [FEET, t % 4 < 2 ? "/  \\" : " || "]] },
  golem: { hp: 4, resist: ["archer", "wanderer"], weak: ["artificer"], color: "stone", art: (t) => [[HEAD, "[==]"], [BODY, "[##]"], [FEET, walk(t, "/  \\", " || ")]] },
  mimic: { hp: 2, resist: ["archer"], color: "mimic", art: (t) => t < START - 12 ? [[FEET, "[==]"]] : [[BODY, "/vv\\"], [FEET, "[^^]"]] },
  // ── the dark ──
  ghost: { hp: 2, flying: true, resist: ["archer"], weak: ["paladin"], color: "ghost",
           art: (t) => [[HEAD, " .-."], [BODY, "(o o)"], [FEET, t % 4 < 2 ? " ^^^" : "^^^ "]] },
  necromancer: { hp: 3, weak: ["paladin"], color: "bat", art: (t) => [[HEAD, t % 8 < 4 ? " o!" : " o;"], [BODY, "/|\\"], [FEET, " M "]] },
  treant: { hp: 4, resist: ["archer"], weak: ["wanderer", "mage"], color: "tree", art: (t) => [[1, "\\^^/"], [HEAD, "<oo>"], [BODY, " ## "], [FEET, t % 4 < 2 ? "/  \\" : " || "]] },
  // ── bosses: many blows, and loot when they fall ──
  ogre: { hp: 5, boss: true, color: "ogre", art: (t) => [[1, " (o)"], [HEAD, "<###>"], [BODY, " ### "], [FEET, walk(t, "/   \\", " | | ")]] },
  whelp: { hp: 5, boss: true, resist: ["archer"], weak: ["mage"], color: "dragon",
           art: (t) => [[HEAD, t % 4 < 2 ? "<\\^/ " : "</^\\ "], [BODY, "<{##}~"], [FEET, walk(t, " /  \\", "  ||  ")]] },
  hydra: { hp: 6, boss: true, color: "slime",                                                      // loses a head at a time
           art: (t, hp) => [[1, ["", "", "  o", "  o o", "o o o", "o o o", "o o o"][hp]!], [HEAD, hp > 3 ? "\\|/" : hp > 1 ? " |/" : "  |"], [BODY, "{###}"], [FEET, walk(t, "/   \\", " | | ")]] },
  lich: { hp: 6, boss: true, resist: ["archer"], weak: ["paladin"], color: "bones",
          art: (t) => [[1, " ^ "], [HEAD, t % 6 < 3 ? "(o)" : "(-)"], [BODY, "/#\\"], [FEET, " M "]] },
  // ── obstacles: the answer opens the way, then the party walks across ──
  log: { hp: 1, answer: "warrior", color: "wood", art: () => [[FEET, "=##=#="]], solved: [[FEET, "=.  .="]], solvedColor: "wood" },
  river: { hp: 1, answer: "mage", color: "water", art: (t) => [[FEET, t % 4 < 2 ? "~~=~~~~=" : "~=~~~=~~"]], solved: [[FEET, "========"]], solvedColor: "ice" },
  gate: { hp: 1, answer: "artificer", color: "iron", art: () => [[1, "_____"], [HEAD, "|###|"], [BODY, "|#o#|"], [FEET, "|###|"]],
          solved: [[1, "_____"], [HEAD, "|   |"], [BODY, "|   |"], [FEET, "|   |"]], solvedColor: "iron" },
  web: { hp: 1, answer: "wanderer", color: "web", art: () => [[1, "\\ | /"], [HEAD, " \\|/ "], [BODY, "--*--"], [FEET, " /|\\ "]],
         solved: [[FEET, " ' . "]], solvedColor: "flame" },
  chasm: { hp: 1, answer: "paladin", color: "stone", art: () => [[FEET, "_      _"]], solved: [[FEET, "_======_"]], solvedColor: "light" },
  boulder: { hp: 1, answer: "warrior", color: "stone", art: () => [[BODY, " ___ "], [FEET, "(@@@)"]], solved: [[FEET, " . o "]], solvedColor: "stone" },
};
/** The road when no quest is in trouble: creatures and obstacles in turn, a boss every so often. */
const QUIET_ROAD: FoeKind[] = [
  "bat", "log", "wolves", "slime", "river", "spider", "skeleton", "gate", "rats", "ogre",
  "web", "imp", "bandit", "wisp", "chasm", "mimic", "harpy", "hydra",
  "snake", "boulder", "kobold", "ghost", "gargoyle", "river", "necromancer", "golem", "treant", "whelp",
  "goblin", "log", "orc", "lich",
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

type ShotInFlight = { hero: number; from: number; hit: number };
type Blow = { t: number; hero: number; damage: number };
export type Fight = {
  shots: ShotInFlight[]; blows: Blow[]; swings: number[];
  /** when it falls, and who felled it */ death?: number; killer?: number;
  /** when a creature nobody could stop passes over or through the party */ escape?: number;
  hpAt: (t: number) => number;
};
/**
 * The whole fight, decided before it is drawn. Ranged heroes fire whenever the creature is in
 * front of them and their rhythm allows; each shot's landing tick comes from its speed and the
 * creature's walk. At the front the warrior swings every few ticks. Blows are applied in tick
 * order; a shot that would land after the death simply vanishes in the burst.
 */
export function fight(heroes: readonly Hero[], kind: FoeKind): Fight {
  const foe = FOES[kind];
  const width = heroes.length * 3 + (heroes.length - 1);
  const rel = (n: number) => n * STEP - width + 3;                     // a hero's hand, relative to the front
  const foeAt = (s: number) => START - s;
  const resist = new Set(foe.resist ?? []), weak = new Set(foe.weak ?? []);
  // an obstacle yields only to its answer; the warrior clears it when that hero is not on the road
  const solver = foe.solved ? (heroes.includes(foe.answer!) ? foe.answer! : "warrior") : undefined;
  const hurts = (hero: Hero) => (solver ? hero === solver : !resist.has(hero));
  const dmg = (hero: Hero) => (weak.has(hero) ? 2 : 1);
  const shots: ShotInFlight[] = [], blows: Blow[] = [], swings: number[] = [];
  const nextFire = heroes.map((_, n) => 4 + (heroes.length - 1 - n));   // the back of the line takes a beat longer
  for (let s = 0; s < FIGHT; s++) {
    heroes.forEach((hero, n) => {
      const shot = FIGURES[hero].shot;
      if (!shot || s < nextFire[n]!) return;
      if (solver !== undefined && hero !== solver) return;             // only the one who knows how works on an obstacle
      if (foeAt(s) <= rel(n) + 3) return;                                // it is already past this hero
      let hit = -1;
      for (let k = s; k < FIGHT; k++) if (rel(n) + Math.floor((k - s) * shot.speed) + shot.glyph.length >= foeAt(k)) { hit = k; break; }
      if (hit < 0) return;
      shots.push({ hero: n, from: s, hit });
      if (hurts(hero)) blows.push({ t: hit, hero: n, damage: dmg(hero) });
      nextFire[n] = s + shot.every;
    });
    if (s >= MELEE && (s - MELEE) % SWING === 0) {
      const w = heroes.length - 1;                                       // the warrior stands at the front
      swings.push(s);
      if (!foe.flying && hurts(heroes[w]!)) blows.push({ t: s + 1, hero: w, damage: dmg(heroes[w]!) });
    }
  }
  blows.sort((a, b) => a.t - b.t);
  let hp = foe.hp, death: number | undefined, killer: number | undefined;
  const kept: Blow[] = [];
  for (const b of blows) {
    hp -= b.damage; kept.push(b);
    if (hp <= 0) { death = b.t; killer = b.hero; break; }
  }
  // nothing could touch it: a flyer swoops over the party, anything else slips through
  const escape = death === undefined ? MELEE : undefined;
  const over = death ?? escape!;
  const hpAt = (t: number) => Math.max(0, foe.hp - kept.filter((b) => b.t <= t).reduce((sum, b) => sum + b.damage, 0));
  return { shots: shots.filter((x) => x.from < over), blows: kept, swings: swings.filter((s) => s <= over), death, killer, escape, hpAt };
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

  // the encounter of the moment, and how the fight goes
  const t = tick % FIGHT;
  const round = Math.floor(tick / FIGHT);
  const road = roadOf(party);
  const kind = road[round % road.length]!;
  const foe = FOES[kind];
  const f = fight(heroes, kind);
  const foeX = (s: number) => front + START - s;
  const wide = Math.max(...foe.art(0, foe.hp).map(([, r]) => r.length));
  const end = f.death ?? f.escape!;                          // when the encounter is over
  const alive = t < end;
  const solved = foe.solved !== undefined;

  // what stands in the way of the forest: the party, and the creature or its burst
  const boxes: Array<[number, number]> = [[left - 1, left + width + 1]];
  if (solved || f.escape !== undefined) boxes.push([foeX(t) - 2, foeX(t) + wide + 1]);   // it stays on the road
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
    const art = alive ? foe.art(t, 1) : foe.solved!, color = palette[alive ? foe.color : foe.solvedColor ?? foe.color];
    for (const [row, line] of art) text(row, foeX(t), line, color);
    if (!alive && t < end + BURST) text(HEAD, foeX(end) + 1, t < end + 2 ? "\\*/" : " . ", palette.star);
  }

  const stride = Math.floor(tick / 2) % 2;
  const sparkle = ["*", ".", "x", "'"][Math.floor(tick / 3) % 4]!;   // no "+": that is the paladin's mark
  const flicker = ["'", "`", "'", "\""][Math.floor(tick / 2) % 4]!;
  const casting = new Set(f.shots.filter((x) => t >= x.from - 1 && t <= x.from + 1).map((x) => x.hero));
  const swinging = alive && f.swings.some((s) => t >= s - 1 && t <= s + 1);
  const cheering = f.death !== undefined && f.killer !== undefined && t >= f.death && t < f.death + 6 ? f.killer : -1;
  heroes.forEach((hero, n) => {
    const fig = FIGURES[hero]!;
    const x = heroX(n);
    const color = palette[hero];
    let top = fig.top, body = fig.body;
    if (hero === "warrior" && n === heroes.length - 1 && swinging) { top = " o "; body = "/|-"; put(BODY, x + 3, "-", color); }
    if (n === cheering) { top = "\\" + top.slice(1); put(1, x + 1, (t - f.death!) % 2 ? "*" : "'", palette.star); }   // an arm up, a star over the head
    [...top].forEach((ch, i) => {
      // the mage's star turns while they walk and flares when they cast; the torch flickers
      if (hero === "mage" && ch === "*") return put(HEAD, x + i, casting.has(n) ? "@" : sparkle, palette.star);
      if (hero === "wanderer" && ch === "'") return put(HEAD, x + i, casting.has(n) ? "," : flicker, palette.flame);
      if (hero === "paladin" && ch === "+") return put(HEAD, x + i, casting.has(n) ? "*" : "+", palette.light);
      if (hero === "archer" && ch === ")" && casting.has(n)) return put(HEAD, x + i, "}", color);
      put(HEAD, x + i, ch, color);
    });
    [...body].forEach((ch, i) => put(BODY, x + i, ch, color));
    const own = LEGS[(stride + n) % 2]!;                    // not in lockstep
    [...own].forEach((ch, i) => put(FEET, x + i, ch, color));
  });

  // the creature walks in, flinches at every blow, and falls in a burst (or passes over the party)
  if (!solved) {
    const hp = f.hpAt(t);
    const flinch = f.blows.some((b) => t === b.t || t === b.t + 1);
    if (alive || f.escape !== undefined) {
      const x = foeX(t);
      const lift = f.escape !== undefined && t >= f.escape ? -2 : 0;      // it swoops over the heads
      for (const [row, line] of foe.art(t, Math.max(1, hp))) text(row + lift, x, line, flinch && alive ? palette.star : palette[foe.color]);
      if (foe.hp > 1 && alive) {                                            // its life, as dots over its head
        const top = Math.min(...foe.art(t, Math.max(1, hp)).map(([r]) => r)) - 1;
        if (top >= 0) text(top, x, ".".repeat(hp), palette.star);
      }
      if (flinch && alive) text(1, x + wide, "!", palette.star);
    } else if (t < end + BURST) {
      const x = foeX(end), rows = foe.art(end, 1).map(([r]) => r);
      const row = rows[Math.floor(rows.length / 2)] ?? BODY;
      for (const r of rows) clear(r, x - 1, x + wide);
      const by = f.killer !== undefined ? FIGURES[heroes[f.killer]!]!.shot?.color : undefined;
      text(row, x + Math.max(0, Math.floor(wide / 2) - 2), t < end + 2 ? "\\*/" : foe.boss ? " $ " : " . ", palette[by ?? "star"]);
    }
  }
  // arrows, spells, flasks, light and a torch in flight
  for (const s of f.shots) {
    if (t < s.from || t >= Math.min(s.hit, end)) continue;
    const shot = FIGURES[heroes[s.hero]!]!.shot!;
    const x = heroX(s.hero) + 3 + Math.floor((t - s.from) * shot.speed);
    if (x > front) text(shot.row, x, shot.glyph, palette[shot.color]);      // shown once it clears the party's heads
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
