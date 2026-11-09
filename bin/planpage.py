"""The plan approval page as an explainer: understand the why, the what and the how before you approve.

plan.md is written in fixed sections, so the page can put them where they help: the pain, the
cause and the expectation in one minute at the top; today and after this plan side by side; your
own Why card next to the plan's understanding, so a misunderstanding shows before any code; the
sealed acceptance contract; then how it will be built, what is not included, the risks, the words
to know and the questions for you. `guild plan ready` refuses a plan missing a required section.
"""
import html
import json
import os
import re

# key, headings that count (lowercase, startswith), required, what it holds
SECTIONS = [
    ("pain", ("the pain", "pain"), True, "who suffers today, where (screen, endpoint, process), one real example with its evidence"),
    ("cause", ("why it happens", "root cause", "cause"), True, "the root cause in plain words, and where it lives (`file:line`)"),
    ("today", ("today", "what exists today", "current state"), True, "how it works now: what exists, what it does"),
    ("after", ("after this plan", "after", "what changes"), True, "how it will work, against today; what is added, changed, removed"),
    ("how", ("how it will be built", "how", "steps"), True, "numbered steps, one idea each, names in backticks"),
    ("expect", ("what you should expect", "expectations", "what to expect", "how it will be proven"), True,
     "what you will see when it works, and how it is proven (the acceptance checks)"),
    ("scope", ("not included", "out of scope"), True, "what this plan does not do, and why"),
    ("risks", ("risks",), True, "what could go wrong, and what is done about each"),
    ("words", ("words to know", "words", "glossary"), False, "domain terms the plan uses, one line each"),
    ("questions", ("questions for you", "questions"), False, "decisions only you can make, each with the options"),
    ("files", ("files",), False, "the files it touches"),
]
REQUIRED = [s[0] for s in SECTIONS if s[2]]
# A screen says more than a paragraph about a screen: plan.md can carry ![what to look at](path) pictures.
IMG = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
UI_WORDS = re.compile(r"\b(modal|screen|button|dialog|drawer|dropdown|tab|form|toast|banner|tooltip|menu|ui|frontend|"
                      r"page|popup|checkbox|sidebar|navbar|placeholder)s?\b", re.I)
SHOT_BEFORE, SHOT_AFTER = ("pain", "cause", "today"), ("after", "expect", "how")


def needs_picture(parts):
    """The pain is on a screen, the plan shows none, and it did not say why it cannot."""
    text = " ".join(parts.get(k, "") for k in ("pain", "today"))
    if IMG.search(" ".join(parts.values())) or "no screen picture" in text.lower():
        return False
    return bool(UI_WORDS.search(IMG.sub("", text)))
TITLES = {"pain": "The pain", "cause": "Why it happens", "today": "Today", "after": "After this plan",
          "how": "How it will be built", "expect": "What you should expect", "scope": "Not included",
          "risks": "Risks", "words": "Words to know", "questions": "Questions for you", "files": "Files"}


def split(md):
    """{section key: its Markdown} from plan.md's `## ` headings; unknown headings go with the one before."""
    out, key = {}, None
    for line in md.splitlines():
        m = re.match(r"^##\s+(.*)", line)
        if m:
            title = m.group(1).strip().lower()
            key = next((k for k, names, _, _ in SECTIONS if any(title.startswith(n) for n in names)), key or "_intro")
            out.setdefault(key, [])
            continue
        out.setdefault(key or "_intro", []).append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


# Not every plan needs every section. The shape says how much you must read to agree:
#   small     a fix with a few steps: what will be done and how you will know it works
#   standard  the pain, the cause, the change, the steps, the proof; you mark only the risks and questions
#   full      everything, and every point is marked, until you agree to all of it
SHAPES = ("small", "standard", "full")
NEEDS = {"small": ["how", "expect"], "standard": ["pain", "cause", "after", "how", "expect"], "full": REQUIRED}
SHAPE_LEAD = {"small": "A small plan: what will be done, and how you will know it works.",
              "standard": "Read the change and the steps. Only the risks and the questions ask for your mark.",
              "full": "A plan worth a close look: every point asks for your mark, and you approve when you agree to all of them."}


