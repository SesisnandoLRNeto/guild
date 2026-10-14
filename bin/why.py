#!/usr/bin/env python3
"""The Why card: before a quest is built, the guildmaster writes why it exists.

  why.py open <slug>     put the card on the war table (guild quest does this for you)
  why.py show <slug>     print the answered card

Five short answers in the guildmaster's own words: the pain, the rule, the decision, the
impact, the future. The AI does not fill it in: thinking first is the point. When it is answered,
the card is kept in quests/<slug>/why.json, it shows at the top of the plan and the wrap-up, and
the adventurer is asked to check it against the ticket, the spec and the code and to challenge
what does not fit, on the war table.
"""
import html
import json
import os
import re
import sys
import time

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")

FIELDS = [
    ("pain", "Pain", "Who suffers today, and one real example of it.",
     "PMs fix pay rates by hand every Monday; last week one worker was paid twice."),
    ("rule", "Rule", "The business rule, in one sentence.",
     "A rate that starts in the past is allowed, with a warning."),
    ("decision", "Decision", "Who decided it, and what was rejected.",
     "Kim decided in the 13 Oct call; blocking past dates was rejected."),
    ("impact", "Impact", "What changes, and for which users, data or money.",
     "Only new rates; the money already paid does not change."),
    ("future", "Future", "What this unlocks next, and what it blocks.",
     "Unlocks the approval flow; blocks nothing."),
]
# A review or an investigation has no rule to build: the card asks what you need from it instead.
LOOK = [
    ("what", "What", "What is being looked at, in your words.",
     "Four stacked PRs from Virgilio that bring productivity data into pay."),
    ("why", "Why now", "Why it matters now, and who waits for it.",
     "Virgilio waits for my review before merging; it touches money."),
    ("worry", "Worry", "What would hurt most if it is missed.",
     "A worker paid twice, or a held row that is lost."),
    ("use", "Use", "What you will do with the answer.",
     "Post the real findings on the PRs myself."),
]
SKIP = ("", "na", "n/a", "-", "skip", "none")

