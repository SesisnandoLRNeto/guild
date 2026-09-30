#!/usr/bin/env python3
"""End-to-end validation scenarios for a quest: the checklist you run before a merge.

  scenarios.py check <slug>              problems with the quest's scenarios.json, one per line (none: ok)
  scenarios.py summary <slug>            passed, failed, skipped and open counts, as JSON
  scenarios.py export <slug> [--out F]   a standalone page for the team (images inside, ticks in their browser)

The adventurer writes quests/<slug>/scenarios.json next to its wrap-up. The war table shows
it at /q/<slug>/validate: what is being tested, the setup, a map of the screens with before
and after shots when the frontend changed, then the scenarios in groups, each with what to do,
the command to copy and what you should see. You mark each one pass, fail or skip (a skip or a
fail takes a note). The results live in quests/<slug>/validation.json, and a wrap-up cannot be
graded "ready to merge" until every scenario passed or was skipped with a reason.

scenarios.json:
{
  "title": "Pay rates: equations per level, end to end",
  "lede": "One or two sentences: what this run proves.",
  "tested": [{"what": "HAS_VALUE and keyword IF", "ticket": "SARA-1064", "pr": "#179", "state": "in review"}],
  "setup": [{"title": "project-api on the quest branch", "text": "...", "cmd": "git switch ...\\n./scripts/up", "note": "..."}],
  "screens": [{"id": "S1", "name": "Project pay rates", "route": "/projects/:id/pay-rates",
               "before": "shots/s1-before.png", "after": "shots/s1-after.png", "what": "what changed here",
               "next": [{"to": "S2", "action": "Add rate"}]}],
  "groups": [{"id": "A", "title": "Dated equations", "refs": "#160 #162", "scenarios": [
      {"id": "A1", "do": "Create an hourly equation.", "cmd": "curl ...", "expect": "201, active, ...",
       "screen": "S1", "shot": "shots/a1.png"}]}],
  "gaps": [{"gap": "No gap list on save", "why": "waiting on product", "where": "SARA-1054"}]
}
Only "groups" is required; every scenario needs "id", "do" and "expect". Image paths are relative
to the quest folder. "before" is left out for a screen that is new.
"""
import base64
import html
import json
import mimetypes
import os
import sys
import time

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
STATUSES = ("pass", "fail", "skip")


def qdir(slug):
    return os.path.join(QUESTS, slug)


def load(slug):
    try:
        return json.load(open(os.path.join(qdir(slug), "scenarios.json")))
    except (OSError, ValueError):
        return None


def state(slug):
    try:
        return json.load(open(os.path.join(qdir(slug), "validation.json")))
    except (OSError, ValueError):
        return {}


def scenario_list(spec):
    return [s for g in (spec or {}).get("groups", []) for s in g.get("scenarios", [])]


def check(slug, frontend=False):
    """What is wrong with the quest's scenarios.json, as a list of plain sentences."""
    path = os.path.join(qdir(slug), "scenarios.json")
    if not os.path.exists(path):
        return ["there is no scenarios.json in the quest folder"]
    try:
        spec = json.load(open(path))
    except ValueError as e:
        return [f"scenarios.json is not valid JSON: {e}"]
    problems, seen = [], set()
    if not spec.get("groups"):
        problems.append('scenarios.json has no "groups"')
    for s in scenario_list(spec):
        sid = s.get("id", "")
        if not sid:
            problems.append("a scenario has no id")
        elif sid in seen:
            problems.append(f"scenario id {sid} is used twice")
        seen.add(sid)
        for key in ("do", "expect"):
            if not str(s.get(key, "")).strip():
                problems.append(f"scenario {sid or '?'} has no \"{key}\"")
    screens = {sc.get("id") for sc in spec.get("screens", [])}
    for s in scenario_list(spec):
        if s.get("screen") and s["screen"] not in screens:
            problems.append(f"scenario {s.get('id')} names screen {s['screen']}, which is not in \"screens\"")
    if frontend and not spec.get("screens"):
        problems.append('the frontend changed, so scenarios.json needs "screens": a map of the screens to validate, '
                        'with "after" shots (and "before" shots from the base branch for screens that existed)')
    for sc in spec.get("screens", []):
        for key in ("before", "after"):
            if sc.get(key) and not os.path.exists(os.path.join(qdir(slug), sc[key])):
                problems.append(f"screen {sc.get('id')}: {sc[key]} is not in the quest folder")
        if frontend and not sc.get("after"):
            problems.append(f"screen {sc.get('id')} has no \"after\" shot")
    return problems


