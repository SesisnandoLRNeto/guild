"""Open questions and the status shape: checks for test/run.sh. Prints "ok <name>" or "FAIL <name>".

Runs in its own GUILD_HOME, HOME and tmux socket; no war table server, no notification, no GitHub.
A quest cannot close while a question is open; answer or snooze lets it; a snooze comes back on
its date; the campfire, the docket and the wrap-up share four sections that always show.
"""
import datetime
import json
import os
import subprocess
import sys

REPO = sys.argv[1]
HOME = os.environ["GUILD_HOME"]
os.environ.update({"HOME": os.path.join(HOME, "home"), "GUILD_WORKTREES": os.path.join(HOME, "wt"),
                   "GUILD_TMUX_SOCKET": f"guild-qtest-{os.getpid()}", "GUILD_NO_NOTIFY": "1",
                   "GUILD_NO_PR_SYNC": "1", "GUILD_BOARD_NO_OPEN": "1"})
os.makedirs(os.environ["HOME"], exist_ok=True)
os.makedirs(os.path.join(HOME, "local"), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "bin"))
import wartable   # noqa: E402

GUILD = os.path.join(REPO, "bin", "guild")
QUESTS = os.path.join(HOME, "quests")
EVENTS = os.path.join(HOME, "events.log")
TODAY = datetime.date.today().isoformat()


def check(name, cond, said=""):
    print(("ok " if cond else "FAIL ") + name + ("" if cond else f"  ({said[:300]})"))


def guild(*args):
    r = subprocess.run([GUILD, *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def quest(slug, state="done"):
    q = os.path.join(QUESTS, slug)
    os.makedirs(os.path.join(q, "boards"), exist_ok=True)
    json.dump({"slug": slug, "repo": os.path.join(HOME, "repo"), "worktree": os.path.join(HOME, "gone", slug),
               "model": "sonnet"}, open(os.path.join(q, "meta.json"), "w"))
    open(os.path.join(q, "status"), "w").write(f"{state}\tshipped\t2026-11-16T10:00:00\n")
    return q


def board(slug, bid, title, wrapup=False):
    d = os.path.join(QUESTS, slug, "boards", bid)
    os.makedirs(d, exist_ok=True)
    json.dump({"quest": slug, "id": bid, "title": title, "created": "2026-11-16T10:00:00", "wrapup": wrapup},
              open(os.path.join(d, "board.json"), "w"))
    json.dump({"questions": [{"id": "choice", "title": title, "type": "single", "recommended": "a",
                              "options": [{"id": "a", "label": "Keep it"}, {"id": "b", "label": "Drop it"}]}]},
              open(os.path.join(d, "decisions.json"), "w"))
    return d


def order(text, words):
    at = [text.find(w) for w in words]
    return all(i >= 0 for i in at) and at == sorted(at)


FOUR = ["Needs you", "Underway", "Next", "Landed"]

# ── the four sections always show, even with nothing at all ───────────────────
empty = wartable.standing_text()
check("an empty guild still shows all four sections, in order", order(empty, FOUR), empty)
check("each with a plain empty sentence", "Nothing needs you right now." in empty and "Nothing is being worked on." in empty
      and "Nothing is snoozed or queued." in empty and "Nothing landed in the last" in empty, empty)

# ── close is refused while a question is open ─────────────────────────────────
quest("qa")
d = board("qa", "100001", "Keep the old export?")
board("qa", "100002", "qa shipped", wrapup=True)          # a wrap-up is a report, never a question
code, out = guild("close", "qa")
check("close is refused while a question is open", code != 0 and os.path.isdir(os.path.join(QUESTS, "qa")), out)
check("and the refusal names the question", "#100001" in out and "Keep the old export?" in out, out)
check("a wrap-up alone does not hold the close back", "qa shipped" not in out, out)
dj = wartable.docket_items()
check("a finished quest's open question stays on the docket", any(i["board"] == "100001" for i in dj["open"]))

quest("qz", state="blocked")
board("qz", "200001", "Which region?")
code, out = guild("sweep")
check("guild sweep shows the four sections in order", order(out, FOUR), out)
check("and lists every open question, most urgent first",
      out.find("qz #200001") >= 0 and out.find("qa #100001") > out.find("qz #200001"), out)

# ── a snooze lets the quest close, and comes back on its date ─────────────────
code, out = guild("ask", "snooze", "qa", "100001", "--until", "yesterday")
check("a snooze needs a real date", code != 0, out)
code, out = guild("ask", "snooze", "qa", "100001", "--until", "7d", "--note", "after the release")
until = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
held = json.load(open(os.path.join(d, "board.json")))
check("guild ask snooze parks the question until a date", code == 0 and held.get("held_until") == until, out)
check("a finished quest stays finished when its question is snoozed", open(os.path.join(QUESTS, "qa", "status")).read().startswith("done"))
check("the snoozed question is under Next, not Needs you",
      any(i["board"] == "100001" for i in wartable.docket_items()["held"])
      and not any(i["board"] == "100001" for i in wartable.docket_items()["open"]))
r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "wartable.py"), "questions", "qa"], capture_output=True, text=True)
check("a snoozed question lets the quest close", r.returncode == 0, r.stdout + r.stderr)

