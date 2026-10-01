#!/usr/bin/env python3
"""War table: a local board where the guildmaster decides, and the quest resumes.

An adventurer writes an HTML page (analysis, variants, before/after, whatever reads best)
plus an optional decisions.json. This server wraps that page with a side panel for choices,
a message and images. The reply is written to decision.json in the board folder, which the
waiting adventurer reads with `guild board wait`.

Everything is local: 127.0.0.1 only, no network calls, no accounts.
"""
import base64
import html as _html
import datetime
import http.server
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
EVENTS = os.path.join(GUILD_HOME, "events.log")
PORT_FILE = os.path.join(GUILD_HOME, ".wartable-port")
WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "web")
SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def board_dir(quest, board):
    if not SAFE.match(quest) or not SAFE.match(board):
        raise ValueError("bad name")
    return os.path.join(QUESTS, quest, "boards", board)


def record(quest, state, note):
    """Set the quest state and append an event, the same way the guild CLI does."""
    qdir = os.path.join(QUESTS, quest)
    if os.path.isdir(qdir):
        with open(os.path.join(qdir, "status"), "w") as f:
            f.write(f"{state}\t{note}\t{now()}\n")
    with open(EVENTS, "a") as f:
        f.write(f"{now()}\t{quest}\t{state}\t{note}\n")
    try:
        sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
        import notify
        threading.Thread(target=notify.on_event, args=(quest, state, note), daemon=True).start()
    except Exception:
        pass


def list_boards():
    out = []
    if not os.path.isdir(QUESTS):
        return out
    for quest in sorted(os.listdir(QUESTS)):
        bdir = os.path.join(QUESTS, quest, "boards")
        if not os.path.isdir(bdir):
            continue
        for board in sorted(os.listdir(bdir)):
            meta_path = os.path.join(bdir, board, "board.json")
            if not os.path.exists(meta_path):
                continue
            meta = json.load(open(meta_path))
            meta["answered"] = os.path.exists(os.path.join(bdir, board, "decision.json"))
            out.append(meta)
    out.sort(key=lambda m: (m["answered"], m.get("created", "")), reverse=False)
    return out


# Added to every board page: the parchment theme, after the page's own styles so it wins,
# and a light color scheme for Mermaid, so diagrams read on parchment.
THEME = (b'<meta name="color-scheme" content="light"><meta name="darkreader-lock">'   # dark-mode extensions leave the parchment alone
         b'<link rel="stylesheet" href="/icons.css"><link rel="stylesheet" href="/theme.css">'
         b'<script src="/lightbox.js" defer></script>'   # click a picture to zoom it or go full screen
         b'<script>addEventListener("pageshow",function(e){if(e.persisted)location.reload()});</script>'   # Back shows fresh state
         b'<script>(function(){var m=window.matchMedia;window.matchMedia=function(q){'
         b'return /prefers-color-scheme:\\s*dark/.test(q)?{matches:false,media:q,addEventListener:function(){},'
         b'removeEventListener:function(){},addListener:function(){},removeListener:function(){}}:m.call(window,q);};})();</script>')


# ── "At a glance": a plain header the war table puts on top of every quest page ──
# A report is written for whoever reads the code; this strip is for anyone: where the work
# stands, in words and as a path of steps, and the few numbers that matter.

GLANCE_CSS = """<style>
.gg{font:14px/1.5 inherit;margin:0 0 26px;padding:16px 18px 14px;border:1px solid var(--line,#cdb88e);border-radius:6px;
  background:rgba(255,250,235,.55)}
.gg-top{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;margin:0 0 12px;padding-right:48px}
.gg-top b{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim,#6e5a41)}
.gg-say{font-size:16px;font-weight:600}
.gg-say.bad{color:var(--bad,#a8322a)}.gg-say.turn{color:#9a5a0c}.gg-say.ok{color:var(--ok,#3f7d3a)}
.gg-path{display:flex;list-style:none;margin:0 0 14px;padding:0;counter-reset:s}
.gg-path li{flex:1;position:relative;text-align:center;font-size:12px;color:var(--dim,#6e5a41);padding-top:26px;min-width:0}
.gg-path li::before{content:"";position:absolute;top:4px;left:50%;width:16px;height:16px;margin-left:-8px;border-radius:50%;
  border:2px solid #b9a37a;background:#f6ecd2;z-index:1}
.gg-path li::after{content:"";position:absolute;top:11px;left:-50%;width:100%;height:2px;background:#cdb88e}
.gg-path li:first-child::after{display:none}
.gg-path li.done{color:var(--text,#2d2216)}.gg-path li.done::before{background:var(--ok,#3f7d3a);border-color:var(--ok,#3f7d3a)}
.gg-path li.done::after,.gg-path li.now::after{background:var(--ok,#3f7d3a)}
.gg-path li.now{color:var(--text,#2d2216);font-weight:700}.gg-path li.now::before{border-color:#b5651d;background:#f3d9a8;box-shadow:0 0 0 4px rgba(217,164,65,.3)}
.gg-path li.stuck::before{border-color:var(--bad,#a8322a);background:#f2c4bb}
.gg-path li.skip{opacity:.45}
.gg-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}
.gg-tile{background:rgba(255,255,255,.35);border:1px solid var(--line,#cdb88e);border-radius:4px;padding:7px 10px}
.gg-tile span{display:block;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--dim,#6e5a41)}
.gg-tile b{font-size:17px}.gg-go{text-decoration:none;color:inherit;border-color:#0d6b63;background:rgba(13,107,99,.08)}
.gg-go:hover{background:rgba(13,107,99,.16)}.gg-tile i{display:block;font-size:11.5px;color:var(--dim,#6e5a41);font-style:normal}
.gw{margin-top:12px;border-top:1px dashed var(--line,#cdb88e);padding-top:10px}
.gw-head{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim,#6e5a41);margin-bottom:6px}
.gw-head i{text-transform:none;letter-spacing:0;font-style:italic}
.gw-row{display:grid;grid-template-columns:90px 1fr;gap:10px;font-size:14px;padding:2px 0}
.gw-row b{font-variant:small-caps;color:#8a4b12}
@media (max-width:640px){.gg-path li{font-size:10.5px}}
</style>"""


