#!/usr/bin/env python3
"""What each quest cost, and what the fleet has done.

Claude Code writes one session log per working directory under
~/.claude/projects/<cwd with / and . turned into ->/<session-id>.jsonl, with the token
usage of every turn. A quest owns its worktree, so those logs are its logs. This reads
them, prices the tokens, and keeps the answer next to the quest.

On a subscription nothing is billed per token: the dollars are what the same work would
have cost on the API. That is still the honest way to compare one quest with another.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import checks  # noqa: E402  (bin/checks.py: the acceptance contract and its runs)

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
ARCHIVE = os.path.join(QUESTS, "_archive")
REPO = os.environ.get("GUILD_REPO", os.path.expanduser("~/Workspace/guild"))
PROJECTS = os.path.expanduser("~/.claude/projects")
DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
COLORS = {"done": "\033[38;5;114m", "failed": "\033[38;5;174m", "working": "\033[38;5;111m",
          "needs-decision": "\033[38;5;179m", "blocked": "\033[38;5;174m", "stopped": "\033[38;5;176m"}


def pricing():
    for path in (os.path.join(GUILD_HOME, "local", "pricing.json"),
                 os.path.join(REPO, "config", "pricing.example.json")):
        if os.path.exists(path):
            data = json.load(open(path))
            return data.get("models", {}), data.get("_default", "claude-opus-5")
    return {}, "claude-opus-5"


def project_dir_for(path):
    """Claude turns a working directory into a folder name by replacing / and . with -."""
    return os.path.join(PROJECTS, path.replace("/", "-").replace(".", "-"))


def read_usage(worktree):
    """Tokens per model, message count and the time span, from a worktree's session logs."""
    models, messages, first, last, sessions = {}, 0, None, None, 0
    d = project_dir_for(worktree)
    if not os.path.isdir(d):
        return models, messages, first, last, sessions
    for name in os.listdir(d):
        if not name.endswith(".jsonl"):
            continue
        sessions += 1
        for line in open(os.path.join(d, name), errors="ignore"):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            stamp = row.get("timestamp")
            if stamp:
                first = min(first, stamp) if first else stamp
                last = max(last, stamp) if last else stamp
            if row.get("type") != "assistant":
                continue
            messages += 1
            msg = row.get("message", {})
            usage = msg.get("usage", {})
            bucket = models.setdefault(msg.get("model", "unknown"),
                                       {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0})
            bucket["input"] += usage.get("input_tokens", 0)
            bucket["output"] += usage.get("output_tokens", 0)
            bucket["cache_write"] += usage.get("cache_creation_input_tokens", 0)
            bucket["cache_read"] += usage.get("cache_read_input_tokens", 0)
    return models, messages, first, last, sessions


def cost_of(models):
    """Dollars, plus the models we had no price for."""
    table, default = pricing()
    total, unknown = 0.0, []
    for model, tokens in models.items():
        rates = table.get(model)
        if rates is None:
            unknown.append(model)
            rates = table.get(default, {"input": 5.0, "output": 25.0, "cache_write": 6.25, "cache_read": 0.5})
        for kind, count in tokens.items():
            total += count / 1_000_000 * rates.get(kind, 0.0)
    return total, unknown


def quest_dirs(include_archive=True):
    out = []
    if os.path.isdir(QUESTS):
        out += [os.path.join(QUESTS, n) for n in sorted(os.listdir(QUESTS))
                if n != "_archive" and os.path.exists(os.path.join(QUESTS, n, "meta.json"))]
    if include_archive and os.path.isdir(ARCHIVE):
        out += [os.path.join(ARCHIVE, n) for n in sorted(os.listdir(ARCHIVE))
                if os.path.exists(os.path.join(ARCHIVE, n, "meta.json"))]
    return out