held["held_until"] = TODAY                                # its day has come
json.dump(held, open(os.path.join(d, "board.json"), "w"))
check("on its date it is back under Needs you", any(i["board"] == "100001" for i in wartable.docket_items()["open"]))
r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "wartable.py"), "questions", "qa"], capture_output=True, text=True)
check("and holds the close back again", r.returncode == 1 and "100001" in r.stdout, r.stdout)
wartable.due_boards()
wartable.due_boards()
check("its return is announced once", open(EVENTS).read().count("held decision is due again: Keep the old export?") == 1)

# ── an answer is a decision in the guildmaster's words, and lets the quest close ──
wrap = wartable.standing_html("qa")
check("the wrap-up shows the four sections", order(wrap, FOUR), wrap)
check("and lists the unanswered question", "Keep the old export?" in wrap, wrap)
served = wartable.with_glance(b"<html><body><h1>What changed</h1></body></html>", "qa", "100002").decode()
check("the served wrap-up page carries them under the glance strip", 'aria-label="Where it stands"' in served
      and served.find("At a glance") < served.find("Where it stands") < served.find("What changed"), served[-400:])
check("a plain question page does not", "Where it stands" not in
      wartable.with_glance(b"<html><body>x</body></html>", "qa", "100001").decode())
code, out = guild("ask", "answer", "qa", "100001", "Nobody uses it any more", "--pick", "b")
check("guild ask answer answers the board", code == 0 and os.path.exists(os.path.join(d, "decision.json")), out)
dec = open(os.path.join(QUESTS, "qa", "decisions.md")).read()
check("the answer is kept as a decision in the guildmaster's words",
      "Keep the old export?: Drop it" in dec and '"Nobody uses it any more"' in dec, dec)
check("and logged as an event", "\tqa\tdecided\t" in open(EVENTS).read())
check("the wrap-up lists it as landed", "Drop it" in wartable.standing_html("qa"))
code, out = guild("close", "qa")
check("with the question answered, close goes through", code == 0 and not os.path.isdir(os.path.join(QUESTS, "qa")), out)

# ── --force still closes, and says what it left ───────────────────────────────
code, out = guild("close", "qz", "--force")
check("--force closes with an open question", code == 0 and not os.path.isdir(os.path.join(QUESTS, "qz")), out)
check("and logs the questions it left", "close-forced\tclosed with open questions: #200001  Which region?" in open(EVENTS).read())

full = wartable.standing_text()
check("after the closes all four sections still show", order(full, FOUR) and "Nothing needs you right now." in full, full)
check("and closed quests are under Landed", "qa: closed" in full, full)

# ── one shape on the three surfaces ───────────────────────────────────────────
page = open(os.path.join(REPO, "web", "docket.html")).read()
check("the docket page has the four sections in order", order(page, [f"</span>{w}</h2>" for w in FOUR]))
camp = open(os.path.join(REPO, "skills", "campfire", "SKILL.md")).read()
check("the campfire answers in the same four sections", order(camp, [f"**{w}**" for w in FOUR]) and "guild sweep" in camp)
