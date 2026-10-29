#!/usr/bin/env python3
"""Housekeeping, so guild stays fast as the months go by.

  tidy.py run [--dry-run]    rotate old events, purge the dead pages of closed quests, print what was done
  tidy.py maybe              the same, at most once a month (the war table server calls this)
  tidy.py purge <quest dir>  purge one closed quest now (guild close does this)

- events.log: lines older than EVENT_DAYS move to events/YYYY-MM.log. Only the oldest lines at
  the top of the file move, so every reader's byte cursor (guild wait, one per quartermaster)
  is shifted by exactly the bytes removed and nothing is replayed or missed. Readers that need
  history (log, retro, lessons, treasury, PR lookup) read the monthly files too: eventlog.lines().
- closed quests: a closed quest's board links already 404, so its pages and pictures are dead
  weight. Every board's HTML, screenshots, uploads and design folders are deleted the moment the
  quest closes (and on every run, for the ones closed before this rule). The small files history
  reads stay: meta, ledger, grade, status, brief, rules, the certificate, and each board's json
  (title, questions, your answer), so costs, grades and decisions keep working.
"""
import glob
import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
EVENTS = os.path.join(GUILD_HOME, "events.log")
ARCHIVE_DIR = os.path.join(GUILD_HOME, "events")
QUEST_ARCHIVE = os.path.join(GUILD_HOME, "quests", "_archive")
STAMP = os.path.join(GUILD_HOME, ".tidy-at")
EVENT_DAYS, EVERY_DAYS = 30, 30
DEAD_DIRS = ("shots", "design", "design-v2")      # whole folders a closed quest does not need


def rotate_events(dry=False, days=EVENT_DAYS):
    """Move the oldest lines to monthly files; shift every cursor by the bytes removed."""
    if not os.path.exists(EVENTS):
        return 0
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    raw = open(EVENTS, "rb").read()
    lines = raw.split(b"\n")
    moved, removed = [], 0
    for line in lines[:-1]:                       # the old lines at the top only
        stamp = line.split(b"\t", 1)[0].decode(errors="ignore")
        if not stamp or stamp >= cutoff:
            break
        moved.append(line)
        removed += len(line) + 1
    if not moved or dry:
        return len(moved)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    by_month = {}
    for line in moved:
        by_month.setdefault(line[:7].decode(errors="ignore") or "unknown", []).append(line)
    for month, rows in by_month.items():
        with open(os.path.join(ARCHIVE_DIR, f"{month}.log"), "ab") as f:
            f.write(b"\n".join(rows) + b"\n")
    tmp = EVENTS + ".tmp"
    with open(tmp, "wb") as f:
        f.write(raw[removed:])
    os.replace(tmp, EVENTS)
    for cursor in glob.glob(os.path.join(GUILD_HOME, ".wait-cursor*")):
        try:
            old = int(open(cursor).read().strip() or 0)
        except (OSError, ValueError):
            continue
        open(cursor, "w").write(str(max(0, old - removed)))
    return len(moved)


def closed_at(path):
    """A closed quest's folder ends in the close time: <slug>-YYYYmmddHHMMSS."""
    tail = os.path.basename(path).rsplit("-", 1)[-1]
    try:
        return datetime.strptime(tail, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def purge_quest(q, dry=False):
    """Delete one closed quest's dead pages and pictures. Returns the bytes it frees.

    Inside a board, only the json survives (board.json, decisions.json, decision.json): that is
    the history the ledger and the retro read. The page, its screenshots and uploads go.
    """
    freed = 0

    def drop(path):
        nonlocal freed
        if not os.path.lexists(path):
            return
        freed += size_of(path) if os.path.isdir(path) else os.path.getsize(path)
        if dry:
            return
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)

    for d in DEAD_DIRS:
        drop(os.path.join(q, d))
    drop(os.path.join(q, "files.tar.gz"))             # what an older guild packed instead of deleting
    boards = os.path.join(q, "boards")
    if os.path.isdir(boards):
        for b in os.listdir(boards):
            bd = os.path.join(boards, b)
            if not os.path.isdir(bd):
                continue
            for name in os.listdir(bd):
                if not name.endswith(".json"):
                    drop(os.path.join(bd, name))
    return freed


def purge_quests(dry=False):
    """Every closed quest: (quests touched, bytes freed)."""
    touched, freed = [], 0
    for q in sorted(glob.glob(os.path.join(QUEST_ARCHIVE, "*"))):
        if not os.path.isdir(q):
            continue
        n = purge_quest(q, dry)
        if n:
            touched.append(os.path.basename(q))
            freed += n
    return touched, freed


def size_of(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def run(dry=False):
    before = size_of(GUILD_HOME)
    events = rotate_events(dry)
    quests, freed = purge_quests(dry)
    after = size_of(GUILD_HOME)
    if not dry:
        open(STAMP, "w").write(time.strftime("%Y-%m-%dT%H:%M:%S"))
    verb = "would move" if dry else "moved"
    print(f"events: {verb} {events} lines older than {EVENT_DAYS} days to {ARCHIVE_DIR}/")
    print(f"closed quests: {'would free' if dry else 'freed'} {freed / 1024 / 1024:.1f} MB of dead pages and pictures "
          f"in {len(quests)} quest{'s' if len(quests) != 1 else ''}"
          + (f" ({', '.join(quests[:5])}{'...' if len(quests) > 5 else ''})" if quests else ""))
    if not dry:
        print(f"guild home: {before // 1024 // 1024} MB -> {after // 1024 // 1024} MB")


def maybe():
    try:
        last = datetime.fromisoformat(open(STAMP).read().strip())
    except (OSError, ValueError):
        last = None
    if last and datetime.now() - last < timedelta(days=EVERY_DAYS):
        return
    run()


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["run"])[0]
    if cmd == "run":
        run("--dry-run" in sys.argv)
    elif cmd == "maybe":
        maybe()
    elif cmd == "purge" and len(sys.argv) > 2:
        print(f"freed {purge_quest(sys.argv[2]) / 1024 / 1024:.1f} MB")
    else:
        raise SystemExit(__doc__)
