#!/usr/bin/env bash
# v3.0.1 — install a git pre-commit hook that rejects commits touching VGFlow
# harness files when the current repo is NOT the vgflow source repo. Catches
# Codex (and any other AI lacking PreToolUse hooks) via git-commit boundary.
#
# Usage:
#   bash install-pre-commit-harness-guard.sh           # install in current repo
#   bash install-pre-commit-harness-guard.sh /path     # install in <path>
#
# Idempotent. Safe to re-run. Refuses to install in vgflow source repo
# (where editing harness IS the workflow).
#
# Override per-commit via env: VG_HARNESS_DEV=1 git commit -m "..."

set -euo pipefail

target="${1:-$(pwd)}"
target="$(cd "$target" && pwd)"

if [ ! -d "${target}/.git" ]; then
  echo "⛔ ${target} is not a git repository" >&2
  exit 1
fi

# Detect: is this the vgflow source repo? Skip install (would block dev work).
if [ -f "${target}/package.json" ] && \
   grep -q '"name"[[:space:]]*:[[:space:]]*"vgflow"' "${target}/package.json" 2>/dev/null; then
  echo "✓ skipping install: ${target} is the vgflow source repo"
  exit 0
fi

hook_path="${target}/.git/hooks/pre-commit"

# Generate the pre-commit hook body. The body is self-contained — no external
# dependencies — so it works on machines without VG_HOME / vg-orchestrator.
cat > "$hook_path" <<'HOOK_BODY'
#!/usr/bin/env bash
# vgflow-harness-guard pre-commit hook (installed by install-pre-commit-harness-guard.sh)
# Rejects commits touching VGFlow harness files. Override: VG_HARNESS_DEV=1 git commit ...

set -euo pipefail

if [ "${VG_HARNESS_DEV:-0}" = "1" ]; then
  exit 0
fi

# Allow when current repo IS the vgflow source (defensive — install script
# refuses, but in case user copies hook between repos).
if [ -f package.json ] && grep -q '"name"[[:space:]]*:[[:space:]]*"vgflow"' package.json 2>/dev/null; then
  exit 0
fi

# Patterns matching VGFlow harness paths.
patterns=(
  '^\.claude/commands/vg/'
  '^\.claude/skills/vg-'
  '^\.claude/scripts/'
  '^\.claude/schemas/.*\.json$'
  '^\.claude/templates/vg/'
  '^\.codex/skills/'
  '^\.codex/agents/.*\.toml$'
)

# Get list of staged files (Added, Modified, Renamed).
staged="$(git diff --cached --name-only --diff-filter=AMR)"
if [ -z "$staged" ]; then
  exit 0
fi

violations=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  for pat in "${patterns[@]}"; do
    if [[ "$f" =~ $pat ]]; then
      violations="${violations}  ${f}\n"
      break
    fi
  done
done <<< "$staged"

if [ -n "$violations" ]; then
  printf "\033[38;5;208mvgflow-harness-guard: commit rejected\033[0m\n" >&2
  printf "Files in this commit modify VGFlow harness paths:\n" >&2
  printf "%b" "$violations" >&2
  cat >&2 <<'EOF'

These files are part of the VGFlow harness, not your project. Modifying
them in a dependent project corrupts the installation:
- /vg:update will conflict / clobber your changes during 3-way merge
- Other team members get inconsistent harness state

What to do:
- Upgrade harness:    /vg:update
- Customize harness:  fork https://github.com/vietdev99/vgflow, patch
                      canonical, then /vg:update --repo=<your-fork>
- Override THIS commit only: VG_HARNESS_DEV=1 git commit ...

Unstage harness files: git reset HEAD -- <files>
EOF
  exit 1
fi

exit 0
HOOK_BODY

chmod +x "$hook_path"
echo "✓ installed pre-commit harness guard at ${hook_path}"
echo "  override per-commit: VG_HARNESS_DEV=1 git commit ..."