def head(slug):
    """The commit the quest's worktree is on now."""
    import subprocess
    try:
        wt = json.load(open(os.path.join(qdir(slug), "meta.json"))).get("worktree", "")
        return subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() if wt else ""
    except (OSError, ValueError):
        return ""


def certificate(slug):
    try:
        return json.load(open(os.path.join(qdir(slug), "certificate.json")))
    except (OSError, ValueError):
        return None


def summary(slug):
    """Counts, and whether the work is certified: every scenario passed (or skipped with a reason)
    on the commit the worktree is on now. A new commit after that makes the certificate stale."""
    spec = load(slug)
    if not spec:
        return {"total": 0, "pass": 0, "fail": 0, "skip": 0, "open": 0, "complete": False, "exists": False,
                "certified": False, "stale": False}
    marks = state(slug)
    ids = [s["id"] for s in scenario_list(spec) if s.get("id")]
    count = {k: sum(1 for i in ids if marks.get(i, {}).get("status") == k) for k in STATUSES}
    open_ = len(ids) - sum(count.values())
    cert = certificate(slug)
    now_at = head(slug)
    stale = bool(cert) and bool(now_at) and cert.get("commit") != now_at
    ok = bool(ids) and open_ == 0 and count["fail"] == 0
    return dict(count, total=len(ids), open=open_, exists=True, complete=ok and not stale,
                certified=bool(cert) and ok and not stale, stale=stale, certificate=cert)


def mark(slug, sid, status, note=""):
    spec = load(slug)
    if sid not in {s.get("id") for s in scenario_list(spec)}:
        raise ValueError(f"no scenario {sid}")
    if status not in STATUSES + ("",):
        raise ValueError("status is pass, fail, skip or empty")
    if status in ("fail", "skip") and not note.strip():
        raise ValueError(f"a {status} needs a note: what you saw, or why it is skipped")
    marks = state(slug)
    if status:
        marks[sid] = {"status": status, "note": note.strip(), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    else:
        marks.pop(sid, None)
    with open(os.path.join(qdir(slug), "validation.json"), "w") as f:
        json.dump(marks, f, indent=2)
    certify(slug)
    return summary(slug)


def certify(slug):
    """When the last scenario passes, write the certificate: when, what, and on which commit.
    Any mark that breaks the list (a fail, a cleared result) takes it away again."""
    spec, marks = load(slug), state(slug)
    ids = [s["id"] for s in scenario_list(spec) if s.get("id")]
    ok = ids and all(marks.get(i, {}).get("status") in ("pass", "skip") for i in ids)
    path = os.path.join(qdir(slug), "certificate.json")
    if not ok:
        if os.path.exists(path):
            os.remove(path)
        return None
    old = certificate(slug)
    commit = head(slug)
    if old and old.get("commit") == commit:
        return old
    cert = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "commit": commit,
            "passed": sum(1 for i in ids if marks[i]["status"] == "pass"),
            "skipped": [{"id": i, "why": marks[i].get("note", "")} for i in ids if marks[i]["status"] == "skip"],
            "total": len(ids)}
    with open(path, "w") as f:
        json.dump(cert, f, indent=2)
    with open(os.path.join(GUILD_HOME, "events.log"), "a") as f:
        f.write(f"{cert['at']}\t{slug}\tvalidated\t{cert['passed']}/{cert['total']} passed on {commit[:8] or 'no commit'}\n")
    return cert


def stamp(s):
    """The certificate as a line of HTML for the page."""
    c = s.get("certificate")
    if s.get("stale"):
        return (f'<p class="cert stale"><b>Certificate out of date.</b> Validated on {esc(c["at"][:16].replace("T", " "))} at '
                f'<code>{esc(c["commit"][:8])}</code>, but the branch has new commits since. Run the list again.</p>')
    if s.get("certified"):
        skipped = f', {len(c["skipped"])} skipped with a reason' if c.get("skipped") else ""
        return (f'<p class="cert"><b>Validated.</b> {c["passed"]} of {c["total"]} passed{skipped}, on '
                f'{esc(c["at"][:16].replace("T", " "))} at commit <code>{esc(c["commit"][:8])}</code>. Ready for the merge decision.</p>')
    return ""


