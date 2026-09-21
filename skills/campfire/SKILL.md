---
name: campfire
description: Guild catch-up. Summarize what the quartermaster reported since the guildmaster's last message, the state of every quest, and every open decision. Use when the guildmaster says campfire, catch up, what did I miss, or where are we.
---

# Campfire

1. Run `guild roster`, and `tail -n 40 ~/.guild/events.log`.
2. Look back at what you told the guildmaster since their last message.
3. Answer in this shape and nothing more:

**Landed**: quests done since the last campfire, each with its PR link or result.
**Under way**: active quests, one line each (slug, model, what it is doing now).
**Waiting on you**: every open decision, each with the options and your recommendation. Number them so the guildmaster can answer "1: B, 2: yes".
**Trial skipped**: any PR that skipped the trial, with the reason.

Leave out empty sections. Keep it short. It should be cheap to run often.
