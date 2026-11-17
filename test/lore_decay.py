"""Lore that expires: checks for test/run.sh. Prints "ok <name>" or "FAIL <name>" per check.

Runs in its own GUILD_HOME. The war table server is stubbed, so no port is opened.
"""
import contextlib
import datetime
import io
import json
import os
import subprocess
import sys

REPO = sys.argv[1]
sys.path.insert(0, os.path.join(REPO, "bin"))
import decay      # noqa: E402
import wartable   # noqa: E402

HOME = os.environ["GUILD_HOME"]
os.makedirs(os.path.join(HOME, "visions"), exist_ok=True)
wartable.ensure_server = lambda: 4999          # never start a server from this test
wartable.open_page = lambda url, args: None
D = datetime.date


def check(name, cond):
    print(("ok " if cond else "FAIL ") + name)


def refused(fn, *a, **k):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fn(*a, **k)
    except SystemExit as e:
        return str(e)
    return ""


LESSONS = os.path.join(HOME, "lessons.md")
VISION = os.path.join(HOME, "visions", "api.md")
open(LESSONS, "w").write(
    "- Give every brief the file path it needs  <!-- lore:aging 2026-09-01 -->\n"
    "  evidence: la: \"the brief does not say where\"\n"
    "- Staging is read-only this week  <!-- lore:perishable 2026-11-08 check=\"ask in #ops\" -->\n"
    "- Run the trial before every pull request opens  <!-- lore:aging 2026-11-15 -->\n"
    "- An old line written before markers existed\n")
open(VISION, "w").write(
    "# api vision\nstatus: sealed\nsealed: 2026-08-01, by the guildmaster\n\n"
    "## Principles\n"
    "- Money values are never floats  <!-- lore:pinned 2026-08-01 -->\n"
    "- Give every brief the file path it needs to change  <!-- lore:aging 2026-08-01 -->\n"
    "- Old ruling about the rates export  <!-- lore:aging 2026-08-01 -->\n")
NOW = D(2026, 11, 17)

# ── marker parsing ────────────────────────────────────────────────────────────
text, mk = decay.split_marker('- Staging is down  <!-- lore:perishable 2026-11-10 check="ask in #ops" -->')
check("a marker is parsed: tier, date and check", mk == {"tier": "perishable", "date": "2026-11-10", "check": "ask in #ops"})
check("the text comes back without the marker", text == "- Staging is down")
check("a line without a marker has none", decay.split_marker("- plain line")[1] is None)
check("marker() writes what split_marker reads",
      decay.split_marker("- x  " + decay.marker("aging", D(2026, 1, 2)))[1] == {"tier": "aging", "date": "2026-01-02"})
ents = decay.entries(open(LESSONS).read().split("\n"))
check("the evidence line belongs to its lesson", ents[0]["span"] == [1, 2])
check("vision headings and header lines are not rules",
      [e["n"] for e in decay.entries(open(VISION).read().split("\n"))] == [6, 7, 8])

# ── stale detection by date ───────────────────────────────────────────────────
rows = {(decay.short(p), e["n"]): st for p, e, st in decay.scan(NOW)}
check("aging is stale after 30 days", rows[("lessons.md", 1)]["stale"])
check("perishable is stale after 7 days", rows[("lessons.md", 3)]["stale"])
check("a fresh aging line is not stale", not rows[("lessons.md", 4)]["stale"])
check("pinned never goes stale", not rows[("visions/api.md", 6)]["stale"])
check("perishable says what to check", rows[("lessons.md", 3)]["check"] == "ask in #ops")
check("an unmarked line counts as aging", rows[("lessons.md", 5)]["tier"] == "aging" and rows[("lessons.md", 5)]["unmarked"])
check("an unmarked line is not stale on the day guild first sees it", not rows[("lessons.md", 5)]["stale"])
seen = json.load(open(decay.SEEN))
check("and its first-seen day is kept", list(seen.values()) == [D.today().isoformat()])
later = D.today() + datetime.timedelta(days=31)
check("31 days later the unmarked line is stale",
      any(decay.short(p) == "lessons.md" and e["n"] == 5 and st["stale"] for p, e, st in decay.scan(later)))
out = io.StringIO()
with contextlib.redirect_stdout(out):
    decay.check(NOW)
check("check lists stale lines with file:line", "stale  lessons.md:1" in out.getvalue() and "stale  visions/api.md:7" in out.getvalue())
check("check prints the tokens per repo", "api" in out.getvalue() and "(any other repo)" in out.getvalue())

# ── duplicates ────────────────────────────────────────────────────────────────
pairs = decay.dups()
check("a near-duplicate across lessons and a vision is found",
      any({a[0], b[0]} == {"lessons.md", "visions/api.md"} and {a[1], b[1]} == {1, 7} for _, a, b in pairs))
check("different rules are not duplicates", not any(1 in (a[1], b[1]) and 6 in (a[1], b[1]) for _, a, b in pairs))

# ── token estimate ────────────────────────────────────────────────────────────
cost = decay.repo_cost(NOW)
check("a repo with a vision loads more than lessons alone", cost["api"] > cost["(any other repo)"] > 0)
check("tidy's summary names stale lines and tokens", "stale lines" in decay.summary(NOW) and "tokens" in decay.summary(NOW))

