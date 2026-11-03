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


def missing(md):
    parts = split(md)
    return [k for k in REQUIRED if not parts.get(k)]


def template():
    """The skeleton the adventurer fills in, for the refusal message and the prompt."""
    return "\n".join(f"## {TITLES[k]}{'' if req else ' (optional)'}\n<{hint}>" for k, _, req, hint in SECTIONS)


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
# sure about. It grills the plan in your favour, so it is kept for the plans worth it.
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


def wants_review(parts, why_card, force=False):
    """Not every plan: when asked (--grill), or a feature you wrote a Why card for that has five or more
    build steps or questions for you. A small fix keeps the plain approve, explain or change."""
    if force:
        return True
    return bool(why_card) and (len(list_items(parts.get("how", ""))) >= 5 or bool(parts.get("questions")))


def review_html(quest, groups):
    esc = html.escape
    total = sum(len(points) for _, _, points in groups)
    nav = " ".join(f'<a href="#rv-{k}">{i}. {esc(t)}</a>' for i, (k, t, _) in enumerate(groups, 1))
    body = ""
    for i, (key, title, points) in enumerate(groups, 1):
        body += f'<h3 id="rv-{key}" class="rv-h">{i}. {esc(title)}</h3>'
        for num, text in points:
            body += (f'<div class="rv" data-id="{num}"><span class="rv-n">{num}</span><div class="rv-b">'
                     f'<p class="rv-t">{esc(text)}</p><div class="rv-btns">'
                     '<button type="button" data-m="agree">Agree</button>'
                     '<button type="button" data-m="change">Change</button>'
                     '<button type="button" data-m="unsure">Not sure</button></div>'
                     '<textarea class="rv-note" rows="2" placeholder="What should change, or what is not clear?"></textarea>'
                     '</div></div>')
    return (REVIEW.replace("__NAV__", nav).replace("__POINTS__", body).replace("__TOTAL__", str(total))
            .replace("__KEY__", esc(quest)))


def render(quest, summary, md, meta, why_card, contract, go, md_to_html, md_inline, plan_path, review=False):
    parts = split(md)
    esc = html.escape
    card = lambda k, cls="": (f'<section class="sec {cls}"><h2>{TITLES[k]}</h2>{md_to_html(parts[k])}</section>'
                              if parts.get(k) else "")
    minute = "".join(f'<div class="m {k}"><b>{label}</b><p>{md_inline(first_lines(parts.get(k, "")), auto_code=True)}</p></div>'
                     for k, label in (("pain", "The pain"), ("cause", "Why it happens"), ("expect", "What you should expect")))
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
        compare = ('<p class="lead2 warn">No Why card yet for this quest, so there is nothing of yours to compare with. '
                   f'<code>guild why open {esc(quest)}</code> puts it on the docket.</p>')
    items = (contract or {}).get("items", [])
    if items:
        contract_html = "<ul class=\"contract\">" + "".join(
            f"<li><code>{esc(i['run'])}</code></li>" if i["kind"] == "check" else f"<li>{md_inline(i['text'], auto_code=True)}</li>"
            for i in items) + "</ul>"
    else:
        contract_html = f"<p class=\"lead2 warn\">No acceptance contract: {esc(meta.get('no_acceptance') or 'none was written')}.</p>"
    return (PAGE.replace("__QUEST__", esc(quest)).replace("__SUMMARY__", md_inline(summary or "", auto_code=True))
            .replace("__MINUTE__", minute)
            .replace("__TODAY__", md_to_html(parts.get("today", "")))
            .replace("__AFTER__", md_to_html(parts.get("after", "")))
            .replace("__COMPARE__", compare)
            .replace("__CONTRACT__", contract_html)
            .replace("__REST__", "".join(card(k) for k in ("pain", "cause", "how", "scope", "risks", "words", "questions", "files")
                                         if k not in ("pain", "cause") or longer(parts.get(k, ""))))
            .replace("__REVIEW__", review_html(quest, review_points(parts)) if review else "")
            .replace("__IF_GO__", "".join(f"<li>{x}</li>" for x in go))
            .replace("__PATH__", esc(plan_path)))


REVIEW = """<section class="review" id="review">
<h2>Agree, point by point</h2>
<p class="lead2">This plan is worth a closer look. Mark each point: <b>Agree</b>, <b>Change</b> or <b>Not sure</b>.
A change or a doubt asks for a short note. Your marks go to the adventurer with your answer on the right, and
the answer is picked for you from them (you can still change it).</p>
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
  var KEY = "guild-review:" + location.pathname, rows = [].slice.call(document.querySelectorAll(".rv")), marks = {};
  try { marks = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
  function save() { try { localStorage.setItem(KEY, JSON.stringify(marks)); } catch (e) {} }
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
      return { id: r.dataset.id, point: r.querySelector(".rv-t").textContent, mark: m.mark || "", note: m.note || "" };
    });
    try { parent.postMessage({ type: "guild-review", points: list, total: rows.length }, location.origin); } catch (e) {}
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
  paint();
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
 .minute { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 0 0 8px; }
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
<h2>In one minute</h2>
<div class="minute">__MINUTE__</div>
<h2>Today, and after this plan</h2>
<div class="ta"><div class="today"><h3>Today</h3>__TODAY__</div><div class="after"><h3>After this plan</h3>__AFTER__</div></div>
__COMPARE__
<h2>What "done" means</h2>
<p class="lead2">The acceptance contract, sealed when the quest started. The trial and the checks judge the work against it.</p>
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
