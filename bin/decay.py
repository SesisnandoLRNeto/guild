#!/usr/bin/env python3
"""Lore that expires: dated tiers for the lines of lessons.md and the repo visions.

Those files only grow, and every quest pays for them in tokens and follows them as rules. So
each line carries a small dated marker, an HTML comment that Markdown hides:

  - Pass --ticket on every quest from Jira  <!-- lore:aging 2026-11-17 -->
  - Staging DB is read-only  <!-- lore:perishable 2026-11-17 check="ask in #ops" -->
  - Money is never a float  <!-- lore:pinned 2026-11-17 -->

pinned never goes stale; aging is stale 30 days after its date; perishable after 7 days and says
what to check. A line with no marker counts as aging from the file's last git commit, or from the
day guild first saw it. Indented lines under a line (a lesson's evidence) belong to it.

  decay.py check [--today D]                   stale lines with file:line, duplicates, tokens per repo
  decay.py refresh <file:line> "<evidence>"    re-date a line; refused without named evidence (logged)
  decay.py archive <file:line> "<reason>"      move the line to <name>.archive.md next to it (logged);
                                               a pinned line goes on the docket for the guildmaster's yes
  decay.py mark <file:line> pinned|aging|perishable [--check "<what to verify>"]
  decay.py render <file>                       the file as a quest reads it: markers out, stale lines flagged
  decay.py read [repo]                         lessons.md and that repo's vision, rendered

<file> is lessons.md, visions/<repo>.md, or a full path. Nothing is ever deleted.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
LESSONS = os.path.join(GUILD_HOME, "lessons.md")
VISIONS = os.path.join(GUILD_HOME, "visions")
LOG = os.path.join(GUILD_HOME, "lore-log.jsonl")
SEEN = os.path.join(GUILD_HOME, "lore-seen.json")
BOARD_QUEST = "lessons"           # the pseudo quest that already holds lesson boards on the docket
TIERS = {"pinned": None, "aging": 30, "perishable": 7}
MARK = re.compile(r'\s*<!--\s*lore:(\w+)\s+(\d{4}-\d{2}-\d{2})((?:\s+\w+=(?:"[^"]*"|\S+))*)\s*-->\s*$')
ATTR = re.compile(r'(\w+)=(?:"([^"]*)"|(\S+))')
HEADER = re.compile(r"^(status|sealed):", re.I)     # a vision's own header lines are not rules
BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
WORD = re.compile(r"[A-Za-z0-9_'-]+")


def today():
    return datetime.date.today()


def marker(tier, date=None, check=""):
    """The marker text for a line: what lessons.decide and the vision skill write."""
    parts = [f"lore:{tier}", (date or today()).isoformat()]
    if check and tier == "perishable":
        parts.append('check="' + check.replace('"', "'") + '"')
    return "<!-- " + " ".join(parts) + " -->"


def split_marker(line):
    """(text without marker, {"tier", "date", "check"} or None)."""
    m = MARK.search(line)
    if not m:
        return line, None
    attrs = {a.group(1): a.group(2) if a.group(2) is not None else a.group(3) for a in ATTR.finditer(m.group(3) or "")}
    return line[:m.start()].rstrip(), {"tier": m.group(1), "date": m.group(2), **attrs}


def files():
    """Every live lore file: lessons.md and each repo's vision (never the archives)."""
    out = [LESSONS] if os.path.isfile(LESSONS) else []
    if os.path.isdir(VISIONS):
        out += sorted(os.path.join(VISIONS, f) for f in os.listdir(VISIONS)
                      if f.endswith(".md") and not f.endswith(".archive.md"))
    return out


def short(path):
    p = os.path.relpath(os.path.abspath(path), GUILD_HOME)
    return path if p.startswith("..") else p


def resolve(name):
    path = name if os.path.isabs(name) else os.path.join(GUILD_HOME, name)
    if not os.path.isfile(path):
        raise SystemExit(f"no lore file {name} (lessons.md, visions/<repo>.md, or a full path)")
    if path.endswith(".archive.md"):
        raise SystemExit(f"{name} is an archive; only live files are checked")
    return path


