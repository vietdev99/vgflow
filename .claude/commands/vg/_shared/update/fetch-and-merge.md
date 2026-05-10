<!-- v2.73.0 T6-T10 extraction — verbatim step blocks from commands/vg/update.md -->
<!-- Group: fetch-and-merge | Steps: 5_fetch_tarball, 6_three_way_merge_per_file, 6b_verify_gate_integrity -->

<process>

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

# Self-bootstrap the updater: merge with the freshly downloaded helper, not
# the installed helper. This prevents stale/broken `.claude/scripts/vg_update.py`
# from deciding whether its own replacement is allowed to land.
MERGE_HELPER="${EXTRACTED}/scripts/vg_update.py"
if [ -f "$MERGE_HELPER" ]; then
  echo "Merge helper: upstream tarball vg_update.py"
else
  MERGE_HELPER="$HELPER"
  echo "Merge helper: installed vg_update.py (upstream helper missing)"
fi
MERGE_HELPER_DIR="$(dirname "$MERGE_HELPER")"
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
  MERGE_STATUS="$(python3 "$MERGE_HELPER" merge \
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

    REL="$REL" MANIFEST="$MANIFEST" REPO_ROOT="$REPO_ROOT" MERGE_HELPER_DIR="$MERGE_HELPER_DIR" python3 -c "
import os, sys
from pathlib import Path
sys.path.insert(0, os.environ.get('MERGE_HELPER_DIR') or os.path.join(os.environ['REPO_ROOT'], '.claude', 'scripts'))
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

CRITICAL_UPDATE_DRIFT=0
for rel in scripts/vg_update.py commands/vg/update.md commands/vg/reapply-patches.md; do
  if [ -f "${EXTRACTED}/${rel}" ] && [ -f "${REPO_ROOT}/.claude/${rel}" ] && ! cmp -s "${EXTRACTED}/${rel}" "${REPO_ROOT}/.claude/${rel}"; then
    echo "  ⛔ Core update file did not match upstream after merge: ${rel}"
    CRITICAL_UPDATE_DRIFT=1
  fi
done
if [ "$CRITICAL_UPDATE_DRIFT" -ne 0 ]; then
  echo "Refusing to bump VGFLOW-VERSION while core update tooling is stale."
  echo "Resolve parked conflicts with /vg:reapply-patches, or refresh install from the latest release."
  exit 4
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

python3 "${MERGE_HELPER}" verify-gates \
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

</process>