def shape(parts, why_card=None, forced=""):
    """small, standard or full, from what the plan holds; the adventurer can force one (--shape)."""
    if forced in SHAPES:
        return forced
    steps = len(list_items(parts.get("how", "")))
    questions = len(list_items(parts.get("questions", ""))) if parts.get("questions") else 0
    if why_card or steps >= 6 or (questions and steps >= 4):
        return "full"
    if steps <= 3 and not questions and not parts.get("cause"):
        return "small"
    return "standard"


def missing(md, kind=None):
    parts = split(md)
    return [k for k in NEEDS[kind or shape(parts)] if not parts.get(k)]


def template(kind="full"):
    """The skeleton the adventurer fills in, for the refusal message and the prompt."""
    return "\n".join(f"## {TITLES[k]}{'' if k in NEEDS[kind] else ' (optional)'}\n<{hint}>" for k, _, req, hint in SECTIONS)


def first_lines(md, limit=260):
    """The opening of a section as one short plain line, for the one-minute summary."""
    text = re.sub(r"```.*?```", "", md, flags=re.S)
    para = next((p for p in re.split(r"\n\s*\n", text) if p.strip()), "")
    para = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", para, flags=re.M)
    para = re.sub(r"\s+", " ", para).strip()
    return para if len(para) <= limit else para[:limit].rsplit(" ", 1)[0] + "..."


def longer(md):
    """Whether a section says more than its one-minute line (then it gets its own full section too)."""
    flat = re.sub(r"\s+", " ", re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", md, flags=re.M)).strip()
    return bool(md.strip()) and first_lines(md) != flat


# The agreement review: every claim of the plan as a point you agree with, want changed, or are not
# sure about. The plan is approved only when every point shown is Agree, and each Change or Not
# sure goes back to the adventurer, who answers it in plan.md and asks again. The shape decides
# which points are shown (review_groups).
REVIEW_GROUPS = [("understood", "What it understood"), ("after", "What changes"), ("how", "How it will be built"),
                 ("scope", "Not included"), ("risks", "Risks"), ("questions", "Questions for you")]


def plain(text):
    """A Markdown line as plain words, for a point's title."""
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def list_items(md):
    """Top-level list items of a section (a wrapped line joins its item); no list means one point."""
    text = re.sub(r"```.*?```", "", md or "", flags=re.S)
    items, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^(?:[-*]|\d+[.)])\s+(.*)", line)
        if m:
            cur = [m.group(1)]
            items.append(cur)
        elif cur is not None and line.startswith((" ", "\t")) and line.strip() and not re.match(r"^\s+(?:[-*]|\d+[.)])\s", line):
            cur.append(line.strip())
        elif not line.strip():
            continue
        elif cur is not None and not line.startswith((" ", "\t")):
            cur = None
    if items:
        return [plain(" ".join(i)) for i in items if plain(" ".join(i))]
    first = first_lines(md or "", 400)
    return [plain(first)] if first else []


def review_points(parts):
    """[(group key, title, [(number, text, detail)])], numbered 1.1, 1.2, 2.1 ..."""
    out, n = [], 0
    for key, title in REVIEW_GROUPS:
        if key == "understood":
            texts = [t for t in (first_lines(parts.get("pain", ""), 300), first_lines(parts.get("cause", ""), 300)) if t]
            texts = [plain(t) for t in texts]
        else:
            texts = list_items(parts.get(key, ""))
        if not texts:
            continue
        n += 1
        out.append((key, title, [(f"{n}.{i}", t) for i, t in enumerate(texts, 1)]))
    return out


def review_groups(parts, kind):
    """The points you mark: none on a small plan, the risks and questions on a standard one, all on a full one."""
    if kind == "small":
        return []
    groups = review_points(parts)
    return groups if kind == "full" else [g for g in groups if g[0] in ("risks", "questions")]


