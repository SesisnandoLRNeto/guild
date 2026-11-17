#!/usr/bin/env python3
"""Bug quests: a failing command before a fix (guild repro).

  guild repro new --cmd "<repro>" [--with <path>]... [--force]   record the repro and run it: it must fail today
  guild repro facts [--trigger T] [--condition C] [--symptom S] [--difference D]
  guild repro compare [--ref <ref>] [--cmd "<variant>"] [--label L]   the repro (or a variant) on another
                                                    commit (temporary worktree) or with another input
  guild repro bisect --good <ref> [--bad <ref>]     first commit where the repro fails (temporary worktree)
  guild repro theory "<theory>" --check "<cmd>" --expect pass|fail [--ref <ref>]
                                                    a check that could prove the theory wrong
  guild repro verify                               the repro on the current tree: after the fix it must pass
  guild repro report                               the diagnosis block, Markdown (plan page, wrap-up, PR body)
  guild repro cleanup                              remove temporary worktrees left by a crash

Inside a quest (GUILD_QUEST). The repro is a shell command that exits non-zero while the bug is
there and 0 when it is gone. --with names files or folders (relative to the worktree) copied into
each temporary worktree, for example a new test that older commits do not have. State lives in
the quest folder, repro.json. Temporary worktrees live in the system temp folder and are removed
after every run, also on errors, with any bisect state.

Called by guild itself, not by an adventurer:
  rootcause.py ready <slug>          what the plan board still misses (exit 1), or nothing
  rootcause.py gate <slug> <sha>     the trial's bug check: failed before, passes on this commit (exit 1)
  rootcause.py _approve <slug> <by>  the guildmaster approved the plan: their yes to the fix
"""
import argparse
import contextlib
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
WT_PREFIX = "guild-repro-"
TIMEOUT = int(os.environ.get("GUILD_REPRO_TIMEOUT", "600"))
PROBE = "_probe"


def now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.returncode, (r.stdout.strip() if r.returncode == 0 else r.stderr.strip())


def qdir(slug):
    return os.path.join(QUESTS, slug)


def meta(slug):
    try:
        return json.load(open(os.path.join(qdir(slug), "meta.json")))
    except (OSError, ValueError):
        return {}


def current():
    slug = os.environ.get("GUILD_QUEST", "")
    if not slug or not os.path.isdir(qdir(slug)):
        raise SystemExit("guild repro runs inside a quest (GUILD_QUEST not set)")
    return slug


def root(slug):
    wt = meta(slug).get("worktree", "")
    if wt and os.path.isdir(wt):
        return wt
    code, top = git("rev-parse", "--show-toplevel")
    if code:
        raise SystemExit("not inside a git repository")
    return top


def head(cwd):
    return git("rev-parse", "HEAD", cwd=cwd)[1]


def dirty(cwd):
    return bool(git("status", "--porcelain", cwd=cwd)[1])


def state_path(slug):
    return os.path.join(qdir(slug), "repro.json")


def load(slug, must=True):
    try:
        return json.load(open(state_path(slug)))
    except (OSError, ValueError):
        if must:
            raise SystemExit("no repro recorded: start with `guild repro new --cmd \"<a command that fails today>\"`")
        return None


def save(slug, data):
    with open(state_path(slug), "w") as f:
        json.dump(data, f, indent=2)


def run(cmd, cwd, timeout=TIMEOUT):
    """Run a shell command. Returns (status, exit code, last lines of output)."""
    try:
        r = subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return ("pass" if r.returncode == 0 else "fail"), r.returncode, (r.stdout + r.stderr)[-1200:]
    except subprocess.TimeoutExpired:
        return "timeout", None, f"no result after {timeout}s"


def show_tail(tail, n=6):
    lines = [l for l in tail.splitlines() if l.strip() and not re.match(r"^[-=]{10,}$", l.strip())]
    for line in lines[-n:]:
        print(f"    | {line[:150]}")


def copy_in(files, src, dst):
    """Put the repro's extra files into a worktree. Returns what was added, so it can be undone."""
    added = []
    for rel in files:
        s, d = os.path.join(src, rel), os.path.join(dst, rel)
        if not os.path.exists(s):
            raise SystemExit(f"--with {rel}: not found in {src}")
        if os.path.isdir(s):
            if os.path.lexists(d):
                continue                          # the commit has its own copy: leave it
            os.makedirs(os.path.dirname(d) or dst, exist_ok=True)
            os.symlink(s, d)
            added.append(("link", rel))
        else:
            os.makedirs(os.path.dirname(d) or dst, exist_ok=True)
            shutil.copy2(s, d)
            added.append(("file", rel))
    return added


