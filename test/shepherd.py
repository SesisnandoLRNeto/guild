"""PR watch: checks for test/run.sh. Prints "ok <name>" or "FAIL <name>" per check.

Runs in its own GUILD_HOME; GitHub, tmux and the guild CLI are stubbed, so nothing leaves the Mac.
"""
import json
import os
import subprocess
import sys

REPO = sys.argv[1]
sys.path.insert(0, os.path.join(REPO, "bin"))
os.environ["GUILD_SHEPHERD_QUIET"] = "300"
import prs        # noqa: E402
import shepherd   # noqa: E402

HOME = os.environ["GUILD_HOME"]
os.makedirs(os.path.join(HOME, "local"), exist_ok=True)
URL = "https://github.com/o/api/pull/7"
SLUG = "rates-export"
QD = os.path.join(HOME, "quests", SLUG)
WT = os.path.join(HOME, "wt")
os.makedirs(QD, exist_ok=True)
os.makedirs(WT, exist_ok=True)
subprocess.run(["git", "-C", WT, "init", "-q"], check=True)
subprocess.run(["git", "-C", WT, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"], check=True)
json.dump({"slug": SLUG, "worktree": WT, "repo": WT}, open(os.path.join(QD, "meta.json"), "w"))
open(os.path.join(QD, "launch.sh"), "w").write("true\n")


def check(name, cond):
    print(("ok " if cond else "FAIL ") + name)


def status(s):
    open(os.path.join(QD, "status"), "w").write(f"{s}\tnote\t2026-11-16T10:00:00\n")


OLD, FRESH = "2026-11-16T08:00:00Z", "2999-01-01T00:00:00Z"
GH = {"pr": {"state": "open", "merged": False, "user": {"login": "me"}, "title": "Rates export", "mergeable_state": "clean",
             "head": {"sha": "h1", "ref": "feat-rates"}, "base": {"ref": "main"}},
      "issue": [], "review": [], "reviews": [], "runs": []}
calls, sent, revived, windows = [], [], [], []


def fake_gh(url, *args, body=None):
    calls.append((args, body))
    path = args[0]
    if "-X" in args:
        return {}
    if path.endswith("/pulls/7"):
        return GH["pr"]
    if "/issues/7/comments" in path:
        return GH["issue"]
    if "/pulls/7/comments" in path:
        return GH["review"]
    if "/pulls/7/reviews" in path:
        return GH["reviews"]
    if "/check-runs" in path:
        return {"check_runs": GH["runs"]}
    raise RuntimeError("unexpected " + path)


class R:
    def __init__(self, code=0):
        self.returncode, self.stderr, self.stdout = code, "", ""


def fake_guild(*args):
    if args[0] == "send":
        sent.append(args[2])
    if args[0] == "revive":
        revived.append(args[1])
    return R()


shepherd.gh = fake_gh
shepherd.guild = fake_guild
shepherd.quest_windows = lambda: list(windows)
shepherd.free_memory = lambda: 80
shepherd.unwatched = lambda urls: []
prs.quest_prs = lambda days=7: {SLUG: URL}


def events():
    try:
        return open(shepherd.EVENTS).read()
    except OSError:
        return ""


# turning it on: what is already on the PR is history
GH["issue"] = [{"id": 1, "user": {"login": "rev"}, "created_at": OLD, "body": "old remark"}]
status("done")
windows[:] = [SLUG]
shepherd.set_mode("on")
check("PR watch turns on with a switch file", shepherd.is_on())
shepherd.once()
check("comments already there when it is turned on are not sent", not sent)

# a new comment from a reviewer, a bot and you: only the reviewer's goes to the quest
GH["review"] = [{"id": 2, "user": {"login": "rev"}, "created_at": OLD, "body": "use a constant here", "path": "A.java", "line": 40},
                {"id": 3, "user": {"login": "github-actions[bot]"}, "created_at": OLD, "body": "coverage 80%"},
                {"id": 4, "user": {"login": "me"}, "created_at": OLD, "body": "will do"}]
shepherd.once()
check("a reviewer's new comment is sent to the quest", len(sent) == 1 and "[rc2] rev on A.java:40: use a constant here" in sent[0])
check("bots and your own comments are left out", sent and "coverage" not in sent[0] and "will do" not in sent[0])
check("the message says to merge, push to the PR branch and reply", sent and "git pull --no-rebase origin feat-rates" in sent[0]
      and "git push origin HEAD:feat-rates" in sent[0] and f"guild shepherd reply {SLUG} <key>" in sent[0])
check("it never tells the quest to merge the PR", sent and "never merge or approve" in sent[0])
check("the hand-off is in the events", "PR watch: 1 comment(s)" in events())
shepherd.once()
check("a comment is sent once", len(sent) == 1)

# a comment still being written waits; a busy quest waits
GH["review"].append({"id": 5, "user": {"login": "rev"}, "created_at": FRESH, "body": "and rename it"})
shepherd.once()
check("a fresh comment waits five quiet minutes for its siblings", len(sent) == 1)
GH["review"][-1]["created_at"] = OLD
status("working")
shepherd.once()
check("a busy quest is not interrupted", len(sent) == 1)
status("done")
shepherd.once()
check("once free, the waiting comment goes", len(sent) == 2 and "[rc5]" in sent[1])

# a closed window: revive when there is room, send on the next pass
windows[:] = []
GH["issue"].append({"id": 6, "user": {"login": "rev"}, "created_at": OLD, "body": "please add a test"})
shepherd.once()
check("a closed quest window is revived", revived == [SLUG] and "working\tPR watch" in open(os.path.join(QD, "status")).read())
windows[:] = [SLUG]
shepherd.once()
check("and the work is sent once its window is up", len(sent) == 3 and "please add a test" in sent[2])

# no room: wait, and say so once
windows[:] = ["a", "b", "c", "d", "e"]
for w in windows:
    os.makedirs(os.path.join(HOME, "quests", w), exist_ok=True)
    open(os.path.join(HOME, "quests", w, "launch.sh"), "w").write("true\n")
status("done")
GH["issue"].append({"id": 8, "user": {"login": "rev"}, "created_at": OLD, "body": "one more"})
shepherd.once()
shepherd.once()
check("with 5 quest windows open it waits for room", len(sent) == 3 and len(revived) == 1)
check("and says why once", events().count("waiting for room") == 1)
windows[:] = [SLUG]
shepherd.once()
check("with room again it goes", len(sent) == 4)

# behind its target only: updated on GitHub, no agent
GH["pr"]["mergeable_state"] = "behind"
shepherd.once()
puts = [(a, b) for a, b in calls if "PUT" in a]
check("a branch only behind its target is updated on GitHub", len(puts) == 1 and puts[0][0][0].endswith("/pulls/7/update-branch")
      and puts[0][1] == {"expected_head_sha": "h1"})
shepherd.once()
check("once per head", len([1 for a, _ in calls if "PUT" in a]) == 1 and len(sent) == 4)

# a conflict and failing checks go to the quest, once per head
GH["pr"]["mergeable_state"] = "dirty"
GH["runs"] = [{"name": "build", "conclusion": "failure", "status": "completed"}]
shepherd.once()
check("a conflict asks for a merge of the target, never a rebase", len(sent) == 5 and "git merge origin/main (merge, never rebase)" in sent[4])
check("failing checks are named", "Failing checks on the head: build" in sent[4])
shepherd.once()
check("not again on the same head", len(sent) == 5)

# replies: only to comments handed to this quest, once each
check("a reply to a comment it was not given is refused", "no comment" in shepherd.reply(SLUG, "rc99", "x"))
before = len(calls)
check("a reply to a line comment goes under it", shepherd.reply(SLUG, "rc2", "moved it to RATE_LIMIT") == ""
      and calls[before][0][0].endswith("/pulls/7/comments/2/replies"))
check("not twice", "already" in shepherd.reply(SLUG, "rc2", "again"))
before = len(calls)
shepherd.reply(SLUG, "ic6", "added RateExportTest")
body = calls[before][1]["body"]
check("a reply to a plain comment quotes it and names the reviewer", body.startswith("> please add a test") and "@rev added RateExportTest" in body)

# two quests on one PR (the opener and a review fix): the watch talks to one only
for q, when in (("rates-fix", "2026-11-17T09:00:00"), ("rates-old", "2026-11-01T09:00:00")):
    os.makedirs(os.path.join(HOME, "quests", q), exist_ok=True)
    json.dump({"slug": q, "created": when}, open(os.path.join(HOME, "quests", q, "meta.json"), "w"))
st = {"prs": {URL: {"slug": SLUG}}}
check("a PR shared by quests keeps the quest it already talks to", shepherd.owners({SLUG: URL, "rates-fix": URL}, st) == {URL: SLUG})
check("else the newest live one", shepherd.owners({"rates-old": URL, "rates-fix": URL}, {"prs": {}}) == {URL: "rates-fix"})
check("archived quests are left out", shepherd.owners({"gone": URL}, {"prs": {}}) == {})
shepherd.set_mode("off")
check("off, a pass does nothing", shepherd.once() is not None and len(sent) == 5)
shepherd.set_mode("on")

# merged: the PR leaves the watch
GH["pr"]["merged"] = True
shepherd.once()
check("a merged PR leaves the watch", URL not in shepherd.load_state()["prs"])
check("adopt refuses a PR it does not list", "not one of your" in shepherd.adopt("https://github.com/o/api/pull/99"))
shepherd.set_mode("off")
check("and turns off", not shepherd.is_on())