def review_html(quest, groups, head="Agree, point by point", lead=None, change="Change", label="Plan review"):
    """The point grid. A point is (number, text) or (number, text, detail html shown under it).
    The findings page reuses it with Disagree in place of Change."""
    esc = html.escape
    total = sum(len(points) for _, _, points in groups)
    nav = " ".join(f'<a href="#rv-{k}">{i}. {esc(t)}</a>' for i, (k, t, _) in enumerate(groups, 1))
    body = ""
    for i, (key, title, points) in enumerate(groups, 1):
        body += f'<h3 id="rv-{key}" class="rv-h">{i}. {esc(title)}</h3>'
        for num, text, *detail in points:
            body += (f'<div class="rv" data-id="{num}"><span class="rv-n">{num}</span><div class="rv-b">'
                     f'<p class="rv-t">{esc(text)}</p>{"".join(detail)}<div class="rv-btns">'
                     '<button type="button" data-m="agree">Agree</button>'
                     f'<button type="button" data-m="change">{esc(change)}</button>'
                     '<button type="button" data-m="unsure">Not sure</button></div>'
                     '<textarea class="rv-note" rows="2" placeholder="What should change, or what is not clear?"></textarea>'
                     '</div></div>')
    page = REVIEW if lead is None else re.sub(r'<p class="lead2">.*?</p>', lambda m: f'<p class="lead2">{lead}</p>', REVIEW, count=1, flags=re.S)
    return (page.replace("__HEAD__", esc(head)).replace("__LABEL__", esc(label)).replace("__CHANGE__", esc(change.lower()))
            .replace("__NAV__", nav).replace("__POINTS__", body).replace("__TOTAL__", str(total))
            .replace("__KEY__", esc(quest)))


VIDEO = """<section class="pvideo" data-q="__Q__"><h2>Watch the plan</h2>
<video controls playsinline preload="metadata" hidden></video>
<p class="pv-wait">The video is being made (about two minutes). It plays here when it is ready.</p></section>
<script>(function () {
  const box = document.querySelector('.pvideo'), v = box.querySelector('video'), w = box.querySelector('.pv-wait');
  const q = '/q/' + box.dataset.q + '/video';
  function look() {
    fetch(q + '.json', {cache: 'no-store'}).then((r) => r.json()).then((s) => {
      if (s.state === 'ready') { v.src = q + '.mp4?v=' + (s.hash || ''); v.hidden = false; w.hidden = true; }
      else if (s.state === 'failed') { w.textContent = 'The video could not be made: ' + (s.error || 'see video/build.log'); }
      else if (s.state === 'none') { box.hidden = true; }
      else setTimeout(look, 4000);
    }).catch(() => setTimeout(look, 8000));
  }
  look();
})();</script>"""


