#!/usr/bin/env python3
"""Fixes that land after a wrap-up: review fixes, conflicts, CI. They get no wrap-up of their own;
their done note joins the wrap-up of the quest that opened the PR, under "Fixed after this report".

  followups.py add <slug> <note>   attach a housekeeping quest's done note to the quest it serves;
                                   prints that quest's slug, or nothing when none is found
  followups.py show <slug>         the HTML block for that quest's wrap-up
"""
import html
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import impactmap  # noqa: E402  (same row styles as the impact map)

QUESTS = os.path.join(os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild")), "quests")
PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
RULE = re.compile(r"^\s*rule change\s*:", re.I)


def path(slug):
    return os.path.join(QUESTS, slug, "followups.json")


def load(slug):
    try:
        return json.load(open(path(slug)))
    except (OSError, ValueError):
        return []


def has_wrapup(q):
    bdir = os.path.join(q, "boards")
    for b in (os.listdir(bdir) if os.path.isdir(bdir) else []):
        try:
            if json.load(open(os.path.join(bdir, b, "board.json"))).get("wrapup"):
                return True
        except (OSError, ValueError):
            pass
    return False


def text(f):
    try:
        return open(f).read()
    except OSError:
        return ""


def parent_of(slug, note):
    """The quest with a wrap-up whose status or meta names the same PR as this note."""
    urls = set(PR_URL.findall(note or ""))
    urls |= set(PR_URL.findall(text(os.path.join(QUESTS, slug, "brief.md"))))
    if not urls:
        return ""
    best = ""
    for name in sorted(os.listdir(QUESTS)):
        q = os.path.join(QUESTS, name)
        if name == slug or not os.path.isdir(q) or not has_wrapup(q):
            continue
        seen = text(os.path.join(q, "status")) + text(os.path.join(q, "meta.json"))
        if any(u in seen for u in urls):
            best = name  # sorted, so the newest timestamped slug wins
    return best


def add(slug, note):
    parent = parent_of(slug, note)
    if not parent:
        return ""
    rows = [r for r in load(parent) if r.get("quest") != slug]
    rows.append({"quest": slug, "note": note, "at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")})
    with open(path(parent), "w") as f:
        json.dump(rows, f, indent=2)
    return parent


def render(slug):
    rows = load(slug)
    if not rows:
        return ""
    rules = sum(1 for r in rows if RULE.match(r.get("note", "")))
    head = "Fixed after this report"
    summary = f"{len(rows)} fix{'es' if len(rows) != 1 else ''} landed after this page was written"
    summary += f", {rules} of them change{'s' if rules == 1 else ''} a rule." if rules else ". None changes a rule."
    out = [impactmap.CSS, f'<section class="gim guild-followups" aria-label="{head}"><h2>{head}</h2>'
           f'<p class="gim-sum">{html.escape(summary)}</p>']
    for r in rows:
        rule = bool(RULE.match(r.get("note", "")))
        lv, label = ("high", "rule") if rule else ("low", "fix")
        out.append(f'<div class="gim-row {lv}"><div class="lv">{label}</div><div>'
                   f'<div class="ba">{html.escape(r.get("note", ""))}</div>'
                   f'<div class="meta">{html.escape(r.get("quest", ""))} · {html.escape(r.get("at", "")[:16].replace("T", " "))}</div>'
                   f'</div></div>')
    out.append("</section>")
    return "".join(out)


def main(argv):
    if len(argv) >= 3 and argv[0] == "add":
        p = add(argv[1], " ".join(argv[2:]))
        if p:
            print(p)
        return 0
    if len(argv) == 2 and argv[0] == "show":
        print(render(argv[1]))
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
