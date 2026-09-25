#!/usr/bin/env python3
"""Quests on another machine, over SSH.

Config: ~/.guild/local/machines.json
  {"mini": {"ssh": "nando@mini",                          what `ssh` connects to
            "guild": "~/Workspace/guild/bin/guild",        guild on that machine (installed there)
            "repos": {"crowdgen-project-api": "~/Workspace/crowdgen-project-api"}}}

  machines.py list | check [name]         the machines, and whether guild answers there
  machines.py start <name> <slug> <local repo> [quest options] < brief
  machines.py sync                         mirror remote quests here, send your answers there
  machines.py close <slug>                 close it on the machine, then here

The agent runs on the machine, inside a cockpit tab here that is an SSH session, so peek,
send and revive work as for a local quest. Guild on the machine keeps the quest; this Mac
keeps a mirror (status, events, boards) that the side menu, the docket and the campaign
board read. Your answers on the docket are copied back, where the agent waits for them.
Cost numbers are not mirrored: they live in the session logs on the machine.
"""
import json
import os
import shlex
import subprocess
import sys

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
CONFIG = os.path.join(GUILD_HOME, "local", "machines.json")
EVENTS = os.path.join(GUILD_HOME, "events.log")
SSH = os.environ.get("GUILD_SSH", "ssh")


def machines():
    try:
        return json.load(open(CONFIG))
    except (OSError, ValueError):
        return {}


def machine(name):
    m = machines().get(name)
    if not m:
        raise SystemExit(f"guild: no machine '{name}' in {CONFIG} (see bin/machines.py for the shape)")
    return m


def ssh_args(m):
    control = os.path.join(GUILD_HOME, ".ssh-%r@%h:%p")
    return [SSH, "-o", "BatchMode=yes", "-o", "ControlMaster=auto", "-o", f"ControlPath={control}",
            "-o", "ControlPersist=10m", m["ssh"]]


def remote(m, command, stdin=None, timeout=120):
    return subprocess.run(ssh_args(m) + [command], input=stdin, capture_output=True, text=True, timeout=timeout)


def rsync(m, src, dst, extra=()):
    rsh = " ".join(shlex.quote(a) for a in ssh_args(m)[:-1])
    return subprocess.run(["rsync", "-az", "-e", rsh, *extra, src, dst], capture_output=True, text=True, timeout=120)


def check(name=None):
    ok = True
    for n, m in machines().items():
        if name and n != name:
            continue
        r = remote(m, f"{m.get('guild', 'guild')} roster >/dev/null && echo guild-ok", timeout=20)
        good = "guild-ok" in r.stdout
        ok &= good
        print(f"{n:<10} {m['ssh']:<24} {'guild answers' if good else 'not reachable, or guild is not installed there'}")
    return ok


def start(name, slug, local_repo, options, brief):
    m = machine(name)
    rrepo = m.get("repos", {}).get(os.path.basename(os.path.abspath(local_repo)) if local_repo else "")
    if not rrepo:
        raise SystemExit(f"guild: machine '{name}' has no repo for {os.path.basename(local_repo or '?')} "
                         f"(add it under repos in {CONFIG})")
    guild = m.get("guild", "guild")
    cmd = f"{guild} quest {shlex.quote(slug)} --repo {shlex.quote(rrepo)} --headless " + " ".join(shlex.quote(o) for o in options)
    r = remote(m, cmd, stdin=brief)
    if r.returncode:
        raise SystemExit(f"guild: the quest did not start on {name}: {(r.stderr or r.stdout).strip()}")
    print(r.stdout.strip())
    home = remote(m, 'printf %s "${GUILD_HOME:-$HOME/.guild}"', timeout=20).stdout.strip()
    rmeta = json.loads(remote(m, f"cat {shlex.quote(home)}/quests/{shlex.quote(slug)}/meta.json", timeout=20).stdout)
    q = os.path.join(QUESTS, slug)
    os.makedirs(q, exist_ok=True)
    meta = dict(rmeta, machine=name, remote_home=home, remote_worktree=rmeta.get("worktree", ""),
                remote_repo=rmeta.get("repo", ""), repo=os.path.abspath(local_repo), worktree="")
    json.dump(meta, open(os.path.join(q, "meta.json"), "w"), indent=2)
    open(os.path.join(q, "brief.md"), "w").write(brief)
    open(os.path.join(q, "status"), "w").write(f"working\tlaunched on {name}\t\n")
    # the tab here is an ssh session into the agent there; revive and handoff reuse this file
    rq = f"{home}/quests/{slug}"
    with open(os.path.join(q, "launch.sh"), "w") as f:
        f.write("#!/usr/bin/env bash\n# the agent runs on " + name + "; this tab is its terminal\n")
        f.write(" ".join(shlex.quote(a) for a in ssh_args(m)[:-1]) + " -t " + shlex.quote(m["ssh"]) +
                ' "GUILD_RESUME=${GUILD_RESUME:-} GUILD_HANDOFF=${GUILD_HANDOFF:-} bash ' + shlex.quote(rq + "/launch.sh") + '"\n')
        f.write("exec $SHELL\n")
    os.chmod(os.path.join(q, "launch.sh"), 0o755)