def glance(quest):
    """The header's HTML for one quest, or "" when there is nothing to say."""
    qdir = os.path.join(QUESTS, quest)
    if not os.path.exists(os.path.join(qdir, "meta.json")):
        return ""
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import ledger
    import prs as prmod
    try:
        q = ledger.load(qdir)
    except (OSError, ValueError):
        return ""
    meta, state, note = q["meta"], q["state"], q["note"]
    pr = prmod.by_slug().get(quest) or {}
    if pr.get("error"):
        pr = {}
    grade = load_json_safe(os.path.join(qdir, "grade.json"))
    edd = q.get("edd") or {}
    planned = os.path.exists(os.path.join(qdir, "plan.md"))
    built = bool(edd.get("runs")) or state in ("done", "trial-pass", "trial-skip") or bool(pr)
    checks_ok = edd.get("last_green") or (not edd.get("checks") and built)
    trial_ok = q.get("trial") in ("pass", "skip")
    steps = [("Asked", True), ("Plan", planned if meta.get("phase") or planned else None), ("Build", built),
             ("Checks", bool(checks_ok) and built), ("Trial", trial_ok), ("PR open", bool(pr)),
             ("Merged", pr.get("state") == "merged")]
    now = next((i for i, (_, ok) in enumerate(steps) if ok is False), None)
    stuck = state in ("blocked", "failed", "stopped", "checks-red")
    items = []
    for i, (name, ok) in enumerate(steps):
        cls = "skip" if ok is None else "done" if ok and (now is None or i < now) else ""
        if i == now:
            cls = "now stuck" if stuck else "now"
        items.append(f'<li class="{cls}">{_html.escape(name)}</li>')

    ticket = meta.get("ticket", "")
    if pr.get("state") == "merged":
        say, tone = "Merged. This work is in the main branch.", "ok"
    elif stuck:
        say, tone = {"blocked": "Blocked", "failed": "Failed", "stopped": "Stopped without a report",
                     "checks-red": "Checks are failing"}[state] + (f": {note}" if note else "."), "bad"
    elif state == "needs-decision":
        say, tone = "Waiting for your decision on the war table.", "turn"
    elif state in ("done", "trial-pass", "trial-skip") and pr.get("state") in ("open", "draft"):
        say, tone = f"Finished. PR #{pr.get('number')} waits for review" + (" (changes requested)." if pr.get("review") == "changes requested" else "."), "turn"
    elif state in ("done", "trial-pass", "trial-skip"):
        say, tone = "Finished." + ("" if grade else " Grade it on the right."), "ok"
    elif state == "held":
        say, tone = "On hold until a date you set.", ""
    else:
        say, tone = "An agent is working on it now.", ""

    tiles = []
    cost = q.get("cost") or 0
    est = " (estimated)" if q.get("unknown") else ""
    tiles.append(("Cost", ledger.money(cost), f"API price{est}"))
    dur = ledger.duration(q)
    if dur:
        tiles.append(("Time open", dur, f"first to last reply, {q.get('messages', 0)} replies"))
    if edd.get("checks"):
        tiles.append(("Checks", "passing" if edd.get("last_green") else "failing" if edd.get("runs") else "not run",
                      f"{edd['checks']} automatic, {edd.get('manual', 0)} by review"))
    if q.get("trial"):
        tiles.append(("Trial", {"pass": "passed", "skip": "skipped"}.get(q["trial"], q["trial"]), "review before the PR"))
    if pr:
        tiles.append(("Pull request", f"#{pr.get('number')} {pr.get('state')}",
                      ", ".join(x for x in [pr.get("review", ""), ("NO CI RUN" if pr.get("checks") == "none" else f"checks {pr['checks']}") if pr.get("checks") else ""] if x)))
    v = scenarios_mod().summary(quest)
    if v["exists"]:
        word = ("certified" if v["certified"] else "out of date, run again" if v["stale"]
                else f"{v['fail']} failed" if v["fail"] else f"{v['open']} to run")
        tiles.append(("Validation", f"{v['pass']}/{v['total']} passed", word + ": open the checklist",
                      f"/q/{quest}/validate"))
    tiles.append(("Your grade", f"{grade['grade']}/5" if grade and grade.get("grade") else "not yet",
                  (grade or {}).get("verdict", "") or "on the right side"))
    model = meta.get("model") or ""
    head = " · ".join(_html.escape(x) for x in [ticket, model, os.path.basename(meta.get("repo", ""))] if x)
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import why
    card = why.glance_html(quest)
    return (GLANCE_CSS + '<section class="gg" aria-label="At a glance">'
            f'<div class="gg-top"><b>At a glance</b><span class="gg-say {tone}">{_html.escape(say)}</span>'
            f'<span style="margin-left:auto;font-size:12px;color:var(--dim,#6e5a41)">{head}</span></div>'
            f'<ol class="gg-path">{"".join(items)}</ol><div class="gg-tiles">'
            + "".join((f'<a class="gg-tile gg-go" href="{t[3]}" target="_top">' if len(t) > 3 else '<div class="gg-tile">')
                      + f'<span>{_html.escape(t[0])}</span><b>{_html.escape(str(t[1]))}</b><i>{_html.escape(t[2])}</i>'
                      + ("</a>" if len(t) > 3 else "</div>") for t in tiles)
            + "</div>" + card + "</section>")


