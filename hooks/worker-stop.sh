#!/usr/bin/env bash
# Stop hook for adventurers: notice a quest that ended its turn without reporting.
#
# A turn also ends when the agent is only waiting, for example on a background test run
# it will be woken by. Marking the quest stopped at that moment is a false alarm: the tab
# gets a `?` and the quartermaster wakes for nothing. So this does not decide now. It
# leaves a detached check that looks again after a grace period, and only marks the quest
# stopped if it is still "working", nothing new was logged for it, and its transcript has
# not moved since. The hook itself returns at once.
input=$(cat)
slug="${GUILD_QUEST:-}"
[ -n "$slug" ] || exit 0
home="${GUILD_HOME:-$HOME/.guild}"
status_file="$home/quests/$slug/status"
[ -f "$status_file" ] || exit 0
[ "$(cut -f1 "$status_file")" = "working" ] || exit 0

transcript=$(python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("transcript_path") or "")
except ValueError: print("")' <<<"$input")
fired=$(date +%Y-%m-%dT%H:%M:%S)
grace="${GUILD_STOP_GRACE:-120}"

(
  sleep "$grace"
  [ "$(cut -f1 "$status_file" 2>/dev/null)" = "working" ] || exit 0
  # Anything logged for this quest after the turn ended means it carried on.
  # awk, not grep -P: macOS ships BSD grep, which has no -P at all
  last=$(awk -F'\t' -v s="$slug" '$2 == s { t = $1 } END { print t }' "$home/events.log" 2>/dev/null)
  [[ -n "$last" && "$last" > "$fired" ]] && exit 0
  # So does a transcript that kept growing.
  if [ -n "$transcript" ] && [ -f "$transcript" ]; then
    moved=$(python3 -c 'import os,sys,time
print(1 if time.time() - os.path.getmtime(sys.argv[1]) < float(sys.argv[2]) - 2 else 0)' "$transcript" "$grace")
    [ "$moved" = 1 ] && exit 0
  fi
  guild status "$slug" stopped "turn ended without a report; peek to see why"
) >/dev/null 2>&1 &
disown
exit 0
