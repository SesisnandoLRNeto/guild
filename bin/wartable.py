#!/usr/bin/env python3
"""War table: a local board where the guildmaster decides, and the quest resumes.

An adventurer writes an HTML page (analysis, variants, before/after, whatever reads best)
plus an optional decisions.json. This server wraps that page with a side panel for choices,
a message and images. The reply is written to decision.json in the board folder, which the
waiting adventurer reads with `guild board wait`.

Everything is local: 127.0.0.1 only, no network calls, no accounts.
"""
import base64
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


def fleet():
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import fleet as mod
    return mod


def campaign_action(action, body):
    """Buttons on the campaign board: jump to a tab, pin a card, add or finish a to-do."""
    f = fleet()
    socket_name = os.environ.get("GUILD_TMUX_SOCKET", "guild")
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
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                return self.send(200, self.render_index())
            if path == "/campaign":        # the campaign board: every agent and ticket, as a kanban
                return self.send(200, open(os.path.join(WEB, "campaign.html")).read())
            if path == "/campaign.json":
                return self.send(200, json.dumps(fleet().board()), "application/json")
            v = re.match(r"^/vendor/([A-Za-z0-9._-]+)$", path)
            if v:   # mermaid and friends, fetched once by install.sh, never from a CDN at view time
                target = os.path.join(GUILD_HOME, "vendor", v.group(1))
                if not os.path.isfile(target):
                    return self.send(404, "not installed: run install.sh")
                with open(target, "rb") as f:
                    return self.send(200, f.read(), "text/javascript; charset=utf-8")
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
                return self.send(200, f.read(), ctype)
        except Exception as e:  # never take the server down for one bad request
            return self.send(500, f"error: {e}")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        c = re.match(r"^/campaign/(jump|pin|todo)$", path)
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
            picked = ", ".join(f"{k}={v}" for k, v in decision["answers"].items()) or "message only"
            record(quest, "working", f"war table answered ({meta.get('title', board)}): {picked}")
            return self.send(200, json.dumps({"ok": True}), "application/json")
        except Exception as e:
            return self.send(500, json.dumps({"error": str(e)}), "application/json")

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
        shell = open(os.path.join(WEB, "shell.html")).read()
        return (shell
                .replace("{{TITLE}}", meta.get("title", board))
                .replace("{{QUEST}}", quest)
                .replace("{{BOARD}}", board)
                .replace("{{SUBTITLE}}", meta.get("subtitle", ""))
                .replace("{{QUESTIONS}}", json.dumps(questions)))


def serve():
    """Start the server unless one is already up. Writes the port to ~/.guild/.wartable-port."""
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
    os.makedirs(d, exist_ok=True)
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
 p.detail { color:var(--dim); margin:0 0 26px; max-width:70ch; white-space:pre-wrap; }
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
        why = f'<div class="why">{_esc(o["why"])}</div>' if o["why"] else ""
        blocks.append(f'<div class="opt{suggested}"><div class="id">{_esc(o["id"])}'
                      f'{" · suggested" if suggested else ""}</div>'
                      f'<div class="label">{_esc(o["label"])}</div>{why}</div>')
    detail = f'<p class="detail">{_esc(args["detail"])}</p>' if args.get("detail") else ""
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