# Brief headings the quartermaster writes, alone on a line or as "Heading: text".
HEADS = ("for the guildmaster", "quest type", "intent", "context", "acceptance", "constraints")

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Why card</title>
<meta name="guild-glance" content="off">
<style>
 .kicker { font-variant: small-caps; letter-spacing: .08em; color: var(--dim); font-size: 13px; }
 .short { font-size: 18px; line-height: 1.5; background: rgba(255,250,235,.7); border: 1px solid var(--line);
          border-left: 5px solid #8a4b12; border-radius: 4px; padding: 12px 18px; margin: 8px 0 18px; }
 .short p { margin: 4px 0; }
 .facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 0 0 18px; }
 .facts div { background: rgba(255,250,235,.55); border: 1px solid var(--line); border-top: 4px solid #9a8b72; border-radius: 4px; padding: 8px 14px; }
 .facts div.hurt { border-top-color: var(--bad); }
 .facts b { font-variant: small-caps; color: #4a2f1a; }
 .screens { display: flex; flex-wrap: wrap; gap: 10px; margin: 6px 0; }
 .screens figure { margin: 0; width: 150px; }
 .screens img { width: 100%; border: 1px solid var(--line); border-radius: 3px; display: block; }
 .screens figcaption { font-size: 12px; color: var(--dim); margin-top: 3px; text-align: center; }
 .facts p, .facts li { font-size: 14.5px; margin: 4px 0; }
 .facts ul { padding-left: 18px; margin: 4px 0; }
 .q { display: grid; grid-template-columns: 110px 1fr; gap: 4px 12px; padding: 8px 0; border-bottom: 1px dashed var(--line); font-size: 15px; }
 .q b { font-variant: small-caps; color: #8a4b12; font-size: 16px; }
 .q i { grid-column: 2; color: var(--dim); font-size: 14px; }
 details { margin-top: 22px; } summary { cursor: pointer; color: var(--dim); }
 details h3 { font-size: 15px; margin: 14px 0 4px; }
 details .sec { font-size: 14px; }
 @media (max-width: 700px) { .q { grid-template-columns: 1fr; } .q i { grid-column: 1; } }
</style></head><body>
<div class="kicker">__SLUG__ · __TYPE__</div>
<h1>Why does this quest exist?</h1>
<p class="lead">Read the short version, then answer the questions on the right in your own words. A guess is fine.
Write "skip" for a question that does not fit. The adventurer checks your answers against the code and the
tickets, and tells you where they do not match.</p>
<h2>The short version</h2>
<div class="short">__SHORT__</div>
__FACTS__
<h2>Your questions</h2>
__FIELDS__
<details><summary>The full brief the adventurer got (commands and rules for the agent)</summary>__BRIEF__</details>
</body></html>"""


def fields_for(card_or_type):
    kind = card_or_type.get("type", "code") if isinstance(card_or_type, dict) else card_or_type
    return LOOK if kind == "look" else FIELDS


def quest_type(brief):
    m = re.search(r"quest type\W*\s*(\w+)", brief, re.I)
    return "look" if m and m.group(1).lower() in ("investigation", "review", "research", "spike") else "code"


def sections(brief):
    """{heading: text} from the brief; text before the first known heading goes under ''."""
    out, key = {}, ""
    for line in brief.splitlines():
        bare = re.sub(r"^[#*\s]+|[*\s]+$", "", line)
        head, sep, rest = bare.partition(":")
        name = (head if sep else bare).strip().lower()
        if name in HEADS:
            key = name
            out.setdefault(key, [])
            if sep and rest.strip():
                out[key].append(rest.strip())
            continue
        out.setdefault(key, []).append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def first_para(text, limit=420):
    para = next((p for p in re.split(r"\n\s*\n|\n(?=\s*[-*] )", text) if p.strip()), "")
    para = re.sub(r"\s+", " ", para).strip()
    return para if len(para) <= limit else para[:limit].rsplit(" ", 1)[0] + "..."


# Sentences that are plumbing for the agent (how to call an API, where a file is, a token), not a
# fact for the guildmaster. These stay in the full brief only.
PLUMBING = re.compile(r"\bhttps?://|\bGET\b|\bheader\b|\btoken\b|json\.load|\bcall the REST API\b|"
                       r"already saved at|read it with|Never print|~/\.guild/", re.I)
FIGMA_FILE = re.compile(r"Figma file ([A-Za-z0-9_-]{10,})")
FIGMA_NODE = re.compile(r"\d{3,5}:\d{4,6}")
SCREEN_TYPES = {"FRAME", "COMPONENT", "COMPONENT_SET", "SECTION"}  # not INSTANCE: that is a badge or icon dropped on top


def clean_bullet(text):
    """A context bullet with agent plumbing sentences and node coordinates stripped, for the guildmaster."""
    kept = [s.strip() for s in re.split(r"(?<=[.:;])\s+", text) if s.strip() and not PLUMBING.search(s)]
    out = FIGMA_NODE.sub("", " ".join(kept))
    return re.sub(r"\s+([.,;)])", r"\1", re.sub(r"\s{2,}", " ", out)).strip(" ;,")


def figma_token():
    try:
        cfg = json.load(open(os.path.expanduser("~/.claude.json")))
        return cfg.get("mcpServers", {}).get("figma", {}).get("env", {}).get("FIGMA_API_KEY", "")
    except (OSError, ValueError, KeyError):
        return ""


def figma_screens(brief, limit=6):
    """Up to `limit` (node id, name) pairs for nodes the brief mentions that Figma itself says are a real
    screen (FRAME/COMPONENT/SECTION), not a status badge or icon dropped on top. The brief's own prose guesses
    at what an id points to and that guess can be wrong (a badge's id, not its frame's); Figma's node type is
    the one source that is never wrong. file key included.
    """
    m = FIGMA_FILE.search(brief)
    if not m:
        return "", []
    file_key = m.group(1)
    ids = list(dict.fromkeys(FIGMA_NODE.findall(brief)))   # de-duplicated, order kept
    if not ids:
        return file_key, []
    token = figma_token()
    if not token:
        return file_key, []
    import urllib.request
    import urllib.parse
    url = "https://api.figma.com/v1/files/" + file_key + "/nodes?" + urllib.parse.urlencode({"ids": ",".join(ids)})
    try:
        req = urllib.request.Request(url, headers={"X-Figma-Token": token})
        with urllib.request.urlopen(req, timeout=15) as r:
            nodes = json.load(r).get("nodes", {})
    except Exception:
        return file_key, []
    frames = []
    for nid in ids:                                        # keep the brief's own order
        doc = (nodes.get(nid) or {}).get("document") or {}
        if doc.get("type") in SCREEN_TYPES:
            frames.append((nid, doc.get("name", nid)))
        if len(frames) >= limit:
            break
    return file_key, frames


def fetch_figma_thumbs(file_key, frames, out_dir):
    """{node id: local png path}, best effort. Never raises: a network or token problem just means no images."""
    token = figma_token()
    if not token or not frames:
        return {}
    import urllib.request
    import urllib.parse
    ids = ",".join(nid for nid, _ in frames)
    url = "https://api.figma.com/v1/images/" + file_key + "?" + urllib.parse.urlencode({"ids": ids, "format": "png", "scale": "0.5"})
    try:
        req = urllib.request.Request(url, headers={"X-Figma-Token": token})
        with urllib.request.urlopen(req, timeout=15) as r:
            images = json.load(r).get("images", {})
    except Exception:
        return {}
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for nid, img_url in images.items():
        if not img_url:
            continue
        try:
            dest = os.path.join(out_dir, nid.replace(":", "-") + ".png")
            urllib.request.urlretrieve(img_url, dest)
            paths[nid] = dest
        except Exception:
            continue
    return paths


def hurt_points(brief):
    """The 'look hardest at' / risk lines of a brief, split into short items."""
    m = re.search(r"(?:look hardest at|where it hurts|risks?)\s*:\s*(.+?)(?:\.\s|\n|$)", brief, re.I)
    if not m:
        return []
    return [x.strip(" .") for x in re.split(r",\s*(?![^()]*\))", m.group(1)) if x.strip(" .")]


def path(slug):
    return os.path.join(QUESTS, slug, "why.json")


def load(slug):
    try:
        return json.load(open(path(slug)))
    except (OSError, ValueError):
        return None


def open_card(slug):
    qdir = os.path.join(QUESTS, slug)
    if not os.path.isdir(qdir):
        raise SystemExit(f"why: no quest {slug}")
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import wartable
    brief = open(os.path.join(qdir, "brief.md")).read() if os.path.exists(os.path.join(qdir, "brief.md")) else ""
    board = "why-" + time.strftime("%H%M%S")
    d = wartable.board_dir(slug, board)
    os.makedirs(d, exist_ok=True)
    kind = quest_type(brief)
    parts = sections(brief)
    esc, md, inline = html.escape, wartable.md_to_html, wartable.md_inline
    mine = parts.get("for the guildmaster") or parts.get("intent") or first_para(parts.get("", ""))
    short = md(mine) if mine else "<p>The quartermaster wrote no intent for this quest. Ask it before you answer.</p>"
    meta = json.load(open(os.path.join(qdir, "meta.json"))) if os.path.exists(os.path.join(qdir, "meta.json")) else {}
    facts = [("Where", f"<p><code>{esc(os.path.basename(meta.get('repo', '')) or '?')}</code>"
                       + (f", ticket <code>{esc(meta['ticket'])}</code>" if meta.get("ticket") else "") + "</p>"
                       + f"<p>{'Read only: nothing is changed or pushed.' if kind == 'look' else 'Code changes in its own branch.'}</p>")]
    if parts.get("context"):
        file_key, frames = figma_screens(parts["context"])
        thumbs = fetch_figma_thumbs(file_key, frames, os.path.join(d, "figma")) if frames else {}
        raw = [re.sub(r"^\s*[-*]\s+", "", l) for l in parts["context"].splitlines() if re.match(r"^\s*[-*]\s+", l)]
        bullets = [clean_bullet(b) for b in raw]
        bullets = [b for b in bullets if b]                # plumbing-only lines clean away to nothing
        body = ""
        if thumbs:
            body += '<div class="screens">' + "".join(
                f'<figure><img src="figma/{os.path.basename(p)}" alt="{esc(label)}"><figcaption>{esc(label)}</figcaption></figure>'
                for nid, label in frames if (p := thumbs.get(nid))) + "</div>"
        if bullets:
            body += "<ul>" + "".join(f"<li>{inline(b, auto_code=True)}</li>" for b in bullets[:6]) + "</ul>"
        if not body:
            body = f"<p>{inline(first_para(parts['context'], 300), auto_code=True)}</p>"
        facts.append(("What it touches", body))
    hurt = hurt_points(brief)
    if hurt:
        facts.append(("Where it can hurt", "<ul>" + "".join(f"<li>{inline(h, auto_code=True)}</li>" for h in hurt[:7]) + "</ul>"))
    facts_html = '<div class="facts">' + "".join(
        f'<div class="{"hurt" if t == "Where it can hurt" else ""}"><b>{t}</b>{body}</div>' for t, body in facts) + "</div>"
    asks = fields_for(kind)
    fields = "".join(f'<div class="q"><b>{esc(label)}</b><span>{esc(hint)}</span><i>For example: {esc(ex)}</i></div>'
                     for _, label, hint, ex in asks)
    full = "".join(f"<h3>{esc(k.capitalize() or 'Opening')}</h3><div class=\"sec\">{md(v)}</div>" for k, v in parts.items() if v)
    with open(os.path.join(d, "content.html"), "w") as f:
        f.write(PAGE.replace("__SLUG__", esc(slug))
                .replace("__TYPE__", "a review: write what you need from it" if kind == "look" else "write why it exists, before it is built")
                .replace("__SHORT__", short).replace("__FACTS__", facts_html).replace("__FIELDS__", fields)
                .replace("__BRIEF__", full or "<p>No brief.</p>"))
    json.dump({"questions": [{"id": k, "title": label, "detail": f"{hint} For example: {ex}", "type": "text"} for k, label, hint, ex in asks],
               "why_type": kind},
              open(os.path.join(d, "decisions.json"), "w"), indent=2)
    json.dump({"id": board, "quest": slug, "title": f"Why card: {slug}", "subtitle": "your words first; the adventurer checks them",
               "kind": "why", "wrapup": False, "created": wartable.now()},
              open(os.path.join(d, "board.json"), "w"), indent=2)
    url = f"http://127.0.0.1:{wartable.ensure_server()}/b/{slug}/{board}/"
    with open(os.path.join(GUILD_HOME, "events.log"), "a") as f:
        f.write(f"{wartable.now()}\t{slug}\twhy-asked\tWhy card on the docket -> {url}\n")
    return url


def save(slug, decision):
    """The answered card, from the board's decision."""
    ans = decision.get("answers", {})
    kind = "look" if any(k in ans for k, _, _, _ in LOOK) else "code"
    card = {k: str(ans.get(k, "")).strip() for k, _, _, _ in fields_for(kind)}
    card["type"] = kind
    card["at"] = decision.get("at", "")
    if decision.get("message"):
        card["note"] = decision["message"]
    json.dump(card, open(path(slug), "w"), indent=2)
    return card


def skipped(card):
    """True when every answer is empty or a 'skip'/'na'."""
    return all(str(card.get(k, "")).strip().lower() in SKIP for k, _, _, _ in fields_for(card))


def as_text(card):
    return "\n".join(f"{label}: {card.get(k) or '(left empty)'}" for k, label, _, _ in fields_for(card))


def glance_html(slug):
    """The card as a small block for the top of the plan and wrap-up pages."""
    card = load(slug)
    if not card or skipped(card):
        return ""
    rows = "".join(f'<div class="gw-row"><b>{html.escape(label)}</b><span>{html.escape(card.get(k) or "(left empty)")}</span></div>'
                   for k, label, _, _ in fields_for(card))
    return ('<div class="gw"><div class="gw-head">Why card <i>written by the guildmaster</i></div>' + rows + "</div>")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) != 2 or a[0] not in ("open", "show"):
        raise SystemExit(__doc__)
    if a[0] == "open":
        print(open_card(a[1]))
    else:
        card = load(a[1])
        print(as_text(card) if card else f"{a[1]} has no answered Why card yet")
