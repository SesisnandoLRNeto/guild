#!/usr/bin/env python3
"""The Why card: before a quest is built, the guildmaster writes why it exists.

  why.py open <slug>     put the card on the war table (guild quest does this for you)
  why.py show <slug>     print the answered card

Five short answers in the guildmaster's own words: the pain, the rule, the decision, the
impact, the future. The AI does not fill it in: thinking first is the point. When it is answered,
the card is kept in quests/<slug>/why.json, it shows at the top of the plan and the wrap-up, and
the adventurer is asked to check it against the ticket, the spec and the code and to challenge
what does not fit, on the war table.
"""
import html
import json
import os
import sys
import time

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")

FIELDS = [
    ("pain", "Pain", "Who suffers today, and one real example of it."),
    ("rule", "Rule", "The business rule, in one sentence."),
    ("decision", "Decision", "Who decided it, and what was rejected."),
    ("impact", "Impact", "What changes, and for which users, data or money."),
    ("future", "Future", "What this unlocks next, and what it blocks."),
]

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Why card</title>
<meta name="guild-glance" content="off"></head><body>
<h1>Why card: __SLUG__</h1>
<p class="lead">Before this quest is built, write why it exists, in your own words. Short is fine; a guess is
fine too, as long as it is yours. The adventurer will check your card against the ticket, the spec and
the code, and challenge what does not fit. That is where you learn the rule for real.</p>
<h2>The five questions</h2>
<ul>__FIELDS__</ul>
<h2>What the quartermaster asked for</h2>
<div class="note">__BRIEF__</div>
</body></html>"""


def path(slug):
    return os.path.join(QUESTS, slug, "why.json")


def load(slug):
    try:
        return json.load(open(path(slug)))
    except (OSError, ValueError):
        return None


def open_card(slug):
    qdir = os.path.join(QUESTS, slug)
    if not os.path.isdir(qdir):
        raise SystemExit(f"why: no quest {slug}")
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import wartable
    brief = open(os.path.join(qdir, "brief.md")).read() if os.path.exists(os.path.join(qdir, "brief.md")) else ""
    board = "why-" + time.strftime("%H%M%S")
    d = wartable.board_dir(slug, board)
    os.makedirs(d, exist_ok=True)
    fields = "".join(f"<li><b>{html.escape(label)}</b>: {html.escape(hint)}</li>" for _, label, hint in FIELDS)
    with open(os.path.join(d, "content.html"), "w") as f:
        f.write(PAGE.replace("__SLUG__", html.escape(slug)).replace("__FIELDS__", fields)
                .replace("__BRIEF__", wartable.md_to_html(brief[:6000]) if brief else "<p>No brief.</p>"))
    json.dump({"questions": [{"id": k, "title": label, "detail": hint, "type": "text"} for k, label, hint in FIELDS]},
              open(os.path.join(d, "decisions.json"), "w"), indent=2)
    json.dump({"id": board, "quest": slug, "title": f"Why card: {slug}", "subtitle": "your words first; the adventurer checks them",
               "kind": "why", "wrapup": False, "created": wartable.now()},
              open(os.path.join(d, "board.json"), "w"), indent=2)
    url = f"http://127.0.0.1:{wartable.ensure_server()}/b/{slug}/{board}/"
    with open(os.path.join(GUILD_HOME, "events.log"), "a") as f:
        f.write(f"{wartable.now()}\t{slug}\twhy-asked\tWhy card on the docket -> {url}\n")
    return url


def save(slug, decision):
    """The answered card, from the board's decision."""
    ans = decision.get("answers", {})
    card = {k: str(ans.get(k, "")).strip() for k, _, _ in FIELDS}
    card["at"] = decision.get("at", "")
    if decision.get("message"):
        card["note"] = decision["message"]
    json.dump(card, open(path(slug), "w"), indent=2)
    return card


def as_text(card):
    return "\n".join(f"{label}: {card.get(k) or '(left empty)'}" for k, label, _ in FIELDS)


def glance_html(slug):
    """The card as a small block for the top of the plan and wrap-up pages."""
    card = load(slug)
    if not card:
        return ""
    rows = "".join(f'<div class="gw-row"><b>{html.escape(label)}</b><span>{html.escape(card.get(k) or "(left empty)")}</span></div>'
                   for k, label, _ in FIELDS)
    return ('<div class="gw"><div class="gw-head">Why card <i>written by the guildmaster</i></div>' + rows + "</div>")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) != 2 or a[0] not in ("open", "show"):
        raise SystemExit(__doc__)
    if a[0] == "open":
        print(open_card(a[1]))
    else:
        card = load(a[1])
        print(as_text(card) if card else f"{a[1]} has no answered Why card yet")
