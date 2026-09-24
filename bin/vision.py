#!/usr/bin/env python3
"""The evidence behind a repo's vision.

A vision is only worth having if every principle in it points at something the team
actually did: a PR it merged, a PR it declined, a change it reverted. This collects that
evidence; the `vision` skill turns it into principles and hard questions, and the
guildmaster answers them on the war table.

Visions live in ~/.guild/visions/<repo>.md, never inside the repo: they are yours until
you decide to share one.

    vision.py evidence <repo-path> [--limit 200] [--min 20]
    vision.py status <repo-name>
"""
import datetime
import json
import os
import subprocess
import sys

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
VISIONS = os.path.join(GUILD_HOME, "visions")


def gh_json(repo, *args):
    r = subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"vision: gh failed: {r.stderr.strip()[:300]}")
    try:
        return json.loads(r.stdout or "[]")
    except ValueError:
        raise SystemExit(f"vision: gh returned something that is not JSON: {r.stdout[:200]}")


def short(text, n=400):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def cmd_evidence(repo, limit, minimum):
    name = os.path.basename(os.path.abspath(repo))
    fields = "number,title,body,mergedAt,closedAt,url,labels"
    merged = gh_json(repo, "pr", "list", "--state", "merged", "--limit", str(limit), "--json", fields)
    closed = gh_json(repo, "pr", "list", "--state", "closed", "--limit", str(limit), "--json", fields)
    declined = [p for p in closed if not p.get("mergedAt")]
    log = subprocess.run(["git", "-C", repo, "log", "--grep=^Revert", "-i", "--format=%h%x09%ad%x09%s",
                          "--date=short", "-50"], capture_output=True, text=True).stdout
    reverts = [dict(zip(("sha", "date", "subject"), l.split("\t", 2))) for l in log.splitlines() if l.strip()]

    if len(merged) < minimum:
        raise SystemExit(f"vision: only {len(merged)} merged PRs in {name}; that is too little history to find "
                         f"real values (need {minimum}). A vision invented from so little would be guesswork.")

    os.makedirs(VISIONS, exist_ok=True)
    data = {"repo": name, "path": os.path.abspath(repo), "collected": datetime.date.today().isoformat(),
            "merged": [{"n": p["number"], "title": p["title"], "merged": (p.get("mergedAt") or "")[:10],
                        "labels": [l["name"] for l in p.get("labels", [])], "body": short(p.get("body"))}
                       for p in merged],
            "declined": [{"n": p["number"], "title": p["title"], "closed": (p.get("closedAt") or "")[:10],
                          "body": short(p.get("body"))} for p in declined],
            "reverts": reverts}
    out = os.path.join(VISIONS, f"{name}.evidence.json")
    json.dump(data, open(out, "w"), indent=2)
    print(out)
    print(f"{len(data['merged'])} merged, {len(data['declined'])} declined, {len(reverts)} reverts")


def cmd_status(name):
    vision = os.path.join(VISIONS, f"{name}.md")
    evidence = os.path.join(VISIONS, f"{name}.evidence.json")
    if os.path.exists(vision):
        first = open(vision).read().splitlines()[:6]
        sealed = any("status: sealed" in l.lower() for l in first)
        print(f"{vision} ({'sealed' if sealed else 'draft'})")
    elif os.path.exists(evidence):
        print(f"no vision yet; evidence collected: {evidence}")
    else:
        print("no vision and no evidence yet: guild vision <repo path>")


def main():
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    if a[0] == "evidence":
        limit = int(a[a.index("--limit") + 1]) if "--limit" in a else 200
        minimum = int(a[a.index("--min") + 1]) if "--min" in a else 20
        return cmd_evidence(a[1], limit, minimum)
    if a[0] == "status":
        return cmd_status(a[1])
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
