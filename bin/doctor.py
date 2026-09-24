#!/usr/bin/env python3
"""`guild doctor`: is this setup healthy, and what is missing?

Three parts: the tools guild needs, the config it reads, and the state it keeps (orphan
quests, stale worktrees, branches nobody closed). Read-only: it never fixes anything, it
prints the command that would.
"""
import json
import os
import shutil
import subprocess
import sys

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
REPO = os.environ.get("GUILD_REPO", os.path.expanduser("~/Workspace/guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
SOCKET = os.environ.get("GUILD_TMUX_SOCKET", "guild")
GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"

problems = 0
warnings = 0


def line(state, what, detail=""):
    global problems, warnings
    mark = {"ok": f"{GREEN}ok  {RESET}", "warn": f"{YELLOW}warn{RESET}", "fail": f"{RED}fail{RESET}"}[state]
    if state == "fail":
        problems += 1
    if state == "warn":
        warnings += 1
    print(f"  {mark}  {what}" + (f"  {DIM}{detail}{RESET}" if detail else ""))


def run(*args, timeout=6):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def section(title):
    print(f"\n{title}")


def check_tools():
    section("tools")
    for tool, why, needed in [("tmux", "the cockpit", True), ("git", "worktrees", True),
                              ("gh", "pull requests", True), ("python3", "guild itself", True),
                              ("claude", "the default harness", True),
                              ("codex", "the codex harness", False),
                              ("claude-deck", "the deck tab", False)]:
        path = shutil.which(tool)
        if path:
            line("ok", tool, path)
        else:
            line("fail" if needed else "warn", tool, f"missing, needed for {why}")
    editor = os.environ.get("EDITOR", "nvim")
    line("ok" if shutil.which(editor) else "warn", f"editor ({editor})", "used by guild edit")
    bin_dir = os.path.expanduser("~/.local/bin")
    line("ok" if bin_dir in os.environ.get("PATH", "").split(":") else "warn",
         "~/.local/bin on PATH", "where the guild command is linked")


def check_config():
    section("config")
    for name, why in [("dispatch.json", "which harness and model a quest gets"),
                      ("identities.json", "git identity and gh account per repo")]:
        path = os.path.join(GUILD_HOME, "local", name)
        if not os.path.exists(path):
            line("fail", name, f"missing: {path}")
            continue
        try:
            json.load(open(path))
            line("ok", name, why)
        except ValueError as e:
            line("fail", name, f"not valid json: {e}")

    env = os.path.join(GUILD_HOME, "local", "env")
    if os.path.exists(env):
        mode = oct(os.stat(env).st_mode)[-3:]
        has_key = any(l.strip().startswith("OPENROUTER_API_KEY=") for l in open(env))
        line("ok" if has_key else "warn", "local/env",
             f"mode {mode}" + ("" if has_key else ", no OPENROUTER_API_KEY (the openrouter harness needs it)"))
        if mode != "600":
            line("warn", "local/env permissions", f"{mode}, should be 600: chmod 600 {env}")
    else:
        line("warn", "local/env", "missing, only needed for the openrouter harness")

    for link, target in [(os.path.expanduser("~/.claude/agents/quartermaster.md"), "the orchestrator"),
                         (os.path.expanduser("~/.claude/skills/war-table"), "decision boards"),
                         (os.path.expanduser("~/.claude/skills/trial"), "the pre-PR gate"),
                         (os.path.expanduser("~/.claude/skills/campfire"), "the catch-up")]:
        line("ok" if os.path.exists(link) else "fail", os.path.basename(link), target)

    # Claude ignores a settings file it cannot parse, which would switch every gate off
    # without a word. Prove they parse and still carry their hooks.
    for name, hook in (("worker-settings.json", "pr-gate.sh"), ("qm-settings.json", "qm-guard.sh")):
        path = os.path.join(GUILD_HOME, name)
        try:
            text = open(path).read()
            json.loads(text)
            line("ok" if hook in text else "fail", name, "valid, hooks present" if hook in text else f"{hook} missing: run install.sh")
        except (OSError, ValueError) as e:
            line("fail", name, f"unreadable or invalid, so its gates are off: {e}")

    guard = os.path.join(REPO, "hooks", "qm-guard.sh")
    line("ok" if os.access(guard, os.X_OK) else "fail", "quartermaster guard", "stops the orchestrator editing project code")

    shim = os.path.join(REPO, "bin", "shims", "gh")
    line("ok" if os.access(shim, os.X_OK) else "fail", "gh shim", "the trial gate for every harness")

    jira = os.path.join(GUILD_HOME, "local", "jira.json")
    if os.path.exists(jira):
        try:
            cfg = json.load(open(jira))
            has_token = os.path.exists(env) and any(l.strip().startswith("JIRA_API_TOKEN=") for l in open(env))
            line("ok" if has_token and cfg.get("projects") else "warn", "jira watcher",
                 f"{', '.join(cfg.get('projects', [])) or 'no projects'} · "
                 f"{'autostart' if cfg.get('autostart') else 'asks first'} · "
                 f"{'token set' if has_token else 'no JIRA_API_TOKEN in local/env'}")
        except ValueError as e:
            line("fail", "jira.json", f"not valid json: {e}")

    mermaid = os.path.join(GUILD_HOME, "vendor", "mermaid.min.js")
    line("ok" if os.path.exists(mermaid) else "warn", "mermaid for boards",
         "diagrams render offline" if os.path.exists(mermaid) else "missing: run install.sh")
    code, out, _ = run(sys.executable, os.path.join(REPO, "bin", "shot.py"), "x", "--find-browser")
    line("ok" if out else "warn", "browser for guild shot", out or "no Chrome/Chromium/Edge: set GUILD_BROWSER")

    calm_file = os.path.join(GUILD_HOME, "calm")
    calm = open(calm_file).read().strip() if os.path.exists(calm_file) else "off"
    line("ok", "calm mode", f"{calm} (the bird; guild calm on|off)")


def check_identities():
    """Every repo with a live quest should map to a git identity and a gh account."""
    section("identities")
    path = os.path.join(GUILD_HOME, "local", "identities.json")
    try:
        ids = json.load(open(path))
    except (OSError, ValueError):
        return line("fail", "identities.json", "unreadable, quests would commit with your global identity")
    owners = [k for k in ids if k != "_note"]
    line("ok", "owners mapped", ", ".join(owners) or "none")
    for owner in owners:
        who = ids[owner]
        gh_user = who.get("gh_user", "")
        if not gh_user:
            line("warn", owner, "no gh_user, so quests use whichever gh account is active")
            continue
        code, _, _ = run("gh", "auth", "token", "--user", gh_user)
        line("ok" if code == 0 else "fail", f"{owner} -> {gh_user}",
             "token available" if code == 0 else "gh has no token for this account: gh auth login")


def check_state():
    section("fleet")
    if not os.path.isdir(QUESTS):
        return line("ok", "no quests yet")
    code, out, _ = run("tmux", "-L", SOCKET, "list-windows", "-a", "-F", "#W")
    windows = set(out.split()) if code == 0 else set()
    live = code == 0
    line("ok" if live else "warn", "cockpit", "running" if live else "not running (guild up)")

    active, orphans, stale = 0, [], []
    for slug in sorted(os.listdir(QUESTS)):
        d = os.path.join(QUESTS, slug)
        if not os.path.exists(os.path.join(d, "meta.json")):
            continue
        state = open(os.path.join(d, "status")).read().split("\t")[0] if os.path.exists(os.path.join(d, "status")) else "?"
        meta = json.load(open(os.path.join(d, "meta.json")))
        if state in ("working", "needs-decision", "blocked", "stopped"):
            active += 1
            if live and slug not in windows:
                orphans.append(slug)
        if state in ("done", "failed") and os.path.isdir(meta.get("worktree", "")):
            stale.append(slug)
    line("ok", "active quests", str(active))
    if orphans:
        line("warn", "quests with no window", f"{', '.join(orphans)} -> guild revive")
    if stale:
        line("warn", "finished quests still holding a worktree", f"{', '.join(stale)} -> guild close <slug>")

    boards = 0
    for slug in os.listdir(QUESTS):
        broot = os.path.join(QUESTS, slug, "boards")
        if os.path.isdir(broot):
            boards += sum(1 for b in os.listdir(broot)
                          if os.path.exists(os.path.join(broot, b, "board.json"))
                          and not os.path.exists(os.path.join(broot, b, "decision.json")))
    line("warn" if boards else "ok", "boards waiting on you", str(boards) + (" -> guild board url" if boards else ""))

    events = os.path.join(GUILD_HOME, "events.log")
    size = os.path.getsize(events) if os.path.exists(events) else 0
    line("warn" if size > 5_000_000 else "ok", "events.log", f"{size // 1024} KB")


def check_trust():
    """Claude asks to trust every new git checkout; guild copies trust from the main repo."""
    section("claude")
    worktrees = os.environ.get("GUILD_WORKTREES", os.path.expanduser("~/Workspace/.guild-worktrees"))
    line("ok" if os.path.isdir(os.path.dirname(worktrees)) else "warn", "worktree root", worktrees)
    try:
        projects = json.load(open(os.path.expanduser("~/.claude.json"))).get("projects", {})
    except (OSError, ValueError):
        return line("warn", "~/.claude.json", "unreadable, quests may ask you to trust each worktree")
    dangling = [p for p in projects if "/.guild-worktrees/" in p and not os.path.exists(p)]
    line("warn" if dangling else "ok", "trust entries for removed worktrees", str(len(dangling)))
    code, out, _ = run("claude", "--version")
    line("ok" if code == 0 else "fail", "claude code", out or "not answering")
    mod = os.path.expanduser("~/.claude/skills/guild-calm")
    line("ok" if os.path.exists(mod) else "warn", "calm mod linked", mod)


def main():
    print(f"guild doctor  {DIM}{GUILD_HOME}{RESET}")
    check_tools()
    check_config()
    check_identities()
    check_state()
    check_trust()
    print()
    if problems:
        print(f"{RED}{problems} problem(s){RESET}, {warnings} warning(s)")
        sys.exit(1)
    print(f"{GREEN}healthy{RESET}" + (f", {warnings} warning(s)" if warnings else ""))


if __name__ == "__main__":
    main()