def load(d):
    """Everything worth knowing about one quest."""
    meta = json.load(open(os.path.join(d, "meta.json")))
    q = {"dir": d, "slug": meta.get("slug", os.path.basename(d)), "meta": meta,
         "archived": os.path.dirname(d) == ARCHIVE}
    status = os.path.join(d, "status")
    parts = (open(status).read().rstrip("\n").split("\t") + ["", "", ""])[:3] if os.path.exists(status) else ["?", "", ""]
    q["state"], q["note"], q["at"] = parts

    snapshot = os.path.join(d, "ledger.json")
    if os.path.exists(snapshot):           # closed quests keep the numbers they had
        q.update(json.load(open(snapshot)))
        q["source"] = "snapshot"
    else:
        models, messages, first, last, sessions = read_usage(meta.get("worktree", ""))
        cost, unknown = cost_of(models)
        q.update({"models": models, "messages": messages, "first": first, "last": last,
                  "sessions": sessions, "cost": cost, "unknown": unknown, "source": "live"})

    q["edd"] = checks.summarize(d)

    trial = os.path.join(d, "trial.json")
    q["trial"] = json.load(open(trial))["result"] if os.path.exists(trial) else ""
    boards = os.path.join(d, "boards")
    q["decisions"] = len([b for b in os.listdir(boards)
                          if os.path.exists(os.path.join(boards, b, "decision.json"))]) if os.path.isdir(boards) else 0
    return q


def tokens_of(q):
    return sum(sum(t.values()) for t in q.get("models", {}).values())


