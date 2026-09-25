#!/usr/bin/env python3
"""A dollar cap per quest.

  budget.py check <slug>     exit 0 under the cap (or no cap); exit 3 over it, after putting
                             one "raise or stop?" question on the docket for that cap
  budget.py show <slug>      spent / cap

The cap lives in the quest's meta.json ("budget", dollars). Spend comes from the ledger's
cost cache, so a check is cheap enough to run before every tool call (hooks/worker-guard.sh).
Claude Code's own --max-budget-usd only works in print mode, so guild enforces it here.
"""
import json
import os
import subprocess
import sys

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
BIN = os.path.dirname(os.path.realpath(__file__))
RAISES = {"raise10": 10, "raise25": 25, "raise50": 50}


def spend(slug):
    try:
        out = subprocess.run([sys.executable, os.path.join(BIN, "ledger.py"), "costs", "--max-age", "90"],
                             capture_output=True, text=True, timeout=30).stdout
        return float(json.loads(out).get(slug, 0))
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def meta_of(slug):
    return json.load(open(os.path.join(GUILD_HOME, "quests", slug, "meta.json")))


def check(slug):
    try:
        meta = meta_of(slug)
    except (OSError, ValueError):
        return 0
    cap = float(meta.get("budget") or 0)
    if not cap:
        return 0
    spent = spend(slug)
    if spent < cap:
        return 0
    qdir = os.path.join(GUILD_HOME, "quests", slug)
    flag = os.path.join(qdir, f".budget-asked-{cap:g}")
    board = open(flag).read().strip() if os.path.exists(flag) else ""
    if not board:
        board = ask(slug, spent, cap)
        open(flag, "w").write(board)
    print(f"Budget reached: this quest spent ${spent:.2f} of its ${cap:g} cap. The guildmaster has a "
          f"question on the docket. Run `guild board wait {board} --timeout 3600` now and do nothing "
          f"else until it is answered.")
    return 3


def ask(slug, spent, cap):
    """One docket question per cap: raise it, or stop the quest."""
    sys.path.insert(0, BIN)
    import wartable
    before = set(os.listdir(os.path.join(GUILD_HOME, "quests", slug, "boards"))) \
        if os.path.isdir(os.path.join(GUILD_HOME, "quests", slug, "boards")) else set()
    os.environ.setdefault("GUILD_BOARD_NO_OPEN", "")
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        wartable.cmd_ask({"quest": slug, "question": f"{slug} reached its ${cap:g} budget (spent ${spent:.2f}). Raise it or stop?",
                          "detail": "The adventurer's tools are paused until you answer. Raising adds to the cap and it carries on.",
                          "option": ["raise10=Raise by $10: finish the current step", "raise25=Raise by $25: room for the rest",
                                     "raise50=Raise by $50: a big piece is still left", "stop=Stop here: keep what is done"],
                          "recommend": "raise10", "title": f"Budget reached: {slug}"})
    bdir = os.path.join(GUILD_HOME, "quests", slug, "boards")
    new = sorted(set(os.listdir(bdir)) - before) if os.path.isdir(bdir) else []
    board = new[-1] if new else ""
    if board:
        path = os.path.join(bdir, board, "board.json")
        meta = json.load(open(path))
        meta["kind"] = "budget"
        json.dump(meta, open(path, "w"), indent=2)
    return board


def apply(slug, choice):
    """The docket answer to a budget question. Returns what happened, in words."""
    path = os.path.join(GUILD_HOME, "quests", slug, "meta.json")
    meta = json.load(open(path))
    cap = float(meta.get("budget") or 0)
    if choice in RAISES:
        meta["budget"] = cap + RAISES[choice]
        json.dump(meta, open(path, "w"), indent=2)
        return "raised", meta["budget"]
    return "stopped", cap


def main():
    cmd, slug = (sys.argv[1:3] + [None, None])[:2]
    if cmd == "check" and slug:
        sys.exit(check(slug))
    if cmd == "show" and slug:
        cap = float(meta_of(slug).get("budget") or 0)
        print(f"{slug}: spent ${spend(slug):.2f}" + (f" of ${cap:g}" if cap else ", no cap"))
        return
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
