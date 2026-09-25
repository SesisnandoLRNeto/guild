#!/usr/bin/env python3
"""The real state of each quest's pull request, from GitHub, for the campaign board.

  prs.py refresh [--force]   ask GitHub about every quest's PR (cached ~2 minutes)
  prs.py show                one line per PR

A quest's PR is the last pull request link in its status note or its events. GitHub is
asked with the account that owns the repo (local/identities.json), so work PRs are read
with the work account. Nothing is ever written to GitHub.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
CACHE = os.path.join(GUILD_HOME, ".pr-cache.json")
TTL = 150
PR = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)")


def load_json(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def cache():
    return load_json(CACHE, {})


def quest_prs(days=7):
    """{slug: pr url} for live quests and those closed in the last week."""
    events = {}
    try:
        for line in open(os.path.join(GUILD_HOME, "events.log")):
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 4:
                m = PR.search(parts[3])
                if m:
                    events[parts[1]] = m.group(0)
    except OSError:
        pass
    out, cutoff = {}, time.time() - days * 86400
    dirs = [d for d in glob.glob(os.path.join(QUESTS, "*")) if not d.endswith("_archive")]
    dirs += [d for d in glob.glob(os.path.join(QUESTS, "_archive", "*")) if os.path.getmtime(d) > cutoff]
    for d in dirs:
        meta = load_json(os.path.join(d, "meta.json"), None)
        if not meta or meta.get("pseudo"):
            continue
        slug = meta.get("slug", os.path.basename(d))
        note = ""
        try:
            note = open(os.path.join(d, "status")).read().split("\t")[1]
        except (OSError, IndexError):
            pass
        m = PR.search(note)
        url = m.group(0) if m else events.get(slug)
        if url:
            out[slug] = url
    return out


def token_for(owner):
    ids = load_json(os.path.join(GUILD_HOME, "local", "identities.json"), {})
    user = (ids.get(owner) or ids.get("*") or {}).get("gh_user")
    if not user:
        return None
    r = subprocess.run(["gh", "auth", "token", "--user", user], capture_output=True, text=True, timeout=10)
    return r.stdout.strip() or None


def checks(rollup):
    states = [(c.get("conclusion") or c.get("state") or "").upper() for c in rollup or []]
    if not states:
        return ""
    if any(s in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED") for s in states):
        return "failing"
    if any(s in ("", "PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED") for s in states):
        return "running"
    return "passing"


def fetch(url):
    owner = PR.search(url).group(1)
    env = dict(os.environ)
    token = token_for(owner)
    if token:
        env["GH_TOKEN"] = token
    r = subprocess.run(["gh", "pr", "view", url, "--json", "state,isDraft,reviewDecision,mergedAt,title,statusCheckRollup"],
                       capture_output=True, text=True, timeout=30, env=env)
    if r.returncode:
        return {"error": (r.stderr or "gh failed").strip()[:200], "at": time.time()}
    d = json.loads(r.stdout)
    state = "merged" if d.get("mergedAt") else ("draft" if d.get("isDraft") and d["state"] == "OPEN" else d["state"].lower())
    review = {"APPROVED": "approved", "CHANGES_REQUESTED": "changes requested", "REVIEW_REQUIRED": "review required"}.get(
        d.get("reviewDecision") or "", "")
    return {"state": state, "review": review, "checks": checks(d.get("statusCheckRollup")), "title": d.get("title", ""),
            "number": int(PR.search(url).group(3)), "at": time.time()}


def refresh(force=False):
    c = cache()
    for slug, url in quest_prs().items():
        entry = c.get(url)
        if force or not entry or time.time() - entry.get("at", 0) > TTL:
            try:
                c[url] = fetch(url)
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                c[url] = {"error": str(e)[:200], "at": time.time()}
        c[url]["slug"] = slug
    tmp = CACHE + ".tmp"
    json.dump(c, open(tmp, "w"), indent=1)
    os.replace(tmp, CACHE)
    return c


def by_slug():
    """{slug: pr info with url} from the cache, for fleet.py. Never calls GitHub."""
    out = {}
    for url, info in cache().items():
        if info.get("slug"):
            out[info["slug"]] = dict(info, url=url)
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "refresh":
        refresh(force="--force" in sys.argv)
    elif cmd == "show":
        refresh()
        for slug, p in sorted(by_slug().items()):
            if p.get("error"):
                print(f"{slug:<28} {p['url']}  (could not read: {p['error']})")
            else:
                extra = ", ".join(x for x in (p["review"], "checks " + p["checks"] if p["checks"] else "") if x)
                print(f"{slug:<28} PR #{p['number']:<5} {p['state']:<7} {extra}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