def load_json_safe(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return None


def with_glance(body, quest):
    """Put the header right after <body>. A page can opt out with <meta name="guild-glance" content="off">."""
    low = body.lower()
    if b'name="guild-glance" content="off"' in low:
        return body
    try:
        strip = glance(quest).encode()
    except Exception:
        return body
    if not strip:
        return body
    i = low.find(b"<body")
    if i < 0:
        return strip + body
    j = low.find(b">", i) + 1
    return body[:j] + strip + body[j:]


def themed(html):
    low = html.lower()
    i = low.find(b"</head>")
    if i < 0:
        i = low.find(b"<body")
    return html[:i] + THEME + html[i:] if i >= 0 else THEME + html


# EDD on the result: every wrap-up asks the guildmaster for a grade and a verdict. The grades
# feed `guild retro`, which compares them by model, tier and harness.
GRADE_QUESTIONS = [
    {"id": "grade", "title": "Grade this work",
     "detail": "The result as delivered. Your grades teach the quartermaster which models to trust with what.",
     "type": "single", "options": [
         {"id": "5", "label": "5 · Legendary", "why": "excellent: merge as is, nothing to add"},
         {"id": "4", "label": "4 · Heroic", "why": "good: small notes, no rework"},
         {"id": "3", "label": "3 · Squire's work", "why": "fair: it works, but needs another pass"},
         {"id": "2", "label": "2 · Needs training", "why": "poor: misses part of the intent"},
         {"id": "1", "label": "1 · Cursed", "why": "wrong: not what was asked"}]},
    {"id": "verdict", "title": "What next?", "type": "single", "options": [
        {"id": "merge", "label": "To the treasury (ready to merge)", "why": "you review and merge the PR"},
        {"id": "changes", "label": "Back to the forge (needs changes)", "why": "your notes go back to the adventurer, who carries on"},
        {"id": "split", "label": "A new quest (split a follow-up)", "why": "this ships; the rest becomes a new quest"}]},
]


def grade_wrapup(quest, board, meta, decision):
    """Keep the grade beside the quest (it moves to the archive with it), log it, and when
    you ask for changes, hand your notes back to the adventurer."""
    ans = decision.get("answers", {})
    grade, verdict, msg = str(ans.get("grade", "")), ans.get("verdict", ""), decision.get("message", "")
    qdir = os.path.join(QUESTS, quest)
    if os.path.isdir(qdir):
        with open(os.path.join(qdir, "grade.json"), "w") as f:
            json.dump({"grade": int(grade) if grade.isdigit() else None, "verdict": verdict, "message": msg,
                       "board": board, "title": meta.get("title", ""), "at": now()}, f, indent=2)
    note = f"{grade or '?'}/5" + (f", {verdict}" if verdict else "") + (f": {msg[:80]}" if msg else "")
    with open(EVENTS, "a") as f:
        f.write(f"{now()}\t{quest}\tgraded\t{note}\n")
    if verdict in ("merge", "split"):
        threading.Thread(target=lambda: (time.sleep(3), sweep()), daemon=True).start()
    if verdict == "changes":
        send_back(quest, (f"The guildmaster reviewed your wrap-up ({meta.get('title', board)}): grade {grade}/5, "
                          f"changes needed. {msg or 'See the board for notes.'} Make the changes, run the trial again, "
                          f"post a new wrap-up, then report done."), f"changes asked on the wrap-up ({grade}/5)")


def send_back(quest, text, why):
    """Hand notes back to a quest's adventurer, bringing its session back first if its tab is closed."""
    guild = os.path.join(os.path.dirname(os.path.realpath(__file__)), "guild")
    record(quest, "working", why)
    revived = subprocess.run([guild, "revive", quest], capture_output=True, text=True).stdout
    if "revived" in revived:
        time.sleep(10)                      # let the session come up before typing into it
    subprocess.run([guild, "send", quest, text], capture_output=True)


def scenarios_mod():
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import scenarios
    return scenarios


def merge_blocked(quest, answers):
    """Why a "ready to merge" verdict cannot be accepted yet, or "" when it can."""
    if answers.get("verdict") != "merge":
        return ""
    sc = scenarios_mod()
    s = sc.summary(quest)
    if not s["exists"] or s["certified"]:
        return ""
    if s["stale"]:
        return (f"Not ready to merge yet: the validation certificate is for an older commit and the branch changed "
                f"since. Run the checklist again at /q/{quest}/validate.")
    return (f"Not ready to merge yet: the validation checklist has {s['fail']} failed and {s['open']} not run "
            f"(of {s['total']}). Run it at /q/{quest}/validate, or pick \"needs changes\".")


def answer_board(quest, board, payload):
    """Write the guildmaster's answer; the waiting adventurer picks it up with `guild board wait`."""
    d = board_dir(quest, board)
    if json.load(open(os.path.join(d, "board.json"))).get("wrapup"):
        why = merge_blocked(quest, payload.get("answers", {}))
        if why:
            raise ValueError(why)
    decision = {
        "answers": payload.get("answers", {}),
        "message": payload.get("message", ""),
        "attachments": payload.get("attachments", []),
        "ended": bool(payload.get("ended")),
        "at": now(),
    }
    with open(os.path.join(d, "decision.json"), "w") as f:
        json.dump(decision, f, indent=2)
    meta = json.load(open(os.path.join(d, "board.json")))
    if meta.get("wrapup"):
        grade_wrapup(quest, board, meta, decision)
        return
    if meta.get("kind") == "why":             # the guildmaster's own words on why this quest exists
        sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
        import why
        card = why.save(quest, decision)
        with open(EVENTS, "a") as f:
            f.write(f"{now()}\t{quest}\twhy\t{card.get('rule', '')[:100]}\n")
        text = ("The guildmaster wrote the Why card for this quest (also in why.json):\n" + why.as_text(card)
                + "\nCheck it against the ticket, the spec and the code before you go on. Where something contradicts "
                  "it or is missing, raise up to three short challenges on the war table (guild ask), each quoting the "
                  "source. Your plan and your wrap-up answer this card.")
        guild = os.path.join(os.path.dirname(os.path.realpath(__file__)), "guild")
        threading.Thread(target=lambda: subprocess.run([guild, "send", quest, text], capture_output=True), daemon=True).start()
        return
    if meta.get("kind") == "lesson":         # accepted lessons reach lessons.md, rejected ones are kept apart
        sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
        import lessons
        status = lessons.decide(meta["lesson"], decision["answers"].get("lesson", "reject"), decision.get("message", ""))
        record(quest, "working", f"lesson {status}: {meta.get('title', board)}")
        return
    if meta.get("kind") == "budget":         # raise the cap, or stop the quest
        sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
        import budget
        what, cap = budget.apply(quest, decision["answers"].get("choice", "stop"))
        if what == "raised":
            record(quest, "working", f"budget raised to ${cap:g}")
            nudge(quest, f"The guildmaster raised your budget to ${cap:g}. Carry on.")
        else:
            record(quest, "failed", f"stopped at the ${cap:g} budget" + (f": {decision['message']}" if decision["message"] else ""))
            nudge(quest, "The guildmaster stopped this quest at its budget. Commit what is done, report "
                         "`guild status <slug> failed \"stopped at budget\"` if you have not, and end your turn.")
        return
    picked = ", ".join(f"{k}={v}" for k, v in decision["answers"].items()) or "message only"
    record(quest, "working", f"war table answered ({meta.get('title', board)}): {picked}")
    if meta.get("held_until"):           # it stopped waiting when you held it: wake it up
        nudge(quest, f"Your held decision '{meta.get('title', board)}' is answered. Read it with "
                     f"`guild board wait {board}` and carry on.")


def nudge(quest, text):
    guild = os.path.join(os.path.dirname(os.path.realpath(__file__)), "guild")
    subprocess.run([guild, "send", quest, text], capture_output=True)


# ── the docket: every open decision on one page, one ruling per row ───────────
def board_questions(bdir, meta):
    qpath = os.path.join(bdir, "decisions.json")
    questions = json.load(open(qpath)).get("questions", []) if os.path.exists(qpath) else []
    return (GRADE_QUESTIONS + questions) if meta.get("wrapup") else questions


def drill_due():
    try:
        sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
        import rulebook
        d = rulebook.drill()
        return {"due": d["due"], "count": sum(1 for i in d["items"] if not i["answered"])}
    except Exception:
        return {"due": False, "count": 0}


def docket_items():
    today = datetime.date.today().isoformat()
    items, recent = [], []
    if not os.path.isdir(QUESTS):
        return {"open": [], "held": [], "recent": []}
    for quest in sorted(os.listdir(QUESTS)):
        qdir = os.path.join(QUESTS, quest)
        bdir = os.path.join(qdir, "boards")
        if not os.path.isdir(bdir):
            continue
        qmeta = {}
        try:
            qmeta = json.load(open(os.path.join(qdir, "meta.json")))
        except (OSError, ValueError):
            pass
        try:
            qstate = open(os.path.join(qdir, "status")).read().split("\t")[0]
        except OSError:
            qstate = ""
        for board in sorted(os.listdir(bdir)):
            d = os.path.join(bdir, board)
            try:
                meta = json.load(open(os.path.join(d, "board.json")))
            except (OSError, ValueError):
                continue
            base = {"quest": quest, "board": board, "title": meta.get("title", board), "subtitle": meta.get("subtitle", ""),
                    "created": meta.get("created", ""), "url": f"/b/{quest}/{board}/", "wrapup": bool(meta.get("wrapup")),
                    "ticket": qmeta.get("ticket", ""), "model": qmeta.get("model", ""), "pseudo": bool(qmeta.get("pseudo"))}
            dec = os.path.join(d, "decision.json")
            if meta.get("kind") == "budget" and not qmeta.get("budget") and not os.path.exists(dec):
                continue                                 # its cap was removed: nothing to raise any more
            if os.path.exists(dec):
                answer = json.load(open(dec))
                recent.append(dict(base, answers=answer.get("answers", {}), message=answer.get("message", ""), at=answer.get("at", "")))
                continue
            if qstate in ("done", "failed") and not meta.get("wrapup"):
                continue                     # the quest moved on: an old unanswered question is not a decision
            item = dict(base, questions=board_questions(d, meta), held_until=meta.get("held_until", ""),
                        held_note=meta.get("held_note", ""))
            items.append(item)
    held = [i for i in items if i["held_until"] and i["held_until"] > today]
    open_ = [i for i in items if i not in held]
    open_.sort(key=lambda i: (i["wrapup"], i["created"]))          # decisions first, then reviews
    held.sort(key=lambda i: i["held_until"])
    recent.sort(key=lambda i: i["at"], reverse=True)
    return {"open": open_, "held": held, "recent": recent[:12], "today": today, "drill": drill_due()}


def hold_board(quest, board, until, note=""):
    """Park a decision until a date. The adventurer stops waiting; the quartermaster brings it
    back on the date (guild wait emits held-due)."""
    d = board_dir(quest, board)
    path = os.path.join(d, "board.json")
    meta = json.load(open(path))
    if until:
        datetime.date.fromisoformat(until)       # refuses anything that is not a date
        meta["held_until"], meta["held_note"] = until, note
        meta.pop("held_announced", None)
    else:
        for k in ("held_until", "held_note", "held_announced"):
            meta.pop(k, None)
    json.dump(meta, open(path, "w"), indent=2)
    title = meta.get("title", board)
    if until:
        record(quest, "held", f"held until {until}: {title}" + (f" ({note})" if note else ""))
        nudge(quest, f"The guildmaster held the decision '{title}' until {until}"
                     + (f": {note}" if note else "") + ". Stop waiting on that board, park this part of the work, "
                     "and end your turn. You will be told when it is answered.")
    else:
        record(quest, "needs-decision", f"back on the docket: {title}")


def due_boards():
    """Held decisions whose date has come, each announced once. Prints one event line each."""
    today = datetime.date.today().isoformat()
    for item in docket_items()["open"]:
        if not item["held_until"]:
            continue
        path = os.path.join(board_dir(item["quest"], item["board"]), "board.json")
        meta = json.load(open(path))
        if meta.get("held_announced"):
            continue
        meta["held_announced"] = today
        json.dump(meta, open(path, "w"), indent=2)
        record(item["quest"], "needs-decision", f"held decision is due again: {item['title']}")


def fleet():
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import fleet as mod
    return mod


def campaign_action(action, body):
    """Buttons on the campaign board: jump to a tab, pin a card, add or finish a to-do."""
    f = fleet()
    socket_name = os.environ.get("GUILD_TMUX_SOCKET", "guild")
    if action == "story":                 # name the row these tickets sit in
        tickets = [t for t in body.get("tickets", []) if re.fullmatch(r"[A-Z][A-Z0-9]{1,9}-\d+", str(t))]
        if not tickets:
            raise ValueError("no tickets")
        f.name_story(str(body.get("name", ""))[:80].strip(), tickets)
        return {"ok": True, "did": "story named" if body.get("name") else "story name removed"}
    if action == "jump":
        tab, sid = body.get("tab", ""), body.get("session", "")
        if tab:
            if not SAFE.match(tab.replace(":", "-")):
                raise ValueError("bad tab")
            subprocess.run(["tmux", "-L", socket_name, "select-window", "-t", f"guild:{tab}"], check=True)
            return {"ok": True, "did": f"switched the cockpit to {tab}"}
        if sid and re.fullmatch(r"[0-9a-f-]{36}", sid):   # no tab: reopen the session in a new one
            guild = os.path.join(os.path.dirname(os.path.realpath(__file__)), "guild")
            subprocess.run([guild, "new", "--resume", sid], check=True, capture_output=True)
            return {"ok": True, "did": "reopened it in a new cockpit tab"}
        raise ValueError("nothing to jump to")
    if action == "close":                 # close the tab (the quest itself stays), or hide the card
        card_id, tab = body.get("id", ""), body.get("tab", "")
        if tab:
            wins = subprocess.run(["tmux", "-L", socket_name, "list-windows", "-t", "guild", "-F", "#{window_id}\t#W"],
                                  capture_output=True, text=True).stdout.splitlines()
            wid = [w.split("\t")[0] for w in wins if w.split("\t")[-1] == tab]
            if tab == "qm" or not wid:
                raise ValueError("that tab cannot be closed from here")
            subprocess.run(["tmux", "-L", socket_name, "kill-window", "-t", wid[0]], check=True)
            return {"ok": True, "did": f"closed the {tab} tab" + (" (the quest is kept: guild revive brings it back)" if card_id.startswith("quest:") else "")}
        f.hide(card_id)
        return {"ok": True, "did": "hidden from the board until it moves again"}
    if action == "pin":
        f.set_pin_key(body["id"], body.get("name", body["id"]), body.get("tab", ""), bool(body.get("on")))
        return {"ok": True}
    if action == "todo":
        items = f.todos()
        if body.get("add"):
            items.append({"text": str(body["add"])[:200], "done": False, "at": now()})
        elif body.get("done"):
            items[int(body["done"]) - 1]["done"] = True
        elif body.get("drop"):
            items.pop(int(body["drop"]) - 1)
        f.save_json(f.TODO, items)
        return {"ok": True}
    raise ValueError(action)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "wartable"

    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="text/html; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if ctype.startswith(("text/html", "application/json")):   # states change: never show a stale copy
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path in ("/", "/index.html", "/docket"):     # the docket is the war table's front page
                return self.send(200, open(os.path.join(WEB, "docket.html")).read())
            if path == "/docket.json":
                return self.send(200, json.dumps(docket_items()), "application/json")
            if path == "/boards":
                return self.send(200, self.render_index())
            if path in ("/theme.css", "/icons.css"):    # the guild look (and its icons) for every page
                with open(os.path.join(WEB, path.lstrip("/")), "rb") as f:
                    return self.send(200, f.read(), "text/css; charset=utf-8")
            if path == "/lightbox.js":
                with open(os.path.join(WEB, "lightbox.js"), "rb") as f:
                    return self.send(200, f.read(), "text/javascript; charset=utf-8")
            if path == "/campaign":        # the campaign board: every agent and ticket, as a kanban
                return self.send(200, open(os.path.join(WEB, "campaign.html")).read())
            if path in ("/rules", "/drill"):   # the rule book, and the weekly drill
                return self.send(200, open(os.path.join(WEB, path.strip("/") + ".html")).read())
            if path in ("/rules.json", "/drill.json"):
                sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
                import rulebook
                if path == "/drill.json":
                    return self.send(200, json.dumps(rulebook.drill()), "application/json")
                book = rulebook.collect()
                return self.send(200, json.dumps({"areas": book, "count": sum(len(v) for v in book.values())}), "application/json")
            if path == "/treasury":        # the treasury: what the work cost and what it was worth
                return self.send(200, open(os.path.join(WEB, "treasury.html")).read())
            if path == "/treasury.json":
                sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
                import treasury
                return self.send(200, json.dumps(treasury.data()), "application/json")
            if path == "/campaign.json":
                return self.send(200, json.dumps(fleet().board()), "application/json")
            v = re.match(r"^/vendor/([A-Za-z0-9._-]+)$", path)
            if v:   # mermaid and friends, fetched once by install.sh, never from a CDN at view time
                target = os.path.join(GUILD_HOME, "vendor", v.group(1))
                if not os.path.isfile(target):
                    return self.send(404, "not installed: run install.sh")
                with open(target, "rb") as f:
                    return self.send(200, f.read(), "text/javascript; charset=utf-8")
            v = re.match(r"^/q/([A-Za-z0-9._-]+)/(validate|validate\.json|validate/export|file/(.+))$", path)
            if v:
                return self.validation_get(v.group(1), v.group(2), v.group(3))
            m = re.match(r"^/b/([^/]+)/([^/]+)/?(.*)$", path)
            if not m:
                return self.send(404, "not found")
            quest, board, rest = m.group(1), m.group(2), m.group(3)
            d = board_dir(quest, board)
            if not os.path.isdir(d):
                return self.send(404, "no such board")
            if rest in ("", "index.html"):
                return self.send(200, self.render_shell(quest, board, d))
            if rest == "state.json":
                dec = os.path.join(d, "decision.json")
                state = {"answered": os.path.exists(dec)}
                if state["answered"]:
                    state["decision"] = json.load(open(dec))
                return self.send(200, json.dumps(state), "application/json")
            target = os.path.realpath(os.path.join(d, rest))
            if not target.startswith(os.path.realpath(d)) or not os.path.isfile(target):
                return self.send(404, "not found")
            ctype = {
                ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
                ".svg": "image/svg+xml", ".webp": "image/webp", ".json": "application/json",
                ".mp4": "video/mp4", ".webm": "video/webm",
            }.get(os.path.splitext(target)[1].lower(), "application/octet-stream")
            with open(target, "rb") as f:
                body = f.read()
            if target.endswith(".html"):
                body = themed(body)
                if rest == "content.html":
                    body = with_glance(body, quest)
            return self.send(200, body, ctype)
        except Exception as e:  # never take the server down for one bad request
            return self.send(500, f"error: {e}")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        k = re.match(r"^/docket/(rule|hold)$", path)
        if k:
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not SAFE.match(body.get("quest", "")) or not SAFE.match(body.get("board", "")):
                    raise ValueError("bad board")
                if k.group(1) == "rule":
                    answer_board(body["quest"], body["board"], body)
                else:
                    hold_board(body["quest"], body["board"], body.get("until", ""), body.get("note", ""))
                return self.send(200, json.dumps({"ok": True}), "application/json")
            except Exception as e:
                return self.send(500, json.dumps({"error": str(e)}), "application/json")
        if path == "/drill/grade":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
            import rulebook
            return self.send(200, json.dumps(rulebook.grade(str(body.get("key", "")), bool(body.get("right")), body.get("answer", ""))),
                             "application/json")
        v = re.match(r"^/q/([A-Za-z0-9._-]+)/validate/(mark|send)$", path)
        if v:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            quest, sc = v.group(1), scenarios_mod()
            try:
                if v.group(2) == "mark":
                    out = sc.mark(quest, str(body.get("id", "")), str(body.get("status", "")), str(body.get("note", "")))
                    out = dict(out, stamp=sc.stamp(out), certificate=None)
                else:
                    failed = sc.failures_text(quest)
                    if not failed:
                        raise ValueError("nothing failed")
                    threading.Thread(target=send_back, daemon=True, args=(quest,
                        "The guildmaster ran your validation checklist and these scenarios failed:\n" + failed
                        + "\nFix them, update scenarios.json if a scenario itself was wrong, run the trial again, "
                          "post a new wrap-up, then report done.", "validation failed: back to the forge")).start()
                    out = {"did": "Sent to the adventurer"}
                return self.send(200, json.dumps(out), "application/json")
            except (ValueError, OSError) as e:
                return self.send(200, json.dumps({"error": str(e)}), "application/json")
        c = re.match(r"^/campaign/(jump|pin|todo|close|story)$", path)
        if c:
            length = int(self.headers.get("Content-Length", 0))
            try:
                return self.send(200, json.dumps(campaign_action(c.group(1), json.loads(self.rfile.read(length) or b"{}"))),
                                 "application/json")
            except Exception as e:
                return self.send(500, json.dumps({"error": str(e)}), "application/json")
        m = re.match(r"^/b/([^/]+)/([^/]+)/(reply|upload)$", path)
        if not m:
            return self.send(404, "not found")
        quest, board, action = m.group(1), m.group(2), m.group(3)
        d = board_dir(quest, board)
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        try:
            if action == "upload":
                name = os.path.basename(payload.get("name", "attachment"))
                if not SAFE.match(name):
                    name = "attachment-%d" % int(time.time() * 1000)
                updir = os.path.join(d, "uploads")
                os.makedirs(updir, exist_ok=True)
                rel = os.path.join("uploads", f"{int(time.time() * 1000)}-{name}")
                with open(os.path.join(d, rel), "wb") as f:
                    f.write(base64.b64decode(payload.get("data", "").split(",")[-1]))
                return self.send(200, json.dumps({"path": rel}), "application/json")

            answer_board(quest, board, payload)
            return self.send(200, json.dumps({"ok": True}), "application/json")
        except Exception as e:
            return self.send(500, json.dumps({"error": str(e)}), "application/json")

    def validation_get(self, quest, what, rel):
        sc = scenarios_mod()
        qd = os.path.join(QUESTS, quest)
        if not os.path.isdir(qd):
            return self.send(404, "no such quest")
        if rel:                                   # a screenshot from the quest folder
            target = os.path.realpath(os.path.join(qd, rel))
            if not target.startswith(os.path.realpath(qd) + os.sep) or not os.path.isfile(target):
                return self.send(404, "not found")
            import mimetypes
            with open(target, "rb") as f:
                return self.send(200, f.read(), mimetypes.guess_type(target)[0] or "application/octet-stream")
        if what == "validate.json":
            return self.send(200, json.dumps({"summary": sc.summary(quest), "marks": sc.state(quest)}, default=str), "application/json")
        if not sc.load(quest):
            return self.send(404, "this quest has no scenarios.json yet")
        meta = load_json_safe(os.path.join(qd, "meta.json")) or {}
        import prs as prmod
        pr = prmod.by_slug().get(quest)
        pr = pr if pr and not pr.get("error") else None
        if what == "validate/export":
            body = sc.export(quest, meta, pr).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{quest}-validation.html"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        return self.send(200, sc.page(quest, meta, image=lambda r: "file/" + r, prs=pr))

    def render_index(self):
        rows = []
        for m in list_boards():
            mark = "answered" if m["answered"] else "waiting"
            rows.append(
                f'<li class="{mark}"><a href="/b/{m["quest"]}/{m["id"]}/">{m.get("title", m["id"])}</a>'
                f'<span class="meta">{m["quest"]} · {mark} · {m.get("created", "")}</span></li>'
            )
        body = "<ul class='boards'>" + ("".join(rows) or "<li class='empty'>No boards yet.</li>") + "</ul>"
        return open(os.path.join(WEB, "index.html")).read().replace("<!--BOARDS-->", body)

    def render_shell(self, quest, board, d):
        meta = json.load(open(os.path.join(d, "board.json")))
        questions = []
        qpath = os.path.join(d, "decisions.json")
        if os.path.exists(qpath):
            questions = json.load(open(qpath)).get("questions", [])
        if meta.get("wrapup"):                  # a finished piece of work: you grade it first
            questions = GRADE_QUESTIONS + questions
        shell = open(os.path.join(WEB, "shell.html")).read()
        return (shell
                .replace("{{TITLE}}", meta.get("title", board))
                .replace("{{QUEST}}", quest)
                .replace("{{BOARD}}", board)
                .replace("{{SUBTITLE}}", meta.get("subtitle", ""))
                .replace("{{QUESTIONS}}", json.dumps(questions)))


class RemoteHandler(Handler):
    """The war table on your Tailscale address. Every request needs the key: once in the link
    (?k=...), after that from a cookie the link sets."""

    def allowed(self):
        cfg = remote_config()
        key = cfg.get("key", "")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        cookie = dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)
        if key and query.get("k", [""])[0] == key:
            self._set_cookie = f"guild_k={key}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000"
            return True
        self._set_cookie = ""
        return bool(key) and cookie.get("guild_k") == key

    def end_headers(self):
        if getattr(self, "_set_cookie", ""):
            self.send_header("Set-Cookie", self._set_cookie)
        super().end_headers()

    def do_GET(self):
        if not self.allowed():
            return self.send(403, "guild: this war table needs its key. Open the link from `guild remote url`.")
        return super().do_GET()

    def do_POST(self):
        if not self.allowed():
            return self.send(403, json.dumps({"error": "key needed"}), "application/json")
        return super().do_POST()


