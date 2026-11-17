"""The trial's scope check: checks for test/run.sh. Prints "ok <name>" or "FAIL <name>" per check.

Runs in its own GUILD_HOME. guild ask is stubbed, so no war table starts and no browser opens.
"""
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout

REPO = sys.argv[1]
sys.path.insert(0, os.path.join(REPO, "bin"))
import scope  # noqa: E402

HOME = os.environ["GUILD_HOME"]
QD = os.path.join(HOME, "quests", "rates-export")
os.makedirs(QD, exist_ok=True)
json.dump({"slug": "rates-export"}, open(os.path.join(QD, "meta.json"), "w"))
open(os.path.join(QD, "plan.md"), "w").write(
    "# Plan\n\n## Steps\n1. The export holds every row of the period.\n2. One retry when the upload fails.\n")
open(os.path.join(QD, "brief.md"), "w").write("Export rates as CSV.\n\nAcceptance:\n- check: npm test -- export\n")
json.dump({"items": [{"kind": "check", "run": "npm test -- export"},
                     {"kind": "manual", "text": "the file name carries the period"}]},
          open(os.path.join(QD, "acceptance.json"), "w"))

asked = []
scope.ask = lambda argv: (asked.append(argv), (True, "board id: x"))[1]


def check(name, cond):
    print(("ok " if cond else "FAIL ") + name)


def sort(findings):
    path = os.path.join(HOME, "findings.json")
    json.dump({"findings": findings}, open(path, "w"))
    out = io.StringIO()
    with redirect_stdout(out):
        scope.cmd_sort(QD, path)
    return out.getvalue()


def get(fid, rnd=None):
    hits = [f for f in scope.load(QD)["findings"] if f["id"] == fid and (rnd is None or f["round"] == rnd)]
    return hits[-1]


# ── classification on sample findings ──────────────────────────────────────────
agreed = scope.agreed_text(QD)
C = lambda f, seen=None: scope.classify(f, agreed, seen or {})[0]  # noqa: E731
check("a bug in agreed code is in scope",
      C({"change": "fix", "agreed": "The export holds every row of the period"}) == "in")
check("a missing test for an acceptance item is in scope",
      C({"change": "test", "agreed": "the file name carries the period"}) == "in")
check("a security hole in the new code is in scope (by what it fixes)",
      C({"change": "fix", "agreed": "one retry when the upload fails", "labels": ["security"]}) == "in")
check("a new option is an expansion", C({"change": "add", "agreed": "one retry when the upload fails"}) == "expansion")
check("a refactor is an expansion", C({"change": "refactor", "agreed": "The export holds every row"}) == "expansion")
check("a destructive fix is an expansion", C({"change": "fix", "destructive": True,
                                               "agreed": "The export holds every row"}) == "expansion")
check("a removal is an expansion", C({"change": "remove", "agreed": "The export holds every row"}) == "expansion")
check("a fix that points at nothing agreed is an expansion", C({"change": "fix", "agreed": ""}) == "expansion")
check("a made-up agreed quote is an expansion", C({"change": "fix", "agreed": "retries use backoff"}) == "expansion")
check("a 'required' or 'security' label does not widen scope",
      C({"change": "add", "agreed": "", "labels": ["security", "required"]}) == "expansion")
check("a theme fixed in an earlier round that comes back is an expansion",
      C({"change": "fix", "agreed": "one retry when the upload fails", "theme": "Retries"}, {"retries": 1}) == "expansion")

# ── round 1: in scope is listed to fix, an expansion becomes a card and is not applied ──
plan_before = open(os.path.join(QD, "plan.md")).read()
out = sort([
    {"id": "f1", "file": "src/export.ts", "line": 42, "summary": "export drops the last row", "change": "fix",
     "agreed": "the export holds every row of the period", "theme": "export rows"},
    {"id": "f2", "file": "src/upload.ts", "line": 10, "summary": "retry fails on timeout", "change": "fix",
     "agreed": "one retry when the upload fails", "theme": "retries"},
    {"id": "f3", "file": "src/upload.ts", "line": 12, "summary": "retries have no backoff", "change": "add",
     "agreed": "", "theme": "retries", "labels": ["required"], "wants": "exponential backoff with a config option",
     "smallest": "keep the single retry", "if_yes": "one more option in this PR", "if_no": "backoff kept as a follow-up",
     "recommend": "no", "why": "no failure seen yet"},
])
check("in-scope findings are marked to fix", get("f1")["scope"] == "in" and "f1" in out and "fix in scope" in out)
check("the expansion is marked do not fix", get("f3")["scope"] == "expansion" and "do not fix" in out)
check("exactly one card was asked, for the expansion", len(asked) == 1 and "--id" in asked[0]
      and asked[0][asked[0].index("--id") + 1] == "scope-1-f3")
