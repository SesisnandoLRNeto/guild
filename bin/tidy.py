#!/usr/bin/env python3
"""Housekeeping, so guild stays fast as the months go by.

  tidy.py run [--dry-run]    rotate old events, pack old closed quests, print what was done
  tidy.py maybe              the same, at most once a month (the war table server calls this)

- events.log: lines older than EVENT_DAYS move to events/YYYY-MM.log. Only the oldest lines at
  the top of the file move, so every reader's byte cursor (guild wait, one per quartermaster)
  is shifted by exactly the bytes removed and nothing is replayed or missed. Readers that need
  history (log, retro, lessons, treasury, PR lookup) read the monthly files too: eventlog.lines().
- closed quests older than PACK_DAYS: their boards, screenshots and design folders are packed
  into files.tar.gz inside the quest folder. meta, ledger, grade, status, brief, rules and the
  validation certificate stay as they are, so costs, grades and history keep working.
"""
import glob
import json
import os
import shutil
import sys
import tarfile
import time
from datetime import datetime, timedelta

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
EVENTS = os.path.join(GUILD_HOME, "events.log")
ARCHIVE_DIR = os.path.join(GUILD_HOME, "events")
QUEST_ARCHIVE = os.path.join(GUILD_HOME, "quests", "_archive")
STAMP = os.path.join(GUILD_HOME, ".tidy-at")
EVENT_DAYS, PACK_DAYS, EVERY_DAYS = 30, 60, 30
PACKED = ("boards", "shots", "design", "design-v2")


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


def pack_quests(dry=False, days=PACK_DAYS):
    cutoff = datetime.now() - timedelta(days=days)
    packed = []
    for q in sorted(glob.glob(os.path.join(QUEST_ARCHIVE, "*"))):
        when = closed_at(q)
        present = [d for d in PACKED if os.path.isdir(os.path.join(q, d))]
        if not when or when > cutoff or not present:
            continue
        packed.append(os.path.basename(q))
        if dry:
            continue
        with tarfile.open(os.path.join(q, "files.tar.gz"), "w:gz") as tar:
            for d in present:
                tar.add(os.path.join(q, d), arcname=d)
        for d in present:
            shutil.rmtree(os.path.join(q, d))
    return packed


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
    quests = pack_quests(dry)
    after = size_of(GUILD_HOME)
    if not dry:
        open(STAMP, "w").write(time.strftime("%Y-%m-%dT%H:%M:%S"))
    verb = "would move" if dry else "moved"
    print(f"events: {verb} {events} lines older than {EVENT_DAYS} days to {ARCHIVE_DIR}/")
    print(f"closed quests: {'would pack' if dry else 'packed'} {len(quests)} older than {PACK_DAYS} days"
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
    else:
        raise SystemExit(__doc__)