def failures_text(slug):
    spec, marks = load(slug), state(slug)
    lines = []
    for s in scenario_list(spec):
        m = marks.get(s.get("id"), {})
        if m.get("status") == "fail":
            lines.append(f"- {s['id']} {s['do']} Expected: {s['expect']} The guildmaster saw: {m.get('note', '')}")
    return "\n".join(lines)


# ── the page ──────────────────────────────────────────────────────────────────
def esc(t):
    return html.escape(str(t or ""))


def rich(t):
    """Plain text with `code` spans, escaped."""
    parts = esc(t).split("`")
    return "".join(f"<code>{p}</code>" if i % 2 else p for i, p in enumerate(parts))


def screen_map(screens):
    """The screens as boxes in columns by how many steps from the first one, with the actions as arrows."""
    if not screens:
        return ""
    by_id = {s["id"]: s for s in screens}
    depth, order = {screens[0]["id"]: 0}, [screens[0]["id"]]
    for sid in order:
        for n in by_id[sid].get("next", []):
            if n.get("to") in by_id and n["to"] not in depth:
                depth[n["to"]] = depth[sid] + 1
                order.append(n["to"])
    for s in screens:                                   # screens nothing points at still get a column
        depth.setdefault(s["id"], max(depth.values()) + 1 if s["id"] not in depth else depth[s["id"]])
    cols = {}
    for s in screens:
        cols.setdefault(depth[s["id"]], []).append(s["id"])
    bw, bh, gx, gy, pad = 200, 64, 90, 26, 16
    pos = {}
    for c, ids in cols.items():
        for r, sid in enumerate(ids):
            pos[sid] = (pad + c * (bw + gx), pad + r * (bh + gy))
    width = pad * 2 + (max(cols) + 1) * bw + max(cols) * gx
    height = pad * 2 + max(len(v) for v in cols.values()) * (bh + gy) - gy
    out = [f'<svg class="map" viewBox="0 0 {width} {height}" role="img" aria-label="Map of the screens to validate">',
           '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
           '<path d="M0 0L10 5L0 10z" class="arh"/></marker></defs>']
    for s in screens:
        x, y = pos[s["id"]]
        for n in s.get("next", []):
            if n.get("to") not in pos:
                continue
            tx, ty = pos[n["to"]]
            x1, y1, x2, y2 = x + bw, y + bh / 2, tx, ty + bh / 2
            if tx <= x:                                  # a step back or down the same column
                x1, y1, x2, y2 = x + bw / 2, y + bh, tx + bw / 2, ty
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            out.append(f'<path class="edge" d="M{x1:.0f} {y1:.0f} C{mx:.0f} {y1:.0f} {mx:.0f} {y2:.0f} {x2:.0f} {y2:.0f}" marker-end="url(#ar)"/>')
            if n.get("action"):
                out.append(f'<text class="act" x="{mx:.0f}" y="{my - 6:.0f}" text-anchor="middle">{esc(n["action"][:26])}</text>')
    for s in screens:
        x, y = pos[s["id"]]
        cls = "node new" if not s.get("before") else "node"
        out.append(f'<a href="#screen-{esc(s["id"])}"><g class="{cls}"><rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="8"/>'
                   f'<text x="{x + 12}" y="{y + 24}" class="nid">{esc(s["id"])}</text>'
                   f'<text x="{x + 40}" y="{y + 24}" class="nname">{esc(s.get("name", "")[:22])}</text>'
                   f'<text x="{x + 12}" y="{y + 46}" class="nroute">{esc(s.get("route", "")[:28])}</text></g></a>')
    out.append("</svg>")
    return "".join(out)