def duration(q):
    if not q.get("first") or not q.get("last"):
        return ""
    try:
        start = datetime.fromisoformat(q["first"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(q["last"].replace("Z", "+00:00"))
    except ValueError:
        return ""
    mins = max(0, int((end - start).total_seconds() // 60))
    return f"{mins // 60}h{mins % 60:02d}" if mins >= 60 else f"{mins}m"


def human_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def money(c):
    return f"${c:,.2f}" if c >= 1 else f"${c:.3f}"


def since_cutoff(spec):
    m = re.fullmatch(r"(\d+)([dhw])", spec or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    delta = {"h": timedelta(hours=n), "d": timedelta(days=n), "w": timedelta(weeks=n)}[unit]
    return datetime.now() - delta


def created_at(q):
    stamp = q["meta"].get("created") or q.get("first") or ""
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00").split("+")[0])
    except ValueError:
        return None


def cmd_cost(args):
    only = args.get("slug")
    rows = [load(d) for d in quest_dirs(include_archive=not args.get("active"))]
    if only:
        rows = [r for r in rows if r["slug"] == only]
        if not rows:
            sys.exit(f"guild: no quest '{only}'")
    rows.sort(key=lambda r: r["cost"], reverse=True)

    print(f"{BOLD}{'QUEST':<26} {'MODEL':<20} {'TOKENS':>8} {'MSGS':>5} {'TIME':>6} {'COST':>9}{RESET}")
    total, unknown = 0.0, set()
    for q in rows:
        models = ", ".join(sorted(q.get("models", {}))) or q["meta"].get("model", "")
        color = COLORS.get(q["state"], "")
        print(f"{color}{q['slug'][:25]:<26}{RESET} {models[:19]:<20} {human_tokens(tokens_of(q)):>8} "
              f"{q.get('messages', 0):>5} {duration(q):>6} {money(q['cost']):>9}")
        total += q["cost"]
        unknown.update(q.get("unknown", []))
    print(f"{BOLD}{'total':<26} {'':<20} {'':>8} {'':>5} {'':>6} {money(total):>9}{RESET}")
    if unknown:
        print(f"{DIM}estimated for unpriced models ({', '.join(sorted(unknown))}): "
              f"add them to ~/.guild/local/pricing.json{RESET}")
    print(f"{DIM}what this work would cost on the API; a subscription bills differently{RESET}")

    if len(rows) > 1:
        for q in rows[:1]:
            print(f"{DIM}most expensive: {q['slug']} ({money(q['cost'])}){RESET}")


def cmd_log(args):
    rows = [load(d) for d in quest_dirs()]
    cutoff = since_cutoff(args.get("since"))
    if cutoff:
        rows = [r for r in rows if (created_at(r) or datetime.min) >= cutoff]
    if args.get("repo"):
        rows = [r for r in rows if args["repo"] in os.path.basename(r["meta"].get("repo", ""))]
    rows.sort(key=lambda r: r["meta"].get("created", ""), reverse=True)

    if args.get("slug"):
        return show_one([r for r in rows if r["slug"] == args["slug"]], args["slug"])

    print(f"{BOLD}{'WHEN':<11} {'QUEST':<24} {'REPO':<20} {'STATE':<15} {'TRIAL':<6} {'DEC':>3} {'COST':>8}{RESET}")
    for q in rows:
        when = (q["meta"].get("created", "") or "")[:10]
        color = COLORS.get(q["state"], "")
        print(f"{DIM}{when:<11}{RESET} {q['slug'][:23]:<24} {os.path.basename(q['meta'].get('repo',''))[:19]:<20} "
              f"{color}{q['state'][:14]:<15}{RESET} {q['trial'][:5]:<6} {q['decisions']:>3} {money(q['cost']):>8}")
    if not rows:
        print(f"{DIM}no quests yet{RESET}")
        return
    print(f"{DIM}{len(rows)} quest(s), {money(sum(r['cost'] for r in rows))} total. "
          f"guild log <slug> for one quest's story.{RESET}")


def show_one(matches, slug):
    if not matches:
        sys.exit(f"guild: no quest '{slug}'")
    q = matches[0]
    m = q["meta"]
    print(f"{BOLD}{q['slug']}{RESET}  {DIM}{m.get('repo','')}  {m.get('branch','')}{RESET}")
    print(f"  state     {COLORS.get(q['state'],'')}{q['state']}{RESET}  {q['note']}")
    print(f"  harness   {m.get('harness','')} {m.get('model','')}   identity {m.get('identity','')}")
    print(f"  started   {m.get('created','')}   ran {duration(q) or 'n/a'}   sessions {q.get('sessions',0)}")
    print(f"  cost      {money(q['cost'])} over {human_tokens(tokens_of(q))} tokens, {q.get('messages',0)} replies")
    for model, tokens in sorted(q.get("models", {}).items()):
        print(f"            {DIM}{model}: in {human_tokens(tokens['input'])}, out {human_tokens(tokens['output'])}, "
              f"cache w {human_tokens(tokens['cache_write'])} / r {human_tokens(tokens['cache_read'])}{RESET}")
    print(f"  trial     {q['trial'] or 'none'}   decisions on the war table: {q['decisions']}")
    edd = q.get("edd", {})
    if edd.get("checks"):
        story = ("first pass" if edd.get("first_pass") else
                 f"green after {edd['runs_to_green']} runs" if edd.get("runs_to_green") else
                 "not green yet" if edd.get("runs") else "never run")
        print(f"  checks    {edd['checks']} check(s), {edd.get('manual', 0)} manual: {story}"
              + (f", {len(edd['weak'])} weak" if edd.get("weak") else ""))

    brief = os.path.join(q["dir"], "brief.md")
    if os.path.exists(brief):
        print(f"\n{BOLD}brief{RESET}")
        for line in open(brief).read().strip().splitlines()[:12]:
            print(f"  {DIM}{line[:100]}{RESET}")
    boards = os.path.join(q["dir"], "boards")
    if os.path.isdir(boards):
        print(f"\n{BOLD}decisions{RESET}")
        for b in sorted(os.listdir(boards)):
            dec = os.path.join(boards, b, "decision.json")
            title = json.load(open(os.path.join(boards, b, "board.json"))).get("title", b)
            if os.path.exists(dec):
                d = json.load(open(dec))
                picked = ", ".join(f"{k}={v}" for k, v in d.get("answers", {}).items()) or "message only"
                print(f"  {title[:60]}: {picked}  {DIM}{d.get('message','')[:50]}{RESET}")
            else:
                print(f"  {title[:60]}: {DIM}still waiting{RESET}")
    events = os.path.join(GUILD_HOME, "events.log")
    if os.path.exists(events):
        mine = [l for l in open(events) if f"\t{q['slug']}\t" in l][-8:]
        if mine:
            print(f"\n{BOLD}events{RESET}")
            for l in mine:
                parts = l.rstrip("\n").split("\t")
                print(f"  {DIM}{parts[0][5:16]}{RESET} {parts[2]:<16} {DIM}{parts[3][:70]}{RESET}")


def decisions_of(q):
    """Every answered board: what was asked, what was suggested, what the guildmaster picked."""
    out = []
    boards = os.path.join(q["dir"], "boards")
    if not os.path.isdir(boards):
        return out
    for b in sorted(os.listdir(boards)):
        bd = os.path.join(boards, b)
        dec, meta_p, q_p = (os.path.join(bd, n) for n in ("decision.json", "board.json", "decisions.json"))
        if not os.path.exists(dec) or not os.path.exists(meta_p):
            continue
        answer = json.load(open(dec))
        title = json.load(open(meta_p)).get("title", b)
        asked = json.load(open(q_p)).get("questions", []) if os.path.exists(q_p) else []
        for question in asked or [{"id": "", "title": title, "recommended": None}]:
            picked = answer.get("answers", {}).get(question.get("id"), "")
            out.append({"question": question.get("title", title),
                        "recommended": question.get("recommended"),
                        "picked": picked,
                        "overruled": bool(question.get("recommended") and picked
                                          and picked != question.get("recommended")),
                        "message": answer.get("message", "")})
    return out


def cmd_retro(args):
    """The facts a retro needs. An agent turns these into lessons; this only counts."""
    cutoff = since_cutoff(args.get("since") or "14d")
    rows = [load(d) for d in quest_dirs()]
    rows = [r for r in rows if not cutoff or (created_at(r) or datetime.min) >= cutoff]
    rows.sort(key=lambda r: r["meta"].get("created", ""))

    events = os.path.join(GUILD_HOME, "events.log")
    lines = open(events).read().splitlines() if os.path.exists(events) else []

    report = {"window": args.get("since") or "14d", "quests": [], "totals": {}}
    for q in rows:
        slug = q["slug"]
        mine = [l.split("\t") for l in lines if f"\t{slug}\t" in l]
        report["quests"].append({
            "slug": slug,
            "ticket": q["meta"].get("ticket", ""),
            "repo": os.path.basename(q["meta"].get("repo", "")),
            "harness": q["meta"].get("harness", ""),
            "model": q["meta"].get("model", ""),
            "state": q["state"],
            "cost": round(q["cost"], 3),
            "duration": duration(q),
            "messages": q.get("messages", 0),
            "trial": q["trial"],
            "brief_lines": len(open(os.path.join(q["dir"], "brief.md")).read().splitlines())
            if os.path.exists(os.path.join(q["dir"], "brief.md")) else 0,
            "decisions": decisions_of(q),
            "stalls": sum(1 for e in mine if len(e) > 2 and e[2] == "stopped"),
            "escalations": sum(1 for e in mine if len(e) > 2 and e[2] == "needs-decision"),
            "revived": sum(1 for e in mine if len(e) > 3 and "revived" in e[3]),
            "edd": q.get("edd", {}),
        })

    quests = report["quests"]
    decisions = [d for q in quests for d in q["decisions"]]
    report["totals"] = {
        "quests": len(quests),
        "cost": round(sum(q["cost"] for q in quests), 3),
        "by_model": {m: round(sum(q["cost"] for q in quests if q["model"] == m), 3)
                     for m in sorted({q["model"] for q in quests if q["model"]})},
        "finished": sum(1 for q in quests if q["state"] == "done"),
        "failed": sum(1 for q in quests if q["state"] == "failed"),
        "trials_skipped": sum(1 for q in quests if q["trial"] == "skip"),
        "trials_passed": sum(1 for q in quests if q["trial"] == "pass"),
        "decisions": len(decisions),
        "recommendation_overruled": sum(1 for d in decisions if d["overruled"]),
        "stalls": sum(q["stalls"] for q in quests),
        "escalations": sum(q["escalations"] for q in quests),
    }
    # EDD: how often a quest met its own acceptance on the first real run, per model.
    judged = [q for q in quests if q["edd"].get("checks") and q["edd"].get("first_pass") is not None]
    by_model = {}
    for q in judged:
        m = by_model.setdefault(q["model"] or q["harness"], [0, 0])
        m[0] += 1 if q["edd"]["first_pass"] else 0
        m[1] += 1
    report["totals"]["edd"] = {
        "quests_with_checks": sum(1 for q in quests if q["edd"].get("checks")),
        "first_pass": sum(1 for q in judged if q["edd"]["first_pass"]),
        "judged": len(judged),
        "first_pass_by_model": {m: f"{a}/{b}" for m, (a, b) in sorted(by_model.items())},
        "weak_checks": sum(len(q["edd"].get("weak", [])) for q in quests),
        "code_quests_without_checks": sum(1 for q in quests if q["trial"] and not q["edd"].get("checks")),
    }
    if args.get("json"):
        print(json.dumps(report, indent=2))
        return

    t = report["totals"]
    print(f"{BOLD}retro, last {report['window']}{RESET}")
    print(f"  {t['quests']} quests, {t['finished']} done, {t['failed']} failed, {money(t['cost'])}")
    print(f"  trials: {t['trials_passed']} passed, {t['trials_skipped']} skipped")
    print(f"  decisions: {t['decisions']}, your call differed from the recommendation {t['recommendation_overruled']} time(s)")
    print(f"  friction: {t['escalations']} escalations, {t['stalls']} silent stops")
    if t["by_model"]:
        print("  spend by model: " + ", ".join(f"{m} {money(c)}" for m, c in t["by_model"].items()))
    e = t["edd"]
    if e["quests_with_checks"]:
        rate = f"{e['first_pass']}/{e['judged']}" if e["judged"] else "no runs yet"
        print(f"  acceptance: first pass {rate}"
              + (" · by model " + ", ".join(f"{m} {v}" for m, v in e["first_pass_by_model"].items()) if e["first_pass_by_model"] else "")
              + (f" · {e['weak_checks']} weak check(s)" if e["weak_checks"] else ""))
    if e["code_quests_without_checks"]:
        print(f"  {e['code_quests_without_checks']} code quest(s) had no acceptance checks at all")
    print()
    for q in quests:
        flags = []
        if q["trial"] == "skip":
            flags.append("trial skipped")
        if q["stalls"]:
            flags.append(f"{q['stalls']} silent stop(s)")
        if q["escalations"] > 1:
            flags.append(f"{q['escalations']} escalations")
        if any(d["overruled"] for d in q["decisions"]):
            flags.append("recommendation overruled")
        if q["brief_lines"] and q["brief_lines"] < 3:
            flags.append("very short brief")
        edd = q["edd"]
        if edd.get("checks"):
            if edd.get("first_pass") is True:
                flags.append("acceptance: first pass")
            elif edd.get("runs_to_green"):
                flags.append(f"acceptance: green after {edd['runs_to_green']} runs")
            elif edd.get("runs"):
                flags.append("acceptance: never green")
            if edd.get("weak"):
                flags.append(f"{len(edd['weak'])} weak check(s)")
        mark = COLORS.get(q["state"], "")
        print(f"  {mark}{q['slug'][:28]:<30}{RESET} {q['model'][:14]:<15} {money(q['cost']):>8} "
              f"{DIM}{', '.join(flags) or 'clean'}{RESET}")
        for d in q["decisions"]:
            if d["overruled"]:
                print(f"    {DIM}asked: {d['question'][:60]}{RESET}")
                print(f"    {DIM}suggested {d['recommended']}, you chose {d['picked']}"
                      f"{' - ' + d['message'][:40] if d['message'] else ''}{RESET}")
    print(f"\n{DIM}Turn this into lessons with the retro skill; they land in ~/.guild/lessons.md{RESET}")


def cmd_costs(args):
    """Cost per quest as JSON, cached, for the cockpit. Reading every log is too slow for a 2s refresh."""
    cache = os.path.join(GUILD_HOME, ".cost-cache.json")
    max_age = float(args.get("max-age") or 45)
    try:
        cached = json.load(open(cache))
        if datetime.now().timestamp() - cached["at"] < max_age:
            print(json.dumps(cached["costs"]))
            return
    except (OSError, ValueError, KeyError):
        pass
    costs = {}
    for d in quest_dirs(include_archive=False):
        try:
            q = load(d)
            costs[q["slug"]] = round(q["cost"], 4)
        except (OSError, ValueError):
            continue
    try:
        json.dump({"at": datetime.now().timestamp(), "costs": costs}, open(cache, "w"))
    except OSError:
        pass
    print(json.dumps(costs))


def cmd_snapshot(args):
    """Freeze a quest's numbers before its worktree and logs can drift (used by guild close)."""
    d = os.path.join(QUESTS, args["slug"])
    if not os.path.isdir(d):
        sys.exit(f"guild: no quest '{args['slug']}'")
    meta = json.load(open(os.path.join(d, "meta.json")))
    models, messages, first, last, sessions = read_usage(meta.get("worktree", ""))
    cost, unknown = cost_of(models)
    json.dump({"models": models, "messages": messages, "first": first, "last": last,
               "sessions": sessions, "cost": cost, "unknown": unknown,
               "snapshot_at": datetime.now().isoformat(timespec="seconds")},
              open(os.path.join(d, "ledger.json"), "w"), indent=2)
    print(f"{money(cost)} over {human_tokens(sum(sum(t.values()) for t in models.values()))} tokens")


def main():
    argv = sys.argv[1:]
    if not argv:
        sys.exit(__doc__)
    cmd, rest = argv[0], argv[1:]
    args, key = {}, None
    for token in rest:
        if token.startswith("--"):
            key = token[2:]
            args[key] = True
        elif key:
            args[key] = token
            key = None
        else:
            args["slug"] = token
    return {"cost": cmd_cost, "log": cmd_log, "retro": cmd_retro, "costs": cmd_costs,
            "snapshot": cmd_snapshot}[cmd](args)


if __name__ == "__main__":
    main()
