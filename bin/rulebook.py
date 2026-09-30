#!/usr/bin/env python3
"""The rule book and the weekly drill: learn the business rules the work keeps changing.

  rulebook.py list [area]     the rules per area, as text
  rulebook.py json            everything the /rules page draws
  rulebook.py drill           this week's drill (made on first call of the week), as JSON

Every backend wrap-up explains its business rule changes in a rules file (guild impact --rules).
This collects them from every quest, live and closed, into one book per area (the repo): the
rule in plain words, what it does now and what it did before, why, an example with real values
when the adventurer gave one, where it lives in the code, the tests that prove it, and which
quests changed it. The same rule written by two quests is one entry with a history.

The drill asks three rules a week: first those you were never asked, then those you missed,
then the ones asked longest ago. You answer in your own words, then see the truth (with where
it lives in the code) and mark yourself right or wrong. Nothing is graded for you: you stay the
judge, and a miss comes back the next week. Results live in ~/.guild/drill.json.
"""
import glob
import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import date

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
DRILL = os.path.join(GUILD_HOME, "drill.json")
PER_WEEK = 3


def load_json(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def quest_of(path):
    """The quest folder a rules file sits in, and its meta."""
    rel = os.path.relpath(path, QUESTS).split(os.sep)
    qdir = os.path.join(QUESTS, rel[0], rel[1]) if rel[0] == "_archive" else os.path.join(QUESTS, rel[0])
    return qdir, load_json(os.path.join(qdir, "meta.json"), {})


def norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def key_of(area, rule):
    return hashlib.sha1(f"{area}|{norm(rule)}".encode()).hexdigest()[:12]


def collect():
    """{area: [rule entries]}, one entry per distinct rule, newest change first."""
    book = {}
    seen_files = set()
    for path in glob.glob(os.path.join(QUESTS, "**", "rules*.json"), recursive=True):
        data = load_json(path, None)
        if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
            continue
        digest = hashlib.sha1(open(path, "rb").read()).hexdigest()
        qdir, meta = quest_of(path)
        if (qdir, digest) in seen_files:            # the same file copied into a board folder
            continue
        seen_files.add((qdir, digest))
        area = os.path.basename(meta.get("repo", "")) or "other"
        when = (meta.get("created") or time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(path))))[:10]
        for r in data["rules"]:
            if not isinstance(r, dict) or not str(r.get("rule", "")).strip():
                continue
            k = key_of(area, r["rule"])
            change = {"quest": meta.get("slug") or os.path.basename(qdir), "ticket": meta.get("ticket", ""), "date": when,
                      "before": r.get("before", ""), "after": r.get("after", ""), "why": r.get("why", "")}
            entries = book.setdefault(area, {})
            e = entries.get(k)
            if not e:
                e = entries[k] = {"key": k, "area": area, "rule": str(r["rule"]).strip(), "history": []}
            e["history"].append(change)
            if change["date"] >= e.get("date", ""):                # the newest change speaks for the rule
                e.update(date=change["date"], after=r.get("after", ""), before=r.get("before", ""), why=r.get("why", ""),
                         where=r.get("where", ""), example=r.get("example"), source=r.get("source", ""),
                         tests=r.get("tests", ""), ticket=meta.get("ticket", ""), quest=change["quest"])
    out = {}
    for area, entries in book.items():
        rules = list(entries.values())
        for e in rules:
            e["history"].sort(key=lambda h: h["date"], reverse=True)
        rules.sort(key=lambda e: (e.get("date", ""), e["rule"]), reverse=True)
        out[area] = rules
    return dict(sorted(out.items()))


# ── the drill ─────────────────────────────────────────────────────────────────
def question(e):
    """What to ask about a rule, and the truth to compare with."""
    ex = e.get("example")
    if isinstance(ex, dict) and ex.get("given"):
        return f"Given {ex['given']}: what happens?", ex.get("then") or e.get("after", "")
    if isinstance(ex, str) and ex.strip():
        return f"{e['rule']}. Here is a case: {ex}. What does the system do?", e.get("after", "")
    return f"{e['rule']}: what does the system do now, and why?", (e.get("after") or "") + (f" Why: {e['why']}" if e.get("why") else "")


def week_id(d=None):
    y, w, _ = (d or date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def drill():
    """This week's questions, made on the first call of the week and kept for the rest of it."""
    state = load_json(DRILL, {"asked": {}, "weeks": {}})
    wk = week_id()
    book = {e["key"]: e for rules in collect().values() for e in rules}
    week = state["weeks"].get(wk, {"keys": [], "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    have = [k for k in week["keys"] if k in book]
    if len(have) < PER_WEEK and len(book) > len(have):         # a new week, or one that started before the rules came
        def score(k):
            hist = state["asked"].get(k, [])
            if not hist:
                return (0, "")
            last = hist[-1]
            return (1 if not last.get("right") else 2, last.get("at", ""))
        extra = sorted((k for k in book if k not in have), key=lambda k: (score(k), random.Random(wk + k).random()))
        week["keys"] = have + extra[:PER_WEEK - len(have)]
        state["weeks"][wk] = week
        json.dump(state, open(DRILL, "w"), indent=2)
    elif wk not in state["weeks"]:
        state["weeks"][wk] = week
    items = []
    for k in state["weeks"].get(wk, {"keys": []})["keys"]:
        e = book.get(k)
        if not e:
            continue
        q, truth = question(e)
        done = [h for h in state["asked"].get(k, []) if h.get("week") == wk]
        items.append({"key": k, "area": e["area"], "question": q, "truth": truth, "where": e.get("where", ""),
                      "tests": e.get("tests", ""), "source": e.get("source", ""), "ticket": e.get("ticket", ""),
                      "rule": e["rule"], "answered": done[-1] if done else None})
    total = len(book)
    asked = [k for k in book if state["asked"].get(k)]
    right = [k for k in asked if state["asked"][k][-1].get("right")]
    return {"week": wk, "items": items, "total": total, "asked": len(asked), "right": len(right),
            "due": any(i["answered"] is None for i in items)}


def grade(key, right, answer=""):
    state = load_json(DRILL, {"asked": {}, "weeks": {}})
    state["asked"].setdefault(key, []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "week": week_id(),
                                               "right": bool(right), "answer": str(answer)[:1000]})
    json.dump(state, open(DRILL, "w"), indent=2)
    return {"ok": True}


def main():
    a = sys.argv[1:] or ["list"]
    if a[0] == "json":
        book = collect()
        print(json.dumps({"areas": book, "count": sum(len(v) for v in book.values())}, indent=1))
    elif a[0] == "drill":
        print(json.dumps(drill(), indent=1))
    elif a[0] == "list":
        for area, rules in collect().items():
            if len(a) > 1 and a[1] != area:
                continue
            print(f"\n{area} ({len(rules)} rules)")
            for e in rules:
                print(f"  - {e['rule']}: {e.get('after', '')}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