def read(path):
    return open(path, encoding="utf-8").read().split("\n")


def write(path, lines):
    open(path, "w", encoding="utf-8").write("\n".join(lines))


def entries(lines):
    """The lines that are rules: [{"n", "text", "marker", "span"}], 1-based. A rule is a top-level line
    of text (not a heading, code, comment or a vision's header); indented lines under it are its children."""
    out, fence = [], False
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence or not s:
            continue
        if line[0] in " \t":
            if out and out[-1]["span"][-1] == i - 1:
                out[-1]["span"].append(i)
            continue
        if s.startswith(("#", "<!--", "|", "---")) or HEADER.match(s):
            continue
        text, mk = split_marker(line)
        out.append({"n": i, "text": text, "marker": mk, "span": [i]})
    return out


_git_dates = {}


def first_seen(path, text):
    """When an unmarked line started: the file's last git commit, else the day guild first saw it."""
    if path not in _git_dates:
        r = subprocess.run(["git", "-C", os.path.dirname(path), "log", "-1", "--format=%as", "--", os.path.basename(path)],
                           capture_output=True, text=True)
        _git_dates[path] = r.stdout.strip() if r.returncode == 0 else ""
    if _git_dates[path]:
        return datetime.date.fromisoformat(_git_dates[path])
    try:
        seen = json.load(open(SEEN))
    except (OSError, ValueError):
        seen = {}
    key = hashlib.sha1(f"{short(path)}\n{text.strip()}".encode()).hexdigest()[:16]
    if key not in seen:
        seen[key] = today().isoformat()
        try:
            json.dump(seen, open(SEEN, "w"), indent=1)
        except OSError:
            pass
    return datetime.date.fromisoformat(seen[key])


def state(path, e, now=None):
    """{"tier", "since", "age", "stale", "check", "unmarked"} for one entry."""
    now = now or today()
    mk = e["marker"]
    tier, check = (mk["tier"], mk.get("check", "")) if mk else ("aging", "")
    if tier not in TIERS:
        tier = "aging"
    try:
        since = datetime.date.fromisoformat(mk["date"]) if mk else first_seen(path, e["text"])
    except ValueError:
        since = now
    age = (now - since).days
    stale = TIERS[tier] is not None and age > TIERS[tier]
    return {"tier": tier, "since": since.isoformat(), "age": age, "stale": stale,
            "check": check or "is it still true?", "unmarked": mk is None}


def words(text):
    return len(WORD.findall(text))


def tokens(text):
    return int(round(words(text) * 1.3))


# ── what quests load ──────────────────────────────────────────────────────────

def render(path, now=None):
    """The file as a quest reads it: archived lines are already gone, markers come out, stale lines
    still load but carry a flag so the quest treats them with care."""
    lines = read(path)
    stale = 0
    for e in entries(lines):
        st = state(path, e, now)
        text = e["text"]
        if st["stale"]:
            stale += 1
            text += f"  [stale: {st['tier']} since {st['since']}, check: {st['check']} Treat with care.]"
        lines[e["n"] - 1] = text
    lines = [split_marker(l)[0] if MARK.search(l) else l for l in lines]
    out = "\n".join(lines)
    if stale:
        out = (f"<!-- {stale} line{'s' if stale != 1 else ''} below {'are' if stale != 1 else 'is'} stale: still the "
               f"guildmaster's word, but check before you rely on {'them' if stale != 1 else 'it'}. -->\n") + out
    return out


def repo_cost(now=None):
    """{repo: tokens} a quest on that repo loads: lessons.md (the quartermaster reads it for every
    brief) plus the repo's vision, both as rendered."""
    base = tokens(render(LESSONS, now)) if os.path.isfile(LESSONS) else 0
    out = {}
    for f in files():
        if f != LESSONS:
            out[os.path.basename(f)[:-3]] = base + tokens(render(f, now))
    out["(any other repo)"] = base
    return out


