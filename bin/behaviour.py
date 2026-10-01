#!/usr/bin/env python3
"""The behaviour check: an independent validator that never reads the code.

  behaviour.py run <slug>       start a separate Claude run that drives the running app through the
                                quest's scenarios and writes quests/<slug>/behaviour.json
  behaviour.py status <slug>    why the trial may not pass yet (nothing printed: fine), exit 1 if not
  behaviour.py audit <log>      the commands in a session log that read code (used after each run)

The reviewer agent and the project checks both look at what the implementing agent wrote, so a test
that passes against a mock, or a stub that hides a defect, gets past both. This validator only sees
the scenarios (in its prompt), starts the app from the quest's worktree and judges what the running
app does against the real local API. Its file tools are switched off and it starts in an empty
folder; afterwards guild reads its own session log, and a run that looked at a diff or opened a
source file is marked tainted and does not count. Mock modes (MSW, VITE_LOCAL_MODE, stubs) are
"blocked", never "pass".

behaviour.json: {"sha": <commit it ran on>, "at", "results": [{"id", "verdict": pass|fail|blocked,
"observed"}], "tainted": [commands], "session": <id>}. The trial needs one for the current commit with
no fail and no taint (`guild trial pass --no-behaviour "<why>"` is the recorded way out).
"""
import json
import os
import re
import subprocess
import sys
import time
import uuid

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
PROJECTS = os.environ.get("GUILD_CLAUDE_PROJECTS", os.path.expanduser("~/.claude/projects"))
CLAUDE = os.environ.get("GUILD_BEHAVIOUR_CLAUDE", "claude")

# Reading code through the shell: a diff or history, or a pager/printer/search pointed at source files.
CODE_READ = [
    re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:diff|show|log\s+.*-p|log\s+.*--patch|blame)\b"),
    re.compile(r"\b(?:cat|less|more|head|tail|sed|awk|grep|rg|ag|bat|vim?|nano|nl|view)\b[^|;&]*"
               r"(?:/src/|\.java\b|\.kt\b|\.tsx?\b|\.jsx?\b|\.py\b|\.go\b|\.rb\b|\.sql\b|\.vue\b)"),
]
MOCK = re.compile(r"VITE_LOCAL_MODE=true|\bmsw\b|mock mode|--mock\b", re.I)

PROMPT = """You are an independent behaviour validator for a code change. You never read the code: not the
source files, not the tests, not the diff, not the git history. You judge only what the RUNNING app does.

The code is checked out at: {worktree}
Do not open, print, search or diff anything in that folder. You may run the app's start scripts from it
(for example `cd {worktree} && ./scripts/up`), call its HTTP API, query its local database with the client
the setup shows, and take screenshots with `guild shot <url> --name <name>`.

Rules:
- Use the real local API only. If a step needs a mock (MSW, VITE_LOCAL_MODE=true, a stub server), do not
  run it: mark that scenario "blocked" with the reason.
- Skip git fetch/switch/checkout steps in the setup: the folder above already has the commit under test.
- Run the scenarios in order; earlier groups create data later ones read.
- For each scenario, compare what you observe with its Expect. "pass" only when every part of Expect holds.
  "fail" when any part does not, and say exactly what you saw instead. "blocked" when you cannot run it
  (a person must look at a screen, a mock would be needed, the app does not start): say why.
- Stop the stack you started when you are done, if the setup has a stop script.

When you finish, your LAST message must be only this JSON, nothing before or after it:
{{"results": [{{"id": "A1", "verdict": "pass|fail|blocked", "observed": "what you saw, one or two sentences"}}]}}

The setup and the scenarios:
{scenarios}
"""


def qdir(slug):
    return os.path.join(QUESTS, slug)


def meta_of(slug):
    return json.load(open(os.path.join(qdir(slug), "meta.json")))


