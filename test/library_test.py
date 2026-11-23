"""The library and the Keeper: checks for test/run.sh. Prints "ok <name>" or "FAIL <name>" per check.

Runs in its own GUILD_HOME with a tiny made-up library. No server is started and no model is called:
the refresh runs against a stub claude.
"""
import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import time

REPO = sys.argv[1]
HOME = os.environ["GUILD_HOME"]
LIB = os.path.join(HOME, "library")
NOTES = os.path.join(LIB, "notes")
GRAPH = os.path.join(LIB, "graphify-out", "graph.json")
os.makedirs(NOTES, exist_ok=True)
os.makedirs(os.path.dirname(GRAPH), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "bin"))
import library    # noqa: E402
import wartable   # noqa: E402

wartable.ensure_server = lambda: 4999          # never start a server from this test


def check(name, cond):
    print(("ok " if cond else "FAIL ") + name)


def run(*args, env=None):
    return subprocess.run([sys.executable, os.path.join(REPO, "bin", "library.py"), *args],
                          capture_output=True, text=True, env={**os.environ, **(env or {})})


# ── a made-up library: four notes, one of them an island ──────────────────────
NOTE = "---\ntitle: {t}\ntype: {k}\nlast_edited: 2026-01-0{d}\n---\n# {t}\n\n{b}\n"
for slug, t, k, d, b in [
    ("rocket-garden", "Rocket Garden", "Project", 1, "The rocket garden grows moon beans.\nSee [[tea-brewing]] for the watering tea."),
    ("tea-brewing", "Tea Brewing", "Recipe", 2, "Green tea is brewed at 80 degrees.\nMoon beans make a sweet tea."),
    ("lighthouse-repair", "Lighthouse Repair", "Project", 3, "The lamp of the lighthouse needs new copper wire."),
    ("bird-watching", "Bird Watching", "Hobby", 4, "Owls come out at night."),
]:
    open(os.path.join(NOTES, slug + ".md"), "w").write(NOTE.format(t=t, k=k, d=d, b=b))
G = {"nodes": [
    {"id": "garden", "label": "Rocket Garden", "community_name": "Space farm", "source_file": "notes/rocket-garden.md"},
    {"id": "beans", "label": "Moon Beans", "community_name": "Space farm", "source_file": "notes/rocket-garden.md"},
    {"id": "tea", "label": "Green Tea", "community_name": "Kitchen", "source_file": "notes/tea-brewing.md"},
    {"id": "lamp", "label": "Lighthouse Lamp", "community_name": "Coast", "source_file": "notes/lighthouse-repair.md"},
    {"id": "wire", "label": "Copper Wire", "community_name": "Coast", "source_file": "notes/lighthouse-repair.md"}],
    "links": [
    {"source": "garden", "target": "beans", "relation": "references", "confidence": "EXTRACTED"},
    {"source": "beans", "target": "tea", "relation": "shares_data_with", "confidence": "EXTRACTED"},
    {"source": "tea", "target": "lamp", "relation": "conceptually_related_to", "confidence": "INFERRED"},
    {"source": "lamp", "target": "wire", "relation": "references", "confidence": "EXTRACTED"}],
    "hyperedges": [{"label": "Things that glow", "nodes": ["lamp", "beans"]}]}
json.dump(G, open(GRAPH, "w"))
time.sleep(0.05)

# ── the page ──────────────────────────────────────────────────────────────────
out = os.path.join(HOME, "out", "library.html")
with contextlib.redirect_stdout(io.StringIO()) as said:
    library.page(NOTES, GRAPH, out)
html = open(out).read() if os.path.isfile(out) else ""
check("page: the file is written", bool(html))
check("page: it holds the notes and the concepts", "Rocket Garden" in html and "Copper Wire" in html and "Bird Watching" in html)
check("page: it has both views", 'id="vNotes"' in html and 'id="vConcepts"' in html)
check("page: guessed and found-in-text links are marked", '"conf": "INFERRED"' in html and "guessed by the model" in html)
check("page: it says what it built", "4 notes" in said.getvalue() and "5 concepts" in said.getvalue())
check("page: no note path leaks into the page", NOTES not in html)
check("page: library.py page builds it from the command line too", run("page", NOTES, GRAPH, out).returncode == 0)

