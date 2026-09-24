---
name: vision
description: Write down what a repo refuses to become. Mines the repo's merged, declined and reverted work for its real values, drafts principles that each cite that evidence, then stress-tests them with hard hypothetical changes that only the guildmaster can rule on, on the war table. The result lives in ~/.guild/visions/<repo>.md and every quest on that repo reads it. Use when the guildmaster says vision, what does this repo stand for, or before a large phase of work on a repo.
---

# Vision

A vision is not a mission statement. It is an **acceptance policy**: given a proposed change, it should tell an agent whether this repo would accept it or resist it, without asking. It exists so the guildmaster's judgment is written down once and reused by every quest, instead of being re-argued, or quietly guessed, every time.

## 1. Collect the evidence

```bash
guild vision <repo path>            # merged PRs, declined PRs, reverts -> ~/.guild/visions/<repo>.evidence.json
```

It refuses when the history is too thin (under 20 merged PRs by default). Do not work around that with invented values. Say so, and stop.

Read the evidence properly: titles, the first lines of bodies, what was declined and why, what was reverted. Also read the repo's `AGENTS.md` / `CLAUDE.md` and its README.

## 2. Draft principles, with evidence

Write 5 to 9 principles. Each one:

- is **specific to this repo**. "Write clean code" and "test well" are banned; they are true of every repo and decide nothing.
- cites **at least two** pieces of evidence: `#123`, `#140`, a revert sha. No evidence, no principle.
- says what it **resists**, not only what it wants. "Money values are never floats (#88, #102); a PR that stores a rate as double is declined" decides something.

## 3. Stress-test it with the guildmaster

Write 8 to 12 hypothetical changes that sit on a fault line: tempting but off-mission, two principles pulling against each other, a small step down a slope. Steelman both sides in one line each. If the answer is obvious from the draft, the question is too easy: replace it.

Put them on the war table as **one board**, one question each:

```bash
# page.html: the draft principles on the left, with their evidence
# decisions.json: one question per hypothetical, options accept / resist / depends, plus a text box
guild board open --quest vision-<repo> --html page.html --decisions decisions.json --assets --title "Vision: <repo>"
guild board wait <id> --quest vision-<repo> --timeout 7200
```

Recommend an answer for each, and say why. The guildmaster choosing against your recommendation is the most useful thing that can happen here: it means the draft got the repo wrong.

## 4. Fold the answers in

Rewrite the principles so the guildmaster's verdicts follow from them. Every answer should now be predictable from the text alone. Add a short "Rulings" section: each hypothetical, the verdict, the reason in the guildmaster's words.

Save to `~/.guild/visions/<repo>.md`, starting with:

```markdown
# <repo> vision
status: sealed
sealed: <date>, by the guildmaster, from <n> merged / <n> declined / <n> reverts
```

## 5. What changes afterwards

- Every new quest on that repo is told to read the vision, and to stop and ask on the war table when its change goes against it.
- The quartermaster reads it before writing a brief for that repo.
- It is yours until you decide to share it. To give it to the team, copy it into the repo as a normal PR.

Re-run this when the repo's direction changes, or when the retro shows quests escalating the same kind of question again and again.
