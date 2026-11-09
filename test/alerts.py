"""Alert and compaction checks for test/run.sh. Prints "ok <name>" or "FAIL <name>" per check.

Runs in the test GUILD_HOME and a fake HOME; GitHub, tmux, the Keychain and SMTP are stubbed.
"""
import datetime
import json
import os
import sys
import time

REPO = sys.argv[1]
sys.path.insert(0, os.path.join(REPO, "bin"))
os.environ.pop("GUILD_NO_NOTIFY", None)
import alerts   # noqa: E402
import notify   # noqa: E402
import prs      # noqa: E402

HOME = os.environ["GUILD_HOME"]
os.makedirs(os.path.join(HOME, "local"), exist_ok=True)


def check(name, cond):
    print(("ok " if cond else "FAIL ") + name)


def utc(hours_ago):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


sent = []
notify.send = lambda title, text, url="", email=False: sent.append((text, email))
mailed, now_mailed = [], []
real_send_email, real_email_now = notify.send_email, notify.email_now
notify.send_email = lambda title, text, url="", **kw: mailed.append(text) or ""
notify.email_now = lambda slug, state, note: now_mailed.append((slug, state, note)) or ""
for f in (alerts.STATE, alerts.USAGE):
    if os.path.exists(f):
        os.remove(f)

# PR follow-ups
pr, merged = "https://github.com/o/r/pull/7", "https://github.com/o/r/pull/8"
json.dump({pr: {"slug": "alpha", "number": 7, "state": "open", "checks": "failing", "conflict": True,
                "waiting_since": utc(30)},
           merged: {"slug": "beta", "number": 8, "state": "merged", "checks": "failing", "conflict": True},
           "https://github.com/o/r/pull/9": {"slug": "gamma", "number": 9, "state": "merged", "merged_at": utc(2)},
           "https://github.com/o/r/pull/10": {"slug": "delta", "number": 10, "state": "open", "review": "changes requested"}},
          open(prs.CACHE, "w"))
texts = [p["text"] for p in alerts.check()]
check("a conflict on an open PR is an alert", any("merge conflict" in t for t in texts))
check("failing checks are an alert", any("failing checks" in t for t in texts))
check("a reviewer waiting a day is an alert", any("waited 30h" in t for t in texts))
check("an old merge (no time known) raises nothing", not any("#8" in t for t in texts))
check("a PR merged today is mailed", any("PR #9 was merged" in t for t in mailed))
check("a review asking for changes is mailed", any("PR #10: a reviewer requested changes" in t for t in mailed))
check("conflicts, failing checks and a waiting reviewer are not mailed", len(mailed) == 2)
check("each alert reaches the Mac once", len(sent) == 5 and not any(e for _, e in sent))
check("a merge is not a docket alert", "#9" not in str([a for a in alerts.current() if a.get("docket", True)]))
alerts.check()
check("a second check sends nothing new", len(sent) == 5 and len(mailed) == 2)
c = prs.cache(); [c.pop(u) for u in ("https://github.com/o/r/pull/9", "https://github.com/o/r/pull/10")]; json.dump(c, open(prs.CACHE, "w"))
sent.clear(); sent.extend([("x", False)] * 3)
c = prs.cache(); c[pr]["conflict"] = False; json.dump(c, open(prs.CACHE, "w"))
alerts.check()
c[pr]["conflict"] = True; json.dump(c, open(prs.CACHE, "w"))
alerts.check()
check("a conflict that comes back is sent again", len(sent) == 4)
c[pr]["waiting_since"] = utc(3); json.dump(c, open(prs.CACHE, "w"))
check("a reviewer waiting 3h is not an alert yet", not any("waited" in p["text"] for p in alerts.current()))
check("waiting_since ignores bots and sees your answer",
      prs.waiting_since({"author": {"login": "me"}, "reviews": [{"author": {"login": "bob"}, "submittedAt": "2026-01-01T10:00:00Z"}],
                         "comments": [{"author": {"login": "me"}, "createdAt": "2026-01-01T11:00:00Z"},
                                      {"author": {"login": "ci[bot]"}, "createdAt": "2026-01-01T12:00:00Z"}]}) == "")
