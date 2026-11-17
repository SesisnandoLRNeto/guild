---
name: campfire
description: Guild catch-up. Summarize what the quartermaster reported since the guildmaster's last message, the state of every quest, and every open decision. Use when the guildmaster says campfire, catch up, what did I miss, or where are we.
---

# Campfire

1. Run `guild sweep` (the same four sections as the docket and the wrap-up), `guild roster`, and `tail -n 40 ~/.guild/events.log`.
2. Look back at what you told the guildmaster since their last message.
3. Answer in this shape and nothing more. Always all four sections, in this order. An empty one gets its plain sentence. Say where everything stands now, not only what changed since the last campfire.

**Needs you**: only what needs the guildmaster's decision: every open question from `guild sweep`, most urgent first, each with its options and your recommendation; a wrap-up to grade; a blocked or failed quest. Number them so the guildmaster can answer "1: B, 2: yes". Record each answer with `guild ask answer <slug> <id> "<their words>" [--pick OPTION]`, or park it with `guild ask snooze <slug> <id> --until 7d`. Empty: "Nothing needs you right now."
**Underway**: active quests, one line each (slug, model, what it is doing now). Empty: "Nothing is being worked on."
**Next**: snoozed questions with the day each comes back, and anything queued. Empty: "Nothing is snoozed or queued."
**Landed**: quests done or closed in the last 7 days, each with its PR link or result. Say here when a PR skipped the trial, and why. Empty: "Nothing landed in the last 7 days."

Keep it short. It should be cheap to run often.
