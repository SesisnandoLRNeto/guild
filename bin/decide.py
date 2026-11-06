#!/usr/bin/env python3
"""Decision pages: show the guildmaster what each choice leads to, so they choose once and right.

  decide.py open <quest> <spec.json>    build the page from a spec and put it on the war table
  decide.py check <spec.json>           what is wrong with a spec, one line each (nothing: fine)

A decision told in prose makes the reader rebuild it in their head, and that is where rework comes
from. The page shows each kind of decision the way it is best judged:

  how the system should behave  ->  "cases": real situations as rows, each option's outcome per cell
  which approach to build       ->  "flow" per option (mermaid), side by side, and "criteria" to compare
  how a screen should look      ->  "image" per option (and "today"), same size
  something with numbers        ->  "numbers": a bar chart per measure

Every page also has the question in one line, why it must be decided now, the recommendation and its
reason, what happens after each choice, and what happens if nobody answers. Answers: each option,
"Explain more" (questions go back, nothing changes), or "My own answer" (in the notes).

spec.json:
{
  "question": "Should a past start date block the save or warn?",
  "why_now": "The builder ships next; its save path depends on this.",
  "today": {"summary": "A past date saves silently.", "image": "shots/today.png", "flow": "flowchart LR\\n A-->B"},
  "options": [
    {"id": "warn", "label": "Save and warn", "summary": "one line", "flow": "flowchart LR\\n ...",
     "image": "shots/warn.png", "effort": "S", "risk": "low", "reversible": true,
     "pros": ["..."], "cons": ["..."], "after": "what happens next if picked", "blocks": "what it rules out later"}
  ],
  "cases": [{"given": "a rate starting 2020-03-01", "outcomes": {"warn": "201 + BACKDATED", "block": "400"}}],
  "criteria": [{"name": "Finance can fix last month", "values": {"warn": "yes", "block": "no"}, "best": "warn"}],
  "numbers": [{"name": "Save time", "unit": "ms", "values": {"warn": 40, "block": 38}, "lower_is_better": true}],
  "recommend": "warn", "why": "Kim's rule: warn, never block; finance must be able to backdate.",
  "if_no_answer": "Nothing is built; the quest waits on this page.",
  "sources": ["SARA-1071", "Pay rate spec v3.4, section 5"]
}
Images are paths beside the spec (they are copied with the page). Only "question" and two or more
"options" are required; a business rule decision without "cases" is refused, because that table is
what keeps two readers from understanding the same rule differently.
"""
import html
import json
import os
import shutil
import sys
import time

BIN = os.path.dirname(os.path.realpath(__file__))
GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))


def esc(t):
    return html.escape(str(t if t is not None else ""))


def check(spec):
    problems = []
    if not str(spec.get("question", "")).strip():
        problems.append('no "question"')
    opts = spec.get("options") or []
    if len(opts) < 2:
        problems.append('fewer than two "options": a decision needs a choice')
    ids = [o.get("id") for o in opts]
    if len(set(ids)) != len(ids) or not all(ids):
        problems.append("every option needs its own id")
    for o in opts:
        if not o.get("label"):
            problems.append(f'option {o.get("id")} has no "label"')
    if spec.get("kind") == "rule" and not spec.get("cases"):
        problems.append('a business rule decision needs "cases": real situations and what each option does with them')
    for c in spec.get("cases") or []:
        miss = [i for i in ids if i not in (c.get("outcomes") or {})]
        if miss:
            problems.append(f'case "{c.get("given", "")[:40]}" has no outcome for {", ".join(miss)}')
    if spec.get("recommend") and spec["recommend"] not in ids:
        problems.append(f'"recommend" is {spec["recommend"]}, which is not an option')
    if spec.get("recommend") and not spec.get("why"):
        problems.append('a recommendation needs its "why"')
    return problems


def bars(metric, opts, labels):
    """One measure as horizontal bars, one per option, the best one marked."""
    vals = {k: float(v) for k, v in (metric.get("values") or {}).items() if isinstance(v, (int, float))}
    if not vals:
        return ""
    top = max(vals.values()) or 1
    best = (min if metric.get("lower_is_better") else max)(vals, key=vals.get)
    unit = esc(metric.get("unit", ""))
    rows = "".join(
        f'<div class="bar-row"><span class="bl">{esc(labels.get(k, k))}</span>'
        f'<span class="bt"><span class="bf{" best" if k == best else ""}" style="width:{max(2, 100 * v / top):.1f}%"></span></span>'
        f'<span class="bv">{v:g} {unit}{" &#10003;" if k == best else ""}</span></div>' for k, v in vals.items())
    note = "lower is better" if metric.get("lower_is_better") else "higher is better"
    return f'<div class="metric"><h3>{esc(metric.get("name", ""))} <small>{note}</small></h3>{rows}</div>'