def remote_config():
    try:
        return json.load(open(os.path.join(GUILD_HOME, "local", "remote.json")))
    except (OSError, ValueError):
        return {}


def serve_remote():
    cfg = remote_config()
    if not (cfg.get("remote") and cfg.get("bind") and cfg.get("key")):
        return
    try:
        httpd = http.server.ThreadingHTTPServer((cfg["bind"], int(cfg.get("port", 4712))), RemoteHandler)
    except OSError:
        return                          # Tailscale down or the port taken: the local table still works
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


def refresh_prs_forever():
    """Keep the campaign board's PR states fresh without making a page wait on GitHub, and
    put finished work away as it finishes."""
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import prs
    while True:
        try:
            prs.refresh()
        except Exception:
            pass
        try:
            sweep()
        except Exception:
            pass
        try:                                   # once a month: rotate old events, pack old closed quests
            import contextlib, io, tidy
            with contextlib.redirect_stdout(io.StringIO()):
                tidy.maybe()
        except Exception:
            pass
        time.sleep(120)


def auto_close_on():
    try:
        return json.load(open(os.path.join(GUILD_HOME, "local", "dispatch.json"))).get("auto_close", True) is not False
    except (OSError, ValueError):
        return True


def sweep():
    """Finished work leaves the cockpit. A quest you graded merge or split loses its tab (the
    agent stops; the worktree stays, so a review fix can still revive it). A quest whose PR
    is merged or closed is closed for good: archived, worktree back to the pool. Never with
    uncommitted changes: `guild close` without --force refuses those."""
    if not auto_close_on():
        return
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import prs
    guild = os.path.join(os.path.dirname(os.path.realpath(__file__)), "guild")
    sock = os.environ.get("GUILD_TMUX_SOCKET", "guild")
    windows = subprocess.run(["tmux", "-L", sock, "list-windows", "-t", "guild", "-F", "#{window_id}\t#W"],
                             capture_output=True, text=True).stdout.splitlines()
    tab = {w.split("\t")[1]: w.split("\t")[0] for w in windows if "\t" in w}
    pr_of = prs.by_slug()
    for slug in sorted(os.listdir(QUESTS)) if os.path.isdir(QUESTS) else []:
        qdir = os.path.join(QUESTS, slug)
        try:
            meta = json.load(open(os.path.join(qdir, "meta.json")))
            state = open(os.path.join(qdir, "status")).read().split("\t")[0]
        except (OSError, ValueError):
            continue
        if meta.get("pseudo") or state != "done":
            continue
        pr = pr_of.get(slug) or {}
        if pr.get("state") in ("merged", "closed"):
            r = subprocess.run([guild, "close", slug], capture_output=True, text=True)
            if r.returncode == 0:
                with open(EVENTS, "a") as f:
                    f.write(f"{now()}\t{slug}\tclosed\tPR {pr['state']}: closed on its own\n")
            continue
        try:
            verdict = json.load(open(os.path.join(qdir, "grade.json"))).get("verdict")
        except (OSError, ValueError):
            verdict = None
        if verdict in ("merge", "split") and slug in tab:
            subprocess.run(["tmux", "-L", sock, "kill-window", "-t", tab[slug]], capture_output=True)
            with open(EVENTS, "a") as f:
                f.write(f"{now()}\t{slug}\tdone\tgraded {verdict}: its tab closed (guild revive {slug} reopens it)\n")