def page(slug, meta=None, export=False, image=None, prs=None):
    """The checklist page. `image(rel)` turns a quest-folder path into a URL (or a data URI in an export)."""
    spec = load(slug) or {"groups": []}
    meta = meta or {}
    marks = state(slug)
    image = image or (lambda rel: rel)
    by_screen = {}
    for s in scenario_list(spec):
        if s.get("screen"):
            by_screen.setdefault(s["screen"], []).append(s["id"])
    pr_label = f"PR #{prs['number']}" if prs and prs.get("number") else ""
    eyebrow = " · ".join(x for x in [os.path.basename(meta.get("repo", "")), meta.get("ticket", ""), pr_label,
                                      "updated " + time.strftime("%d %b %Y")] if x)
    h = [f'<header><div class="eyebrow">{esc(eyebrow)}</div><h1>{esc(spec.get("title") or "Validate " + slug)}</h1>']
    if spec.get("lede"):
        h.append(f'<p class="lede">{rich(spec["lede"])}</p>')
    h.append('<div class="progress"><span id="count"></span><div class="bar" aria-hidden="true">'
             '<i class="bp" id="fill-pass"></i><i class="bf" id="fill-fail"></i><i class="bs" id="fill-skip"></i></div>')
    if export:
        h.append('<button class="btn" id="reset" type="button">Clear my ticks</button>')
    else:
        h.append('<button class="btn warn" id="sendfail" type="button" hidden>Send the failures to the adventurer</button>'
                 '<a class="btn" href="validate/export" download>Download for the team</a>')
    h.append('</div>')
    h.append(f'<div id="cert">{stamp(summary(slug))}</div>')
    if export:
        done = summary(slug)
        h.append(f'<p class="note">The guildmaster ran this list: {done["pass"]} passed, {done["fail"]} failed, '
                 f'{done["skip"]} skipped, {done["open"]} not run. Their result shows on each scenario. Your ticks stay in your browser.</p>')
    h.append('</header>')

    tested = spec.get("tested") or ([{"what": meta.get("title") or slug, "ticket": meta.get("ticket", ""),
                                      "pr": f"#{prs['number']}" if prs else "", "state": (prs or {}).get("state", "")}] if meta else [])
    if tested:
        rows = "".join(f'<tr><td class="mono">{esc(t.get("pr", ""))}</td><td class="mono">{esc(t.get("ticket", ""))}</td>'
                       f'<td>{rich(t.get("what", ""))}</td><td><span class="pill">{esc(t.get("state", ""))}</span></td></tr>' for t in tested)
        h.append(f'<section><h2>What is being tested</h2><div class="tbl"><table><thead><tr><th>PR</th><th>Ticket</th>'
                 f'<th>What it adds</th><th>State</th></tr></thead><tbody>{rows}</tbody></table></div></section>')

    if spec.get("setup"):
        steps = []
        for st in spec["setup"]:
            steps.append('<div class="step"><div>' + f'<h3>{rich(st.get("title", ""))}</h3>'
                         + (f'<p>{rich(st["text"])}</p>' if st.get("text") else "")
                         + (f'<div class="cmd">{esc(st["cmd"])}</div>' if st.get("cmd") else "")
                         + (f'<p class="note">{rich(st["note"])}</p>' if st.get("note") else "") + '</div></div>')
        h.append(f'<section><h2>Setup</h2><div class="steps">{"".join(steps)}</div></section>')

    if spec.get("screens"):
        cards = []
        for sc in spec["screens"]:
            pics = []
            if sc.get("before"):
                pics.append(f'<figure><img src="{esc(image(sc["before"]))}" alt="{esc(sc["id"])} before" loading="lazy">'
                            f'<figcaption><span class="tag old">before</span> the base branch</figcaption></figure>')

            if sc.get("after"):
                cap = "this change" if sc.get("before") else "a new screen: nothing to compare with"
                pics.append(f'<figure><img src="{esc(image(sc["after"]))}" alt="{esc(sc["id"])} after" loading="lazy">'
                            f'<figcaption><span class="tag new">after</span> {cap}</figcaption></figure>')
            chips = " ".join(f'<a class="chip" href="#s-{esc(i)}">{esc(i)}</a>' for i in by_screen.get(sc["id"], []))
            cards.append(f'<div class="screen" id="screen-{esc(sc["id"])}"><div class="shead"><h3><span class="id">{esc(sc["id"])}</span>'
                         f'{esc(sc.get("name", ""))}</h3><code>{esc(sc.get("route", ""))}</code></div>'
                         + (f'<p>{rich(sc["what"])}</p>' if sc.get("what") else "")
                         + f'<div class="pair{"" if len(pics) > 1 else " solo"}">{"".join(pics)}</div>'
                         + (f'<p class="sub">Scenarios on this screen: {chips}</p>' if chips else "") + '</div>')
        h.append('<section><h2>Screens to validate</h2><p class="sub">The path through the app. Click a screen to jump '
                 'to its before and after; each scenario names the screen it happens on.</p>'
                 f'<div class="mapbox">{screen_map(spec["screens"])}</div>{"".join(cards)}</section>')

    groups = []
    for g in spec.get("groups", []):
        items = []
        for s in g.get("scenarios", []):
            sid = s.get("id", "")
            m = marks.get(sid, {})
            body = (f'<p><span class="id">{esc(sid)}</span>{rich(s.get("do", ""))}'
                    + (f' <a class="chip" href="#screen-{esc(s["screen"])}">on {esc(s["screen"])}</a>' if s.get("screen") else "")
                    + '</p>'
                    + (f'<div class="cmd">{esc(s["cmd"])}</div>' if s.get("cmd") else "")
                    + (f'<figure class="shot"><img src="{esc(image(s["shot"]))}" alt="{esc(sid)}" loading="lazy"></figure>' if s.get("shot") else "")
                    + f'<p class="expect"><b>Expect</b> {rich(s.get("expect", ""))}</p>')
            if export:
                gm = (f'<p class="gm gm-{esc(m.get("status"))}">Guildmaster: <b>{esc(m.get("status"))}</b>'
                      + (f', {esc(m.get("note"))}' if m.get("note") else "") + '</p>') if m else '<p class="gm">Guildmaster: not run</p>'
                ctl = f'<label class="check"><input type="checkbox" aria-label="{esc(sid)} done"></label>'
                items.append(f'<div class="scen" id="s-{esc(sid)}" data-k="{esc(sid)}">{ctl}<div class="body">{body}{gm}</div></div>')
            else:
                ctl = ('<div class="marks" role="group" aria-label="Result">'
                       + "".join(f'<button type="button" data-st="{k}" class="mk mk-{k}">{k}</button>' for k in STATUSES) + '</div>')
                note = f'<textarea class="mnote" placeholder="What you saw (needed for a fail or a skip)">{esc(m.get("note", ""))}</textarea>'
                items.append(f'<div class="scen live" id="s-{esc(sid)}" data-k="{esc(sid)}" data-st="{esc(m.get("status", ""))}">'
                             f'<div class="body">{body}<div class="mrow">{ctl}{note}</div></div></div>')
        groups.append(f'<div class="group"><div class="ghead"><h3>{esc(g.get("id", ""))}. {esc(g.get("title", ""))}</h3>'
                      f'<span class="prs">{esc(g.get("refs", ""))}</span></div>{"".join(items)}</div>')
    h.append('<section id="scenarios"><h2>Scenarios</h2><p class="sub">Run the groups in order: earlier groups create data the '
             f'later ones read.</p>{"".join(groups)}</section>')

    if spec.get("gaps"):
        rows = "".join(f'<tr><td>{rich(x.get("gap", ""))}</td><td>{rich(x.get("why", ""))}</td><td class="mono">{esc(x.get("where", ""))}</td></tr>'
                       for x in spec["gaps"])
        h.append(f'<section><h2>Known gaps (do not report as bugs)</h2><div class="tbl"><table><thead><tr><th>Gap</th><th>Why</th>'
                 f'<th>Tracked in</th></tr></thead><tbody>{rows}</tbody></table></div></section>')
    h.append(f'<footer>{esc(slug)} · generated by guild from scenarios.json · {time.strftime("%d %b %Y %H:%M")}</footer>')

    script = EXPORT_JS.replace("__KEY__", json.dumps(f"guild-validate-{slug}")) if export else LIVE_JS
    return (PAGE_HEAD.replace("__TITLE__", esc(spec.get("title") or f"Validate {slug}")).replace("__THEME__", theme(export))
            + '<div class="wrap">' + "".join(h) + '</div><script>' + COPY_JS + script + '</script></body></html>')


WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "web")


def theme(inline):
    """The guild's parchment theme: linked on the war table, copied in for the standalone export."""
    if not inline:
        return '<meta name="color-scheme" content="light"><link rel="stylesheet" href="/icons.css"><link rel="stylesheet" href="/theme.css">'
    css = ""
    for name in ("icons.css", "theme.css"):
        try:
            css += open(os.path.join(WEB, name)).read()
        except OSError:
            pass
    return f'<meta name="color-scheme" content="light"><style>{css}</style>'


PAGE_HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>__THEME__<style>
:root{--paper:rgba(255,250,235,.62);--ink:var(--text,#2d2216);--muted:var(--dim,#6e5a41);--accent-soft:rgba(138,75,18,.12);
--ok-soft:rgba(63,125,58,.13);--bad-soft:rgba(168,50,42,.12);--warn-soft:rgba(154,106,18,.16);--code-bg:rgba(90,60,30,.10);--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
html:root body{max-width:1100px}
*{box-sizing:border-box}
.wrap{display:grid;gap:36px}
header{display:grid;gap:12px;border-bottom:1px solid var(--line);padding-bottom:22px}
.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
h1{margin:0}h2{margin:0}h3{margin:0}p{margin:0}
.lede,.sub{color:var(--muted);max-width:75ch}.lede{font-size:16px}
section{display:grid;gap:14px;scroll-margin-top:16px}
code{font-family:var(--mono);font-size:.88em;background:var(--code-bg);padding:1px 5px;border-radius:4px}
.progress{display:flex;flex-wrap:wrap;align-items:center;gap:12px;font-variant-numeric:tabular-nums}
.bar{flex:1 1 220px;height:9px;background:var(--line);border-radius:99px;overflow:hidden;display:flex}
.bar i{display:block;height:100%;width:0;transition:width .2s}.bp{background:var(--ok)}.bf{background:var(--bad)}.bs{background:var(--warn)}
.btn{font:600 12.5px/1 inherit;background:var(--paper);color:var(--ink);border:1px solid var(--line);border-radius:5px;padding:7px 11px;cursor:pointer;text-decoration:none}
.btn.warn{background:var(--bad);color:#fff5dc;border-color:var(--bad)}.btn:hover{background:#d9a441;border-color:#a87a25}
.pill{display:inline-block;font:600 11px/1 inherit;padding:4px 7px;border-radius:999px;background:var(--accent-soft);color:var(--accent)}
.tbl{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--paper)}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:560px}th,td{text-align:left;vertical-align:top;padding:8px 12px;border-top:1px solid var(--line)}
thead th{border-top:0;font:600 11px/1.2 inherit;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);background:var(--code-bg)}td.mono{font-family:var(--mono);font-size:12.5px}
.steps{display:grid;gap:10px;counter-reset:s}.step{display:grid;grid-template-columns:34px minmax(0,1fr);gap:10px;background:var(--paper);border:1px solid var(--line);border-radius:6px;padding:12px 14px}
.step::before{counter-increment:s;content:counter(s);font:750 20px/1.2 inherit;color:var(--accent)}.step>div{display:grid;gap:8px;min-width:0}
.cmd{position:relative;background:var(--code-bg);border-radius:6px;padding:10px 64px 10px 12px;font:13px/1.55 var(--mono);white-space:pre;overflow-x:auto}
.copy{position:absolute;top:6px;right:6px;font:600 11px/1 inherit;background:var(--paper);color:var(--ink);border:1px solid var(--line);border-radius:4px;padding:5px 8px;cursor:pointer}
.group{display:grid;gap:10px}.ghead{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px}.ghead .prs{font:500 12px/1.3 var(--mono);color:var(--muted)}
.scen{background:var(--paper);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:6px;display:grid;grid-template-columns:36px minmax(0,1fr);gap:4px 10px;padding:12px 14px;scroll-margin-top:16px}
.scen.live{grid-template-columns:minmax(0,1fr)}.scen[data-st=pass]{border-left-color:var(--ok)}.scen[data-st=fail]{border-left-color:var(--bad)}.scen[data-st=skip]{border-left-color:var(--warn)}
.scen.done{opacity:.62}.check{display:flex;justify-content:center;padding-top:2px}.check input{width:18px;height:18px;accent-color:var(--accent)}
.body{display:grid;gap:8px;min-width:0}.id{font:600 12px/1 var(--mono);color:var(--accent);margin-right:6px}
.expect{border-left:3px solid var(--ok);padding:4px 10px;background:var(--ok-soft);border-radius:0 4px 4px 0;font-size:14px}.expect b{color:var(--ok)}
.note{border-left:3px solid var(--warn);padding:6px 10px;background:var(--warn-soft);border-radius:0 4px 4px 0;font-size:14px}
.mrow{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start}.marks{display:inline-flex;border:1px solid var(--line);border-radius:5px;overflow:hidden}
.mk{font:600 12px/1 inherit;text-transform:capitalize;background:var(--paper);color:var(--ink);border:0;padding:7px 12px;cursor:pointer}.mk+.mk{border-left:1px solid var(--line)}
.scen[data-st=pass] .mk-pass{background:var(--ok);color:#fff5dc}.scen[data-st=fail] .mk-fail{background:var(--bad);color:#fff5dc}.scen[data-st=skip] .mk-skip{background:var(--warn);color:#fff5dc}
.mnote{flex:1 1 260px;min-height:34px;font:13px/1.4 inherit;padding:6px 8px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--ink);display:none}
.scen[data-st=fail] .mnote,.scen[data-st=skip] .mnote,.mnote.shown{display:block}
.gm{font-size:13px;color:var(--muted)}.gm.gm-pass b{color:var(--ok)}.gm.gm-fail b{color:var(--bad)}.gm.gm-skip b{color:var(--warn)}
.chip{font:600 11.5px/1 var(--mono);color:var(--accent);background:var(--accent-soft);border-radius:4px;padding:3px 6px;text-decoration:none;white-space:nowrap}
.mapbox{overflow-x:auto;background:var(--paper);border:1px solid var(--line);border-radius:6px;padding:8px}.map{display:block;min-width:520px;max-width:100%;height:auto}
.node rect{fill:var(--accent-soft);stroke:var(--accent);stroke-width:1.2}.node.new rect{fill:var(--warn-soft);stroke:var(--warn)}
.nid{font:700 12px var(--mono);fill:var(--accent)}.nname{font:600 13px sans-serif;fill:var(--ink)}.nroute{font:11px var(--mono);fill:var(--muted)}
.edge{fill:none;stroke:var(--muted);stroke-width:1.2}.arh{fill:var(--muted)}.act{font:11px sans-serif;fill:var(--muted)}
.screen{background:var(--paper);border:1px solid var(--line);border-radius:6px;padding:12px 14px;display:grid;gap:10px;scroll-margin-top:16px}
.shead{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline}.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pair.solo{grid-template-columns:minmax(0,640px)}
figure{margin:0;border:1px solid var(--line);border-radius:6px;overflow:hidden;background:var(--bg)}figure img{display:block;width:100%;cursor:zoom-in}
figcaption{font-size:12.5px;padding:6px 10px;color:var(--muted)}figure.none{display:grid;place-items:center;min-height:120px;color:var(--muted);font-size:13px;padding:12px;text-align:center}
figure.shot{max-width:560px}.tag{font:700 10.5px/1 inherit;letter-spacing:.06em;text-transform:uppercase;padding:3px 6px;border-radius:3px}.tag.old{background:var(--code-bg)}.tag.new{background:var(--ok-soft);color:var(--ok)}
footer{color:var(--muted);font-size:12.5px;border-top:1px solid var(--line);padding-top:14px}
.scen h3::before,.screen h3::before,.ghead h3::before,.step h3::before{content:none}
.cert{border:1px solid var(--ok);background:var(--ok-soft);border-radius:6px;padding:10px 14px}.cert b{color:var(--ok)}
.cert.stale{border-color:var(--warn);background:var(--warn-soft)}.cert.stale b{color:var(--warn)}
.zoom{position:fixed;inset:0;background:rgba(0,0,0,.88);display:grid;place-items:center;z-index:9;cursor:zoom-out}.zoom img{max-width:96vw;max-height:94vh}
@media (max-width:700px){.pair{grid-template-columns:1fr}.scen{grid-template-columns:28px minmax(0,1fr)}}
</style></head><body>"""

COPY_JS = r"""
[].slice.call(document.querySelectorAll('.cmd')).forEach(function(el){
  var b=document.createElement('button');b.type='button';b.className='copy';b.textContent='Copy';
  b.addEventListener('click',function(){var t=el.textContent.replace(/Copy$|Copied$/,'').trim();
    var ok=function(){b.textContent='Copied';setTimeout(function(){b.textContent='Copy'},1400)};
    if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(ok,function(){})}});
  el.appendChild(b);});
