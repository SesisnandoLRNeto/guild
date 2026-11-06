#!/usr/bin/env python3
"""The reel: what a quest did, as a short pixel-art explainer you can watch, or save as a video.

Scenes come from what the quest left behind: the brief, the plan (the pain, the cause, today and
after, the steps), the files it changed, the checks, the trial, the validation and the PR. An
adventurer can write `reel.json` in the quest folder to tell the story in its own words; any scene
it writes replaces the one guild would build.

    reel.py json <slug>      the scenes, as the page plays them

reel.json: {"title": "...", "scenes": [{"kind": "pain|cause|change|build|trial|result|note",
            "title": "...", "say": "what the narrator says", "items": ["..."],
            "before": ["..."], "after": ["..."]}]}
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
KINDS = ("title", "pain", "cause", "change", "build", "trial", "result", "note")


def qdir(slug):
    return os.path.join(GUILD_HOME, "quests", slug)


def read(path, default=""):
    try:
        return open(path).read()
    except OSError:
        return default


def load_json(path, default=None):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def short(text, limit=240):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def opening(intent):
    """The intent as whole sentences: a cut line or one that ends on "She asks:" loses its tail."""
    text = short(intent, 200)
    text = re.sub(r"\s*[^.!?]*(:|\.\.\.)\s*$", "", text) or text
    return text if text.endswith((".", "!", "?")) else text + "."


def build(slug):
    q = qdir(slug)
    meta = load_json(os.path.join(q, "meta.json"))
    if meta is None:
        return {"error": f"no quest {slug}"}
    import lore
    import planpage
    k = lore.klass(meta.get("build_model") or meta.get("model") or "", meta.get("tier", "")) or \
        {"name": "Wanderer", "race": "human"}
    brief = read(os.path.join(q, "brief.md"))
    intent = next((l.split(":", 1)[1].strip() for l in brief.splitlines() if l.lower().startswith("intent:")), "")
    if not intent:
        first = brief.strip().splitlines()[0] if brief.strip() else slug
        intent = re.sub(r"^ticket:\s*\S+\s*(\([^)]*\))?\.?\s*", "", first, flags=re.I)
    intent = planpage.plain(intent)
    plan = planpage.split(re.sub(r"^#\s+.*\n+", "", read(os.path.join(q, "plan.md")), count=1)) \
        if os.path.exists(os.path.join(q, "plan.md")) else {}
    why = load_json(os.path.join(q, "why.json"), {}) or {}
    status = (read(os.path.join(q, "status")).split("\t") + ["", ""])[:2]
    ticket = meta.get("ticket", "")
    name = ticket or slug

    scenes = [{"kind": "title", "title": name, "sub": short(intent, 90),
               "say": f"{name}. {opening(intent)} A {k['name']} took this quest."}]

    pain = planpage.first_lines(plan.get("pain", ""), 300) if plan.get("pain") else (why.get("pain") or "")
    if pain:
        scenes.append({"kind": "pain", "title": "The pain", "say": short(planpage.plain(pain), 280)})
    if plan.get("cause"):
        cause = planpage.plain(planpage.first_lines(plan["cause"], 300))
        where = re.findall(r"[\w./-]+\.\w+:\d+", plan["cause"])
        scenes.append({"kind": "cause", "title": "Why it happens", "say": short(cause, 280),
                       "items": where[:2]})
    before = planpage.list_items(plan.get("today", ""))[:3]
    after = planpage.list_items(plan.get("after", ""))[:4]
    if after:
        scenes.append({"kind": "change", "title": "What changes", "before": [short(x, 70) for x in before],
                       "after": [short(x, 70) for x in after],
                       "say": ("Before, " + short("; ".join(x.rstrip(".") for x in before), 120) + ". " if before else "")
                              + "After this quest: " + short("; ".join(x.rstrip(".") for x in after), 200) + "."})

    steps = [short(x, 80) for x in planpage.list_items(plan.get("how", ""))[:5]]
    changed = []
    try:
        import files
        listing = files.listing(slug)
        changed = listing.get("changed", []) if not listing.get("error") else []
    except Exception:
        changed = []
    if steps or changed:
        add = sum(int(c.get("add") or 0) for c in changed)
        dele = sum(int(c.get("del") or 0) for c in changed)
        names = [os.path.basename(c["path"]) for c in changed[:6]]
        count = f"{len(changed)} files changed, {add} lines added and {dele} removed." if changed else ""
        scenes.append({"kind": "build", "title": "At the forge", "items": steps or names,
                       "files": names, "count": [len(changed), add, dele],
                       "say": short(("It was built in steps. " if steps else "The forge worked on these files. ") + count, 220)})

    checks = []
    trial = load_json(os.path.join(q, "trial.json"))
    if trial:
        checks.append({"what": "Trial", "ok": trial.get("result") == "pass",
                       "note": short(("passed: " if trial.get("result") == "pass" else "skipped: ") + (trial.get("note") or ""), 70)})
    lines = [l for l in read(os.path.join(q, "checks.jsonl")).splitlines() if l.strip()]
    if lines:
        last = load_json_line(lines[-1]) or {}
        runs = [r for r in last.get("results", []) if r.get("kind") == "check"]
        if runs:
            green = sum(1 for r in runs if r.get("status") == "pass")
            checks.append({"what": "Acceptance checks", "ok": green == len(runs), "note": f"{green}/{len(runs)} green"})
    try:
        import scenarios
        s = scenarios.summary(slug)
        if s.get("exists"):
            checks.append({"what": "Your validation", "ok": bool(s.get("certified")),
                           "note": f"{s['pass']}/{s['total']} passed" + (", certified" if s.get("certified") else "")})
    except Exception:
        pass
    if checks:
        good = sum(1 for c in checks if c["ok"])
        scenes.append({"kind": "trial", "title": "Proof by trial", "items": checks,
                       "say": f"{good} of {len(checks)} proofs came back green. " + " ".join(f"{c['what']}: {c['note']}." for c in checks)})

    pr = re.search(r"https://github\.com/\S+/pull/(\d+)", " ".join(status)) or re.search(r"PR #(\d+)", " ".join(status))
    state = status[0].strip()
    scenes.append({"kind": "result", "title": "Back with the loot" if state == "done" else "On the road",
                   "pr": pr.group(1) if pr else "", "url": pr.group(0) if pr and pr.group(0).startswith("http") else "",
                   "say": (f"The quest is back with the loot: pull request {pr.group(1)} waits at the castle gate for review."
                           if pr else f"The quest stands at: {short(status[1] or state, 120)}.")})

    custom = load_json(os.path.join(q, "reel.json"), {}) or {}
    for sc in custom.get("scenes", []):
        if sc.get("kind") not in KINDS:
            sc["kind"] = "note"
        same = next((i for i, x in enumerate(scenes) if x["kind"] == sc["kind"] and sc["kind"] != "note"), None)
        if same is None:
            scenes.insert(len(scenes) - 1, sc)
        else:
            scenes[same] = {**scenes[same], **sc}
    return {"slug": slug, "ticket": ticket, "title": custom.get("title") or name, "hero": k.get("race", "human"),
            "klass": k.get("name", ""), "repo": os.path.basename(meta.get("repo", "")), "scenes": scenes}


def load_json_line(line):
    try:
        return json.loads(line)
    except ValueError:
        return None


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "json":
        raise SystemExit(__doc__)
    print(json.dumps(build(sys.argv[2]), indent=2))


if __name__ == "__main__":
    main()
