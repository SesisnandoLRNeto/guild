#!/usr/bin/env python3
"""The Why card: before a quest is built, the guildmaster writes why it exists.

  why.py open <slug>     put the card on the war table (guild quest does this for you)
  why.py show <slug>     print the answered card
  why.py prune           drop the unanswered cards of housekeeping quests from the docket
  why.py wanted <slug> [brief.md]   exit 0 when this quest deserves a card (a feature or an
                         implementation), 1 for housekeeping: a PR review fix, a merge, a CI
                         or conflict chore, a rebase. Prints the reason.

Five short answers in the guildmaster's own words: the pain, the rule, the decision, the
impact, the future. The AI does not fill it in: thinking first is the point. When it is answered,
the card is kept in quests/<slug>/why.json, it shows at the top of the plan and the wrap-up, and
the adventurer is asked to check it against the ticket, the spec and the code and to challenge
what does not fit, on the war table.
"""
import html
import json
import os
import re
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
<meta name="guild-glance" content="off">
<style>
  /* the realm look for the card: a hero like the other pages, the questions as tiles, the brief on a sheet */
  html:root h1.rm-title { display: block; font-size: 30px; border: 0; padding: 0; }
  html:root .why-hero { margin: 6px 0 26px; padding: 20px 26px 18px; max-width: none; }
  html:root .why-hero .rm-sub { display: block; max-width: 70ch; }
  html:root .why-hero .rm-party { margin-left: auto; }
  .why-q { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin: 0 0 8px; }
  html:root .why-q > div { margin: 0; padding: 12px 14px; display: grid; gap: 4px; border-radius: 4px; }
  .why-q b { font-variant: small-caps; letter-spacing: .06em; color: #f3cf6c; font-size: 15px; }
  .why-q span { color: #a8987a; font-size: 13px; line-height: 1.4; }
  html:root .why-brief { max-width: 82ch; padding: 16px 20px; border-radius: 4px; }
  html:root .why-brief p:first-child { margin-top: 0; }
</style></head><body>
<section class="rm-hero rm-frame why-hero">
  <div>
    <p class="rm-kicker">The war table · why card</p>
    <h1 class="rm-title">Why card: __SLUG__</h1>
    <div class="rm-rule"></div>
    <p class="rm-sub">Before this quest is built, write why it exists, in your own words. Short is fine; a guess is
fine too, as long as it is yours. The adventurer will check your card against the ticket, the spec and
the code, and challenge what does not fit. That is where you learn the rule for real.</p>
  </div>
  <div class="rm-party" aria-label="Who is at the table">__PARTY__</div>
</section>
<h2>The five questions</h2>
<div class="why-q">__FIELDS__</div>
<h2>What the quartermaster asked for</h2>
<div class="note why-brief">__BRIEF__</div>
</body></html>"""


# Housekeeping has no pain, rule or decision of its own: a review fix carries the PR's, a merge
# carries the branch's. A card there is five empty boxes. These words in the slug or the brief say
# the quest is housekeeping; everything else (a feature, a behaviour change, a bug with a rule
# behind it) gets the card.
CHORE_SLUG = re.compile(r"^pr\d+[-_]|[-_](merge|review|ci|rebase|conflict|conflicts|hotfix|deps|bump|release)([-_]|$)|^(merge|review|ci|rebase|release)[-_]")
CHORE_WORDS = re.compile(r"\b(review (fix|fixes|items|comments)|requested changes|address(ing)? (the )?review|"
                         r"up to date with main|conflicts? with main|resolve (the )?(merge )?conflicts?|merge only|"
                         r"ci (is|run|job|fails|failing|flak)|flaky test|bump (the )?version|release notes only)\b", re.I)


def wanted(slug, brief=""):
    """(True, "") when the quest deserves a Why card; (False, why not) for housekeeping."""
    m = CHORE_SLUG.search(slug or "")
    if m:
        return False, f"the slug says housekeeping ({m.group(0).strip('-_')})"
    # only the intent at the top of a brief counts: a feature brief's constraints often say
    # "merge, never rebase" or "address the review", and that must not take its card away
    head = "\n".join((brief or "").splitlines()[:2])
    m = CHORE_WORDS.search(head)
    if m:
        return False, f"the brief says housekeeping ({m.group(0)})"
    return True, ""


def path(slug):
    return os.path.join(QUESTS, slug, "why.json")


def load(slug):
    try:
        return json.load(open(path(slug)))
    except (OSError, ValueError):
        return None


def render(slug, brief):
    """The card's page: the hero, the five questions as tiles, the brief on a sheet."""
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import wartable
    fields = "".join(f'<div class="rm-frame"><b>{html.escape(label)}</b><span>{html.escape(hint)}</span></div>' for _, label, hint in FIELDS)
    party = (wartable.figure_html("human", "Guildmaster", "writes the card",
                                  "You. Five short answers in your own words; a guess is fine, a blank is not.")
             + wartable.figure_html("highelf", "High elf", "checks it",
                                    "The adventurer reads your card against the ticket, the spec and the code, and says where it does not fit. Politely. Mostly."))
    return (PAGE.replace("__SLUG__", html.escape(slug)).replace("__FIELDS__", fields).replace("__PARTY__", party)
            .replace("__BRIEF__", wartable.md_to_html(brief[:6000]) if brief else "<p>No brief.</p>"))


def refresh():
    """Redraw every why card page with the current look (the brief does not change)."""
    n = 0
    for slug in sorted(os.listdir(QUESTS)) if os.path.isdir(QUESTS) else []:
        qdir = os.path.join(QUESTS, slug)
        bdir = os.path.join(qdir, "boards")
        if not os.path.isdir(bdir):
            continue
        brief = open(os.path.join(qdir, "brief.md")).read() if os.path.exists(os.path.join(qdir, "brief.md")) else ""
        for b in os.listdir(bdir):
            if b.startswith("why-") and os.path.exists(os.path.join(bdir, b, "content.html")):
                with open(os.path.join(bdir, b, "content.html"), "w") as f:
                    f.write(render(slug, brief))
                n += 1
    return n


def prune():
    """Take the unanswered Why cards of housekeeping quests off the docket. Returns the boards removed."""
    import shutil
    gone = []
    for slug in sorted(os.listdir(QUESTS)) if os.path.isdir(QUESTS) else []:
        qdir = os.path.join(QUESTS, slug)
        bdir = os.path.join(qdir, "boards")
        if not os.path.isdir(bdir):
            continue
        brief = open(os.path.join(qdir, "brief.md")).read() if os.path.exists(os.path.join(qdir, "brief.md")) else ""
        if wanted(slug, brief)[0]:
            continue
        for b in os.listdir(bdir):
            if b.startswith("why-") and not os.path.exists(os.path.join(bdir, b, "decision.json")):
                shutil.rmtree(os.path.join(bdir, b))
                gone.append(f"{slug}/{b}")
    return gone


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
    with open(os.path.join(d, "content.html"), "w") as f:
        f.write(render(slug, brief))
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
    if a and a[0] == "wanted":
        brief = open(a[2]).read() if len(a) > 2 and os.path.exists(a[2]) else ""
        ok, why_not = wanted(a[1] if len(a) > 1 else "", brief)
        print("why card: a feature or implementation, the card is on" if ok else f"why card: skipped, {why_not}")
        raise SystemExit(0 if ok else 1)
    if a == ["prune"]:
        gone = prune()
        print("\n".join(gone) or "nothing to prune")
        raise SystemExit(0)
    if a == ["refresh"]:
        print(f"redrew {refresh()} why cards")
        raise SystemExit(0)
    if len(a) != 2 or a[0] not in ("open", "show"):
        raise SystemExit(__doc__)
    if a[0] == "open":
        print(open_card(a[1]))
    else:
        card = load(a[1])
        print(as_text(card) if card else f"{a[1]} has no answered Why card yet")
