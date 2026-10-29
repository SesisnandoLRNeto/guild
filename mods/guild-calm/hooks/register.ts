// guild calm: the working row becomes the running sessions walking as a party through a forest,
// and tool rows stop drawing.
//
// Why: while an adventurer works, the tool calls scrolling by are noise. Hiding them
// keeps your attention for the question that matters. Nothing here changes the stored
// transcript or the model's context: `ui.render` only changes what is drawn.
//
// This is an early-access Claude Code surface. The mod does nothing at all unless both
// CLAUDE_CODE_ENABLE_FUNCTION_HOOKS and GUILD_CALM are exactly "1", so it can never
// touch a normal session. `guild up` and `guild quest` set both when calm is on.
import type { EngineInterface, Register, RenderElement, RenderInput } from "claude-code";
import { DEFAULT_PARTY, PARTY_KEY, PARTY_PALETTES, PARTY_ROWS, PARTY_TICK_MS, foeFor, heroFor, partyColumns, partyFamily, partyFrame, type Party, type PartyPalette } from "../lib/party.ts";

const COMMAND = "calm";
/** How often the road is read again: which quests run, on which model, and which are in trouble. */
const ROSTER_MS = 5000;

let calm = true;
let palette: PartyPalette = PARTY_PALETTES.light;
let preferencePath = "";
let activation: Promise<boolean> | undefined;
let loading: Promise<void> | undefined;
let ticker: { cancel(): void } | undefined;
let roster: { cancel(): void } | undefined;
let tick = 0;
let questsDir = "";
/** The sessions on the road right now, and the creatures the troubled quests send. */
let party: Party = DEFAULT_PARTY;
/** Every working row currently drawing the party, with the size a repaint must repeat. */
const sites = new Map<string, { columns: number }>();

function activated($: EngineInterface): Promise<boolean> {
  if (activation === undefined) {
    activation = Promise.all([$.env.get("CLAUDE_CODE_ENABLE_FUNCTION_HOOKS"), $.env.get("GUILD_CALM")])
      .then(([hooks, guild]) => hooks === "1" && guild === "1")
      .catch(() => false);
  }
  return activation;
}

async function load($: EngineInterface): Promise<void> {
  const home = (await $.env.get("GUILD_HOME").catch(() => undefined)) || `${await $.env.get("HOME")}/.guild`;
  preferencePath = `${home}/calm`;
  questsDir = `${home}/quests`;
  calm = (await $.fs.read(preferencePath).catch(() => "on")).trim() !== "off";
  palette = PARTY_PALETTES[partyFamily(await readTheme($))];
  await readRoster($);
  ticker ??= $.clock.every(PARTY_TICK_MS, () => void repaint($));
  roster ??= $.clock.every(ROSTER_MS, () => void readRoster($));
  $.ui.invalidate("ui.render");
}

async function readTheme($: EngineInterface): Promise<unknown> {
  try {
    return (await $.config.list()).find((row) => row.key === "theme")?.value;
  } catch {
    return undefined;
  }
}

/**
 * The party from the quests folder: every quest whose status is `working` walks as the hero of
 * its model, and every blocked, failed or checks-red quest sends its creature down the road. The
 * quartermaster and the boards are pseudo quests with no model of their own: the quartermaster is
 * the party's mage by rule (see marchingOrder), so they add no hero here. A quest that cannot be
 * read is simply not on the road.
 */
async function readRoster($: EngineInterface): Promise<void> {
  const next: Party = { heroes: [], foes: [] };
  const entries = await $.fs.list(questsDir).catch(() => []);
  for (const entry of entries) {
    if (entry.kind !== "dir" || entry.name.startsWith("_") || entry.name.startsWith(".")) continue;
    const dir = `${questsDir}/${entry.name}`;
    const status = await $.fs.read(`${dir}/status`).catch(() => "");
    const state = status.split("\n")[0]?.split("\t")[0]?.trim() ?? "";
    if (state === "working") {
      const meta = await $.fs.read(`${dir}/meta.json`).catch(() => "{}");
      let model = "", pseudo = false;
      try {
        const m = JSON.parse(meta) as { model?: string; build_model?: string; pseudo?: boolean };
        model = m.model || m.build_model || "";
        pseudo = m.pseudo === true;
      } catch { /* a quest without readable meta walks as a wanderer */ }
      if (!pseudo) next.heroes.push(heroFor(model));
    }
    const foe = foeFor(state);
    if (foe) next.foes.push(foe);
  }
  party = next;
}

