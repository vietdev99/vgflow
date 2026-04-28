---
name: vg:update
description: Pull latest VG release from GitHub, 3-way merge with local, park conflicts for /vg:reapply-patches
argument-hint: "[--check] [--accept-breaking] [--repo=vietdev99/vgflow]"
allowed-tools:
  - Bash
  - Read
  - Write
  - AskUserQuestion
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "update.started"
    - event_type: "update.completed"
---

<rules>
1. **Atomic** — VERSION file + ancestor dir rotated only after all merges complete.
2. **Non-destructive on conflict** — conflicted files are parked under `.claude/vgflow-patches/`, never clobber user edits.
3. **All logic in Python** — this markdown wraps `.claude/scripts/vg_update.py`; no version math / SHA / merge logic in bash.
4. **Honor repo override** — `--repo=owner/name` flag flows through to `vg_update.py`.
5. **Honor args literally** — use `${ARGUMENTS}`, never `$*`/`$@` to avoid arg splitting.
</rules>

<objective>
Sync local VG install (`.claude/commands/vg/`, `.claude/skills/`, `.claude/scripts/`, `.claude/templates/`)
to latest GitHub release of `vietdev99/vgflow`. Logic lives in `.claude/scripts/vg_update.py`.
High-level flow:

1. Preflight: verify `git`, `curl`, `python3`, helper script present.
2. `--check` mode → just print version state + exit.
3. Query `GET /repos/{repo}/releases/latest` via helper → compare with `.claude/VGFLOW-VERSION`.
4. Show changelog preview for versions `> installed, <= latest`.
5. Ask user to confirm.
6. Breaking-change gate: major bump requires `--accept-breaking` + shows migration doc.
7. Download tarball + verify SHA256 + extract to `.vgflow-cache/v{ver}/`.
8. Walk extracted tree, 3-way merge each file against `.claude/vgflow-ancestor/v{installed}/`.
9. Clean merges → apply; conflicts → `.claude/vgflow-patches/{rel}.conflict` + manifest entry.
10. Rotate ancestor dir + bump `.claude/VGFLOW-VERSION`.
11. Sync Codex mirrors directly from the updated release assets.
12. Verify/repair Claude + Codex Playwright MCP workers (`playwright1`..`playwright5`).
13. Verify/install Graphify tooling when `graphify.enabled=true`.
14. Report counts + restart reminder.
</objective>

<process>

<step name="0_preflight">
```bash
set -u

REPO_ROOT="$(pwd)"
ARGS="${ARGUMENTS:-}"

# Parse --repo= (defaults to vietdev99/vgflow)
REPO="$(printf '%s' "$ARGS" | grep -oE -- '--repo=[^ ]+' | sed 's/^--repo=//' | head -n1)"
REPO="${REPO:-vietdev99/vgflow}"

# Preflight tooling
command -v git      >/dev/null 2>&1 || { echo "git CLI required"; exit 1; }
command -v curl     >/dev/null 2>&1 || { echo "curl required"; exit 1; }
command -v python3  >/dev/null 2>&1 || { echo "python3 required"; exit 1; }

HELPER="${REPO_ROOT}/.claude/scripts/vg_update.py"
if [ ! -f "$HELPER" ]; then
  echo "vg_update.py missing at ${HELPER}"
  echo "Legacy install detected. Re-install vgflow first:"
  echo "  curl -fsSL https://raw.githubusercontent.com/${REPO}/main/install.sh | bash"
  exit 1
fi

echo "repo=${REPO}"
```
</step>

<step name="1_check_only_mode">
```bash
if printf '%s' "$ARGS" | grep -qE -- '(^|[[:space:]])--check([[:space:]]|$)'; then
  python3 "$HELPER" check --repo "$REPO"
  exit $?
fi
```
</step>

