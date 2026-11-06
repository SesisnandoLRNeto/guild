#!/usr/bin/env python3
"""guild draw: a picture for a war table page, drawn by guild instead of by hand.

An adventurer describes what it wants to show as a small JSON spec; guild picks the best form
for it and draws a clean SVG: a state machine for modes that loop back with guards, a flow for a
path from a request to an answer, an organogram for who owns or contains what, a rules table for
conditions and their outcomes. The figure says which form it chose and why, so the guildmaster
reads the reason with the picture.

  guild draw spec.json                      the <figure> on stdout
  guild draw spec.json --into page.html     put it where the page has <!--GUILD-DRAW--> (or after
                                            "How the gears turn", or before </body>)
  guild draw --example                      a spec to start from

The spec:
  {"kind": "auto" | "state" | "flow" | "org" | "rules",      (auto picks)
   "direction": "TB" | "LR",                                  (optional)
   "title": "...", "note": "one line under the picture",
   "nodes": [{"id": "SELF", "label": "Self reported", "kind": "start|end|normal"}],
   "edges": [{"from": "SELF", "to": "LOCKED", "label": "a day exists",
              "trigger": "screen or endpoint", "who": "who does it", "scenario": "when it happens",
              "result": "what they see", "where": "Class.method"}],      (the scene fields are optional)
   "tree": {"label": "Project", "sub": "owner", "children": [...]},
   "rules": [{"when": "...", "then": "...", "else": "...", "where": "..."}]}
"""
import html
import json
import os
import sys

FONT = "ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif"
E = html.escape
NODE_H = 40
PAD_X = 16
CHAR_W = 7.4          # average width of a 13px sans glyph
LABEL_CHAR_W = 6.6     # 12px edge labels
GAP_LAYER = 92
GAP_NODE = 44
MARGIN = 28
WRAP_AT = 24


# ── picking the form ──────────────────────────────────────────────────────────
def pick(spec):
    """(kind, why): the form that fits the data, and the reason in one sentence."""
    kind = spec.get("kind", "auto")
    if kind and kind != "auto":
        return kind, {
            "state": "a state machine: modes with the moves allowed between them",
            "flow": "a flow: the path from one end to the other",
            "org": "an organogram: who contains or owns what",
            "rules": "a rules table: each condition with what happens",
        }.get(kind, kind)
    if spec.get("rules"):
        return "rules", "a rules table, because the point is conditions and what happens under each"
    if spec.get("tree"):
        return "org", "an organogram, because the point is what contains or owns what"
    edges = spec.get("edges") or []
    nodes = {n["id"] for n in spec.get("nodes") or []}
    loops = any(e["from"] == e["to"] for e in edges)
    starts = any(n.get("kind") in ("start", "end") for n in spec.get("nodes") or [])
    if loops or starts or has_cycle(nodes, edges):
        return "state", "a state machine, because the moves loop back and depend on guards"
    return "flow", "a flow, because the path runs one way from start to finish"


def has_cycle(nodes, edges):
    out = {n: [] for n in nodes}
    for e in edges:
        if e["from"] != e["to"] and e["from"] in out:
            out[e["from"]].append(e["to"])
    seen, stack = set(), set()

    def visit(n):
        if n in stack:
            return True
        if n in seen:
            return False
        seen.add(n); stack.add(n)
        if any(visit(m) for m in out.get(n, [])):
            return True
        stack.discard(n)
        return False
    return any(visit(n) for n in nodes)


# ── text ──────────────────────────────────────────────────────────────────────
def wrap(text, at=WRAP_AT):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > at:
            lines.append(cur); cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def text_lines(x, y, lines, size=13, weight="600", anchor="middle", fill="var(--gd-text, #2d2216)"):
    lh = size + 4
    top = y - lh * (len(lines) - 1) / 2
    return "".join(f'<text x="{x:.1f}" y="{top + i * lh + size * .35:.1f}" text-anchor="{anchor}" font-size="{size}" '
                   f'font-weight="{weight}" fill="{fill}">{E(l)}</text>' for i, l in enumerate(lines))