document.addEventListener('click',function(e){var i=e.target.closest('figure img');if(!i)return;
  var z=document.createElement('div');z.className='zoom';z.innerHTML='<img src="'+i.src+'">';z.onclick=function(){z.remove()};document.body.appendChild(z);});
function paint(counts,total){var p=function(n){return (total?n/total*100:0)+'%'};
  document.getElementById('fill-pass').style.width=p(counts.pass);document.getElementById('fill-fail').style.width=p(counts.fail);
  document.getElementById('fill-skip').style.width=p(counts.skip);
  document.getElementById('count').textContent=counts.pass+' passed · '+counts.fail+' failed · '+counts.skip+' skipped · '+(total-counts.pass-counts.fail-counts.skip)+' to run';}
"""

LIVE_JS = r"""
var cards=[].slice.call(document.querySelectorAll('.scen.live'));
function tally(){var c={pass:0,fail:0,skip:0};cards.forEach(function(s){if(c[s.dataset.st]!==undefined)c[s.dataset.st]++});paint(c,cards.length);
  document.getElementById('sendfail').hidden=!c.fail;}
function save(s,st){var note=s.querySelector('.mnote').value;
  fetch('validate/mark',{method:'POST',body:JSON.stringify({id:s.dataset.k,status:st,note:note})}).then(function(r){return r.json()}).then(function(o){
    if(o.error){alert(o.error);s.querySelector('.mnote').classList.add('shown');s.querySelector('.mnote').focus();return}
    s.dataset.st=st;tally();document.getElementById('cert').innerHTML=o.stamp||'';});}
