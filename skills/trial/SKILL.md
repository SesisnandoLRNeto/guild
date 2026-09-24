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
4. **Acceptance.** `guild check` must be green on the current commit, or `guild trial pass` refuses. If the brief has no `check:` lines, say so in the report: a code quest without runnable acceptance is a gap the guildmaster should see.
5. **Project checks.** Run the project's own checks, found from the repo (package.json scripts, Makefile, mvnw or gradlew, pytest, and so on): build, tests related to the change, lint and types. Paste the result lines, not the full logs.
6. **Live check** when it makes sense: run the thing (CLI, endpoint, UI through the browser tools) and prove that the acceptance criteria hold.
7. **Report.** Write `~/.guild/quests/$GUILD_QUEST/trial.md`:
   - **Risk**: low, medium or high, with the reason (blast radius, migrations, public API, auth, data).
   - **Findings**: fixed, escalated, dropped.
   - **Testing**: each scenario, pass or fail, and the evidence.
8. **Record.** Only when every check is green and no finding is left open: `guild trial pass "<one-line summary>"`. Otherwise keep working, or escalate.

Reuse the Risk and Testing sections of `trial.md` in the PR body.

## Skipping

Allowed only when the brief allows it or the change has no code (docs, specs, config comments): `guild trial skip "<reason>"`. The PR body must then include `Trial: skipped - <reason>`. The PR hook checks this.

A new commit after the trial makes it stale. The hook blocks the PR until you run the trial again.
