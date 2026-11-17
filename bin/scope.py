#!/usr/bin/env python3
"""The trial's scope check: review findings sorted against what the guildmaster agreed.

The reviewer finds problems; fixing all of them lets each round add a little more (a new
option, a guarantee, an abstraction, a refactor, the same theme with more machinery) until
the PR is bigger than the plan. So each finding is sorted:

  in scope   completes or corrects what was agreed: a bug in the new code, a missing test
             for agreed behaviour, a security hole in the new code. The adventurer fixes it.
  expansion  adds something not agreed, or is destructive. Not fixed: it becomes one short
             decision card for the guildmaster. Yes adds it to plan.md; no records it as a
             follow-up on the campaign board (guild todo).

Labels like "security" or "required" are evidence on the card, never a reason to widen scope.

    scope.py sort <quest-dir> <findings.json>     sort one review round, record it, open the cards
    scope.py answer <quest-dir> <id> yes|no       record an answer by hand (cards are read on their own;
                                                  inside a quest only "no" is allowed)
    scope.py report <quest-dir>                   the counts for trial.md
    scope.py status <quest-dir>                   exit 1 while an expansion waits for an answer

findings.json: {"findings": [{"id", "file", "line", "summary", "change", "agreed", "theme",
  "labels", "destructive", "wants", "smallest", "if_yes", "if_no", "recommend", "why"}]}
  change    what the fix does: fix | test | add | refactor | remove
  agreed    the plan step or acceptance line it completes, quoted; empty when there is none
"""
import datetime
import json
import os
import re
import subprocess
import sys

BIN = os.path.dirname(os.path.realpath(__file__))
GUILD = os.path.join(BIN, "guild")
CHANGES = ("fix", "test", "add", "refactor", "remove")
CARD_PARTS = ("Agreed", "The review wants", "Smallest option", "If yes", "If no", "Recommendation")


