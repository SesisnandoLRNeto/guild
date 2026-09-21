#!/usr/bin/env bash
# PreToolUse(Bash) hook for adventurers: block `gh pr create` until the trial passed or was skipped for HEAD.
input=$(cat)
cmd=$(python3 -c "import json,sys;print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" <<< "$input")
case "$cmd" in *"gh pr create"*) ;; *) exit 0 ;; esac

slug="${GUILD_QUEST:-}"
[ -n "$slug" ] || exit 0
trial="${GUILD_HOME:-$HOME/.guild}/quests/$slug/trial.json"
head=$(git rev-parse HEAD 2>/dev/null)

if [ ! -f "$trial" ]; then
  echo "Blocked: no trial for this quest. Run the trial skill first, or if the guildmaster allowed it: guild trial skip \"<reason>\"." >&2
  exit 2
fi
read -r sha result note < <(python3 -c "import json;t=json.load(open('$trial'));print(t['sha'],t['result'],t['note'])")
if [ "$sha" != "$head" ]; then
  echo "Blocked: the trial ran on $sha but HEAD is now $head. Run the trial again for the new commits." >&2
  exit 2
fi
if [ "$result" = "skip" ] && ! grep -q "Trial: skipped" <<< "$cmd"; then
  echo "Blocked: the trial was skipped ($note). Add a line 'Trial: skipped - $note' to the PR body so the reviewer sees it." >&2
  exit 2
fi
exit 0
