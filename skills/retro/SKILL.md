---
name: retro
description: Turn the guild's own history into lessons. Reads what quests cost, which recommendations the guildmaster overruled, which trials were skipped and where work stalled, then writes a few durable lessons to ~/.guild/lessons.md. Use when the guildmaster says retro, what did we learn, how are we doing, or at the end of a week.
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

## 3. Write the lessons

Append to `~/.guild/lessons.md`, newest first, each one:

```markdown
## 2026-09-23
- **Name the file names.** ask-e2e escalated to ask which file name to use; the brief said "a greeting file".
  Evidence: ask-e2e, 1 escalation, recommendation overruled.
  Apply: in a brief, name every artifact the quest will create.
```

Rules for a lesson:
- It must change what someone does next time. "Be more careful" is not a lesson.
- It must name its evidence: the quests it came from.
- Three to five per retro, maximum. A long file is an unread file.
- If a lesson repeats one already in the file, sharpen the old one instead of adding a second.
- Remove a lesson when the evidence stops appearing. Write down that you removed it and why.

## 4. Close the loop

Tell the guildmaster the lessons in a few lines and what you will do differently. The quartermaster reads `~/.guild/lessons.md` before writing a brief, so a lesson written here changes the next quest.

## Your grades

Every wrap-up asks the guildmaster for a grade (1 to 5) and a verdict (merge, changes, split). `guild retro` shows the average by model, tier and harness, and how often changes were asked. Use them:
- A model or tier that keeps getting 3 or less for a kind of work is a routing lesson: propose the change to `~/.guild/local/dispatch.json` on the war table, with the grades as evidence. Never change the file without the guildmaster's pick.
- "Changes" verdicts with notes are the most honest signal of what went wrong; quote them.
- Finished quests without a grade are listed: remind the guildmaster, do not guess a grade.