def serve():
    """Start the server unless one is already up. Writes the port to ~/.guild/.wartable-port."""
    serve_remote()
    if not os.environ.get("GUILD_NO_PR_SYNC"):
        threading.Thread(target=refresh_prs_forever, daemon=True).start()
    port = int(os.environ.get("GUILD_BOARD_PORT", "4711"))
    for candidate in range(port, port + 20):
        try:
            httpd = http.server.ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
        except OSError:
            continue
        with open(PORT_FILE, "w") as f:
            f.write(str(candidate))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return candidate
    raise SystemExit("wartable: no free port")


def running_port():
    if not os.path.exists(PORT_FILE):
        return None
    port = int(open(PORT_FILE).read().strip() or 0)
    with socket.socket() as s:
        s.settimeout(0.3)
        return port if s.connect_ex(("127.0.0.1", port)) == 0 else None


def ensure_server():
    port = running_port()
    if port:
        return port
    subprocess.Popen([sys.executable, os.path.realpath(__file__), "daemon"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(50):
        time.sleep(0.1)
        port = running_port()
        if port:
            return port
    raise SystemExit("wartable: server did not start")


def cmd_open(args):
    quest = args["quest"]
    board = args.get("id") or time.strftime("%H%M%S")
    d = board_dir(quest, board)
    fresh = not os.path.exists(d)
    os.makedirs(d, exist_ok=True)
    try:
        write_board(d, quest, board, args)
    except BaseException:
        if fresh:                           # a half-made board would look like an open decision forever
            subprocess.run(["rm", "-rf", d])
        raise
    finish_open(quest, board, args)


def write_board(d, quest, board, args):
    src = os.path.abspath(args["html"])
    # The page and everything beside it (images, css) move into the board folder.
    srcdir = os.path.dirname(src)
    for name in os.listdir(srcdir) if args.get("assets") else [os.path.basename(src)]:
        s, t = os.path.join(srcdir, name), os.path.join(d, name)
        if os.path.isdir(s):
            subprocess.run(["cp", "-R", s, t], check=True)
        else:
            subprocess.run(["cp", s, t], check=True)
    os.replace(os.path.join(d, os.path.basename(src)), os.path.join(d, "content.html"))
    if args.get("decisions"):
        subprocess.run(["cp", os.path.abspath(args["decisions"]), os.path.join(d, "decisions.json")], check=True)
    json.dump({"id": board, "quest": quest, "title": args.get("title") or board,
               "subtitle": args.get("subtitle", ""), "wrapup": bool(args.get("wrapup")), "created": now()},
              open(os.path.join(d, "board.json"), "w"), indent=2)


def finish_open(quest, board, args):
    port = ensure_server()
    url = f"http://127.0.0.1:{port}/b/{quest}/{board}/"
    if args.get("wrapup"):
        record(quest, "working", f"wrap-up ready: {args.get('title') or board} -> {url}")
    else:
        record(quest, "needs-decision", f"war table ready: {args.get('title') or board} -> {url}")
    # GUILD_BOARD_NO_OPEN=1 keeps the tests (and any script) out of your browser.
    if not args.get("no_open") and os.environ.get("GUILD_BOARD_NO_OPEN") != "1":
        subprocess.run(["open", url], check=False)
    print(url)
    print(f"board id: {board}")
    print(f"now wait for the answer: guild board wait {board} --timeout 3600")



# ── Markdown for pages: plans and long details, readable instead of one grey paragraph ──
# names that read as code in prose: paths, CamelCase (with .members and ()), snake_case, #123
CODE_WORD = (r"(?:[\w.-]*/[\w./-]*[\w/-])|(?:[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+(?:\.[A-Za-z_]+)*(?:\(\))?)"
             r"|(?:[a-z]+_[a-z0-9_]+)|(?:#\d+)")


def md_inline(text, auto_code=False):
    """Code spans first (kept aside), then bold and links over the whole line, so **bold with
    `code` inside** works."""
    spans = []

    def keep(m):
        spans.append(f"<code>{_esc(m.group(1))}</code>")
        return f"\x00{len(spans) - 1}\x00"
    t = _esc(re.sub(r"`([^`]+)`", keep, text))
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
    if auto_code:                                       # names in prose read as code
        t = re.sub(r"(?:^|(?<=[\s(]))(?:" + CODE_WORD + r")(?![\w/])", lambda m: f"<code>{m.group(0)}</code>", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], t)


def md_to_html(md):
    """Enough Markdown for a plan: headings, lists (nested by indent), tables, code blocks, quotes."""
    lines, out, i = md.splitlines(), [], 0
    stack = []                                          # open lists: (indent, tag)

    def close_lists(to=-1):
        while stack and stack[-1][0] > to:
            out.append(f"</li></{stack.pop()[1]}>")

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            close_lists()
            code, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i]); i += 1
            out.append(f"<pre><code>{_esc(chr(10).join(code))}</code></pre>")
            i += 1
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = [c.strip() for c in line.strip().strip("|").split("|")]
            rows, i = [], i + 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")]); i += 1
            table = "<table><tr>" + "".join(f"<th>{md_inline(h)}</th>" for h in head) + "</tr>"
            table += "".join("<tr>" + "".join(f"<td>{md_inline(c)}</td>" for c in r) + "</tr>" for r in rows) + "</table>"
            out.append(f'<div class="tablewrap">{table}</div>')
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            close_lists()
            level = min(4, len(m.group(1)) + 1)          # the page title is the h1
            out.append(f"<h{level}>{md_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        m = re.match(r"^(\s*)([-*]|\d+[.)])\s+(.*)", line)
        if m:
            indent, tag = len(m.group(1)), "ol" if m.group(2)[0].isdigit() else "ul"
            if not stack or indent > stack[-1][0]:
                out.append(f"<{tag}><li>"); stack.append((indent, tag))
            else:
                close_lists(indent)
                if stack and stack[-1][0] == indent:
                    out.append("</li><li>")
                else:
                    out.append(f"<{tag}><li>"); stack.append((indent, tag))
            out.append(md_inline(m.group(3)))
            i += 1
            continue
        if line.strip().startswith(">"):
            close_lists()
            out.append(f"<blockquote>{md_inline(line.strip()[1:].strip())}</blockquote>")
            i += 1
            continue
        if not line.strip():
            nxt = next((l for l in lines[i + 1:] if l.strip()), "")
            if not (stack and (nxt.startswith(" ") or re.match(r"^\s*([-*]|\d+[.)])\s", nxt))):
                close_lists()
            i += 1
            continue
        if stack and line.startswith(" "):              # a list item's wrapped line
            out.append(" " + md_inline(line.strip()))
            i += 1
            continue
        close_lists()
        para = [line.strip()]                           # one paragraph: every line up to a blank or a block
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(\s*([-*]|\d+[.)])\s|#{1,4}\s|\s*\||\s*```|\s*>)", lines[i]):
            para.append(lines[i].strip()); i += 1
        out.append(f"<p>{md_inline(' '.join(para))}</p>")
    close_lists()
    return "\n".join(out)