<step name="2_version_compare">
```bash
CHECK_OUTPUT="$(python3 "$HELPER" check --repo "$REPO")"
RC=$?
if [ $RC -ne 0 ]; then
  echo "Check failed (network offline or API error):"
  echo "$CHECK_OUTPUT"
  exit $RC
fi

INSTALLED="$(printf '%s' "$CHECK_OUTPUT" | grep -oE 'current=[^ ]+' | head -n1 | sed 's/^current=//')"
LATEST="$(printf   '%s' "$CHECK_OUTPUT" | grep -oE 'latest=[^ ]+'  | head -n1 | sed 's/^latest=//')"
STATE="$(printf    '%s' "$CHECK_OUTPUT" | grep -oE 'state=[^ ]+'   | head -n1 | sed 's/^state=//')"

echo "installed=${INSTALLED} latest=${LATEST} state=${STATE}"

case "$STATE" in
  up-to-date)
    echo "Already on v${INSTALLED}. Nothing to do."
    exit 0
    ;;
  ahead-of-release)
    echo "Local v${INSTALLED} is ahead of latest release v${LATEST} (dev build?). Nothing to do."
    exit 0
    ;;
  update-available)
    echo "Update available: v${INSTALLED} -> v${LATEST}"
    ;;
  *)
    echo "Unknown state: ${STATE}"
    exit 2
    ;;
esac
```
</step>

<step name="3_changelog_preview">
```bash
echo ""
echo "--- Changelog preview (v${INSTALLED} -> v${LATEST}) ---"
CHANGELOG_RAW="$(curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/CHANGELOG.md" 2>/dev/null || true)"

if [ -z "$CHANGELOG_RAW" ]; then
  echo "(CHANGELOG.md not reachable; skipping preview)"
else
  printf '%s\n' "$CHANGELOG_RAW" | INSTALLED="$INSTALLED" LATEST="$LATEST" python3 -c "
import os, re, sys

text = sys.stdin.read()
installed = os.environ.get('INSTALLED', '0.0.0')
latest    = os.environ.get('LATEST', '0.0.0')

def vt(v):
    try:
        return tuple(int(x) for x in v.lstrip('v').split('.'))
    except Exception:
        return (0, 0, 0)

inst_t = vt(installed)
late_t = vt(latest)

pattern = re.compile(r'## \[(\d+\.\d+\.\d+)\].*?(?=## \[|\Z)', re.S)
shown = False
for m in pattern.finditer(text):
    ver = m.group(1)
    t = vt(ver)
    if t > inst_t and t <= late_t:
        sys.stdout.write(m.group(0).rstrip() + '\n\n')
        shown = True
if not shown:
    sys.stdout.write('(no changelog entries between versions)\n')
"
fi
echo "-------------------------------------------------"
```

Then ask via AskUserQuestion:
- **question:** `"Proceed with update v${INSTALLED} -> v${LATEST}?"`
- **options:** `["Yes, update now", "No, cancel"]`

If user picks **No, cancel**, run:
```bash
echo "Cancelled. No changes applied."
exit 0
```
</step>

<step name="4_breaking_gate">
```bash
MAJOR_INSTALLED="$(printf '%s' "$INSTALLED" | cut -d. -f1)"
MAJOR_LATEST="$(printf    '%s' "$LATEST"    | cut -d. -f1)"

# Normalize non-numeric to 0
case "$MAJOR_INSTALLED" in *[!0-9]*|'') MAJOR_INSTALLED=0 ;; esac
case "$MAJOR_LATEST"    in *[!0-9]*|'') MAJOR_LATEST=0    ;; esac

# Additional deep-compat scan — catches breaking changes WITHIN a major
# (renamed step markers, dropped contract fields, removed scripts, etc.)
# compat-check.py reads latest RELEASE.md / CHANGELOG, grep against installed
# skill files, surface anything user needs to know regardless of major bump.
COMPAT_CHECK=".claude/scripts/compat-check.py"
if [ -f "$COMPAT_CHECK" ]; then
  echo ""
  echo "━━━ Deep compat scan (${INSTALLED} → ${LATEST}) ━━━"
  ${PYTHON_BIN:-python3} "$COMPAT_CHECK" \
    --from "$INSTALLED" --to "$LATEST" 2>&1 | head -50 \
    || echo "(compat-check returned non-zero — review output before proceeding)"
fi

if [ "$MAJOR_LATEST" -gt "$MAJOR_INSTALLED" ] && [ "$INSTALLED" != "0.0.0" ]; then
  MIG="migrations/v${MAJOR_INSTALLED}_to_v${MAJOR_LATEST}.md"
  echo ""
  echo "=== BREAKING CHANGE DETECTED ==="
  echo "  v${MAJOR_INSTALLED}.x -> v${MAJOR_LATEST}.x"
  echo ""
  echo "--- Migration doc: ${MIG} ---"
  curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/${MIG}" 2>/dev/null \
    || echo "(no migration doc found at that path -- review CHANGELOG manually)"
  echo "----------------------------"
  echo ""

  if ! printf '%s' "$ARGS" | grep -qE -- '(^|[[:space:]])--accept-breaking([[:space:]]|$)'; then
    echo "Breaking change requires opt-in. Re-run with --accept-breaking to proceed."
    exit 1
  fi
  echo "User opted in via --accept-breaking. Proceeding."
fi
```
</step>

