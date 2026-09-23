#!/usr/bin/env bash
# The guild test suite.
#
# Everything runs against a throwaway HOME, a throwaway repo, its own tmux socket and a
# stub `claude`, so no model is ever called, nothing touches your real setup, and the
# whole run takes seconds. Run it with: test/run.sh
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
GUILD="$REPO/bin/guild"
TMP="$(mktemp -d)"
export HOME="$TMP/home"
export GUILD_HOME="$HOME/.guild"
export GUILD_WORKTREES="$TMP/worktrees"
export GUILD_TMUX_SOCKET="guild-test"
export GUILD_BOARD_PORT="4899"
export GUILD_BOARD_NO_OPEN="1"   # a test must never pop a browser tab
export PATH="$TMP/stub:$PATH"
mkdir -p "$HOME" "$GUILD_HOME/local" "$GUILD_WORKTREES" "$TMP/stub"

pass=0; fail=0
ok()   { pass=$((pass + 1)); printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf '  \033[31mFAIL\033[0m %s\n     %s\n' "$1" "${2:-}"; }
is()   { [ "$2" = "$3" ] && ok "$1" || bad "$1" "expected [$3], got [$2]"; }
has()  { case "$2" in *"$3"*) ok "$1" ;; *) bad "$1" "[$3] not found in: ${2:0:200}" ;; esac; }
hasnt(){ case "$2" in *"$3"*) bad "$1" "[$3] should not be there" ;; *) ok "$1" ;; esac; }
section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

cleanup() {
  tmux -L "$GUILD_TMUX_SOCKET" kill-server 2>/dev/null
  pkill -f "wartable.py daemon" 2>/dev/null
  rm -rf "$TMP"
}
trap cleanup EXIT

# ── fixtures ──────────────────────────────────────────────────────────────────
cat > "$TMP/stub/claude" <<'STUB'
#!/bin/sh
echo "STUB claude $*" > "$GUILD_HOME/last-claude-args"
sleep 60
STUB
cat > "$TMP/stub/gh" <<'STUB'
#!/bin/sh
echo "REAL GH: $*"
STUB
chmod +x "$TMP/stub/claude" "$TMP/stub/gh"

cat > "$GUILD_HOME/local/identities.json" <<'JSON'
{ "TestOrg": { "name": "Work Person", "email": "work@example.com", "gh_user": "work-acct" },
  "*": { "name": "Me", "email": "me@example.com", "gh_user": "my-acct" } }
JSON
cp "$REPO/config/pricing.example.json" "$GUILD_HOME/local/pricing.json"
cp "$REPO/config/dispatch.example.json" "$GUILD_HOME/local/dispatch.json"

REPO_A="$TMP/repo-a"
mkdir -p "$REPO_A" && git -C "$REPO_A" init -q -b main
git -C "$REPO_A" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
printf 'node_modules/\n' > "$REPO_A/.gitignore"
git -C "$REPO_A" add .gitignore
git -C "$REPO_A" -c user.email=t@t -c user.name=t commit -q -m "ignore build output"
git -C "$REPO_A" remote add origin "git@github.com:TestOrg/repo-a.git"
echo 25 > "$REPO_A/.java-version"   # untracked on purpose: that is the case that used to break

tmux -L "$GUILD_TMUX_SOCKET" new-session -d -s guild -n qm "sleep 600"

# ── quests ────────────────────────────────────────────────────────────────────
section "quests"
out=$(echo "do a thing" | "$GUILD" quest alpha --repo "$REPO_A" --model sonnet --ticket ABC-1 2>&1)
has "quest is created" "$out" "quest alpha"
[ -f "$GUILD_HOME/quests/alpha/brief.md" ] && ok "brief is stored" || bad "brief is stored"
WT=$(python3 -c "import json;print(json.load(open('$GUILD_HOME/quests/alpha/meta.json'))['worktree'])")
[ -d "$WT" ] && ok "worktree exists" || bad "worktree exists" "$WT"
has "it comes from the pool" "$WT" "/pool/repo-a-"
is "branch is quest/alpha" "$(git -C "$REPO_A" branch --list quest/alpha --format '%(refname:short)')" "quest/alpha"
is "ticket is recorded" "$(python3 -c "import json;print(json.load(open('$GUILD_HOME/quests/alpha/meta.json'))['ticket'])")" "ABC-1"
has "work identity comes from the remote owner" "$(cat "$GUILD_HOME/quests/alpha/launch.sh")" "work@example.com"
has "gh account matches the owner" "$(cat "$GUILD_HOME/quests/alpha/launch.sh")" "work-acct"
has "the shim is first on PATH" "$(cat "$GUILD_HOME/quests/alpha/launch.sh")" "bin/shims"
has "a window is opened for it" "$(tmux -L "$GUILD_TMUX_SOCKET" list-windows -t guild -F '#W')" "alpha"
is "an untracked toolchain pin is carried into the worktree" "$(cat "$WT/.java-version" 2>/dev/null)" "25"