def detail_html(detail):
    """A long one-line detail becomes short bullets, with names shown as code."""
    detail = detail.strip()
    if not detail:
        return ""
    parts = [p.strip() for p in re.split(r";\s+|(?<=[.!?])\s+(?=[A-Z0-9#`])", detail) if p.strip()]
    if len(detail) > 220 and len(parts) > 2:
        return '<ul class="detail">' + "".join(f"<li>{md_inline(p, auto_code=True)}</li>" for p in parts) + "</ul>"
    return f'<p class="detail">{md_inline(detail, auto_code=True)}</p>'


PLAN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Approve the plan?</title>
<style>
 body { max-width: 980px; }
 .kicker { font-variant: small-caps; letter-spacing: .08em; color: var(--dim); font-size: 13px; }
 .summary { font-size: 17px; margin: 6px 0 22px; }
 .plan h2 { font-size: 18px; margin: 26px 0 8px; }
 .plan h3 { font-size: 16px; margin: 18px 0 6px; }
 .plan ol > li { margin: 0 0 12px; }
 .plan li li { margin: 3px 0; }
 .plan p { margin: 6px 0; }
 .plan code { overflow-wrap: anywhere; }
 .plan pre code { white-space: pre; }
 .tablewrap { overflow-x: auto; margin: 8px 0 12px; }
 .tablewrap td code { white-space: normal; overflow-wrap: anywhere; }
 .next { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 30px; }
 .next div { background: var(--card); border: 1px solid var(--line); border-radius: 4px; padding: 12px 16px; }
 .next div.go { border-left: 4px solid var(--ok); }
 .next div.change { border-left: 4px solid var(--accent); }
 .next h3 { margin: 0 0 6px; font-size: 15px; }
 .next ol { margin: 0; padding-left: 20px; }
 .hint { color: var(--dim); font-size: 13px; margin-top: 22px; }
 @media (max-width: 700px) { .next { grid-template-columns: 1fr; } }
