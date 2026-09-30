#!/usr/bin/env python3
"""The treasury: what the work cost, and what it was worth.

  treasury.py json      everything the /treasury page draws, as JSON

Three sources, all local:
  - the ledger, per quest: tokens, dollars, time, checks, trial, grade, decisions
  - every Claude Code session log on this Mac, per day and scope (quests, quartermasters,
    your own sessions), read once per file and then only the new lines (cache below)
  - Jev's own log (jev-usage.jsonl): one line per call with its tokens

Dollars are API prices from ~/.guild/local/pricing.json. A model with no price there is
priced with the default and flagged as estimated. Jev is priced only when pricing.json
has a "jev" entry; otherwise the page shows its calls and tokens and says so.
"""
import glob
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

BIN = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, BIN)
import ledger  # noqa: E402

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
PROJECTS = os.environ.get("GUILD_CLAUDE_PROJECTS", os.path.expanduser("~/.claude/projects"))
FILES_CACHE = os.path.join(GUILD_HOME, ".treasury-files.json")
DAYS = 30
KINDS = ("input", "output", "cache_write", "cache_read")


def load_json(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def local_day(stamp):
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().date().isoformat()
    except (TypeError, ValueError):
        return ""


# ── every session log on the Mac, per day ─────────────────────────────────────
def scan_files():
    """{path: {"days": {day: {model: {kind: tokens}}}}}, read incrementally: a log only grows,
    so each file is read from where the last scan stopped. A reply written on several lines
    (one per content block) counts once: the repeats sit next to each other."""
    cache = load_json(FILES_CACHE, {})
    cutoff = time.time() - (DAYS + 5) * 86400
    seen = set()
    for path in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        try:
            st = os.stat(path)
        except OSError:
            continue
        if st.st_mtime < cutoff:
            continue
        seen.add(path)
        c = cache.get(path)
        if not c or st.st_size < c.get("offset", 0):
            c = {"offset": 0, "last_id": "", "days": {}}
        if st.st_size == c["offset"]:
            cache[path] = c
            continue
        with open(path, "rb") as f:
            f.seek(c["offset"])
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1          # a half-written last line waits for the next scan
        for raw in chunk[:end].splitlines():
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if row.get("type") != "assistant":
                continue
            msg = row.get("message", {})
            mid, model = msg.get("id") or "", msg.get("model", "unknown")
            if model == "<synthetic>" or (mid and mid == c["last_id"]):
                continue
            c["last_id"] = mid
            day = local_day(row.get("timestamp", ""))
            if not day:
                continue
            u = msg.get("usage", {})
            b = c["days"].setdefault(day, {}).setdefault(model, dict.fromkeys(KINDS, 0))
            b["input"] += u.get("input_tokens", 0)
            b["output"] += u.get("output_tokens", 0)
            b["cache_write"] += u.get("cache_creation_input_tokens", 0)
            b["cache_read"] += u.get("cache_read_input_tokens", 0)
        c["offset"] += end
        cache[path] = c
    cache = {p: v for p, v in cache.items() if p in seen}
    try:
        json.dump(cache, open(FILES_CACHE, "w"))
    except OSError:
        pass
    return cache


def qm_sessions():
    ids = set()
    p = os.path.join(GUILD_HOME, "qm-session")
    if os.path.exists(p):
        ids.add(open(p).read().strip())
    for f in glob.glob(os.path.join(GUILD_HOME, "qms", "*.json")):
        ids.add(load_json(f, {}).get("session", ""))
    return ids - {""}


def scope_of(path, qms):
    folder = os.path.basename(os.path.dirname(path))
    if os.path.basename(path)[:-6] in qms:
        return "Quartermaster", "quartermaster"
    if "-guild-worktrees-" in folder:
        return "Quests", folder.split("-guild-worktrees-")[-1].replace("pool-", "")
    # "-Users-nando-Workspace-crowdgen-frontend" -> "Workspace/crowdgen-frontend"
    home = os.path.expanduser("~").replace("/", "-").replace(".", "-")
    name = folder[len(home):].strip("-") if folder.startswith(home) else folder.strip("-")
    name = name.replace("Workspace-", "Workspace/", 1)
    return "Your sessions", name or "~ (home folder)"


def daily(files):
    """Dollars per day for the last DAYS days, by scope and by model; and your sessions by folder."""
    qms = qm_sessions()
    start = (date.today() - timedelta(days=DAYS - 1)).isoformat()
    by_scope, by_model, folders, unknown = {}, {}, {}, set()
    for path, c in files.items():
        scope, folder = scope_of(path, qms)
        for day, models in c["days"].items():
            if day < start:
                continue
            for model, tokens in models.items():
                cost, unk = ledger.cost_of({model: tokens})
                unknown.update(unk)
                by_scope.setdefault(day, {}).setdefault(scope, 0.0)
                by_scope[day][scope] += cost
                by_model.setdefault(day, {}).setdefault(model, 0.0)
                by_model[day][model] += cost
                if scope == "Your sessions":
                    folders[folder] = folders.get(folder, 0.0) + cost
    days = [(date.today() - timedelta(days=DAYS - 1 - i)).isoformat() for i in range(DAYS)]
    return {"days": days,
            "by_scope": [{"day": d, **{k: round(v, 4) for k, v in by_scope.get(d, {}).items()}} for d in days],
            "by_model": [{"day": d, **{k: round(v, 4) for k, v in by_model.get(d, {}).items()}} for d in days],
            "folders": sorted(({"name": k, "cost": round(v, 2)} for k, v in folders.items()), key=lambda r: -r["cost"])[:12],
            "unknown": sorted(unknown)}


# ── Jev ───────────────────────────────────────────────────────────────────────
def jev():
    path = os.path.join(GUILD_HOME, "jev-usage.jsonl")
    rows = []
    if os.path.exists(path):
        for line in open(path):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    price = load_json(os.path.join(GUILD_HOME, "local", "pricing.json"), {}).get("jev")
    if not isinstance(price, dict) or not {"input", "output"} <= set(price):
        price = None

    def dollars(inp, out):
        return round(inp / 1e6 * price["input"] + out / 1e6 * price["output"], 4) if price else None

    by_why, by_day = {}, {}
    for r in rows:
        w = by_why.setdefault(r.get("why") or "other", {"calls": 0, "input": 0, "output": 0})
        w["calls"] += 1; w["input"] += r.get("input", 0); w["output"] += r.get("output", 0)
        d = by_day.setdefault(r["at"][:10], {"calls": 0, "input": 0, "output": 0})
        d["calls"] += 1; d["input"] += r.get("input", 0); d["output"] += r.get("output", 0)
    inp, out = sum(r.get("input", 0) for r in rows), sum(r.get("output", 0) for r in rows)
    for v in list(by_why.values()) + list(by_day.values()):
        v["cost"] = dollars(v["input"], v["output"])
    return {"calls": len(rows), "input": inp, "output": out, "cost": dollars(inp, out), "priced": bool(price),
            "by_why": by_why, "by_day": by_day, "since": rows[0]["at"] if rows else ""}


# ── quests ────────────────────────────────────────────────────────────────────
def stories():
    names = load_json(os.path.join(GUILD_HOME, "stories.json"), {})
    parents = {k: (v.get("parent") or {}).get("summary", "")
               for k, v in load_json(os.path.join(GUILD_HOME, ".campaign-tickets.json"), {}).get("info", {}).items()}
    return names, parents


def quests():
    sys.path.insert(0, BIN)
    import prs as prmod
    pr_of = prmod.by_slug()
    names, parents = stories()
    events = os.path.join(GUILD_HOME, "events.log")
    lines = [l.split("\t") for l in open(events).read().splitlines()] if os.path.exists(events) else []
    out = []
    for d in ledger.quest_dirs():
        try:
            q = ledger.load(d)
        except (OSError, ValueError, KeyError):
            continue
        meta = q["meta"]
        if not q.get("cost") and not q.get("messages"):
            continue                                   # a test run or a quest that never started
        ticket = meta.get("ticket", "")
        grade = ledger.grade_of(d) or q.get("grade") or None
        decisions = ledger.decisions_of(q)
        mine = [e for e in lines if len(e) > 2 and e[1] == q["slug"]]
        pr = pr_of.get(q["slug"]) or {}
        per_model = {}
        for model, tokens in (q.get("models") or {}).items():
            if model == "<synthetic>":
                continue
            per_model[model] = round(ledger.cost_of({model: tokens})[0], 4)
        tokens = {k: sum(t.get(k, 0) for t in (q.get("models") or {}).values()) for k in KINDS}
        mins = 0
        if q.get("first") and q.get("last"):
            try:
                a = datetime.fromisoformat(q["first"].replace("Z", "+00:00"))
                b = datetime.fromisoformat(q["last"].replace("Z", "+00:00"))
                mins = max(0, int((b - a).total_seconds() // 60))
            except ValueError:
                pass
        edd = q.get("edd") or {}
        out.append({
            "slug": q["slug"], "ticket": ticket, "story": names.get(ticket) or parents.get(ticket) or "",
            "repo": os.path.basename(meta.get("repo", "")), "harness": meta.get("harness", "claude"),
            "tier": meta.get("tier", ""), "model": meta.get("model", "") or (max(per_model, key=per_model.get) if per_model else ""),
            "models": per_model, "state": q["state"], "archived": q["archived"],
            "created": meta.get("created", "") or (q.get("first") or "")[:19], "minutes": mins,
            "messages": q.get("messages", 0), "tokens": tokens, "cost": round(q.get("cost") or 0, 4),
            "estimated": bool(q.get("unknown")),
            "first_pass": edd.get("first_pass"), "runs_to_green": edd.get("runs_to_green"), "weak": len(edd.get("weak") or []),
            "trial": q.get("trial", ""),
            "grade": (grade or {}).get("grade"), "verdict": (grade or {}).get("verdict", ""),
            "decisions": len(decisions), "overruled": sum(1 for x in decisions if x["overruled"]),
            "escalations": sum(1 for e in mine if e[2] == "needs-decision"),
            "stalls": sum(1 for e in mine if e[2] == "stopped"),
            "pr": pr.get("state", "") if not pr.get("error") else "",
        })
    out.sort(key=lambda r: r["created"], reverse=True)
    return out


def data():
    qs = quests()
    files = scan_files()
    day = daily(files)
    j = jev()
    now = date.today()

    def spent(n):
        start = (now - timedelta(days=n - 1)).isoformat()
        return round(sum(v for r in day["by_scope"] if r["day"] >= start for k, v in r.items() if k != "day"), 2)

    pricing = load_json(os.path.join(GUILD_HOME, "local", "pricing.json"), {})
    known = set(pricing.get("models", {}))
    unknown = sorted(m for m in set(day["unknown"]) | {m for q in qs for m in q["models"]}
                     if m != "<synthetic>" and m not in known and re.sub(r"-\d{8}$", "", m) not in known)
    return {"at": time.strftime("%H:%M"), "today": now.isoformat(),
            "totals": {"week": spent(7), "month": spent(DAYS), "quests_all": round(sum(q["cost"] for q in qs), 2),
                       "quests": len(qs)},
            "daily": day, "quests": qs, "jev": j,
            "unknown_models": unknown, "default_model": pricing.get("_default", "claude-opus-5")}


if __name__ == "__main__":
    if (sys.argv[1:] or ["json"])[0] != "json":
        raise SystemExit(__doc__)
    print(json.dumps(data(), indent=1))
