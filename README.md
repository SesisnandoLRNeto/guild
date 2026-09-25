# guild

A small, personal agent orchestration setup for Claude Code.

You are the **guildmaster**. You talk to one agent, the **quartermaster**. It turns your requests into **quests** and sends **adventurers** (other agent sessions) to do them, each in its own git worktree and tmux window. Adventurers must pass a **trial** (review + checks) before they can open a PR. You review every PR. Nothing merges without you.

Inspired by the "one orchestrator, many workers" idea from Kun Chen's [firstmate](https://github.com/kunchenguid/firstmate). This is a separate, much smaller take written from scratch for one person's workflow.

## Design

- **Personal, not per repo.** Everything installs into `~/.claude` and `~/.guild`. No project repo gets new files.
- **Scoped hooks.** Guild hooks load only in sessions guild starts (`claude --settings ~/.guild/*.json`), never in your normal sessions.
- **State on disk.** `~/.guild/quests/<slug>/` holds the brief, status, trial result and report. `~/.guild/events.log` is the event stream. Kill any session and nothing is lost.
- **No polling tokens.** The quartermaster runs `guild wait` in the background. It returns only when an adventurer reports, and Claude Code wakes the quartermaster when a background command finishes.
- **No false alarms.** A turn that ends while an adventurer waits on a background command is not a silent stop. The stop hook looks again after two minutes (`GUILD_STOP_GRACE`) and only flags the quest if nothing moved.
- **Right identity per repo.** A quest's git author and `gh` account come from the repo's remote owner (`~/.guild/local/identities.json`), so work repos get work identity and personal repos get personal identity.

## Install