def render(quest, summary, md, meta, why_card, contract, go, md_to_html, md_inline, plan_path, kind="full", video=False):
    parts = split(md)
    esc = html.escape
    shots = {k: IMG.findall(v) for k, v in parts.items()}
    parts = {k: IMG.sub("", v).strip() for k, v in parts.items()}
    groups = review_groups(parts, kind)
    card = lambda k, cls="": (f'<section class="sec {cls}"><h2>{TITLES[k]}</h2>{md_to_html(parts[k])}</section>'
                              if parts.get(k) else "")
    minute = "".join(f'<div class="m {k}"><b>{label}</b><p>{md_inline(first_lines(parts.get(k, "")), auto_code=True)}</p></div>'
                     for k, label in (("pain", "The pain"), ("cause", "Why it happens"), ("expect", "What you should expect"))
                     if parts.get(k))
    n = minute.count('<div class="m ')
    minute = f'<h2>In one minute</h2><div class="minute n{n}">{minute}</div>' if minute else ""
    fig = lambda cap, src: (f'<figure><a href="{esc(src)}" target="_blank"><img src="{esc(src)}" alt="{esc(cap)}"></a>'
                            + (f"<figcaption>{md_inline(cap, auto_code=True)}</figcaption>" if cap else "") + "</figure>")
    before = [x for k in SHOT_BEFORE for x in shots.get(k, [])]
    after = [x for k in SHOT_AFTER for x in shots.get(k, [])]
    other = [x for k, v in shots.items() if k not in SHOT_BEFORE + SHOT_AFTER for x in v]
    cols = [(t, xs) for t, xs in (("Today", before + other), ("After this plan", after)) if xs]
    if cols:
        minute += ('<h2>On screen</h2><div class="shots n' + str(len(cols)) + '">'
                   + "".join(f'<div class="shot"><h3>{t}</h3>{"".join(fig(c, s_) for c, s_ in xs)}</div>' for t, xs in cols)
                   + "</div>")
    if parts.get("today") or parts.get("after"):
        ta = ('<h2>Today, and after this plan</h2><div class="ta">'
              + (f'<div class="today"><h3>Today</h3>{md_to_html(parts["today"])}</div>' if parts.get("today") else "")
              + (f'<div class="after"><h3>After this plan</h3>{md_to_html(parts["after"])}</div>' if parts.get("after") else "")
              + "</div>")
    else:
        ta = ""
    if why_card:
        mine = "".join(f'<div class="row"><b>{esc(label)}</b><span>{esc(why_card.get(k) or "(left empty)")}</span></div>'
                       for k, label in (("pain", "Pain"), ("rule", "Rule"), ("decision", "Decision"), ("impact", "Impact"), ("future", "Future")))
        theirs = "".join(f'<div class="row"><b>{label}</b><span>{md_inline(first_lines(parts.get(k, ""), 400), auto_code=True)}</span></div>'
                         for k, label in (("pain", "Pain"), ("cause", "Why"), ("after", "What changes"), ("expect", "Expect"), ("scope", "Not included")))
        compare = ('<h2>Your Why card and the plan, side by side</h2><p class="lead2">Read them together. Where they '
                   'disagree, that is a misunderstanding: ask before you approve, not after the code exists.</p>'
                   f'<div class="cmp"><div class="col yours"><h3>Your words</h3>{mine}</div>'
                   f'<div class="col plan"><h3>The plan\'s understanding</h3>{theirs}</div></div>')
    else:
        compare = ""                                    # the Why card is optional: no card, no block
    items = (contract or {}).get("items", [])
    if items:
        contract_html = "<ul class=\"contract\">" + "".join(
            f"<li><code>{esc(i['run'])}</code></li>" if i["kind"] == "check" else f"<li>{md_inline(i['text'], auto_code=True)}</li>"
            for i in items) + "</ul>"
    else:
        contract_html = ""
    if contract_html:
        contract_html = ('<h2>What "done" means</h2><p class="lead2">The acceptance contract, sealed when the quest started. '
                         'The trial and the checks judge the work against it.</p>' + contract_html)
    elif kind != "small":
        contract_html = f"<p class=\"lead2 warn\">No acceptance contract: {esc(meta.get('no_acceptance') or 'none was written')}.</p>"
    reel = (f'<p class="reel"><a href="/q/{esc(quest)}/reel" target="_blank">Watch the reel</a>: this plan as a short '
            'animated story, if you would rather watch than read.</p>') if kind == "full" else ""
    if video:                                       # the adventurer told the plan as a video: it comes first
        reel = VIDEO.replace("__Q__", esc(quest))
    return (PAGE.replace("__QUEST__", esc(quest)).replace("__SUMMARY__", md_inline(summary or "", auto_code=True))
            .replace("__SHAPE__", SHAPE_LEAD[kind]).replace("__REEL__", reel)
            .replace("__MINUTE__", minute)
            .replace("__TA__", ta)
            .replace("__COMPARE__", compare)
            .replace("__CONTRACT__", contract_html)
            .replace("__REST__", "".join(card(k) for k in ("pain", "cause", "how", "scope", "risks", "words", "questions", "files")
                                         if k not in ("pain", "cause") or longer(parts.get(k, ""))))
            .replace("__REVIEW__", review_html(quest, groups) if groups else "")
            .replace("__IF_GO__", "".join(f"<li>{x}</li>" for x in go))
            .replace("__PATH__", esc(plan_path)))