def undo_copy(added, wt):
    for kind, rel in added:
        d = os.path.join(wt, rel)
        if kind == "link":
            os.unlink(d)
        elif git("ls-files", "--error-unmatch", "--", rel, cwd=wt)[0] == 0:
            git("checkout", "--", rel, cwd=wt)     # tracked at this commit: restore its version
        else:
            os.remove(d)


@contextlib.contextmanager
def worktree(top, ref):
    """A detached worktree at <ref> in the temp folder, always removed afterwards, bisect state with it.
    Not a pool slot: a slot keeps a quest's warm build cache, and a bisect jumps across old commits."""
    code, sha = git("rev-parse", "--verify", "--quiet", ref + "^{commit}", cwd=top)
    if code:
        raise SystemExit(f"unknown ref: {ref}")
    tmp = tempfile.mkdtemp(prefix=WT_PREFIX)
    wt = os.path.join(tmp, "wt")
    code, err = git("worktree", "add", "--detach", wt, sha, cwd=top)
    if code:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SystemExit(f"could not create a worktree at {ref}: {err}")
    try:
        yield wt, sha
    finally:
        if os.path.exists(os.path.join(wt, ".git")):
            git("bisect", "reset", cwd=wt)
        git("worktree", "remove", "--force", wt, cwd=top)
        shutil.rmtree(tmp, ignore_errors=True)
        git("worktree", "prune", cwd=top)


def run_at(top, data, cmd, ref=None):
    """Run cmd on the quest's tree, or on <ref> in a temporary worktree. Returns a result dict."""
    if not ref:
        status, code, tail = run(cmd, top)
        return {"ref": None, "sha": head(top), "dirty": dirty(top), "status": status, "exit": code, "tail": tail}
    with worktree(top, ref) as (wt, sha):
        copy_in(data["repro"].get("with", []), top, wt)
        status, code, tail = run(cmd, wt)
    return {"ref": ref, "sha": sha, "dirty": False, "status": status, "exit": code, "tail": tail}


def where(r):
    base = f"`{r['ref']}` ({r['sha'][:8]})" if r.get("ref") else f"the quest worktree on `{r['sha'][:8]}`"
    return base + (" + uncommitted changes" if r.get("dirty") else "")


# ---------------------------------------------------------------- the adventurer's commands

def cmd_new(a):
    slug = current()
    top = root(slug)
    if load(slug, must=False) and not a.force:
        raise SystemExit("a repro is already recorded for this quest; --force starts it again")
    missing = [w for w in (a.with_ or []) if not os.path.exists(os.path.join(top, w))]
    if missing:
        raise SystemExit("--with path not found: " + ", ".join(missing))
    data = {"slug": slug, "created_at": now(), "repro": {"cmd": a.cmd, "with": a.with_ or []}, "first_fail": None,
            "facts": {}, "comparisons": [], "bisect": None, "theories": [], "approval": None, "verify": []}
    r = run_at(top, data, a.cmd)
    print(f"repro on {where(r)}: {r['status'].upper()} (exit {r['exit']})")
    show_tail(r["tail"], 10)
    if r["status"] != "fail":
        print("REFUSED: the repro does not fail today, so it does not show the bug.\n"
              "Change the input or the assertion until it fails for the reason in the bug report.")
        return 1
    r["at"] = now()
    data["first_fail"] = r
    save(slug, data)
    print("recorded. Read the output above: it must fail for the reported reason, not for a typo or a\n"
          "missing import. Next: `guild repro facts`, then `guild repro compare`.")
    return 0


FACTS = ("trigger", "condition", "symptom", "difference")


def cmd_facts(a):
    slug = current()
    data = load(slug)
    for k in FACTS:
        v = getattr(a, k)
        if v:
            data["facts"][k] = v
    save(slug, data)
    for k in FACTS:
        print(f"  {k:<10} {data['facts'].get(k, '(not recorded)')}")
    return 0


