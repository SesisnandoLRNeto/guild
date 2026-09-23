# guild

A small, personal agent orchestration setup for Claude Code.

You are the **guildmaster**. You talk to one agent, the **quartermaster**. It turns your requests into **quests** and sends **adventurers** (other agent sessions) to do them, each in its own git worktree and tmux window. Adventurers must pass a **trial** (review + checks) before they can open a PR. You review every PR. Nothing merges without you.

Inspired by the "one orchestrator, many workers" idea from Kun Chen's [firstmate](https://github.com/kunchenguid/firstmate). This is a separate, much smaller take written from scratch for one person's workflow.

## Design

- **Personal, not per repo.** Everything installs into `~/.claude` and `~/.guild`. No project repo gets new files.
- **Scoped hooks.** Guild hooks load only in sessions guild starts (`claude --settings ~/.guild/*.json`), never in your normal sessions.
- **State on disk.** `~/.guild/quests/<slug>/` holds the brief, status, trial result and report. `~/.guild/events.log` is the event stream. Kill any session and nothing is lost.
- **No polling tokens.** The quartermaster runs `guild wait` in the background. It returns only when an adventurer reports, and Claude Code wakes the quartermaster when a background command finishes.
- **Right identity per repo.** A quest's git author and `gh` account come from the repo's remote owner (`~/.guild/local/identities.json`), so work repos get work identity and personal repos get personal identity.

## Install