check("github-actions counts as a bot though gh drops [bot]",
      prs.waiting_since({"author": {"login": "me"}, "comments": [{"author": {"login": "github-actions"}, "createdAt": "2026-01-01T10:00:00Z"}]}) == "")
check("a plain approval waits for no answer",
      prs.waiting_since({"author": {"login": "me"}, "reviews": [{"author": {"login": "bob"}, "state": "APPROVED", "body": "", "submittedAt": "2026-01-01T10:00:00Z"}]}) == "")
check("a review with questions does",
      prs.waiting_since({"author": {"login": "me"}, "reviews": [{"author": {"login": "bob"}, "state": "COMMENTED", "body": "why?", "submittedAt": "2026-01-01T10:00:00Z"}]}) == "2026-01-01T10:00:00Z")
json.dump({}, open(prs.CACHE, "w"))

# Claude usage
json.dump({"rate_limits": {"five_hour": {"used_percentage": 86, "resets_at": time.time() + 3600},
                           "seven_day": {"used_percentage": 40}}, "at": time.time()}, open(alerts.USAGE, "w"))
texts = [p["text"] for p in alerts.current()]
check("usage over 80% of the 5-hour limit is an alert", any("86% of the 5-hour" in t for t in texts))
check("usage at 40% of the week is quiet", not any("weekly" in t for t in texts))
json.dump({"rate_limits": {"five_hour": {"used_percentage": 95}}, "at": time.time() - 7 * 3600}, open(alerts.USAGE, "w"))
check("an old usage reading says nothing", alerts.current() == [])
os.remove(alerts.USAGE)

# a question waiting too long
old = (datetime.datetime.now() - datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
items = [{"quest": "alpha", "board": "b1", "title": "Which way?", "created": old},
         {"quest": "alpha", "board": "wrap", "title": "Wrap-up", "created": old, "wrapup": True}]
texts = [p["text"] for p in alerts.current(items)]
check("a board waiting 3h is an alert", any("waited 3h on your answer: Which way?" in t for t in texts))
check("results waiting 3h are one too", any("alpha: results have waited 3h for your check" in t for t in texts))
fresh = (datetime.datetime.now() - datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
check("a board waiting 30 minutes is not mailed yet", alerts.current([{"quest": "alpha", "board": "b2", "title": "Soon", "created": fresh}]) == [])
alerts.check(items)
check("after an hour the plan or question is mailed in full, with its board",
      ("alpha", "needs-decision", "war table ready: Which way? -> /b/alpha/b1/") in now_mailed)
check("and the results too", any(m[:2] == ("alpha", "wrapup") for m in now_mailed))
# a quest blocked for an hour
bq = os.path.join(HOME, "quests", "stuck")
os.makedirs(bq, exist_ok=True)
json.dump({"slug": "stuck"}, open(os.path.join(bq, "meta.json"), "w"))
open(os.path.join(bq, "status"), "w").write("blocked\tneeds the staging password\t2026-01-01T00:00:00\n")
check("a quest blocked for ten minutes waits", not any("stuck" in p["text"] for p in alerts.current()))
two_h = time.time() - 7200
os.utime(os.path.join(bq, "status"), (two_h, two_h))
alerts.check()
check("blocked for two hours is mailed, with what it needs", any(m[0] == "stuck" and m[1] == "blocked"
                                                                 and "staging password" in m[2] for m in now_mailed))
import shutil; shutil.rmtree(bq)

# compaction
wt = os.path.join(HOME, "wt-compact")
qdir = os.path.join(HOME, "quests", "compactme")
os.makedirs(qdir, exist_ok=True)
json.dump({"slug": "compactme", "worktree": wt}, open(os.path.join(qdir, "meta.json"), "w"))
open(os.path.join(qdir, "status"), "w").write("needs-decision\tpicked a board\t2026-01-01T00:00:00\n")
logdir = os.path.join(alerts.PROJECTS, wt.replace("/", "-").replace(".", "-"))
os.makedirs(logdir, exist_ok=True)


def session(minutes_ago, tokens, stop="end_turn", uuid="t1"):
    stamp = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_ago)).isoformat()
    rows = [{"type": "user", "timestamp": stamp, "message": {"role": "user"}},
            {"type": "assistant", "timestamp": stamp, "uuid": uuid,
             "message": {"stop_reason": stop, "usage": {"input_tokens": 10, "cache_read_input_tokens": tokens}}},
            {"type": "system", "subtype": "turn_duration", "timestamp": stamp}]
    with open(os.path.join(logdir, "s.jsonl"), "w") as f:
        f.write("\n".join(json.dumps(r) for r in rows) + "\n")