def cmd_compare(a):
    slug = current()
    top, data = root(slug), load(slug)
    if not a.ref and not a.cmd:
        raise SystemExit("compare needs --ref <commit/branch/tag>, --cmd \"<variant>\", or both")
    cmd = a.cmd or data["repro"]["cmd"]
    r = run_at(top, data, cmd, a.ref)
    r.update({"label": a.label or (a.ref and f"repro at {a.ref}") or "variant", "cmd": cmd, "at": now()})
    data["comparisons"].append(r)
    save(slug, data)
    print(f"{r['label']}: {r['status'].upper()} (exit {r['exit']}) on {where(r)}")
    if r["status"] != "pass":
        show_tail(r["tail"], 4)
    if any(c["status"] == "pass" for c in data["comparisons"]):
        print("You have a failing path and a working path. Name the smallest difference:\n"
              "  guild repro facts --difference \"...\"")
    return 0


def cmd_probe(state_file, main_root):
    """Called by `git bisect run` inside the worktree: 0 = good (repro passes), 1 = bad, 125 = skip."""
    data = json.load(open(state_file))
    wt = os.getcwd()
    added = copy_in(data["repro"].get("with", []), main_root, wt)
    try:
        status, _, _ = run(data["repro"]["cmd"], wt)
    finally:
        undo_copy(added, wt)
    return {"pass": 0, "fail": 1}.get(status, 125)


def cmd_bisect(a):
    slug = current()
    top, data = root(slug), load(slug)
    bad = a.bad or "HEAD"
    print(f"checking the ends first: --good {a.good} must pass, --bad {bad} must fail")
    g = run_at(top, data, data["repro"]["cmd"], a.good)
    b = run_at(top, data, data["repro"]["cmd"], bad)
    print(f"  {a.good}: {g['status']}   {bad}: {b['status']}")
    if g["status"] != "pass" or b["status"] != "fail":
        print("REFUSED: bisect needs a good ref where the repro passes and a bad ref where it fails.\n"
              "Use `guild repro compare --ref` to find a ref that passes.")
        if g["status"] != "pass":
            show_tail(g["tail"], 4)
        return 1
    with worktree(top, bad) as (wt, bad_sha):
        code, err = git("bisect", "start", bad_sha, g["sha"], cwd=wt)
        if code:
            raise SystemExit(f"git bisect start failed: {err}")
        r = subprocess.run(["git", "bisect", "run", sys.executable, os.path.abspath(__file__), PROBE,
                            state_path(slug), top], cwd=wt, capture_output=True, text=True)
        out = r.stdout + r.stderr
        m = re.search(r"^([0-9a-f]{40}) is the first bad commit", out, re.M)
    if not m:
        print("bisect did not name a commit (some commits may not build). Last lines:")
        show_tail(out, 10)
        return 1
    sha = m.group(1)
    subject = git("log", "-1", "--format=%s", sha, cwd=top)[1]
    files = git("show", "--name-only", "--format=", sha, cwd=top)[1].splitlines()
    data["bisect"] = {"good": a.good, "good_sha": g["sha"], "bad": bad, "bad_sha": b["sha"],
                      "first_bad": sha, "subject": subject, "files": files, "at": now()}
    data["comparisons"] += [dict(g, label=f"bisect good end {a.good}", cmd=data["repro"]["cmd"], at=now()),
                            dict(b, label=f"bisect bad end {bad}", cmd=data["repro"]["cmd"], at=now())]
    save(slug, data)
    print(f"first commit where the repro fails: {sha[:8]} {subject}")
    print("  files: " + ", ".join(files))
    print("This is where the failure starts, which is not always the cause: the commit can expose an older bug.\n"
          "Read its diff, then test that idea with `guild repro theory`.")
    return 0


def cmd_theory(a):
    slug = current()
    top, data = root(slug), load(slug)
    r = run_at(top, data, a.check, a.ref)
    verdict = "survived" if r["status"] == a.expect else "disproved"
    data["theories"].append({"theory": a.theory, "check": a.check, "expect": a.expect, "got": r["status"],
                             "verdict": verdict, "ref": a.ref, "sha": r["sha"], "dirty": r["dirty"],
                             "exit": r["exit"], "tail": r["tail"], "at": now()})
    save(slug, data)
    print(f"theory: {a.theory}")
    print(f"  check {r['status'].upper()} (predicted {a.expect}) on {where(r)}: {verdict.upper()}")
    show_tail(r["tail"], 4)
    print("Survived one check. That is support, not proof. A second, different check makes it stronger."
          if verdict == "survived" else "Disproved. Keep it in the record and try the next theory.")
    return 0