# ── refresh with evidence ─────────────────────────────────────────────────────
check("refresh without evidence is refused", "evidence" in refused(decay.refresh, "lessons.md:1", "ok"))
msg = decay.refresh("lessons.md:1", "read three briefs from last week, all name the file", NOW)
check("refresh re-dates the line", "<!-- lore:aging 2026-11-17 -->" in open(LESSONS).read().split("\n")[0])
check("and keeps the text", open(LESSONS).read().startswith("- Give every brief the file path it needs  <!--"))
log = [json.loads(l) for l in open(decay.LOG)]
check("the refresh and its evidence are logged",
      log[-1]["action"] == "refresh" and "three briefs" in log[-1]["evidence"] and log[-1]["from"] == "2026-09-01")
decay.refresh("lessons.md:3", "asked in #ops: staging is still read-only", NOW)
check("a perishable refresh keeps its check", 'lore:perishable 2026-11-17 check="ask in #ops"' in open(LESSONS).read())
check("a child line cannot be addressed", "not a rule line" in refused(decay.refresh, "lessons.md:2", "something long enough"))

# ── archive as a move ─────────────────────────────────────────────────────────
before = open(LESSONS).read()
check("archive without a reason is refused", "reason" in refused(decay.archive, "lessons.md:1", ""))
decay.archive("lessons.md:1", "every brief template now asks for the path", now=NOW)
after = open(LESSONS).read()
arch = open(os.path.join(HOME, "lessons.archive.md")).read()
check("the archived line leaves the live file", "file path it needs" not in after)
check("its evidence line moves with it", "the brief does not say where" not in after and "the brief does not say where" in arch)
check("the archive keeps the line and the reason", "Give every brief the file path it needs" in arch
      and "reason: every brief template now asks for the path" in arch)
check("nothing else changed", after.split("\n") == before.split("\n")[2:])
check("the archive is logged", json.loads(open(decay.LOG).read().splitlines()[-1])["action"] == "archive")
check("archives are never checked", decay.LESSONS in decay.files() and not any(f.endswith(".archive.md") for f in decay.files()))

# ── pinned protection ─────────────────────────────────────────────────────────
vbefore = open(VISION).read()
msg = decay.archive("visions/api.md:6", "floats are fine now", now=NOW)
check("a pinned line is not archived on the quartermaster's word", open(VISION).read() == vbefore)
check("it goes on the docket instead", "docket" in msg)
board = msg.split("board ")[1].split(")")[0]
bdir = os.path.join(HOME, "quests", "lessons", "boards", board)
meta = json.load(open(os.path.join(bdir, "board.json")))
check("as a lore-archive board", meta.get("kind") == "lore-archive" and meta.get("file") == "visions/api.md")
wartable.answer_board("lessons", board, {"answers": {"lore": "keep"}})
check("Keep leaves the pinned line where it is", open(VISION).read() == vbefore)
os.remove(os.path.join(bdir, "decision.json"))
wartable.answer_board("lessons", board, {"answers": {"lore": "archive"}, "message": "yes, we moved to decimals"})
check("Archive on the docket moves it", "Money values are never floats" not in open(VISION).read())
varch = open(os.path.join(HOME, "visions", "api.archive.md")).read()
check("with the guildmaster's words", "confirmed by: the guildmaster on the docket: yes, we moved to decimals" in varch)

# ── archived lines no longer reach the quest prompt ───────────────────────────
decay.archive("visions/api.md:6", "duplicate of the lesson", now=NOW)   # was line 7 before the move
rendered = decay.render(VISION, NOW)
check("an archived line is not in what the quest reads", "file path it needs to change" not in rendered
      and "Money values" not in rendered)
check("a stale line still loads, flagged", "Old ruling about the rates export  [stale: aging since 2026-08-01" in rendered)
check("markers are stripped from what the quest reads", "lore:" not in rendered)
check("the quest is told stale lines need care", rendered.startswith("<!-- 1 line below is stale"))
guild = open(os.path.join(REPO, "bin", "guild")).read()
check("a new quest reads the rendered vision", 'decay.py" render "$vision_file" > "$q/vision.md"' in guild
      and "\\`$q/vision.md\\`" in guild)
r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "decay.py"), "read", "api"], capture_output=True, text=True,
                   env={**os.environ, "GUILD_HOME": HOME})
check("lore read shows lessons and the vision without archived lines",
      "Run the trial" in r.stdout and "Old ruling" in r.stdout and "Money values" not in r.stdout)

# ── accepted lessons start aging ──────────────────────────────────────────────
import lessons  # noqa: E402
json.dump([{"id": "L1", "text": "Name the test to run", "evidence": [{"quest": "a", "quote": "q"}], "status": "proposed"}],
          open(lessons.PROPOSED, "w"))
lessons.decide("L1", "accept")
check("an accepted lesson is written as aging, dated today",
      f"- Name the test to run  <!-- lore:aging {D.today().isoformat()} -->" in open(LESSONS).read())
check("mark sets a tier", "marked" in decay.mark("lessons.md:3", "pinned"))
check("perishable needs a check", "check" in refused(decay.mark, "lessons.md:3", "perishable"))