<step name="5_fetch_tarball">
```bash
echo ""
echo "Fetching tarball..."
FETCH_OUT="$(python3 "$HELPER" fetch --repo "$REPO" 2>&1)"
RC=$?
printf '%s\n' "$FETCH_OUT"
if [ $RC -ne 0 ]; then
  echo "Fetch failed (rc=$RC)"
  exit $RC
fi

EXTRACTED="$(printf '%s' "$FETCH_OUT" | grep -oE 'EXTRACTED=[^ ]+' | head -n1 | sed 's/^EXTRACTED=//')"
if [ -z "$EXTRACTED" ] || [ ! -d "$EXTRACTED" ]; then
  echo "Could not determine extracted directory from fetch output."
  exit 3
fi
echo "Extracted: ${EXTRACTED}"
```
</step>

<step name="6_three_way_merge_per_file">
```bash
ANCESTOR_DIR="${REPO_ROOT}/.claude/vgflow-ancestor/v${INSTALLED}"
PATCHES_DIR="${REPO_ROOT}/.claude/vgflow-patches"
MANIFEST="${PATCHES_DIR}/.patches-manifest.json"
mkdir -p "$PATCHES_DIR"

UPDATED=0
NEW_FILES=0
CONFLICTS=0
FORCE_UPSTREAM=0
SKIPPED=0

# Issue #30: warn user up-front if ancestor stash missing — every file
# will be force-upstream-copied, no 3-way merge possible.
if [ ! -d "$ANCESTOR_DIR" ]; then
  echo "⚠ Ancestor stash missing: $ANCESTOR_DIR"
  echo "   Cannot perform true 3-way merge for any file."
  echo "   Files differing from upstream will be force-upgraded to upstream."
  echo "   Cause: prior install never snapshotted, OR VGFLOW-VERSION"
  echo "          mismatched ancestor stash version, OR previous failed update."
  echo ""

  # Issue #42 pre-flight integrity scan: count force-upstream-at-risk files
  # + show first N filenames so user can audit before silent overwrite.
  # Non-fatal — preflight always exits 0; we parse JSON to decide.
  PREFLIGHT_JSON="$(python3 "$HELPER" preflight \
    --extracted-root "$EXTRACTED" \
    --install-root   "${REPO_ROOT}/.claude" \
    --ancestor-dir   "$ANCESTOR_DIR" 2>&1)"
  AT_RISK="$(printf '%s' "$PREFLIGHT_JSON" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(d.get('force_upstream_count', 0))
except Exception:
    print(0)
")"
  if [ "${AT_RISK:-0}" -gt 0 ]; then
    echo "Pre-flight scan: ${AT_RISK} file(s) at risk of silent force-upstream overwrite."
    echo "First 10 (sorted):"
    printf '%s' "$PREFLIGHT_JSON" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    for f in d.get('force_upstream_files', [])[:10]:
        print('  - ' + f)
    extra = d.get('force_upstream_count', 0) - 10
    if extra > 0:
        print('  ... + {} more (run /vg:update --check-preflight to see all)'.format(extra))
except Exception:
    pass
"
    echo ""
    echo "  These files will be OVERWRITTEN with upstream content. Local edits lost."
    echo "  Recover post-update via: git diff HEAD~1 -- .claude/ | head -200"
    echo ""
  fi
fi

# Process substitution instead of pipe so counter vars persist in this shell
while IFS= read -r upstream_file; do
  # Strip the extracted root prefix to get the relative path inside the release
  REL="${upstream_file#$EXTRACTED/}"

  # Skip meta/install files that don't belong in user's .claude/
  case "$REL" in
    VERSION|CHANGELOG.md|README.md|LICENSE|install.sh|sync.sh|vg.config.template.md)
      SKIPPED=$((SKIPPED + 1))
      continue
      ;;
  esac

  # Map upstream path -> install path under .claude/
  case "$REL" in
    codex-skills/*|gemini-skills/*|templates/codex/*|templates/codex-agents/*)
      # Codex/Gemini mirrors are not Claude install files. They are deployed
      # in step 8 so /vg:update works for standard installs that do not carry
      # a checked-out vgflow/sync.sh beside the project.
      SKIPPED=$((SKIPPED + 1))
      continue
      ;;
    commands/*|skills/*|scripts/*|schemas/*|templates/vg/*)
      TARGET_REL=".claude/${REL}"
      ;;
    *)
      # Unknown top-level path — skip defensively; manual review wanted
      SKIPPED=$((SKIPPED + 1))
      continue
      ;;
  esac

  ABS_TARGET="${REPO_ROOT}/${TARGET_REL}"
  ABS_UPSTREAM="${upstream_file}"
  ABS_ANCESTOR="${ANCESTOR_DIR}/${REL}"

  if [ ! -f "$ABS_TARGET" ]; then
    # New file -> straight copy
    mkdir -p "$(dirname "$ABS_TARGET")"
    cp "$ABS_UPSTREAM" "$ABS_TARGET"
    NEW_FILES=$((NEW_FILES + 1))
    continue
  fi

  # 3-way merge via helper
  MERGE_STATUS="$(python3 "$HELPER" merge \
    --ancestor "$ABS_ANCESTOR" \
    --current  "$ABS_TARGET" \
    --upstream "$ABS_UPSTREAM" \
    --output   "${ABS_TARGET}.merged" 2>&1 | tail -n1)"

  if [ "$MERGE_STATUS" = "clean" ]; then
    mv "${ABS_TARGET}.merged" "$ABS_TARGET"
    UPDATED=$((UPDATED + 1))
  elif [ "$MERGE_STATUS" = "force-upstream" ]; then
    # Issue #30: ancestor missing → take upstream as authoritative.
    # Apply upstream + log distinct count so user sees we couldn't 3-way
    # merge. This is the safe default; without baseline 3-way merge is
    # impossible and user's intent in /vg:update is "give me new version".
    mv "${ABS_TARGET}.merged" "$ABS_TARGET"
    FORCE_UPSTREAM=$((FORCE_UPSTREAM + 1))
  else
    # Real conflict — git merge-file produced markers, park for /vg:reapply-patches
    PARKED="${PATCHES_DIR}/${REL}.conflict"
    mkdir -p "$(dirname "$PARKED")"
    mv "${ABS_TARGET}.merged" "$PARKED"

    REL="$REL" MANIFEST="$MANIFEST" REPO_ROOT="$REPO_ROOT" python3 -c "
import os, sys
from pathlib import Path
sys.path.insert(0, os.path.join(os.environ['REPO_ROOT'], '.claude', 'scripts'))
from vg_update import PatchesManifest
PatchesManifest(Path(os.environ['MANIFEST'])).add(os.environ['REL'], 'conflict')
"
    CONFLICTS=$((CONFLICTS + 1))
  fi
done < <(find "$EXTRACTED" -type f)

echo ""
echo "Merge pass done: updated=${UPDATED} new=${NEW_FILES} conflicts=${CONFLICTS} force_upstream=${FORCE_UPSTREAM} skipped_meta=${SKIPPED}"
if [ "$FORCE_UPSTREAM" -gt 0 ]; then
  echo "  ⚠ ${FORCE_UPSTREAM} file(s) force-upgraded to upstream because ancestor stash missing."
  echo "    Local edits to those files (if any) were OVERWRITTEN. Inspect with:"
  echo "      git diff HEAD -- .claude/ | head -100"
  echo "    Recover via git checkout if needed."
fi
```
</step>