def sync():
    """Pull each remote quest's status, events and boards; push the answers given here."""
    by_machine = {}
    for slug in sorted(os.listdir(QUESTS)) if os.path.isdir(QUESTS) else []:
        try:
            meta = json.load(open(os.path.join(QUESTS, slug, "meta.json")))
        except (OSError, ValueError):
            continue
        if meta.get("machine"):
            by_machine.setdefault(meta["machine"], []).append((slug, meta))
    for name, quests in by_machine.items():
        m = machines().get(name)
        if not m:
            continue
        for slug, meta in quests:
            local = os.path.join(QUESTS, slug) + "/"
            there = f"{m['ssh']}:{meta['remote_home']}/quests/{slug}/"
            # your answers first, so the agent waiting there sees them at once
            if os.path.isdir(local + "boards"):
                r = rsync(m, local + "boards/", there + "boards/",
                          ("-i", "--include=*/", "--include=decision.json", "--exclude=*"))
                if "decision.json" in r.stdout:          # an answer went over: the quest moves on there too
                    remote(m, f"{m.get('guild', 'guild')} status {shlex.quote(slug)} working 'answered on the docket'", timeout=30)
            rsync(m, there, local, ("--exclude=meta.json", "--exclude=launch.sh", "--exclude=brief.md"))
        # events for these quests, from where we left off
        cursor_file = os.path.join(GUILD_HOME, f".events-cursor-{name}")
        cursor = int(open(cursor_file).read() or 0) if os.path.exists(cursor_file) else 0
        home = quests[0][1]["remote_home"]
        r = remote(m, f"tail -c +{cursor + 1} {shlex.quote(home)}/events.log; echo; wc -c < {shlex.quote(home)}/events.log", timeout=30)
        if r.returncode:
            continue
        lines = r.stdout.rstrip("\n").split("\n")
        size = lines.pop().strip() if lines else ""
        mine = {s for s, _ in quests}
        new = [l for l in lines if l.count("\t") >= 2 and l.split("\t")[1] in mine]
        if new:
            with open(EVENTS, "a") as f:
                f.write("\n".join(new) + "\n")
        if size.isdigit():
            open(cursor_file, "w").write(size)


def close(slug):
    meta = json.load(open(os.path.join(QUESTS, slug, "meta.json")))
    m = machine(meta["machine"])
    r = remote(m, f"{m.get('guild', 'guild')} close {shlex.quote(slug)} --force")
    print(r.stdout.strip() or r.stderr.strip())


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "list"
    if cmd in ("list", "check"):
        if cmd == "list" and not machines():
            print(f"no machines yet: describe one in {CONFIG}")
        sys.exit(0 if check(args[1] if len(args) > 1 else None) else 1)
    elif cmd == "start" and len(args) >= 4:
        start(args[1], args[2], args[3], args[4:], sys.stdin.read())
    elif cmd == "sync":
        sync()
    elif cmd == "close" and len(args) > 1:
        close(args[1])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