out=$(echo x | "$GUILD" quest alpha --repo "$REPO_A" 2>&1); has "a duplicate slug is refused" "$out" "already exists"
out=$(echo x | "$GUILD" quest beta --repo "$REPO_A" --harness nope 2>&1); has "an unknown harness is refused" "$out" "unknown harness"
out=$(echo x | "$GUILD" quest "Bad Slug" --repo "$REPO_A" 2>&1); has "a bad slug is refused" "$out" "lowercase"
out=$(echo x | "$GUILD" quest gamma --repo "$TMP" 2>&1); has "a non-repo is refused" "$out" "not a git repo"

# ── status and events ─────────────────────────────────────────────────────────
section "status and events"
"$GUILD" status alpha working "reading the code" >/dev/null
is "state is written" "$(cut -f1 "$GUILD_HOME/quests/alpha/status")" "working"
has "an event is appended" "$(tail -1 "$GUILD_HOME/events.log")" "reading the code"
out=$("$GUILD" status alpha nonsense 2>&1); has "a bad state is refused" "$out" "bad state"
out=$("$GUILD" roster); has "the roster lists it" "$out" "alpha"
has "the count line reads" "$("$GUILD" roster --count)" "working"

# ── the war table ─────────────────────────────────────────────────────────────
section "war table"
out=$(GUILD_QUEST=alpha "$GUILD" ask "Which name?" --option "a=Alpha: first" --option "b=Beta: second" --recommend b --no-open 2>&1)
has "ask prints a url" "$out" "http://127.0.0.1:4899/b/alpha/"
board=$(ls "$GUILD_HOME/quests/alpha/boards" | head -1)
q=$(python3 -c "import json;q=json.load(open('$GUILD_HOME/quests/alpha/boards/$board/decisions.json'))['questions'][0];print(q['recommended'], [o['id'] for o in q['options']])")
has "both options survive" "$q" "['a', 'b']"
has "the recommendation is kept" "$q" "b "
page=$(cat "$GUILD_HOME/quests/alpha/boards/$board/content.html")
hasnt "the page css is not a format string" "$page" "{{"
has "the page shows the options" "$page" "Alpha"
is "the quest is waiting on you" "$(cut -f1 "$GUILD_HOME/quests/alpha/status")" "needs-decision"

curl -s -X POST "http://127.0.0.1:4899/b/alpha/$board/reply" -d '{"answers":{"choice":"a"},"message":"go with alpha"}' >/dev/null
sleep 1
is "answering puts the quest back to work" "$(cut -f1 "$GUILD_HOME/quests/alpha/status")" "working"
has "the answer is stored" "$(cat "$GUILD_HOME/quests/alpha/boards/$board/decision.json")" "go with alpha"
out=$(GUILD_QUEST=alpha "$GUILD" board wait "$board" --timeout 5)
has "wait returns the answer" "$out" "go with alpha"

# a decision cannot be escalated as plain text
"$GUILD" status alpha needs-decision "Should we rename the module?" >/dev/null 2>&1
boards=$(ls "$GUILD_HOME/quests/alpha/boards" | wc -l | tr -d ' ')
is "plain-text escalation builds a board" "$boards" "2"
out=$(curl -s "http://127.0.0.1:4899/b/alpha/$board/../../../etc/passwd")
hasnt "the server refuses path traversal" "$out" "root:"

# ── the trial gate ────────────────────────────────────────────────────────────
section "trial gate"
export GUILD_QUEST=alpha
run_shim() { (cd "$WT" && PATH="$REPO/bin/shims:$PATH" gh "$@" 2>&1); }
has "other gh commands pass through" "$(run_shim --version)" "REAL GH"
has "a PR with no trial is blocked" "$(run_shim pr create --title x)" "blocked"
(cd "$WT" && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m work)
(cd "$WT" && "$GUILD" trial pass "checks green" >/dev/null)
has "a PR after a passed trial goes through" "$(run_shim pr create --title x)" "REAL GH"
(cd "$WT" && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m more)
has "a stale trial blocks the PR" "$(run_shim pr create --title x)" "HEAD is"
(cd "$WT" && "$GUILD" trial skip "docs only" >/dev/null)
has "a skipped trial needs the note in the body" "$(run_shim pr create --body hello)" "Trial: skipped"
has "with the note it goes through" "$(run_shim pr create --body 'Trial: skipped - docs only')" "REAL GH"
out=$(cd "$WT" && "$GUILD" trial skip 2>&1); has "skip without a reason is refused" "$out" "reason"
echo '{"tool_input":{"command":"gh pr create"}}' | "$REPO/hooks/pr-gate.sh" >/dev/null 2>&1
is "the claude hook agrees with the shim" "$?" "2"
unset GUILD_QUEST

