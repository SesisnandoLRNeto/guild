---
name: war-table
description: Put a decision board or a wrap-up report on the guild war table, a local page where the guildmaster compares options with visuals, picks one, and sends notes or images back. Use inside a quest when a choice needs the guildmaster's eyes, and at the end of a feature to show what changed and why. Trigger words: war table, board, show me the options, wrap up.
---

# War table

A board is a normal HTML page you write, opened in a local browser with a side panel for choices, a message and images. Text in a terminal cannot show a UI change, three variants, or a before and after. A board can.

Use it for two things:

1. **Decision board**, when a choice is the guildmaster's to make: several designs, a trade-off, an ambiguous requirement, anything that changes intent or scope.
2. **Wrap-up report**, at the end of a feature, after the trial: what changed, what it looks like now, what it cost, what still hurts.

## The short way

A plain decision needs no HTML at all:

```bash
guild ask "Ship the chooser now or after the icons?" \
  --detail "The icons quest is still running; shipping first means two releases." \
  --option "now=Ship now: users get it this week, two releases" \
  --option "later=Wait for the icons: one release, about four days later" \
  --recommend later
guild board wait <id> --timeout 3600
```

Guild builds the page, opens it and waits. Use the long way below when the decision needs pictures: variants, before and after, a diagram, numbers.

## How to run one

```bash
# inside a quest, after writing page.html (and its images) in a folder
guild board open --html /tmp/board/page.html --assets --title "Snowy mountains: 3 variants" --subtitle "pick one, or ask for another pass"
guild board wait <id> --timeout 3600     # the id is printed in the url; blocks until the answer comes back
```

`--assets` copies everything next to the page (images, css). The quest goes to `needs-decision` on its own, so the quartermaster knows you are waiting. When the answer arrives it goes back to `working`.

The answer is JSON: `answers` (your question id to the chosen option id), `message` (free text), `attachments` (image paths, relative to the board folder), `ended` (the guildmaster considers this closed). Read it, say in one line what you understood, and continue.

## Decision file

Write `decisions.json` beside the page and pass `--decisions`:

```json
{ "questions": [
  { "id": "peak", "title": "Which peak shape?", "detail": "Affects the silhouette at every distance.",
    "type": "single", "recommended": "d",
    "options": [
      { "id": "a", "label": "Rounded hills", "why": "Softest, but reads flat at dawn", "image": "shots/a.png" },
      { "id": "d", "label": "Carved peaks", "why": "Closest to Everest photos, costs one extra draw call", "image": "shots/d.png" }
    ] },
  { "id": "scope", "title": "Ship the chooser now or later?", "type": "single",
    "options": [{ "id": "now", "label": "Now" }, { "id": "later", "label": "Later" }] }
] }
```

`type` is `single`, `multi` or `text`. Keep it to the few questions that really need the guildmaster. Always give a `recommended` option and say why in `why`. Do not ask what you can decide yourself.

## What a good page holds

**Decision board**
- The question in one line at the top, and what happens after each choice.
- The options side by side, same vantage point, same size. Use `<img>` for screenshots, real ones, never drawings of what it might look like.
- The current state as one of the columns, labelled "today", so the guildmaster sees the change, not just the options.
- A short "what I already ruled out and why".
- Numbers when they exist: bundle size, query count, render time, token cost.

**Wrap-up report** (after the trial, before or with the PR). Open it with `--wrapup`, which marks it as the quest's report and leaves the quest working instead of waiting on a decision. A code quest cannot report `done` without one.
- **What changed**: one paragraph, then the file list with one line each.
- **Before and after**: screenshots in pairs, same viewport and same data. Use the Chrome tools to take them.
- **Evidence**: the trial's testing table, with results.
- **Performance**: numbers before and after, and how you measured them.
- **Pain points**: what fought back, what is still ugly, what you would redo.
- **Why**: the design choices you made on your own, each with its reason, so the guildmaster can disagree cheaply.
- **Next to other work**: run `guild roster` and name the quests this touches or blocks.
- **Backend: data model, impact and business rules.** When the change touches migrations, entities, services or validation, the report gets a drawn section. Guild builds it; you explain it:
  1. `guild impact --out /tmp/impact.html` gives a first look. Read what it found: the schema diff (every migration replayed on the base and on your branch), changed entities and fields, every module that uses what changed (the files you did *not* touch are the ones to double check), changed endpoints, and the code lines that look like rules.
  2. Write `rules.json` beside your page. For every real business rule change, one entry in plain words a product person can read:
     ```json
     {"rules": [{"rule": "A workstream paid by units needs its units per hour",
                 "before": "not stored", "after": "required when paid by UNITS, above 0",
                 "where": "WorkstreamClosureService.java:148", "why": "hourly equivalent for the minimum wage check"}],
      "note": "The other candidates only carry the new field; same behaviour."}
     ```
     Use `note` to say why the remaining candidates are not rule changes. Never leave a candidate unexplained.
  3. `guild impact --into <page.html> --rules rules.json` puts the section where the page has `<!--GUILD-IMPACT-->` (or at the end): an ER diagram of the changed tables with NEW, CHANGED and REMOVED columns, before and after column lists, the constraints the database now enforces, a module impact map, the endpoints, and your rules table. Rerunning it replaces the section.
  4. If an entity field has no column in the migrations, the section shows it in red. Fix it before the wrap-up.
  `guild status done` refuses a backend quest whose wrap-up lacks this section or leaves rules unexplained. `--no-impact "<why>"` is the recorded escape.
- End with the decisions the guildmaster still owns: merge as is, change something, or split a follow-up quest.

## Diagrams and screenshots

- **Diagrams**: write Mermaid in `<pre class="mermaid">` blocks. The war table serves Mermaid itself, so it renders offline. Reach for it whenever the point has arrows: a state machine you want the guildmaster to approve before building it, a request flow, a sequence between services, or "what is actually happening" behind a hard topic.
- **Prototypes first**: when a decision is about behaviour, draw the state machine or flow as the options themselves (one diagram per option) and let the guildmaster pick before any code exists.
- **Screenshots**: `guild shot <url> --name before|after` takes them one way every time (headless, fixed viewport). Take the pair with identical flags, then put them side by side.

## Page rules

- Start from `~/Workspace/guild/web/board-template.html`. It already has the colors, the option grid, the numbers table and dark and light support. Copy it, then replace the content.
- One self-contained HTML file, plus images in a subfolder. Relative paths only.
- No CDNs and no network calls. The board must work offline.
- The war table dresses every page in the guild theme (a parchment sheet on a wooden table, serif small-caps headings) when it serves it. Use the template's tokens (`--card`, `--line`, `--text`, `--dim`, `--accent`, `--ok`, `--bad`) instead of hard-coded colors, so your page takes the theme. Mermaid is drawn in its light variant to read on parchment.
- It has to read well in a 900px wide frame. The side panel takes the rest.
- Plain B1 English, no emojis, no em dashes.