argv = asked[0]
detail = argv[argv.index("--detail") + 1]
check("the card has the five parts", all(f"**{p}:**" in detail for p in scope.CARD_PARTS))
check("the card shows what the review wants and the agreement gap",
      "exponential backoff" in detail and "nothing in the plan" in detail)
check("the card treats the label as evidence", "Labelled required: evidence, not a reason to widen scope" in detail)
check("the card offers yes and no with the recommendation",
      argv[0] == "ask" and any(a.startswith("yes=") for a in argv) and any(a.startswith("no=") for a in argv)
      and argv[argv.index("--recommend") + 1] == "no")
check("the plan is not changed by an open expansion", open(os.path.join(QD, "plan.md")).read() == plan_before)
r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "scope.py"), "status", QD], capture_output=True, text=True)
check("status refuses while a card waits", r.returncode == 1 and "f3" in r.stdout)
check("the report counts a waiting card",
      scope.report_line(scope.load(QD)) == "Scope: 2 fixed in scope, 1 expansion(s) sent to the guildmaster "
                                           "(0 yes, 0 no, 1 waiting), 0 follow-up(s) recorded")

# ── the guildmaster answers no on the card: a follow-up, not a fix ─────────────
bdir = os.path.join(QD, "boards", "scope-1-f3")
os.makedirs(bdir, exist_ok=True)
json.dump({"answers": {"choice": "no"}}, open(os.path.join(bdir, "decision.json"), "w"))
data = scope.sync(QD, scope.load(QD))
todo = json.load(open(os.path.join(HOME, "todo.json")))
check("a no is read from the card", get("f3")["answer"] == "no")
check("a no records a follow-up on the campaign board",
      any("follow-up from rates-export: exponential backoff" in t["text"] for t in todo))
check("a no leaves the plan as agreed", open(os.path.join(QD, "plan.md")).read() == plan_before)
r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "scope.py"), "status", QD], capture_output=True, text=True)
check("status is clear once every card is answered", r.returncode == 0)

# ── round 2: the retries theme comes back with more machinery ──────────────────
asked.clear()
sort([{"id": "f4", "summary": "retry should be idempotent with a request key", "change": "fix",
       "agreed": "one retry when the upload fails", "theme": "retries", "wants": "an idempotency key on uploads"},
      {"id": "f5", "summary": "a new config section for upload policy", "change": "add", "agreed": "",
       "wants": "an upload policy config section", "recommend": "yes"}])
check("a returning theme becomes a card in round 2", get("f4")["scope"] == "expansion" and "round 1" in get("f4")["reason"]
      and len(asked) == 2)

# ── yes adds it to the plan ───────────────────────────────────────────────────
bdir = os.path.join(QD, "boards", "scope-2-f5")
os.makedirs(bdir, exist_ok=True)
json.dump({"answers": {"choice": "yes"}}, open(os.path.join(bdir, "decision.json"), "w"))
scope.sync(QD, scope.load(QD))
plan = open(os.path.join(QD, "plan.md")).read()
check("a yes adds it to plan.md", "## Added during the trial" in plan and "an upload policy config section" in plan)
check("a yes is not a follow-up",
      not any("upload policy" in t["text"] for t in json.load(open(os.path.join(HOME, "todo.json")))))

# ── by hand: an adventurer may say no, never yes ──────────────────────────────
env = dict(os.environ, GUILD_QUEST="rates-export")
r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "scope.py"), "answer", QD, "f4", "yes"],
                   capture_output=True, text=True, env=env)
check("an adventurer cannot answer yes for the guildmaster", r.returncode != 0 and "only the guildmaster" in r.stderr)
r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "scope.py"), "answer", QD, "f4", "no"],
                   capture_output=True, text=True, env=env)
check("an adventurer can drop an expansion to a follow-up", r.returncode == 0 and get("f4")["answer"] == "no")

# ── report counts ─────────────────────────────────────────────────────────────
line = scope.report_line(scope.load(QD))
check("the report shows fixed in scope, sent and follow-ups",
      line == "Scope: 2 fixed in scope, 3 expansion(s) sent to the guildmaster (1 yes, 2 no, 0 waiting), "
              "2 follow-up(s) recorded")

# ── a quest that may not ask: the expansion is a follow-up at once ─────────────
scope.ask = lambda argv: (False, "guild: epic dagger (x): this quest decides alone.")
sort([{"id": "f6", "summary": "add a cache", "change": "add", "agreed": "", "wants": "a cache for rates"}])
f6 = get("f6")
check("a refused card becomes a follow-up, never a fix", f6["answer"] == "no" and f6.get("card_refused")
      and any("a cache for rates" in t["text"] for t in json.load(open(os.path.join(HOME, "todo.json")))))

# ── bad input is refused ──────────────────────────────────────────────────────
for name, bad in [("an unknown change", {"id": "x", "summary": "s", "change": "polish"}),
                  ("a missing id", {"summary": "s", "change": "fix"})]:
    try:
        sort([bad])
        check(f"{name} is refused", False)
    except SystemExit:
        check(f"{name} is refused", True)