Needs `tmux`, `git`, `gh`, `python3` and Claude Code. Optional: `nvim` (or set `$EDITOR`) for `guild edit`, and [claude-deck](https://github.com/SesisnandoLRNeto/claude-deck) if you want its tab (`GUILD_DECK=1 guild up`).

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
| `guild quest <slug> --repo PATH [--ticket KEY] [--harness NAME] [--tier T \| --model M] [--plan] < brief` | Worktree + branch + adventurer window. With `--ticket`, the branch is `KEY/<slug>`. See [Routing](#routing-which-model-does-which-work) |
| `guild roster` | All quests and their state |
| `guild wait [secs]` | Block until the next event |
| `guild peek <slug>` / `guild send <slug> "<msg>"` | Look at or talk to an adventurer |
| `guild trial pass [note]` / `guild trial skip "<reason>"` | Record the trial for HEAD (inside a quest) |
| `guild close <slug> [--force]` | Kill the window, remove the worktree, archive the quest |
| `guild revive [slug]` | Bring an active quest's window back after a restart |
| `guild pool list\|drop [repo]` | The warm worktree slots quests start from |
| `guild check [slug] [--baseline]` | Run the brief's acceptance checks in the quest worktree (EDD) |
| `guild check <slug> --reseal` | Accept a changed Acceptance block (you only, never an adventurer) |
| `guild vision <repo>` / `guild vision status <repo>` | Collect a repo's evidence for its written vision |
| `guild jira once\|watch\|status` | Start quests from your `@quartermaster` comments on tickets |
| `guild shot <url> --name before\|after` | A screenshot taken the same way every time, filed under the quest |
| `guild peek <slug> --calls` | The tool calls an adventurer actually ran, from its session log |
| `guild doctor` | Check tools, config, identities, orphan quests, waiting boards |
| `guild cost [slug]` | Tokens, replies, time and dollars per quest |
| `guild log [slug] [--since 7d] [--repo NAME]` | History: what ran, what it decided, what it cost |
| `guild retro [--since 14d]` | The facts a retro needs: overruled calls, skipped trials, stalls, spend |
| `guild board open --html FILE [--decisions FILE] [--assets]` | Put a war table up and open it in the browser |
| `guild board wait <id>` | Block until the guildmaster answers, then print the answer |
| `guild board list` / `guild board url` | Boards and their state |
| `guild ask "<question>" [--option "id=Label: why"]...` | Turn a question into a board page and open it |
| `guild calm on\|off\|status` | Draw a party walking through a forest instead of tool calls |
| `guild new [dir] [name] [--harness H] [--tier T]` | A plain agent session in a new cockpit tab (also `Ctrl-g n`, or click `+ claude`) |
| `guild campaign` | The campaign board: every quest, session, subagent, ticket and to-do as a kanban (`Ctrl-g k`) |
| `guild pin [tab]` / `guild unpin [tab]` / `guild pins [menu]` | Keep sessions at the top of the sidebar; the menu jumps to one (`Ctrl-g p`, `Ctrl-g P`) |
| `guild todo add "<text>"` / `done <n>` / `drop <n>` | Your own cards on the campaign board, personal or not |
| `guild harnesses` | The agent CLIs guild knows, and the model each tier maps to |
| `guild impact [--rules FILE] [--into PAGE]` | Data model, impact and business rule changes, drawn for a backend wrap-up |
| `guild watch [secs]` | The sidebar renderer (the cockpit runs it for you) |
| `guild edit [slug\|path]` | Your editor: a quest's worktree or any folder (with the file tree), one file, or your work root |

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

**Diagrams and screenshots.** Write Mermaid inside `<pre class="mermaid">` in a board page and it renders, offline: the war table serves a pinned Mermaid that `install.sh` fetched once, so a state machine, a flow or a sequence can be the options themselves, approved before any code exists. `guild shot <url> --name before|after` takes screenshots one way every time (headless Chrome, fixed viewport, throwaway profile) so before and after pairs can be compared. Chrome starts cold on each shot, so one takes about 20 seconds.

**Backend wrap-ups: data model, impact and business rules.** `guild impact` draws the part of a backend report that a diff hides:

- **Data model changes.** Every migration (Liquibase formatted SQL or XML, Flyway SQL) is replayed once on the base branch and once on the quest's branch, and the two schemas are compared: an ER diagram of the changed tables with NEW, CHANGED and REMOVED columns, before and after column lists, and the constraints the database now enforces (CHECK, NOT NULL, DEFAULT, UNIQUE). Changed JPA entities are compared field by field, and a field with no column in the migrations is flagged in red.
- **Impact on the rest of the project.** Every file outside the migrations that names a changed table, entity or removed field, grouped by module and layer (API, service, repository, mapper, contract, tests), as a map and a table. The files the change did not touch are the ones to double check. Changed `@...Mapping` lines list the endpoints.
- **Business rule changes.** Code cannot say what a rule means, so guild finds the candidates (validation annotations, throws, conditions, enum constants, schema constraints) and the adventurer explains each one in plain words in a rules file: rule, before, after, where, why.

```sh
guild impact --into wrapup.html --rules rules.json    # inside a quest; rerunning replaces the section
```

`guild status done` refuses a backend quest whose wrap-up lacks the section, or leaves a rule candidate unexplained (`--no-impact "<why>"` is the recorded way out). No database and no build are needed: it reads the repo and git.

**The docket.** `guild docket` (or `Ctrl-g g`) is the war table's front page: every open decision from every quest on one parchment ledger, one row each. Pick a ruling (a star marks the adventurer's suggestion), add a note, or hold it until a date, then send them all with one button. A held decision parks its quest and tells the adventurer to stop waiting; on its date `guild wait` raises it again and the quartermaster brings it back to you. Wrap-ups waiting for your grade are rows too. The full list of boards stays at `/boards`.

**From your phone.** `guild remote on` opens a second copy of the war table on your Tailscale address (Tailscale must be running), behind a random key: `guild remote url` prints the link for your phone, which sets a cookie so the next pages need no key. `guild remote restart` applies it, `guild remote off` closes it. Guild sends a Mac notification when something waits for you (a decision, a block, a failure, a wrap-up to grade); add `"ntfy": "https://ntfy.sh/<a-private-topic>"` to `~/.guild/local/remote.json` for a phone push too. The push says only which quest waits and links to the docket: never the note, the ticket text or code, because the topic lives on a third-party service. `"mac": false` turns the Mac notifications off; `guild notify test` checks both.

**Grading the result.** Every wrap-up page asks you for a grade (1 to 5) and a verdict: ready to merge, needs changes, or split a follow-up. "Needs changes" sends your notes straight back to the adventurer, which carries on. The grade stays with the quest (`grade.json`), the campaign board shows it (or a red "grade it" until you do), and `guild retro` compares grades by model, tier and harness, so routing in `dispatch.json` follows your judgment, not only whether checks passed.

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

**Lessons need evidence.** A lesson is proposed with `guild lesson propose "<lesson>" --evidence "<quest>: <quote>" --evidence "<quest>: <quote>"`. It needs verbatim quotes from at least two different quests, and guild checks each quote really is in that quest's brief, report, trial, boards, your grade notes, events or session log. The proposal becomes a docket row; only what you accept reaches `lessons.md` (with its evidence), and a hook stops the quartermaster from writing that file by hand. `guild lessons` lists them all.

## Acceptance as checks (EDD)

"The agent says it works" is not evidence. A brief's `Acceptance:` block can hold checks:

```
Acceptance:
- check: ./mvnw -q test -Dtest=RateValueIT
- check: curl -sf localhost:8080/health
- the list shows dated history            <- no command: shown on the wrap-up page
```

- When the quest starts, those lines are **sealed** into `acceptance.json` with a hash. The adventurer cannot quietly rewrite them: a hook refuses the edit, and `guild check` refuses to run a contract whose hash changed. Only you reseal (`guild check <slug> --reseal`).
- `guild check --baseline` runs before any work. A check that already passes is reported as **weak**: it proves nothing about the change.
- `guild check` runs them in the worktree; `guild trial pass` is refused until the last run was green on the current commit.
- The retro reports **first-pass rate per model**: how often a quest met its own acceptance on its first real run. That is how you find out, with numbers, whether a cheaper model is enough for a kind of ticket.

## A repo's vision

A vision is an acceptance policy for a whole repo: given a change, would this repo accept it or resist it?

- `guild vision <repo>` collects the evidence: merged PRs, declined PRs, reverts, read with the repo owner's GitHub account. It refuses when there is too little history to find real values.
- The `vision` skill drafts principles that each cite that evidence, then writes 8 to 12 hard hypothetical changes and puts them on the war table as one board. You rule on them; your answers are folded back in and the result is sealed in `~/.guild/visions/<repo>.md`, outside the repo.
- Every new quest on that repo is told to read it and to stop and ask when a change goes against it. The quartermaster reads it before writing a brief.

## From ticket to quest

Your work starts in a tracker, not in a terminal. The `intake` skill queries your open tickets live (Jira through its MCP tools), sorts them into ready, needs-you and not-code, proposes a shortlist, and after your yes creates the quests:

```sh
guild quest work-api-null-fix --repo ~/code/work-api --ticket PMC2-1023 < brief.md
```

The key is stored with the quest, so `guild log` and `guild retro` can show which ticket the work came from. Nothing is ever posted back to the tracker without your word.

## Tickets that start themselves

Comment `@quartermaster repo:work-api build the fair pay list` on a ticket, and a quest can start from it. This is the one part of guild that acts without you typing a command, so it is built around what it must never do:

- **Only your comments count.** Anyone else mentioning the trigger is ignored, and remembered as ignored.
- **Ticket text never becomes a command.** `check:` lines come only from your comment; the ticket description is context, with any `check:` lines stripped.
- **It asks first.** By default it puts "start a quest for SARA-812?" on the war table with the exact brief it would use. It starts only on your yes. `"autostart": true` skips the question and is capped by `max_active`.
- **It never writes to Jira.** Ticket comments stay yours. It tells you, with a desktop notification, when a quest it started is done, with the note (usually the PR).
- It watches only the projects you list; the repo comes from `repo:<name>` or a per-project default, and an unknown repo is a question, not a guess.

Set it up with `config/jira.example.json` copied to `~/.guild/local/jira.json` and `JIRA_API_TOKEN=...` in `~/.guild/local/env`. `guild jira once` polls one time; with `"watch": true` the cockpit opens a `jira` tab running `guild jira watch`.

## Tests

```sh
./test/run.sh      # 145 checks, under a minute, no model calls
```

The suite runs against a throwaway `HOME`, a throwaway repo, its own tmux socket and a stub `claude`, so it never touches your real setup and never spends a token. It covers the quest lifecycle, identities, the war table (including a path traversal attempt), the trial gate in both forms, cost arithmetic against a synthetic session log, the retro counters, revive, close, and doctor. It also runs in CI on every push.

Close the terminal, reboot, or kill tmux: nothing is lost.

- The quartermaster keeps its Claude session id in `~/.guild/qm-session`, so the next `guild up` **resumes the same conversation** instead of waking up with an empty head. If that session log is gone, it starts a fresh one under a new id.
- Active quests get their windows back automatically (`guild revive` does it on its own during `guild up`). Each adventurer is relaunched in its worktree with `--continue`, and is told it was interrupted, so it checks `git log` and its own status before carrying on. A Codex quest resumes with `codex resume --last`.
- `guild doctor` reports anything left behind: quests with no window, finished quests still holding a worktree, boards waiting on you, broken identities, missing tools.

## Running a phase of tickets

A phase is not "start seven quests". Tickets depend on each other, and a quest that starts before its dependency is merged writes against a schema that does not exist yet.

**Before the first quest**

1. `guild doctor` — green, and the repo's owner maps to the right GitHub account.
2. Check the repo has agent instructions (`AGENTS.md` or `CLAUDE.md`). A quest is only as good as what the repo tells an agent.
3. Write the phase down: ticket, what it waits on, one line of intent. The `intake` skill does that from the tracker.

**Then run it in waves**

A wave is the set of tickets whose dependencies are already merged. Three or four at a time is plenty: the pool has 4 slots per repo by default, and every quest you start is another PR you owe a review.

```sh
guild quest fair-pay-values --repo ~/code/project-api --ticket SARA-812 --model sonnet <<'EOF'
Intent: why this ticket exists, in your words
Context: the ticket, the spec page, the code it touches, decisions already made
Acceptance: what done looks like, as checks someone can run
Constraints: what not to touch; whether the trial may be skipped
Quest type: code
EOF
```

The branch is `SARA-812/fair-pay-values`, the way the repo already names branches, so branch, PR and ticket line up.

**While a wave runs**

- The sidebar shows each quest, its model and its live cost. `*` wants a decision, `!` is blocked, `?` stopped without reporting.
- Answer boards the same day. A blocked adventurer costs nothing and moves nothing.
- `/campfire` tells you what landed, what runs, what waits on you.
- Review each PR as it arrives. A merged dependency is what unblocks the next wave.

**Closing a wave**

`guild close <slug>` returns the worktree to the warm pool and freezes the cost into history. Then `guild retro --since 7d`, and let the `retro` skill write the lessons before the next phase.

**What it costs**

`guild cost` after the first wave beats any estimate. Route the mechanical tickets (DDL, contracts, small endpoints) to Sonnet in `~/.guild/local/dispatch.json` and keep the expensive models for the ones with judgment in them.

## The worktree pool

A fresh worktree has no `node_modules`, no `target/`, no build cache, so the first build of every quest pays for all of it again, in minutes and in tokens. Guild keeps a small pool of slots per repo instead (4 by default, `GUILD_POOL_MAX`).

A quest takes a free slot and points it at its own branch; closing the quest returns the slot with `git clean -fd`, which removes untracked leftovers but keeps ignored build output. The next quest on that repo starts warm. `guild quest --fresh` opts out and gets a throwaway worktree, removed on close. `guild pool list` shows what is busy, `guild pool drop [repo]` clears free slots.

## After a restart

Close the terminal, reboot, or kill tmux: nothing is lost.

- The quartermaster keeps its Claude session id in `~/.guild/qm-session`, so the next `guild up` **resumes the same conversation** instead of waking up with an empty head. If that session log is gone, it starts a fresh one under a new id.
- Active quests get their windows back automatically (`guild revive` does it on its own during `guild up`). Each adventurer is relaunched in its worktree with `--continue`, and is told it was interrupted, so it checks `git log` and its own status before carrying on. A Codex quest resumes with `codex resume --last`.
- `guild doctor` reports anything left behind: quests with no window, finished quests still holding a worktree, boards waiting on you, broken identities, missing tools.

## Harnesses: who runs a quest

A harness is an agent CLI. Guild is not tied to Claude Code: each harness is a few lines of config in `config/harnesses.json`, and you add your own in `~/.guild/local/harnesses.json` without touching code. `guild harnesses` lists them.

| Harness | What it is | Needs |
|---|---|---|
| `claude` | Claude Code on your Anthropic plan (default) | nothing |
| `openrouter` | Claude Code pointed at OpenRouter's Anthropic-compatible endpoint, so any model it serves can run a quest | `OPENROUTER_API_KEY` in `~/.guild/local/env` |
| `codex` | The OpenAI Codex CLI on your ChatGPT or API account | `npm i -g @openai/codex`, then `codex login` once |

**Adding a CLI.** A harness says how to start a quest, how to resume one, how to open a plain tab, how to pass a model, and which model each tier means:

```json
{
  "gemini": {
    "bin": "gemini",
    "hooks": false,
    "model_flag": "-m {model}",
    "start": "gemini {model_args} --yolo -i {prompt_and_kickoff}",
    "tab": "gemini {model_args}",
    "tiers": { "plan": "gemini-pro-latest", "build": "gemini-flash-latest", "deep": "gemini-pro-latest", "light": "gemini-flash-latest" }
  }
}
```

That is an example of the shape, not a tested config: check the CLI's own flags and model names. Placeholders: `{slug}`, `{qdir}`, `{worktree}`, `{guild_home}`, `{settings}`, `{name}`, `{session}`, `{model_args}`, `{prompt}`, `{kickoff}`, `{prompt_and_kickoff}`. `env` and `needs_env` set and check variables for that harness only.

**What works on any harness, and what needs Claude Code**

- Any harness: worktrees, briefs, reports (`guild status`), the war table, acceptance checks, the trial gate on `gh pr create` (a `gh` shim, not a hook), history, the campaign board and pins. Dollar costs and the session cards on the campaign board come from Claude Code logs, so other harnesses show their quests there but no spend. When the process exits while the quest still says working, guild marks it stopped, so a quiet stop is caught even without hooks.
- Claude Code only (`hooks: true`): the stop hook that notices a turn ending without a report while the process is still alive, the guard hooks, calm mode, and the `trial` skill. `openrouter` keeps all of these, because it is still Claude Code.
- The quartermaster itself runs on Claude Code (it is a Claude Code agent). The adventurers can be anything.
- Context is not shared between harnesses. The quartermaster holds it and writes a brief per quest; the reports come back as files. That is the whole protocol, so any CLI agent can play.

## Routing: which model does which work

Tiers name the kind of work. Each harness maps a tier to its own model, so a rule keeps its meaning when you switch harness.

| Tier | Work | `claude` | `openrouter` (default map) |
|---|---|---|---|
| `plan` | Planning, architecture, open investigations | `opus` | `moonshotai/kimi-k2-thinking` |
| `build` | Normal implementation | `sonnet` | `deepseek/deepseek-chat` |
| `deep` | High complexity | `claude-fable-5-1` | `moonshotai/kimi-k2-thinking` |
| `light` | Easy, well defined | `haiku` | `deepseek/deepseek-chat` |

**Plan, then build.** `--plan` splits a quest in two. The adventurer starts on the `plan` tier, writes `plan.md`, and puts it on the war table for you. When you approve, it runs `guild status <slug> planned`, and guild restarts it in the same conversation on the build model (`--tier`, `--model`, or the `build` tier). So Opus thinks, you approve, and Sonnet types.

```sh
guild quest rate-api  --repo ~/code/api --plan < brief.md                 # opus plans, sonnet builds
guild quest hard-bug  --repo ~/code/api --plan --tier deep < brief.md     # opus plans, fable builds
guild quest typo      --repo ~/code/web --tier light < brief.md           # haiku, no plan
guild quest big-sweep --repo ~/code/app --harness openrouter --tier build < brief.md
```

**Effort and budget.** Each tier also carries an effort level (Claude's `--effort`, Codex's reasoning effort): plan and deep run high, build medium, light low. Override with `--effort`. Every quest can have a dollar cap: `--budget 40`, a rule's `budget`, or `budget_default` in `dispatch.json` (30 in the example). Past the cap, the adventurer's tools pause (the hook still lets it run `guild` commands), and the docket asks you: raise by $10, $25 or $50, or stop. `guild budget <slug> [N | +N]` shows or changes a cap by hand. Claude Code's own `--max-budget-usd` works only in print mode, so guild enforces the cap itself, from the same cost numbers as `guild cost`.

**Helpers, for big work.** Inside a quest, `guild helper <name> [--tier light|build] < brief` starts a helper quest: same repo, a worktree on `<parent branch>--<name>`, the parent's ticket. The parent waits with `guild wait --for <slug>` (its own cursor, so the quartermaster still sees every event), then merges the helper's branch and reviews it. Helpers do not push or open PRs, and cannot start helpers of their own; `helpers_max` in `dispatch.json` caps them (2 by default). In the side menu a helper sits right after its parent (`└ name`); on the campaign board it joins the parent's thread and shows on the parent's card.

You rarely type these. The quartermaster matches each task to a rule in `~/.guild/local/dispatch.json` (copied from `config/dispatch.example.json`) and says which rule it used. The default rule is "build with a plan first". Change the map in `harnesses.json` and the rules in `dispatch.json`; name a model yourself and it wins.

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
 guild   0 qm   1 pay-rate   2 layouts*    2 working · 1 waiting on you
```

- **One screen, like herdr**: every tab carries the same side menu at the same width, so switching tabs changes only the content on the right. New Claude tabs, terminals (`Ctrl-g t`) and editors (`Ctrl-g e`) open as tabs inside the cockpit, never as a separate window. The tab strip sits on top.
- **The side menu**, laid out like claude-deck: a title bar, thin panels with the title in the border (Pinned, Tabs, Activity), rows numbered like the tab strip with a colored chip per repo or kind (`term`, `edit`, `ai`, `qm`), the tab you are on highlighted, and a `key:Action` help bar. Click a row to switch to that tab. The help bar says which way the keys work right now: a green dot means the side menu has focus and plain letters work (`n` new Claude tab, `t` terminal, `b` board, `g` war table, `p` pins, `0`-`9` tab, `x` close a terminal or editor tab, `?` every key, `q` back); `^g` means press `Ctrl-g` first, from anywhere, with the same letters. The whole cockpit uses the deck's blue-grey surface (Catppuccin Mocha).
- **Right pane**: the quartermaster. The only session you talk to.
- **One tab per quest**, plus your terminals, editors and Claude tabs. The side menu and the campaign board show what claude-deck used to, so its tab is off by default; `GUILD_DECK=1 guild up` brings it back. A tab whose program exits closes itself. A tab is marked when its quest wants you: `*` waiting on a decision, `!` blocked or failed, `?` stopped without a report, `+` done.
- **Status bar**: every tab is a button, click it to switch. On the right, buttons for `+claude`, `+term`, `board` (the campaign) and `pins`, then how many quests are working, how many wait on you, how many boards are open.

### Keys

Press **Ctrl-g**, then a letter. You can keep Ctrl held for the letter: `Ctrl-g Ctrl-k` works the same as `Ctrl-g k`, so each action is one hand, one motion. Not sure which letter? **`Ctrl-g ?`** (or `Ctrl-g Space`) opens a menu of every action; press its letter or click it.

Why not a bare `Ctrl-k`: every Ctrl letter already means something in Claude Code, zsh or nvim (`Ctrl-k` deletes a line, `Ctrl-t` opens the todo list, `Ctrl-h/j/k/l` move between nvim windows), so taking one away would break the tools inside the cockpit.

| Key | What |
|---|---|
| `Ctrl-g` `?` | Menu of every action |
| `Ctrl-g` then `0`…`9` | Jump to a tab |
| `Ctrl-g` `Left` / `Right` | Previous or next tab |
| `Ctrl-g` `Ctrl-h` / `Ctrl-l` | Move to the sidebar, and back to the quartermaster |
| `Ctrl-g` `w` | Pick a tab from a list |
| `Ctrl-g` `n` | A new Claude tab in the current folder (`Ctrl-g N` asks for the folder) |
| `Ctrl-g` `t` | A plain terminal tab in the current folder |
| `Ctrl-g` `e` | Your editor with the file tree on the current quest's worktree |
| `Ctrl-g` `E` | Asks what to open: a quest, a folder or one file |
| `Ctrl-g` `b` (or `k`) | Open the campaign board in the browser |
| `Ctrl-g` `g` | The docket: every open decision on one page |
| `Ctrl-g` `p` | Pin or unpin the current tab (it goes to the top of the sidebar) |
| `Ctrl-g` `P` | Menu of pinned sessions: pick one to jump to it, or to reopen it if its tab is gone |
| `Ctrl-g` `=` | Put the sidebar back to its size (about a quarter of the window, 24 to 36 columns) |
| `Ctrl-g` `\|` / `-` | Split a pane; the mouse works too |

### The campaign board

`guild campaign` (or `Ctrl-g k`) opens a kanban on the war table server, styled as a guild's quest board. It shows the whole moment, not only the quartermaster's quests:

- **Quest board**: your open Jira tickets that have no quest yet (when `~/.guild/local/jira.json` is set up), and your own to-dos. Post one from the page or with `guild todo add`.
- **On the road**: quests at work, and every Claude session on this machine that is mid-turn, inside the cockpit or not. Subagents a session is running show on its card as companions.
- **Awaiting orders**: quests that need a decision, are blocked or stopped, and sessions whose turn ended and wait for you.
- **Trial**: quests that passed the trial and wait for their PR.
- **Returned**: done and closed in the last week.

Each card shows the model as a wax seal (legendary for Fable, epic for Opus, rare for Sonnet, common for Haiku), what the agent is on, its repo and age, and buttons: go to its tab, reopen a session in the cockpit, pin it, open its wrap-up, decision board, PR or ticket. Sessions are read from Claude Code's own logs, so a spec session you named with `/rename` shows by that name. It refreshes every 3 seconds.

### Pins

`Ctrl-g p` pins the tab you are on, and it moves to the top of the sidebar with its state (working, your turn, how many subagents). A tab opened with `guild new` pins by its session id, so the pin survives `guild up`: `Ctrl-g P` lists the pins and reopens a closed one with its conversation. Pinned cards also come first on the campaign board.

### It does not touch your tmux

The cockpit runs on its own tmux server, socket `guild`, with `config/guild.tmux.conf`. Your normal `tmux` keeps its own server, config, keys and sessions. Attach by hand with `tmux -L guild attach -t guild`, and kill everything with `tmux -L guild kill-server`.

## Calm mode: the party on the road

While an adventurer works, the tool calls scrolling by are noise. With calm on, guild sessions draw a night forest where the spinner was: stars and a moon, pines and bushes drifting past, and a party of three walking through it, a helmeted knight with a sword in front, a wizard whose staff twinkles, a hooded archer with a drawn bow behind. Seven rows, plain ASCII, colors follow your dark or light theme. Tool rows (`ToolUse`, `ToolResult`, `ToolGroup`) draw at zero height. The model's context and the stored transcript are untouched: only the drawing changes. `/calm` toggles it inside a session, and `guild peek <slug> --calls` still shows every command from the session log.

It is a `mods/guild-calm` plugin on Claude Code's early-access function-hooks surface, so it is opt-in twice: `guild calm on` writes the preference, and guild exports `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` and `GUILD_CALM=1` only for the sessions it starts. Without both, the mod is a complete no-op, so your normal sessions never change. Verified on Claude Code 2.1.280; the API may change between releases.

## The trial

A `PreToolUse` hook blocks `gh pr create` in adventurer sessions unless `guild trial` recorded a result for the current HEAD. A new commit makes the trial stale. A skipped trial needs a reason, and the PR body must say `Trial: skipped - <reason>`.

## Folder trust

Claude Code asks you to trust every new git checkout. Worktrees go to `~/Workspace/.guild-worktrees/` (change with `GUILD_WORKTREES`), and `guild quest` marks a new worktree as trusted in `~/.claude.json` only when its main repo, or a parent folder, is already trusted.

## Roadmap

- A second layer of orchestrators, so one quartermaster is not the only liaison when the fleet grows