# ── the ledger ────────────────────────────────────────────────────────────────
section "wrap-up gate"
# alpha has commits by now, so "done" owes a report.
out=$("$GUILD" status alpha done "shipped it" 2>&1); has "a code quest cannot just say done" "$out" "wrap-up board"
hasnt "and it did not become done" "$(cut -f1 "$GUILD_HOME/quests/alpha/status")" "done"
out=$("$GUILD" status alpha done "docs only" --no-wrapup 2>&1)
is "--no-wrapup is an explicit way out" "$(cut -f1 "$GUILD_HOME/quests/alpha/status")" "done"
has "and it is recorded" "$(cut -f2 "$GUILD_HOME/quests/alpha/status")" "no wrap-up"

"$GUILD" status alpha working "back to it" >/dev/null
cat > "$TMP/wrap.html" <<'HTML'
<!doctype html><meta charset=utf-8><h1>What changed</h1><p>before and after</p>
HTML
out=$(GUILD_QUEST=alpha "$GUILD" board open --html "$TMP/wrap.html" --wrapup --title "alpha shipped" --no-open 2>&1)
has "a wrap-up board can be opened" "$out" "http://127.0.0.1:4899/b/alpha/"
is "a wrap-up does not park the quest on a decision" "$(cut -f1 "$GUILD_HOME/quests/alpha/status")" "working"
"$GUILD" status alpha done "shipped it" >/dev/null 2>&1
is "with a wrap-up, done goes through" "$(cut -f1 "$GUILD_HOME/quests/alpha/status")" "done"
"$GUILD" status alpha working "carrying on" >/dev/null   # later sections need it live

section "quartermaster guard"
guard() { echo "$1" | GUILD_HOME="$GUILD_HOME" "$REPO/hooks/qm-guard.sh" >/dev/null 2>&1; echo $?; }
is "a write into a repo is refused" "$(guard '{"tool_name":"Write","tool_input":{"file_path":"'"$REPO_A"'/src/X.java"}}')" "2"
is "editing guild itself is refused too" "$(guard '{"tool_name":"Edit","tool_input":{"file_path":"'"$REPO"'/bin/guild"}}')" "2"
is "guild state stays writable" "$(guard '{"tool_name":"Edit","tool_input":{"file_path":"'"$GUILD_HOME"'/local/dispatch.json"}}')" "0"
is "other tools are untouched" "$(guard '{"tool_name":"Bash","tool_input":{"command":"guild roster"}}')" "0"
is "reads are untouched" "$(guard '{"tool_name":"Read","tool_input":{"file_path":"'"$REPO_A"'/src/X.java"}}')" "0"
is "malformed input never blocks" "$(guard 'not json')" "0"

section "ledger"
# A synthetic session log with round numbers: sonnet 5 at $2/$10/$2.50/$0.20 per M.
proj="$HOME/.claude/projects/$(echo "$WT" | sed 's#/#-#g; s#\.#-#g')"
mkdir -p "$proj"
python3 - "$proj/session.jsonl" <<'PY'
import json, sys
rows = [{"type": "assistant", "timestamp": "2026-09-23T10:00:00Z",
         "message": {"model": "claude-sonnet-5",
                     "usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
                               "cache_creation_input_tokens": 1_000_000,
                               "cache_read_input_tokens": 1_000_000}}},
        {"type": "assistant", "timestamp": "2026-09-23T10:30:00Z",
         "message": {"model": "claude-sonnet-5", "usage": {"input_tokens": 0, "output_tokens": 0}}}]
open(sys.argv[1], "w").write("\n".join(json.dumps(r) for r in rows))
PY
out=$("$GUILD" cost alpha)
has "cost is priced from the session log" "$out" '$14.70'   # 2 + 10 + 2.50 + 0.20
has "the model is named" "$out" "claude-sonnet-5"
has "duration is measured" "$out" "30m"
out=$("$GUILD" cost)
has "the total adds up" "$out" "total"
out=$("$GUILD" log alpha)
has "history shows the brief" "$out" "do a thing"
has "history shows the decision" "$out" "go with alpha"
has "history shows the trial" "$out" "skip"
out=$("$GUILD" retro --since 30d --json)
is "retro counts the overruled call" "$(echo "$out" | python3 -c 'import json,sys;print(json.load(sys.stdin)["totals"]["recommendation_overruled"])')" "1"
is "retro counts the skipped trial" "$(echo "$out" | python3 -c 'import json,sys;print(json.load(sys.stdin)["totals"]["trials_skipped"])')" "1"
is "retro keeps the ticket" "$(echo "$out" | python3 -c 'import json,sys;print(json.load(sys.stdin)["quests"][0]["ticket"])')" "ABC-1"

