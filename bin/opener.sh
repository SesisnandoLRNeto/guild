#!/usr/bin/env bash
# Open a page in the guildmaster's browser, from any caller.
#
#   opener.sh open URL   what guild and the war table call. When the GUI-session agent
#                        (com.guild.opener, see `guild opener install`) is loaded, the URL goes
#                        into a queue folder and launchd opens it from the login session. A caller
#                        inside a detached tmux cannot run `open` itself (error -600). Without the
#                        agent it tries `open` / `xdg-open` right here.
#   opener.sh drain      what the agent runs: open every queued URL, then delete the file.
#
# A failed open is never silent: one line goes to events.log.
set -u
GUILD_HOME="${GUILD_HOME:-$HOME/.guild}"
QUEUE="$GUILD_HOME/open-queue"
LABEL="com.guild.opener"

log_failure() { # url
  printf '%s\tguild\topen-failed\tcould not open the page: %s\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$1" >> "$GUILD_HOME/events.log"
}

open_here() { # url
  if command -v open >/dev/null 2>&1; then open "$1" >/dev/null 2>&1
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1
  else return 1; fi
}

agent_loaded() {
  [ "$(uname)" = Darwin ] && command -v launchctl >/dev/null 2>&1 &&
    launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1
}

case "${1:-}" in
  open)
    url="${2:-}"; [ -n "$url" ] || exit 2
    [ -z "${GUILD_BOARD_NO_OPEN:-}" ] || exit 0
    if agent_loaded; then
      mkdir -p "$QUEUE" && printf '%s\n' "$url" > "$QUEUE/.$$.tmp" && mv "$QUEUE/.$$.tmp" "$QUEUE/$(date +%s)-$$-$RANDOM.url" && exit 0
    fi
    open_here "$url" || { log_failure "$url"; exit 1; }
    ;;
  drain)
    mkdir -p "$QUEUE"
    for f in "$QUEUE"/*.url; do
      [ -f "$f" ] || continue
      url=$(head -n1 "$f"); rm -f "$f"
      [ -n "$url" ] && { open_here "$url" || log_failure "$url"; }
    done
    ;;
  *) echo "usage: opener.sh open URL | drain" >&2; exit 2 ;;
esac
