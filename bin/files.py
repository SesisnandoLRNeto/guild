#!/usr/bin/env python3
"""The map room: find any file in a quest's worktree, read it with its changes marked in the
gutter, and compare it with the base branch or any earlier commit. The war table serves the page
at /q/<slug>/files; this module answers its JSON calls and the CLI (`python3 files.py list|show|diff`).

Everything comes from git in the quest's worktree; nothing is cached. A path is accepted only when
it stays inside the worktree, a revision only when it looks like a sha or HEAD."""
import json
import os
import re
import subprocess
import sys

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
QUESTS = os.path.join(GUILD_HOME, "quests")
REV = re.compile(r"^([0-9a-fA-F]{4,40}(~\d+)?|HEAD(~\d+)?|WORK)$")
LANGS = {
    ".java": "java", ".kt": "kotlin", ".ts": "ts", ".tsx": "ts", ".js": "js", ".jsx": "js", ".mjs": "js",
    ".py": "python", ".rb": "ruby", ".go": "go", ".rs": "rust", ".sh": "sh", ".bash": "sh", ".zsh": "sh",
    ".html": "html", ".vue": "html", ".xml": "html", ".svg": "html", ".css": "css", ".scss": "css",
    ".json": "json", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".sql": "sql", ".md": "md",
    ".properties": "ini", ".ini": "ini", ".env": "ini", ".gradle": "groovy", ".groovy": "groovy", ".cs": "csharp",
    ".c": "c", ".h": "c", ".cpp": "c", ".hpp": "c", ".swift": "swift", ".php": "php", ".tf": "hcl", ".dockerfile": "sh",
}
MAX_BYTES = 1_500_000


def meta(slug):
    try:
        return json.load(open(os.path.join(QUESTS, slug, "meta.json")))
    except (OSError, ValueError):
        return {}


def worktree(slug):
    m = meta(slug)
    for d in (m.get("worktree"), m.get("repo")):
        if d and os.path.isdir(d):
            return d
    return ""


def git(wt, *args, text=True):
    try:
        out = subprocess.run(["git", "-C", wt, *args], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return "" if text else b""
    return out.stdout.decode("utf-8", "replace") if text else out.stdout


def base_sha(wt, base):
    """Where the quest's branch left the base: the merge base, so the quest's own commits count as changes."""
    for ref in [base, "origin/main", "main", "origin/master", "master"]:
        if not ref:
            continue
        sha = git(wt, "merge-base", ref, "HEAD").strip()
        if sha:
            return sha
    roots = git(wt, "rev-list", "--max-parents=0", "HEAD").split()
    return roots[-1] if roots else "HEAD"


def safe_path(wt, path):
    """The path relative to the worktree, or "" when it points outside of it."""
    if not path or path.startswith("/") or "\0" in path:
        return ""
    full = os.path.realpath(os.path.join(wt, path))
    root = os.path.realpath(wt)
    if full != root and not full.startswith(root + os.sep):
        return ""
    return os.path.relpath(full, root)


def lang_of(path):
    name = os.path.basename(path).lower()
    if name in ("dockerfile", "makefile"):
        return "sh" if name == "dockerfile" else "make"
    return LANGS.get(os.path.splitext(name)[1], "")


def listing(slug):
    wt = worktree(slug)
    if not wt:
        return {"error": f"quest {slug} has no worktree"}
    m = meta(slug)
    base = base_sha(wt, m.get("base", ""))
    changed = {}
    for line in git(wt, "diff", "--name-status", "-M", base).splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0][0], parts[-1]
        changed[path] = {"path": path, "status": status, "add": 0, "del": 0,
                         "from": parts[1] if status == "R" and len(parts) > 2 else ""}
    for line in git(wt, "diff", "--numstat", "-M", base).splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        path = parts[-1]
        if "=>" in path:           # renames come as "dir/{old => new}.ext"; name-status already has them
            path = re.sub(r"\{[^}]*=> ([^}]*)\}", r"\1", path).replace("//", "/")
            path = next((p for p in changed if p.endswith(path.split("}")[-1])), path)
        if path in changed:
            changed[path]["add"] = int(parts[0]) if parts[0].isdigit() else 0
            changed[path]["del"] = int(parts[1]) if parts[1].isdigit() else 0
    for path in git(wt, "ls-files", "--others", "--exclude-standard").splitlines():
        if path and path not in changed:
            try:
                n = sum(1 for _ in open(os.path.join(wt, path), "rb"))
            except OSError:
                n = 0
            changed[path] = {"path": path, "status": "A", "add": n, "del": 0, "from": "", "untracked": True}
    tracked = [p for p in git(wt, "ls-files").splitlines() if p]
    deleted = {p for p, c in changed.items() if c["status"] == "D"}
    files = sorted(set(tracked) | {p for p in changed if p not in deleted} - deleted)
    commits = []
    for line in git(wt, "log", "--format=%h%x09%H%x09%ar%x09%s", f"{base}..HEAD").splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4:
            commits.append({"short": parts[0], "sha": parts[1], "when": parts[2], "subject": parts[3]})
    order = {"M": 0, "A": 1, "R": 1, "D": 2}
    return {
        "slug": slug, "repo": m.get("repo", ""), "worktree": wt, "branch": m.get("branch", "") or git(wt, "branch", "--show-current").strip(),
        "base": m.get("base", "") or "origin/main", "base_sha": base, "head": git(wt, "rev-parse", "--short", "HEAD").strip(),
        "changed": sorted(changed.values(), key=lambda c: (order.get(c["status"], 3), c["path"])),
        "files": files, "commits": commits, "ticket": m.get("ticket", ""),
    }