def cmd_verify(a):
    slug = current()
    top, data = root(slug), load(slug)
    r = run_at(top, data, data["repro"]["cmd"])
    r["at"] = now()
    data["verify"].append(r)
    save(slug, data)
    print(f"repro on {where(r)}: {r['status'].upper()} (exit {r['exit']})")
    if r["status"] != "pass":
        show_tail(r["tail"])
        print("still failing: the bug is not fixed")
        return 1
    if r["dirty"]:
        print("passes, but with uncommitted changes. Commit, then verify again for the trial.")
    return 0


def cmd_cleanup(a):
    top = root(current())
    gone = 0
    for line in git("worktree", "list", "--porcelain", cwd=top)[1].splitlines():
        if line.startswith("worktree ") and WT_PREFIX in line:
            wt = line[len("worktree "):]
            git("bisect", "reset", cwd=wt)
            git("worktree", "remove", "--force", wt, cwd=top)
            shutil.rmtree(os.path.dirname(wt), ignore_errors=True)
            gone += 1
    git("worktree", "prune", cwd=top)
    print(f"removed {gone} leftover worktree(s)")
    return 0


# ---------------------------------------------------------------- what guild reads

def same_code(top, a, b):
    return a == b or git("diff", "--quiet", a, b, cwd=top)[0] == 0


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def report(slug):
    """The diagnosis block, Markdown: shown on the plan board, the wrap-up and the PR body."""
    data = load(slug, must=False)
    if not data:
        return ""
    top = root(slug)
    sha = head(top)
    ff, facts = data.get("first_fail"), data.get("facts", {})
    last = data["verify"][-1] if data["verify"] else None
    missing = "**not recorded**"
    L = ["<!-- guild:diagnosis -->", "## Diagnosis (the bug, proven before the fix)", "",
         f"**Repro:** `{data['repro']['cmd']}`"]
    if data["repro"].get("with"):
        L.append(f"Extra files: {', '.join('`' + w + '`' for w in data['repro']['with'])}")
    L.append("")
    if ff:
        L.append(f"- Before the fix: **failed** (exit {ff['exit']}) on {where(ff)}, {ff['at']}")
    if not last:
        L.append("- After the fix: **not run yet** (`guild repro verify`)")
    elif last["dirty"] or not same_code(top, last["sha"], sha):
        L.append(f"- After the fix: last run was on {where(last)}, HEAD is `{sha[:8]}`: **run verify again**")
    else:
        L.append(f"- After the fix: **{'passes' if last['status'] == 'pass' else 'STILL FAILS'}** on HEAD `{sha[:8]}`")
    L += ["", "**What happens**",
          f"- Trigger: {facts.get('trigger', missing)}",
          f"- Condition (why it does not happen every time): {facts.get('condition', missing)}",
          f"- Symptom: {facts.get('symptom', missing)}", "",
          "**Failing path and working path**"]
    if data["comparisons"]:
        L += ["", "| Path | Command | Where | Result |", "|---|---|---|---|"]
        for c in data["comparisons"]:
            cmd = "repro" if c["cmd"] == data["repro"]["cmd"] else f"`{cell(c['cmd'])}`"
            L.append(f"| {cell(c['label'])} | {cmd} | {where(c)} | {c['status']} |")
        L.append("")
    else:
        L.append("- no comparison recorded")
    if not any(c["status"] == "pass" for c in data["comparisons"]):
        L.append("- **no working path found**: the difference below is a guess")
    L.append(f"- Smallest difference: {facts.get('difference', missing)}")
    bi = data.get("bisect")
    if bi:
        L.append(f"- Bisect ({bi['good']} good, {bi['bad']} bad): first failing commit `{bi['first_bad'][:8]}` "
                 f"\"{cell(bi['subject'])}\" ({', '.join(bi['files'])})")
    L += ["", "**Theories**"]
    if data["theories"]:
        L += ["", "| Theory | Check | Predicted | Got | Verdict |", "|---|---|---|---|---|"]
        for t in data["theories"]:
            at = f" at `{t['ref']}`" if t.get("ref") else ""
            L.append(f"| {cell(t['theory'])} | `{cell(t['check'])}`{at} | {t['expect']} | {t['got']} | {t['verdict']} |")
        n = sum(1 for t in data["theories"] if t["verdict"] == "disproved")
        L += ["", f"{len(data['theories'])} theory check(s), {n} disproved."]
    else:
        L.append("- **none recorded**: the cause is not tested")
    ap = data.get("approval")
    L += ["", f"**Fix approved by the guildmaster:** {ap['by'] + ' (' + ap['at'] + ')' if ap else missing}",
          "<!-- /guild:diagnosis -->"]
    return "\n".join(L)


