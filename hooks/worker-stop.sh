#!/usr/bin/env bash
# Stop hook for adventurers: if the turn ended while the quest still says "working",
# the adventurer stopped without reporting (question, error, or silent stop). Wake the quartermaster.
cat > /dev/null
slug="${GUILD_QUEST:-}"
[ -n "$slug" ] || exit 0
status_file="${GUILD_HOME:-$HOME/.guild}/quests/$slug/status"
[ -f "$status_file" ] || exit 0
state=$(cut -f1 "$status_file")
[ "$state" = "working" ] && guild status "$slug" stopped "turn ended without a report; peek to see why"
exit 0
