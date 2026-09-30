"""All of guild's events, old and new: the monthly files tidy.py moved out, then events.log."""
import glob
import os

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))


def lines():
    out = []
    for path in sorted(glob.glob(os.path.join(GUILD_HOME, "events", "*.log"))) + [os.path.join(GUILD_HOME, "events.log")]:
        try:
            out += open(path, errors="ignore").read().splitlines()
        except OSError:
            pass
    return out
