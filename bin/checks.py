#!/usr/bin/env python3
"""Acceptance as commands: the evaluation half of guild.

A brief's Acceptance block can hold checks, one per line:

    Acceptance:
    - check: ./mvnw -q test -Dtest=RateValueIT
    - check: curl -sf localhost:8080/health
    - the list shows dated history              <- no command: a manual criterion

When a quest starts, guild seals those lines into acceptance.json and records a hash.
The adventurer runs them; it cannot quietly rewrite them, because a changed file no
longer matches the hash and guild refuses to run it. Every run is kept in checks.jsonl,
which is what lets the retro measure first-pass rate per model and spot weak checks
(ones that already passed before any work was done).

    checks.py seal <quest-dir>                 parse the brief, write acceptance.json
    checks.py run <quest-dir> <worktree> [--baseline] [--timeout S]
    checks.py status <quest-dir> <sha>         green for this commit? (exit 0/1)
    checks.py reseal <quest-dir>               accept a changed brief (the guildmaster's call)
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def parse_brief(text):
    """Bullets under 'Acceptance:' until the next 'Word:' header at column 0."""
    items, inside = [], False
    for line in text.splitlines():
        if re.match(r"^Acceptance\s*:", line, re.I):
            inside = True
            rest = line.split(":", 1)[1].strip()
            if rest:
                items.append(rest)
            continue
        if inside and re.match(r"^[A-Z][A-Za-z ]{1,30}:", line):
            break
        if inside:
            bullet = re.sub(r"^\s*(?:[-*]|\d+\.)\s*", "", line).strip()
            if bullet:
                items.append(bullet)
    out = []
    for item in items:
        m = re.match(r"^check\s*:\s*(.+)$", item, re.I)
        out.append({"kind": "check", "run": m.group(1).strip()} if m else {"kind": "manual", "text": item})
    return out


# Pins guild copies into a worktree on purpose; they are untracked and never count as changes.
PINS = set((os.environ.get("GUILD_TOOLCHAIN_PINS") or
            ".java-version .nvmrc .node-version .tool-versions .python-version .ruby-version .sdkmanrc").split())


def is_dirty(worktree):
    out = subprocess.run(["git", "-C", worktree, "status", "--porcelain"], capture_output=True, text=True).stdout
    return any(line and not (line.startswith("?? ") and line[3:].strip() in PINS) for line in out.splitlines())


def digest(items):
    return hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()[:16]


def load_contract(qdir):
    path = os.path.join(qdir, "acceptance.json")
    if not os.path.exists(path):
        return None
    data = json.load(open(path))
    meta = json.load(open(os.path.join(qdir, "meta.json")))
    if meta.get("acceptance_hash") and digest(data["items"]) != meta["acceptance_hash"]:
        raise SystemExit(f"{RED}guild check: acceptance.json changed since the quest started.{RESET}\n"
                         "Only the guildmaster changes acceptance: edit the brief, then `guild check --reseal <slug>`.")
    return data


def cmd_seal(qdir):
    items = parse_brief(open(os.path.join(qdir, "brief.md")).read())
    json.dump({"items": items, "sealed_at": now()}, open(os.path.join(qdir, "acceptance.json"), "w"), indent=2)
    meta_path = os.path.join(qdir, "meta.json")
    meta = json.load(open(meta_path))
    meta["acceptance_hash"] = digest(items)
    json.dump(meta, open(meta_path, "w"), indent=2)
    checks = sum(1 for i in items if i["kind"] == "check")
    print(f"acceptance: {checks} check(s), {len(items) - checks} manual")


def cmd_reseal(qdir):
    cmd_seal(qdir)


def cmd_run(qdir, worktree, baseline, timeout):
    contract = load_contract(qdir)
    if not contract or not any(i["kind"] == "check" for i in contract["items"]):
        print("no acceptance checks in this quest's brief")
        return 0
    sha = subprocess.run(["git", "-C", worktree, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = is_dirty(worktree)
    results = []
    print(f"{BOLD}{'baseline ' if baseline else ''}checks on {sha[:8]}{' (uncommitted changes)' if dirty else ''}{RESET}")
    for item in contract["items"]:
        if item["kind"] == "manual":
            results.append({"kind": "manual", "text": item["text"], "status": "manual"})
            print(f"  {DIM}manual{RESET}  {item['text']}")
            continue
        start = time.time()
        try:
            r = subprocess.run(["bash", "-c", item["run"]], cwd=worktree, capture_output=True, text=True, timeout=timeout)
            status = "pass" if r.returncode == 0 else "fail"
            tail = (r.stdout + r.stderr)[-600:]
        except subprocess.TimeoutExpired:
            status, tail = "timeout", f"no result after {timeout}s"
        secs = round(time.time() - start, 1)
        results.append({"kind": "check", "run": item["run"], "status": status, "seconds": secs, "tail": tail})
        color = GREEN if status == "pass" else RED
        print(f"  {color}{status:<7}{RESET} {item['run']}  {DIM}{secs}s{RESET}")
        if status != "pass" and not baseline:
            for line in tail.strip().splitlines()[-4:]:
                print(f"          {DIM}{line[:120]}{RESET}")
    run = {"at": now(), "sha": sha, "dirty": dirty, "baseline": baseline, "results": results}
    with open(os.path.join(qdir, "checks.jsonl"), "a") as f:
        f.write(json.dumps(run) + "\n")
    checks = [r for r in results if r["kind"] == "check"]
    passed = sum(1 for r in checks if r["status"] == "pass")
    green = passed == len(checks)
    if baseline:
        weak = [r["run"] for r in checks if r["status"] == "pass"]
        if weak:
            print(f"{RED}weak:{RESET} these already pass before any work, so they prove nothing about it:")
            for w in weak:
                print(f"  {w}")
        print(f"baseline recorded ({passed}/{len(checks)} already green)")
        print(f"__EVENT__\tchecks-baseline\t{passed}/{len(checks)} already green" + (f", {len(weak)} weak" if weak else ""))
        return 0
    print(f"{GREEN if green else RED}{passed}/{len(checks)} green{RESET}")
    print(f"__EVENT__\tchecks-{'green' if green else 'red'}\t{passed}/{len(checks)} on {sha[:8]}")
    return 0 if green else 1


def cmd_status(qdir, sha):
    """Exit 0 when there are no checks, or the last real run on this commit was all green."""
    contract = load_contract(qdir)
    if not contract or not any(i["kind"] == "check" for i in contract["items"]):
        return 0
    path = os.path.join(qdir, "checks.jsonl")
    runs = [json.loads(l) for l in open(path)] if os.path.exists(path) else []
    real = [r for r in runs if not r["baseline"]]
    if not real:
        print("no check run yet: run `guild check`")
        return 1
    last = real[-1]
    if last["sha"] != sha or last.get("dirty"):
        print(f"the last check run was on {last['sha'][:8]}{' with uncommitted changes' if last.get('dirty') else ''}, "
              f"HEAD is {sha[:8]}: run `guild check` again")
        return 1
    bad = [r for r in last["results"] if r["kind"] == "check" and r["status"] != "pass"]
    if bad:
        print(f"{len(bad)} acceptance check(s) still failing: run `guild check`")
        return 1
    return 0


def summarize(qdir):
    """For the ledger: first-pass, runs to green, weak checks."""
    path = os.path.join(qdir, "checks.jsonl")
    contract_path = os.path.join(qdir, "acceptance.json")
    if not os.path.exists(contract_path):
        return {}
    items = json.load(open(contract_path)).get("items", [])
    checks = [i for i in items if i["kind"] == "check"]
    if not checks:
        return {"checks": 0, "manual": len(items)}
    runs = [json.loads(l) for l in open(path)] if os.path.exists(path) else []
    base = [r for r in runs if r["baseline"]]
    real = [r for r in runs if not r["baseline"]]

    def green(r):
        return all(x["status"] == "pass" for x in r["results"] if x["kind"] == "check")

    runs_to_green = next((n for n, r in enumerate(real, 1) if green(r)), None)
    weak = sorted({x["run"] for r in base for x in r["results"] if x["kind"] == "check" and x["status"] == "pass"})
    return {"checks": len(checks), "manual": len(items) - len(checks), "baselined": bool(base),
            "runs": len(real), "runs_to_green": runs_to_green,
            "first_pass": (runs_to_green == 1) if real else None, "weak": weak,
            "last_green": green(real[-1]) if real else None}


def main():
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    cmd = a[0]
    if cmd == "seal":
        return cmd_seal(a[1])
    if cmd == "reseal":
        return cmd_reseal(a[1])
    if cmd == "run":
        baseline = "--baseline" in a
        timeout = int(a[a.index("--timeout") + 1]) if "--timeout" in a else 900
        sys.exit(cmd_run(a[1], a[2], baseline, timeout))
    if cmd == "status":
        sys.exit(cmd_status(a[1], a[2]))
    if cmd == "summary":
        print(json.dumps(summarize(a[1])))
        return
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