# ── the Keeper ────────────────────────────────────────────────────────────────
r = run("ask", "what do we know about moon beans?")
check("ask: exits 0 on a match", r.returncode == 0)
check("ask: matches the concept and names its note", "concept  Moon Beans  (in Rocket Garden)" in r.stdout)
check("ask: lists a connection found in the text", "Moon Beans shares data with Green Tea (in the text)" in r.stdout)
check("ask: labels a guessed link", "Green Tea is related to Lighthouse Lamp (guessed)" in r.stdout)
check("ask: links in the text come before guessed ones",
      r.stdout.find("(in the text)") < r.stdout.find("(guessed)"))
check("ask: read next gives the note's file path first", r.stdout.split("Read next:")[-1].strip().startswith(os.path.join(NOTES, "rocket-garden.md")))
check("ask: output is short", len(r.stdout.splitlines()) <= 25)
r = run("ask", "lighthouse", "--hops", "1")
check("ask: --hops 1 stays near the seed", "Copper Wire" in r.stdout and "Moon Beans" not in r.stdout)
r = run("ask", "how", "about", "the", "tea")
check("ask: a note title matches and stopwords are ignored", "Tea Brewing" in r.stdout and r.returncode == 0)
r = run("ask", "submarine pizza")
check("ask: no match says so and exits 1", r.returncode == 1 and "found nothing" in r.stdout)
r = run("ask", "moon beans", "--graph", os.path.join(HOME, "nope.json"))
check("ask: a missing graph exits 1 with a clear message", r.returncode == 1 and "guild library refresh" in r.stderr)

# ── status ────────────────────────────────────────────────────────────────────
past = time.time() - 3600
os.utime(GRAPH, (past, past))
for f in os.listdir(NOTES):
    os.utime(os.path.join(NOTES, f), (past - 60, past - 60))
os.utime(os.path.join(NOTES, "tea-brewing.md"))           # edited after the graph was built
s = run("status").stdout
check("status: counts the notes", "notes    4 in" in s)
check("status: counts graph nodes and links", "5 nodes, 4 links" in s)
check("status: notes changed since the graph", "changed  1 notes since the graph was built: tea-brewing.md" in s)
check("status: islands", "islands  1 notes with no links: bird-watching" in s)
check("status: the page is not built yet", "not built yet" in s)

# ── the war table route ───────────────────────────────────────────────────────
def get(path, cls=wartable.Handler):
    h = cls.__new__(cls)
    h.path, got = path, {}
    h.send = lambda code, body, ctype="text/html; charset=utf-8": got.update(code=code, body=body)
    h.do_GET()
    return got


g = get("/library")
check("/library: 404 says to run refresh when the page is missing", g.get("code") == 404 and "guild library refresh" in g.get("body", ""))
with contextlib.redirect_stdout(io.StringIO()):
    library.ensure()
g = get("/library")
check("/library: serves the built page", g.get("code") == 200 and "Lighthouse Repair" in g.get("body", ""))
h = wartable.RemoteHandler.__new__(wartable.RemoteHandler)
h.path, got = "/library", {}
h.send = lambda code, body, ctype="": got.update(code=code)
wartable.Handler.do_GET(h)
check("/library: never on the remote copy", got.get("code") == 404)

# ── refresh, against a stub claude ────────────────────────────────────────────
stub = os.path.join(HOME, "fake-claude")
open(stub, "w").write("#!/bin/sh\necho \"$@\" >> \"$GUILD_HOME/claude-calls\"\n"
                      "case \"$2\" in /graphify*) touch graphify-out/graph.json ;; esac\n")
os.chmod(stub, os.stat(stub).st_mode | stat.S_IEXEC)
r = run("refresh", env={"GUILD_LIBRARY_CLAUDE": stub})
calls = open(os.path.join(HOME, "claude-calls")).read() if os.path.isfile(os.path.join(HOME, "claude-calls")) else ""
check("refresh: a folder source skips the export", "1/3 export: source is a folder" in r.stdout and "notion" not in calls)
check("refresh: runs graphify --update headless in the home", f"/graphify {NOTES} --update --no-viz" in calls)
check("refresh: rebuilds the page", r.returncode == 0 and "3/3 page" in r.stdout)
os.makedirs(os.path.join(HOME, "local"), exist_ok=True)
json.dump({"source": "notion"}, open(os.path.join(HOME, "local", "library.json"), "w"))
open(os.path.join(HOME, "claude-calls"), "w").close()
r = run("refresh", env={"GUILD_LIBRARY_CLAUDE": stub})
calls = open(os.path.join(HOME, "claude-calls")).read()
check("refresh: a notion source exports first, read-only tools only",
      "Export Notion Memory" in calls and "notion-fetch" in calls and "notion-update-page" not in calls and "notion-create" not in calls)
