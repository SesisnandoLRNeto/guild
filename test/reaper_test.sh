#!/usr/bin/env bash
# The reaper's tests: finished quests lose their window and strays, busy and active ones do not.
#
# Same pattern as run.sh: a throwaway HOME, its own tmux socket, no model, no real fleet.
# Quests are written by hand (meta.json, status, a board) so no worktree or claude is needed.
set -uo pipefail

unset GUILD_QUEST GUILD_QM GUILD_ROLE GUILD_CALM GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL GH_TOKEN

REPO="$(cd "$(dirname "$0")/.." && pwd)"
GUILD="$REPO/bin/guild"
TMP="$(mktemp -d)"
export HOME="$TMP/home"
export GUILD_HOME="$HOME/.guild"
export GUILD_WORKTREES="$TMP/worktrees"
export GUILD_TMUX_SOCKET="guild-reap-test"
export GUILD_BOARD_NO_OPEN="1" GUILD_NO_NOTIFY="1" GUILD_NO_PR_SYNC="1"
export GUILD_REAP_AFTER=30
mkdir -p "$HOME" "$GUILD_HOME/quests" "$GUILD_HOME/local" "$GUILD_WORKTREES"
touch "$GUILD_HOME/events.log"

pass=0; fail=0
ok()   { pass=$((pass + 1)); printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf '  \033[31mFAIL\033[0m %s\n     %s\n' "$1" "${2:-}"; }
is()   { [ "$2" = "$3" ] && ok "$1" || bad "$1" "expected [$3], got [$2]"; }
has()  { case "$2" in *"$3"*) ok "$1" ;; *) bad "$1" "[$3] not found in: ${2:0:300}" ;; esac; }
hasnt(){ case "$2" in *"$3"*) bad "$1" "[$3] should not be there" ;; *) ok "$1" ;; esac; }
section() { printf '\n\033[1m%s\033[0m\n' "$1"; }
alive() { kill -0 "$1" 2>/dev/null; }
window() { tmux -L "$GUILD_TMUX_SOCKET" list-windows -t guild -F '#W' 2>/dev/null | grep -qx "$1" && echo yes || echo no; }

cleanup() {
  for f in "$TMP"/pids/*; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done
  tmux -L "$GUILD_TMUX_SOCKET" kill-server 2>/dev/null
  rm -rf "$TMP"
}
trap cleanup EXIT
mkdir -p "$TMP/pids"

OLD="2026-01-01T00:00:00"
quest() { # slug state status-time [ticket]
  local d="$GUILD_HOME/quests/$1" wt="$GUILD_WORKTREES/$1"
  mkdir -p "$d/boards/100" "$wt"
  printf '{"slug":"%s","repo":"%s/repo","harness":"claude","model":"sonnet","worktree":"%s","branch":"quest/%s","created":"2025-12-31T00:00:00","ticket":"%s"}\n' \
    "$1" "$TMP" "$wt" "$1" "${4:-}" > "$d/meta.json"
  printf '%s\t%s\t%s\n' "$2" "note" "$3" > "$d/status"
  echo '{"title":"wrap-up"}' > "$d/boards/100/board.json"
  printf '#!/bin/sh\nsleep 300\n' > "$d/launch.sh"
  tmux -L "$GUILD_TMUX_SOCKET" new-window -d -t guild -n "$1" "sleep 300"
}
stray() { # slug: a sleep left running with its cwd in the quest's worktree, parent gone (like nohup java)
  ( cd "$GUILD_WORKTREES/$1"; nohup sleep 3$RANDOM >/dev/null 2>&1 & echo $! > "$TMP/pids/$1" )
  for _ in 1 2 3 4 5 6 7 8 9 10; do   # until the fork has become the sleep
    case "$(ps -o command= -p "$(cat "$TMP/pids/$1")" 2>/dev/null)" in sleep*) break ;; esac
    sleep 0.2
  done
}

tmux -L "$GUILD_TMUX_SOCKET" new-session -d -s guild -n qm "sleep 300"

quest gone done "$OLD";            stray gone
quest working-q working "$OLD";    stray working-q
quest fresh done "$(date +%Y-%m-%dT%H:%M:%S)"; stray fresh
quest busy done "$OLD"
tmux -L "$GUILD_TMUX_SOCKET" kill-window -t guild:busy
tmux -L "$GUILD_TMUX_SOCKET" new-window -d -t guild -n busy "bash -c 'sleep 306 & wait'; true"
stray busy
sleep 0.5

section "dry run"
out=$("$GUILD" reap --dry-run 2>&1)
has "dry run names the window" "$out" "gone: would have closed its window"
has "dry run names the stray" "$out" "would have stopped sleep"
is "dry run keeps the window" "$(window gone)" yes
alive "$(cat "$TMP/pids/gone")" && ok "dry run keeps the stray" || bad "dry run keeps the stray"

section "the reap"
out=$("$GUILD" reap 2>&1)
has "says what it did" "$out" "gone: closed its window (gone), revivable"
has "says which process" "$out" "stopped sleep (pid $(cat "$TMP/pids/gone"))"
is "a done quest past the grace period loses its window" "$(window gone)" no
sleep 0.5
alive "$(cat "$TMP/pids/gone")" && bad "its stray process is dead" || ok "its stray process is dead"
is "a working quest keeps its window" "$(window working-q)" yes
alive "$(cat "$TMP/pids/working-q")" && ok "a working quest keeps its process" || bad "a working quest keeps its process"
is "a done quest inside the grace period keeps its window" "$(window fresh)" yes
alive "$(cat "$TMP/pids/fresh")" && ok "and its process" || bad "and its process"
is "a quest with a command running is left alone" "$(window busy)" yes
has "and it says why" "$out" "busy: skipped, a command is running in its window"
alive "$(cat "$TMP/pids/busy")" && ok "its process lives" || bad "its process lives"
hasnt "never touches the quartermaster window" "$out" "qm"
is "the qm window survives" "$(window qm)" yes
has "one reaped event is logged" "$(cat "$GUILD_HOME/events.log")" "gone	reaped"

section "paused and revivable"
has "the roster shows it paused" "$("$GUILD" roster)" "done (paused)"
hasnt "a working quest is not paused" "$("$GUILD" roster | grep working-q)" "paused"
is "the worktree stays" "$([ -d "$GUILD_WORKTREES/gone" ] && echo yes)" yes
is "the board stays" "$([ -f "$GUILD_HOME/quests/gone/boards/100/board.json" ] && echo yes)" yes
is "the quest is not archived" "$([ -d "$GUILD_HOME/quests/gone" ] && echo yes)" yes
out=$("$GUILD" revive 2>&1)
hasnt "a plain revive leaves paused quests alone" "$out" "revived gone"
out=$("$GUILD" revive gone 2>&1)
has "revive by name brings it back" "$out" "revived gone"
is "its window is back" "$(window gone)" yes
hasnt "and it is no longer paused" "$("$GUILD" roster | grep '^gone')" "paused"

section "a revived quest gets a new grace period"
out=$("$GUILD" reap 2>&1)
is "it is not reaped again at once" "$(window gone)" yes

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
