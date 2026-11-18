#!/usr/bin/env python3
"""The Library: a map of your second brain, and the Keeper who answers from it.

  library.py page [<notes_dir> <graph.json> <out.html>]   build the graph page (no args: the configured home)
  library.py ensure                                      build the page when it is missing or older than the graph
  library.py ask "<question>" [--graph P] [--notes D] [--hops 2]
  library.py status
  library.py refresh                                     export (Notion only), graphify, page

The notes are a folder of markdown files (frontmatter: title, type, notion_url or url, last_edited).
The graph is graphify's graph.json built from that folder. Both live in the library home
(~/.guild/local/library.json, default $GUILD_HOME/library), never in this repo.
ask uses no model: it matches the question's words to concept labels and note titles, then walks the links.
"""
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
CLAUDE = os.environ.get("GUILD_LIBRARY_CLAUDE", "claude")
MODEL = os.environ.get("GUILD_LIBRARY_MODEL", "sonnet")

REL = {"references": "mentions", "conceptually_related_to": "is related to",
       "semantically_similar_to": "is similar to", "shares_data_with": "shares data with",
       "implements": "implements", "rationale_for": "is the reason for", "calls": "calls"}
STOP = set("""a an and are as at be been but by can could did do does for from had has have how i if in into is it
its me my of on or our should so than that the their them then there these they this to us was we were what when where
which who whom why will with would you your about any all also just more most much not now only some such too very
tell show give find know need want past last did done does get got thing things any anything something""".split())


def paths():
    """Where the library lives. ~/.guild/local/library.json may set home, notes and source."""
    cfg = {}
    try:
        cfg = json.load(open(os.path.join(GUILD_HOME, "local", "library.json")))
    except (OSError, ValueError):
        pass
    home = os.path.expanduser(cfg.get("home") or os.path.join(GUILD_HOME, "library"))
    notes = os.path.join(home, os.path.expanduser(cfg.get("notes") or "notes"))
    return {"home": home, "notes": notes, "source": cfg.get("source") or "folder",
            "graph": os.path.join(home, "graphify-out", "graph.json"), "page": os.path.join(home, "library.html")}


# ── reading the notes and the graph ───────────────────────────────────────────