REVIEW = """<section class="review" id="review" data-label="__LABEL__" data-change="__CHANGE__">
<h2>__HEAD__</h2>
<p class="lead2">Mark each point below: <b>Agree</b>, <b>Change</b> or <b>Not sure</b>. A change or a doubt asks for a
short note. You can approve only when every point is Agree. Until then your marks go back to the adventurer, it
answers in the plan, and you get this page again: points you agreed stay agreed, new or changed ones are marked
<span class="rv-new">new</span>.</p>
<p class="rv-nav">__NAV__</p>
__POINTS__
<div class="rv-bar"><span><b class="c-agree">0</b> agree</span><span><b class="c-change">0</b> change</span>
<span><b class="c-unsure">0</b> not sure</span><span class="c-left">__TOTAL__ of __TOTAL__ left</span>
<button type="button" class="rv-all">Agree to the rest</button><button type="button" class="rv-clear">Clear marks</button></div>
</section>
<style>
 .review { margin-top: 18px; }
 .rv-nav a { margin-right: 12px; font-size: 14px; }
 .rv-h { margin: 18px 0 8px; font-size: 16px; }
 .rv { display: grid; grid-template-columns: 44px 1fr; gap: 8px; border: 1px solid var(--line); border-radius: 6px;
       padding: 10px 14px; margin: 0 0 8px; background: var(--card); }
 .rv-n { font-family: ui-monospace, monospace; font-size: 12px; color: var(--dim); padding-top: 3px; }
 .rv-t { margin: 0 0 8px; }
 .rv-d { font-size: 14px; margin: 0 0 8px; } .rv-d p { margin: 2px 0; } .rv-d .sev { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
 .rv-new { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #e0b84a; border: 1px solid #e0b84a;
           border-radius: 999px; padding: 0 7px; margin-left: 6px; }
 .rv-btns button { font: inherit; font-size: 13px; border: 1px solid var(--line); background: transparent; color: inherit;
                   border-radius: 999px; padding: 3px 12px; margin-right: 6px; cursor: pointer; }
 .rv-note { display: none; box-sizing: border-box; width: 100%; margin-top: 8px; font: inherit; font-size: 14px; }
 .rv.change .rv-note, .rv.unsure .rv-note { display: block; }
 .rv.agree { border-color: #5f9b4a; } .rv.agree button[data-m=agree] { border-color: #5f9b4a; color: #8fcf6a; }
 .rv.change { border-color: #c9832e; } .rv.change button[data-m=change] { border-color: #c9832e; color: #f0a64a; }
 .rv.unsure { border-color: #8a6fc9; } .rv.unsure button[data-m=unsure] { border-color: #8a6fc9; color: #b49cf0; }
 .rv-bar { position: sticky; bottom: 0; display: flex; flex-wrap: wrap; gap: 14px; align-items: center; padding: 10px 14px;
           margin-top: 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--card); font-size: 14px; z-index: 5; }
 .rv-bar .c-agree { color: #8fcf6a; } .rv-bar .c-change { color: #f0a64a; } .rv-bar .c-unsure { color: #b49cf0; }
 .rv-bar .c-left { color: var(--dim); margin-right: auto; }
 .rv-bar button { font: inherit; font-size: 13px; border: 1px solid var(--line); background: transparent; color: inherit; border-radius: 6px; padding: 5px 12px; cursor: pointer; }
 html.realm.rm-dark .rv, html.realm.rm-dark .rv-bar { background: linear-gradient(180deg, #241d2b, #17121c); border-color: #4a3f52; }
 html.realm.rm-dark .rv.agree { border-color: #5f9b4a; } html.realm.rm-dark .rv.change { border-color: #c9832e; } html.realm.rm-dark .rv.unsure { border-color: #8a6fc9; }
 html.realm.rm-dark .rv-note { background: rgba(0,0,0,.3); color: var(--rm-text); border: 1px solid #4a3f52; border-radius: 4px; }
</style>
<script>
(function () {
  // Marks live per quest and point text, so a plan asked again keeps what you agreed. A new round
  // (another board) keeps only Agree: a doubt you had must be read again against the new answer.
  var KEY = "guild-review:__KEY__", rows = [].slice.call(document.querySelectorAll(".rv")), marks = {}, store = {};
  try { store = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
  var same = store.page === location.pathname, byText = store.marks || {};
  var before = same ? store.before : store.texts;          // the texts of the round before this one
  rows.forEach(function (r) {
    var t = r.querySelector(".rv-t").textContent, m = byText[t];
    r.dataset.text = t;
    if (m && (same || m.mark === "agree")) marks[r.dataset.id] = m;
    if (before && before.indexOf(t) < 0) r.querySelector(".rv-t").insertAdjacentHTML("beforeend", ' <span class="rv-new">new</span>');
  });
  function save() {
    var keep = {};
    rows.forEach(function (r) { if (marks[r.dataset.id]) keep[r.dataset.text] = marks[r.dataset.id]; });
    var texts = rows.map(function (r) { return r.dataset.text; });
    try { localStorage.setItem(KEY, JSON.stringify({ page: location.pathname, texts: texts, before: before || null, marks: keep })); } catch (e) {}
  }
  function paint() {
    var c = { agree: 0, change: 0, unsure: 0 };
    rows.forEach(function (r) {
      var m = marks[r.dataset.id] || {};
      r.classList.remove("agree", "change", "unsure");
      if (m.mark) { r.classList.add(m.mark); c[m.mark]++; }
      var t = r.querySelector(".rv-note"); if (t.value !== (m.note || "")) t.value = m.note || "";
    });
    document.querySelector(".c-agree").textContent = c.agree;
    document.querySelector(".c-change").textContent = c.change;
    document.querySelector(".c-unsure").textContent = c.unsure;
    var left = rows.length - c.agree - c.change - c.unsure;
    document.querySelector(".c-left").textContent = left + " of " + rows.length + " left";
    var list = rows.map(function (r) {
      var m = marks[r.dataset.id] || {};
      return { id: r.dataset.id, point: r.dataset.text, mark: m.mark || "", note: m.note || "" };
    });
    var sec = document.getElementById("review");
    try { parent.postMessage({ type: "guild-review", points: list, total: rows.length, label: sec.dataset.label,
                               change: sec.dataset.change }, location.origin); } catch (e) {}
  }
  rows.forEach(function (r) {
    r.querySelectorAll("button").forEach(function (b) {
      b.onclick = function () {
        var m = marks[r.dataset.id] || {};
        m.mark = m.mark === b.dataset.m ? "" : b.dataset.m;
        marks[r.dataset.id] = m; save(); paint();
        if (m.mark === "change" || m.mark === "unsure") r.querySelector(".rv-note").focus();
      };
    });
    r.querySelector(".rv-note").oninput = function (e) {
      var m = marks[r.dataset.id] || {}; m.note = e.target.value; marks[r.dataset.id] = m; save(); paint();
    };
  });
  document.querySelector(".rv-all").onclick = function () {
    rows.forEach(function (r) { var m = marks[r.dataset.id] || {}; if (!m.mark) { m.mark = "agree"; marks[r.dataset.id] = m; } });
    save(); paint();
  };
  document.querySelector(".rv-clear").onclick = function () { marks = {}; save(); paint(); };
  save(); paint();
})();
</script>
"""


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Understand the plan</title>
<style>
 body { max-width: 1040px; }
 .kicker { font-variant: small-caps; letter-spacing: .08em; color: var(--dim); font-size: 13px; }
 .summary { font-size: 17px; margin: 6px 0 18px; }
 .pvideo { margin: 0 0 18px; } .pvideo video { display: block; width: 100%; max-width: 360px; aspect-ratio: 9 / 16;
   margin: 0 auto; border-radius: 10px; background: #000; } .pvideo .pv-wait { color: var(--dim); font-style: italic; }
 .minute { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 0 0 8px; }
 .minute.n1 { grid-template-columns: 1fr; } .minute.n2 { grid-template-columns: 1fr 1fr; }
 .shots { display: grid; grid-template-columns: 1fr; gap: 14px; margin: 0 0 8px; } .shots.n2 { grid-template-columns: 1fr 1fr; }
 .shot h3 { margin: 0 0 6px; font-size: 15px; } .shot figure { margin: 0 0 10px; }
 .shot img { display: block; max-width: 100%; border: 1px solid var(--line); border-radius: 4px; }
 .shot figcaption { font-size: 13.5px; color: var(--dim); margin-top: 4px; }
 @media (max-width: 760px) { .shots.n2 { grid-template-columns: 1fr; } }
 .ta:has(> div:only-child) { grid-template-columns: 1fr; }
 .reel a { font-weight: 600; }
 .minute .m { background: rgba(255,250,235,.62); border: 1px solid var(--line); border-top: 4px solid #8a4b12; border-radius: 4px; padding: 10px 14px; }
 .minute .m.pain { border-top-color: var(--bad); } .minute .m.expect { border-top-color: var(--ok); }
 .minute b { font-variant: small-caps; font-size: 14px; color: #4a2f1a; }
 .minute p { margin: 4px 0 0; font-size: 14.5px; }
 .ta { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
 .ta > div { background: rgba(255,250,235,.55); border: 1px solid var(--line); border-radius: 4px; padding: 4px 16px 10px; min-width: 0; }
 .ta > div.after { border-left: 4px solid var(--ok); } .ta > div.today { border-left: 4px solid #9a8b72; }
 .ta h3 { margin: 10px 0 4px; font-size: 15px; }
 .cmp { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
 .cmp .col { background: rgba(255,250,235,.6); border: 1px solid var(--line); border-radius: 4px; padding: 6px 14px 10px; }
 .cmp .yours { border-left: 4px solid #b5651d; } .cmp .plan { border-left: 4px solid #3f7fc4; }
 .cmp h3 { margin: 8px 0 6px; font-size: 15px; } .cmp h3::before { content: none; }
 .row { display: grid; grid-template-columns: 100px 1fr; gap: 8px; font-size: 14px; padding: 3px 0; border-bottom: 1px dashed var(--line); }
 .row b { font-variant: small-caps; color: #8a4b12; }
 .lead2 { color: var(--dim); font-size: 14px; margin: 0 0 10px; } .lead2.warn { color: #9a5a0c; }
 .contract li { margin: 4px 0; }
 .sec { margin-top: 6px; }
 .sec ol > li { margin: 0 0 10px; }
 .sec code { overflow-wrap: anywhere; } .sec pre code { white-space: pre; }
 .tablewrap { overflow-x: auto; margin: 8px 0 12px; }
 pre.mermaid { background: rgba(255,250,235,.7); }
 .next { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-top: 20px; }
 .next div { background: var(--card); border: 1px solid var(--line); border-radius: 4px; padding: 10px 14px; }
 .next div.go { border-left: 4px solid var(--ok); } .next div.change { border-left: 4px solid var(--accent); }
 .next div.explain { border-left: 4px solid #3f7fc4; }
 .next h3 { margin: 0 0 6px; font-size: 15px; } .next ol { margin: 0; padding-left: 20px; font-size: 14px; }
 .hint { color: var(--dim); font-size: 13px; margin-top: 18px; }
 @media (max-width: 760px) { .minute, .ta, .cmp, .next { grid-template-columns: 1fr; } }
 /* the realm: the cards sit on dark stone like every other page, not on see-through parchment */
 html.realm.rm-dark .minute .m, html.realm.rm-dark .ta > div, html.realm.rm-dark .cmp .col, html.realm.rm-dark .next div {
   background: linear-gradient(180deg, #241d2b, #17121c); border-color: #4a3f52; color: var(--rm-text);
   box-shadow: inset 0 0 0 1px rgba(217, 164, 65, .10), 0 6px 14px rgba(0, 0, 0, .45); }
 html.realm.rm-dark .minute .m { border-top-color: var(--rm-gold); }
 html.realm.rm-dark .minute .m.pain { border-top-color: #e0573f; } html.realm.rm-dark .minute .m.expect { border-top-color: #8fb35a; }
 html.realm.rm-dark .ta > div.today { border-left-color: #a8987a; } html.realm.rm-dark .ta > div.after { border-left-color: #8fb35a; }
 html.realm.rm-dark .minute b, html.realm.rm-dark .row b { color: #f3cf6c; }
 html.realm.rm-dark .lead2.warn { color: #e0a93a; }
 html.realm.rm-dark .tablewrap th, html.realm.rm-dark .sec th { background: rgba(217, 164, 65, .10); color: #f3cf6c; }
 html.realm.rm-dark .tablewrap td, html.realm.rm-dark .sec td { border-color: #4a3f52; }
 html.realm.rm-dark pre.mermaid { background: #f3e7c9; border: 1px solid #8a6a1e; border-radius: 4px; }
</style></head><body>
<div class="kicker">__QUEST__ · read the map, then give the order</div>
<h1>Understand the plan</h1>
<p class="summary">__SUMMARY__</p>
<p class="lead2 shape">__SHAPE__</p>
__REEL__
__MINUTE__
__TA__
__COMPARE__
__CONTRACT__
__REST__
__REVIEW__
<h2>What happens next</h2>
<div class="next">
 <div class="go"><h3>Approve</h3><ol>__IF_GO__</ol></div>
 <div class="explain"><h3>Explain more</h3><ol>
  <li>Write what is not clear in the notes on the right.</li>
  <li>The adventurer answers on this page and asks again.</li>
  <li>Nothing changes and nothing is built yet.</li></ol></div>
 <div class="change"><h3>Change it</h3><ol>
  <li>Write what to change in the notes on the right.</li>
  <li>The adventurer updates the plan and puts it here again.</li>
  <li>Nothing is built until you approve.</li></ol></div>
</div>
<p class="hint">The full plan file: <code>__PATH__</code></p>
<script src="/vendor/mermaid.min.js"></script>
<script>if (window.mermaid) mermaid.initialize({ startOnLoad: true, theme: "neutral", securityLevel: "strict" });</script>
</body></html>
"""
