#!/usr/bin/env python3
"""The last tool calls an agent made in a worktree, read from its Claude session log."""
import glob
import json
import os
import sys

worktree, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 15
folder = os.path.expanduser("~/.claude/projects/" + worktree.replace("/", "-").replace(".", "-"))
logs = sorted(glob.glob(os.path.join(folder, "*.jsonl")), key=os.path.getmtime)
if not logs:
    raise SystemExit("no Claude session log for this worktree (a Codex quest keeps its own)")

calls, results = [], {}
for line in open(logs[-1], errors="ignore"):
    try:
        row = json.loads(line)
    except ValueError:
        continue
    content = (row.get("message") or {}).get("content")
    if not isinstance(content, list):
        continue
    for block in content:
        if block.get("type") == "tool_use":
            args = block.get("input") or {}
            what = args.get("command") or args.get("file_path") or args.get("pattern") or json.dumps(args)[:120]
            calls.append((row.get("timestamp", "")[11:19], block.get("name", "?"), what, block.get("id")))
        elif block.get("type") == "tool_result":
            out = block.get("content")
            if isinstance(out, list):
                out = " ".join(b.get("text", "") for b in out if isinstance(b, dict))
            results[block.get("tool_use_id")] = (out or "").strip()

for when, name, what, cid in calls[-n:]:
    print(f"{when} UTC  {name:<6} {str(what).splitlines()[0][:110]}")
    res = results.get(cid, "")
    if res:
        print(f"                 -> {res.splitlines()[0][:110]}")
