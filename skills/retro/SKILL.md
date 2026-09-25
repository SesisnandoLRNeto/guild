---
name: retro
description: Turn the guild's own history into lessons. Reads what quests cost, which recommendations the guildmaster overruled, which trials were skipped and where work stalled, then proposes a few durable lessons, each backed by quotes from two quests, for the guildmaster to accept. Use when the guildmaster says retro, what did we learn, how are we doing, or at the end of a week.
---

# Retro

The fleet already records what happened. This turns it into something that changes the next quest.

## 1. Gather

```bash
guild retro --since 14d          # readable
guild retro --since 14d --json   # every field, for your own counting
guild log --since 14d
cat ~/.guild/lessons.md 2>/dev/null
```

Read a few real briefs and decisions behind the numbers (`guild log <slug>`). Counts alone lie.

## 2. Look for these

- **Overruled recommendations.** The guildmaster chose something other than the suggested option. This is the strongest signal in the whole file: it says the agent's judgment and the guildmaster's differ in a specific, nameable way.
- **Escalations that were not decisions.** A quest asking for something the brief should have said. That is a brief problem, not a model problem.
- **Silent stops and revivals.** Where adventurers lose their way.
- **Skipped trials.** Which repos or task types keep skipping, and whether a bug followed.
- **Cost against outcome.** An expensive quest that produced a small diff, or a cheap model that had to be redone.
- **Acceptance.** First-pass rate by model (did the quest meet its own checks on the first real run?), weak checks (already green before any work), and code quests that had no checks at all. A model with a low first-pass rate on a task type is a routing lesson for `dispatch.json`; weak checks are a lesson about how acceptance gets written.
- **Very short briefs.** Check whether they correlate with escalations.

## 3. Propose the lessons

You do not write `~/.guild/lessons.md` (a hook refuses it). You propose, with evidence, and the guildmaster accepts on the docket:

```bash
guild lesson propose "In a brief, name every file the quest will create." \
  --evidence "ask-e2e: which file name should the greeting use" \
  --evidence "hello-test: the brief does not say where the file goes" \
  --why "two quests escalated for a name the brief could have given"
```

Rules for a lesson:
- **Evidence from two different quests at least**, each a verbatim quote (12+ characters) from what that quest left behind: its brief, report, trial, boards, your grade notes, its events or its session log. Guild checks every quote and refuses the lesson when one is not really there. One quest is an anecdote, not a pattern.
- It must change what someone does next time. "Be more careful" is not a lesson.
- Three to five per retro, maximum. A long file is an unread file.
- Each proposal is a row on the docket (accept or reject). Accepted ones land in `lessons.md` with their evidence; rejected ones stay in `guild lessons` so you do not propose them again.

## 4. Close the loop

Tell the guildmaster the lessons in a few lines and what you will do differently. The quartermaster reads `~/.guild/lessons.md` before writing a brief, so a lesson written here changes the next quest.

## Your grades

Every wrap-up asks the guildmaster for a grade (1 to 5) and a verdict (merge, changes, split). `guild retro` shows the average by model, tier and harness, and how often changes were asked. Use them:
- A model or tier that keeps getting 3 or less for a kind of work is a routing lesson: propose the change to `~/.guild/local/dispatch.json` on the war table, with the grades as evidence. Never change the file without the guildmaster's pick.
- "Changes" verdicts with notes are the most honest signal of what went wrong; quote them.
- Finished quests without a grade are listed: remind the guildmaster, do not guess a grade.

