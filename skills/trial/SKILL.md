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
   - It changes intent or scope, or you are not sure: do not fix it. Report `guild status $GUILD_QUEST needs-decision "..."` and stop.
   - Not real after checking: drop it, and note why in the report.
4. **Acceptance.** `guild check` must be green on the current commit, or `guild trial pass` refuses. The contract was sealed when the quest started; judge the work against it, not against what you ended up building. If it has no `check:` lines, say so in the report: a code quest without runnable acceptance is a gap the guildmaster should see.
5. **Project checks.** Run the project's own checks, found from the repo (package.json scripts, Makefile, mvnw or gradlew, pytest, and so on): build, tests related to the change, lint and types. Paste the result lines, not the full logs.
5b. **Second opinion on risk** when `guild jev status` shows the quests scope on: `guild jev risk` scores the diff 1 to 5. Put its score next to yours in the report; if they differ by 2 or more, say why.
6. **Behaviour check (independent).** Write `scenarios.json` first (war-table skill, "Validation scenarios"), then run `guild behaviour`. It starts a separate Claude run that cannot read the code or the diff: it starts the app from your worktree and drives the scenarios against the real local API, never a mock. It takes minutes. `guild trial pass` refuses until it has run on the current commit with no fail and no sign that it looked at the code. When it fails, fix the code; if a scenario itself is wrong, say so on the war table instead of weakening it. "blocked" scenarios (a person must look at a screen) are listed for the guildmaster, not failures. Nothing a validator can run (docs, config)? `guild trial pass --no-behaviour "<why>"`, recorded.
7. **Report.** Write `~/.guild/quests/$GUILD_QUEST/trial.md`:
   - **Risk**: low, medium or high, with the reason (blast radius, migrations, public API, auth, data).
   - **Findings**: fixed, escalated, dropped.
   - **Testing**: each scenario, pass or fail, and the evidence.
8. **Record.** Only when every check is green and no finding is left open: `guild trial pass "<one-line summary>"`. Otherwise keep working, or escalate.

**The PR body.** `gh pr create` needs the section `guild pr-body` prints: the acceptance contract sealed when the quest started, each check's result on HEAD, the behaviour check and the checklist state. Paste it as is (do not edit it; it carries the contract hash and HEAD and the gate checks both), then write the rest of the body yourself: what changed and why, reusing the Risk and Testing sections of `trial.md`. Describe only what is in the branch now; never copy a body from an earlier PR.

## Skipping

Allowed only when the brief allows it or the change has no code (docs, specs, config comments): `guild trial skip "<reason>"`. The PR body must then include `Trial: skipped - <reason>`. The PR hook checks this.

A new commit after the trial makes it stale. The hook blocks the PR until you run the trial again.