cards.forEach(function(s){
  s.querySelectorAll('.mk').forEach(function(b){b.addEventListener('click',function(){
    var st=s.dataset.st===b.dataset.st?'':b.dataset.st;var n=s.querySelector('.mnote');
    if((st==='fail'||st==='skip')&&!n.value.trim()){n.classList.add('shown');n.placeholder=st==='fail'?'What did you see instead? Then press Fail again.':'Why skip it? Then press Skip again.';n.focus();return}
    save(s,st);});});
  s.querySelector('.mnote').addEventListener('change',function(){if(s.dataset.st)save(s,s.dataset.st)});});
document.getElementById('sendfail').addEventListener('click',function(){var b=this;b.disabled=true;
  fetch('validate/send',{method:'POST',body:'{}'}).then(function(r){return r.json()}).then(function(o){b.textContent=o.error||o.did;});});
tally();
"""

EXPORT_JS = r"""
var KEY=__KEY__,saved={};try{saved=JSON.parse(localStorage.getItem(KEY)||'{}')||{}}catch(e){}
var boxes=[].slice.call(document.querySelectorAll('.scen'));
function upd(){var d=boxes.filter(function(s){return s.querySelector('input').checked}).length;paint({pass:d,fail:0,skip:0},boxes.length);
  document.getElementById('count').textContent=d+' of '+boxes.length+' done';}
