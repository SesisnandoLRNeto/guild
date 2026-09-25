#!/usr/bin/env bash
# The quartermaster orchestrates; it does not code.
#
# Rule 1 in its instructions says so, but an instruction is a request. This hook is the
# rule: a write outside guild's own state is refused, so the only way for the
# quartermaster to change a project is to send a quest. Loaded only by qm-settings.json,
# so it never touches an adventurer or any other session.
set -uo pipefail

GUILD_HOME="${GUILD_HOME:-$HOME/.guild}"
input=$(cat)

read -r tool path < <(python3 -c '
import json, sys
try:
    row = json.load(sys.stdin)
except ValueError:
    print("? ?"); raise SystemExit
i = row.get("tool_input", {}) or {}
print(row.get("tool_name", "?"), i.get("file_path") or i.get("notebook_path") or i.get("path") or "?")
' <<<"$input")

case "$tool" in Edit|Write|NotebookEdit|MultiEdit) ;; *) exit 0 ;; esac
[ "$path" = "?" ] && exit 0

# Lessons need evidence and the guildmaster's yes: they go through `guild lesson propose`.
case "$path" in "$GUILD_HOME"/lessons.md|"$GUILD_HOME"/lessons-proposed.json)
  echo "Blocked: lessons are not written by hand. Propose one with quotes from two quests: guild lesson propose \"<lesson>\" --evidence \"<quest>: <quote>\" --evidence \"<quest>: <quote>\". The guildmaster accepts it on the docket." >&2
  exit 2 ;;
esac

# Guild's own state is always writable: briefs, boards, notes, its own config.
case "$path" in "$GUILD_HOME"/*) exit 0 ;; esac

# Anything else inside a git repository is project code, wherever it lives. A scratch
# file that belongs to no repo is fine.
dir="$path"
while [ ! -d "$dir" ] && [ "$dir" != "/" ]; do dir=$(dirname "$dir"); done
git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

cat >&2 <<EOF
Blocked: the quartermaster does not edit project code, and $path is project code.

Send a quest instead:
  guild quest <slug> --repo <repo path> [--model <m>] <<'EOF'
  Intent / Context / Acceptance / Constraints
  EOF

Guild's own state under $GUILD_HOME stays writable, and so does any file that belongs to no repo.
EOF
exit 2
