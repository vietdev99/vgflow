---
name: "vg-update"
description: "Pull latest VG release from GitHub, 3-way merge with local, park conflicts for /vg:reapply-patches"
metadata:
  short-description: "Pull latest VG release from GitHub, 3-way merge with local, park conflicts for /vg:reapply-patches"
---

<codex_skill_adapter>
## Codex ⇆ Claude Code tool mapping

This skill was originally designed for Claude Code. When running in Codex CLI:

| Claude tool | Codex equivalent |
|------|------------------|
| AskUserQuestion | request_user_input (free-form text, or number-prefix choices) |
| Task (agent spawn) | Use `codex exec --model <model>` subprocess with isolated prompt |
| TaskCreate/TaskUpdate | N/A — use inline markdown headers and status narration |
| WebFetch | `curl -sfL` or `gh api` for GitHub URLs |
| Bash/Read/Write/Edit/Glob/Grep | Same — Codex supports these natively |

## Invocation

This skill is invoked by mentioning `$vg-update`. Treat all user text after `$vg-update` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


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
11. Sync codex/gemini mirrors via `vgflow/sync.sh` if present.
12. Report counts + restart reminder.
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
SKIPPED=0

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
    commands/*|skills/*|scripts/*|templates/*|codex-skills/*|gemini-skills/*)
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
  else
    # Conflict — park in patches dir + add to manifest
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
done < <(find "$EXTRACTED" -type f \( -name "*.md" -o -name "*.py" -o -name "*.yaml" -o -name "*.yml" -o -name "*.sh" -o -name "*.json" \))

echo ""
echo "Merge pass done: updated=${UPDATED} new=${NEW_FILES} conflicts=${CONFLICTS} skipped_meta=${SKIPPED}"
```
</step>

<step name="6b_verify_gate_integrity">
**T8: post-merge hard-gate (cổng cứng) integrity check.**

After 3-way merge (gộp), download `gate-manifest.json` for the upstream release, re-hash every hard-gate block in the merged command files, and diff against the manifest SHA256. Mismatches get parked in `.planning/vgflow-patches/gate-conflicts.md` for resolution by `/vg:reapply-patches --verify-gates`.

Backward-compat (tương thích ngược): a 404 from the manifest URL (pre-v1.8.0 release) is a soft-skip with a warning — NOT a failure.

```bash
set +e  # Never let this step fail the whole /vg:update run
echo ""
echo "=== T8: verifying hard-gate integrity ==="

python3 "${REPO_ROOT}/.claude/scripts/vg_update.py" verify-gates \
  --manifest-version "${LATEST}" \
  --from-version "${INSTALLED}" \
  --merged-root "${REPO_ROOT}/.claude" \
  --output-dir "${REPO_ROOT}/.planning/vgflow-patches" \
  --phase ""
VG_INTEGRITY_RC=$?

case "$VG_INTEGRITY_RC" in
  0) echo "Gate integrity: OK (tất cả cổng nguyên vẹn)" ;;
  1) echo "Gate integrity: CONFLICTS (xung đột) — see .planning/vgflow-patches/gate-conflicts.md" ;;
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

<step name="8_sync_codex">
```bash
# If project has a vgflow/sync.sh (codex + gemini mirror sync), run it
if [ -f "${REPO_ROOT}/vgflow/sync.sh" ]; then
  echo ""
  echo "Running vgflow/sync.sh --no-source ..."
  ( cd "$REPO_ROOT" && bash vgflow/sync.sh --no-source 2>&1 | tail -20 ) || echo "(sync.sh returned non-zero, continuing)"
else
  echo "(vgflow/sync.sh not present — skipping codex/gemini mirror sync)"
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
- `vgflow/sync.sh --no-source` invoked if present.
- Final report lists updated / new / conflict counts and suggests `/vg:reapply-patches` when relevant.
- Meta files (VERSION, CHANGELOG.md, README.md, LICENSE, install.sh, sync.sh, vg.config.template.md) never written to `.claude/`.
</success_criteria>