<step name="6b_verify_gate_integrity">
**T8: post-merge hard-gate (cổng cứng) integrity check.**

After 3-way merge (gộp), download `gate-manifest.json` for the upstream release, re-hash every hard-gate block in the merged command files, and diff against the manifest SHA256. Mismatches get parked in `${PLANNING_DIR}/vgflow-patches/gate-conflicts.md` for resolution by `/vg:reapply-patches --verify-gates`.

Backward-compat (tương thích ngược): a 404 from the manifest URL (pre-v1.8.0 release) is a soft-skip with a warning — NOT a failure.

```bash
set +e  # Never let this step fail the whole /vg:update run
echo ""
echo "=== T8: verifying hard-gate integrity ==="

python3 "${REPO_ROOT}/.claude/scripts/vg_update.py" verify-gates \
  --manifest-version "${LATEST}" \
  --from-version "${INSTALLED}" \
  --merged-root "${REPO_ROOT}/.claude" \
  --output-dir "${REPO_ROOT}/${PLANNING_DIR}/vgflow-patches" \
  --phase ""
VG_INTEGRITY_RC=$?

case "$VG_INTEGRITY_RC" in
  0) echo "Gate integrity: OK (tất cả cổng nguyên vẹn)" ;;
  1) echo "Gate integrity: CONFLICTS (xung đột) — see ${PLANNING_DIR}/vgflow-patches/gate-conflicts.md" ;;
  2) echo "Gate integrity: SKIP — pre-v1.8.0 upstream has no gate-manifest (bỏ qua, tương thích ngược)" ;;
  *) echo "Gate integrity: ERROR rc=${VG_INTEGRITY_RC} — treating as non-fatal" ;;
esac
set -e
```
</step>

