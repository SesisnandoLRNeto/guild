#!/usr/bin/env python3
"""Tell the guildmaster when something waits for them, and reach the war table from a phone.

  notify.py event <slug> <state> <note>   called for every guild event; notifies on the ones
                                          that need you (a decision, a block, a failure, done)
  notify.py remote on|off|status|url|qr   the war table on your Tailscale address, behind a key (qr: scan it)
  notify.py test                          send a test notification the configured ways
  notify.py email <to> [from] | off       email alerts to <to>, sent from the Gmail account [from]

Config: ~/.guild/local/remote.json
  {"remote": true, "bind": "100.x.y.z", "port": 4712, "key": "...",   written by `guild remote on`
   "mac": true,                                                         a macOS notification (default on)
   "ntfy": "https://ntfy.sh/<your-private-topic>",                      optional phone push, off by default
   "email": {"to": "you@gmail.com", "from": "you@gmail.com"}}           optional email for alerts (alerts.py)

Email goes through Gmail's SMTP server as "from", with a Gmail app password kept in the
macOS Keychain (service "guild-email", account = the "from" address), never in a file:
  security add-generic-password -s guild-email -a you@gmail.com -w
Only alerts are emailed (PR follow-ups, Claude usage, a question waiting too long), not
every quest event. An email carries the same short line as the push and a link without the key.

The phone push carries only "<quest>: <what waits>" and a link, never the note, the ticket
text or code: the topic is a third-party service.
"""
import json
import os
import secrets
import smtplib
import ssl
from email.message import EmailMessage
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

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


def email_password(sender):
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", "guild-email", "-a", sender, "-w"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def send_email(title, text, url=""):
    """Send one alert by email. Returns "" when sent, or why it was not."""
    e = config().get("email") or {}
    to, sender = e.get("to", ""), e.get("from") or e.get("to", "")
    if not to:
        return "no email set (guild notify email <address>)"
    password = email_password(sender)
    if not password:
        return f"no app password in the Keychain for {sender} (security add-generic-password -s guild-email -a {sender} -w)"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = title, sender, to
    msg.set_content(text + ("\n\n" + url.split("?k=")[0] if url else "") + "\n\n(guild alert)")
    try:
        with smtplib.SMTP_SSL(e.get("host", "smtp.gmail.com"), int(e.get("port", 465)),
                              context=ssl.create_default_context(), timeout=20) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
        return ""
    except (OSError, smtplib.SMTPException) as err:
        return f"email failed: {type(err).__name__}"


def send(title, text, url="", email=False):
    cfg = config()
    if os.environ.get("GUILD_NO_NOTIFY"):
        return
    if email and cfg.get("email"):
        send_email(title, text, url)  # a mail that fails must never break the guild either
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
    if state == "wrapup":                 # the quest reported done with a wrap-up to grade
        what = "posted its wrap-up for your grade"
    elif state == "done" and "(no wrap-up)" in note:
        what = "is done"
    if not what:
        return
    send(f"guild: {slug}", f"{slug} {what}", docket_url())


def console_url(cfg=None):
    """The phone link that lands on the console. The key in it sets a cookie, so every page works after."""
    return docket_url(cfg).replace("/?k=", "/console?k=", 1)


def print_qr(url):
    """The link as a QR code in the terminal, and as text under it."""
    import qr
    print(qr.terminal(url))
    print(url)
    print("A bigger code on this Mac: http://127.0.0.1:4711/remote/qr")


def remote(cmd):
    cfg = config()
    if cmd == "on":
        ip = tailscale_ip()
        if not ip:
            raise SystemExit("guild remote: Tailscale is not running here. Start it (the menu bar app, or `tailscale up`) and run this again.")
        cfg.update(remote=True, bind=ip, port=int(cfg.get("port", 4712)), key=cfg.get("key") or secrets.token_urlsafe(18))
        save(cfg)
        print("remote on: restart the war table with `guild remote restart`, then scan this with the phone camera (same tailnet):")
        print_qr(console_url(cfg))
    elif cmd == "off":
        cfg["remote"] = False
        save(cfg)
        print("remote off: the war table answers on this Mac only after `guild remote restart`")
    elif cmd == "url":
        print(docket_url(cfg))
    elif cmd == "qr":
        if not (cfg.get("remote") and cfg.get("key")):
            raise SystemExit("guild remote qr: remote is off. Run `guild remote on` and `guild remote restart` first.")
        print("Scan with the phone camera (Tailscale on). It opens the quest console; the docket is one tap away.")
        print_qr(console_url(cfg))
    elif cmd == "status":
        print(f"remote: {'on at ' + cfg.get('bind', '?') + ':' + str(cfg.get('port', 4712)) if cfg.get('remote') else 'off'}"
              f" · mac notifications: {'on' if cfg.get('mac', True) else 'off'}"
              f" · phone push: {'ntfy ' + cfg['ntfy'].split('/')[2] if cfg.get('ntfy') else 'off'}"
              f" · alert email: {(cfg.get('email') or {}).get('to') or 'off'}")
    else:
        raise SystemExit("usage: guild remote on|off|status|url|qr|restart")


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
        if config().get("email"):
            why = send_email("guild: test alert", "Test from guild: alerts reach this inbox.", docket_url())
            print("email: " + (why or "sent to " + config()["email"]["to"]))
    elif args[0] == "email" and len(args) > 1:
        cfg = config()
        if args[1] == "off":
            cfg.pop("email", None)
            print("alert email off")
        else:
            cfg["email"] = {"to": args[1], "from": args[2] if len(args) > 2 else args[1]}
            print(f"alerts go to {args[1]}. Put a Gmail app password for {cfg['email']['from']} in the Keychain:\n"
                  f"  security add-generic-password -s guild-email -a {cfg['email']['from']} -w\n"
                  "then run `guild notify test`.")
        save(cfg)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
