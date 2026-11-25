"""Bug quests (guild repro) and scout quests (guild promote): checks for test/run.sh.

Prints "ok <name>" or "FAIL <name>" per check. Runs in its own GUILD_HOME, HOME and worktree folder,
with a throwaway repo and a stub claude; quests start --headless, so no tmux and no war table.
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.abspath(sys.argv[1])
GUILD = os.path.join(REPO, "bin", "guild")
GH = os.environ["GUILD_HOME"]
TMP = tempfile.mkdtemp(prefix="guild-kinds-")
STUB = os.path.join(TMP, "stub")
os.makedirs(STUB)
os.makedirs(os.path.join(GH, "local"), exist_ok=True)
for name in ("claude", "gh"):                       # the real gh must never run: this one says so
    with open(os.path.join(STUB, name), "w") as f:
        f.write("#!/bin/sh\necho REAL-GH-CALLED\n" if name == "gh" else "#!/bin/sh\nexit 0\n")
    os.chmod(os.path.join(STUB, name), 0o755)
for k in ("GUILD_QUEST", "GUILD_QM", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
    os.environ.pop(k, None)
os.environ.update(HOME=os.path.join(TMP, "home"), GUILD_WORKTREES=os.path.join(TMP, "worktrees"),
                  GUILD_TMUX_SOCKET="guild-kinds-test", GUILD_BOARD_NO_OPEN="1", GUILD_NO_NOTIFY="1",
                  GUILD_NO_WHY="1", GUILD_NO_PR_SYNC="1", PYTHONDONTWRITEBYTECODE="1", PATH=STUB + ":" + os.environ["PATH"],
                  GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
os.makedirs(os.environ["HOME"])


def check(name, cond):
    print(("ok " if cond else "FAIL ") + name)


def sh(*args, cwd=None, quest=None, stdin=None, env=None):
    e = dict(os.environ, **(env or {}))
    if quest:
        e["GUILD_QUEST"] = quest
    r = subprocess.run(list(args), cwd=cwd, input=stdin, capture_output=True, text=True, env=e)
    return r.returncode, r.stdout + r.stderr


def git(*args, cwd):
    return sh("git", *args, cwd=cwd)[1].strip()


def meta(slug):
    return json.load(open(os.path.join(GH, "quests", slug, "meta.json")))


# a repo where commit 3 of 4 breaks the sum
R = os.path.join(TMP, "calc")
os.makedirs(R)
git("init", "-q", "-b", "main", cwd=R)
open(os.path.join(R, "calc.sh"), "w").write("echo $((2+2))\n")
git("add", ".", cwd=R); git("commit", "-qm", "calc", cwd=R)
GOOD = git("rev-parse", "HEAD", cwd=R)
open(os.path.join(R, "readme"), "w").write("a\n")
git("add", ".", cwd=R); git("commit", "-qm", "readme", cwd=R)
open(os.path.join(R, "calc.sh"), "w").write("echo $((2+3))\n")
git("add", ".", cwd=R); git("commit", "-qm", "faster sum", cwd=R)
BAD = git("rev-parse", "HEAD", cwd=R)
open(os.path.join(R, "readme"), "w").write("b\n")
git("add", ".", cwd=R); git("commit", "-qm", "readme again", cwd=R)
MAIN = git("rev-parse", "HEAD", cwd=R)
REPRO = '[ "$(bash calc.sh)" = 4 ]'
tmp_before = {d for d in os.listdir(tempfile.gettempdir()) if d.startswith("guild-repro-")}

# ── bug quest ──────────────────────────────────────────────────────────────────
code, out = sh(GUILD, "quest", "sum", "--repo", R, "--bug", "--quick", "--headless", stdin="Intent: x\n")
check("--bug refuses --quick (the diagnosis needs the plan board)", code != 0 and "--bug" in out)
code, out = sh(GUILD, "quest", "sum", "--repo", R, "--bug", "--headless",
               stdin=f"Intent: the sum is wrong\nAcceptance:\n- check: {REPRO}\n")
check("guild quest --bug starts", code == 0)
m = meta("sum")
WT = m["worktree"]
check("a bug quest is marked kind bug", m.get("kind") == "bug")
check("a bug quest plans first", m.get("phase") == "plan")
prompt = open(os.path.join(GH, "quests", "sum", "prompt.md")).read()
check("the adventurer prompt explains the repro steps", "a failing repro first" in prompt and "guild repro new" in prompt)

code, out = sh(GUILD, "repro", "new", "--cmd", "true", cwd=WT, quest="sum")
check("repro new refuses a command that passes today", code != 0 and "REFUSED" in out)
check("and records nothing", not os.path.exists(os.path.join(GH, "quests", "sum", "repro.json")))
code, out = sh(GUILD, "repro", "new", "--cmd", REPRO, cwd=WT, quest="sum")
check("repro new records a command that fails today", code == 0 and "FAIL" in out)

code, out = sh(GUILD, "plan", "ready", "the fix", cwd=WT, quest="sum")
check("plan ready refuses a bug quest without its diagnosis", code != 0 and "still lacks" in out and "trigger" in out)

sh(GUILD, "repro", "facts", "--trigger", "any call", "--condition", "always since the faster sum",
   "--symptom", "prints 5", cwd=WT, quest="sum")
code, out = sh(GUILD, "repro", "compare", "--ref", GOOD, cwd=WT, quest="sum")
check("compare runs the repro on an older commit and it passes there", code == 0 and "PASS" in out)
code, out = sh(GUILD, "repro", "theory", "the faster sum adds 3", "--check", "grep -q '2+3' calc.sh",
               "--expect", "pass", cwd=WT, quest="sum")
check("a theory with a check that could disprove it is recorded", code == 0 and "SURVIVED" in out)

code, out = sh(GUILD, "repro", "bisect", "--good", GOOD, cwd=WT, quest="sum")
check("bisect names the commit that broke it", code == 0 and BAD[:8] in out)
if not (code == 0 and BAD[:8] in out):
    print("     bisect said (exit %s):\n" % code + "\n".join("     | " + l for l in out.splitlines()[-15:]))
wts = git("worktree", "list", "--porcelain", cwd=R)
check("bisect leaves no temporary worktree behind", "guild-repro-" not in wts)
check("bisect leaves no bisect refs behind", git("for-each-ref", "refs/bisect", cwd=R) == ""
      and git("for-each-ref", "refs/bisect", cwd=WT) == "")
common = git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=R)
leftover = [os.path.join(dp, f) for dp, _, fs in os.walk(common) for f in fs if f.startswith("BISECT_")]
check("bisect leaves no BISECT_ state files behind", not leftover)
tmp_after = {d for d in os.listdir(tempfile.gettempdir()) if d.startswith("guild-repro-")}
check("bisect removes its temporary folders", tmp_after <= tmp_before)
check("the quest worktree is untouched by the bisect", git("rev-parse", "HEAD", cwd=WT) == MAIN
      and git("status", "--porcelain", cwd=WT) == "")

code, out = sh("python3", os.path.join(REPO, "bin", "rootcause.py"), "ready", "sum")
check("the diagnosis is ready for the plan board", code == 0)
sys.path.insert(0, os.path.join(REPO, "bin"))
os.environ["GUILD_HOME"] = GH
import rootcause   # noqa: E402
import planpage    # noqa: E402
page = planpage.diag_html(rootcause.report("sum"), lambda md: md)
check("the plan board shows the diagnosis first", "Diagnosis: the bug, proven before the fix" in page and REPRO in page)

open(os.path.join(WT, "calc.sh"), "w").write("echo $((2+2))\n")
git("commit", "-qam", "fix the sum", cwd=WT)
sh(GUILD, "check", cwd=WT, quest="sum")
code, out = sh(GUILD, "trial", "pass", "--no-behaviour", "test repo", cwd=WT, quest="sum")
check("the trial refuses a bug quest until the repro ran on HEAD", code != 0 and "guild repro verify" in out)
code, out = sh(GUILD, "repro", "verify", cwd=WT, quest="sum")
check("repro verify passes after the fix", code == 0 and "PASS" in out)
code, out = sh(GUILD, "trial", "pass", "--no-behaviour", "test repo", cwd=WT, quest="sum")
check("the trial passes once the repro failed before and passes on HEAD", code == 0)
code, out = sh(GUILD, "pr-body", cwd=WT, quest="sum")
check("the PR body carries the diagnosis block", "<!-- guild:diagnosis -->" in out and "Before the fix: **failed**" in out
      and "passes** on HEAD" in out)
body = os.path.join(TMP, "body.md")
open(body, "w").write(out.replace("<!-- guild:diagnosis -->", ""))
code, why = sh("python3", os.path.join(REPO, "bin", "prbody.py"), "verify", "sum", body)
check("a bug PR body without the diagnosis is refused", code != 0 and "diagnosis" in why)

# ── scout quest ────────────────────────────────────────────────────────────────
code, out = sh(GUILD, "quest", "why-sum", "--repo", R, "--scout", "--headless", stdin="Intent: why is the sum 5?\n")
check("guild quest --scout starts with no acceptance block", code == 0)
s = meta("why-sum")
SW = s["worktree"]
check("a scout is marked kind scout, on a scout/ branch, with no plan", s.get("kind") == "scout"
      and s.get("branch") == "scout/why-sum" and s.get("phase") == "")
open(os.path.join(SW, "scratch.sh"), "w").write("echo debug\n")
git("add", ".", cwd=SW); git("commit", "-qm", "scratch", cwd=SW)

code, out = sh(GUILD, "trial", "pass", "--no-behaviour", "x", cwd=SW, quest="why-sum")
check("the trial is refused for a scout", code != 0 and "scout" in out)
code, out = sh(GUILD, "trial", "skip", "no code", cwd=SW, quest="why-sum")
check("a skipped trial is refused for a scout too", code != 0)
code, out = sh(os.path.join(REPO, "bin", "shims", "gh"), "pr", "create", "--title", "x", "--body", "y", cwd=SW, quest="why-sum")
check("gh pr create is refused for a scout (shim)", code == 2 and "REAL-GH-CALLED" not in out and "scout" in out)
code, out = sh(os.path.join(REPO, "hooks", "pr-gate.sh"), cwd=SW, quest="why-sum",
               stdin=json.dumps({"tool_input": {"command": "gh pr create --title x"}}))
check("gh pr create is refused for a scout (hook)", code == 2 and "scout" in out)

code, out = sh(GUILD, "promote", "why-sum", "sum-fix", "--headless")
check("promote refuses a scout with no findings", code != 0 and "findings" in out)
code, out = sh(GUILD, "status", "why-sum", "done", "found it")
check("a scout cannot report done without findings", code != 0 and "## Findings" in out)
open(os.path.join(GH, "quests", "why-sum", "findings.md"), "w").write(
    "# why-sum\n\n## Findings\n- calc.sh adds 2+3 since commit 'faster sum' (evidence: git log -S '2+3')\n\n"
    "## Recommendation\n- put 2+2 back and add a test\n\nAcceptance:\n- check: " + REPRO + "\n")
code, out = sh(GUILD, "status", "why-sum", "done", "found it")
check("a scout reports done once findings.md has both sections", code == 0)

code, out = sh(GUILD, "promote", "sum", "--headless")
check("promote refuses a quest that is not a scout", code != 0 and "not a scout" in out)
code, out = sh(GUILD, "promote", "why-sum", "sum-fix", "--headless")
check("guild promote starts a normal quest", code == 0)
p = meta("sum-fix")
brief = open(os.path.join(GH, "quests", "sum-fix", "brief.md")).read()
check("the new quest's brief carries the scout's findings", "From scout `why-sum`" in brief and "adds 2+3" in brief
      and "put 2+2 back" in brief)
acc = json.load(open(os.path.join(GH, "quests", "sum-fix", "acceptance.json")))
check("and the acceptance block the scout proposed", any(i.get("run") == REPRO for i in acc.get("items", [])))
check("the new quest is a normal quest from the scout", p.get("kind") == "" and p.get("from_scout") == "why-sum"
      and p.get("branch") == "quest/sum-fix")
check("it starts from a clean base: the scout's code is left behind",
      git("rev-parse", "HEAD", cwd=p["worktree"]) == MAIN and not os.path.exists(os.path.join(p["worktree"], "scratch.sh")))
check("the scout's branch keeps its scratch commit", "scratch" in git("log", "-1", "--format=%s", "scout/why-sum", cwd=R))
check("the scout records where it went", meta("why-sum").get("promoted_to") == "sum-fix")
check("the new adventurer is told it was promoted", "Promoted from scout" in open(os.path.join(GH, "quests", "sum-fix", "prompt.md")).read())

subprocess.run(["chmod", "-R", "u+w", TMP], capture_output=True)   # python may leave a read-only cache in HOME
subprocess.run(["rm", "-rf", TMP], capture_output=True)