# ── graphs: state machines and flows ──────────────────────────────────────────
def layout_graph(spec, kind):
    direction = spec.get("direction") or ("TB" if kind == "state" else "LR")
    nodes = []
    byid = {}
    for n in spec.get("nodes") or []:
        node = {"id": n["id"], "label": n.get("label", n["id"]), "kind": n.get("kind", "normal"),
                "lines": [] if n.get("kind") in ("start", "end") else wrap(n.get("label", n["id"]))}
        if node["kind"] in ("start", "end"):
            node["w"] = node["h"] = 20
        else:
            node["w"] = max(84, max(len(l) for l in node["lines"]) * CHAR_W + 2 * PAD_X)
            node["h"] = NODE_H + (len(node["lines"]) - 1) * 17
        nodes.append(node); byid[node["id"]] = node
    edges = []
    for e in spec.get("edges") or []:
        for end in ("from", "to"):           # a node named only in an edge still gets drawn
            if e[end] not in byid:
                node = {"id": e[end], "label": e[end], "kind": "normal", "lines": wrap(e[end])}
                node["w"] = max(84, max(len(l) for l in node["lines"]) * CHAR_W + 2 * PAD_X)
                node["h"] = NODE_H
                nodes.append(node); byid[e[end]] = node
        edges.append({"from": e["from"], "to": e["to"], "label": e.get("label", ""), "scene": e.get("scene")})

    # break cycles for the layering only: a back edge is layered the other way round
    order = [n["id"] for n in nodes]
    out = {i: [] for i in order}
    for e in edges:
        if e["from"] != e["to"]:
            out[e["from"]].append(e["to"])
    seen, stack, back = set(), [], set()

    def dfs(n):
        seen.add(n); stack.append(n)
        for m in out[n]:
            if m in stack:
                back.add((n, m))
            elif m not in seen:
                dfs(m)
        stack.pop()
    for n in order:
        if n not in seen:
            dfs(n)
    dag = {i: [] for i in order}
    preds = {i: [] for i in order}
    for e in edges:
        a, b = e["from"], e["to"]
        if a == b:
            continue
        if (a, b) in back:
            a, b = b, a
        if b not in dag[a]:
            dag[a].append(b); preds[b].append(a)

    # layers: longest path from the sources
    rank = {i: 0 for i in order}
    for _ in range(len(order)):
        changed = False
        for a in order:
            for b in dag[a]:
                if rank[b] < rank[a] + 1:
                    rank[b] = rank[a] + 1; changed = True
        if not changed:
            break
    layers = {}
    for i in order:
        layers.setdefault(rank[i], []).append(i)
    depth = max(layers) + 1 if layers else 0

    # order inside a layer: barycenter of the neighbours, a few sweeps each way
    pos = {i: k for L in layers.values() for k, i in enumerate(L)}
    for _ in range(4):
        for r in range(1, depth):
            L = layers[r]
            key = lambda i: (sum(pos[p] for p in preds[i]) / len(preds[i])) if preds[i] else pos[i]
            L.sort(key=key); pos.update({i: k for k, i in enumerate(L)})
        for r in range(depth - 2, -1, -1):
            L = layers[r]
            key = lambda i: (sum(pos[s] for s in dag[i]) / len(dag[i])) if dag[i] else pos[i]
            L.sort(key=key); pos.update({i: k for k, i in enumerate(L)})

    # coordinates: layers along the main axis, nodes spread and centred across it
    cross = "w" if direction == "TB" else "h"
    along = "h" if direction == "TB" else "w"
    widths = {r: sum(byid[i][cross] for i in L) + GAP_NODE * (len(L) - 1) for r, L in layers.items()}
    span = max(widths.values()) if widths else 0
    gaps = max(GAP_LAYER, 40 + max((len(e["label"]) for e in edges), default=0) * 0) if edges else GAP_LAYER
    offset = MARGIN
    for r in range(depth):
        L = layers[r]
        start = MARGIN + (span - widths[r]) / 2
        for i in L:
            n = byid[i]
            n["c"] = start + n[cross] / 2        # position across
            n["a"] = offset + max(byid[j][along] for j in L) / 2   # position along
            start += n[cross] + GAP_NODE
        offset += max(byid[j][along] for j in L) + gaps
    total_along = offset - gaps + MARGIN
    total_cross = span + 2 * MARGIN
    for n in nodes:
        if direction == "TB":
            n["x"], n["y"] = n["c"], n["a"]
        else:
            n["x"], n["y"] = n["a"], n["c"]
        n["rank"] = rank[n["id"]]
    size = (total_cross, total_along) if direction == "TB" else (total_along, total_cross)
    return nodes, byid, edges, direction, size, layers