# ── revive and close ──────────────────────────────────────────────────────────
section "revive and close"
tmux -L "$GUILD_TMUX_SOCKET" kill-window -t guild:alpha 2>/dev/null
out=$("$GUILD" revive 2>&1)
has "an orphan quest is revived" "$out" "revived alpha"
has "its window is back" "$(tmux -L "$GUILD_TMUX_SOCKET" list-windows -t guild -F '#W')" "alpha"
has "the revived launch continues instead of restarting" "$(cat "$GUILD_HOME/quests/alpha/launch.sh")" "continue"

mkdir -p "$WT/node_modules" && echo cached > "$WT/node_modules/dep.txt"   # ignored build output
echo "work in progress" > "$WT/unsaved.txt"
out=$("$GUILD" close alpha 2>&1); has "a dirty worktree is protected" "$out" "uncommitted"
[ -d "$GUILD_HOME/quests/alpha" ] && ok "a protected quest stays live" || bad "a protected quest stays live"
"$GUILD" close alpha --force >/dev/null 2>&1
[ -d "$GUILD_HOME/quests/alpha" ] && bad "the quest is archived" "still live" || ok "the quest is archived"
archived=$(ls "$GUILD_HOME/quests/_archive" | head -1)
[ -f "$GUILD_HOME/quests/_archive/$archived/ledger.json" ] && ok "its cost is frozen on close" || bad "its cost is frozen on close"
has "history keeps the frozen cost" "$("$GUILD" cost)" '$14.70'

section "worktree pool"
[ -d "$WT" ] && ok "closing returns the slot instead of deleting it" || bad "closing returns the slot instead of deleting it"
is "the build cache survives" "$(cat "$WT/node_modules/dep.txt" 2>/dev/null)" "cached"
is "tracked leftovers are gone" "$([ -e "$WT/unsaved.txt" ] && echo present || echo gone)" "gone"
is "the slot holds no branch" "$(git -C "$WT" symbolic-ref -q --short HEAD || echo detached)" "detached"
has "the pool lists it as free" "$("$GUILD" pool list)" "free"

out=$(echo "second quest" | "$GUILD" quest beta --repo "$REPO_A" --model sonnet 2>&1)
has "the next quest reuses the warm slot" "$out" "reused"
WT2=$(python3 -c "import json;print(json.load(open('$GUILD_HOME/quests/beta/meta.json'))['worktree'])")
is "it is the same slot" "$WT2" "$WT"
is "and it is still warm" "$(cat "$WT2/node_modules/dep.txt" 2>/dev/null)" "cached"
is "on the new quest branch" "$(git -C "$WT2" symbolic-ref --short HEAD)" "quest/beta"
has "the pool now lists it busy" "$("$GUILD" pool list)" "busy"

out=$(echo "isolated" | "$GUILD" quest gamma --repo "$REPO_A" --fresh --model sonnet 2>&1)
WT3=$(python3 -c "import json;print(json.load(open('$GUILD_HOME/quests/gamma/meta.json'))['worktree'])")
hasnt "--fresh stays out of the pool" "$WT3" "/pool/"
"$GUILD" close gamma --force >/dev/null 2>&1
[ -d "$WT3" ] && bad "a fresh worktree is removed on close" || ok "a fresh worktree is removed on close"

out=$("$GUILD" pool drop 2>&1); has "a busy slot is not dropped" "$out" "in use"
"$GUILD" close beta --force >/dev/null 2>&1
out=$("$GUILD" pool drop 2>&1); has "a free slot can be dropped" "$out" "dropped"

# ── doctor ────────────────────────────────────────────────────────────────────
section "doctor"
out=$("$GUILD" doctor 2>&1); code=$?
has "doctor reports the tools" "$out" "tmux"
has "doctor checks the identities" "$out" "TestOrg"
rm "$GUILD_HOME/local/dispatch.json"
out=$("$GUILD" doctor 2>&1); code=$?
is "doctor fails when config is missing" "$code" "1"
has "doctor names what is missing" "$out" "dispatch.json"

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
