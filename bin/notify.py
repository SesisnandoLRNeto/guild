#!/usr/bin/env python3
"""Tell the guildmaster when something waits for them, and reach the war table from a phone.

  notify.py event <slug> <state> <note>   called for every guild event; notifies on the ones
                                          that need you (a decision, a block, a failure, done)
  notify.py remote on|off|status|url      the war table on your Tailscale address, behind a key
  notify.py test                          send a test notification the configured ways

Config: ~/.guild/local/remote.json
  {"remote": true, "bind": "100.x.y.z", "port": 4712, "key": "...",   written by `guild remote on`
   "mac": true,                                                         a macOS notification (default on)
   "ntfy": "https://ntfy.sh/<your-private-topic>"}                      optional phone push, off by default

The phone push carries only "<quest>: <what waits>" and a link, never the note, the ticket
text or code: the topic is a third-party service.
"""
import json
import os
import secrets
import subprocess
import sys
import urllib.request

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
CONFIG = os.path.join(GUILD_HOME, "local", "remote.json")
LOUD = {"needs-decision": "a decision waits for you", "blocked": "is blocked", "failed": "failed",
        "done": "is done, its wrap-up waits for your grade", "graded": None}


def config():
    try:
        return json.load(open(CONFIG))
    except (OSError, ValueError):
        return {}


def save(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    json.dump(cfg, open(CONFIG, "w"), indent=2)
    os.chmod(CONFIG, 0o600)          # the key opens your war table: keep it yours


def tailscale_ip():
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
        ip = out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
        status = subprocess.run(["tailscale", "status"], capture_output=True, text=True, timeout=5)
        return ip if status.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def docket_url(cfg=None):
    cfg = cfg or config()
    if cfg.get("remote") and cfg.get("bind") and cfg.get("key"):
        return f"http://{cfg['bind']}:{cfg.get('port', 4712)}/?k={cfg['key']}"
    try:
        port = open(os.path.join(GUILD_HOME, ".wartable-port")).read().strip()
        return f"http://127.0.0.1:{port}/"
    except OSError:
        return ""


def send(title, text, url=""):
    cfg = config()
    if os.environ.get("GUILD_NO_NOTIFY"):
        return
    if cfg.get("mac", True) and sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f"display notification {json.dumps(text)} with title {json.dumps(title)}"],
                       capture_output=True, timeout=5)
    if cfg.get("ntfy"):
        req = urllib.request.Request(cfg["ntfy"], data=text.encode(), method="POST",
                                     headers={"Title": title, **({"Click": url} if url else {}), "Tags": "crossed_swords"})
        try:
            urllib.request.urlopen(req, timeout=8)
        except OSError:
            pass                      # a push that fails must never break the guild


def on_event(slug, state, note):
    what = LOUD.get(state)
    if state == "working" and note.startswith("wrap-up ready"):
        what = "posted its wrap-up for your grade"
    elif state == "done" and "(no wrap-up)" in note:
        what = "is done"
    if not what:
        return
    send(f"guild: {slug}", f"{slug} {what}", docket_url())


def remote(cmd):
    cfg = config()
    if cmd == "on":
        ip = tailscale_ip()
        if not ip:
            raise SystemExit("guild remote: Tailscale is not running here. Start it (the menu bar app, or `tailscale up`) and run this again.")
        cfg.update(remote=True, bind=ip, port=int(cfg.get("port", 4712)), key=cfg.get("key") or secrets.token_urlsafe(18))
        save(cfg)
        print("remote on: restart the war table with `guild remote restart`, then open on your phone (same tailnet):")
        print(docket_url(cfg))
    elif cmd == "off":
        cfg["remote"] = False
        save(cfg)
        print("remote off: the war table answers on this Mac only after `guild remote restart`")
    elif cmd == "url":
        print(docket_url(cfg))
    elif cmd == "status":
        print(f"remote: {'on at ' + cfg.get('bind', '?') + ':' + str(cfg.get('port', 4712)) if cfg.get('remote') else 'off'}"
              f" · mac notifications: {'on' if cfg.get('mac', True) else 'off'}"
              f" · phone push: {'ntfy ' + cfg['ntfy'].split('/')[2] if cfg.get('ntfy') else 'off'}")
    else:
        raise SystemExit("usage: guild remote on|off|status|url|restart")


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    if args[0] == "event" and len(args) >= 3:
        on_event(args[1], args[2], args[3] if len(args) > 3 else "")
    elif args[0] == "remote" and len(args) > 1:
        remote(args[1])
    elif args[0] == "test":
        send("guild", "Test from guild: notifications reach you.", docket_url())
        print("sent the ways configured in " + CONFIG)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