def read_note(p):
    t = p.read_text(encoding="utf-8")
    meta, body = {}, t
    m = re.match(r"^---\n(.*?)\n---\n?", t, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
        body = t[m.end():]
    body = re.sub(r"^# .*\n+", "", body, count=1).replace("\\_", "_").replace("\\~", "~")
    return meta, body


def snippets(label, body, n=2):
    words = [w for w in re.split(r"[\s/(),:]+", label) if len(w) > 3]
    out = []
    for line in body.splitlines():
        s = line.strip(" -*#|")
        if not s:
            continue
        if label.lower() in s.lower() or (words and sum(w.lower() in s.lower() for w in words) >= max(1, len(words) // 2 + 1)):
            out.append(s[:320])
        if len(out) >= n:
            break
    return out


def load(notes_dir, graph_path):
    """Notes, concepts and both kinds of links, the way the page shows them."""
    notes_dir, g = Path(notes_dir), json.loads(Path(graph_path).read_text(encoding="utf-8"))
    notes = {}
    for p in sorted(notes_dir.glob("*.md")):
        meta, body = read_note(p)
        notes[p.stem] = {"id": p.stem, "title": meta.get("title", p.stem), "type": meta.get("type", "Note"),
                         "url": meta.get("notion_url") or meta.get("url", ""), "edited": meta.get("last_edited", "")[:10],
                         "body": body, "path": str(p)}

    concepts = {}
    for n in g.get("nodes", []):
        f = Path(n.get("source_file") or "").stem
        concepts[n["id"]] = {"id": n["id"], "label": n.get("label", n["id"]), "cluster": n.get("community_name") or "",
                             "note": f if f in notes else "", "says": snippets(n.get("label", ""), notes.get(f, {}).get("body", ""))}
    groups = defaultdict(list)
    for h in g.get("hyperedges", []):
        for nid in h.get("nodes", []):
            groups[nid].append(h.get("label", ""))
    for nid, c in concepts.items():
        c["groups"] = groups.get(nid, [])

    cedges = []
    for e in g.get("links", []):
        if e["source"] in concepts and e["target"] in concepts:
            rel = e.get("relation", "related")
            cedges.append({"s": e["source"], "t": e["target"], "rel": REL.get(rel, rel.replace("_", " ")),
                           "conf": e.get("confidence", "EXTRACTED")})

    # Notes view: roll concept links up to the notes they came from
    nlinks = {}

    def add(a, b, why, conf):
        if not a or not b or a == b:
            return
        k = tuple(sorted((a, b)))
        L = nlinks.setdefault(k, {"s": k[0], "t": k[1], "why": [], "conf": "INFERRED"})
        if why not in L["why"]:
            L["why"].append(why)
        if conf == "EXTRACTED":
            L["conf"] = "EXTRACTED"
    for e in cedges:
        a, b = concepts[e["s"]], concepts[e["t"]]
        add(a["note"], b["note"], f'{a["label"]} {e["rel"]} {b["label"]}', e["conf"])
    for nid, nt in notes.items():                      # [[wiki links]] written in the notes
        for slug in re.findall(r"\[\[([^\]|]+)", nt["body"]):
            if slug in notes:
                add(nid, slug, f'{nt["title"]} links to {notes[slug]["title"]}', "EXTRACTED")
    by_label = defaultdict(set)                       # the same thing named in two notes
    for c in concepts.values():
        if c["note"]:
            by_label[re.sub(r"\W+", " ", c["label"].lower()).strip()].add(c["note"])
    for lab, ns in by_label.items():
        ns = sorted(ns)
        for i in range(len(ns)):
            for j in range(i + 1, len(ns)):
                add(ns[i], ns[j], f"both mention {lab}", "EXTRACTED")
    for nt in notes.values():
        nt["concepts"] = [c["id"] for c in concepts.values() if c["note"] == nt["id"]]
    return {"notes": notes, "concepts": concepts, "cedges": cedges, "nedges": list(nlinks.values())}


# ── the page ──────────────────────────────────────────────────────────────────

def page(notes_dir, graph_path, out):
    d = load(notes_dir, graph_path)
    data = {"notes": [{k: v for k, v in n.items() if k != "path"} for n in d["notes"].values()],
            "concepts": list(d["concepts"].values()), "cedges": d["cedges"], "nedges": d["nedges"]}
    html = TEMPLATE.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    Path(out).write_text(html, encoding="utf-8")
    print(f"{out}: {len(d['notes'])} notes, {len(d['nedges'])} note links, {len(d['concepts'])} concepts, {len(d['cedges'])} concept links")


def ensure():
    p = paths()
    if not os.path.isfile(p["graph"]):
        raise SystemExit(f"library: no graph at {p['graph']}. Run: guild library refresh")
    if not os.path.isfile(p["page"]) or os.path.getmtime(p["page"]) < os.path.getmtime(p["graph"]):
        page(p["notes"], p["graph"], p["page"])


# ── the Keeper: answer a question from the graph, no model ────────────────────

def words(text):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9_-]*", text.lower()) if len(w) > 1 and w not in STOP]


def score(qwords, text):
    tw = set(words(text))
    s = 0.0
    for w in qwords:
        if w in tw:
            s += 1
        elif len(w) > 3 and any(t.startswith(w) or w.startswith(t) for t in tw if len(t) > 3):
            s += 0.5                                   # "deploys" finds "deploy"
    return s / (1 + 0.1 * len(tw))                     # a short label that matches beats a long one


def ask(question, graph=None, notes=None, hops=2, cap=25):
    p = paths()
    graph, notes = graph or p["graph"], notes or p["notes"]
    if not os.path.isfile(graph):
        print(f"library: no graph at {graph}. Run: guild library refresh", file=sys.stderr)
        return 1
    d = load(notes, graph)
    q = words(question)
    if not q:
        print("library: the question has no words to look for", file=sys.stderr)
        return 1
    hits = []
    for c in d["concepts"].values():
        s = score(q, c["label"])
        if s > 0:
            hits.append((s, "concept", c["id"]))
    for n in d["notes"].values():
        s = score(q, n["title"] + " " + n["id"].replace("-", " "))
        if s > 0:
            hits.append((s * 1.2, "note", n["id"]))
    hits.sort(key=lambda h: -h[0])
    if not hits:
        print(f"The Keeper found nothing for: {' '.join(q)}")
        print("No note title or concept matches these words. Try other words, or run: guild library status")
        return 1
    best = hits[0][0]
    seeds = [h for h in hits if h[0] >= best * 0.5][:5]

    start = {}
    for _, kind, i in seeds:
        for cid in ([i] if kind == "concept" else d["notes"][i]["concepts"][:6]):
            start[cid] = 0
    adj = defaultdict(list)
    for e in d["cedges"]:
        adj[e["s"]].append(e)
        adj[e["t"]].append(e)
    depth, frontier, seen_e = dict(start), list(start), {}
    for h in range(1, hops + 1):
        nxt = []
        for cid in frontier:
            for e in adj[cid]:
                key = (e["s"], e["t"], e["rel"])
                if key not in seen_e:
                    seen_e[key] = (e, h)
                o = e["t"] if e["s"] == cid else e["s"]
                if o not in depth:
                    depth[o] = h
                    nxt.append(o)
        frontier = nxt

    C, N = d["concepts"], d["notes"]
    edges = sorted(seen_e.values(), key=lambda x: (x[0]["conf"] != "EXTRACTED", x[1], -(x[0]["s"] in start) - (x[0]["t"] in start)))
    reads = defaultdict(float)
    for _, kind, i in seeds:
        reads[i if kind == "note" else C[i]["note"]] += 3
    for e, h in edges:
        w = (2 if e["conf"] == "EXTRACTED" else 1) / h
        for cid in (e["s"], e["t"]):
            reads[C[cid]["note"]] += w
    reads.pop("", None)

    out = ["Matched:"]
    for _, kind, i in seeds:
        if kind == "note":
            out.append(f"  note     {N[i]['title']}")
        else:
            c = C[i]
            out.append(f"  concept  {c['label']}" + (f"  (in {N[c['note']]['title']})" if c["note"] else ""))
    shown = edges[:max(3, cap - len(out) - 8)]
    if shown:
        out.append("Connections:")
        for e, _ in shown:
            src = C[e["s"]]["note"] or C[e["t"]]["note"]
            tag = "in the text" if e["conf"] == "EXTRACTED" else "guessed"
            out.append(f"  {C[e['s']]['label']} {e['rel']} {C[e['t']]['label']} ({tag})" + (f" - {N[src]['title']}" if src else ""))
    guessed = sum(1 for e, _ in edges if e["conf"] != "EXTRACTED")
    if len(edges) > len(shown):
        out.append(f"  and {len(edges) - len(shown)} more ({guessed} of all {len(edges)} links are guessed)")
    out.append("Read next:")
    for nid, _ in sorted(reads.items(), key=lambda x: -x[1])[:max(1, cap - len(out))][:5]:
        out.append(f"  {N[nid]['path']}  {N[nid]['title']}")
    print("\n".join(out[:cap]))
    return 0


# ── status ────────────────────────────────────────────────────────────────────

def when(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def status():
    p = paths()
    files = sorted(Path(p["notes"]).glob("*.md")) if os.path.isdir(p["notes"]) else []
    print(f"home     {p['home']} (source: {p['source']})")
    print(f"notes    {len(files)} in {p['notes']}")
    if not os.path.isfile(p["graph"]):
        print("graph    none yet. Run: guild library refresh")
        return 0
    g = json.load(open(p["graph"]))
    built = os.path.getmtime(p["graph"])
    print(f"graph    {len(g.get('nodes', []))} nodes, {len(g.get('links', []))} links, last refresh {when(built)}")
    changed = [f.name for f in files if f.stat().st_mtime > built]
    print(f"changed  {len(changed)} notes since the graph was built" + (f": {', '.join(changed[:8])}" + (" ..." if len(changed) > 8 else "") if changed else ""))
    d = load(p["notes"], p["graph"])
    linked = {e["s"] for e in d["nedges"]} | {e["t"] for e in d["nedges"]}
    islands = [n for n in d["notes"] if n not in linked]
    print(f"islands  {len(islands)} notes with no links" + (f": {', '.join(islands[:8])}" + (" ..." if len(islands) > 8 else "") if islands else ""))
    print(f"page     {p['page']} ({'built ' + when(os.path.getmtime(p['page'])) if os.path.isfile(p['page']) else 'not built yet'})")
    return 0


# ── refresh: export (Notion), graphify, page. Manual only, never on a timer ──

NOTION_READ = ["notion-search", "notion-fetch", "notion-memory-search", "notion-get-users"]


def claude(prompt, cwd, tools):
    env = dict(os.environ)
    env.pop("GUILD_QUEST", None)                       # not a quest's agent: no quest hooks, no quest identity
    cmd = [CLAUDE, "-p", prompt, "--model", MODEL, "--output-format", "text", "--allowedTools", *tools]
    return subprocess.run(cmd, cwd=cwd, env=env, timeout=int(os.environ.get("GUILD_LIBRARY_TIMEOUT", "3600"))).returncode


def refresh():
    p = paths()
    os.makedirs(p["notes"], exist_ok=True)
    if p["source"] == "notion":
        print(f"1/3 export: a headless Claude run reads Notion Memory (read only) into {p['notes']}")
        prompt = open(os.path.join(REPO, "prompts", "library-export.md")).read().replace("{{NOTES}}", p["notes"])
        tools = [f"mcp__{s}__{t}" for s in ("notion", "claude_ai_Notion") for t in NOTION_READ] + ["Read", "Write", "Edit", "Glob"]
        if claude(prompt, p["notes"], tools) != 0:
            raise SystemExit("library: the Notion export failed; the notes and the graph are as they were")
    else:
        print(f"1/3 export: source is a folder, nothing to export ({p['notes']})")
    if not list(Path(p["notes"]).glob("*.md")):
        raise SystemExit(f"library: no markdown notes in {p['notes']}")
    update = " --update" if os.path.isfile(p["graph"]) else ""
    print(f"2/3 graph: headless Claude runs /graphify{update} in {p['home']} (a few minutes)")
    if claude(f"/graphify {p['notes']}{update} --no-viz", p["home"],
              ["Skill", "Bash", "Read", "Write", "Edit", "Glob", "Grep", "Agent"]) != 0 or not os.path.isfile(p["graph"]):
        raise SystemExit(f"library: graphify did not write {p['graph']}")
    print("3/3 page")
    page(p["notes"], p["graph"], p["page"])
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "page":
        if len(rest) == 3:
            page(*rest)
        elif not rest:
            p = paths()
            if not os.path.isfile(p["graph"]):
                raise SystemExit(f"library: no graph at {p['graph']}. Run: guild library refresh")
            page(p["notes"], p["graph"], p["page"])
        else:
            raise SystemExit("usage: library.py page [<notes_dir> <graph.json> <out.html>]")
        return 0
    if cmd == "ensure":
        ensure()
        return 0
    if cmd == "ask":
        opts, q = {"--graph": None, "--notes": None, "--hops": "2"}, []
        i = 0
        while i < len(rest):
            if rest[i] in opts and i + 1 < len(rest):
                opts[rest[i]] = rest[i + 1]
                i += 2
            else:
                q.append(rest[i])
                i += 1
        if not q:
            raise SystemExit('usage: guild keeper "<question>" [--hops 2]')
        return ask(" ".join(q), opts["--graph"], opts["--notes"], int(opts["--hops"]))
    if cmd == "status":
        return status()
    if cmd == "refresh":
        return refresh()
    raise SystemExit(f"library: unknown command {cmd}")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>The Library</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<style>
:root{--bg:#1e1e1e;--panel:#262626;--line:#3a3a3a;--text:#dadada;--dim:#8a8a8a;--accent:#a78bfa;--ok:#4ade80;--guess:#fbbf24}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow:hidden}
#bar{position:fixed;top:12px;left:12px;display:flex;gap:8px;z-index:3;flex-wrap:wrap;max-width:calc(100% - 24px)}
#bar input,#bar button{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 10px;font:inherit}
#bar input{width:220px}#bar button{cursor:pointer}#bar button.on{border-color:var(--accent);color:var(--accent)}
#legend{position:fixed;left:12px;bottom:12px;background:rgba(38,38,38,.9);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:12px;z-index:3;max-height:40vh;overflow:auto}
#legend div{display:flex;align-items:center;gap:6px;cursor:pointer}#legend i{width:10px;height:10px;border-radius:50%;display:inline-block}
#legend .dash{width:18px;height:0;border-top:2px dashed var(--guess);border-radius:0}#legend .solid{width:18px;height:0;border-top:2px solid #777;border-radius:0}
svg{width:100%;height:100%;display:block;cursor:grab}
.link{stroke:#555;stroke-opacity:.55}.link.guess{stroke:var(--guess);stroke-dasharray:4 3;stroke-opacity:.5}
.node circle{stroke:var(--bg);stroke-width:1.5;cursor:pointer}.node text{fill:var(--text);font-size:11px;pointer-events:none;paint-order:stroke;stroke:var(--bg);stroke-width:3px}
.faded{opacity:.08}.sel circle{stroke:#fff;stroke-width:2.5}
#panel{position:fixed;top:0;right:0;width:min(440px,100%);height:100%;background:var(--panel);border-left:1px solid var(--line);transform:translateX(100%);transition:transform .2s;z-index:4;display:flex;flex-direction:column}
#panel.open{transform:none}#ph{padding:14px 16px 8px;border-bottom:1px solid var(--line)}#pb{padding:12px 16px 40px;overflow:auto;flex:1}
#ph h2{margin:4px 0 6px;font-size:18px}.row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--dim)}
.chip{border:1px solid var(--line);border-radius:999px;padding:1px 8px;font-size:12px;color:var(--text)}
.tools{display:flex;gap:6px;margin-bottom:6px}.tools button{background:none;border:1px solid var(--line);color:var(--text);border-radius:6px;padding:3px 8px;cursor:pointer;font:inherit;font-size:12px}
h3{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);margin:18px 0 8px}
.conn{border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:6px}
.conn a,.go{color:var(--accent);cursor:pointer;text-decoration:none;font-weight:600}.why{font-size:12.5px;color:var(--dim);margin-top:3px}
.tag{font-size:10.5px;border-radius:4px;padding:0 5px;margin-left:6px;font-weight:600}.tag.EXTRACTED{color:var(--ok);border:1px solid var(--ok)}.tag.INFERRED,.tag.AMBIGUOUS{color:var(--guess);border:1px solid var(--guess)}
.says{border-left:3px solid var(--accent);padding:4px 10px;margin:6px 0;color:var(--text);font-size:13px}
.md{font-size:13.5px}.md a{color:var(--accent)}.md table{border-collapse:collapse;font-size:12px}.md td,.md th{border:1px solid var(--line);padding:3px 6px}.md code{background:#333;padding:0 4px;border-radius:3px}
.cchips{display:flex;flex-wrap:wrap;gap:5px}.cchips span{cursor:pointer}
#hint{position:fixed;bottom:12px;right:12px;color:var(--dim);font-size:12px;z-index:2}
</style></head><body>
<div id="bar"><input id="q" placeholder="Search notes or concepts" autocomplete="off">
<button id="vNotes" class="on">Notes</button><button id="vConcepts">Concepts</button><button id="guess" class="on">Show guessed links</button><button id="reset">Show all</button></div>
<svg id="g"></svg><div id="legend"></div>
<div id="panel"><div id="ph"></div><div id="pb"></div></div>
<div id="hint">Click a node to read it. Hover to see its neighbours. Scroll to zoom.</div>
<script>
const D=/*DATA*/null;
const notes=new Map(D.notes.map(n=>[n.id,n])), concepts=new Map(D.concepts.map(c=>[c.id,c]));
const types=[...new Set(D.notes.map(n=>n.type))].sort();
const TYPE_COL=Object.fromEntries(types.map((t,i)=>[t,d3.hsl(210+i*360/Math.max(types.length,1),.7,.66).formatHex()]));
const clusters=[...new Set(D.concepts.map(c=>c.cluster))].sort();
const CL_COL=new Map(clusters.map((c,i)=>[c,d3.hsl(i*360/clusters.length,.62,.62).formatHex()]));
let view="notes", showGuess=true, focus=null, selected=null, history=[];
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const svg=d3.select("#g"), root=svg.append("g"); let zoomK=1;
const zoom=d3.zoom().scaleExtent([.15,6]).on("zoom",e=>{root.attr("transform",e.transform);zoomK=e.transform.k;labels()});
svg.call(zoom).on("click",e=>{if(e.target.tagName==="svg")closePanel()});
let sim, nodeSel, linkSel, adj;

function graphData(){
  let nodes, links;
  if(view==="notes"){nodes=D.notes.map(n=>({id:n.id,label:n.title,color:TYPE_COL[n.type]||"#999"}));
    links=D.nedges.map(e=>({source:e.s,target:e.t,conf:e.conf,n:e.why.length}));}
  else{nodes=D.concepts.map(c=>({id:c.id,label:c.label,color:CL_COL.get(c.cluster)}));
    links=D.cedges.map(e=>({source:e.s,target:e.t,conf:e.conf,n:1}));}
  if(!showGuess)links=links.filter(l=>l.conf==="EXTRACTED");
  if(focus){const keep=new Set([focus]);for(let d=0;d<2;d++)for(const l of links){if(keep.has(l.source)||keep.has(l.target)){keep.add(l.source);keep.add(l.target)}}
    nodes=nodes.filter(n=>keep.has(n.id));links=links.filter(l=>keep.has(l.source)&&keep.has(l.target));}
  const deg=new Map();links.forEach(l=>{deg.set(l.source,(deg.get(l.source)||0)+1);deg.set(l.target,(deg.get(l.target)||0)+1)});
  nodes.forEach(n=>n.deg=deg.get(n.id)||0);
  adj=new Map(nodes.map(n=>[n.id,new Set([n.id])]));links.forEach(l=>{adj.get(l.source)?.add(l.target);adj.get(l.target)?.add(l.source)});
  return {nodes,links};
}
function draw(){
  const {nodes,links}=graphData(); root.selectAll("*").remove(); if(sim)sim.stop();
  const W=innerWidth,H=innerHeight, big=view==="concepts";
  linkSel=root.append("g").selectAll("line").data(links).join("line").attr("class",d=>"link"+(d.conf==="EXTRACTED"?"":" guess")).attr("stroke-width",d=>Math.min(1+Math.log2(d.n),4));
  nodeSel=root.append("g").selectAll("g").data(nodes).join("g").attr("class","node")
    .on("click",(e,d)=>{e.stopPropagation();open(d.id)}).on("mouseenter",(e,d)=>hl(d.id)).on("mouseleave",()=>hl(null))
    .call(d3.drag().on("start",(e,d)=>{if(!e.active)sim.alphaTarget(.2).restart();d.fx=d.x;d.fy=d.y}).on("drag",(e,d)=>{d.fx=e.x;d.fy=e.y}).on("end",(e,d)=>{if(!e.active)sim.alphaTarget(0);d.fx=null;d.fy=null}));
  nodeSel.append("circle").attr("r",d=>(big?3:5)+Math.sqrt(d.deg)*(big?1.4:2.2)).attr("fill",d=>d.color);
  nodeSel.append("text").attr("dy",d=>-((big?3:5)+Math.sqrt(d.deg)*(big?1.4:2.2))-4).attr("text-anchor","middle").text(d=>d.label.length>42?d.label.slice(0,40)+"...":d.label);
  sim=d3.forceSimulation(nodes).force("link",d3.forceLink(links).id(d=>d.id).distance(big?38:95).strength(.5))
    .force("charge",d3.forceManyBody().strength(big?-45:-320)).force("center",d3.forceCenter(W/2,H/2))
    .force("x",d3.forceX(W/2).strength(.04)).force("y",d3.forceY(H/2).strength(.04)).force("collide",d3.forceCollide(d=>(big?5:9)+Math.sqrt(d.deg)*2))
    .on("tick",()=>{linkSel.attr("x1",d=>d.source.x).attr("y1",d=>d.source.y).attr("x2",d=>d.target.x).attr("y2",d=>d.target.y);nodeSel.attr("transform",d=>`translate(${d.x},${d.y})`)});
  sim.on("end.fit",fit); setTimeout(fit,1200);
  legend(); labels(); mark();
}
function fit(){if(!nodeSel)return;const ns=nodeSel.data();if(!ns.length)return;
  const xs=ns.map(d=>d.x),ys=ns.map(d=>d.y),x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
  const panelW=document.getElementById("panel").classList.contains("open")?document.getElementById("panel").offsetWidth:0;
  const W=innerWidth-panelW,H=innerHeight,k=Math.min(2.5,.88*Math.min(W/(x1-x0+80),H/(y1-y0+80)));
  svg.transition().duration(500).call(zoom.transform,d3.zoomIdentity.translate(W/2-k*(x0+x1)/2,H/2-k*(y0+y1)/2).scale(k));}
addEventListener("resize",()=>{if(!sim)return;sim.force("center",d3.forceCenter(innerWidth/2,innerHeight/2)).force("x",d3.forceX(innerWidth/2).strength(.04)).force("y",d3.forceY(innerHeight/2).strength(.04)).alpha(.3).restart()});
function labels(){if(!nodeSel)return;const q=document.getElementById("q").value.trim().toLowerCase();
  nodeSel.select("text").attr("opacity",d=>(q&&d.label.toLowerCase().includes(q))||d.id===selected||zoomK>(view==="notes"?1.5:2.2)||d.deg>=(view==="notes"?9:12)?1:0)}
function hl(id){if(!nodeSel)return;if(!id){nodeSel.classed("faded",false);linkSel.classed("faded",false);search();return}
  const nb=adj.get(id);nodeSel.classed("faded",d=>!nb.has(d.id));linkSel.classed("faded",d=>d.source.id!==id&&d.target.id!==id);
  nodeSel.select("text").attr("opacity",d=>nb.has(d.id)?1:0)}
function search(){const q=document.getElementById("q").value.trim().toLowerCase();if(!nodeSel)return;
  nodeSel.classed("faded",d=>q&&!d.label.toLowerCase().includes(q));linkSel.classed("faded",!!q);labels()}
function mark(){if(nodeSel)nodeSel.classed("sel",d=>d.id===selected)}
function legend(){const L=document.getElementById("legend");
  const items=view==="notes"?Object.entries(TYPE_COL).map(([k,c])=>`<div><i style="background:${c}"></i>${k}</div>`):clusters.map(c=>`<div data-c="${esc(c)}"><i style="background:${CL_COL.get(c)}"></i>${esc(c)}</div>`);
  L.innerHTML=items.join("")+`<div style="margin-top:6px"><i class="solid"></i>found in the text</div><div><i class="dash"></i>guessed by the model</div>`;
  L.querySelectorAll("[data-c]").forEach(el=>el.onclick=()=>{const c=el.dataset.c;nodeSel.classed("faded",d=>concepts.get(d.id).cluster!==c);linkSel.classed("faded",true)});}
function setView(v,keepFocus){view=v;if(!keepFocus)focus=null;document.getElementById("vNotes").classList.toggle("on",v==="notes");document.getElementById("vConcepts").classList.toggle("on",v==="concepts");draw()}
function md(body){let h=marked.parse(body.replace(/\[\[([^\]|]+)\]\]/g,(m,s)=>notes.has(s)?`<a class="go" data-note="${s}">${esc(notes.get(s).title)}</a>`:m));return h}
const tag=c=>`<span class="tag ${c}">${c==="EXTRACTED"?"in the text":"guessed"}</span>`;
function open(id,noHist){
  if(selected&&!noHist&&selected!==id)history.push([view,selected]);
  if(notes.has(id)&&view!=="notes")setView("notes",false); if(concepts.has(id)&&view!=="concepts")setView("concepts",false);
  selected=id;mark();labels();
  const P=document.getElementById("panel"),H=document.getElementById("ph"),B=document.getElementById("pb");
  const tools=`<div class="tools">${history.length?'<button id="back">Back</button>':""}<button id="foc">Focus here</button><button id="cls">Close</button></div>`;
  if(notes.has(id)){const n=notes.get(id);
    const links=D.nedges.filter(e=>e.s===id||e.t===id).filter(e=>showGuess||e.conf==="EXTRACTED").sort((a,b)=>b.why.length-a.why.length);
    H.innerHTML=tools+`<h2>${esc(n.title)}</h2><div class="row"><span class="chip" style="border-color:${TYPE_COL[n.type]}">${esc(n.type)}</span>edited ${esc(n.edited)}${n.url?` <a class="go" href="${esc(n.url)}" target="_blank" rel="noopener">${/notion\.(so|site|com)/.test(n.url)?"Open in Notion":"Open the source"}</a>`:""}</div>`;
    B.innerHTML=`<h3>Connected to ${links.length} notes</h3>`+(links.map(e=>{const o=e.s===id?e.t:e.s;return `<div class="conn"><a data-note="${o}">${esc(notes.get(o).title)}</a>${tag(e.conf)}<div class="why">${e.why.slice(0,4).map(esc).join("<br>")}${e.why.length>4?`<br>and ${e.why.length-4} more`:""}</div></div>`}).join("")||'<div class="why">No links yet. This note is an island.</div>')
      +`<h3>Concepts in this note (${n.concepts.length})</h3><div class="cchips">${n.concepts.map(c=>`<span class="chip" data-concept="${c}">${esc(concepts.get(c).label)}</span>`).join("")}</div>`
      +`<h3>What it says</h3><div class="md">${md(n.body)}</div>`;
  }else{const c=concepts.get(id);
    const links=D.cedges.filter(e=>e.s===id||e.t===id).filter(e=>showGuess||e.conf==="EXTRACTED");
    H.innerHTML=tools+`<h2>${esc(c.label)}</h2><div class="row"><span class="chip" style="border-color:${CL_COL.get(c.cluster)}">${esc(c.cluster)}</span>${c.note?`from <a class="go" data-note="${c.note}">${esc(notes.get(c.note).title)}</a>`:""}</div>`;
    B.innerHTML=`<h3>What the note says about it</h3>`+(c.says.length?c.says.map(s=>`<div class="says">${esc(s)}</div>`).join(""):`<div class="why">Named in the note without a sentence of its own. Open the note to read the context.</div>`)
      +`<h3>Connections (${links.length})</h3>`+links.map(e=>{const out=e.s===id,o=concepts.get(out?e.t:e.s);
        return `<div class="conn">${out?`This ${esc(e.rel)} <a data-concept="${o.id}">${esc(o.label)}</a>`:`<a data-concept="${o.id}">${esc(o.label)}</a> ${esc(e.rel)} this`}${tag(e.conf)}<div class="why">in ${esc(notes.get(o.note)?.title||o.note)}</div></div>`}).join("")
      +(c.groups.length?`<h3>Part of a group</h3>`+c.groups.map(g=>`<div class="conn">${esc(g)}</div>`).join(""):"");
  }
  P.classList.add("open");
  P.querySelectorAll("[data-note]").forEach(a=>a.onclick=()=>open(a.dataset.note));
  P.querySelectorAll("[data-concept]").forEach(a=>a.onclick=()=>open(a.dataset.concept));
  document.getElementById("cls").onclick=closePanel;
  document.getElementById("foc").onclick=()=>{focus=id;draw()};
  const bk=document.getElementById("back"); if(bk)bk.onclick=()=>{const [v,p]=history.pop();if(v!==view)setView(v,false);open(p,true)};
  B.scrollTop=0;
}
function closePanel(){document.getElementById("panel").classList.remove("open");selected=null;mark();labels()}
document.getElementById("vNotes").onclick=()=>setView("notes");
document.getElementById("vConcepts").onclick=()=>setView("concepts");
document.getElementById("guess").onclick=e=>{showGuess=!showGuess;e.target.classList.toggle("on",showGuess);draw()};
document.getElementById("reset").onclick=()=>{focus=null;document.getElementById("q").value="";svg.transition().call(zoom.transform,d3.zoomIdentity);draw()};
document.getElementById("q").oninput=search;
document.getElementById("q").onkeydown=e=>{if(e.key!=="Enter")return;const q=e.target.value.trim().toLowerCase();
  const pool=view==="notes"?D.notes.map(n=>[n.id,n.title]):D.concepts.map(c=>[c.id,c.label]);const hit=pool.find(([,l])=>l.toLowerCase().includes(q));if(hit)open(hit[0])};
addEventListener("keydown",e=>{if(e.key==="Escape")closePanel()});
draw();
</script></body></html>"""

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