function ensureLoaded($: EngineInterface): Promise<void> {
  return (loading ??= load($));
}

/** Repaint every mounted party without a render pass. */
async function repaint($: EngineInterface): Promise<void> {
  if (!calm || sites.size === 0) return;
  tick += 1;
  for (const [requestId, site] of [...sites]) {
    const result = await $.ui.blit({
      requestId,
      key: PARTY_KEY,
      cells: partyFrame(site.columns, tick, palette, party),
      columns: site.columns,
      rows: PARTY_ROWS,
    });
    // Denied means that row is gone (the turn ended, or a resize redrew it).
    if (result.deny !== undefined && sites.get(requestId) === site) sites.delete(requestId);
  }
}

/** A row that takes no space at all. */
function hidden($: EngineInterface, e: RenderInput): RenderElement {
  const { Box } = $.ui.resolve(e);
  return Box({ display: "none" });
}

export const register: Register = (on) => {
  on("session.start", async ($, e, next) => {
    if (!(await activated($))) return next(e);
    loading = undefined;
    sites.clear();
    await ensureLoaded($);
    await $.command.register({ name: COMMAND, description: "Guild calm: show the party instead of the tool calls." });
    return next(e);
  });

  on("command.run", { command: COMMAND }, async ($, e, next) => {
    if (!(await activated($))) return next(e);
    await ensureLoaded($);
    const wanted = !calm;
    try {
      await $.fs.write(preferencePath, wanted ? "on\n" : "off\n");
    } catch (error) {
      $.ui.toast(`Calm unchanged: ${error instanceof Error ? error.message : String(error)}`);
      return {};
    }
    calm = wanted;
    if (!calm) sites.clear();
    $.ui.invalidate("ui.render");
    $.ui.toast(calm ? "Calm on, the party is on the road" : "Calm off, tool calls are back");
    return {};
  });

  // A theme change repaints the party in the new family's colors.
  on("config.set", { key: "theme" }, async ($, e, next) => {
    if (!(await activated($))) return next(e);
    const result = await next(e);
    if (result.deny === undefined) {
      const chosen = PARTY_PALETTES[partyFamily(result.value)];
      if (chosen !== palette) {
        palette = chosen;
        if (calm) $.ui.invalidate("ui.render");
      }
    }
    return result;
  });

  on("ui.render", { component: "Spinner" }, async ($, e, next) => {
    if (!(await activated($))) return next(e);
    await ensureLoaded($);
    if (!calm || e.surface !== "terminal") {
      sites.delete(e.requestId);
      return next(e);
    }
    const columns = partyColumns(e.viewport?.columns);
    sites.set(e.requestId, { columns });
    const { Box, Raster } = $.ui.resolve(e);
    return Box({
      flexDirection: "column",
      children: Raster({ key: PARTY_KEY, columns, rows: PARTY_ROWS, cells: partyFrame(columns, tick, palette, party) }),
    });
  });

  // One hook per tool row. The matcher's type takes one literal, not the union a loop gives,
  // so each name is passed as the first one's type; at run time each call sees its own name.
  const toolRows = ["ToolUse", "ToolResult", "ToolGroup"] as const;
  for (const component of toolRows) {
    on("ui.render", { component: component as (typeof toolRows)[0] }, async ($, e, next) => {
      if (!(await activated($))) return next(e);
      await ensureLoaded($);
      return calm ? hidden($, e) : next(e);
    });
  }
};