# ── the weekly check ──────────────────────────────────────────────────────────

def scan(now=None):
    """[(path, entry, state)] for every rule line in every live file."""
    return [(f, e, state(f, e, now)) for f in files() for e in entries(read(f))]


def similarity(a, b):
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    j1 = len(sa & sb) / len(sa | sb)
    ga, gb = set(zip(a, a[1:])), set(zip(b, b[1:]))
    j2 = len(ga & gb) / len(ga | gb) if ga and gb else 0.0
    return max(j1, (j1 + j2) / 2 if j2 else j1, 0.8 * len(sa & sb) / min(len(sa), len(sb)))


def dups(threshold=0.6, min_words=6):
    """[(score, (file, n, text), (file, n, text))]: near-duplicate rules across lessons and visions."""
    pool = []
    for f in files():
        for e in entries(read(f)):
            text = BULLET.sub("", e["text"].strip())
            ws = [w.lower() for w in WORD.findall(text)]
            if len(ws) >= min_words:
                pool.append((short(f), e["n"], text, ws))
    pairs = []
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            sc = similarity(pool[i][3], pool[j][3])
            if sc >= threshold:
                pairs.append((sc, pool[i][:3], pool[j][:3]))
    return sorted(pairs, key=lambda p: -p[0])


def summary(now=None):
    """One line for guild tidy: stale lines, duplicates, the biggest load."""
    if not files():
        return "lore: no lessons.md and no visions yet"
    stale = sum(1 for _, _, st in scan(now) if st["stale"])
    cost = repo_cost(now)
    top = max(cost.items(), key=lambda kv: kv[1])
    pairs = len(dups())
    return (f"lore: {stale} stale line{'s' if stale != 1 else ''}, {pairs} duplicate pair{'s' if pairs != 1 else ''}, "
            f"~{top[1]} tokens per quest on {top[0]}; guild lore check lists them with file:line")


def check(now=None):
    if not files():
        print("no lore yet: lessons.md and visions/<repo>.md are empty")
        return
    rows = scan(now)
    for f in files():
        mine = [(e, st) for p, e, st in rows if p == f]
        stale = [(e, st) for e, st in mine if st["stale"]]
        print(f"== {short(f)}: {len(mine)} lines, ~{tokens(render(f, now))} tokens, {len(stale)} stale")
        for e, st in stale:
            how = " (no marker)" if st["unmarked"] else ""
            print(f"  stale  {short(f)}:{e['n']}  {st['tier']} since {st['since']}, {st['age']}d{how}; "
                  f"check: {st['check']}  {e['text'].strip()[:80]}")
    pairs = dups()
    if pairs:
        print("\nduplicates (keep one owner per rule, archive the other):")
        for sc, a, b in pairs:
            print(f"  {sc:.2f}  {a[0]}:{a[1]}  {a[2][:70]}\n        {b[0]}:{b[1]}  {b[2][:70]}")
    print("\ntokens a quest loads, per repo (lessons.md + the repo's vision):")
    for repo, t in sorted(repo_cost(now).items(), key=lambda kv: -kv[1]):
        print(f"  {repo:<24} ~{t}")
    if any(st["stale"] for _, _, st in rows):
        print('\nfor each stale line: guild lore refresh <file:line> "<what you checked and saw>"'
              '\n                  or guild lore archive <file:line> "<why it no longer holds>"')


# ── refresh, archive, mark ────────────────────────────────────────────────────

