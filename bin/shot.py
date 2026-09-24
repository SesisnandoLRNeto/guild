#!/usr/bin/env python3
"""guild shot: a screenshot a board can trust.

Before-and-after pairs only mean something when they are taken the same way: same
browser, same viewport, same wait. Every agent doing it its own way produces pairs you
cannot compare. This takes them one way, headless, and files them under the quest.

    guild shot <url> --name before [--width 1280] [--height 800] [--wait MS]
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))

CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
]


def find_browser():
    override = os.environ.get("GUILD_BROWSER")
    if override:
        return override if (os.path.exists(override) or shutil.which(override)) else None
    for c in CANDIDATES:
        if os.path.isabs(c) and os.path.exists(c):
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


def main():
    args, key, url = {}, None, None
    for token in sys.argv[1:]:
        if token.startswith("--"):
            key = token[2:]
            args[key] = True
        elif key:
            args[key] = token
            key = None
        else:
            url = token
    if not url or args.get("help"):
        raise SystemExit(__doc__)
    if args.get("find-browser"):
        print(find_browser() or "")
        return

    browser = find_browser()
    if not browser:
        raise SystemExit("guild shot: no Chrome, Chromium or Edge found (set GUILD_BROWSER)")

    quest = os.environ.get("GUILD_QUEST", "")
    name = args.get("name") or "shot"
    if not name.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("guild shot: --name takes letters, digits, - and _")
    out = args.get("out") or os.path.join(GUILD_HOME, "quests", quest or "quartermaster", "shots", f"{name}.png")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    width, height = int(args.get("width") or 1280), int(args.get("height") or 800)
    # Chrome writes the image and then sometimes never exits (a page with a big script or
    # an open request keeps it alive), so waiting for the process is the wrong signal.
    # Wait for the file to appear and stop growing, then end Chrome ourselves. A throwaway
    # profile keeps it away from your real, locked Chrome profile.
    if os.path.exists(out):
        os.remove(out)
    profile = tempfile.mkdtemp(prefix="guild-shot-")
    cmd = [browser, "--headless", f"--user-data-dir={profile}", "--disable-gpu", "--hide-scrollbars",
           "--no-first-run", "--no-default-browser-check", f"--window-size={width},{height}",
           f"--screenshot={os.path.abspath(out)}"]
    if args.get("wait"):
        cmd.append(f"--virtual-time-budget={int(args['wait'])}")
    cmd.append(url)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline, last, steady = time.time() + float(args.get("timeout") or 60), -1, None
    try:
        while time.time() < deadline and proc.poll() is None:
            size = os.path.getsize(out) if os.path.exists(out) else -1
            if size > 0 and size == last:
                if steady and time.time() - steady > 0.6:
                    break
            else:
                last, steady = size, time.time()
            time.sleep(0.2)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    if not os.path.exists(out) or os.path.getsize(out) == 0:
        raise SystemExit("guild shot: no image produced (is the page reachable?)")
    print(out)
    print(f"{width}x{height}. Take the other half of the pair with the same flags.")


if __name__ == "__main__":
    main()