def render(spec, md_inline):
    opts = spec["options"]
    labels = {o["id"]: o.get("label", o["id"]) for o in opts}
    rec = spec.get("recommend")
    inl = lambda t: md_inline(str(t or ""), auto_code=True)
    parts = [f'<div class="kicker">a fork in the road: your call</div><h1>{inl(spec["question"])}</h1>']
    if spec.get("why_now"):
        parts.append(f'<p class="lead">{inl(spec["why_now"])}</p>')
    if rec:
        parts.append(f'<div class="rec"><b>Suggested: {esc(labels.get(rec, rec))}.</b> {inl(spec.get("why", ""))}</div>')

    # the options as cards: what it is, effort, risk, can it be undone
    cards = []
    for o in opts:
        chips = []
        if o.get("effort"):
            chips.append(f'<span class="chip">effort {esc(o["effort"])}</span>')
        if o.get("risk"):
            chips.append(f'<span class="chip risk-{esc(str(o["risk"]).lower())}">risk {esc(o["risk"])}</span>')
        if "reversible" in o:
            chips.append(f'<span class="chip {"ok" if o["reversible"] else "warn"}">{"can be undone" if o["reversible"] else "hard to undo"}</span>')
        pc = "".join(f"<li class=\"pro\">{inl(p)}</li>" for p in o.get("pros", [])) + "".join(f"<li class=\"con\">{inl(c)}</li>" for c in o.get("cons", []))
        cards.append(f'<div class="opt{" suggested" if o["id"] == rec else ""}"><div class="oid">Path {esc(o["id"])}{" · suggested" if o["id"] == rec else ""}</div>'
                     f'<h3>{esc(o.get("label", ""))}</h3><p>{inl(o.get("summary", ""))}</p><div class="chips">{"".join(chips)}</div>'
                     + (f"<ul class=\"pc\">{pc}</ul>" if pc else "")
                     + (f'<p class="after"><b>If you pick it:</b> {inl(o["after"])}</p>' if o.get("after") else "")
                     + (f'<p class="blocks"><b>It rules out:</b> {inl(o["blocks"])}</p>' if o.get("blocks") else "") + "</div>")
    parts.append(f'<h2>The paths <small class="plain">(the options)</small></h2><div class="opts n{min(len(opts), 3)}">{"".join(cards)}</div>')

    # what each option does with real situations: the table that prevents two readings of one rule
    if spec.get("cases"):
        head = "".join(f'<th class="{"sug" if o["id"] == rec else ""}">{esc(o.get("label", o["id"]))}</th>' for o in opts)
        rows = "".join(f'<tr><td class="given">{inl(c.get("given", ""))}</td>'
                       + "".join(f'<td class="{"sug" if o["id"] == rec else ""}">{inl((c.get("outcomes") or {}).get(o["id"], ""))}</td>' for o in opts)
                       + "</tr>" for c in spec["cases"])
        parts.append('<h2>What each option does, case by case</h2><p class="hint2">Read a row: one real situation, and exactly what '
                     f'happens under each option.</p><div class="tablewrap"><table class="cases"><tr><th>When</th>{head}</tr>{rows}</table></div>')

    # flows and pictures, side by side, today first
    today = spec.get("today") or {}
    cols = ([("today", "Today", today)] if (today.get("flow") or today.get("image") or today.get("summary")) else []) \
        + [(o["id"], o.get("label", o["id"]), o) for o in opts if o.get("flow") or o.get("image")]
    if len(cols) > (1 if today else 0):
        tiles = []
        for oid, label, o in cols:
            body = (f'<p>{inl(o["summary"])}</p>' if oid == "today" and o.get("summary") else "") \
                + (f'<pre class="mermaid">{esc(o["flow"])}</pre>' if o.get("flow") else "") \
                + (f'<img src="{esc(o["image"])}" alt="{esc(label)}">' if o.get("image") else "")
            tiles.append(f'<div class="col{" today" if oid == "today" else ""}{" sug" if oid == rec else ""}"><h3>{esc(label)}</h3>{body}</div>')
        n = 2 if len(cols) in (2, 4) else min(len(cols), 3)          # four sit as two by two, never three and one
        parts.append(f'<h2>How it works under each option</h2><div class="cols n{n}">{"".join(tiles)}</div>')

    # side-by-side criteria, the best value per row marked
    if spec.get("criteria"):
        head = "".join(f"<th>{esc(o.get('label', o['id']))}</th>" for o in opts)
        rows = "".join(f'<tr><td class="given">{inl(c.get("name", ""))}</td>'
                       + "".join(f'<td class="{"best" if c.get("best") == o["id"] else ""}">{inl((c.get("values") or {}).get(o["id"], ""))}'
                                 f'{" &#10003;" if c.get("best") == o["id"] else ""}</td>' for o in opts) + "</tr>"
                       for c in spec["criteria"])
        parts.append(f'<h2>Compared</h2><div class="tablewrap"><table class="crit"><tr><th></th>{head}</tr>{rows}</table></div>')

    if spec.get("numbers"):
        parts.append("<h2>The numbers</h2>" + "".join(bars(m, opts, labels) for m in spec["numbers"]))

    tail = []
    if spec.get("if_no_answer"):
        tail.append(f'<p><b>If nobody answers:</b> {inl(spec["if_no_answer"])}</p>')
    if spec.get("sources"):
        tail.append("<p><b>Sources:</b> " + ", ".join(inl(s) for s in spec["sources"]) + "</p>")
    tail.append('<p class="hint2">Pick a path on the right, or <b>Explain more</b> with your questions in the notes '
                '(nothing changes until you decide), or <b>My own answer</b> with your words in the notes.</p>')
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import lore
    tail.append(f'<p class="bard"><span class="gi-icon gi-scroll" aria-hidden="true"></span>{esc(lore.quip(spec["question"]))}'
                '<small>the bard</small></p>')
    parts.append('<div class="foot">' + "".join(tail) + "</div>")
    return PAGE.replace("__TITLE__", esc(spec["question"])[:80]).replace("__BODY__", "".join(parts))


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>__TITLE__</title>
<style>
 body { max-width: 1060px; }
 .kicker { font-variant: small-caps; letter-spacing: .08em; color: var(--dim); font-size: 13px; }
 h2 .plain { font-size: 13px; font-weight: 400; color: var(--dim); }
 .bard { margin-top: 14px; font-style: italic; color: var(--dim); } .bard .gi-icon { margin-right: 7px; color: #8a4b12; }
 .bard small { margin-left: 8px; font-style: normal; font-variant: small-caps; letter-spacing: .06em; }
 .rec { border: 1px solid var(--ok); background: rgba(63,125,58,.12); border-radius: 5px; padding: 10px 14px; margin: 10px 0 4px; }
 .rec b { color: var(--ok); }
 .opts { display: grid; gap: 12px; } .opts.n2 { grid-template-columns: 1fr 1fr; } .opts.n3 { grid-template-columns: repeat(3, 1fr); }
 .opt { background: rgba(255,250,235,.62); border: 1px solid var(--line); border-top: 4px solid #9a8b72; border-radius: 5px; padding: 10px 14px; min-width: 0; }
 .opt.suggested { border-top-color: var(--ok); box-shadow: 0 0 0 1px rgba(63,125,58,.35); }
 .opt h3 { margin: 2px 0 4px; font-size: 16px; } .opt h3::before { content: none; }
 .oid { font: 600 11.5px ui-monospace, Menlo, monospace; color: #8a4b12; }
 .opt p { margin: 4px 0; font-size: 14.5px; }
 .chips { display: flex; flex-wrap: wrap; gap: 5px; margin: 6px 0; }
 .chip { font-size: 12px; padding: 2px 8px; border-radius: 999px; background: rgba(90,60,30,.10); }
 .chip.ok, .chip.risk-low { background: rgba(63,125,58,.15); color: var(--ok); }
 .chip.warn, .chip.risk-high { background: rgba(168,50,42,.13); color: var(--bad); }
 .chip.risk-medium { background: rgba(154,106,18,.16); color: #9a5a0c; }
 ul.pc { list-style: none; padding-left: 0; margin: 6px 0; font-size: 14px; }
 ul.pc li { padding-left: 18px; position: relative; margin: 2px 0; }
 ul.pc li::before { content: none !important; }
 ul.pc li.pro::after { content: "+"; position: absolute; left: 2px; top: 0; color: var(--ok); font-weight: 700; }
 ul.pc li.con::after { content: "\\2212"; position: absolute; left: 2px; top: 0; color: var(--bad); font-weight: 700; }
 .after, .blocks { font-size: 13.5px; } .blocks b { color: var(--bad); }
 .hint2 { color: var(--dim); font-size: 13.5px; }
 table.cases td, table.crit td { font-size: 14px; }
 table.cases td.given, table.crit td.given { font-weight: 600; width: 30%; }
 table.cases .sug { background: rgba(63,125,58,.10); }
 table.crit td.best { background: rgba(63,125,58,.13); font-weight: 600; }
 .cols { display: grid; gap: 12px; } .cols.n2 { grid-template-columns: 1fr 1fr; } .cols.n3 { grid-template-columns: repeat(3, 1fr); }
 .col { background: rgba(255,250,235,.55); border: 1px solid var(--line); border-radius: 5px; padding: 4px 12px 10px; min-width: 0; }
 .col.today { border-left: 4px solid #9a8b72; } .col.sug { border-left: 4px solid var(--ok); }
 .col h3 { margin: 8px 0 6px; font-size: 15px; } .col img { width: 100%; border: 1px solid var(--line); border-radius: 3px; }
 pre.mermaid { background: rgba(255,250,235,.7); }
 .metric { margin: 8px 0 14px; } .metric h3 { margin: 0 0 6px; font-size: 15px; } .metric small { color: var(--dim); font-weight: 400; }
 .bar-row { display: grid; grid-template-columns: minmax(110px, 26%) 1fr auto; gap: 10px; align-items: center; font-size: 14px; margin: 3px 0; }
 .bt { display: block; height: 14px; background: rgba(90,60,30,.10); border-radius: 3px; overflow: hidden; }
 .bf { display: block; height: 100%; background: #9a8b72; } .bf.best { background: var(--ok); }
 .foot { margin-top: 18px; border-top: 1px solid var(--line); padding-top: 10px; font-size: 14px; }
 @media (max-width: 760px) { .opts.n2, .opts.n3, .cols.n2, .cols.n3 { grid-template-columns: 1fr; } }
</style></head><body>__BODY__
<script src="/vendor/mermaid.min.js"></script>
<script>if (window.mermaid) mermaid.initialize({ startOnLoad: true, theme: "neutral", securityLevel: "strict" });</script>
</body></html>
"""


def side_panel(spec):
    """The war table's answer panel: each option, Explain more, My own answer."""
    opts = [{"id": o["id"], "label": o.get("label", o["id"]), "why": o.get("summary", "")} for o in spec["options"]]
    opts += [{"id": "explain", "label": "Explain more", "why": "something is not clear: your questions go back, nothing changes"},
             {"id": "own", "label": "My own answer", "why": "none of these: write yours in the notes"}]
    return {"questions": [{"id": "choice", "title": spec["question"], "type": "single",
                           "recommended": spec.get("recommend"), "options": opts}]}


def open_page(quest, spec_path):
    spec = json.load(open(spec_path))
    problems = check(spec)
    if problems:
        raise SystemExit("guild decide: the spec is not ready:\n" + "\n".join(f"  - {p}" for p in problems))
    sys.path.insert(0, BIN)
    import wartable
    tmp = os.path.join(GUILD_HOME, f".decide-{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    src = os.path.dirname(os.path.abspath(spec_path))
    for o in list(spec["options"]) + [spec.get("today") or {}]:      # images travel with the page
        if o.get("image") and os.path.exists(os.path.join(src, o["image"])):
            dst = os.path.join(tmp, o["image"])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(os.path.join(src, o["image"]), dst)
    open(os.path.join(tmp, "page.html"), "w").write(render(spec, wartable.md_inline))
    json.dump(side_panel(spec), open(os.path.join(tmp, "decisions.json"), "w"), indent=2)
    try:
        wartable.cmd_open({"quest": quest, "html": os.path.join(tmp, "page.html"), "decisions": os.path.join(tmp, "decisions.json"),
                           "assets": True, "title": spec["question"][:90], "no_open": os.environ.get("GUILD_BOARD_NO_OPEN") == "1"})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "open":
        open_page(a[1], a[2])
    elif len(a) == 2 and a[0] == "check":
        p = check(json.load(open(a[1])))
        print("\n".join(p))
        sys.exit(1 if p else 0)
    else:
        raise SystemExit(__doc__)
