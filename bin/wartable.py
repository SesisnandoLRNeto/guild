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
               "subtitle": args.get("subtitle", ""), "created": now()},
              open(os.path.join(d, "board.json"), "w"), indent=2)

    port = ensure_server()
    url = f"http://127.0.0.1:{port}/b/{quest}/{board}/"
    record(quest, "needs-decision", f"war table ready: {args.get('title') or board} -> {url}")
    if not args.get("no_open"):
        subprocess.run(["open", url], check=False)
    print(url)


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
        while True:
            time.sleep(3600)
    args, key = {}, None
    positional = []
    for token in rest:
        if token.startswith("--"):
            key = token[2:].replace("-", "_")
            args[key] = True
        elif key:
            args[key] = token
            key = None
        else:
            positional.append(token)
    if cmd == "open":
        args["quest"] = positional[0]
        return cmd_open(args)
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
