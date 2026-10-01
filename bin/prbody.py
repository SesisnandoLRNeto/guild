#!/usr/bin/env python3
"""The part of a PR description guild writes: the sealed contract and what proved it, for HEAD.

  prbody.py build <slug>              the section to paste into the PR body (guild pr-body)
  prbody.py verify <slug> <bodyfile>  exit 1 with the reason when the body lacks a current section

Hand-written PR descriptions drift: they list tickets that left the branch, name classes the code
no longer uses, point at closed PRs. This section is generated from the acceptance contract sealed
when the quest started (not from memory after the fact) and from the results on the exact commit
being opened: each acceptance check and its run, the independent behaviour check, and the
validation checklist. `gh pr create` inside a quest requires it, with the current contract hash and
HEAD, so it cannot go stale before the PR exists. The adventurer writes the rest of the body.
"""
import json
import os
import re
import subprocess
import sys

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
MARK = re.compile(r"<!-- guild:contract hash=(\S*) head=(\S+) -->")


def load(path, default=None):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def head(worktree):
    return subprocess.run(["git", "-C", worktree, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def build(slug):
    q = os.path.join(QUESTS, slug)
    meta = load(os.path.join(q, "meta.json"), {})
    sha = head(meta.get("worktree", ""))
    contract = load(os.path.join(q, "acceptance.json"), {"items": []})
    runs = []
    if os.path.exists(os.path.join(q, "checks.jsonl")):
        runs = [json.loads(l) for l in open(os.path.join(q, "checks.jsonl")) if l.strip()]
    last = next((r for r in reversed(runs) if not r.get("baseline") and r.get("sha") == sha), None)
    status = {r.get("run"): r.get("status") for r in (last or {}).get("results", []) if r.get("kind") == "check"}
    hsh = meta.get("acceptance_hash", "")
    out = [f"<!-- guild:contract hash={hsh} head={sha} -->",
           f"## Acceptance (sealed when the quest started{f', {hsh[:8]}' if hsh else ''})"]
    items = contract.get("items", [])
    if not items:
        out.append(f"No acceptance contract: {meta.get('no_acceptance') or 'none was written'}.")
    for i in items:
        if i["kind"] == "check":
            st = status.get(i["run"])
            out.append(f"- [{'x' if st == 'pass' else ' '}] `{i['run']}`: " + (f"{st} on {sha[:8]}" if st else "not run on this commit"))
        else:
            out.append(f"- [ ] {i['text']} (checked by a person on the validation checklist)")
    b = load(os.path.join(q, "behaviour.json"))
    out.append("\n## Behaviour check (an independent validator drove the running app; it never read the code)")
    if not b:
        out.append("Not run.")
    elif b.get("sha") != sha:
        out.append(f"Ran on {b.get('sha', '')[:8]}, not on this commit.")
    else:
        for r in b.get("results", []):
            out.append(f"- {r.get('id')}: **{r.get('verdict')}**. {r.get('observed', '')}")
        if b.get("tainted"):
            out.append("This run looked at the code, so it does not count.")
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import scenarios
    s = scenarios.summary(slug)
    if s.get("exists"):
        out.append("\n## Validation checklist")
        out.append(f"{s['total']} scenarios; the guildmaster's run: {s['pass']} passed, {s['fail']} failed, "
                   f"{s['skip']} skipped, {s['open']} not run yet" + (" (certified for this commit)." if s.get("certified") else "."))
    trial = load(os.path.join(q, "trial.json"))
    if trial and trial.get("result") == "skip":
        out.append(f"\nTrial: skipped - {trial.get('note', '')}")
    out.append("<!-- /guild:contract -->")
    return "\n".join(out)


def verify(slug, body):
    q = os.path.join(QUESTS, slug)
    meta = load(os.path.join(q, "meta.json"), {})
    m = MARK.search(body or "")
    if not m:
        return "the PR body has no guild contract section: run `guild pr-body` and put its output in the body"
    if m.group(1) != meta.get("acceptance_hash", ""):
        return "the PR body's contract section is for another acceptance contract: run `guild pr-body` again"
    sha = head(meta.get("worktree", ""))
    if m.group(2) != sha:
        return f"the PR body's contract section was made on {m.group(2)[:8]} but HEAD is {sha[:8]}: run `guild pr-body` again"
    return ""


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "build":
        print(build(a[1]))
    elif len(a) >= 3 and a[0] == "verify":
        why = verify(a[1], open(a[2]).read() if os.path.exists(a[2]) else "")
        if why:
            print(why)
            sys.exit(1)
    else:
        raise SystemExit(__doc__)
