#!/usr/bin/env python3
"""The impact map: what a change does to the business, by area, with a level, on top of the plan and the wrap-up.

The adventurer writes quests/<slug>/impact.json. At `guild plan ready` it is the expected impact and a copy is
kept as impact.planned.json; at `guild status done` it is what shipped, and the war table shows both side by side,
so an area that was not in the plan (a surprise) or a planned area that did not ship (dropped) stands out.

Levels follow fixed rules, so a change cannot be played down:
  high    a rule's outcome changes: money, permissions, state changes, deleting or migrating data,
          an API contract other systems use
  medium  a user sees a different behavior but no rule's outcome changes; or code nobody touched that
          uses what changed (touched: false)
  low     no behavior change: refactor, tests, docs

  impactmap.py check <slug> plan|done    the problems, one per line (nothing when it is fine)
  impactmap.py example                   a filled impact.json
"""
import html
import json
import os
import sys

LEVELS = ("high", "medium", "low")
EXAMPLE = {
    "rows": [
        {"id": "closure-rate", "level": "high", "area": "Pay rate on workstream closure",
         "before": "a workstream closes with no units per hour", "after": "closing is refused until units per hour is set",
         "who": "project managers", "where": "Close workstream screen, POST /workstreams/{id}/close",
         "proof": "scenario 3 passed; WorkstreamClosureServiceTest.requiresUnitsPerHour", "reversible": "yes, one revert"},
        {"id": "ws-list", "level": "medium", "area": "Workstream list", "touched": False,
         "before": "sorts by rate", "after": "same, but rate can now be empty",
         "who": "project managers", "where": "Workstreams page", "proof": "scenario 5 passed"},
        {"id": "mapper", "level": "low", "area": "Rate mapper refactor", "after": "no behavior change", "proof": "unit tests"},
        {"id": "error-text", "level": "medium", "area": "Closing error message", "before": "\"Invalid request\"",
         "after": "\"Set units per hour before closing\"", "who": "project managers",
         "proof": "scenario 3 passed", "surprise": "the old message hid the reason, found while testing"},
    ],
    "dropped": [{"id": "export", "why": "the CSV export already handled an empty rate; nothing to change"}],
}


def _quest_dir(slug):
    home = os.environ.get("GUILD_HOME") or os.path.expanduser("~/.guild")
    return os.path.join(home, "quests", slug)


def _load(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return None


def load(slug):
    return _load(os.path.join(_quest_dir(slug), "impact.json"))


def planned(slug):
    return _load(os.path.join(_quest_dir(slug), "impact.planned.json"))


def snapshot(slug):
    """At plan ready: keep the expected impact, so the wrap-up can compare what shipped against it."""
    data = load(slug)
    if data is not None:
        json.dump(data, open(os.path.join(_quest_dir(slug), "impact.planned.json"), "w"), indent=2)


def check(data, stage, plan=None):
    """Problems with an impact map, in words the adventurer can act on. stage is plan or done."""
    if data is None:
        return ["no impact map: write impact.json (guild impact-map example shows one)"]
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list) or not data["rows"]:
        return ['impact.json needs "rows": a list with at least one area']
    out, ids = [], set()
    for n, r in enumerate(data["rows"], 1):
        name = f'row {n} ({r.get("area") or r.get("id") or "no area"})' if isinstance(r, dict) else f"row {n}"
        if not isinstance(r, dict):
            out.append(f"{name}: must be an object"); continue
        for k in ("id", "area", "after"):
            if not str(r.get(k) or "").strip():
                out.append(f'{name}: needs "{k}"')
        if r.get("id") in ids:
            out.append(f'{name}: id "{r["id"]}" is used twice')
        ids.add(r.get("id"))
        level = r.get("level")
        if level not in LEVELS:
            out.append(f'{name}: "level" is high, medium or low, got {level!r}')
        if level in ("high", "medium") and not str(r.get("who") or "").strip():
            out.append(f'{name}: a {level} area says "who" feels it')
        if level == "high" and not str(r.get("before") or "").strip():
            out.append(f'{name}: a high area says "before", so the change of outcome shows')
        if stage == "done" and level == "high" and not str(r.get("proof") or "").strip():
            out.append(f'{name}: a high area needs its "proof" (the scenario or test that shows it works)')
    if stage == "done" and isinstance(plan, dict) and isinstance(plan.get("rows"), list):
        before = {r.get("id"): r for r in plan["rows"] if isinstance(r, dict)}
        for r in data["rows"]:
            if isinstance(r, dict) and r.get("id") not in before and not str(r.get("surprise") or "").strip():
                out.append(f'row {r.get("id")}: was not in the plan, so it needs "surprise": why it changed anyway')
        dropped = {d.get("id"): d for d in data.get("dropped") or [] if isinstance(d, dict)}
        for pid in before:
            if pid not in ids and not str((dropped.get(pid) or {}).get("why") or "").strip():
                out.append(f'planned area {pid} did not ship: add {{"id": "{pid}", "why": "..."}} to "dropped"')
    return out