</style></head><body>
<div class="kicker">__QUEST__ · plan for your approval</div>
<h1>Approve the plan?</h1>
<p class="summary">__SUMMARY__</p>
<div class="plan">__PLAN__</div>
<h2>What happens next</h2>
<div class="next">
 <div class="go"><h3>If you approve</h3><ol>__IF_GO__</ol></div>
 <div class="change"><h3>If you ask for changes</h3><ol>
  <li>Write what to change in the notes on the right.</li>
  <li>The adventurer updates the plan and puts it here again.</li>
  <li>Nothing is built until you approve.</li></ol></div>
</div>
<p class="hint">The full plan file: <code>__PATH__</code></p>
</body></html>
"""


def cmd_plan(args):
    """The plan phase's approval board: plan.md rendered, and what each answer leads to."""
    quest = args["quest"]
    qdir = os.path.join(QUESTS, quest)
    path = os.path.join(qdir, "plan.md")
    if not os.path.exists(path):
        raise SystemExit(f"guild plan: write the plan to {path} first")
    meta = json.load(open(os.path.join(qdir, "meta.json")))
    md = open(path).read()
    md = re.sub(r"^#\s+.*\n+", "", md, count=1)          # its title is the page's
    build = meta.get("build_model") or meta.get("model") or "the build model"
    effort = meta.get("build_effort") or ""
    budget = meta.get("budget")
    go = [f"The adventurer restarts on <b>{_esc(build)}</b>{' (' + _esc(effort) + ' effort)' if effort else ''}, in the same conversation.",
          "It builds these steps and runs the acceptance checks.",
          "It runs the trial (an adversarial review and the project's checks), then opens the PR.",
          "You get a wrap-up page to grade."]
    if budget:
        go.append(f"It stops and asks you if it passes its ${float(budget):g} budget.")
    page = (PLAN_PAGE.replace("__QUEST__", _esc(quest))
            .replace("__SUMMARY__", md_inline(args.get("summary") or "", auto_code=True))
            .replace("__PLAN__", md_to_html(md))
            .replace("__IF_GO__", "".join(f"<li>{x}</li>" for x in go))
            .replace("__PATH__", _esc(path)))
    decisions = {"questions": [{"id": "choice", "title": "Approve the plan?", "type": "single", "recommended": "go",
                                "options": [{"id": "go", "label": "Approve", "why": "build it as planned"},
                                            {"id": "change", "label": "Change it", "why": "your notes go back; it replans"}]}]}
    if args.get("board"):                               # redo an open board in place (same id, same question)
        d = board_dir(quest, args["board"])
        open(os.path.join(d, "content.html"), "w").write(page)
        json.dump(decisions, open(os.path.join(d, "decisions.json"), "w"), indent=2)
        print(f"board {args['board']} redrawn")
        return
    tmp = os.path.join(GUILD_HOME, ".plan-tmp")
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "page.html"), "w").write(page)
    json.dump(decisions, open(os.path.join(tmp, "decisions.json"), "w"), indent=2)
    args.update(html=os.path.join(tmp, "page.html"), decisions=os.path.join(tmp, "decisions.json"),
                title=f"Approve the plan: {quest}")
    cmd_open(args)


