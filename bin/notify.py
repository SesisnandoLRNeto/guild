#!/usr/bin/env python3
"""Tell the guildmaster when something waits for them, and reach the war table from a phone.

  notify.py event <slug> <state> <note>   called for every guild event; notifies on the ones
                                          that need you (a decision, a block, a failure, done)
  notify.py remote on|off|status|url|qr   the war table on your Tailscale address, behind a key (qr: scan it)
  notify.py test                          send a test notification the configured ways
  notify.py email <to> [from] | off       email alerts to <to>, sent from the Gmail account [from]
  notify.py email events on|off           email quest events too (default on once email is set)

Config: ~/.guild/local/remote.json
  {"remote": true, "bind": "100.x.y.z", "port": 4712, "key": "...",   written by `guild remote on`
   "mac": true,                                                         a macOS notification (default on)
   "ntfy": "https://ntfy.sh/<your-private-topic>",                      optional phone push, off by default
   "email": {"to": "you@gmail.com", "from": "you@gmail.com",            optional email: alerts (alerts.py) and
             "events": true}}                                           quest events (default on, false turns them off)

Email goes through Gmail's SMTP server as "from", with a Gmail app password kept in the
macOS Keychain (service "guild-email", account = the "from" address), never in a file:
  security add-generic-password -s guild-email -a you@gmail.com -w
Email carries the alerts (PR follow-ups, Claude usage, a question waiting too long) and the
quest events that need you: needs-decision, blocked, failed, done and wrap-up. Each mail reads
on its own, with no link needed: a decision lists the question, the detail, every option with its
trade-off and the recommended one; blocked and failed carry the whole note, repo, branch and PR;
done carries the PR links and the wrap-up title; a PR alert carries the PR title and its GitHub URL.
It is an HTML mail with a plain-text copy. Events within 60 seconds of each other share one mail
(a second decision gets its own, so a reply names one question).
Links: with `guild remote on` the war table link is the Tailscale address with its key (that
address only opens on your tailnet). With remote off the mail says to open the war table on the
Mac, and the key is never put in a link that is not the tailnet address. Tokens, passwords and the
key are cut out of anything quoted from a note. Reply to a decision mail with an option letter
("b", or "b: why") or free text to answer it from the phone (bin/mailreply.py reads the replies).

The phone push carries only "<quest>: <what waits>" and a link, never the note, the ticket
text or code: the topic is a third-party service.
"""
import fcntl
import html
import json
import os
import re
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
CONFIG = os.path.join(GUILD_HOME, "local", "remote.json")
QUESTS = os.path.join(GUILD_HOME, "quests")
QUEUE = os.path.join(GUILD_HOME, "local", "email-queue.json")
TOKENS = os.path.join(GUILD_HOME, "local", "email-tokens.json")
WINDOW = 60          # seconds an email waits for the events that follow it
STALE = 90           # a queue older than this lost its sender: the next event sends it
EMAIL_STATES = ("needs-decision", "blocked", "failed", "done", "wrapup")
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


# ---- what an email may say: no secrets, and links that open where you read them ---------------

SECRETS = [
    r"gh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}", r"xox[abprs]-[A-Za-z0-9-]{10,}",
    r"AKIA[0-9A-Z]{16}", r"sk-[A-Za-z0-9_-]{16,}", r"AIza[0-9A-Za-z_-]{20,}",
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
]
KEYED = re.compile(r"(?i)\b(pass(?:word|wd)?|pwd|secret|token|api[_-]?key|credentials?|authorization)\b(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)")
BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
LONG = re.compile(r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[G-Zg-z_-])[A-Za-z0-9_-]{32,}\b")
URL_KEY = re.compile(r"([?&])k=[A-Za-z0-9_.~-]+")
LOCAL = re.compile(r"https?://(?:127\.0\.0\.1|localhost)(?::\d+)?(/[^\s)>\"'\]]*)?")
PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")


