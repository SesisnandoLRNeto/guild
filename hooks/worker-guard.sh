#!/usr/bin/env bash
# An adventurer does not grade its own homework.
#
# The acceptance contract (brief.md, acceptance.json) is sealed when the quest starts and
# belongs to the guildmaster. This refuses edits to those files and the reseal command in
# adventurer sessions. guild check also verifies the seal's hash, so a harness without
# hooks still cannot pass on a quietly weakened contract.
set -uo pipefail
q="${GUILD_HOME:-$HOME/.guild}/quests/${GUILD_QUEST:-}"
[ -n "${GUILD_QUEST:-}" ] || exit 0
input=$(cat)
read -r tool target < <(python3 -c '
import json, sys
try:
    row = json.load(sys.stdin)
except ValueError:
    print("? ?"); raise SystemExit
i = row.get("tool_input", {}) or {}
t = row.get("tool_name", "?")
v = i.get("command") if t == "Bash" else (i.get("file_path") or i.get("notebook_path") or "")
print(t, (v or "?").replace("\n", " "))
' <<<"$input")

# The budget: past the quest's dollar cap, every tool waits for the guildmaster, except the
# guild commands the adventurer needs to ask and to wait for the answer.
case "$tool:$target" in
  Bash:guild\ *|Bash:*/guild\ *) ;;
  *)
    if msg=$(python3 "$(dirname "$(readlink -f "$0")")/../bin/budget.py" check "$GUILD_QUEST" 2>/dev/null); then :; else
      [ $? = 3 ] && { echo "Blocked: $msg" >&2; exit 2; }
    fi ;;
esac

case "$tool" in
  Edit|Write|MultiEdit|NotebookEdit)
    case "$target" in
      "$q/brief.md"|"$q/acceptance.json"|"$q/meta.json")
        echo "Blocked: the brief and its acceptance checks belong to the guildmaster. If a check is wrong, put it on the war table (guild ask) instead of changing it." >&2
        exit 2 ;;
    esac ;;
  Bash)
    case "$target" in
      *"--reseal"*)
        echo "Blocked: only the guildmaster reseals acceptance. Escalate with guild ask." >&2
        exit 2 ;;
    esac ;;
esac
exit 0