def hunks(diff_text):
    """The changed stretches of the new file, from a unified diff: (kind, start, end) with kind
    add, change or del; a del marks the line the removed text sat before."""
    out = []
    new = pending_del = 0
    for line in diff_text.splitlines():
        h = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
        if h:
            new = int(h.group(1))
            pending_del = 0
            continue
        if line.startswith("+++") or line.startswith("---") or line.startswith("\\"):
            continue
        if line.startswith("-"):
            pending_del += 1
        elif line.startswith("+"):
            if pending_del:
                out.append(["change", new, new])
                pending_del -= 1
            else:
                out.append(["add", new, new])
            new += 1
        else:
            if pending_del:
                out.append(["del", new, new])
                pending_del = 0
            new += 1
    if diff_text and pending_del:
        out.append(["del", new, new])
    merged = []
    for kind, a, b in out:
        if merged and merged[-1][0] == kind and merged[-1][2] + 1 >= a:
            merged[-1][2] = b
        else:
            merged.append([kind, a, b])
    return merged


def show(slug, path, rev=""):
    wt = worktree(slug)
    rel = safe_path(wt, path) if wt else ""
    if not rel:
        return {"error": "no such file"}
    rev = rev if rev and REV.match(rev) and rev != "WORK" else ""
    if rev:
        if not git(wt, "cat-file", "-t", f"{rev}:{rel}").strip():
            return {"error": "not in that commit"}
        raw = git(wt, "show", f"{rev}:{rel}", text=False)
    else:
        full = os.path.join(wt, rel)
        if not os.path.isfile(full):
            return {"error": "no such file"}
        with open(full, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    binary = b"\0" in raw[:8000]
    text = "" if binary else raw[:MAX_BYTES].decode("utf-8", "replace")
    m = meta(slug)
    base = base_sha(wt, m.get("base", ""))
    marks = []
    if not rev and not binary:
        if git(wt, "cat-file", "-t", f"{base}:{rel}").strip():       # it existed at the base: mark the hunks
            marks = hunks(git(wt, "diff", "-U0", base, "--", rel))
        else:                                                        # new in this quest: every line is new
            n = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
            marks = [["add", 1, n]] if n else []
    mine = set(git(wt, "rev-list", f"{base}..HEAD").split())       # the quest's own commits
    log = []
    for line in git(wt, "log", "--follow", "--format=%h%x09%H%x09%ar%x09%an%x09%s", "-n", "40", "--", rel).splitlines():
        parts = line.split("\t", 4)
        if len(parts) == 5:
            log.append({"short": parts[0], "sha": parts[1], "when": parts[2], "author": parts[3], "subject": parts[4],
                        "quest": parts[1] in mine})
    return {"path": rel, "lang": lang_of(rel), "rev": rev, "binary": binary, "text": text, "truncated": len(raw) > MAX_BYTES,
            "lines": text.count("\n") + (0 if text.endswith("\n") or not text else 1), "marks": marks, "log": log,
            "base_sha": base}


def diff(slug, path, frm="", to=""):
    """Rows of a unified diff for one file: kind ctx/add/del/hunk, old and new line numbers, text.
    `frm` defaults to the base of the quest; `to` empty means the working tree."""
    wt = worktree(slug)
    rel = safe_path(wt, path) if wt else ""
    if not rel:
        return {"error": "no such file"}
    m = meta(slug)
    base = base_sha(wt, m.get("base", ""))
    frm = frm if frm and REV.match(frm) and frm != "WORK" else base
    to = to if to and REV.match(to) and to != "WORK" else ""
    in_from = bool(git(wt, "cat-file", "-t", f"{frm}:{rel}").strip())
    if to:
        text = git(wt, "diff", "-M", frm, to, "--", rel)
    elif in_from:
        text = git(wt, "diff", "-M", frm, "--", rel)
    else:
        full = os.path.join(wt, rel)
        text = git(wt, "diff", "--no-index", "--", os.devnull, full) if os.path.isfile(full) else ""
    rows, old, new, add, dele = [], 0, 0, 0, 0
    for line in text.splitlines():
        if line.startswith(("diff ", "index ", "--- ", "+++ ", "new file", "deleted file", "similarity", "rename ", "old mode", "new mode", "Binary")):
            if line.startswith("Binary"):
                rows.append({"kind": "hunk", "text": "binary file, no text to compare"})
            continue
        h = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$", line)
        if h:
            old, new = int(h.group(1)), int(h.group(2))
            rows.append({"kind": "hunk", "text": line})
            continue
        if line.startswith("\\"):
            continue
        if line.startswith("+"):
            rows.append({"kind": "add", "old": None, "new": new, "text": line[1:]}); new += 1; add += 1
        elif line.startswith("-"):
            rows.append({"kind": "del", "old": old, "new": None, "text": line[1:]}); old += 1; dele += 1
        else:
            rows.append({"kind": "ctx", "old": old, "new": new, "text": line[1:]}); old += 1; new += 1
    return {"path": rel, "lang": lang_of(rel), "from": frm, "to": to or "WORK", "rows": rows, "add": add, "del": dele,
            "same": not rows}


def main(argv):
    if len(argv) < 2 or argv[0] not in ("list", "show", "diff"):
        print("usage: files.py list <slug> | show <slug> <path> [rev] | diff <slug> <path> [from] [to]", file=sys.stderr)
        return 2
    if argv[0] == "list":
        out = listing(argv[1])
    elif argv[0] == "show":
        out = show(argv[1], argv[2] if len(argv) > 2 else "", argv[3] if len(argv) > 3 else "")
    else:
        out = diff(argv[1], argv[2] if len(argv) > 2 else "", argv[3] if len(argv) > 3 else "", argv[4] if len(argv) > 4 else "")
    print(json.dumps(out, indent=1))
    return 1 if out.get("error") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
