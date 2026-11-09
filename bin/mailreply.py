#!/usr/bin/env python3
"""Answer a war table decision by replying to its email.

  mailreply.py poll      read the replies once (the war table does this every 2 minutes)

Every decision email carries a secret token twice: in the subject, as "[guild <board> <token>]",
and in a line at the end of the body ("guild-ref: <token>"). A reply counts only when
  - it is from the "to" address of the email setting (a From line can be faked, so also)
  - it carries a token guild sent, in the subject and in the body, and both agree
  - it answers that mail (In-Reply-To names it, or the subject starts with Re:)
Anything else is left alone and logged to events.log. The reply's first line is the answer:
"b" or "b: a few words" picks option b; any other text is a free-text answer. Quoted history is
cut before reading. Replies are read over IMAP (Gmail needs IMAP on in its settings), only the
unseen ones that name a guild mail; each is marked seen and nothing is ever deleted.
After a reply is recorded guild mails "got it"; a reply to a board answered already gets a note.
"""
import datetime
import email
import imaplib
import json
import os
import re
import sys
import time
from email.header import decode_header, make_header
from email.utils import parseaddr

BIN = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, BIN)
import notify  # noqa: E402

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
EVENTS = os.path.join(GUILD_HOME, "events.log")
KEEP_DAYS = 14                   # a token nobody used in two weeks is dropped
TAG = re.compile(r"\[guild\s+(\S+)\s+([A-Za-z0-9_-]+)\]")
REF = re.compile(r"guild-ref:\s*([A-Za-z0-9_-]+)")
LAST_ERROR = [""]
IGNORED = set()


def log(quest, note, quiet=False):
    if quiet:
        return
    with open(EVENTS, "a") as f:
        f.write(f"{datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\t{quest or 'mail'}\temail-reply\t{note}\n")


def text_of(msg):
    """The plain text of a message (the HTML with its tags cut when there is no plain part)."""
    plain, rich = [], []
    for part in msg.walk():
        kind = part.get_content_type()
        if kind not in ("text/plain", "text/html"):
            continue
        raw = part.get_payload(decode=True)
        if raw is None:
            continue
        text = raw.decode(part.get_content_charset() or "utf-8", "replace")
        (plain if kind == "text/plain" else rich).append(text)
    if plain:
        return "\n".join(plain)
    return re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>|</p>|</div>", "\n", "\n".join(rich)))


def strip_quoted(text):
    """What the person wrote, without the mail they answered."""
    lines = text.replace("\r\n", "\n").split("\n")
    out = []
    for n, line in enumerate(lines):
        s = line.strip()
        if s.startswith(">"):
            continue
        if re.match(r"^On .+(wrote|said):?$", s) or (re.match(r"^On .+", s) and n + 1 < len(lines)
                                                     and re.match(r"^.*wrote:$", lines[n + 1].strip())):
            break
        if re.match(r"^-{2,}\s*(Original Message|Forwarded)", s, re.I) or re.match(r"^_{5,}$", s) \
                or re.match(r"^(From|De):\s", s) or s == "--":
            break
        out.append(line)
    return "\n".join(out).strip()


def parse_answer(text, question):
    """({question id: option id}, message). An option letter first, or the whole text as free text."""
    options = {str(o.get("id", "")).lower(): o for o in question.get("options") or []}
    lines = [l for l in text.splitlines() if l.strip()]
    first = lines[0].strip() if lines else ""
    m = re.match(r"^([A-Za-z0-9_-]+)\s*(?:[:.,)-]\s*(.*))?$", first)
    if m and m.group(1).lower() in options:
        pick = options[m.group(1).lower()]["id"]
        message = "\n".join(filter(None, [(m.group(2) or "").strip()] + [l.strip() for l in lines[1:]]))
        return {question.get("id", "choice"): pick}, message
    return {}, text.strip()[:4000]


def forget(tokens, token):
    with notify.locked():
        current = notify.load_json(notify.TOKENS, {})
        current.pop(token, None)
        notify.save_json(notify.TOKENS, current)
    tokens.pop(token, None)