<step name="7_rotate_ancestor_and_version">
```bash
# Remove old ancestor (ignore missing)
rm -rf "${REPO_ROOT}/.claude/vgflow-ancestor/v${INSTALLED}"
mkdir -p "${REPO_ROOT}/.claude/vgflow-ancestor"

# Move extracted upstream tree into ancestor slot for the new version
NEW_ANCESTOR="${REPO_ROOT}/.claude/vgflow-ancestor/v${LATEST}"
rm -rf "$NEW_ANCESTOR"
mv "$EXTRACTED" "$NEW_ANCESTOR"

# Best-effort cleanup: .vgflow-cache leftover tarball + parent dirs
rm -rf "${REPO_ROOT}/.vgflow-cache" 2>/dev/null || true

# Bump VERSION file (atomic via tmp + mv)
echo "$LATEST" > "${REPO_ROOT}/.claude/VGFLOW-VERSION.tmp"
mv "${REPO_ROOT}/.claude/VGFLOW-VERSION.tmp" "${REPO_ROOT}/.claude/VGFLOW-VERSION"
echo "VGFLOW-VERSION = ${LATEST}"
```
</step>

<step name="7b_repair_hooks">
```bash
# Re-install/repair Claude Code hooks after scripts are merged. This matters
# because UserPromptSubmit seeds run-start, Stop verifies runtime_contract, and
# PostToolUse Bash step tracking writes hook.step_active telemetry into
# .vg/events.db. Without this, updates can silently leave stale hook wiring.
echo ""
echo "Repairing Claude enforcement hooks..."
HOOK_INSTALL="${REPO_ROOT}/.claude/scripts/vg-hooks-install.py"
HOOK_SELFTEST="${REPO_ROOT}/.claude/scripts/vg-hooks-selftest.py"
if [ -f "$HOOK_INSTALL" ]; then
  if python3 "$HOOK_INSTALL"; then
    echo "Claude hooks: installed/repaired"
    if [ -f "$HOOK_SELFTEST" ]; then
      if python3 "$HOOK_SELFTEST" >/dev/null 2>&1; then
        echo "Claude hooks: self-test PASS"
      else
        echo "⚠ Claude hooks: self-test failed; run python3 \"$HOOK_SELFTEST\""
      fi
    fi
  else
    echo "⚠ Claude hooks: install failed; run python3 \"$HOOK_INSTALL\""
  fi
else
  echo "⚠ Claude hooks: installer missing after update"
fi
```
</step>

