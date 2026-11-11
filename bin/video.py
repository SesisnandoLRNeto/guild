#!/usr/bin/env python3
"""The plan video: a one-minute explainer of a plan, for the plans that are a story.

  video.py spec                      the video.json format, and how to tell the story
  video.py check <slug|file>         what is wrong with a video.json (nothing printed: it is fine)
  video.py build <slug>              build quests/<slug>/video/video.mp4 now
  video.py render <file> <out.mp4>   build any video.json into a file (pictures beside the file)
  video.py status <slug>             building, ready or failed

`guild plan ready` builds it in the background when the quest folder has a video.json, and the
plan page plays it at the top. Scenes are drawn by guild (web/video.html), voiced with the Mac's
`say`, captured frame by frame in headless Chrome, and joined with ffmpeg.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

BIN = os.path.dirname(os.path.realpath(__file__))
WEB = os.path.join(os.path.dirname(BIN), "web")
GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
LEAD, TAIL = 0.3, 0.55
W, H = 540, 960                                   # CSS pixels; frames are twice that (1080x1920)

SPEC = """video.json: a one-minute video of the plan, for a full plan that is a story (guild plan ready
refuses it on a small or standard plan: those are told on the page).

When it fits: the pain is something a person can watch go wrong (a screen, data that changes shape
on its way, steps that fail in order) and the guildmaster would otherwise have to imagine it.
Skip it for small plans, refactors, upgrades, config, tests and docs.

Tell it in this order (one idea per scene, 6 to 10 scenes, under 200 words in all):
  1. hook        a surprising fact about the pain              (title)
  2. the parts   the 2 to 4 things involved, named first        (parts)
  3. the normal  how it works when nothing goes wrong           (table, card)
  4. the pain    as a tiny story on a screen they know          (change, table, picture, card)
  5. the turn    "the good news": what the fix is, in one line  (turn)
  6. the fix     the steps as a numbered checklist, 3 at most   (checklist)
  7. the call    the decision you need, with your pick          (decision)
  8. the close   back to the opening, now fixed                 (card)

{"title": "Dates from Excel", "tag": "SARA-1759",
 "scenes": [{"type": "title", "kicker": "The plan, in one minute", "title": "Dates from *Excel*",
             "sub": "Productivity and payment uploads",
             "say": "Finance saves a CSV in Excel. Then the upload says a *correct* date is *wrong*."}, ...]}

Every scene has "say": what the narrator reads, one to three short sentences, 40 words at most.
In "say", *word* lights that caption word in gold, and {1}, {2}, {3} mark the moment the scene's
1st, 2nd, 3rd thing appears ("{1}One. Read one or two digits."). Without marks they come in evenly.
In titles and big texts, *word* is gold too. Plain words: no file names, no code.

Scene types and their fields (? = optional):
  title      kicker?, title, sub?
  parts      items: [{name, icon}] 2 to 4, each appears at {1} {2} ...
             icons: file table check user screen server db mail clock lock phone gear money
  table      label?, head: [..], rows: [[..]] (4 columns and 4 rows at most), mark?: [row, col],
             result?: {text, tag, good, note?} appears at {1}
  change     label?, before, drop?, via?, after?, good?, result?: {text, tag, good, note?}
             drop: a part of "before" that falls out at {1} ("0" in "09/24"); or via + after: an
             arrow and the new value at {1}. The result card appears at {2}.
  card       label?, text, lines?: [..], pick?: index in lines lit at {1}, tag?, good?, note?
  picture    label?, src (a file beside plan.md or in the worktree), box?: [x, y, w, h] in percent,
             a ring that appears at {1}, caption?
  turn       pill? ("The good news"), text (at {1}), chips?: [..]
  checklist  label?, items: [{title, sub?}] 2 to 4, item n appears at {n} and gets its tick
  decision   label? ("Your call"), question (at {1}), options: [{key, text, pick?}] (at {2}), note?