def ready(slug):
    """What the plan board still misses before the guildmaster can say yes to a fix. Empty when ready."""
    data = load(slug, must=False)
    if not data or not data.get("first_fail"):
        return ["a repro that fails today: guild repro new --cmd \"<command>\""]
    gaps = [f"the {k}: guild repro facts --{k} \"...\"" for k in ("trigger", "condition", "symptom")
            if not data["facts"].get(k)]
    if not data["comparisons"]:
        gaps.append("a failing path against a working one: guild repro compare --ref <older commit> or --cmd \"<other input>\"")
    if not data["theories"]:
        gaps.append("a theory a command could disprove: guild repro theory \"<theory>\" --check \"<cmd>\" --expect pass|fail")
    return gaps


def gate(slug, sha):
    """The trial's bug check. Returns the reason it fails, or ''."""
    data = load(slug, must=False)
    if not data or not data.get("first_fail") or data["first_fail"].get("status") != "fail":
        return "a bug quest needs a repro that failed before the fix: guild repro new --cmd \"<command>\""
    top = root(slug)
    last = data["verify"][-1] if data.get("verify") else None
    if not last or last["dirty"] or not same_code(top, last["sha"], sha):
        return f"the repro has not run on {sha[:8]} with a clean tree: commit, then guild repro verify"
    if last["status"] != "pass":
        return f"the repro still fails on {sha[:8]}: the bug is not fixed"
    return ""


def approve(slug, by):
    data = load(slug, must=False)
    if not data:
        return
    data["approval"] = {"by": by[:300], "at": now(), "sha": head(root(slug))}
    save(slug, data)


def stop(signum, frame):
    raise SystemExit(f"stopped by signal {signum}: temporary worktree removed")


def main():
    signal.signal(signal.SIGTERM, stop)              # so the cleanup in worktree() still runs
    argv = sys.argv[1:]
    if argv[:1] == [PROBE]:
        return cmd_probe(argv[1], argv[2])
    if argv[:1] == ["ready"] and len(argv) == 2:
        gaps = ready(argv[1])
        print("\n".join(gaps))
        return 1 if gaps else 0
    if argv[:1] == ["gate"] and len(argv) == 3:
        why = gate(argv[1], argv[2])
        print(why)
        return 1 if why else 0
    if argv[:1] == ["_approve"] and len(argv) == 3:
        approve(argv[1], argv[2])
        return 0
    if argv[:1] == ["report"]:
        text = report(argv[1] if len(argv) > 1 else current())
        print(text or "no repro recorded for this quest")
        return 0
    ap = argparse.ArgumentParser(prog="guild repro", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command")
    p = sub.add_parser("new")
    p.add_argument("--cmd", required=True)
    p.add_argument("--with", dest="with_", action="append")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("facts")
    for k in FACTS:
        p.add_argument("--" + k)
    p = sub.add_parser("compare")
    p.add_argument("--ref")
    p.add_argument("--cmd")
    p.add_argument("--label")
    p = sub.add_parser("bisect")
    p.add_argument("--good", required=True)
    p.add_argument("--bad")
    p = sub.add_parser("theory")
    p.add_argument("theory")
    p.add_argument("--check", required=True)
    p.add_argument("--expect", required=True, choices=["pass", "fail"])
    p.add_argument("--ref")
    sub.add_parser("verify")
    sub.add_parser("cleanup")
    a = ap.parse_args(argv)
    if not a.command:
        print(__doc__)
        return 0
    return globals()["cmd_" + a.command](a)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        sys.exit("stopped: temporary worktree removed")