<step name="8_sync_codex">
```bash
# Standard installs do NOT include vgflow/sync.sh. Deploy Codex mirrors
# directly from the rotated release ancestor so Claude and Codex update
# together without clobbering user-merged .claude files.
echo ""
echo "Syncing Codex mirror from updated release assets..."

CODEX_SOURCE="${NEW_ANCESTOR}"
CODEX_SKILLS_UPDATED=0
CODEX_AGENTS_UPDATED=0

if [ -d "${CODEX_SOURCE}/codex-skills" ]; then
  mkdir -p "${REPO_ROOT}/.codex/skills"
  while IFS= read -r skill_dir; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    skill="$(basename "$skill_dir")"
    rm -rf "${REPO_ROOT}/.codex/skills/${skill}"
    mkdir -p "${REPO_ROOT}/.codex/skills/${skill}"
    cp -R "$skill_dir"/. "${REPO_ROOT}/.codex/skills/${skill}/"
    CODEX_SKILLS_UPDATED=$((CODEX_SKILLS_UPDATED + 1))
  done < <(find "${CODEX_SOURCE}/codex-skills" -mindepth 1 -maxdepth 1 -type d | sort)
fi

if [ -d "${CODEX_SOURCE}/templates/codex-agents" ]; then
  mkdir -p "${REPO_ROOT}/.codex/agents"
  cp "${CODEX_SOURCE}/templates/codex-agents/"*.toml "${REPO_ROOT}/.codex/agents/" 2>/dev/null || true
  CODEX_AGENTS_UPDATED=$(ls "${REPO_ROOT}/.codex/agents/"*.toml 2>/dev/null | wc -l | tr -d ' ')
fi

if [ -d "${CODEX_SOURCE}/templates/codex" ]; then
  mkdir -p "${REPO_ROOT}/.codex"
  cp "${CODEX_SOURCE}/templates/codex/"* "${REPO_ROOT}/.codex/" 2>/dev/null || true
fi

codex_config_path() {
  local path="$1"
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$path"
  else
    printf '%s\n' "$path"
  fi
}

register_codex_agent() {
  local config="$1"
  local name="$2"
  local desc="$3"
  local config_file
  config_file="$(codex_config_path "$HOME/.codex/agents/${name}.toml")"
  if ! grep -q "^\[agents\.${name}\]" "$config" 2>/dev/null; then
    cat >> "$config" <<EOF

[agents.${name}]
description = "${desc}"
config_file = "${config_file}"
EOF
  fi
}

if [ -d "$HOME/.codex" ]; then
  mkdir -p "$HOME/.codex/skills" "$HOME/.codex/agents"
  if [ -d "${CODEX_SOURCE}/codex-skills" ]; then
    while IFS= read -r skill_dir; do
      [ -f "$skill_dir/SKILL.md" ] || continue
      skill="$(basename "$skill_dir")"
      rm -rf "$HOME/.codex/skills/${skill}"
      mkdir -p "$HOME/.codex/skills/${skill}"
      cp -R "$skill_dir"/. "$HOME/.codex/skills/${skill}/"
    done < <(find "${CODEX_SOURCE}/codex-skills" -mindepth 1 -maxdepth 1 -type d | sort)
  fi
  if [ -d "${CODEX_SOURCE}/templates/codex-agents" ]; then
    cp "${CODEX_SOURCE}/templates/codex-agents/"*.toml "$HOME/.codex/agents/" 2>/dev/null || true
  fi
  CODEX_CONFIG="$HOME/.codex/config.toml"
  touch "$CODEX_CONFIG"
  register_codex_agent "$CODEX_CONFIG" "vgflow-orchestrator" "VGFlow phase orchestrator for Codex. Coordinates VG skills, gates, and artifact writes."
  register_codex_agent "$CODEX_CONFIG" "vgflow-executor" "VGFlow bounded code executor for Codex child tasks."
  register_codex_agent "$CODEX_CONFIG" "vgflow-classifier" "VGFlow cheap classifier/scanner for read-only summaries and triage."
fi

echo "Codex mirror: skills=${CODEX_SKILLS_UPDATED} agents=${CODEX_AGENTS_UPDATED}"

if [ -f "${REPO_ROOT}/.claude/scripts/verify-codex-mirror-equivalence.py" ]; then
  VERIFY_OUT="${PATCHES_DIR}/codex-mirror-verify.json"
  if REPO_ROOT="${REPO_ROOT}" python3 "${REPO_ROOT}/.claude/scripts/verify-codex-mirror-equivalence.py" --json > "$VERIFY_OUT"; then
    echo "Codex mirror verify: PASS"
  else
    echo "⚠ Codex mirror verify: DRIFT — see ${VERIFY_OUT}"
    echo "   If conflicts were parked, resolve them with /vg:reapply-patches then run /vg:sync --verify."
    if [ "${CONFLICTS}" -eq 0 ]; then
      exit 1
    fi
  fi
fi
```
</step>