boxes.forEach(function(s){var k=s.dataset.k,cb=s.querySelector('input');cb.checked=!!saved[k];s.classList.toggle('done',cb.checked);
  cb.addEventListener('change',function(){saved[k]=cb.checked;s.classList.toggle('done',cb.checked);try{localStorage.setItem(KEY,JSON.stringify(saved))}catch(e){}upd();});});
document.getElementById('reset').addEventListener('click',function(){saved={};try{localStorage.removeItem(KEY)}catch(e){}
  boxes.forEach(function(s){s.querySelector('input').checked=false;s.classList.remove('done')});upd();});
upd();
"""


def export(slug, meta=None, prs=None):
    """The page with every image inside it, so it can be sent, published or opened anywhere."""
    def inline(rel):
        path = os.path.join(qdir(slug), rel)
        try:
            data = open(path, "rb").read()
        except OSError:
            return rel
        kind = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{kind};base64,{base64.b64encode(data).decode()}"
    return page(slug, meta, export=True, image=inline, prs=prs)


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        raise SystemExit(__doc__)
    cmd, slug = args[0], args[1]
    if cmd == "check":
        frontend = "--frontend" in args
        for p in check(slug, frontend):
            print(p)
    elif cmd == "summary":
        print(json.dumps(summary(slug)))
    elif cmd == "export":
        out = args[args.index("--out") + 1] if "--out" in args else os.path.expanduser(f"~/Downloads/{slug}-validation.html")
        meta = json.load(open(os.path.join(qdir(slug), "meta.json"))) if os.path.exists(os.path.join(qdir(slug), "meta.json")) else {}
        sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
        import prs as prmod
        pr = prmod.by_slug().get(slug)
        with open(out, "w") as f:
            f.write(export(slug, meta, pr if pr and not pr.get("error") else None))
        print(out)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
