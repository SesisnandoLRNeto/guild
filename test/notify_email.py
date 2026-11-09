"""Quest-event email checks for test/run.sh. Prints "ok <name>" or "FAIL <name>" per check.

Runs in the test GUILD_HOME and a fake HOME; SMTP, IMAP, the Keychain, GitHub and the clock are
stubbed, so no mail is ever sent and nothing waits 60 seconds.
"""
import json
import os
import sys
import time
from email.message import EmailMessage

REPO = sys.argv[1]
sys.path.insert(0, os.path.join(REPO, "bin"))
os.environ.pop("GUILD_NO_NOTIFY", None)
import mailreply  # noqa: E402
import notify     # noqa: E402
import prs        # noqa: E402
import wartable   # noqa: E402

HOME = os.environ["GUILD_HOME"]
os.makedirs(os.path.join(HOME, "local"), exist_ok=True)
REAL_TIME = time.time
KEY = "k3y-for-tests"
PR = "https://github.com/o/r/pull/7"


def check(name, cond):
    print(("ok " if cond else "FAIL ") + name)


def config(**kw):
    cfg = {"mac": False, "email": {"to": "me@example.com", "from": "me@example.com"}}
    cfg.update(kw)
    notify.save(cfg)


def remote_on():
    config(remote=True, bind="100.64.0.1", port=4712, key=KEY)


mails, sleeps = [], []