<step name="8b_repair_playwright_mcp">
```bash
echo ""
echo "Verifying Playwright MCP workers..."
MCP_VALIDATOR="${REPO_ROOT}/.claude/scripts/validators/verify-playwright-mcp-config.py"
LOCK_SOURCE="${NEW_ANCESTOR}/playwright-locks/playwright-lock.sh"
if [ -f "$MCP_VALIDATOR" ]; then
  if python3 "$MCP_VALIDATOR" --repair --lock-source "$LOCK_SOURCE"; then
    echo "Playwright MCP verify: PASS (Claude + Codex playwright1-5)"
  else
    echo "⛔ Playwright MCP verify failed."
    echo "   Fix settings, then run:"
    echo "   python3 \"$MCP_VALIDATOR\" --repair --lock-source \"$LOCK_SOURCE\""
    exit 1
  fi
else
  echo "⛔ Playwright MCP validator missing after update: $MCP_VALIDATOR"
  exit 1
fi
```
</step>

<step name="8c_ensure_graphify">
```bash
echo ""
echo "Verifying Graphify tooling..."
GRAPHIFY_HELPER="${REPO_ROOT}/.claude/scripts/ensure-graphify.py"
if [ "${VGFLOW_SKIP_GRAPHIFY_INSTALL:-false}" = "true" ]; then
  echo "Graphify verify: SKIP (VGFLOW_SKIP_GRAPHIFY_INSTALL=true)"
elif [ -f "$GRAPHIFY_HELPER" ]; then
  if python3 "$GRAPHIFY_HELPER" --target "$REPO_ROOT" --repair; then
    echo "Graphify verify: PASS (installed/configured or intentionally disabled)"
  else
    echo "⚠ Graphify verify failed."
    echo "   /vg:build can still use grep fallback unless graphify.fallback_to_grep=false."
    echo "   Manual repair: python3 \"$GRAPHIFY_HELPER\" --target \"$REPO_ROOT\" --repair"
  fi
else
  echo "⚠ Graphify helper missing after update: $GRAPHIFY_HELPER"
fi
```
</step>

<step name="9_report">
```bash
echo ""
echo "========================================"
echo "  VG update complete"
echo "  v${INSTALLED} -> v${LATEST}"
echo "----------------------------------------"
echo "  Files updated:    ${UPDATED}"
echo "  New files:        ${NEW_FILES}"
echo "  Conflicts parked: ${CONFLICTS}"
echo "  Skipped (meta):   ${SKIPPED}"
echo "========================================"

if [ "$CONFLICTS" -gt 0 ]; then
  echo ""
  echo "Resolve conflicts: /vg:reapply-patches"
  echo "Parked under:      .claude/vgflow-patches/"
fi

echo ""
echo "NOTE: Restart Claude Code session to load updated commands/skills."
```
</step>

</process>

<success_criteria>
- `/vg:update --check` prints `current=... latest=... state=...` and exits cleanly.
- Non-check run: shows changelog preview, asks confirmation, either applies or exits on cancel.
- Clean merges applied silently; conflicts parked to `.claude/vgflow-patches/{rel}.conflict` with manifest entry.
- Major-version bump blocked unless `--accept-breaking` is passed AND migration doc displayed.
- `.claude/VGFLOW-VERSION` bumped to `${LATEST}`; old `vgflow-ancestor/v{INSTALLED}` removed; new `vgflow-ancestor/v{LATEST}` populated.
- Claude Code hooks are installed/repaired after update (`UserPromptSubmit`, `Stop`, `PostToolUse` edit warning, `PostToolUse` Bash step tracker).
- Codex mirrors in `.codex/skills`, `.codex/agents`, and global `~/.codex` are refreshed directly from the updated release assets.
- Functional Codex mirror equivalence is verified after update; drift without merge conflicts fails the update.
- Playwright MCP workers are verified/repaired after update for both Claude and Codex (`playwright1`..`playwright5`) and stale hardcoded lock scripts are replaced.
- Graphify tooling is verified/repaired after update when `graphify.enabled=true`; missing package installs `graphifyy[mcp]`, `.mcp.json` is repaired, and `.graphifyignore` / `.gitignore` are maintained.
- Final report lists updated / new / conflict counts and suggests `/vg:reapply-patches` when relevant.
- Meta files (VERSION, CHANGELOG.md, README.md, LICENSE, install.sh, sync.sh, vg.config.template.md) never written to `.claude/`.
</success_criteria>