def now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[`*_>\"'#\-]", " ", str(text or ""))).strip().lower()


def agreed_text(qdir):
    """What the guildmaster agreed: plan.md, the sealed acceptance items, and the brief."""
    parts = []
    for name in ("plan.md", "brief.md"):
        p = os.path.join(qdir, name)
        if os.path.exists(p):
            parts.append(open(p).read())
    try:
        for item in json.load(open(os.path.join(qdir, "acceptance.json"))).get("items", []):
            parts.append(item.get("text") or item.get("run") or "")
    except (OSError, ValueError):
        pass
    return norm("\n".join(parts))


def classify(f, agreed, seen_themes):
    """(scope, reason). Labels are never read here: they are evidence, not authority."""
    change = f.get("change")
    if change == "remove" or f.get("destructive"):
        return "expansion", "destructive: it removes or rewrites what exists"
    if change in ("add", "refactor"):
        return "expansion", f"{change}: not part of what was agreed"
    quote = norm(f.get("agreed"))
    if not quote:
        return "expansion", "it points at nothing agreed"
    if quote not in agreed:
        return "expansion", "the agreed line it quotes is not in the plan, brief or acceptance"
    theme = norm(f.get("theme"))
    if theme and theme in seen_themes:
        return "expansion", f"theme '{f['theme']}' was fixed in round {seen_themes[theme]} and came back"
    return "in", f"completes: {f['agreed']}"


def validate(spec):
    items = spec.get("findings") if isinstance(spec, dict) else None
    if not isinstance(items, list):
        raise SystemExit('scope: findings.json needs {"findings": [...]}')
    ids = set()
    for n, f in enumerate(items, 1):
        if not f.get("id") or not f.get("summary"):
            raise SystemExit(f"scope: finding {n} needs an id and a summary")
        if f["id"] in ids or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", str(f["id"])):
            raise SystemExit(f"scope: finding id '{f['id']}' is repeated or not a plain word")
        ids.add(f["id"])
        if f.get("change") not in CHANGES:
            raise SystemExit(f"scope: finding {f['id']}: change must be one of {', '.join(CHANGES)}")
    return items


def card_text(f, reason):
    """The five parts the guildmaster needs, short. Returns (question, detail)."""
    where = f"{f['file']}:{f['line']}" if f.get("file") and f.get("line") else f.get("file", "")
    labels = ", ".join(f.get("labels") or [])
    wants = f.get("wants") or f["summary"]
    rec = f.get("recommend") or "no"
    lines = [
        f"**Agreed:** {f.get('agreed') or 'nothing in the plan, brief or acceptance covers this'}",
        f"**The review wants:** {wants}" + (f" ({where})" if where else "")
        + (f". Labelled {labels}: evidence, not a reason to widen scope" if labels else ""),
        f"**Smallest option:** {f.get('smallest') or 'leave it out of this PR'}",
        f"**If yes:** {f.get('if_yes') or 'it is added to the plan and built in this PR'}",
        f"**If no:** {f.get('if_no') or 'nothing changes here; it is kept as a follow-up idea'}",
        f"**Recommendation:** {rec}" + (f", {f['why']}" if f.get("why") else ""),
        f"Why this is a question: {reason}.",
    ]
    return f"Add to this PR? {wants}"[:200], "\n\n".join(lines)


def card_args(f, reason, board):
    question, detail = card_text(f, reason)
    rec = "yes" if (f.get("recommend") or "no") == "yes" else "no"
    return ["ask", question, "--detail", detail, "--id", board, "--title", f"Scope: {f['id']}",
            "--option", "yes=Yes, add it to the plan: build it in this PR",
            "--option", "no=No, keep it as a follow-up: the PR stays as agreed",
            "--recommend", rec]


def ask(argv):
    """One card on the war table through guild ask. Returns (ok, message)."""
    r = subprocess.run([GUILD, *argv], capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def load(qdir):
    try:
        return json.load(open(os.path.join(qdir, "scope.json")))
    except (OSError, ValueError):
        return {"rounds": 0, "findings": []}


def save(qdir, data):
    json.dump(data, open(os.path.join(qdir, "scope.json"), "w"), indent=2)


def add_to_plan(qdir, f):
    p = os.path.join(qdir, "plan.md")
    text = open(p).read() if os.path.exists(p) else ""
    head = "## Added during the trial"
    if head not in text:
        text = text.rstrip("\n") + f"\n\n{head}\n\nThe guildmaster said yes to these on the war table.\n"
    text = text.rstrip("\n") + f"\n- {f.get('wants') or f['summary']} (finding {f['id']}, {now()[:10]})\n"
    open(p, "w").write(text)


def add_follow_up(qdir, f):
    slug = os.path.basename(os.path.normpath(qdir))
    text = f"follow-up from {slug}: {f.get('wants') or f['summary']}"
    subprocess.run([sys.executable, os.path.join(BIN, "fleet.py"), "todo", "add", text],
                   capture_output=True, text=True, check=False)


def apply_answer(qdir, f, answer, how):
    f["answer"], f["answered_at"], f["answered_by"] = answer, now(), how
    if answer == "yes":
        add_to_plan(qdir, f)
    else:
        add_follow_up(qdir, f)


def sync(qdir, data):
    """Read the answers the guildmaster gave on the cards."""
    changed = False
    for f in data["findings"]:
        if f["scope"] != "expansion" or f.get("answer") or not f.get("board"):
            continue
        try:
            dec = json.load(open(os.path.join(qdir, "boards", f["board"], "decision.json")))
        except (OSError, ValueError):
            continue
        choice = (dec.get("answers") or {}).get("choice")
        if choice in ("yes", "no"):
            apply_answer(qdir, f, choice, "war table")
            changed = True
    if changed:
        save(qdir, data)
    return data


def cmd_sort(qdir, path):
    items = validate(json.load(open(path)))
    data = sync(qdir, load(qdir))
    rnd = data["rounds"] + 1
    agreed = agreed_text(qdir)
    seen = {}
    for f in data["findings"]:
        if f["scope"] == "in" and norm(f.get("theme")):
            seen.setdefault(norm(f["theme"]), f["round"])
    out = []
    for f in items:
        scope, reason = classify(f, agreed, seen)
        rec = dict(f, round=rnd, scope=scope, reason=reason, answer=None)
        if scope == "expansion":
            rec["board"] = f"scope-{rnd}-{f['id']}"
            ok, msg = ask(card_args(f, reason, rec["board"]))
            if not ok:          # a quest that may not ask (epic dagger): the safe answer is no
                rec["board"] = ""
                rec["card_refused"] = msg.splitlines()[-1] if msg else "guild ask failed"
                apply_answer(qdir, rec, "no", "card refused")
        out.append(rec)
    data["rounds"] = rnd
    data["findings"].extend(out)
    save(qdir, data)
    for r in out:
        tag = "fix in scope" if r["scope"] == "in" else (
            "follow-up (card refused)" if r.get("card_refused") else f"card {r['board']}, do not fix")
        print(f"{r['id']:<10} {tag:<28} {r['reason']}")
    print(report_line(data))


def counts(data):
    c = {"in": 0, "sent": 0, "yes": 0, "no": 0, "waiting": 0, "follow_ups": 0}
    for f in data["findings"]:
        if f["scope"] == "in":
            c["in"] += 1
            continue
        if f.get("board"):
            c["sent"] += 1
        if f.get("answer") == "yes":
            c["yes"] += 1
        elif f.get("answer") == "no":
            c["no"] += 1
            c["follow_ups"] += 1
        else:
            c["waiting"] += 1
    return c


def report_line(data):
    c = counts(data)
    return (f"Scope: {c['in']} fixed in scope, {c['sent']} expansion(s) sent to the guildmaster "
            f"({c['yes']} yes, {c['no']} no, {c['waiting']} waiting), {c['follow_ups']} follow-up(s) recorded")


def main():
    argv = sys.argv[1:]
    if len(argv) < 2:
        raise SystemExit(__doc__)
    cmd, qdir = argv[0], argv[1]
    if cmd == "sort" and len(argv) == 3:
        return cmd_sort(qdir, argv[2])
    data = sync(qdir, load(qdir))
    if cmd == "report":
        print(report_line(data))
        for f in data["findings"]:
            if f["scope"] == "expansion":
                print(f"- {f['id']}: {f.get('wants') or f['summary']} -> {f.get('answer') or 'waiting'}")
    elif cmd == "status":
        waiting = [f["id"] for f in data["findings"] if f["scope"] == "expansion" and not f.get("answer")]
        if waiting:
            print(f"scope cards still wait for the guildmaster: {', '.join(waiting)} (guild board wait <id>)")
            sys.exit(1)
    elif cmd == "answer" and len(argv) == 4 and argv[3] in ("yes", "no"):
        hit = [f for f in data["findings"] if f["id"] == argv[2] and f["scope"] == "expansion"]
        if not hit:
            raise SystemExit(f"scope: no expansion '{argv[2]}'")
        f = hit[-1]
        if argv[3] == "yes" and os.environ.get("GUILD_QUEST"):
            raise SystemExit("scope: only the guildmaster widens the plan; the card on the war table asks them")
        if f.get("answer"):
            raise SystemExit(f"scope: {f['id']} already answered {f['answer']}")
        apply_answer(qdir, f, argv[3], "by hand")
        save(qdir, data)
        print(f"{f['id']}: {argv[3]}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
