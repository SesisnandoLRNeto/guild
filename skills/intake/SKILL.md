---
name: intake
description: Turn assigned tickets into quests. Pulls the guildmaster's open tickets from the tracker (Jira through its MCP tools), proposes which ones to run and how, and creates the quests with the ticket key attached. Use when the guildmaster says intake, what is on my plate, start my tickets, or names a ticket key.
---

# Intake

Work starts in the tracker, not in the terminal. This is how a ticket becomes a quest.

## 1. Read the real queue

Query it live, every time. Never work from a remembered list.

With the Jira MCP tools (`mcp__atlassian__jira_search`, `jira_get_issue`):

```
assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC
```

Pull at least 30 comments on a ticket before you act on it, and read the **tail**: the tracker returns the oldest first, and the newest comment is usually the one that matters. If the tracker is not reachable, say so and ask the guildmaster to paste the ticket.

## 2. Sort before you dispatch

For each ticket decide, and say in one line:

- **Ready**: the intent and acceptance are clear enough to write a brief. Propose a quest.
- **Needs the guildmaster**: real ambiguity, a product call, or a risk. Put it on the war table with `guild ask` rather than guessing.
- **Not code**: a question, a duplicate, or a product answer. Say what the reply should be; do not open a quest.

Never open a quest for every ticket. A quest per ticket is how a fleet gets loud.

## 3. Propose, then create

Bring the shortlist to the guildmaster: ticket, one-line intent, the repo you would use, the harness and model from `~/.guild/local/dispatch.json`, and why. Wait for a yes.

Then, per approved ticket:

```bash
guild quest <slug> --repo <path> --ticket <KEY> --model <m> <<'EOF'
Intent: <why this ticket exists, in the guildmaster's words>
Context: <ticket key and link, the comment tail that matters, related code, prior decisions>
Acceptance: <what done looks like, from the ticket>
Constraints: <what not to touch; whether the trial may be skipped>
Quest type: code | investigation
EOF
```

Use a slug a human can read: `work-api-null-fix`, not `PMC2-1023`. The key lives in `--ticket`, so `guild log` and `guild retro` can show it.

## 4. Close the loop back to the tracker

When a quest is done, draft the ticket comment for the guildmaster and let them post it. Write it as an engineer talking to a colleague: what was wrong, what changed, how to retest, and the PR link. Keep code details out of a product ticket. Never post to the tracker without the guildmaster's word.

## Before you write any brief

Read `~/.guild/lessons.md`. Past retros are there to stop the same mistake twice.