CSS = """<style>
.gim{margin:18px 0;padding:16px 18px;border:1px solid #c9b78f;border-radius:6px;background:#fffaf0;color:#2b2418;font:15px/1.45 system-ui,sans-serif}
.gim h2{margin:0 0 4px;font-size:18px}
.gim .gim-sum{margin:0 0 12px;color:#5b4f3a}
.gim .gim-sum b{padding:1px 7px;border-radius:9px;font-size:12px;margin-right:4px}
.gim .gim-row{display:grid;grid-template-columns:78px 1fr;gap:4px 12px;padding:10px 0;border-top:1px solid #e6dcc3}
.gim .lv{align-self:start;text-align:center;font-weight:700;font-size:12px;padding:3px 0;border-radius:4px;letter-spacing:.04em}
.gim .high{background:#b3261e;color:#fff}.gim .medium{background:#e0a100;color:#241a00}.gim .low{background:#d9d2c0;color:#3d3627}
.gim .area{font-weight:600}
.gim .tag{font-size:11px;font-weight:700;margin-left:6px;padding:1px 6px;border-radius:3px;vertical-align:2px}
.gim .tag.surprise{background:#b3261e;color:#fff}.gim .tag.untouched{background:#efe3c4;color:#5b4f3a}.gim .tag.new{background:#2e6b3a;color:#fff}
.gim .ba{margin:3px 0}.gim .ba span{color:#7a6c52}
.gim .meta{color:#5b4f3a;font-size:13px}
.gim .why{color:#8f1d16;font-size:13px}
.gim .noproof{color:#8f1d16}
.gim .dropped{color:#7a6c52;text-decoration:line-through}
@media (max-width:560px){.gim .gim-row{grid-template-columns:1fr}.gim .lv{justify-self:start;padding:3px 10px}}
</style>"""


def _counts(rows):
    c = {lv: sum(1 for r in rows if isinstance(r, dict) and r.get("level") == lv) for lv in LEVELS}
    return c


def _count_html(c):
    return " ".join(f'<b class="{lv}">{c[lv]} {lv}</b>' for lv in LEVELS if c[lv]) or "nothing"


def render(data, plan=None, stage="plan"):
    """The map as an HTML section. stage plan: expected impact. stage done: what shipped, against the plan."""
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        return ""
    esc = lambda s: html.escape(str(s or ""))
    rows = [r for r in data["rows"] if isinstance(r, dict)]
    order = {lv: i for i, lv in enumerate(LEVELS)}
    rows.sort(key=lambda r: (order.get(r.get("level"), 9), r.get("touched") is False))
    before = {r.get("id"): r for r in (plan or {}).get("rows", []) if isinstance(r, dict)} if isinstance(plan, dict) else None
    if stage == "done" and before is not None:
        surprises = sum(1 for r in rows if r.get("id") not in before)
        head = "What this changed"
        summary = (f'Planned: {_count_html(_counts(list(before.values())))} &nbsp;·&nbsp; Shipped: {_count_html(_counts(rows))}'
                   + (f' &nbsp;·&nbsp; <b class="high">{surprises} not in the plan</b>' if surprises else ""))
    elif stage == "done":
        head, summary = "What this changed", f"Shipped: {_count_html(_counts(rows))} (no plan map to compare against)"
    else:
        head, summary = "What this will change", f"Expected: {_count_html(_counts(rows))}. Approving the plan agrees with this impact."
    out = [CSS, f'<section class="gim guild-impactmap" aria-label="{head}"><h2>{head}</h2><p class="gim-sum">{summary}</p>']
    for r in rows:
        lv = r.get("level") if r.get("level") in LEVELS else "low"
        tags = ""
        if r.get("touched") is False:
            tags += '<span class="tag untouched">not touched, uses what changed</span>'
        if stage == "done" and before is not None and r.get("id") not in before:
            tags += '<span class="tag surprise">not in the plan</span>'
        ba = (f'<div class="ba"><span>Before:</span> {esc(r.get("before"))} &nbsp; <span>After:</span> {esc(r.get("after"))}</div>'
              if r.get("before") else f'<div class="ba">{esc(r.get("after"))}</div>')
        meta = [f'Who feels it: {esc(r["who"])}' if r.get("who") else "", f'Where: {esc(r["where"])}' if r.get("where") else "",
                f'Reversible: {esc(r["reversible"])}' if r.get("reversible") else ""]
        proof = ""
        if stage == "done":
            proof = (f'<div class="meta">Proof: {esc(r["proof"])}</div>' if r.get("proof")
                     else '<div class="meta noproof">No proof given</div>')
        why = f'<div class="why">Why it changed anyway: {esc(r["surprise"])}</div>' if r.get("surprise") and stage == "done" else ""
        out.append(f'<div class="gim-row"><div class="lv {lv}">{lv.upper()}</div><div>'
                   f'<div class="area">{esc(r.get("area"))}{tags}</div>{ba}'
                   + (f'<div class="meta">{" &nbsp;·&nbsp; ".join(m for m in meta if m)}</div>' if any(meta) else "")
                   + proof + why + "</div></div>")
    if stage == "done":
        for d in data.get("dropped") or []:
            if isinstance(d, dict):
                area = (before or {}).get(d.get("id"), {}).get("area") or d.get("id")
                out.append(f'<div class="gim-row"><div class="lv low">DROPPED</div><div><div class="area dropped">{esc(area)}</div>'
                           f'<div class="meta">Planned but not shipped: {esc(d.get("why"))}</div></div></div>')
    out.append("</section>")
    return "".join(out)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip()); return 0
    if argv[0] == "example":
        print(json.dumps(EXAMPLE, indent=2)); return 0
    if argv[0] == "check" and len(argv) >= 3:
        stage = argv[2]
        if stage not in ("plan", "done"):
            print("stage is plan or done"); return 2
        for p in check(load(argv[1]), stage, planned(argv[1]) if stage == "done" else None):
            print(p)
        return 0
    if argv[0] == "show" and len(argv) >= 2:
        print(render(load(argv[1]), planned(argv[1]), argv[2] if len(argv) > 2 else "done")); return 0
    print(__doc__.strip()); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
