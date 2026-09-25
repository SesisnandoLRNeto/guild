#!/usr/bin/env python3
"""Lessons that need evidence (Backpass's rule): a lesson is proposed with verbatim quotes
from at least two different quests, guild checks every quote is really there, and the
guildmaster accepts or rejects it on the docket. Only accepted lessons reach lessons.md,
which the quartermaster reads before writing any brief.

  lessons.py propose "<lesson>" --evidence "<slug>: <quote>" --evidence "<slug>: <quote>" [--why "<why>"]
  lessons.py list
  lessons.py decide <id> accept|reject [note]     (the docket calls this)

A quote counts when it appears, ignoring case and spacing, in the quest's own files (brief,
report, trial, boards, your grade), its events, or its session log.
"""
import glob
import json
import os
import re
import sys
import time

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
PROPOSED = os.path.join(GUILD_HOME, "lessons-proposed.json")
LESSONS = os.path.join(GUILD_HOME, "lessons.md")
PROJECTS = os.environ.get("GUILD_CLAUDE_PROJECTS", os.path.expanduser("~/.claude/projects"))
BOARD_QUEST = "lessons"


def norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[`*_>\"']", "", text)).strip().lower()


def quest_dir(slug):
    live = os.path.join(QUESTS, slug)
    if os.path.isdir(live):
        return live
    archived = sorted(glob.glob(os.path.join(QUESTS, "_archive", f"{slug}-*")))
    return archived[-1] if archived else ""


def sources(slug):
    """(where, text) for every place a quest left words behind."""
    d = quest_dir(slug)
    if not d:
        return
    for path in glob.glob(os.path.join(d, "**", "*"), recursive=True):
        if os.path.isfile(path) and path.endswith((".md", ".json", ".html", ".txt")):
            try:
                yield os.path.relpath(path, d), open(path, errors="replace").read()
            except OSError:
                pass
    try:
        events = [l for l in open(os.path.join(GUILD_HOME, "events.log")).read().splitlines() if f"\t{slug}\t" in l]
        yield "events", "\n".join(events)
    except OSError:
        pass
    try:
        wt = json.load(open(os.path.join(d, "meta.json"))).get("worktree", "")
    except (OSError, ValueError):
        wt = ""
    if wt:
        folder = os.path.join(PROJECTS, re.sub(r"[/.]", "-", wt))
        for log in glob.glob(os.path.join(folder, "*.jsonl")):
            texts = []
            for line in open(log, errors="replace"):
                try:
                    msg = json.loads(line).get("message") or {}
                except ValueError:
                    continue
                c = msg.get("content")
                if isinstance(c, str):
                    texts.append(c)
                elif isinstance(c, list):
                    texts += [x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text"]
            yield "session log", "\n".join(texts)


def find(slug, quote):
    q = norm(quote)
    for where, text in sources(slug):
        if q and q in norm(text):
            return where
    return ""


def load():
    try:
        return json.load(open(PROPOSED))
    except (OSError, ValueError):
        return []


def save(items):
    json.dump(items, open(PROPOSED, "w"), indent=2)


def propose(text, evidence, why=""):
    rows = []
    for e in evidence:
        slug, _, quote = e.partition(":")
        slug, quote = slug.strip(), quote.strip()
        if not slug or len(quote) < 12:
            raise SystemExit(f"lesson refused: evidence must be '<quest>: <a quote of 12+ characters>', got {e!r}")
        where = find(slug, quote)
        if not where:
            raise SystemExit(f"lesson refused: the quote is not in quest {slug} (brief, report, trial, boards, grade, "
                             f"events or session log): {quote!r}. Quote it exactly as it was written.")
        rows.append({"quest": slug, "quote": quote, "where": where})
    if len({r["quest"] for r in rows}) < 2:
        raise SystemExit("lesson refused: a lesson needs quotes from at least two different quests. One quest "
                         "is an anecdote, not a pattern.")
    items = load()
    if any(norm(i["text"]) == norm(text) for i in items):
        raise SystemExit("lesson refused: the same lesson was already proposed (see guild lessons)")
    ident = time.strftime("L%y%m%d%H%M%S")
    item = {"id": ident, "text": text, "why": why, "evidence": rows, "status": "proposed",
            "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    item["board"] = put_on_docket(item)
    items.append(item)
    save(items)
    print(f"proposed {ident}: it is on the docket for the guildmaster to accept or reject")


def put_on_docket(item):
    """A board under the 'lessons' pseudo quest, answered from the docket like any other."""
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import wartable
    qdir = os.path.join(QUESTS, BOARD_QUEST)
    if not os.path.isdir(qdir):
        os.makedirs(qdir)
        json.dump({"slug": BOARD_QUEST, "repo": "lessons", "harness": "", "model": "", "pseudo": True},
                  open(os.path.join(qdir, "meta.json"), "w"))
        open(os.path.join(qdir, "status"), "w").write("working\tlessons waiting for you\t\n")
    esc = wartable._esc
    quotes = "".join(f'<li><blockquote>{esc(e["quote"])}</blockquote><span class="where">{esc(e["quest"])} · {esc(e["where"])}</span></li>'
                     for e in item["evidence"])
    page = (f'<!doctype html><html><head><meta charset="utf-8"><title>Lesson</title><style>'
            f'blockquote{{margin:0 0 2px;font-style:italic}} .where{{font-size:12px;color:var(--dim)}} li{{margin:10px 0}}</style></head>'
            f'<body><h1>A lesson to keep?</h1><p class="lead">{esc(item["text"])}</p>'
            f'{"<p>" + esc(item["why"]) + "</p>" if item["why"] else ""}'
            f'<h2>Evidence</h2><ul>{quotes}</ul>'
            f'<p class="lead">Accepted lessons go to lessons.md, which the quartermaster reads before every brief.</p></body></html>')
    tmp = os.path.join(GUILD_HOME, ".lesson-tmp")
    os.makedirs(tmp, exist_ok=True)
    json.dump({"questions": [{"id": "lesson", "title": "Keep this lesson?", "type": "single", "options": [
        {"id": "accept", "label": "Accept", "why": "it goes into lessons.md"},
        {"id": "reject", "label": "Reject", "why": "not a real pattern, or not worth a rule"}]}]},
        open(os.path.join(tmp, "decisions.json"), "w"))
    open(os.path.join(tmp, "page.html"), "w").write(page)
    board = item["id"].lower()
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        wartable.cmd_open({"quest": BOARD_QUEST, "id": board, "html": os.path.join(tmp, "page.html"),
                           "decisions": os.path.join(tmp, "decisions.json"), "title": f"Lesson: {item['text'][:60]}",
                           "no_open": True})
    path = os.path.join(QUESTS, BOARD_QUEST, "boards", board, "board.json")
    meta = json.load(open(path))
    meta.update(kind="lesson", lesson=item["id"])
    json.dump(meta, open(path, "w"), indent=2)
    return board


def decide(ident, choice, note=""):
    items = load()
    item = next((i for i in items if i["id"] == ident), None)
    if not item:
        raise SystemExit(f"no lesson {ident}")
    item["status"] = "accepted" if choice == "accept" else "rejected"
    item["note"] = note
    save(items)
    if item["status"] == "accepted":
        refs = "; ".join(f'{e["quest"]}: "{e["quote"][:80]}"' for e in item["evidence"])
        with open(LESSONS, "a") as f:
            f.write(f"- {item['text']}" + (f" ({note})" if note else "") + f"\n  evidence: {refs}\n")
    return item["status"]


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    if args[0] == "propose" and len(args) > 1:
        text, evidence, why, i = args[1], [], "", 2
        while i < len(args):
            if args[i] == "--evidence" and i + 1 < len(args):
                evidence.append(args[i + 1]); i += 2
            elif args[i] == "--why" and i + 1 < len(args):
                why = args[i + 1]; i += 2
            else:
                raise SystemExit(f"unknown argument {args[i]}")
        propose(text, evidence, why)
    elif args[0] == "list":
        for i in load():
            print(f"{i['id']}  {i['status']:<9} {i['text']}  ({', '.join(e['quest'] for e in i['evidence'])})")
        if os.path.exists(LESSONS):
            print(f"\naccepted lessons live in {LESSONS}")
    elif args[0] == "decide" and len(args) >= 3:
        print(decide(args[1], args[2], " ".join(args[3:])))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
