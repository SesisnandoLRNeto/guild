# guild

Personal agent orchestration for Claude Code and other agent CLIs.

You are the **guildmaster**. You talk to one agent, the **quartermaster**. It turns your requests into **quests** and sends **adventurers** (other agent sessions) to do them, each in its own git worktree and its own tab of a tmux cockpit. An adventurer must pass a **trial** (an adversarial review and the project's checks) before it can open a PR. You review every PR, and nothing merges without you.

Inspired by the "one orchestrator, many workers" idea from Kun Chen's [firstmate](https://github.com/kunchenguid/firstmate). This is a separate take, written from scratch for one person's workflow.

> **Status: a personal tool, shared in the open.** It is built for one person's daily work on macOS (the core also runs on Linux, where CI runs the tests). It is not a product, and nothing here is supported or stable. There is no license yet, so reuse is not granted by default: open an issue if you want to use part of it. The RPG names (guildmaster, quest, war table) are a skin; [How it works](#how-it-works) maps each one to a plain engineering term.

## What it does

- **One screen.** A tmux [cockpit](#the-cockpit) with the same side menu in every tab, click and key driven, in claude-deck's colors. New terminals, editors and Claude tabs open inside it.
- **Decisions on pages, not in chat.** Agents put every real choice on the [war table](#the-war-table), a local parchment page. The [docket](#the-war-table) lists every open decision on one page: rule, hold until a date, send all. It works from your phone over Tailscale, and you get a notification when something waits for you.
- **Plans before code.** A quest can plan first on Opus, show the plan on a page, and build on another model once you approve ([routing](#routing-which-model-does-which-work)).
- **Proof before review.** Acceptance written as commands and sealed at the start ([EDD](#acceptance-as-checks-edd)), the trial gate on `gh pr create`, and a wrap-up page for every code quest. Backend wrap-ups draw the data model changes, their impact and the business rule changes. You grade each wrap-up, and the grades feed the retro.
- **The whole picture.** A [campaign board](#the-campaign-board): a kanban of every quest, every Claude session on the machine, its subagents and your tickets, with Trello-like labels and the real PR state from GitHub. Finished work closes itself once graded or merged.
- **Any model, any CLI.** Harnesses are config: Claude Code, OpenRouter, Codex or your own. Tiers route planning to Opus, building to Sonnet, hard work to Fable and small fixes to Haiku, each with an effort level and an optional dollar cap ([harnesses](#harnesses-who-runs-a-quest)).
- **Room to grow.** Helper quests under a quest, quests on another machine over SSH, lessons that need evidence from two quests, a Jira watcher, and optional [Jev](#the-war-table) for small judgment calls.

## How it works

guild is a small control plane around agent CLIs. It adds no server of its own except a local web page, and it keeps all state in plain files.

```
 you ──asks──> quartermaster ──guild quest + brief──> adventurer (one per quest)
  │            (Claude Code)                          own worktree, own tmux tab
  │                 ▲                                        │
  │           guild wait                          guild status / guild ask
  │                 │                                        ▼
  └──answers──> war table <──reads/writes──> ~/.guild/quests/<slug>/  +  events.log
               (127.0.0.1)                                   │
                                                  trial passes ──> gh pr create ──> you merge
```

1. You ask the quartermaster for something. It picks a rule from `dispatch.json` (which harness, tier, budget, plan first or not) and writes a brief.
2. `guild quest` takes a warm worktree from the pool, makes the branch, seals the acceptance checks, and starts the adventurer in its own tmux tab.
3. The adventurer works and reports with `guild status`. A real question goes to the war table (`guild ask`), and it blocks on `guild board wait` until you answer on the page.
4. The quartermaster sleeps on `guild wait` (a blocking background command, so no tokens are spent polling) and wakes when a line lands in `events.log`.
5. Before `gh pr create`, the trial must pass for the current commit: sealed checks green, adversarial review done. A `gh` shim and a hook enforce it.
6. The adventurer writes a wrap-up page. You grade it and review the PR. Only you merge. A merged or closed PR closes the quest and returns the worktree to the pool.

| guild name | Plain term | Where |
|---|---|---|
| guildmaster | the human | - |
| quartermaster | orchestrator agent (a Claude Code session) | tmux window `qm`, `agents/quartermaster.md` |
| quest | one unit of work: brief, branch, worktree, status | `~/.guild/quests/<slug>/` |
| adventurer | worker agent session for one quest | `prompts/adventurer.md` |
| harness / tier | how to launch an agent CLI / which model and effort for a kind of work | `config/harnesses.json`, `dispatch.json` |
| trial | pre-PR gate for one commit | `hooks/pr-gate.sh`, `bin/shims/gh`, `skills/trial` |
| war table / board / docket | local web server / one decision or report page / the list of open decisions | `bin/wartable.py`, `web/` |
| campaign board | kanban of quests, sessions and tickets | `bin/fleet.py`, `web/campaign.html` |
| cockpit | tmux on its own server, with a side menu | `config/guild.tmux.conf`, `bin/watch.py` |

Code map: `bin/guild` is the CLI (Bash); every `bin/*.py` is one area (war table, fleet, ledger, checks, lessons, budget, impact, harness, Jira, Jev, machines). Python uses only the standard library.

## Design

- **Personal, not per repo.** Everything installs into `~/.claude` and `~/.guild`. No project repo gets new files.
- **Scoped hooks.** Guild hooks load only in sessions guild starts (`claude --settings ~/.guild/*.json`), never in your normal sessions.
- **State on disk.** `~/.guild/quests/<slug>/` holds the brief, status, trial result and report. `~/.guild/events.log` is the event stream. Kill any session and nothing is lost.
- **No polling tokens.** The quartermaster runs `guild wait` in the background. It returns only when an adventurer reports, and Claude Code wakes the quartermaster when a background command finishes.
- **No false alarms.** A turn that ends while an adventurer waits on a background command is not a silent stop. The stop hook looks again after two minutes (`GUILD_STOP_GRACE`) and only flags the quest if nothing moved.
- **Right identity per repo.** A quest's git author and `gh` account come from the repo's remote owner (`~/.guild/local/identities.json`), so work repos get work identity and personal repos get personal identity.
- **Nothing leaves the Mac by default.** The phone access, push notifications and Jev are off until you turn them on, and Jev follows a data rule (blocked owners stay home). Guild reads GitHub and Jira; it never writes to them.

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
| `guild story "<name>" TICKET...` | Name the campaign board row those tickets sit in (an empty name removes it) |
| `guild validate <slug>` / `guild validate export <slug> [--out F]` | The quest's end-to-end checklist, run before a merge; a standalone copy for the team |
| `guild why <slug>` / `guild why open <slug>` | The quest's Why card: show your answers, or put the card on the docket again |
| `guild rules` / `guild drill` | The rule book (every business rule the work changed, per area) and this week's three-question drill |
| `guild tidy [--dry-run]` | Move old events to monthly files and pack old closed quests (runs monthly on its own) |
| `guild behaviour [slug]` | An independent validator drives the running app through the scenarios; it never reads the code |
| `guild pr-body [slug]` | The PR's contract section for HEAD; `gh pr create` needs it |
| `guild treasury` | What the work cost and what it was worth, as charts: spend per day, per story, ticket and model, grades against cost, Jev |
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

Terminal text cannot show a UI change or three variants side by side. So an adventurer can write an HTML page plus a `decisions.json` and put it on the war table: a local server (127.0.0.1 only) that wraps the page with a side panel for the options, a message and images you paste or drop. Your answer is written to the quest folder and the waiting adventurer picks it up and continues. Use it for decisions, and after a feature for the wrap-up report: before and after screens, evidence, performance, pain points, and the reasons behind each choice. Start pages from `web/board-template.html`. Click any picture on a board page to open it large: zoom with the wheel or `+`/`-`, drag to move, arrows for the next picture, `F` for full screen.

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

**Finished work leaves the cockpit.** Grade a wrap-up "ready to merge" or "split" and the quest's tab closes (the agent stops; the worktree and branch stay, so `guild revive <slug>` or a later "needs changes" brings it back in the same conversation). When the PR is merged or closed on GitHub, the war table server closes the quest for good: archived, worktree back to the pool, never with uncommitted changes. `"auto_close": false` in `dispatch.json` turns this off.

**Jev for small judgment calls (optional).** With a TypeSafe key (`TYPESAFE_API_KEY` in `~/.guild/local/env`), `guild jev on <scope>` lets Jev answer typed questions in under a second: `board` decides whether any session on this Mac is waiting for your decision (cached per message); `quests` sorts a silent stop into asking (a board on the docket), finished, stuck or waiting on a job, and gives the trial a 1-5 risk score (`guild jev risk`); `global` adds a Stop hook to `~/.claude/settings.json` (with a backup) that notifies you when an allowed session waits for you. The data rule decides what may leave the Mac: owners or paths in `block` (Appen by default) stay home unless in `allow` (`guild jev allow <owner or path>`; quests run in worktrees elsewhere, so allow by owner). Off, without a key, or on any error, guild does exactly what it did before. `guild jev test` checks the key.

**Validation before a merge.** Every code quest also writes `scenarios.json`: an end-to-end run sheet shown at `/q/<slug>/validate` (`guild validate <slug>`, or the Validation tile on the wrap-up). It lists what is being tested, the exact setup commands, then scenarios in groups run in order, each with what to do, a command with a Copy button and what you must see. When the frontend changed, a map of the screens shows the path through the app, and each screen has its before (base branch) and after (the quest's branch) shots side by side. You mark each scenario pass, fail or skip; a fail or a skip needs a note. "Send the failures to the adventurer" hands the failed ones back with your notes. When the last one passes, guild writes a certificate (`certificate.json`: when, the counts, the commit), logs `validated`, and the page, the wrap-up and the campaign card say so. A wrap-up cannot be graded "ready to merge" without a certificate for the commit the branch is on now, so a later commit means the list is run again. `guild status done` refuses a code quest without scenarios (`--no-scenarios "<why>"` is the recorded way out). For the team, `guild validate export <slug>` (or "Download for the team" on the page) writes one self-contained HTML file, screenshots inside, with your results on each scenario and checkboxes that stay in each reader's browser; ask the quartermaster to publish it as a private Artifact and share it from its Share menu.

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

### The treasury

`guild treasury` opens a page on the war table with what the work cost and what it was worth:

- **Spend per day**, last 30 days, for every Claude Code session on this Mac, split by scope (quests, quartermasters, your own sessions) or by model.
- **Where the money went**: totals per story, ticket, quest, model or repo, for 7 days, 30 days or all time.
- **Was it worth it?** Per model, tier or harness: quests, total and average cost, your average grade, first-pass rate, overruled calls, stalls. A scatter of cost against grade, one dot per quest, and the token mix per model (cache reads are most tokens but cost little).
- **Your own sessions by folder**, **Jev** calls and tokens by use, and a sortable table of every quest.

Every Jev call is logged with its tokens (`~/.guild/jev-usage.jsonl`); add `"jev": {"input": N, "output": N}` (dollars per million tokens) to `pricing.json` to see dollars. A model with no price is flagged and priced with the default.

How costs are counted: Claude Code writes one log line per content block of a reply, each carrying the same usage, so guild counts each reply once by its message id. A pooled worktree also holds the logs of earlier quests, so a quest counts only lines written after it started.

## Understanding the business rules

Three habits, built in, so the rules behind the work reach you whole: why each exists, what it changes, and what comes next.

**The Why card.** Every quest starts by putting a card on the docket with five questions you answer in your own words: the **pain** (who suffers today, one real example), the **rule** (in one sentence), the **decision** (who decided, what was rejected), the **impact** (what changes, for which users, data or money) and the **future** (what it unlocks or blocks). The AI never fills it in: thinking first is the point. Your answers are kept in `why.json` and top the quest's plan and wrap-up, so you judge the result against your own why. The adventurer then checks your card against the ticket, the spec and the code, and raises up to three challenges on the war table where something contradicts it or is missing. `--no-why` skips it; helpers never get one.

**The rule book.** Every backend wrap-up explains its business rule changes in a rules file (`guild impact --rules`): the rule, before, after, where, why, and an example with real values, its source and the tests that prove it. `guild rules` gathers them from every quest, live and closed, into one book per area, with search and the history of each rule (which quests changed it, and when).

**The weekly drill.** `guild drill` asks three rules a week: first those you were never asked, then those you missed, then the ones asked longest ago. You answer first, then see the truth with where it lives in the code, and mark yourself right or wrong; a miss comes back the next week. The docket says when this week's drill waits.

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

## Housekeeping

Once a month the war table server runs `guild tidy`: events older than 30 days move from `events.log` to `events/YYYY-MM.log` (the readers' byte cursors are shifted, so nothing is replayed or missed, and history, the retro and lessons read the monthly files too), and quests closed more than 60 days ago get their boards and screenshots packed into `files.tar.gz`, keeping meta, costs, grades and certificates as they are. `guild tidy --dry-run` shows what it would do.

## Tests

```sh
./test/run.sh      # 369 checks, about 3 minutes, no model calls
```

The suite runs against a throwaway `HOME`, a throwaway repo, its own tmux socket and a stub `claude`, so it never touches your real setup and never spends a token. It covers the quest lifecycle, identities, the war table and the docket, the trial gate in both forms, checks and grades, costs and the retro, budget caps, helpers, lessons, revive and close. Fakes stand in for everything outside: a fake Jira, a fake Jev, a fake ntfy, a fake GitHub PR cache, and a fake `ssh` that runs the "remote" guild in its own home. `test/cockpit.py` drives a real tmux client in a pty to test keys and clicks. It also runs in CI on every push.

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

**Effort and budget.** Each tier also carries an effort level (Claude's `--effort`, Codex's reasoning effort): plan and deep run high, build medium, light low. Override with `--effort`. There is no dollar cap by default. When you want one, pass `--budget 40` on the quest, or set a rule's `budget` or `budget_default` in `dispatch.json`. Past the cap, the adventurer's tools pause (the hook still lets it run `guild` commands), and the docket asks you: raise by $50 or $100, or stop. `guild budget <slug> [N | +N]` shows or changes a cap by hand. Claude Code's own `--max-budget-usd` works only in print mode, so guild enforces the cap itself, from the same cost numbers as `guild cost`.

**Helpers, for big work.** Inside a quest, `guild helper <name> [--tier light|build] < brief` starts a helper quest: same repo, a worktree on `<parent branch>--<name>`, the parent's ticket. The parent waits with `guild wait --for <slug>` (its own cursor, so the quartermaster still sees every event), then merges the helper's branch and reviews it. Helpers do not push or open PRs, and cannot start helpers of their own; `helpers_max` in `dispatch.json` caps them (2 by default). In the side menu a helper sits right after its parent (`└ name`); on the campaign board it joins the parent's thread and shows on the parent's card.

**Another machine.** Describe a machine once in `~/.guild/local/machines.json` (`{"mini": {"ssh": "you@mini", "guild": "~/Workspace/guild/bin/guild", "repos": {"crowdgen-project-api": "~/Workspace/crowdgen-project-api"}}}`, with guild installed there), check it with `guild machines check`, and send a quest with `--machine mini`. Guild on that machine builds the worktree and runs the agent; your cockpit tab is an SSH session into it, so peek, send and revive work as usual. `guild wait` mirrors the quest here about every 20 seconds (status, events, boards), your docket answers go back to the agent, and `guild close` closes it there first. Cost numbers stay on the machine. The side menu marks such quests `@mini`.

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

`guild campaign` (or `Ctrl-g k`) opens a kanban on the war table server, laid out in swimlanes: **one row per story, its tickets moving left to right** through five columns. A summary line on top counts everything ("12 done · 2 in progress · 3 need you (2 blocked) · 4 in review · 3 to do").

| Column | What sits there |
|---|---|
| To do | Tickets with no quest yet (when Jira is set up), stopped quests, idle sessions, your own to-dos |
| In progress | Quests and Claude sessions at work |
| Needs you | A decision only you can make: an open board, a blocked or failed quest, a session that asked you something |
| In review | Finished quests whose PR is still open, as GitHub says |
| Done | Merged or closed in the last week (three per row, then "+N more") |

**What makes a row.** Quests on the same ticket, or built on each other's branch, are one story. Its name comes from you (`guild story "Rate engine" SARA-832 SARA-838`, or "Name this story" on the row), else from the Jira parent (the epic or story above the tickets), else from its tickets. Giving two stories the same name merges them. Each row shows a progress bar, "2/5 done", and one line on its state ("Blocked: SARA-839 builder", "1 needs your decision", "All done"). Tickets with no story share a "Single tickets" row; sessions and to-dos have the last row, unless a session talks about a story's ticket, which puts it in that story.

**Cards** show the ticket, a plain title, the model as a wax seal, and what the agent is on. A red edge means blocked, failed or stopped, orange means it waits for you, green means it is working, and the reason is written in words on the card. Labels show the PR as GitHub sees it (draft, open, merged, review, checks) and the Jira status. Buttons appear on hover: go to its tab, reopen a session, pin, wrap-up, decide, PR. Sessions are read from Claude Code's own logs, so a session you named with `/rename` shows by that name. The page refreshes every 3 seconds; PR states refresh every two minutes (`guild prs` shows them in the terminal). Nothing is written to GitHub or Jira.

### A tree of tabs, and more than one quartermaster

The side menu's Tabs panel is a tree: each quartermaster, the quests it started under it, helpers under their quest, then the other tabs (terminals, editors). Activity lists only quests still alive, for the last day (`GUILD_ACTIVITY_HOURS` changes it); `events.log` keeps everything for the retro.

`guild qm new <name> [dir]` opens another quartermaster in its own tab (`qm-<name>`), with its own conversation. Each quest remembers who started it, and `guild wait` shows each quartermaster only the events of its own quests. `guild up` brings them all back; `guild qm close <name>` hands its quests to the first one. `guild qm reset [name]` gives a quartermaster a fresh conversation (quests, boards and history stay; the new id is kept for `guild up`); `/compact` in its pane is the lighter option.

### Pins

`Ctrl-g p` pins the tab you are on (or select a row in the side menu and press `s`), and it moves to the top of the sidebar with its state (working, your turn, how many subagents). A tab opened with `guild new` pins by its session id, so the pin survives `guild up`: `Ctrl-g P` lists the pins and reopens a closed one with its conversation. Pinned cards also come first on the campaign board.

### It does not touch your tmux

The cockpit runs on its own tmux server, socket `guild`, with `config/guild.tmux.conf`. Your normal `tmux` keeps its own server, config, keys and sessions. Attach by hand with `tmux -L guild attach -t guild`, and kill everything with `tmux -L guild kill-server`.

## Calm mode: the party on the road

While an adventurer works, the tool calls scrolling by are noise. With calm on, guild sessions draw a tiny party where the spinner was: an orange archer, a cyan mage and a red knight walking right through a night forest (stars and a moon, near and far pines drifting at different speeds, bushes and grass). Enemies come in from the right, one at a time, and each hero has their own: a bat flies in and the archer shoots it, a slime crawls in and the mage throws a spell, a skeleton marches in and the knight cuts it down. Five rows, plain ASCII, colors follow your dark or light theme. Tool rows (`ToolUse`, `ToolResult`, `ToolGroup`) draw at zero height. The model's context and the stored transcript are untouched: only the drawing changes. `/calm` toggles it inside a session, and `guild peek <slug> --calls` still shows every command from the session log.

It is a `mods/guild-calm` plugin on Claude Code's early-access function-hooks surface, so it is opt-in twice: `guild calm on` writes the preference, and guild exports `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` and `GUILD_CALM=1` only for the sessions it starts. Without both, the mod is a complete no-op, so your normal sessions never change. Verified on Claude Code 2.1.280; the API may change between releases.

## The trial

A `PreToolUse` hook blocks `gh pr create` in adventurer sessions unless `guild trial` recorded a result for the current HEAD. A new commit makes the trial stale. A skipped trial needs a reason, and the PR body must say `Trial: skipped - <reason>`.

**The contract comes first.** `guild quest` refuses a brief with no `Acceptance:` block, before any worktree exists: what "done" means is written from the ticket and the spec, not described after the code. The block is sealed with a hash, the trial judges against it, and a quest with nothing to accept (a merge, a review) starts with `--no-acceptance "<why>"`, recorded.

**An independent behaviour check.** The reviewer agent and the project checks both look at what the implementing agent wrote, so a test that passes against a mock, or a stub that hides a defect, gets past both. `guild behaviour` starts a separate Claude run that cannot read the code: it gets only the scenarios, its file tools are off and it starts in an empty folder, it starts the app from the quest's worktree and drives each scenario against the real local API, and anything that needs a mock is "blocked", never "pass". Afterwards guild reads that run's own session log; a run that looked at a diff or opened a source file is marked tainted and does not count. `guild trial pass` needs a clean run on the current commit with no fail (`--no-behaviour "<why>"` is the recorded way out).

**A PR body that cannot drift.** `gh pr create` needs the section `guild pr-body` prints: the sealed contract, each check's result on HEAD, the behaviour check and the checklist state, stamped with the contract hash and the commit. The adventurer writes the rest; the gate refuses a body without a current section.

**CI that did not run is red.** An open PR with no checks at all (a conflict, a skipped workflow) shows "no CI run" on the campaign board and the wrap-up, says NO CI RUN in `guild prs`, and sends one notification, instead of looking quiet.

## Folder trust

Claude Code asks you to trust every new git checkout. Worktrees go to `~/Workspace/.guild-worktrees/` (change with `GUILD_WORKTREES`), and `guild quest` marks a new worktree as trusted in `~/.claude.json` only when its main repo, or a parent folder, is already trusted.

## Contributing

Ideas, questions and bug reports are welcome as GitHub issues. For code, open an issue first: the design follows one person's workflow, and a change that fits it is easier to agree on before it is written. Every change runs `./test/run.sh` (no model calls, no real accounts). Keep the lines in [Design](#design): nothing merges without the human, nothing writes to Jira or GitHub on its own, and normal Claude Code sessions stay untouched.

## Roadmap

- Prove the newer pieces in daily use: OpenRouter and Codex quests, the second machine over real SSH, and the phone access.
- Click on a thing in a board page to comment on it.
- Faster `guild shot` (Chrome starts cold, about 20 seconds a shot).
- Rotate the event log; clean up old boards and branches after close.
- Voice input for the quartermaster, if macOS dictation is not enough.