cfg = notify.config(); cfg["alerts"] = {"cache_minutes": 5}; notify.save(cfg)   # the window is 3.5 to 4.75 min
typed = []
alerts.tab_open = lambda slug: True


class Run:
    def __init__(self, out=""):
        self.stdout, self.returncode = out, 0


def fake_run(cmd, **kw):
    if "list-panes" in cmd:
        return Run("%3 1\n%11 \n")
    if "send-keys" in cmd:
        typed.append((cmd[cmd.index("-t") + 1], cmd[-1]))
    return Run()


alerts.subprocess.run = fake_run
session(4, 150_000)
check("an idle session reads its idle minutes and context", alerts.idle_session(wt)[1] == 150_010)
session(4, 150_000, stop="tool_use")
check("a session mid-turn is not idle", alerts.idle_session(wt) is None)
session(1, 150_000)
check("a quest idle for one minute is left alone", alerts.compact_idle() == [])
session(4, 20_000)
check("a small context is left alone", alerts.compact_idle() == [])
session(4, 150_000)
check("a big idle quest is compacted before the cache goes cold", alerts.compact_idle() == ["compactme"])
check("/compact goes to the content pane, not the side menu", ("%11", "/compact") in typed)
check("the same idle stretch is compacted once", alerts.compact_idle() == [])
session(4, 150_000, uuid="t2")
open(os.path.join(qdir, "status"), "w").write("done\tfinished\t2026-01-01T00:00:00\n")
check("a done quest is never compacted", alerts.compact_idle() == [])
check("the compaction is in the events", "compacted" in open(os.path.join(HOME, "events.log")).read())

# email
notify.send_email, notify.email_now = real_send_email, real_email_now
cfg = notify.config()
cfg.pop("email", None); notify.save(cfg)
check("no email set says how to set it", "guild notify email" in notify.send_email("t", "x"))
cfg["email"] = {"to": "me@example.com", "from": "me@example.com"}; notify.save(cfg)
notify.email_password = lambda sender: ""
check("no app password says how to add it", "security add-generic-password" in notify.send_email("t", "x"))
mails = []


class SMTP:
    def __init__(self, host, port, **kw):
        mails.append({"host": host, "port": port})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        mails[-1]["login"] = (user, password)

    def send_message(self, msg):
        mails[-1]["msg"] = msg


notify.email_password = lambda sender: "app-pass"
notify.smtplib.SMTP_SSL = SMTP
why = notify.send_email("guild: alpha", "alpha: PR #7 has a merge conflict", "http://100.1.2.3:4712/?k=secret")
body = mails[-1]["msg"].get_body(preferencelist=("plain",)).get_content() if mails else ""
check("an alert email goes through Gmail with the app password", why == "" and mails[-1]["host"] == "smtp.gmail.com"
      and mails[-1]["login"] == ("me@example.com", "app-pass"))
check("the email carries the line and the link", "merge conflict" in body and "http://100.1.2.3:4712/" in body)
check("the war table key never goes into an email", "secret" not in body)
cfg.pop("email", None); notify.save(cfg)