def handle(msg, tokens, to, answer_board, quiet=False):
    """Act on one message. Returns what was done, in a few words."""
    sender = parseaddr(msg.get("From", ""))[1].lower()
    if sender != to.lower():
        log("", f"ignored a reply from another address ({sender or 'none'})", quiet)
        return "ignored: other address"
    subject = str(make_header(decode_header(msg.get("Subject", ""))))
    body = text_of(msg)
    tag, ref = TAG.search(subject), REF.search(body)
    if not tag or not ref or tag.group(2) != ref.group(1):
        log("", "ignored a reply without its token", quiet)
        return "ignored: no token"
    info = tokens.get(tag.group(2))
    if not info or info.get("board") != tag.group(1):
        log("", "ignored a reply with a token guild did not send", quiet)
        return "ignored: unknown token"
    quest, board = info["quest"], info["board"]
    answers_to = msg.get("In-Reply-To", "").strip()
    if not (subject.lower().lstrip().startswith("re:") or (info.get("msgid") and answers_to == info["msgid"])):
        return "ignored: not a reply"            # the original mail itself, seen in a shared inbox
    bdir = os.path.join(QUESTS, quest, "boards", board)
    decisions = notify.load_json(os.path.join(bdir, "decisions.json"), {})
    questions = decisions.get("questions", [])
    if os.path.exists(os.path.join(bdir, "decision.json")):
        notify.send_email(f"guild: {quest} already answered",
                          f"The question on {quest} ({board}) was already answered on the war table.\nYour reply was not used.")
        forget(tokens, tag.group(2))
        log(quest, f"reply to {board}: already answered")
        return "already answered"
    kind = notify.load_json(os.path.join(bdir, "board.json"), {}).get("kind")
    if len(questions) != 1 or kind:               # budget, lesson, why: a stray word must not stop a quest
        notify.send_email(f"guild: {quest} needs the war table",
                          f"This board has several questions, so it cannot be answered by reply. Open the war table on your Mac"
                          f"{' or at ' + notify.war_link('/b/%s/%s/' % (quest, board)) if notify.tail_base() else ''}.")
        forget(tokens, tag.group(2))
        log(quest, f"reply to {board}: several questions, not answered")
        return "several questions"
    if decisions.get("review"):                   # a plan approved point by point: a letter cannot mark the points
        notify.send_email(f"guild: {quest} needs the plan page",
                          "This plan is approved point by point, so a reply cannot approve it. Open the plan"
                          f"{' at ' + notify.war_link('/b/%s/%s/' % (quest, board)) if notify.tail_base() else ' on your Mac'}"
                          " and mark each point.")
        forget(tokens, tag.group(2))
        log(quest, f"reply to {board}: a point-by-point plan, not answered")
        return "plan needs marks"
    question = questions[0]
    answers, message = parse_answer(strip_quoted(body), question)
    if not answers and not message:
        log(quest, f"reply to {board}: empty")
        return "ignored: empty"
    answer_board(quest, board, {"answers": answers, "message": message})
    forget(tokens, tag.group(2))
    pick = next(iter(answers.values()), "")
    label = next((o.get("label", "") for o in question.get("options") or [] if o.get("id") == pick), "")
    said = f"you chose {pick}" + (f" ({label})" if label else "") if pick else "your answer is recorded"
    notify.send_email(f"guild: {quest} got it", f"Got it: {said}." + (f"\nYour note: {message}" if message and pick else "")
                      + f"\n{quest} picks it up now.")
    log(quest, f"answered {board} by email: {pick or 'free text'}")
    return f"answered: {pick or 'free text'}"


def poll(answer_board):
    """Read the unseen replies once. Never raises: a mail problem must not stop the war table."""
    cfg = notify.config()
    e = cfg.get("email") or {}
    if not notify.email_events_on(cfg):
        return []
    tokens = notify.load_json(notify.TOKENS, {})
    def stale(i):
        age = time.time() - float(i.get("created") or 0)
        answered = os.path.exists(os.path.join(QUESTS, i.get("quest", ""), "boards", i.get("board", ""), "decision.json"))
        return age > KEEP_DAYS * 86400 or (answered and age > 86400)     # a day to reply "already answered"
    old = [t for t, i in tokens.items() if stale(i)]
    for t in old:
        forget(tokens, t)
    if not tokens:
        return []                                # nothing is waiting for a reply: do not even log in
    sender = e.get("from") or e.get("to", "")
    password = notify.email_password(sender)
    if not password:
        return []
    done = []
    try:
        imap = imaplib.IMAP4_SSL(e.get("imap_host", "imap.gmail.com"), int(e.get("imap_port", 993)))
        try:
            imap.login(sender, password)
            imap.select("INBOX")
            status, found = imap.search(None, "UNSEEN", "SUBJECT", '"[guild "')
            for num in (found[0].split() if status == "OK" and found and found[0] else []):
                status, data = imap.fetch(num, "(BODY.PEEK[])")
                if status != "OK" or not data or not isinstance(data[0], tuple):
                    continue
                raw = data[0][1][:300_000]               # no reply is that long
                try:
                    key = hash(raw)
                    result = handle(email.message_from_bytes(raw), tokens, e["to"], answer_board, quiet=key in IGNORED)
                    if result.startswith("ignored"):
                        IGNORED.add(key)                 # not ours to mark read, and not worth logging twice
                    else:
                        imap.store(num, "+FLAGS", "\\Seen")
                    done.append(result)
                except Exception as err:         # one bad reply must not hide the next
                    log("", f"a reply could not be read: {type(err).__name__}")
        finally:
            try:
                imap.logout()
            except Exception:
                pass
    except (OSError, imaplib.IMAP4.error) as err:
        if str(err) != LAST_ERROR[0]:              # say it once, not every 2 minutes
            LAST_ERROR[0] = str(err)
            log("", f"could not read replies: {type(err).__name__} (is IMAP on in Gmail settings?)")
    return done


if __name__ == "__main__":
    if sys.argv[1:] == ["poll"]:
        import wartable
        print("\n".join(poll(wartable.answer_board)) or "nothing to read")
    else:
        raise SystemExit(__doc__)