Needs `tmux`, `git`, `gh`, `python3` and Claude Code. Optional: `nvim` (or set `$EDITOR`) for `guild edit`, and [claude-deck](https://github.com/SesisnandoLRNeto/claude-deck) for the `deck` tab.

```sh
git clone https://github.com/SesisnandoLRNeto/guild ~/Workspace/guild
~/Workspace/guild/install.sh
# edit ~/.guild/local/dispatch.json and ~/.guild/local/identities.json
guild up ~/Workspace
```

## Commands

| Command | What it does |
|---|---|
| `guild up [dir]` | Start or attach the `guild` tmux session, with the quartermaster in window `qm` |
| `guild quest <slug> --repo PATH [--model M] [--harness claude\|openrouter\|codex] < brief` | Worktree + branch `quest/<slug>` + adventurer window |
| `guild roster` | All quests and their state |
| `guild wait [secs]` | Block until the next event |
| `guild peek <slug>` / `guild send <slug> "<msg>"` | Look at or talk to an adventurer |
| `guild trial pass [note]` / `guild trial skip "<reason>"` | Record the trial for HEAD (inside a quest) |
| `guild close <slug> [--force]` | Kill the window, remove the worktree, archive the quest |
| `guild board open --html FILE [--decisions FILE] [--assets]` | Put a war table up and open it in the browser |
| `guild board wait <id>` | Block until the guildmaster answers, then print the answer |
| `guild board list` / `guild board url` | Boards and their state |
| `guild calm on\|off\|status` | Draw a blue bird instead of tool calls in guild sessions |
| `guild watch [secs]` | The sidebar renderer (the cockpit runs it for you) |
| `guild edit [slug]` | Open `$EDITOR` (nvim by default) on a quest's worktree, in its own tab |

Skills: `/campfire` (catch up: landed, under way, waiting on you), `trial` (the pre-PR gate) and `war-table` (decision boards and wrap-up reports).

## The war table

Terminal text cannot show a UI change or three variants side by side. So an adventurer can write an HTML page plus a `decisions.json` and put it on the war table: a local server (127.0.0.1 only) that wraps the page with a side panel for the options, a message and images you paste or drop. Your answer is written to the quest folder and the waiting adventurer picks it up and continues. Use it for decisions, and after a feature for the wrap-up report: before and after screens, evidence, performance, pain points, and the reasons behind each choice. Start pages from `web/board-template.html`.

## Harnesses: who runs a quest

A quest can run on three harnesses. The quartermaster picks one from `~/.guild/local/dispatch.json`, or you name it.

| Harness | What it is | Model looks like | Needs |
|---|---|---|---|
| `claude` | Claude Code on your Anthropic plan (default) | `opus`, `sonnet`, `claude-fable-5-1` | nothing |
| `openrouter` | Claude Code pointed at OpenRouter's Anthropic-compatible endpoint, so any model it serves can run a quest | `moonshotai/kimi-k2-thinking`, `deepseek/deepseek-chat`, `~anthropic/claude-sonnet-latest` | `OPENROUTER_API_KEY` in `~/.guild/local/env` |
| `codex` | The OpenAI Codex CLI on your ChatGPT or API account | `gpt-5.6-codex` | `npm i -g @openai/codex`, then `codex login` once |

```sh
guild quest big-rename --repo ~/code/app --harness openrouter --model moonshotai/kimi-k2-thinking < brief.md
guild quest app-icons  --repo ~/code/app --harness codex --model gpt-5.6-codex < brief.md
```

Why bother: the work that needs judgment gets your Anthropic quota, and the long mechanical sweeps go somewhere cheaper. Codex also generates images, which Claude does not.

**How the harnesses differ**

- Context is not shared between them. The quartermaster holds it and writes a brief per quest; the reports come back as files. That is the whole protocol, so any CLI agent can play.
- `openrouter` is still Claude Code, so it keeps the hooks, the trial gate and calm mode. Guild sets `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` and an empty `ANTHROPIC_API_KEY` for that quest only, never for your normal sessions.
- `codex` runs with `-s workspace-write -a never`, so it works unattended, writes only inside its worktree, and can still report to `~/.guild`. It has no stop hook, so a Codex adventurer that goes quiet is not reported on its own: the quartermaster notices it in the roster and peeks.
- The trial gate does not depend on hooks. Guild puts a `gh` shim first on every quest's PATH, so `gh pr create` is blocked on any harness until the trial passed for the current commit.

## The cockpit

`guild up` builds the whole workspace in tmux:

```
┌─ sidebar ────────┬─ quartermaster ─────────────────────────────┐
│ fleet            │                                             │
│                  │  > ship the pay rate change                 │
│  crowdgen-api    │                                             │
│  ● pay-rate      │  Quest pay-rate is on opus. Two others are   │
│    opus·working  │  still running. I will report back.          │
│  crowdgen-front  │                                             │
│  ● layouts [board]│                                            │
│    fable·waiting │                                             │
│                  │                                             │
│ recent           │                                             │
│  07:14 done      │                                             │
│   docs: PR #12   │                                             │
└──────────────────┴─────────────────────────────────────────────┘
 guild   0 qm   1 deck   2 pay-rate   3 layouts*    2 working · 1 waiting on you
```

- **Left pane**: every quest grouped by repo, with a colored state dot, its model, and the last events. It refreshes every 2 seconds.
- **Right pane**: the quartermaster. The only session you talk to.
- **One tab per quest**, plus a `deck` tab running [claude-deck](https://github.com/SesisnandoLRNeto/claude-deck) when it is installed. The deck speaks tmux, so from that tab you can mirror, jump to or type into any adventurer's pane. A tab is marked when its quest wants you: `*` waiting on a decision, `!` blocked or failed, `?` stopped without a report, `+` done.
- **Status bar** on the right: how many quests are working, how many wait on you, how many boards are open.

### Keys

The prefix is **Ctrl-g** (not Ctrl-b), so muscle memory from your own tmux does not fire here.

| Key | What |
|---|---|
| `Ctrl-g` then `0`…`9` | Jump to a tab |
| `Alt-Left` / `Alt-Right` | Previous or next tab |
| `Alt-h` / `Alt-l` | Move between the sidebar and the quartermaster |
| `Ctrl-g` `w` | Pick a quest from a list |
| `Ctrl-g` `e` | nvim on the current quest's worktree, in its own tab |
| `Ctrl-g` `g` | Open the war table in the browser |
| `Ctrl-g` `\|` / `-` | Split a pane; the mouse works too |

### It does not touch your tmux

The cockpit runs on its own tmux server, socket `guild`, with `config/guild.tmux.conf`. Your normal `tmux` keeps its own server, config, keys and sessions. Attach by hand with `tmux -L guild attach -t guild`, and kill everything with `tmux -L guild kill-server`.

## Calm mode: the blue bird

While an adventurer works, the tool calls scrolling by are noise. With calm on, guild sessions draw a blue bird gliding across two rows of sky where the spinner was, and tool rows (`ToolUse`, `ToolResult`, `ToolGroup`) draw at zero height. The model's context and the stored transcript are untouched: only the drawing changes. `/bird` toggles it inside a session.

It is a `mods/guild-calm` plugin on Claude Code's early-access function-hooks surface, so it is opt-in twice: `guild calm on` writes the preference, and guild exports `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` and `GUILD_CALM=1` only for the sessions it starts. Without both, the mod is a complete no-op, so your normal sessions never change. Verified on Claude Code 2.1.280; the API may change between releases.

## The trial

A `PreToolUse` hook blocks `gh pr create` in adventurer sessions unless `guild trial` recorded a result for the current HEAD. A new commit makes the trial stale. A skipped trial needs a reason, and the PR body must say `Trial: skipped - <reason>`.

## Folder trust

Claude Code asks you to trust every new git checkout. Worktrees go to `~/Workspace/.guild-worktrees/` (change with `GUILD_WORKTREES`), and `guild quest` marks a new worktree as trusted in `~/.claude.json` only when its main repo, or a parent folder, is already trusted.

## Roadmap

- A second layer of orchestrators, so one quartermaster is not the only liaison when the fleet grows