class SMTP:
    def __init__(self, host, port, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        pass

    def send_message(self, msg):
        mails.append(msg)


notify.smtplib.SMTP_SSL = SMTP
notify.email_password = lambda sender: "app-pass-9x"
notify.time.sleep = lambda s: sleeps.append(s)          # the burst window, without waiting
pushed = []
notify.send = lambda title, text, url="", email=False: pushed.append((title, text, url))


def plain(msg):
    return msg.get_body(preferencelist=("plain",)).get_content()


def page(msg):
    part = msg.get_body(preferencelist=("html",))
    return part.get_content() if part else ""


def board(quest, bid, title, questions=None, wrapup=False, subtitle="", created="2026-11-05T10:00:00"):
    d = os.path.join(HOME, "quests", quest, "boards", bid)
    os.makedirs(d, exist_ok=True)
    json.dump({"id": bid, "quest": quest, "title": title, "subtitle": subtitle, "wrapup": wrapup, "created": created},
              open(os.path.join(d, "board.json"), "w"))
    if questions:
        json.dump({"questions": questions}, open(os.path.join(d, "decisions.json"), "w"))
    return d


for quest in ("alpha", "beta", "gamma"):
    os.makedirs(os.path.join(HOME, "quests", quest), exist_ok=True)
    json.dump({"slug": quest, "repo": "/work/guild", "branch": f"quest/{quest}", "ticket": "SARA-12" if quest == "alpha" else ""},
              open(os.path.join(HOME, "quests", quest, "meta.json"), "w"))
json.dump({PR: {"slug": "alpha", "number": 7, "state": "open", "title": "Finance-only rate editing"}}, open(prs.CACHE, "w"))
QUESTION = {"id": "choice", "title": "How should the email let you act from a phone?",
            "detail": "Links point at 127.0.0.1, which only opens on this Mac.", "type": "single", "recommended": "c",
            "options": [{"id": "a", "label": "Tailscale only", "why": "almost no code"},
                        {"id": "b", "label": "Self-contained email", "why": "works anywhere, no network exposure"},
                        {"id": "c", "label": "Both", "why": "a now, b as well"}]}
board("alpha", "224416", "Phone alerts", [QUESTION])
NOTE = "war table ready: Phone alerts -> http://127.0.0.1:4711/b/alpha/224416/"

# a decision, remote on
remote_on()
notify.on_event("alpha", "needs-decision", NOTE)
m = mails[-1]
text, html = plain(m), page(m)
check("a decision emails once, after the burst window", len(mails) == 1 and sleeps == [60])
check("the subject names the quest and the state", m["Subject"].startswith("guild: alpha needs a decision"))
check("the body holds the question and its detail", QUESTION["title"] in text and "only opens on this Mac" in text)
check("it lists every option with its trade-off",
      all(o["label"] in text and o["why"] in text for o in QUESTION["options"]))
check("it names the recommended option", "Recommended: c (Both)" in text)
check("it names the quest, the ticket and the branch", "Quest: alpha" in text and "SARA-12" in text and "quest/alpha" in text)
check("the mail has an HTML body with the options as a list", "<li" in html and "Tailscale only" in html and "recommended" in html)
check("remote on: the link is the tailnet address with its key, on the board",
      f"http://100.64.0.1:4712/b/alpha/224416/?k={KEY}" in text and f"?k={KEY}" in html)
check("remote on: no 127.0.0.1 link anywhere", "://127.0.0.1" not in text and "://127.0.0.1" not in html)
token = next(iter(notify.load_json(notify.TOKENS, {})), "")
check("the decision carries its secret token, in the subject and in the body",
      token and f"[guild 224416 {token}]" in m["Subject"] and f"guild-ref: {token}" in text)
check("the Keychain password is not in the mail", "app-pass-9x" not in text and "app-pass-9x" not in html)
check("Mac and ntfy still get the same short line at once", pushed[-1][:2] == ("guild: alpha", "alpha a decision waits for you")
      and pushed[-1][2].endswith(f"?k={KEY}"))

# remote off
config()
mails.clear()
notify.on_event("alpha", "needs-decision", NOTE)
m = mails[-1]
text, html = plain(m), page(m)
check("remote off: the mail says to open the war table on the Mac", "Open the war table on your Mac" in text)
check("remote off: no war table link, no key, no 127.0.0.1",
      "http" not in text.replace("https://github", "") and "k=" not in text and "://127.0.0.1" not in html and "?k=" not in html)
check("remote off: the question and options are still all there", QUESTION["title"] in text and "Both" in text)

# blocked and failed: the full note, never cut, with the PR link; no secrets
remote_on()
mails.clear()
long_note = ("tests fail on the CI runner. " * 25 + f"see {PR} and http://127.0.0.1:4711/b/alpha/9/ "
             "token: ghp_abcdefghijklmnopqrstuvwxyz0123456789 password=hunter2hunter2 "
             f"Authorization: Bearer abcdefghijklmnop12345678 key {KEY} END-OF-NOTE")
notify.on_event("alpha", "blocked", long_note)
m = mails[-1]
text = plain(m)
check("a blocked mail holds the whole note", "END-OF-NOTE" in text and text.count("tests fail on the CI runner.") == 25)
check("and the PR link and its title", PR in text and "Finance-only rate editing" in text)
check("and the repo and branch", "Repo: guild" in text and "Branch: quest/alpha" in text)
check("a token, a password and a bearer value are cut out",
      "ghp_" not in text and "hunter2" not in text and "abcdefghijklmnop12345678" not in text)
check("the war table key stays out of the text of a note", "key [removed]" in text and f"key {KEY}" not in text)
check("a 127.0.0.1 link in a note is turned into the tailnet one", "127.0.0.1" not in text and "http://100.64.0.1:4712/b/alpha/9/" in text)
mails.clear()
notify.on_event("beta", "failed", "the build broke")
check("a failed mail says so in the subject", mails[-1]["Subject"] == "guild: beta failed" and "the build broke" in plain(mails[-1]))

# done and wrap-up: the PR links and the wrap-up title and summary
board("alpha", "wrap1", "Phone alerts shipped", wrapup=True, subtitle="Quest events reach you by email")
mails.clear()
notify.on_event("alpha", "done", "https://github.com/o/r/pull/9")
text = plain(mails[-1])
check("a done mail has the PR links, the wrap-up title and its summary",
      PR in text and "https://github.com/o/r/pull/9" in text and "Phone alerts shipped" in text and "reach you by email" in text)

# a burst: three events within 30 seconds are one email
clock = [1000.0]
notify.time.time = lambda: clock[0]
mails.clear()


def during_the_window(seconds):
    clock[0] += 30
    notify.on_event("beta", "failed", "second event")
    notify.on_event("gamma", "blocked", "third event")


notify.time.sleep = during_the_window
notify.on_event("alpha", "blocked", "first event")
text = plain(mails[-1]) if mails else ""
check("three events in 30 seconds give one email", len(mails) == 1)
check("which lists all three", all(w in text for w in ("first event", "second event", "third event")))
check("and says how many in the subject", mails[-1]["Subject"].startswith("guild: 3 updates (alpha, beta, gamma)"))

# two decisions in one burst: each gets its own mail, so a reply names one question
board("beta", "b2", "Pick a colour", [dict(QUESTION, title="Which colour?")])
mails.clear()


def two_decisions(seconds):
    notify.on_event("beta", "needs-decision", "war table ready: Pick a colour -> http://127.0.0.1:4711/b/beta/b2/")
    notify.on_event("gamma", "blocked", "a block")


notify.time.sleep = two_decisions
notify.on_event("alpha", "needs-decision", NOTE)
subjects = [m["Subject"] for m in mails]
check("two decisions in a burst are two mails, one token each", len(mails) == 2 and sum("[guild " in s for s in subjects) == 2
      and len({s.split("[guild ")[1] for s in subjects}) == 2)
check("the other event rides with the first decision", "a block" in plain(mails[0]) and "a block" not in plain(mails[1]))

# a queue whose sender died is sent by the next event
notify.time.sleep = lambda s: None
mails.clear()
notify.save_json(notify.QUEUE, [notify.event_item("beta", "failed", "stuck one")])
clock[0] += 200
notify.on_event("gamma", "failed", "fresh one")
check("a stale queue is flushed by the next event, in one email", len(mails) == 1 and "stuck one" in plain(mails[0])
      and "fresh one" in plain(mails[0]))
notify.time.time = REAL_TIME

# settings
mails.clear()
config(email={"to": "me@example.com", "from": "me@example.com", "events": False})
notify.on_event("alpha", "blocked", "no mail for this")
check("events false turns quest-event email off", mails == [])
check("but Mac and ntfy still hear it", pushed[-1][1] == "alpha is blocked")
config(email={"to": "me@example.com", "from": "me@example.com"})
notify.on_event("alpha", "working", "just working")
notify.on_event("alpha", "graded", "graded")
check("states that need nothing from you send nothing", mails == [])
os.environ["GUILD_NO_NOTIFY"] = "1"
notify.on_event("alpha", "blocked", "silenced")
del os.environ["GUILD_NO_NOTIFY"]
check("GUILD_NO_NOTIFY silences the mail too", mails == [])

# PR alerts: the title and the GitHub URL; and the key only ever in the tailnet address
remote_on()
notify.send_email("guild: alpha", "alpha: PR #7 has a merge conflict", PR)
text = plain(mails[-1])
check("a PR alert carries the PR title and its GitHub URL", "PR title: Finance-only rate editing" in text and PR in text)
notify.send_email("guild: usage", "Claude usage at 86%", f"http://100.64.0.1:4712/?k={KEY}")
check("an alert keeps the tailnet link with its key", f"http://100.64.0.1:4712/?k={KEY}" in plain(mails[-1]))
notify.send_email("guild: x", "y", f"http://evil.example:4712/?k={KEY}")
check("the key never goes into a link that is not the tailnet address", KEY not in plain(mails[-1]))
config()
notify.send_email("guild: usage", "Claude usage at 86%", "http://127.0.0.1:4711/")
text = plain(mails[-1])
check("an alert with remote off says to open it on the Mac, with no 127.0.0.1 link", "on your Mac" in text and "127.0.0.1" not in text)

# ---- replies --------------------------------------------------------------------------------
config()
inbox, seen, touched = [], set(), []


class IMAP:
    def __init__(self, host, port):
        touched.append(("connect", host, port))

    def login(self, user, password):
        touched.append(("login", user))

    def select(self, box):
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        touched.append(("search",) + criteria)
        return "OK", [b" ".join(str(i).encode() for i, _ in enumerate(inbox, 1) if i not in seen)]

    def fetch(self, num, what):
        return "OK", [(b"1 (RFC822)", inbox[int(num) - 1]), b")"]

    def store(self, num, how, flag):
        seen.add(int(num))
        return "OK", []

    def logout(self):
        pass

    def __getattr__(self, name):               # expunge, delete, copy: the code must never call them
        raise AssertionError("mailreply must never delete mail: " + name)


mailreply.imaplib.IMAP4_SSL = IMAP


def decision_mail(bid="224416", quest="alpha", note=NOTE):
    """Send a decision mail and return (token, Message-ID) the way a phone would see them."""
    mails.clear()
    notify.on_event(quest, "needs-decision", note.replace("224416", bid).replace("alpha", quest))
    tok = [t for t, i in notify.load_json(notify.TOKENS, {}).items() if i["board"] == bid and i["quest"] == quest][-1]
    return tok, mails[-1]["Message-ID"], mails[-1]["Subject"]


def reply(token, msgid, subject, body, sender="me@example.com", quote=True, ref=True):
    r = EmailMessage()
    r["From"], r["To"], r["Subject"], r["In-Reply-To"] = sender, "me@example.com", "Re: " + subject, msgid
    quoted = "\n\nOn Thu, 5 Nov 2026 at 22:00, guild <me@example.com> wrote:\n> Question: How should the email...\n> a) Tailscale only\n" \
             + (f"> guild-ref: {token}\n" if ref else "")
    r.set_content(body + (quoted if quote else ""))
    return r.as_bytes()


def answered(bid="224416", quest="alpha"):
    return notify.load_json(os.path.join(HOME, "quests", quest, "boards", bid, "decision.json"), None)


events = lambda: open(os.path.join(HOME, "events.log")).read() if os.path.exists(os.path.join(HOME, "events.log")) else ""
tok, mid, subj = decision_mail()

inbox[:] = [reply(tok, mid, subj, "b")]
mails.clear()
out = mailreply.poll(wartable.answer_board)
d = answered()
check("a valid reply answers the board like a click", d and d["answers"] == {"choice": "b"} and out == ["answered: b"])
check("it is marked seen and nothing is deleted", seen == {1} and ("search", "UNSEEN", "SUBJECT", '"[guild "') in touched)
check("a short got-it mail comes back", len(mails) == 1 and mails[0]["Subject"] == "guild: alpha got it"
      and "you chose b (Self-contained email)" in plain(mails[0]))
check("the token is spent", tok not in notify.load_json(notify.TOKENS, {}))
check("the war table event for the answer is written", "war table answered (Phone alerts): choice=b" in events())

# the same reply again: the board is answered already
tok2, mid2, subj2 = decision_mail()           # a second mail for the board, answered on the war table already
inbox[:] = [reply(tok2, mid2, subj2, "a")]
seen.clear()
mails.clear()
out = mailreply.poll(wartable.answer_board)
check("a reply to a board answered already gets a short mail back, and changes nothing",
      out == ["already answered"] and answered()["answers"] == {"choice": "b"} and "already answered" in mails[-1]["Subject"])

# ignored replies: no token, another address, the original itself
os.remove(os.path.join(HOME, "quests", "alpha", "boards", "224416", "decision.json"))
tok, mid, subj = decision_mail()
inbox[:] = []
seen.clear()
inbox.append(reply(tok, mid, subj, "b", ref=False))
mails.clear()
out = mailreply.poll(wartable.answer_board)
check("a reply without the token is ignored and logged", out == ["ignored: no token"] and answered() is None and mails == []
      and "ignored a reply without its token" in events())
inbox[:] = [reply(tok, mid, subj, "b", sender="stranger@example.org")]
seen.clear()
out = mailreply.poll(wartable.answer_board)
check("a reply from another address is ignored and logged", out == ["ignored: other address"] and answered() is None
      and "another address (stranger@example.org)" in events())
orig = EmailMessage()
orig["From"], orig["To"], orig["Subject"] = "me@example.com", "me@example.com", subj
orig.set_content(f"the question\n\nguild-ref: {tok}")
inbox[:] = [orig.as_bytes()]
seen.clear()
out = mailreply.poll(wartable.answer_board)
check("the mail guild sent, seen in a shared inbox, is not taken for a reply", out == ["ignored: not a reply"] and answered() is None)

# quoted history is cut; free text is kept as the answer
inbox[:] = [reply(tok, mid, subj, "c: both, but start with the email\nthanks")]
seen.clear()
out = mailreply.poll(wartable.answer_board)
d = answered()
check("quoted history is cut: the option comes from the new text only", d and d["answers"] == {"choice": "c"})
check("the words after the option letter become the note", d and "start with the email" in d["message"] and "Tailscale" not in d["message"])
os.remove(os.path.join(HOME, "quests", "alpha", "boards", "224416", "decision.json"))
tok, mid, subj = decision_mail()
inbox[:] = [reply(tok, mid, subj, "Do the email first, Tailscale later.")]
seen.clear()
mails.clear()
out = mailreply.poll(wartable.answer_board)
d = answered()
check("free text is recorded as the message, with no option picked", out == ["answered: free text"] and d
      and d["answers"] == {} and d["message"] == "Do the email first, Tailscale later.")
check("and the got-it mail says it was recorded", "your answer is recorded" in plain(mails[-1]))

# a board with several questions is not answered by reply
board("gamma", "g1", "Two things", [QUESTION, dict(QUESTION, id="second")])
tok, mid, subj = decision_mail("g1", "gamma", "war table ready: Two things -> http://127.0.0.1:4711/b/gamma/g1/")
inbox[:] = [reply(tok, mid, subj, "a")]
seen.clear()
mails.clear()
out = mailreply.poll(wartable.answer_board)
check("a board with several questions gets a note to use the war table", out == ["several questions"] and answered("g1", "gamma") is None
      and "several questions" in plain(mails[-1]))

# a budget (or lesson, or why) board is never answered by a stray word
d = board("gamma", "bud", "Budget reached", [dict(QUESTION, id="choice", options=[{"id": "stop", "label": "Stop"}, {"id": "raise50", "label": "Raise"}])])
meta = notify.load_json(os.path.join(d, "board.json"), {}); meta["kind"] = "budget"; json.dump(meta, open(os.path.join(d, "board.json"), "w"))
tok, mid, subj = decision_mail("bud", "gamma", "war table ready: Budget reached -> http://127.0.0.1:4711/b/gamma/bud/")
check("a budget board's mail does not invite a reply", "Answer by replying" not in plain(mails[-1]))
inbox[:] = [reply(tok, mid, subj, "thanks, will do")]
seen.clear()
mails.clear()
out = mailreply.poll(wartable.answer_board)
check("a stray word does not answer a budget board (it would stop the quest)", out == ["several questions"] and answered("bud", "gamma") is None)

# a stranger's mail with a guild subject stays unread, and is logged once
inbox[:] = [reply(tok, mid, subj, "hi", sender="stranger@example.org")]
seen.clear()
before = events().count("another address (stranger@example.org)")
mailreply.poll(wartable.answer_board)
mailreply.poll(wartable.answer_board)
check("a stranger's mail is left unread", seen == set())
check("and logged once, not every poll", events().count("another address (stranger@example.org)") == before + 1)

# a send that fails is kept for the next event
tok, mid, subj = decision_mail()
class Down2(SMTP):
    def send_message(self, msg):
        raise OSError("smtp down")
notify.smtplib.SMTP_SSL = Down2
mails.clear()
notify.on_event("beta", "failed", "lost?")
kept = notify.load_json(notify.QUEUE, [])
check("a failed send keeps the event queued", len(kept) == 1 and kept[0]["slug"] == "beta")
notify.smtplib.SMTP_SSL = SMTP
notify.on_event("gamma", "failed", "after the outage")
check("and the next event sends both", len(mails) >= 1 and "lost?" in plain(mails[-1]) and "after the outage" in plain(mails[-1]))

# IMAP trouble never raises, and no tokens means no login
tok, mid, subj = decision_mail()


class Down(IMAP):
    def login(self, user, password):
        raise OSError("imap off")


mailreply.imaplib.IMAP4_SSL = Down
try:
    out = mailreply.poll(wartable.answer_board)
    check("an IMAP error is logged once and never raised", out == [] and "could not read replies" in events())
except Exception as err:
    check("an IMAP error is logged once and never raised: " + repr(err), False)
mailreply.imaplib.IMAP4_SSL = IMAP
notify.save_json(notify.TOKENS, {})
touched.clear()
mailreply.poll(wartable.answer_board)
check("with no decision waiting, guild does not even log in", touched == [])
config(email={"to": "me@example.com", "from": "me@example.com", "events": False})
notify.save_json(notify.TOKENS, {"x": {"quest": "alpha", "board": "224416", "created": time.time()}})
mailreply.poll(wartable.answer_board)
check("events off also stops reading replies", touched == [])
config()
