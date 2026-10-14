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


def render(quest, summary, md, meta, why_card, contract, go, md_to_html, md_inline, plan_path):
    parts = split(md)
    esc = html.escape
    card = lambda k, cls="": (f'<section class="sec {cls}"><h2>{TITLES[k]}</h2>{md_to_html(parts[k])}</section>'
                              if parts.get(k) else "")
    minute = "".join(f'<div class="m {k}"><b>{label}</b><p>{md_inline(first_lines(parts.get(k, "")), auto_code=True)}</p></div>'
                     for k, label in (("pain", "The pain"), ("cause", "Why it happens"), ("expect", "What you should expect")))
    if why_card:
        import why
        mine = "".join(f'<div class="row"><b>{esc(label)}</b><span>{esc(why_card.get(k) or "(left empty)")}</span></div>'
                       for k, label, _, _ in why.fields_for(why_card))
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
            .replace("__IF_GO__", "".join(f"<li>{x}</li>" for x in go))
            .replace("__PATH__", esc(plan_path)))


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
</style></head><body>
<div class="kicker">__QUEST__ · understand it, then approve</div>
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