def edge_path(a, b, direction, kind, side=1):
    """A cubic path from node a to node b, and the point where its label sits.
    kind: forward (next layers), back (an earlier layer), level (the same layer), loop."""
    if kind == "loop":
        if direction == "TB":
            x, y = a["x"] + a["w"] / 2, a["y"]
            d = f"M{x:.1f},{y - 8:.1f} C{x + 46:.1f},{y - 30:.1f} {x + 46:.1f},{y + 30:.1f} {x:.1f},{y + 8:.1f}"
            return d, (x + 36, y, "right")
        x, y = a["x"], a["y"] + a["h"] / 2
        d = f"M{x - 8:.1f},{y:.1f} C{x - 30:.1f},{y + 46:.1f} {x + 30:.1f},{y + 46:.1f} {x + 8:.1f},{y:.1f}"
        return d, (x, y + 36, "below")
    if direction == "TB":
        if kind == "forward":
            x1, y1, x2, y2 = a["x"] + side, a["y"] + a["h"] / 2, b["x"] + side, b["y"] - b["h"] / 2
            dy = (y2 - y1) * .5
            d = f"M{x1:.1f},{y1:.1f} C{x1:.1f},{y1 + dy:.1f} {x2:.1f},{y2 - dy:.1f} {x2:.1f},{y2:.1f}"
            mx, my = bezier_mid((x1, y1), (x1, y1 + dy), (x2, y2 - dy), (x2, y2))
            return d, (mx, my, "right" if side > 0 else "left" if side < 0 else "on")
        if kind == "back":
            s = 1 if side >= 0 else -1
            x1, y1 = a["x"] + s * a["w"] / 2, a["y"]
            x2, y2 = b["x"] + s * b["w"] / 2, b["y"]
            bulge = s * (52 + abs(side))
            d = f"M{x1:.1f},{y1:.1f} C{x1 + bulge:.1f},{y1:.1f} {x2 + bulge:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
            mx, my = bezier_mid((x1, y1), (x1 + bulge, y1), (x2 + bulge, y2), (x2, y2))
            return d, (mx, my, "right" if s > 0 else "left")
        s = 1 if b["x"] > a["x"] else -1
        x1, y1, x2, y2 = a["x"] + s * a["w"] / 2, a["y"], b["x"] - s * b["w"] / 2, b["y"]
        d = f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}"
        return d, ((x1 + x2) / 2, y1 - 6, "above")
    # LR
    if kind == "forward":
        x1, y1, x2, y2 = a["x"] + a["w"] / 2, a["y"] + side, b["x"] - b["w"] / 2, b["y"] + side
        dx = (x2 - x1) * .5
        d = f"M{x1:.1f},{y1:.1f} C{x1 + dx:.1f},{y1:.1f} {x2 - dx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
        mx, my = bezier_mid((x1, y1), (x1 + dx, y1), (x2 - dx, y2), (x2, y2))
        return d, (mx, my, "below" if side > 0 else "above" if side < 0 else "on")
    if kind == "back":
        s = 1 if side >= 0 else -1
        x1, y1 = a["x"], a["y"] + s * a["h"] / 2
        x2, y2 = b["x"], b["y"] + s * b["h"] / 2
        bulge = s * (46 + abs(side))
        d = f"M{x1:.1f},{y1:.1f} C{x1:.1f},{y1 + bulge:.1f} {x2:.1f},{y2 + bulge:.1f} {x2:.1f},{y2:.1f}"
        mx, my = bezier_mid((x1, y1), (x1, y1 + bulge), (x2, y2 + bulge), (x2, y2))
        return d, (mx, my, "below" if s > 0 else "above")
    s = 1 if b["y"] > a["y"] else -1
    x1, y1, x2, y2 = a["x"], a["y"] + s * a["h"] / 2, b["x"], b["y"] - s * b["h"] / 2
    d = f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}"
    return d, (x1 + 6, (y1 + y2) / 2, "right")