def head(worktree):
    return subprocess.run(["git", "-C", worktree, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def audit(log_path):
    """Every tool call in a session log that read code, as short strings."""
    found = []
    try:
        lines = open(log_path, errors="ignore").read().splitlines()
    except OSError:
        return ["the validator's session log is missing, so its independence cannot be checked"]
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") != "assistant":
            continue
        for block in (row.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name, inp = block.get("name", ""), block.get("input") or {}
            if name in ("Read", "Grep", "Glob", "NotebookRead"):
                found.append(f"{name} {inp.get('file_path') or inp.get('path') or inp.get('pattern', '')}"[:200])
            elif name == "Bash":
                cmd = str(inp.get("command", ""))
                if any(p.search(cmd) for p in CODE_READ):
                    found.append(cmd[:200])
    return found


def scenarios_text(slug):
    spec = json.load(open(os.path.join(qdir(slug), "scenarios.json")))
    keep = {k: spec[k] for k in ("title", "setup", "groups", "gaps") if k in spec}
    return json.dumps(keep, indent=1)


def run(slug):
    meta = meta_of(slug)
    wt = meta.get("worktree", "")
    if not os.path.exists(os.path.join(qdir(slug), "scenarios.json")):
        raise SystemExit("behaviour: write scenarios.json first (war-table skill, \"Validation scenarios\")")
    sha = head(wt)
    work = os.path.join(qdir(slug), "behaviour-run")
    os.makedirs(work, exist_ok=True)
    sid = str(uuid.uuid4())
    prompt = PROMPT.format(worktree=wt, scenarios=scenarios_text(slug))
    cmd = [CLAUDE, "-p", prompt, "--session-id", sid, "--model", os.environ.get("GUILD_BEHAVIOUR_MODEL", "sonnet"),
           "--output-format", "json", "--allowedTools", "Bash",
           "--disallowedTools", "Read", "Grep", "Glob", "Edit", "Write", "NotebookEdit", "WebFetch",
           "Bash(git diff:*)", "Bash(git show:*)", "Bash(git log:*)", "Bash(git blame:*)"]
    env = dict(os.environ)
    env.pop("GUILD_QUEST", None)                      # not the quest's agent: no quest hooks, no quest identity
    print(f"behaviour check for {slug} on {sha[:8]}: a separate Claude run that cannot read the code. This takes a few minutes.")
    proc = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=int(os.environ.get("GUILD_BEHAVIOUR_TIMEOUT", "2400")))
    text = proc.stdout
    try:
        text = json.loads(proc.stdout).get("result", proc.stdout)
    except ValueError:
        pass
    m = re.search(r"\{\s*\"results\"\s*:.*\}\s*$", text.strip(), re.S)
    try:
        results = json.loads(m.group(0))["results"] if m else []
    except ValueError:
        results = []
    # Claude names the folder after the real path (/var is /private/var on macOS): find the log by its id
    import glob
    logs = glob.glob(os.path.join(PROJECTS, "*", f"{sid}.jsonl"))
    log = logs[0] if logs else os.path.join(PROJECTS, os.path.realpath(work).replace("/", "-").replace(".", "-"), f"{sid}.jsonl")
    tainted = audit(log)
    for r in results:                                  # a pass that leaned on a mock is not a pass
        if r.get("verdict") == "pass" and MOCK.search(str(r.get("observed", ""))):
            r["verdict"], r["observed"] = "blocked", "used a mock: " + str(r.get("observed", ""))
    out = {"sha": sha, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": results, "tainted": tainted, "session": sid,
           "error": "" if results else (proc.stderr.strip()[-400:] or "the validator returned no results")}
    json.dump(out, open(os.path.join(qdir(slug), "behaviour.json"), "w"), indent=2)
    counts = {v: sum(1 for r in results if r.get("verdict") == v) for v in ("pass", "fail", "blocked")}
    with open(os.path.join(GUILD_HOME, "events.log"), "a") as f:
        f.write(f"{out['at']}\t{slug}\tbehaviour\t{counts['pass']} pass, {counts['fail']} fail, {counts['blocked']} blocked on {sha[:8]}"
                + (" (TAINTED)" if tainted else "") + "\n")
    for r in results:
        print(f"  {r.get('id', '?'):>4} {r.get('verdict', '?'):<8} {r.get('observed', '')}")
    print(f"{counts['pass']} pass, {counts['fail']} fail, {counts['blocked']} blocked" + (f"; TAINTED: {tainted}" if tainted else ""))
    if out["error"]:
        print("no results: " + out["error"])


def status(slug, sha):
    """Why the behaviour check does not let the trial pass yet, or "" when it does."""
    path = os.path.join(qdir(slug), "behaviour.json")
    if not os.path.exists(os.path.join(qdir(slug), "scenarios.json")):
        return ""                                        # no scenarios, nothing to drive (guild status done asks for them)
    if not os.path.exists(path):
        return "no behaviour check yet: run `guild behaviour` (an independent validator drives the app; it never reads the code)"
    b = json.load(open(path))
    if b.get("sha") != sha:
        return f"the behaviour check ran on {b.get('sha', '')[:8]} but HEAD is {sha[:8]}: run `guild behaviour` again"
    if b.get("tainted"):
        return "the behaviour check looked at the code, so it is not independent: run `guild behaviour` again"
    if not b.get("results"):
        return "the behaviour check returned no results: " + (b.get("error") or "run it again")
    fails = [r for r in b["results"] if r.get("verdict") == "fail"]
    if fails:
        return "the behaviour check failed " + ", ".join(f"{r.get('id')} ({r.get('observed', '')[:80]})" for r in fails)
    return ""


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        raise SystemExit(__doc__)
    if a[0] == "run":
        run(a[1])
    elif a[0] == "status":
        why = status(a[1], a[2] if len(a) > 2 else head(meta_of(a[1]).get("worktree", "")))
        if why:
            print(why)
            sys.exit(1)
    elif a[0] == "audit":
        for f in audit(a[1]):
            print(f)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