def log(entry):
    entry["at"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def target(spec):
    """(path, lines, entry) for 'lessons.md:4'."""
    name, _, n = spec.rpartition(":")
    if not name or not n.isdigit():
        raise SystemExit(f"give a place like lessons.md:4 or visions/api.md:7, got {spec!r}")
    path = resolve(name)
    lines = read(path)
    e = next((x for x in entries(lines) if x["n"] == int(n)), None)
    if not e:
        raise SystemExit(f"{short(path)}:{n} is not a rule line (a heading, a blank, a child line or past the end); "
                         f"guild lore check prints the right numbers")
    return path, lines, e


def refresh(spec, evidence, now=None):
    evidence = (evidence or "").strip()
    if len(evidence) < 12:
        raise SystemExit('refresh needs evidence you can name: what you checked and what you saw, e.g. '
                         '"ran the quest flow on api, --ticket is still required"')
    path, lines, e = target(spec)
    old = e["marker"] or {"tier": "aging"}
    if old["tier"] not in TIERS:
        old["tier"] = "aging"
    lines[e["n"] - 1] = f"{e['text']}  {marker(old['tier'], now, old.get('check', ''))}"
    write(path, lines)
    log({"action": "refresh", "file": short(path), "line": e["n"], "tier": old["tier"], "from": old.get("date", ""),
         "evidence": evidence, "text": e["text"].strip()})
    return f"refreshed {short(path)}:{e['n']} ({old['tier']}, dated {(now or today()).isoformat()})"


def archive_name(path):
    return path[:-3] + ".archive.md" if path.endswith(".md") else path + ".archive.md"


def archive(spec, reason, confirmed_by="", now=None):
    reason = (reason or "").strip()
    if not reason:
        raise SystemExit("archive needs a reason: why the line no longer holds")
    path, lines, e = target(spec)
    if e["marker"] and e["marker"]["tier"] == "pinned" and not confirmed_by:
        board = ask_guildmaster(path, e, reason)
        return (f"{short(path)}:{e['n']} is pinned: only the guildmaster archives it. It is on the docket "
                f"(board {board}); the line moves when they say yes.")
    ap = archive_name(path)
    new = not os.path.exists(ap)
    with open(ap, "a", encoding="utf-8") as f:
        if new:
            f.write(f"# Archive of {os.path.basename(path)}\n\nLines moved out of the live file. Quests never read this file.\n")
        f.write(f"\n<!-- {(now or today()).isoformat()}, was line {e['n']}; reason: {reason}"
                + (f"; confirmed by: {confirmed_by}" if confirmed_by else "") + " -->\n")
        for k in e["span"]:
            f.write(lines[k - 1] + "\n")
    write(path, [l for i, l in enumerate(lines, 1) if i not in e["span"]])
    log({"action": "archive", "file": short(path), "line": e["n"], "lines": len(e["span"]), "reason": reason,
         "confirmed_by": confirmed_by, "text": e["text"].strip()})
    return f"archived {short(path)}:{e['n']} -> {short(ap)} (line numbers below it moved up)"


def archive_text(name, text, reason, confirmed_by):
    """The docket's yes on a pinned line: find it by its text (line numbers may have moved) and archive it."""
    path = resolve(name)
    e = next((x for x in entries(read(path)) if x["text"].strip() == text.strip()), None)
    if not e:
        return "the line is no longer in the file"
    return archive(f"{short(path)}:{e['n']}", reason, confirmed_by)


def mark(spec, tier, check=""):
    if tier not in TIERS:
        raise SystemExit(f"tier is one of {', '.join(TIERS)}")
    if tier == "perishable" and not check:
        raise SystemExit('a perishable line says what to check: --check "<what to verify>"')
    path, lines, e = target(spec)
    lines[e["n"] - 1] = f"{e['text']}  {marker(tier, None, check)}"
    write(path, lines)
    log({"action": "mark", "file": short(path), "line": e["n"], "tier": tier,
         "was": (e["marker"] or {}).get("tier"), "text": e["text"].strip()})
    return f"marked {short(path)}:{e['n']} {tier}"


def ask_guildmaster(path, e, reason):
    """A board under the 'lessons' pseudo quest: archive this pinned line, or keep it."""
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import contextlib
    import io
    import wartable
    qdir = os.path.join(GUILD_HOME, "quests", BOARD_QUEST)
    if not os.path.isdir(qdir):
        os.makedirs(qdir)
        json.dump({"slug": BOARD_QUEST, "repo": "lessons", "harness": "", "model": "", "pseudo": True},
                  open(os.path.join(qdir, "meta.json"), "w"))
        open(os.path.join(qdir, "status"), "w").write("working\tlessons waiting for you\t\n")
    board = "lore-" + hashlib.sha1(f"{short(path)}\n{e['text']}".encode()).hexdigest()[:8]
    if os.path.isdir(os.path.join(qdir, "boards", board)):
        return board
    esc = wartable._esc
    page = (f'<!doctype html><html><head><meta charset="utf-8"><title>Archive a pinned line</title></head><body>'
            f'<h1>Archive a pinned line?</h1><p class="lead">{esc(BULLET.sub("", e["text"].strip()))}</p>'
            f'<p>From <code>{esc(short(path))}:{e["n"]}</code>, pinned on {esc(e["marker"]["date"])}.</p>'
            f'<h2>Why the quartermaster wants it gone</h2><p>{esc(reason)}</p>'
            f'<p class="lead">Archive moves it to {esc(short(archive_name(path)))}; nothing is deleted. '
            f'Quests stop reading it.</p></body></html>')
    tmp = os.path.join(GUILD_HOME, ".lore-tmp")
    os.makedirs(tmp, exist_ok=True)
    json.dump({"questions": [{"id": "lore", "title": "Archive this pinned line?", "type": "single", "options": [
        {"id": "archive", "label": "Archive", "why": "it no longer holds; quests stop reading it"},
        {"id": "keep", "label": "Keep", "why": "it still holds; it stays pinned"}]}]},
        open(os.path.join(tmp, "decisions.json"), "w"))
    open(os.path.join(tmp, "page.html"), "w").write(page)
    with contextlib.redirect_stdout(io.StringIO()):
        wartable.cmd_open({"quest": BOARD_QUEST, "id": board, "html": os.path.join(tmp, "page.html"),
                           "decisions": os.path.join(tmp, "decisions.json"),
                           "title": f"Archive pinned: {e['text'].strip()[:50]}", "no_open": True})
    bpath = os.path.join(qdir, "boards", board, "board.json")
    meta = json.load(open(bpath))
    meta.update(kind="lore-archive", file=short(path), text=e["text"], reason=reason)
    json.dump(meta, open(bpath, "w"), indent=2)
    return board


def decide(meta, decision):
    """The docket answered a lore-archive board."""
    if decision.get("answers", {}).get("lore") != "archive":
        return "kept"
    words_ = decision.get("message", "").strip()
    return archive_text(meta["file"], meta["text"], meta["reason"],
                        "the guildmaster on the docket" + (f": {words_}" if words_ else ""))


def main():
    a = sys.argv[1:]
    now = None
    if "--today" in a:
        i = a.index("--today")
        now = datetime.date.fromisoformat(a[i + 1])
        del a[i:i + 2]
    if not a:
        raise SystemExit(__doc__)
    cmd = a[0]
    if cmd == "check":
        return check(now)
    if cmd == "refresh" and len(a) >= 3:
        return print(refresh(a[1], " ".join(a[2:]), now))
    if cmd == "archive" and len(a) >= 3:
        return print(archive(a[1], " ".join(a[2:]), now=now))
    if cmd == "mark" and len(a) >= 3:
        chk = a[a.index("--check") + 1] if "--check" in a else ""
        return print(mark(a[1], a[2], chk))
    if cmd == "render" and len(a) == 2:
        return print(render(resolve(a[1]), now))
    if cmd == "read":
        parts = [render(LESSONS, now)] if os.path.isfile(LESSONS) else []
        if len(a) > 1 and os.path.isfile(os.path.join(VISIONS, f"{os.path.basename(a[1].rstrip('/'))}.md")):
            parts.append(render(os.path.join(VISIONS, f"{os.path.basename(a[1].rstrip('/'))}.md"), now))
        return print("\n\n".join(parts) or "no lessons and no vision yet")
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