def bezier_mid(p0, p1, p2, p3, t=.5):
    f = lambda a, b, c, d: (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t ** 2 * c + t ** 3 * d
    return f(p0[0], p1[0], p2[0], p3[0]), f(p0[1], p1[1], p2[1], p3[1])


def draw_graph(spec, kind):
    nodes, byid, edges, direction, (W, H), layers = layout_graph(spec, kind)
    # what each edge is, and a side so two edges between the same nodes do not share a line
    pairs = {}
    for e in edges:
        pairs.setdefault(frozenset((e["from"], e["to"])), []).append(e)
    back_count = 0
    out = []
    labels = []
    for e in edges:
        a, b = byid[e["from"]], byid[e["to"]]
        if a is b:
            k, side = "loop", 0
        elif b["rank"] > a["rank"]:
            k = "forward"
            side = 0
            twins = pairs[frozenset((a["id"], b["id"]))]
            if len(twins) > 1:
                side = 10 if direction == "TB" else 8
        elif b["rank"] < a["rank"]:
            k = "back"
            back_count += 1
            side = (1 if back_count % 2 else -1) * (1 + 12 * (back_count // 2))
            twins = pairs[frozenset((a["id"], b["id"]))]
            if len(twins) > 1 and abs(b["rank"] - a["rank"]) == 1:
                k, side = "forward", -10 if direction == "TB" else -8   # the twin of a forward edge: a parallel line back
        else:
            k, side = "level", 0
        d, mid = edge_path(a, b, direction, k, side)
        if k == "forward" and side < 0:      # drawn as a forward curve, but it points back
            d = reverse_path(d)
        # a forward edge that skips a layer swings round the nodes in between
        if k == "forward" and abs(b["rank"] - a["rank"]) > 1:
            d, mid = skip_path(a, b, direction, byid, layers)
        scene = e.get("scene")
        out.append(f'<path d="{d}" fill="none" stroke="var(--gd-line, #8a6a1e)" stroke-width="1.6" marker-end="url(#gd-arrow)"'
                   + (f' class="gd-edge" data-scene="{scene}"' if scene else "") + "/>")
        if e["label"] or scene:
            labels.append([mid[0], mid[1], mid[2] if len(mid) > 2 else "on", e["label"], scene])
    # labels: a pill each, anchored beside its line, kept off the nodes and off each other
    node_boxes = [(n["x"] - n["w"] / 2 - 4, n["y"] - n["h"] / 2 - 4, n["w"] + 8, n["h"] + 8) for n in nodes]
    boxes = []
    for mx, my, where, label, scene in labels:
        lines = wrap(label, 26) if label else [""]
        w = (max(len(l) for l in lines) * LABEL_CHAR_W + 14 if label else 0) + (18 if scene else 0)
        h = 16 * len(lines) + 6 if label else 22
        x, y = mx - w / 2, my - h / 2
        if where == "right": x = mx + 6
        elif where == "left": x = mx - w - 6
        elif where == "above": y = my - h - 4
        elif where == "below": y = my + 4
        for _ in range(8):
            moved = False
            for (bx, by, bw, bh) in node_boxes:          # off a node: step out sideways, away from its centre
                if x < bx + bw and x + w > bx and y < by + bh and y + h > by:
                    x = bx + bw + 4 if mx >= bx + bw / 2 else bx - w - 4; moved = True
            for (bx, by, bw, bh) in boxes:               # off another label: step down
                if x < bx + bw and x + w > bx and y < by + bh and y + h > by:
                    y = by + bh + 4; moved = True
            if not moved:
                break
        boxes.append((x, y, w, h))
        badge = ""
        tx = x + w / 2
        if scene:
            badge = (f'<circle cx="{x + 11:.1f}" cy="{y + h / 2:.1f}" r="8" fill="var(--gd-line, #8a6a1e)"/>'
                     f'<text x="{x + 11:.1f}" y="{y + h / 2 + 3.5:.1f}" text-anchor="middle" font-size="10" font-weight="700" fill="var(--gd-pill, #fff8e6)">{scene}</text>')
            tx = x + 18 + (w - 18) / 2
        out.append(f'<g class="gd-label"{f" data-scene={chr(34)}{scene}{chr(34)}" if scene else ""}>'
                   f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{h / 2 if not label else 4}" fill="var(--gd-pill, #fff8e6)" '
                   f'stroke="var(--gd-line, #8a6a1e)" stroke-width=".6" opacity=".96"/>' + badge
                   + (text_lines(tx, y + h / 2, lines, 12, "500", fill="var(--gd-dim, #5b3e28)") if label else "") + "</g>")
        W = max(W, x + w + MARGIN); H = max(H, y + h + MARGIN)
    # a label pushed past the left edge moves the whole picture right
    minx = min([bx for (bx, _, _, _) in boxes] + [MARGIN])
    shift = MARGIN / 2 - minx if minx < MARGIN / 2 else 0
    for n in nodes:
        if n["kind"] == "start":
            out.append(f'<circle cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="8" fill="var(--gd-line, #8a6a1e)"/>')
        elif n["kind"] == "end":
            out.append(f'<circle cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="9" fill="none" stroke="var(--gd-line, #8a6a1e)" stroke-width="1.6"/>'
                       f'<circle cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="5.5" fill="var(--gd-line, #8a6a1e)"/>')
        else:
            out.append(f'<rect x="{n["x"] - n["w"] / 2:.1f}" y="{n["y"] - n["h"] / 2:.1f}" width="{n["w"]:.1f}" height="{n["h"]:.1f}" rx="7" '
                       f'fill="var(--gd-node, #f6ecd2)" stroke="var(--gd-line, #8a6a1e)" stroke-width="1.4"/>'
                       + text_lines(n["x"], n["y"], n["lines"]))
    body = "".join(out)
    if shift:
        body = f'<g transform="translate({shift:.1f},0)">{body}</g>'
        W += shift
    return svg(W, H, body)


def reverse_path(d):
    """Flip a cubic path so the arrow sits on the other end."""
    parts = d.replace("M", "").replace("C", " ").split()
    pts = [tuple(float(v) for v in p.split(",")) for p in parts]
    if len(pts) != 4:
        return d
    p0, p1, p2, p3 = pts[::-1]
    return f"M{p0[0]:.1f},{p0[1]:.1f} C{p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f} {p3[0]:.1f},{p3[1]:.1f}"


def skip_path(a, b, direction, byid, layers):
    """An edge over more than one layer: swing past the nodes in between on the emptier side."""
    between = [byid[i] for r in range(a["rank"] + 1, b["rank"]) for i in layers[r]]
    if direction == "TB":
        left = min(n["x"] - n["w"] / 2 for n in between); right = max(n["x"] + n["w"] / 2 for n in between)
        mid = (a["x"] + b["x"]) / 2
        cx = (left - 36) if abs(mid - left) < abs(mid - right) else (right + 36)
        x1, y1, x2, y2 = a["x"], a["y"] + a["h"] / 2, b["x"], b["y"] - b["h"] / 2
        d = f"M{x1:.1f},{y1:.1f} C{cx:.1f},{y1 + 40:.1f} {cx:.1f},{y2 - 40:.1f} {x2:.1f},{y2:.1f}"
        mx, my = bezier_mid((x1, y1), (cx, y1 + 40), (cx, y2 - 40), (x2, y2))
        return d, (mx, my, "left" if cx < mid else "right")
    top = min(n["y"] - n["h"] / 2 for n in between); bottom = max(n["y"] + n["h"] / 2 for n in between)
    mid = (a["y"] + b["y"]) / 2
    cy = (top - 34) if abs(mid - top) < abs(mid - bottom) else (bottom + 34)
    x1, y1, x2, y2 = a["x"] + a["w"] / 2, a["y"], b["x"] - b["w"] / 2, b["y"]
    d = f"M{x1:.1f},{y1:.1f} C{x1 + 40:.1f},{cy:.1f} {x2 - 40:.1f},{cy:.1f} {x2:.1f},{y2:.1f}"
    mx, my = bezier_mid((x1, y1), (x1 + 40, cy), (x2 - 40, cy), (x2, y2))
    return d, (mx, my, "above" if cy < mid else "below")


# ── organograms ───────────────────────────────────────────────────────────────
def draw_org(spec):
    tree = spec["tree"]
    boxes = []

    def measure(t):
        t["lines"] = wrap(t.get("label", ""), 20)
        t["w"] = max(110, max(len(l) for l in t["lines"]) * CHAR_W + 2 * PAD_X, len(t.get("sub", "")) * 6.4 + 2 * PAD_X)
        t["h"] = NODE_H + (len(t["lines"]) - 1) * 17 + (16 if t.get("sub") else 0)
        for c in t.get("children") or []:
            measure(c)
        t["span"] = max(t["w"], sum(c["span"] for c in t.get("children") or []) + GAP_NODE * max(0, len(t.get("children") or []) - 1))
    measure(tree)

    def place(t, left, depth):
        t["x"] = left + t["span"] / 2
        t["y"] = MARGIN + depth * (NODE_H + 70) + t["h"] / 2
        boxes.append(t)
        cur = left + (t["span"] - (sum(c["span"] for c in t.get("children") or []) + GAP_NODE * max(0, len(t.get("children") or []) - 1))) / 2
        for c in t.get("children") or []:
            place(c, cur, depth + 1)
            cur += c["span"] + GAP_NODE
    place(tree, MARGIN, 0)
    out = []
    for t in boxes:
        kids = t.get("children") or []
        if kids:
            y0 = t["y"] + t["h"] / 2
            ym = y0 + 24
            out.append(f'<path d="M{t["x"]:.1f},{y0:.1f} V{ym:.1f}" stroke="var(--gd-line, #8a6a1e)" stroke-width="1.4" fill="none"/>')
            out.append(f'<path d="M{kids[0]["x"]:.1f},{ym:.1f} H{kids[-1]["x"]:.1f}" stroke="var(--gd-line, #8a6a1e)" stroke-width="1.4" fill="none"/>')
            for c in kids:
                out.append(f'<path d="M{c["x"]:.1f},{ym:.1f} V{c["y"] - c["h"] / 2:.1f}" stroke="var(--gd-line, #8a6a1e)" stroke-width="1.4" fill="none"/>')
    for t in boxes:
        out.append(f'<rect x="{t["x"] - t["w"] / 2:.1f}" y="{t["y"] - t["h"] / 2:.1f}" width="{t["w"]:.1f}" height="{t["h"]:.1f}" rx="7" '
                   f'fill="var(--gd-node, #f6ecd2)" stroke="var(--gd-line, #8a6a1e)" stroke-width="1.4"/>')
        dy = -8 if t.get("sub") else 0
        out.append(text_lines(t["x"], t["y"] + dy, t["lines"]))
        if t.get("sub"):
            out.append(text_lines(t["x"], t["y"] + t["h"] / 2 - 12, [t["sub"]], 11, "500", fill="var(--gd-dim, #5b3e28)"))
    W = tree["span"] + 2 * MARGIN
    H = max(t["y"] + t["h"] / 2 for t in boxes) + MARGIN
    return svg(W, H, "".join(out))


# ── rules ─────────────────────────────────────────────────────────────────────
def draw_rules(spec):
    rows = spec.get("rules") or []
    has_else = any(r.get("else") for r in rows)
    has_where = any(r.get("where") for r in rows) and not any(r.get("scenario") or r.get("trigger") for r in rows)
    head = "<tr><th>When</th><th>Then</th>" + ("<th>Otherwise</th>" if has_else else "") + ("<th>Where</th>" if has_where else "") + "</tr>"
    body = "".join(
        f'<tr{" data-scene=" + chr(34) + str(r["scene"]) + chr(34) if r.get("scene") else ""}><td class="gd-when">'
        + (f'<b class="gd-n">{r["scene"]}</b> ' if r.get("scene") else "") + f'{E(r.get("when", ""))}</td><td class="gd-then">{E(r.get("then", ""))}</td>'
        + (f'<td class="gd-else">{E(r.get("else", ""))}</td>' if has_else else "")
        + (f'<td class="gd-where"><code>{E(r.get("where", ""))}</code></td>' if has_where else "") + "</tr>" for r in rows)
    return f'<table class="guild-rules">{head}{body}</table>'


# ── the figure ────────────────────────────────────────────────────────────────
def svg(W, H, body):
    return (f'<svg viewBox="0 0 {W:.0f} {H:.0f}" width="100%" style="max-width:{W:.0f}px;display:block;height:auto" '
            f'font-family="{FONT}" role="img">'
            '<defs><marker id="gd-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            '<path d="M0,0 L10,5 L0,10 z" fill="var(--gd-line, #8a6a1e)"/></marker></defs>' + body + "</svg>")


SCENE_FIELDS = (("trigger", "Triggered by"), ("who", "Who"), ("scenario", "Scenario"), ("result", "What they see"), ("where", "Where"))


def number_scenes(spec):
    """Give every edge (or rule) that tells a scene its number, in order. Returns the scenes."""
    scenes = []
    items = spec.get("edges") if spec.get("edges") else spec.get("rules") or []
    for item in items:
        if any(item.get(k) for k, _ in SCENE_FIELDS if k != "where"):   # a code location alone is not a scene
            item["scene"] = len(scenes) + 1
            scenes.append(item)
    return scenes


def scenes_html(scenes, kind):
    if not scenes:
        return ""
    rows = []
    for sc in scenes:
        head = sc.get("label") or sc.get("when") or f'{sc.get("from", "")} to {sc.get("to", "")}'
        if kind in ("state", "flow") and sc.get("from") and sc.get("to"):
            head = f'{E(head)} <span class="gd-move">{E(sc["from"])} &rarr; {E(sc["to"])}</span>'
        else:
            head = E(head)
        cells = "".join(f'<dt>{label}</dt><dd>{"<code>" + E(sc[k]) + "</code>" if k == "where" else E(sc[k])}</dd>'
                        for k, label in SCENE_FIELDS if sc.get(k))
        rows.append(f'<li data-scene="{sc["scene"]}"><b class="gd-n">{sc["scene"]}</b><div><p class="gd-head">{head}</p><dl>{cells}</dl></div></li>')
    script = ("<script>(function(){var f=document.currentScript.parentNode;"
              "function mark(n,on){f.querySelectorAll('[data-scene=\"'+n+'\"]').forEach(function(el){el.classList.toggle('gd-hot',on)});}"
              "f.querySelectorAll('[data-scene]').forEach(function(el){el.addEventListener('mouseenter',function(){mark(el.dataset.scene,true)});"
              "el.addEventListener('mouseleave',function(){mark(el.dataset.scene,false)});});})();</script>")
    return f'<ol class="gd-scenes">{"".join(rows)}</ol>{script}'


def figure(spec):
    kind, why = pick(spec)
    scenes = number_scenes(spec)
    if kind == "rules":
        body = draw_rules(spec)
    elif kind == "org":
        body = draw_org(spec)
    elif kind in ("state", "flow"):
        body = draw_graph(spec, kind)
    else:
        raise SystemExit(f"guild draw: unknown kind {kind}")
    title = f'<figcaption class="gd-title">{E(spec["title"])}</figcaption>' if spec.get("title") else ""
    note = E(spec.get("note", ""))
    return (f'<figure class="guild-draw" data-kind="{kind}">{title}<div class="gd-body">{body}</div>'
            f'<figcaption class="gd-note">{note}{" " if note else ""}<small>Drawn as {E(why)}.</small></figcaption>'
            + scenes_html(scenes, kind) + "</figure>")


def into(page, fig):
    text = open(page).read()
    if "<!--GUILD-DRAW-->" in text:
        return text.replace("<!--GUILD-DRAW-->", fig, 1)
    low = text.lower()
    i = low.find("how the gears turn")
    if i >= 0:
        j = low.find("</h2>", i)
        if j >= 0:
            return text[:j + 5] + "\n" + fig + text[j + 5:]
    j = low.rfind("</body>")
    return (text[:j] + fig + "\n" + text[j:]) if j >= 0 else text + fig


EXAMPLE = {
    "kind": "auto", "title": "Reporting mode of a workstream",
    "note": "Once a day exists, the mode stays where it is.",
    "nodes": [{"id": "start", "kind": "start"}, {"id": "SELF", "label": "Self reported"},
              {"id": "SYSTEM_TRACKED", "label": "System tracked"}, {"id": "LOCKED", "label": "Locked: a day exists"}],
    "edges": [{"from": "start", "to": "SELF"},
              {"from": "SELF", "to": "SYSTEM_TRACKED", "label": "no day reported yet",
               "trigger": "the Edit workstream form, field Reporting mode", "who": "a project manager",
               "scenario": "the workstream was created as self reported and nobody has reported a day on it yet",
               "result": "the save goes through and the self-report field disappears", "where": "WorkstreamEditService"},
              {"from": "SYSTEM_TRACKED", "to": "SELF", "label": "no day reported yet"},
              {"from": "SELF", "to": "LOCKED", "label": "a day exists",
               "trigger": "a contributor saves a timesheet day", "scenario": "the first day reported on the workstream locks its mode",
               "where": "TimesheetCommandService.saveDraft"},
              {"from": "SYSTEM_TRACKED", "to": "LOCKED", "label": "a day exists"},
              {"from": "LOCKED", "to": "LOCKED", "label": "a move is refused with 409",
               "trigger": "the Edit workstream form, field Reporting mode", "who": "a project manager",
               "scenario": "days already exist and the mode is switched in or out of system tracked",
               "result": "409 with a clear message; nothing changes", "where": "WorkstreamEditService"}],
}


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        raise SystemExit(__doc__)
    if argv[0] == "--example":
        print(json.dumps(EXAMPLE, indent=2)); return
    spec = json.load(open(argv[0]))
    fig = figure(spec)
    if "--into" in argv:
        page = argv[argv.index("--into") + 1]
        out = into(page, fig)             # read first: open(page, "w") would empty it
        open(page, "w").write(out)
        print(f"drawn into {page} as {pick(spec)[0]}")
    elif "--out" in argv:
        out = argv[argv.index("--out") + 1]
        open(out, "w").write(fig)
        print(f"drawn to {out} as {pick(spec)[0]}")
    else:
        print(fig)


if __name__ == "__main__":
    main(sys.argv[1:])