def redact(text, cfg=None):
    """Cut tokens, passwords and the war table key out of text that came from a quest note."""
    cfg = cfg or config()
    text = text or ""
    for secret in (cfg.get("key"), cfg.get("ntfy")):
        if secret and len(secret) > 6:
            text = text.replace(secret, "[removed]")
    text = BEARER.sub(lambda m: f"{m.group(1)} [removed]", text)
    text = KEYED.sub(lambda m: f"{m.group(1)}{m.group(2)}[removed]", text)
    for pat in SECRETS:
        text = re.sub(pat, "[removed]", text)
    text = URL_KEY.sub("", text)
    return LONG.sub("[removed]", text)


def tail_base(cfg=None):
    """http://<tailscale ip>:<port> when the war table is on your tailnet, else ""."""
    cfg = cfg or config()
    if cfg.get("remote") and cfg.get("bind") and cfg.get("key"):
        return f"http://{cfg['bind']}:{cfg.get('port', 4712)}"
    return ""


def war_link(path="/", cfg=None):
    """A war table link that opens on a phone: the tailnet address with its key. "" with remote off."""
    cfg = cfg or config()
    base = tail_base(cfg)
    return f"{base}{path}?k={cfg['key']}" if base else ""


def localize(text, cfg=None):
    """A 127.0.0.1 link opens nothing on a phone: point it at the tailnet, or say where to open it."""
    cfg = cfg or config()
    return LOCAL.sub(lambda m: war_link(m.group(1) or "/", cfg) or "(open the war table on your Mac)", text or "")


def clean(text, cfg=None):
    return localize(redact(text, cfg), cfg)


def safe_link(url, cfg=None):
    """The key stays only in a link to the tailnet address; every other link loses it."""
    cfg = cfg or config()
    if not url:
        return ""
    base = tail_base(cfg)
    if base and url.startswith(base + "/"):
        return url
    if LOCAL.match(url):
        return ""
    return URL_KEY.sub("", url)


# ---- what each event says ---------------------------------------------------------------------