Check it with `guild video check <slug>`; `guild plan ready` builds it in the background.
"""

ICONS = {"file", "table", "check", "user", "screen", "server", "db", "mail", "clock", "lock", "phone", "gear", "money"}
TYPES = {"title": ["title"], "parts": ["items"], "table": ["head", "rows"], "change": ["before"], "card": ["text"],
         "picture": ["src"], "turn": ["text"], "checklist": ["items"], "decision": ["question", "options"]}


def qdir(slug):
    return os.path.join(QUESTS, slug)


def vdir(slug):
    return os.path.join(qdir(slug), "video")


def settings():
    s = {"voice": "Samantha", "rate": 178, "fps": 30}
    try:
        s.update(json.load(open(os.path.join(GUILD_HOME, "local", "video.json"))))
    except (OSError, ValueError):
        pass
    if os.environ.get("GUILD_VIDEO_VOICE"):
        s["voice"] = os.environ["GUILD_VIDEO_VOICE"]
    if os.environ.get("GUILD_VIDEO_FPS"):
        s["fps"] = int(os.environ["GUILD_VIDEO_FPS"])
    if s["voice"] != "off" and not shutil.which("say"):
        s["voice"] = "off"                        # not a Mac: captions only
    return s


def words_of(say):
    return [w for w in re.sub(r"\{\d\}", " ", say or "").replace("*", "").split() if w]


def picture_path(src, bases):
    src = os.path.expanduser(src or "")
    for p in ([src] if os.path.isabs(src) else [os.path.join(b, src) for b in bases if b]):
        if os.path.isfile(p):
            return p
    return ""


def bases_for(slug):
    try:
        meta = json.load(open(os.path.join(qdir(slug), "meta.json")))
    except (OSError, ValueError):
        meta = {}
    return [qdir(slug), meta.get("worktree", "")]


def check(spec, bases):
    """The problems with a video.json, as plain lines; empty when it is fine."""
    if not isinstance(spec, dict) or not isinstance(spec.get("scenes"), list):
        return ['it needs {"title": ..., "scenes": [...]}']
    errs, total = [], 0
    scenes = spec["scenes"]
    if not 3 <= len(scenes) <= 12:
        errs.append(f"{len(scenes)} scenes: tell it in 3 to 12 (6 to 10 is best)")
    long = lambda v, n: isinstance(v, str) and len(re.sub(r"\*", "", v)) > n
    for i, sc in enumerate(scenes, 1):
        at = f"scene {i}"
        if not isinstance(sc, dict):
            errs.append(f"{at}: not an object")
            continue
        kind = sc.get("type")
        if kind not in TYPES:
            errs.append(f"{at}: type is one of {', '.join(TYPES)}")
            continue
        at = f"scene {i} ({kind})"
        n = len(words_of(sc.get("say")))
        total += n
        if not n:
            errs.append(f'{at}: needs "say", what the narrator reads')
        elif n > 40:
            errs.append(f'{at}: "say" has {n} words; keep it to 40')
        for f in TYPES[kind]:
            if not sc.get(f):
                errs.append(f'{at}: needs "{f}"')
        for f, lim in (("title", 34), ("text", 40), ("before", 22), ("after", 22), ("question", 90), ("pill", 24)):
            if long(sc.get(f), lim):
                errs.append(f'{at}: "{f}" is longer than {lim} characters; it will not fit')
        if kind == "parts" and isinstance(sc.get("items"), list):
            if not 2 <= len(sc["items"]) <= 4:
                errs.append(f"{at}: 2 to 4 items")
            for it in sc["items"]:
                if not isinstance(it, dict) or not it.get("name"):
                    errs.append(f'{at}: each item needs a "name"')
                elif it.get("icon") and it["icon"] not in ICONS:
                    errs.append(f"{at}: icon {it['icon']} is not one of: {' '.join(sorted(ICONS))}")
        if kind == "checklist" and isinstance(sc.get("items"), list):
            if not 2 <= len(sc["items"]) <= 4:
                errs.append(f"{at}: 2 to 4 items")
            if any(not isinstance(it, dict) or not it.get("title") for it in sc["items"]):
                errs.append(f'{at}: each item needs a "title"')
        if kind == "table" and isinstance(sc.get("head"), list) and isinstance(sc.get("rows"), list):
            if len(sc["head"]) > 4 or len(sc["rows"]) > 4:
                errs.append(f"{at}: 4 columns and 4 rows at most")
            if any(not isinstance(r, list) or len(r) != len(sc["head"]) for r in sc["rows"]):
                errs.append(f"{at}: every row needs as many cells as the head")
        if kind == "decision" and isinstance(sc.get("options"), list):
            if not 2 <= len(sc["options"]) <= 3 or any(not isinstance(o, dict) or not o.get("text") for o in sc["options"]):
                errs.append(f'{at}: 2 or 3 options, each with "text"')
        if kind == "change" and sc.get("drop") and sc["drop"] not in str(sc.get("before")):
            errs.append(f'{at}: "drop" must be a part of "before"')
        if kind == "picture" and sc.get("src") and not picture_path(sc["src"], bases):
            errs.append(f"{at}: the picture is not there: {sc['src']}")
    if total > 230:
        errs.append(f"{total} words in all: keep it under 200, about a minute")
    return errs


def load(path):
    try:
        return json.load(open(path)), ""
    except OSError:
        return None, f"no {path}"
    except ValueError as e:
        return None, f"{path} is not valid JSON: {e}"


# --- headless Chrome, spoken to over its DevTools socket (no dependency) ---------------------

def _exact(s, n):
    buf = bytearray(n)
    view, got = memoryview(buf), 0
    while got < n:
        k = s.recv_into(view[got:], n - got)
        if not k:
            raise ConnectionError("the browser closed the socket")
        got += k
    return bytes(buf)


def _send(s, text):
    data = text.encode()
    n = len(data)
    head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                            bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                            bytes([0x80 | 127]) + struct.pack(">Q", n))
    mask = os.urandom(4)
    s.sendall(head + mask + bytes(b ^ mask[i & 3] for i, b in enumerate(data)))


def _recv(s):
    data = b""
    while True:
        b0, b1 = _exact(s, 2)
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack(">H", _exact(s, 2))[0]
        elif n == 127:
            n = struct.unpack(">Q", _exact(s, 8))[0]
        if b1 & 0x80:
            _exact(s, 4)
        payload, op = _exact(s, n), b0 & 0x0F
        if op == 8:
            raise ConnectionError("the browser closed the socket")
        if op in (9, 10):
            continue
        data += payload
        if b0 & 0x80:
            return data.decode()


class Chrome:
    def __init__(self):
        sys.path.insert(0, BIN)
        import shot
        browser = shot.find_browser()
        if not browser:
            raise RuntimeError("no Chrome or Chromium found")
        self.profile = tempfile.mkdtemp(prefix="guild-video-")
        self.proc = subprocess.Popen([browser, "--headless=new", "--remote-debugging-port=0",
                                      f"--user-data-dir={self.profile}", "--hide-scrollbars", "--no-first-run",
                                      "--no-default-browser-check", "--mute-audio", "--allow-file-access-from-files",
                                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = os.path.join(self.profile, "DevToolsActivePort")
        for _ in range(150):
            if os.path.exists(port_file) and open(port_file).read().strip():
                break
            time.sleep(0.1)
        else:
            self.close()
            raise RuntimeError("Chrome did not open its DevTools port")
        port = int(open(port_file).read().split()[0])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        page = next(t for t in json.load(opener.open(f"http://127.0.0.1:{port}/json/list", timeout=10))
                    if t.get("type") == "page")
        u = urllib.parse.urlparse(page["webSocketDebuggerUrl"])
        self.sock = socket.create_connection((u.hostname, u.port), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while not head.endswith(b"\r\n\r\n"):
            head += _exact(self.sock, 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise RuntimeError("Chrome refused the DevTools socket")
        self.n = 0

    def call(self, method, **params):
        self.n += 1
        _send(self.sock, json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(_recv(self.sock))
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})

    def js(self, expr, wait=False):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=wait, returnByValue=True)
        if r.get("exceptionDetails"):
            raise RuntimeError("page error: " + json.dumps(r["exceptionDetails"])[:300])
        return r.get("result", {}).get("value")

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


# --- build -----------------------------------------------------------------------------------

def duration(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", path], text=True))


def chunks(words):
    out, start = [], 0
    for i, w in enumerate(words):
        if i + 1 - start >= 4 or re.search(r"[.,:;?!]$", w["w"]) or i == len(words) - 1:
            out.append([start, i + 1])
            start = i + 1
    return out


def timing(spec, work, voice, rate):
    """Voice each scene and time its caption words. Returns (timing, audio wav)."""
    scenes, t0, wavs = [], 0.0, []
    for n, sc in enumerate(spec["scenes"]):
        tokens = sc["say"].split()
        words, cues, pend = [], {}, []
        for tk in tokens:
            while True:
                m = re.match(r"\{(\d)\}(.*)", tk)
                if not m:
                    break
                pend.append("c" + m.group(1))
                tk = m.group(2)
            if not tk:
                continue
            words.append({"w": tk.replace("*", ""), "key": "*" in tk, "cues": pend})
            pend = []
        spoken = " ".join(w["w"] for w in words)
        if voice != "off":
            txt, aiff = os.path.join(work, f"{n}.txt"), os.path.join(work, f"{n}.aiff")
            open(txt, "w").write(spoken)
            subprocess.run(["say", "-v", voice, "-r", str(rate), "-f", txt, "-o", aiff], check=True)
            a = duration(aiff)
        else:
            a = max(1.6, 0.36 * len(words))
        weight = [len(w["w"]) + 2 + (7 if re.search(r"[.?!:;]$", w["w"]) else 3 if w["w"].endswith(",") else 0) for w in words]
        speak, acc = max(a - 0.25, 0.5), 0
        for w, k in zip(words, weight):
            w["t"] = round(LEAD + speak * acc / sum(weight), 3)
            acc += k
            for c in w.pop("cues"):
                cues[c] = w["t"]
        for c in pend:                             # a mark at the very end
            cues[c] = round(LEAD + speak, 3)
        d = round(LEAD + a + TAIL, 3)
        scenes.append({"start": round(t0, 3), "dur": d, "words": words, "cues": cues, "chunks": chunks(words),
                       "speech": round(LEAD + speak, 3)})
        if voice != "off":
            wav = os.path.join(work, f"{n}.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", aiff, "-af",
                            f"adelay={int(LEAD * 1000)}:all=1,apad=whole_dur={d}", "-ar", "44100", "-ac", "1", wav], check=True)
            wavs.append(wav)
        t0 += d
    total = round(t0, 3)
    audio = os.path.join(work, "voice.wav")
    if wavs:
        lst = os.path.join(work, "list.txt")
        open(lst, "w").write("".join(f"file '{w}'\n" for w in wavs))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", audio], check=True)
    else:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(total), audio],
                       check=True)
    return {"scenes": scenes, "total": total}, audio


def render(spec, bases, out, log=print):
    """Build spec into the mp4 at out. Pictures are looked up in bases."""
    s = settings()
    work = tempfile.mkdtemp(prefix="guild-video-work-")
    chrome = None
    try:
        spec = json.loads(json.dumps(spec))
        for n, sc in enumerate(spec["scenes"]):
            if sc.get("type") == "picture":
                src = picture_path(sc["src"], bases)
                name = f"pic{n}{os.path.splitext(src)[1].lower() or '.png'}"
                shutil.copy(src, os.path.join(work, name))
                sc["src"] = name
        t, audio = timing(spec, work, s["voice"], s["rate"])
        log(f"voice ready: {t['total']}s, {len(t['scenes'])} scenes")
        page = open(os.path.join(WEB, "video.html")).read()
        data = json.dumps({"spec": spec, "timing": t}).replace("</", "<\\/")
        open(os.path.join(work, "index.html"), "w").write(page.replace("/*__REEL__*/", f"window.REEL={data};"))
        chrome = Chrome()
        chrome.call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=2, mobile=False)
        chrome.call("Page.navigate", url="file://" + os.path.join(work, "index.html"))
        for _ in range(100):
            if chrome.js("document.readyState === 'complete' && typeof window.render === 'function'"):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("the video page did not load")
        chrome.js("document.fonts.ready.then(() => true)", wait=True)
        fps = s["fps"]
        frames = int(t["total"] * fps + 0.999)
        tmp = out + ".part.mp4"
        enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg",
                                "-i", "-", "-i", audio, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                                "-crf", "21", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", tmp],
                               stdin=subprocess.PIPE)
        for f in range(frames):
            chrome.js(f"render({f / fps})")
            shot = chrome.call("Page.captureScreenshot", format="jpeg", quality=90)
            enc.stdin.write(base64.b64decode(shot["data"]))
            if f and f % (fps * 10) == 0:
                log(f"frame {f}/{frames}")
        enc.stdin.close()
        if enc.wait():
            raise RuntimeError("ffmpeg could not join the frames")
        os.replace(tmp, out)
        return t["total"]
    finally:
        if chrome:
            chrome.close()
        shutil.rmtree(work, ignore_errors=True)


def fingerprint(spec, bases):
    h = hashlib.sha256(json.dumps([spec, settings()], sort_keys=True).encode())
    h.update(open(os.path.join(WEB, "video.html"), "rb").read())
    for sc in spec.get("scenes", []):
        if sc.get("type") == "picture":
            p = picture_path(sc.get("src"), bases)
            if p:
                h.update(open(p, "rb").read())
    return h.hexdigest()[:16]


def status(slug):
    try:
        return json.load(open(os.path.join(vdir(slug), "status.json")))
    except (OSError, ValueError):
        return {"state": "none"}


def save_status(slug, **st):
    os.makedirs(vdir(slug), exist_ok=True)
    tmp = os.path.join(vdir(slug), "status.json.tmp")
    json.dump({**st, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, open(tmp, "w"))
    os.replace(tmp, os.path.join(vdir(slug), "status.json"))


def build(slug, log=print):
    spec, err = load(os.path.join(qdir(slug), "video.json"))
    if err:
        raise SystemExit(f"video: {err}")
    bases = bases_for(slug)
    errs = check(spec, bases)
    if errs:
        save_status(slug, state="failed", error="; ".join(errs))
        raise SystemExit("video: " + "\n  ".join(["video.json needs work:"] + errs))
    fp = fingerprint(spec, bases)
    out = os.path.join(vdir(slug), "video.mp4")
    st = status(slug)
    if st.get("state") == "ready" and st.get("hash") == fp and os.path.exists(out):
        log("video: already built from this video.json")
        return out
    save_status(slug, state="building", hash=fp, pid=os.getpid())
    try:
        secs = render(spec, bases, out, log)
    except Exception as e:
        save_status(slug, state="failed", hash=fp, error=str(e)[:300])
        raise SystemExit(f"video: {e}")
    save_status(slug, state="ready", hash=fp, seconds=secs)
    log(f"video: {out}")
    return out


def spawn(slug):
    """Build in the background (a plan page waits for nobody). A build already running is stopped."""
    st = status(slug)
    if st.get("state") == "building" and st.get("pid"):
        try:
            os.killpg(st["pid"], signal.SIGTERM)
        except OSError:
            pass
    os.makedirs(vdir(slug), exist_ok=True)
    log = open(os.path.join(vdir(slug), "build.log"), "w")
    p = subprocess.Popen([sys.executable, os.path.realpath(__file__), "build", slug], stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True, env={**os.environ, "GUILD_HOME": GUILD_HOME})
    save_status(slug, state="building", pid=p.pid)
    return p


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "help"):
        raise SystemExit(__doc__)
    if a[0] == "spec":
        print(SPEC)
    elif a[0] == "check" and len(a) > 1:
        if os.path.isfile(a[1]):
            spec, err = load(a[1])
            bases = [os.path.dirname(os.path.abspath(a[1]))]
        else:
            spec, err = load(os.path.join(qdir(a[1]), "video.json"))
            bases = bases_for(a[1])
        errs = [err] if err else check(spec, bases)
        if errs:
            raise SystemExit("\n".join(errs))
    elif a[0] == "build" and len(a) > 1:
        build(a[1])
    elif a[0] == "render" and len(a) > 2:
        spec, err = load(a[1])
        errs = [err] if err else check(spec, [os.path.dirname(os.path.abspath(a[1]))])
        if errs:
            raise SystemExit("\n".join(errs))
        render(spec, [os.path.dirname(os.path.abspath(a[1]))], os.path.abspath(a[2]))
        print(a[2])
    elif a[0] == "status" and len(a) > 1:
        print(json.dumps(status(a[1])))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
