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
| `guild revive [slug]` | Bring an active quest's window back after a restart |
| `guild pool list\|drop [repo]` | The warm worktree slots quests start from |
| `guild doctor` | Check tools, config, identities, orphan quests, waiting boards |
| `guild cost [slug]` | Tokens, replies, time and dollars per quest |
| `guild log [slug] [--since 7d] [--repo NAME]` | History: what ran, what it decided, what it cost |
| `guild retro [--since 14d]` | The facts a retro needs: overruled calls, skipped trials, stalls, spend |
| `guild board open --html FILE [--decisions FILE] [--assets]` | Put a war table up and open it in the browser |
| `guild board wait <id>` | Block until the guildmaster answers, then print the answer |
| `guild board list` / `guild board url` | Boards and their state |
| `guild ask "<question>" [--option "id=Label: why"]...` | Turn a question into a board page and open it |
| `guild calm on\|off\|status` | Draw a blue bird instead of tool calls in guild sessions |
| `guild watch [secs]` | The sidebar renderer (the cockpit runs it for you) |
| `guild edit [slug\|path]` | Your editor with the file tree: a quest's worktree, any folder, or your work root |

Skills: `/campfire` (catch up: landed, under way, waiting on you), `trial` (the pre-PR gate) and `war-table` (decision boards and wrap-up reports).

## The war table

**Every decision becomes a page.** An adventurer cannot escalate with a line of terminal text: `guild status <slug> needs-decision` either finds a board waiting for you, or builds one from the question and opens it. The short way is one command:

```sh
guild ask "Ship the chooser now or after the icons?" \
  --option "now=Ship now: users get it this week, two releases" \
  --option "later=Wait for the icons: one release, four days later" --recommend later
```

The agent then blocks on `guild board wait <id>` until you answer, and picks up your choice, your notes and your screenshots.

Terminal text cannot show a UI change or three variants side by side. So an adventurer can write an HTML page plus a `decisions.json` and put it on the war table: a local server (127.0.0.1 only) that wraps the page with a side panel for the options, a message and images you paste or drop. Your answer is written to the quest folder and the waiting adventurer picks it up and continues. Use it for decisions, and after a feature for the wrap-up report: before and after screens, evidence, performance, pain points, and the reasons behind each choice. Start pages from `web/board-template.html`.

## Costs and history

Claude Code writes a session log per working directory. A quest owns its worktree, so those are its logs: guild reads the token usage from them and prices it.

```
guild cost                     # every quest, most expensive first
guild log --since 7d           # what ran this week, with trial result and decisions
guild log pay-rate-fix         # one quest's whole story
```

`guild log <slug>` prints the brief, the harness and identity, how long it ran, tokens in and out, cache reads and writes, the trial result, every war table decision with what you picked, and the last events.

The live cost of each quest also shows in the cockpit sidebar and the total sits in the status bar. When a quest closes, its numbers are frozen into `ledger.json` next to the archived quest, so history never drifts.

Prices live in `~/.guild/local/pricing.json` (per million tokens, input, output, cache write, cache read). A model that is not in that file is priced with the default and flagged as estimated, so add new models as they ship. On a subscription nothing is billed per token: the dollars are what the same work would have cost on the API, which is still the honest way to compare two quests.

## The learning loop

History is only useful if it changes the next quest.

```
guild retro --since 14d
```

It counts the things worth learning from: **where your call differed from the agent's recommendation**, trials that were skipped, quests that escalated more than once or stopped silently, very short briefs, and spend per model. The `retro` skill turns that into three to five lessons in `~/.guild/lessons.md`, each with its evidence and what to do differently.

The quartermaster reads that file before writing any brief, so a lesson written on Friday changes Monday's work. A lesson that stops showing up in the evidence gets removed.

## From ticket to quest

Your work starts in a tracker, not in a terminal. The `intake` skill queries your open tickets live (Jira through its MCP tools), sorts them into ready, needs-you and not-code, proposes a shortlist, and after your yes creates the quests:

```sh
guild quest work-api-null-fix --repo ~/code/work-api --ticket PMC2-1023 < brief.md
```

The key is stored with the quest, so `guild log` and `guild retro` can show which ticket the work came from. Nothing is ever posted back to the tracker without your word.

## Tests

```sh
./test/run.sh      # 59 checks, about 5 seconds, no model calls
```

The suite runs against a throwaway `HOME`, a throwaway repo, its own tmux socket and a stub `claude`, so it never touches your real setup and never spends a token. It covers the quest lifecycle, identities, the war table (including a path traversal attempt), the trial gate in both forms, cost arithmetic against a synthetic session log, the retro counters, revive, close, and doctor. It also runs in CI on every push.

Close the terminal, reboot, or kill tmux: nothing is lost.

- The quartermaster keeps its Claude session id in `~/.guild/qm-session`, so the next `guild up` **resumes the same conversation** instead of waking up with an empty head. If that session log is gone, it starts a fresh one under a new id.
- Active quests get their windows back automatically (`guild revive` does it on its own during `guild up`). Each adventurer is relaunched in its worktree with `--continue`, and is told it was interrupted, so it checks `git log` and its own status before carrying on. A Codex quest resumes with `codex resume --last`.
- `guild doctor` reports anything left behind: quests with no window, finished quests still holding a worktree, boards waiting on you, broken identities, missing tools.

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
| `Ctrl-g` `e` | Your editor with the file tree on the current quest's worktree |
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
