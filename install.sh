#!/usr/bin/env bash
# Link guild into ~/.claude and PATH, and create ~/.guild with its settings. Safe to run again.
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
GUILD_HOME="${GUILD_HOME:-$HOME/.guild}"
CLAUDE="$HOME/.claude"

mkdir -p "$GUILD_HOME/local" "$GUILD_HOME/quests" "$CLAUDE/agents" "$CLAUDE/skills"
chmod +x "$REPO"/bin/* "$REPO"/hooks/*.sh

# CLI: always your own ~/.local/bin, so the link never lands in a shared prefix.
BIN="$HOME/.local/bin"
mkdir -p "$BIN"
ln -sf "$REPO/bin/guild" "$BIN/guild"
echo "cli    -> $BIN/guild"
[[ ":$PATH:" == *":$BIN:"* ]] || echo "       ! $BIN is not on your PATH; add it to your shell profile"

ln -sf "$REPO/agents/quartermaster.md" "$CLAUDE/agents/quartermaster.md"; echo "agent  -> ~/.claude/agents/quartermaster.md"
for s in "$REPO"/skills/*/; do
  name=$(basename "$s"); ln -sfn "$s" "$CLAUDE/skills/$name"; echo "skill  -> ~/.claude/skills/$name"
done

# Per-session settings (loaded with --settings only by guild sessions, never globally)
cat > "$GUILD_HOME/worker-settings.json" <<EOF
{
  "permissions": { "allow": ["Bash(guild status:*)", "Bash(guild trial:*)", "Bash(guild board:*)"] },
  "hooks": {
    "PreToolUse": [{ "matcher": "Bash", "hooks": [{ "type": "command", "command": "$REPO/hooks/pr-gate.sh" }] }],
    "Stop": [{ "hooks": [{ "type": "command", "command": "$REPO/hooks/worker-stop.sh" }] }]
  }
}
EOF
cat > "$GUILD_HOME/qm-settings.json" <<EOF
{
  "permissions": { "allow": ["Bash(guild:*)"] }
}
EOF
echo "settings -> $GUILD_HOME/{worker,qm}-settings.json"

# The calm mod loads as a skills-dir plugin; it stays inert unless `guild calm on`.
ln -sfn "$REPO/mods/guild-calm" "$CLAUDE/skills/guild-calm"; echo "mod    -> ~/.claude/skills/guild-calm (enable with: guild calm on)"

for f in dispatch identities; do
  [ -f "$GUILD_HOME/local/$f.json" ] || { cp "$REPO/config/$f.example.json" "$GUILD_HOME/local/$f.json"; echo "config -> $GUILD_HOME/local/$f.json (edit it)"; }
done
echo "done. Start with: guild up"