ASK_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>__TITLE__</title>
<style>
 :root { color-scheme: dark light;
   --bg:#0f1117; --card:#161922; --line:#242835; --text:#e6e8ef; --dim:#9aa3b8; --accent:#7aa2f7; }
 @media (prefers-color-scheme: light) {
   :root { --bg:#f6f7fa; --card:#fff; --line:#e2e5ec; --text:#1b1f2a; --dim:#5c6478; --accent:#3a63c8; } }
 * { box-sizing:border-box; }
 body { margin:0; padding:32px 36px 56px; background:var(--bg); color:var(--text);
   font:15px/1.65 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }
 h1 { font-size:22px; margin:0 0 10px; max-width:70ch; }
 p.detail { margin:0 0 26px; max-width:74ch; }
 ul.detail { margin:0 0 26px; padding-left:20px; max-width:74ch; }
 ul.detail li { margin:0 0 6px; }
 code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.88em; }
 .opt { background:var(--card); border:1px solid var(--line); border-left:3px solid var(--accent);
   border-radius:10px; padding:14px 16px; margin-bottom:10px; max-width:70ch; }
 .opt .id { font-family:ui-monospace,monospace; font-size:11px; color:var(--accent);
   text-transform:uppercase; letter-spacing:.06em; }
 .opt .label { font-weight:600; margin:2px 0 4px; }
 .opt .why { color:var(--dim); font-size:14px; white-space:pre-wrap; }
 .opt.suggested { border-left-color:#e0af68; }
 .opt.suggested .id { color:#e0af68; }
 .hint { color:var(--dim); font-size:13px; margin-top:28px; border-top:1px solid var(--line); padding-top:14px; }
</style></head><body>
<h1>__QUESTION__</h1>
__DETAIL__
__OPTIONS__
<p class="hint">Choose in the panel (beside this page, or below it on a narrow window). Notes and screenshots go there too.</p>
</body></html>
"""


def _esc(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def cmd_ask(args):
    """Turn a plain question into a board: page, decision file, browser, all in one call."""
    question = args["question"]
    options = []
    raw = args.get("option") or []
    if isinstance(raw, str):
        raw = [raw]
    for item in raw:
        # "id=Label" or "id=Label: why this one"
        ident, _, rest = item.partition("=")
        label, _, why = rest.partition(":")
        options.append({"id": ident.strip(), "label": label.strip() or ident.strip(), "why": why.strip()})

    blocks = []
    for o in options:
        suggested = " suggested" if o["id"] == args.get("recommend") else ""
        why = f'<div class="why">{md_inline(o["why"], auto_code=True)}</div>' if o["why"] else ""
        blocks.append(f'<div class="opt{suggested}"><div class="id">{_esc(o["id"])}'
                      f'{" · suggested" if suggested else ""}</div>'
                      f'<div class="label">{_esc(o["label"])}</div>{why}</div>')
    detail = detail_html(args.get("detail") or "")
    page = (ASK_PAGE.replace("__TITLE__", _esc(args.get("title") or question[:60]))
            .replace("__QUESTION__", _esc(question))
            .replace("__DETAIL__", detail)
            .replace("__OPTIONS__", "\n".join(blocks)))

    question_id = "choice"
    decisions = {"questions": [{
        "id": question_id,
        "title": question,
        "detail": args.get("detail", ""),
        "type": "single" if options else "text",
        "recommended": args.get("recommend"),
        "options": [{"id": o["id"], "label": o["label"], "why": o["why"]} for o in options],
    }]}

    tmp = os.path.join(GUILD_HOME, ".ask-tmp")
    os.makedirs(tmp, exist_ok=True)
    page_path, dec_path = os.path.join(tmp, "page.html"), os.path.join(tmp, "decisions.json")
    with open(page_path, "w") as f:
        f.write(page)
    with open(dec_path, "w") as f:
        json.dump(decisions, f, indent=2)

    args["html"], args["decisions"] = page_path, dec_path
    args.setdefault("title", question[:60])
    cmd_open(args)


def cmd_wait(args):
    d = board_dir(args["quest"], args["id"])
    dec = os.path.join(d, "decision.json")
    deadline = time.time() + float(args.get("timeout") or 3600)
    while time.time() < deadline:
        if os.path.exists(dec):
            print(open(dec).read())
            return
        time.sleep(2)
    print(json.dumps({"timeout": True}))


def main():
    argv = sys.argv[1:]
    if not argv:
        raise SystemExit(__doc__)
    cmd, rest = argv[0], argv[1:]
    if cmd == "due":
        due_boards()
        return
    if cmd == "sweep":
        sweep()
        return
    if cmd == "daemon":
        serve()
        with open(os.path.join(GUILD_HOME, ".wartable-pid"), "w") as f:
            f.write(str(os.getpid()))
        while True:
            time.sleep(3600)
    args, key = {}, None
    positional = []
    for token in rest:
        if token.startswith("--"):
            key = token[2:].replace("-", "_")
            if not isinstance(args.get(key), list):  # keep what a repeated flag collected
                args[key] = True
        elif key:
            if key == "option":
                if not isinstance(args.get("option"), list):
                    args["option"] = []
                args["option"].append(token)
            else:
                args[key] = token
            key = None
        else:
            positional.append(token)
    if cmd == "open":
        args["quest"] = positional[0]
        return cmd_open(args)
    if cmd == "plan":
        args["quest"] = positional[0]
        args["summary"] = positional[1] if len(positional) > 1 else ""
        return cmd_plan(args)
    if cmd == "ask":
        args["quest"] = positional[0]
        args["question"] = positional[1]
        return cmd_ask(args)
    if cmd == "wait":
        args["quest"], args["id"] = positional[0], positional[1]
        return cmd_wait(args)
    if cmd == "list":
        for m in list_boards():
            print(f'{"answered" if m["answered"] else "waiting "}  {m["quest"]:<24} {m["id"]:<10} {m.get("title", "")}')
        return
    if cmd == "url":
        port = running_port()
        print(f"http://127.0.0.1:{port}/" if port else "war table is not running")
        return
    raise SystemExit(f"wartable: unknown command {cmd}")


if __name__ == "__main__":
    main()