def load_json(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def quest_facts(slug, note=""):
    """Repo, branch, ticket (with its Jira link) and PRs of a quest."""
    meta = load_json(os.path.join(QUESTS, slug, "meta.json"), {})
    facts = []
    if meta.get("repo"):
        facts.append(("Repo", os.path.basename(meta["repo"].rstrip("/"))))
    if meta.get("branch"):
        facts.append(("Branch", meta["branch"]))
    ticket = meta.get("ticket", "")
    if ticket and ticket != "none":
        site = os.environ.get("GUILD_JIRA_SITE") or load_json(os.path.join(GUILD_HOME, "local", "jira.json"), {}).get("site", "")
        facts.append(("Ticket", f"{ticket} {site.rstrip('/')}/browse/{ticket}" if site else ticket))
    prs_found = {}
    try:
        import prs
        for url, p in prs.cache().items():
            if p.get("slug") == slug:
                prs_found[url] = p.get("title", "")
    except Exception:
        pass
    for url in PR_URL.findall(note or ""):
        prs_found.setdefault(url, "")
    return facts, prs_found


def find_board(slug, note="", want_wrapup=False):
    """The (board id, board.json, decisions) a note points at, else the quest's newest open one."""
    bdir = os.path.join(QUESTS, slug, "boards")
    m = re.search(r"/b/([\w.-]+)/([\w.-]+)/", note or "")
    if m and m.group(1) == slug and os.path.isdir(os.path.join(bdir, m.group(2))):
        ids = [m.group(2)]
    else:
        ids = []
        for b in sorted(os.listdir(bdir)) if os.path.isdir(bdir) else []:
            meta = load_json(os.path.join(bdir, b, "board.json"), {})
            if meta and bool(meta.get("wrapup")) == want_wrapup and (want_wrapup or not os.path.exists(os.path.join(bdir, b, "decision.json"))):
                ids.append((meta.get("created", ""), b))
        ids = [b for _, b in sorted(ids)][-1:]
    for b in ids:
        meta = load_json(os.path.join(bdir, b, "board.json"), {})
        if meta:
            return b, meta, load_json(os.path.join(bdir, b, "decisions.json"), {}).get("questions", [])
    return "", {}, []


def new_token(slug, board):
    """One secret per decision mail: a reply must carry it, so a forged From line is not enough."""
    token = secrets.token_urlsafe(12)
    with locked():
        tokens = load_json(TOKENS, {})
        tokens[token] = {"quest": slug, "board": board, "created": time.time()}
        save_json(TOKENS, tokens)
    return token


def event_item(slug, state, note, cfg=None):
    """One event as an email section: {"slug","state","subject","blocks","board","token"}."""
    cfg = cfg or config()
    facts, prs_found = quest_facts(slug, note)
    blocks, token, board_id = [], "", ""
    flat = [("Quest", slug)] + facts
    subject = {"needs-decision": "needs a decision", "blocked": "is blocked", "failed": "failed",
               "done": "is done", "wrapup": "wrap-up ready"}.get(state, state)
    blocks.append(("title", f"{slug} {subject}"))
    blocks.append(("facts", [(k, clean(v, cfg)) for k, v in flat]))
    board_link = ""
    if state == "needs-decision":
        board_id, meta, questions = find_board(slug, note)
        if board_id:
            board_link = war_link(f"/b/{slug}/{board_id}/", cfg)
            token = new_token(slug, board_id)
            for q in questions or [{"title": meta.get("title", "")}]:
                blocks.append(("h", "Question"))
                blocks.append(("p", clean(q.get("title", ""), cfg)))
                if q.get("detail"):
                    blocks.append(("h", "Detail"))
                    blocks.append(("p", clean(q["detail"], cfg)))
                if q.get("options"):
                    blocks.append(("h", "Options"))
                    blocks.append(("opts", [(o.get("id", ""), clean(o.get("label", ""), cfg), clean(o.get("why", ""), cfg),
                                             o.get("id") == q.get("recommended")) for o in q["options"]]))
                    rec = next((o for o in q["options"] if o.get("id") == q.get("recommended")), None)
                    if rec:
                        blocks.append(("p", f"Recommended: {rec['id']} ({clean(rec.get('label', ''), cfg)})"))
            if len(questions) == 1 and not meta.get("kind"):
                blocks.append(("p", "Answer by replying to this email with an option letter (b, or b: a few words) or free text."))
            else:
                blocks.append(("p", "This board has several questions: answer it on the war table."))
        else:
            blocks.append(("h", "What waits for you"))
            blocks.append(("p", clean(note, cfg)))
    elif state in ("blocked", "failed"):
        blocks.append(("h", "What happened"))
        blocks.append(("p", clean(note, cfg)))
    else:                                    # done, wrapup
        board_id, meta, _ = find_board(slug, note, want_wrapup=True)
        if meta:
            board_link = war_link(f"/b/{slug}/{board_id}/", cfg)
            blocks.append(("h", "Wrap-up"))
            blocks.append(("p", clean(meta.get("title", ""), cfg) + (f"\n{clean(meta['subtitle'], cfg)}" if meta.get("subtitle") else "")))
        elif state == "done" and note:
            blocks.append(("h", "Result"))
            blocks.append(("p", clean(note, cfg)))
    if prs_found:
        blocks.append(("h", "Pull request" + ("s" if len(prs_found) > 1 else "")))
        blocks.append(("links", [(clean(t, cfg) or "PR", u) for u, t in prs_found.items()]))
    if board_link:
        blocks.append(("links", [("Open the war table", board_link)]))
    elif tail_base(cfg):
        blocks.append(("links", [("Open the war table", war_link("/", cfg))]))
    else:
        blocks.append(("p", "Open the war table on your Mac."))
    return {"slug": slug, "state": state, "subject": f"guild: {slug} {subject}", "blocks": blocks,
            "board": board_id if token else "", "token": token, "ts": time.time()}


def render(items, token_item=None):
    """(text, html) for one or more items. The reply token goes last, in a line a reply quotes back."""
    text, page = [], []
    for n, item in enumerate(items):
        if n:
            text.append("\n" + "-" * 30 + "\n")
            page.append("<hr>")
        for kind, *a in item["blocks"]:
            if kind == "title":
                text.append(a[0] + "\n" + "=" * len(a[0]))
                page.append(f'<h2 style="margin:16px 0 6px">{html.escape(a[0])}</h2>')
            elif kind == "facts":
                text.append("\n".join(f"{k}: {v}" for k, v in a[0]))
                page.append('<p style="color:#555;margin:4px 0">' + "<br>".join(
                    f"<b>{html.escape(k)}:</b> {linkify(v)}" for k, v in a[0]) + "</p>")
            elif kind == "h":
                text.append("\n" + a[0].upper())
                page.append(f'<h3 style="margin:14px 0 4px">{html.escape(a[0])}</h3>')
            elif kind == "p":
                text.append(a[0])
                page.append(f'<p style="margin:4px 0;white-space:pre-wrap">{linkify(a[0])}</p>')
            elif kind == "opts":
                text.append("\n".join(f"  {i}) {label}" + (f": {why}" if why else "") + ("  <- recommended" if rec else "")
                                      for i, label, why, rec in a[0]))
                page.append('<ul style="padding-left:18px">' + "".join(
                    f'<li style="margin:6px 0"><b>{html.escape(i)}) {html.escape(label)}</b>'
                    + (" (recommended)" if rec else "") + (f"<br>{linkify(why)}" if why else "") + "</li>"
                    for i, label, why, rec in a[0]) + "</ul>")
            elif kind == "links":
                text.append("\n".join(f"{label}: {url}" for label, url in a[0]))
                page.append("<p>" + "<br>".join(
                    f'<a href="{html.escape(url, quote=True)}" style="display:inline-block;padding:6px 12px;background:#1a56db;'
                    f'color:#fff;border-radius:6px;text-decoration:none">{html.escape(label)}</a>' for label, url in a[0]) + "</p>")
    if token_item and token_item.get("token"):
        ref = f"guild-ref: {token_item['token']}"
        text.append("\n" + ref)
        page.append(f'<div style="display:none">{ref}</div><p style="color:#999;font-size:11px">{ref}</p>')
    return "\n\n".join(text), '<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:15px;max-width:640px">' + "".join(page) + "</div>"


def linkify(text):
    out = html.escape(text)
    return re.sub(r"(https?://[^\s<]+)", lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', out)


# ---- the queue: events close together share one email ---------------------------------------

class locked:
    def __enter__(self):
        os.makedirs(os.path.dirname(QUEUE), exist_ok=True)
        self.f = open(QUEUE + ".lock", "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def save_json(path, data):
    tmp = path + ".tmp"
    json.dump(data, open(tmp, "w"))
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def queue_add(item):
    """Add to the queue. Returns (first, stale): first when the queue was empty, stale when it is
    older than STALE (the process that should have sent it died)."""
    with locked():
        q = load_json(QUEUE, [])
        first = not q
        stale = bool(q) and (time.time() - q[0]["ts"] > STALE or bool(q[0].get("retry")))
        q.append(item)
        save_json(QUEUE, q)
    return first, stale


def flush():
    """Send what is queued: one email, except that each decision gets its own."""
    with locked():
        q = load_json(QUEUE, [])
        save_json(QUEUE, [])
    decisions = [i for i in q if i.get("token")]
    rest = [i for i in q if not i.get("token")]
    groups = ([[decisions[0]] + rest] + [[d] for d in decisions[1:]]) if decisions else ([rest] if rest else [])
    for group in groups:
        lead = next((i for i in group if i.get("token")), None)
        if len(group) == 1:
            subject = group[0]["subject"]
        else:
            slugs = list(dict.fromkeys(i["slug"] for i in group))
            subject = f"guild: {len(group)} updates ({', '.join(slugs[:3])}{', ...' if len(slugs) > 3 else ''})"
        if lead:
            subject += f" [guild {lead['board']} {lead['token']}]"
        text, page = render(group, lead)
        msgid = make_msgid(domain="guild.local")
        if lead:
            with locked():
                tokens = load_json(TOKENS, {})
                if lead["token"] in tokens:
                    tokens[lead["token"]]["msgid"] = msgid
                    save_json(TOKENS, tokens)
        why = send_email(subject, text, html_body=page, msgid=msgid)
        if why.startswith("email failed"):               # Gmail down: keep them, the next event sends them again
            with locked():
                again = [dict(i, retry=True) for i in group if time.time() - i["ts"] < 3600] + load_json(QUEUE, [])
                save_json(QUEUE, again)


def email_events_on(cfg=None):
    e = (cfg or config()).get("email") or {}
    return bool(e.get("to")) and e.get("events", True) is not False


def email_event(slug, state, note):
    cfg = config()
    if not email_events_on(cfg) or state not in EMAIL_STATES:
        return
    first, stale = queue_add(event_item(slug, state, note, cfg))
    if stale:
        flush()
    elif first:
        time.sleep(float((cfg.get("email") or {}).get("window", WINDOW)))
        flush()


# ---- sending -------------------------------------------------------------------------------

def email_password(sender):
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", "guild-email", "-a", sender, "-w"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def pr_context(url):
    """For a PR alert: the PR's title, so the mail says which PR without a click."""
    try:
        import prs
        title = (prs.cache().get(url) or {}).get("title", "")
        return f"PR title: {title}\n" if title else ""
    except Exception:
        return ""


def send_email(title, text, url="", html_body=None, msgid=None, to=None):
    """Send one email. Returns "" when sent, or why it was not."""
    cfg = config()
    e = cfg.get("email") or {}
    to, sender = to or e.get("to", ""), e.get("from") or e.get("to", "")
    if not to:
        return "no email set (guild notify email <address>)"
    password = email_password(sender)
    if not password:
        return f"no app password in the Keychain for {sender} (security add-generic-password -s guild-email -a {sender} -w)"
    link = safe_link(url, cfg)
    context = pr_context(url) if "/pull/" in url else ""
    if html_body is None:
        body = context + text + ("\n\n" + link if link else ("\n\nOpen the war table on your Mac." if url else ""))
        page = None
    else:
        body, page = text, html_body
    body = body.replace(password, "[removed]")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = title, sender, to
    if msgid:
        msg["Message-ID"] = msgid
    msg.set_content(body + "\n\n(guild alert)")
    if page:
        msg.add_alternative(page.replace(password, "[removed]"), subtype="html")
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
    if not os.environ.get("GUILD_NO_NOTIFY"):
        try:
            email_event(slug, state, note)
        except Exception:
            pass                          # an email that fails must never break the guild


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
              f" · alert email: {(cfg.get('email') or {}).get('to') or 'off'}"
              f"{'' if not cfg.get('email') else ' (quest events ' + ('on' if email_events_on(cfg) else 'off') + ')'}")
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
        elif args[1] == "events" and len(args) > 2 and args[2] in ("on", "off"):
            if not cfg.get("email"):
                raise SystemExit("set an email first: guild notify email <address>")
            cfg["email"]["events"] = args[2] == "on"
            print(f"quest events by email: {args[2]}")
        else:
            cfg["email"] = dict(cfg.get("email") or {}, to=args[1], **{"from": args[2] if len(args) > 2 else args[1]})
            print(f"alerts go to {args[1]}. Put a Gmail app password for {cfg['email']['from']} in the Keychain:\n"
                  f"  security add-generic-password -s guild-email -a {cfg['email']['from']} -w\n"
                  "then run `guild notify test`.")
        save(cfg)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
