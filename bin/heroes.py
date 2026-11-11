#!/usr/bin/env python3
"""The hall of heroes: each model is a character that levels up with the quests it finished.

  heroes.py json      everything the /heroes page draws, as JSON

Reads the treasury's quest list (bin/treasury.py), so the numbers match the treasury. A quest
belongs to the hero of its main model; its gold is split by what each model really spent.

XP, per quest:  20 for setting out, +80 when it is done, +40 when it opened a PR,
                +15 per grade star, +25 when the checks were green on the first run,
                +5 per dollar spent (gold turns into experience).
Level L needs 75 * L * (L - 1) XP, so each level costs a little more than the last.
"""
import json
import math
import os
import sys
from datetime import datetime

BIN = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, BIN)

# key, words in the model name, name, race (web/races.svg), class, calm mode name, lore line
HEROES = [
    ("fable", ("fable",), "Fable", "dragon", "The Oracle", "Paladin",
     "Sees further than anyone. Eats more gold than anyone. Called for the hard questions, not the long ones."),
    ("opus", ("opus", "thinking"), "Opus", "highelf", "The Archmage", "",
     "Thinks for a long time, then is right. Usually. The quartermaster is one of them."),
    ("sonnet", ("sonnet",), "Sonnet", "dwarf", "Knight of the Forge", "Archer",
     "Steady hands. Builds all day, grumbles about the tests, builds some more."),
    ("haiku", ("haiku",), "Haiku", "gnome", "The Scout", "Warrior",
     "Small, fast and cheap. Runs the easy roads before the others have their boots on."),
    ("codex", ("codex", "gpt-"), "Codex", "gnome", "The Artificer", "",
     "A tinkerer from another guild (OpenAI). Gears, images and long mechanical jobs. Ranks by effort: "
     "apprentice (low), tinker (medium), artificer (high), master artificer (xhigh)."),
    ("mercenary", ("deepseek", "/", "qwen", "kimi", "glm"), "Sellswords", "human", "Hired Blades", "",
     "Hired through OpenRouter when the guild's own heroes are busy or out of gold. Loyal to whoever pays."),
]
TITLES = [(1, "Recruit"), (3, "Squire"), (5, "Adventurer"), (8, "Veteran"), (12, "Champion"), (16, "Hero"), (20, "Legend")]


def hero_of(model, harness=""):
    m = (model or "").lower()
    if harness == "codex":
        return "codex"
    for key, words, *_ in HEROES:
        if any(w in m for w in words):
            return key
    return "mercenary" if m else ""


def quest_xp(q):
    xp = 20
    if q.get("state") == "done":
        xp += 80
    if q.get("pr"):
        xp += 40
    xp += 15 * int(q.get("grade") or 0)
    if q.get("first_pass"):
        xp += 25
    xp += int(5 * (q.get("cost") or 0))
    return xp


def level_of(xp):
    lvl = max(1, int((1 + math.sqrt(1 + 4 * xp / 75)) / 2))
    floor, nxt = 75 * lvl * (lvl - 1), 75 * (lvl + 1) * lvl
    title = [t for at, t in TITLES if lvl >= at][-1]
    return {"level": lvl, "title": title, "floor": floor, "next": nxt}


def stat(v):
    return max(1, min(20, int(round(v))))


def build(quests):
    by = {h[0]: [] for h in HEROES}
    gold = {h[0]: 0.0 for h in HEROES}
    for q in quests:
        key = hero_of(q.get("model"), q.get("harness"))
        if key:
            by[key].append(q)
        for model, cost in (q.get("models") or {}).items():
            k = hero_of(model, q.get("harness")) or key
            if k:
                gold[k] += cost or 0
    out = []
    for key, _, name, race, klass, calm, lore in HEROES:
        qs = sorted(by[key], key=lambda r: r.get("created") or "")
        done = [q for q in qs if q.get("state") == "done"]
        graded = [q["grade"] for q in qs if q.get("grade")]
        fp = [q for q in qs if q.get("first_pass") is not None]
        decided = sum(q.get("decisions") or 0 for q in qs)
        overruled = sum(q.get("overruled") or 0 for q in qs)
        mins = sorted(q["minutes"] for q in done if q.get("minutes"))
        xp, timeline, log = 0, [], []
        for q in qs:
            gain = quest_xp(q)
            xp += gain
            timeline.append([(q.get("created") or "")[:10], xp])
            log.append({"when": (q.get("created") or "")[:10], "slug": q["slug"], "state": q.get("state"), "xp": gain,
                        "cost": round(q.get("cost") or 0, 2), "grade": q.get("grade"), "pr": q.get("pr", ""),
                        "model": q.get("model", "")})
        median = mins[len(mins) // 2] if mins else 0
        stats = {} if not qs else {
            "STR": stat(4 * math.log2(1 + len(done))),                       # quests finished
            "INT": stat(4 * (sum(graded) / len(graded))) if graded else 0,   # your grades
            "DEX": stat(20 - 3 * math.log2(1 + median / 5)) if median else 0,  # speed
            "CON": stat(20 * len(done) / len(qs)),                            # how often it finishes
            "WIS": stat(20 * sum(1 for q in fp if q["first_pass"]) / len(fp)) if fp else 0,  # green on the first run
            "CHA": stat(20 * (1 - overruled / decided)) if decided else 0,  # you took its advice
        }
        badges = []

        def badge(cond, icon, label, why):
            if cond:
                badges.append({"icon": icon, "label": label, "why": why})
        badge(qs, "flag", "First steps", "went on a first quest")
        badge(len(done) >= 10, "sword", "Ten trophies", "10 quests done")
        badge(len(done) >= 50, "shield", "Fifty trophies", "50 quests done")
        badge(len(done) >= 100, "crown", "Hundred trophies", "100 quests done")
        badge(sum(1 for q in qs if q.get("pr")) >= 10, "chest", "Treasure hunter", "10 pull requests")
        badge(any(q.get("grade") == 5 for q in qs), "crystal", "Legendary deed", "graded 5 at least once")
        badge(sum(1 for q in fp if q["first_pass"]) >= 10, "swords", "Clean blade", "10 quests green on the first run")
        badge(any(q.get("minutes") and q["minutes"] <= 10 and q.get("state") == "done" for q in qs), "hourglass", "Swift", "a quest done in 10 minutes or less")
        badge(gold[key] >= 100, "torch", "Dragon's hoard", "spent more than $100")
        out.append({
            "key": key, "name": name, "race": race, "class": klass, "calm": calm, "lore": lore,
            "recruited": bool(qs), "xp": xp, **level_of(xp),
            "quests": len(qs), "done": len(done), "failed": sum(1 for q in qs if q.get("state") in ("failed", "stopped")),
            "active": sum(1 for q in qs if q.get("state") in ("working", "needs-decision", "blocked")),
            "prs": sum(1 for q in qs if q.get("pr")), "gold": round(gold[key], 2),
            "grade": round(sum(graded) / len(graded), 1) if graded else None, "median_minutes": median,
            "stats": stats, "badges": badges, "timeline": timeline,
            "since": qs[0]["created"][:10] if qs else "", "log": list(reversed(log))[:12],
        })
    out.sort(key=lambda h: (-h["recruited"], -h["xp"]))
    return out


def data():
    import treasury
    return {"at": datetime.now().isoformat(timespec="seconds"), "heroes": build(treasury.quests())}


if __name__ == "__main__":
    if sys.argv[1:2] == ["json"]:
        print(json.dumps(data(), indent=1))
    else:
        print(__doc__)
