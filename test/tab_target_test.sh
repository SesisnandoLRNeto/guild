#!/usr/bin/env bash
# Opening a quest tab must not be confused by a window whose name starts with "guild".
#
# tmux reads a bare session name as a window target and prefix-matches window names, so with
# a window "guild-x" at index 1 the old `-t guild` tried index 1 and failed. Run it with:
#   test/tab_target_test.sh
set -uo pipefail

unset GUILD_QUEST GUILD_QM GUILD_ROLE GUILD_CALM GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL GH_TOKEN

REPO="$(cd "$(dirname "$0")/.." && pwd)"
GUILD="$REPO/bin/guild"
TMP="$(mktemp -d)"
export HOME="$TMP/home"
export GUILD_HOME="$HOME/.guild"
export GUILD_WORKTREES="$TMP/worktrees"
export GUILD_TMUX_SOCKET="guild-tab-test"
export GUILD_BOARD_PORT="4898"
export GUILD_BOARD_NO_OPEN="1"
export GUILD_NO_WHY="1"
export GUILD_NO_ACCEPTANCE="test fixture"
export GUILD_NO_PLAN="test fixture"
export GUILD_NO_NOTIFY="1"
export GUILD_NO_PR_SYNC="1"
export PATH="$TMP/stub:$PATH"
mkdir -p "$HOME" "$GUILD_HOME/local" "$GUILD_WORKTREES" "$TMP/stub"

pass=0; fail=0
ok()  { pass=$((pass + 1)); printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  \033[31mFAIL\033[0m %s\n     %s\n' "$1" "${2:-}"; }

cleanup() {
  tmux -L "$GUILD_TMUX_SOCKET" kill-server 2>/dev/null
  [ -f "$GUILD_HOME/.wartable-pid" ] && kill "$(cat "$GUILD_HOME/.wartable-pid")" 2>/dev/null
  rm -rf "$TMP"
}
trap cleanup EXIT

# ── fixtures ──────────────────────────────────────────────────────────────────
cat > "$TMP/stub/claude" <<'STUB'
#!/bin/sh
sleep 60
STUB
chmod +x "$TMP/stub/claude"

cat > "$GUILD_HOME/local/identities.json" <<'JSON'
{ "*": { "name": "Me", "email": "me@example.com", "gh_user": "my-acct" } }
JSON
cp "$REPO/config/pricing.example.json" "$GUILD_HOME/local/pricing.json"
cp "$REPO/config/dispatch.example.json" "$GUILD_HOME/local/dispatch.json"

REPO_A="$TMP/repo-a"
mkdir -p "$REPO_A" && git -C "$REPO_A" init -q -b main
git -C "$REPO_A" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$REPO_A" remote add origin "git@github.com:TestOrg/repo-a.git"

# The session has a window at index 1 whose name starts with "guild", the case that broke.
tmux -L "$GUILD_TMUX_SOCKET" new-session -d -s guild -n qm "sleep 600"
tmux -L "$GUILD_TMUX_SOCKET" new-window -d -t guild -n guild-x "sleep 600"

# ── a quest opens its tab next to a window named guild-x ─────────────────────
out=$(echo "do a thing" | "$GUILD" quest tabfix --repo "$REPO_A" --model sonnet 2>&1); code=$?
if [ "$code" -eq 0 ] && [ "${out#*create window failed}" = "$out" ] && [ "${out#*could not open tab}" = "$out" ]; then
  ok "a quest opens its window while guild-x exists"
else
  bad "a quest opens its window while guild-x exists" "exit $code: $out"
fi

if tmux -L "$GUILD_TMUX_SOCKET" list-windows -t guild -F '#W' | grep -qx tabfix; then
  ok "the tab is named after the quest"
else
  bad "the tab is named after the quest" "$(tmux -L "$GUILD_TMUX_SOCKET" list-windows -t guild -F '#W')"
fi

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
