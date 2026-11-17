---
name: trial
description: Guild trial, the gate an adventurer must pass before opening a PR. Reviews the diff with the reviewer agent, fixes safe findings, runs the project checks, writes a risk and testing report, and records the result with `guild trial`. Use at the end of a code quest, before `gh pr create`.
---

# Trial

Run this inside a quest worktree (`GUILD_QUEST` is set). The goal is simple: no PR reaches the guildmaster unless someone tried to break it first.

## Steps

1. **Scope.** `git diff --stat <base>...HEAD` and read the full diff. Re-read the brief's acceptance criteria.
2. **Review.** Start the `reviewer` agent if it exists, or else a general agent told to act as an adversarial reviewer. Give it the diff, the brief, and this instruction: find correctness, security and scope problems, each with `file:line` and a concrete failure scenario. Read-only.
3. **Act on findings.**
   - Safe and mechanical (a clear bug, a missing null check, a failing test): fix it, commit, and review the new diff again.
   - First sort every finding with `guild scope sort` (see **Scope check** below). Fix only the ones it marks in scope; each expansion goes to the guildmaster as a card and is not fixed.
   - It changes the intent of the work, or you are not sure: do not fix it. Report `guild status $GUILD_QUEST needs-decision "..."` and stop.
   - Not real after checking: drop it, and note why in the report.
4. **Acceptance.** `guild check` must be green on the current commit, or `guild trial pass` refuses. The contract was sealed when the quest started; judge the work against it, not against what you ended up building. If it has no `check:` lines, say so in the report: a code quest without runnable acceptance is a gap the guildmaster should see.
5. **Project checks.** Run the project's own checks, found from the repo (package.json scripts, Makefile, mvnw or gradlew, pytest, and so on): build, tests related to the change, lint and types. Paste the result lines, not the full logs.
5b. **Second opinion on risk** when `guild jev status` shows the quests scope on: `guild jev risk` scores the diff 1 to 5. Put its score next to yours in the report; if they differ by 2 or more, say why.
6. **Behaviour check (independent).** Write `scenarios.json` first (war-table skill, "Validation scenarios"), then run `guild behaviour`. It starts a separate Claude run that cannot read the code or the diff: it starts the app from your worktree and drives the scenarios against the real local API, never a mock. It takes minutes. `guild trial pass` refuses until it has run on the current commit with no fail and no sign that it looked at the code. When it fails, fix the code; if a scenario itself is wrong, say so on the war table instead of weakening it. "blocked" scenarios (a person must look at a screen) are listed for the guildmaster, not failures. Nothing a validator can run (docs, config)? `guild trial pass --no-behaviour "<why>"`, recorded.
7. **Report.** Write `~/.guild/quests/$GUILD_QUEST/trial.md`:
   - **Risk**: low, medium or high, with the reason (blast radius, migrations, public API, auth, data).
   - **Findings**: fixed, escalated, dropped, and the line `guild scope report` prints (fixed in scope, expansions sent, follow-ups recorded).
   - **Testing**: each scenario, pass or fail, and the evidence.
8. **Record.** Only when every check is green and no finding is left open: `guild trial pass "<one-line summary>"`. Otherwise keep working, or escalate.

## Scope check

A review always finds more. Fixing all of it lets each round add a little: a new option, a guarantee, an abstraction, a subsystem, a refactor, or the same theme back with more machinery. The PR ends up bigger than what the guildmaster approved. So every finding is sorted against what was agreed (`plan.md`, the brief, the sealed acceptance list) before anything is fixed.

- **In scope**: it completes or corrects what was agreed. A bug in the new code, a missing test for agreed behaviour, a security hole in the new code. Fix it as usual.
- **Expansion**: it adds something not agreed, or it is destructive (removes or rewrites what exists). Do not fix it. It becomes one decision card for the guildmaster.

Labels like "security", "required" or "blocker" are evidence for the card, not permission to widen the PR. A security hole in the new code is in scope because it is a bug in what was agreed, not because of its label.

Ask the reviewer to give, for each finding, what the fix would change and which agreed line it serves. Then write `findings.json` in the quest folder and run `guild scope sort findings.json`:

```json
{"findings": [{"id": "f1", "file": "src/rates.ts", "line": 42, "summary": "export drops the last row",
  "change": "fix", "agreed": "the export holds every row of the period", "theme": "export rows", "labels": []},
 {"id": "f2", "summary": "retries have no backoff", "change": "add", "agreed": "", "theme": "retries",
  "labels": ["required"], "wants": "exponential backoff with a config option",
  "smallest": "keep the single retry the plan names", "if_yes": "one more option and its tests in this PR",
  "if_no": "one retry as agreed; backoff kept as a follow-up", "recommend": "no", "why": "no failure seen yet"}]}
```

- `change` is what the fix does: `fix` (corrects new code), `test` (tests agreed behaviour), `add` (new option, guarantee, abstraction, subsystem), `refactor`, `remove`.
- `agreed` quotes the plan step, brief line or acceptance item it completes, word for word. Guild looks for that quote; an empty or made-up quote makes it an expansion.
- `theme` is a short tag. A theme that was already fixed in scope in an earlier round and comes back is an expansion: the same thing with more machinery.
- `add`, `refactor`, `remove` and anything `destructive` are always expansions.

For each expansion guild opens a card through `guild ask` (board id `scope-<round>-<id>`) with five parts: what was agreed, what the review wants to add, the smallest option that satisfies the agreement, what happens if yes and if no, and your recommendation. Fill `wants`, `smallest`, `if_yes`, `if_no`, `recommend` and `why` so the card reads well; keep each to one line. Then fix the in-scope findings and wait for the cards (`guild board wait <id>`).

- **Yes**: guild adds it to `plan.md` under "Added during the trial". Build it, then review again.
- **No**: guild records it as a follow-up on the campaign board (`guild todo`). Nothing changes in the PR.
- On an epic-dagger quest, where you may not ask, every expansion becomes a follow-up at once.

`guild trial pass` is refused while a card waits. `guild scope report` prints the counts for `trial.md`. Each review round is a new `guild scope sort`; the answers carry over.

**The PR body.** `gh pr create` needs the section `guild pr-body` prints: the acceptance contract sealed when the quest started, each check's result on HEAD, the behaviour check and the checklist state. Paste it as is (do not edit it; it carries the contract hash and HEAD and the gate checks both), then write the rest of the body yourself: what changed and why, reusing the Risk and Testing sections of `trial.md`. Describe only what is in the branch now; never copy a body from an earlier PR.

## Skipping

Allowed only when the brief allows it or the change has no code (docs, specs, config comments): `guild trial skip "<reason>"`. The PR body must then include `Trial: skipped - <reason>`. The PR hook checks this.

A new commit after the trial makes it stale. The hook blocks the PR until you run the trial again.
