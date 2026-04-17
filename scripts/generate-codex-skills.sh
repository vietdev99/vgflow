#!/bin/bash
# Generate Codex skill files from Claude command files.
# Usage: ./scripts/generate-codex-skills.sh [--force]
#
# For each .claude/commands/vg/*.md that doesn't have a codex-skills/vg-X/SKILL.md,
# create one by wrapping the original content with codex adapter prelude.
#
# Codex skill format:
#   - frontmatter: name, description, metadata.short-description
#   - <codex_skill_adapter> block mapping AskUserQuestion → request_user_input,
#     Task → agent_spawn, etc.
#   - Rest of content copied verbatim from source command
#
# Skip if codex-skills/vg-X/SKILL.md already exists (unless --force).

set -e

FORCE=false
for arg in "$@"; do
  [ "$arg" = "--force" ] && FORCE=true
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"  # assume vgflow-repo is a sibling of dev RTB
DEV_ROOT="${DEV_ROOT:-$REPO_ROOT/RTB}"         # override via env if structure differs

# Find VG source commands
if [ -d "$DEV_ROOT/.claude/commands/vg" ]; then
  SOURCE_DIR="$DEV_ROOT/.claude/commands/vg"
elif [ -d "$REPO_ROOT/commands/vg" ]; then
  SOURCE_DIR="$REPO_ROOT/commands/vg"  # fallback to mirror
else
  echo "ERROR: Cannot find VG source commands. Set DEV_ROOT env var." >&2
  exit 1
fi

TARGET_DIR="$SCRIPT_DIR/../codex-skills"
mkdir -p "$TARGET_DIR"

GENERATED=0
SKIPPED=0

for src in "$SOURCE_DIR"/*.md; do
  [ -f "$src" ] || continue
  name=$(basename "$src" .md)
  # Skip partial/fragment files
  case "$name" in _*|*-insert) continue ;; esac

  target="$TARGET_DIR/vg-${name}/SKILL.md"

  if [ -f "$target" ] && [ "$FORCE" = "false" ]; then
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  mkdir -p "$(dirname "$target")"

  # Extract description from source frontmatter
  description=$(awk '/^description:/{gsub(/^description:\s*"?/,""); gsub(/"?\s*$/,""); print; exit}' "$src")

  # Write codex skill with adapter prelude
  cat > "$target" <<EOF
---
name: "vg-${name}"
description: "${description}"
metadata:
  short-description: "${description}"
---

<codex_skill_adapter>
## Codex ⇆ Claude Code tool mapping

This skill was originally designed for Claude Code. When running in Codex CLI:

| Claude tool | Codex equivalent |
|------|------------------|
| AskUserQuestion | request_user_input (free-form text, or number-prefix choices) |
| Task (agent spawn) | Use \`codex exec --model <model>\` subprocess with isolated prompt |
| TaskCreate/TaskUpdate | N/A — use inline markdown headers and status narration |
| WebFetch | \`curl -sfL\` or \`gh api\` for GitHub URLs |
| Bash/Read/Write/Edit/Glob/Grep | Same — Codex supports these natively |

## Invocation

This skill is invoked by mentioning \`\$vg-${name}\`. Treat all user text after \`\$vg-${name}\` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>

EOF

  # Append source content after frontmatter (skip first frontmatter block)
  awk '
    BEGIN { in_fm = 0; past_fm = 0 }
    /^---$/ {
      if (in_fm == 0 && past_fm == 0) { in_fm = 1; next }
      if (in_fm == 1) { in_fm = 0; past_fm = 1; next }
    }
    past_fm == 1 { print }
  ' "$src" >> "$target"

  GENERATED=$((GENERATED + 1))
  echo "✓ Generated: vg-${name}"
done

echo ""
echo "Summary: ${GENERATED} generated, ${SKIPPED} skipped (use --force to overwrite)"
