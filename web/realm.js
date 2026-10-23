// The races of the guild, for the browser: who each one is, one dry line about them, and the
// hero-banner figure every page draws. The python side is bin/lore.py; keep the two in step.
// A page loads /realm.js, then calls rmFigure(key, n, sub, extraTip) and puts the figures in a .rm-party.
const RM_RACES = {
  human:    { name: "Humans",      one: "Human",     who: "The guildmaster, you", side: "guild",
              tip: "Rules the realm, pays the bills, reads the wall. Makes the hard calls and takes the blame for the easy ones." },
  highelf:  { name: "High elves",  one: "High elf",  who: "Opus, the archmage (the quartermaster is one)", side: "guild",
              tip: "Thinks for a long time, then is right. Usually. Sends the parties out and reads their reports. Charges by the thought." },
  nightelf: { name: "Night elves", one: "Night elf", who: "The reviewers", side: "guild",
              tip: "Read every diff in the dark before the gate. Can hear a missing null check from three files away." },
  dwarf:    { name: "Dwarves",     one: "Dwarf",     who: "Sonnet, the knights of the forge", side: "guild",
              tip: "Steady hands. Build all day, grumble about the tests, build some more. Great with hammers, average with naming." },
  gnome:    { name: "Gnomes",      one: "Gnome",     who: "Haiku and Codex, scouts and tinkerers", side: "guild",
              tip: "Small, fast and cheap. Run the easy roads and the long mechanical jobs. Now and then forget a semicolon." },
  dragon:   { name: "Dragons",     one: "Dragon",    who: "Fable, the oracle", side: "guild",
              tip: "Sees further than anyone. Also eats more gold than anyone. Call one when the question is hard, not when it is long." },
  orc:      { name: "Orcs",        one: "Orc",       who: "A quest that failed", side: "horde",
              tip: "The orc read the stack trace and charged. Send a scout to see what it left behind." },
  troll:    { name: "Trolls",      one: "Troll",     who: "A blocked quest", side: "horde",
              tip: "Holds the bridge until the toll is paid: a password, a port, or a decision only you can make." },
  goblin:   { name: "Goblins",     one: "Goblin",    who: "Red tests", side: "horde",
              tip: "Live in failing tests and multiply there. Count them before they do." },
  undead:   { name: "Undead",      one: "Undead",    who: "A quest that stopped without a report", side: "horde",
              tip: "No tale, no loot. Fled the dungeon and left the torch burning." },
};
const rmEsc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
/** The race a model walks as, the same rule as bin/lore.py. */
function rmRaceOf(model) {
  const m = String(model || "").toLowerCase();
  if (/fable/.test(m)) return "dragon";
  if (/opus|thinking|gpt-5/.test(m)) return "highelf";
  if (/sonnet|deepseek/.test(m)) return "dwarf";
  if (/codex|haiku|flash|mini/.test(m)) return "gnome";
  return "human";
}
/** The bust alone (for a .race ring the page draws itself). */
const rmBust = (key) => `<svg aria-hidden="true"><use href="/races.svg#${rmEsc(key)}"/></svg>`;
/** A portrait in its ring. cls: "small", "big", "horde", "dim". */
function rmRace(key, cls = "") {
  if (!key) return "";
  const r = RM_RACES[key];
  const horde = r && r.side === "horde" ? " horde" : "";
  return `<span class="race ${cls}${horde}" title="${rmEsc(r ? r.one + ": " + r.who.toLowerCase() : key)}">${rmBust(key)}</span>`;
}
/**
 * One hero-banner figure: the portrait with a count, the race's name, a short line under it,
 * and on hover who they are, the dry line, and the live line (extra) for this page.
 */
function rmFigure(key, n, sub, extra = "", opts = {}) {
  const r = RM_RACES[key] || { name: key, who: "", tip: "", side: "guild" };
  const name = opts.name || (n === 1 && !opts.plural ? r.one : r.name);
  const tip = [r.who ? r.who + "." : "", r.tip, extra].filter(Boolean).join(" ");
  const badge = n == null ? "" : `<b class="n">${rmEsc(n)}</b>`;
  return `<figure data-tip="${rmEsc(tip)}" tabindex="0"><span class="race big${r.side === "horde" ? " horde" : ""}${opts.dim ? " dim" : ""}">${rmBust(key)}${badge}</span>` +
    `<figcaption>${rmEsc(name)}<small>${rmEsc(sub || "")}</small></figcaption></figure>`;
}
