<!-- v2.73.0 T6-T10 extraction — verbatim step blocks from commands/vg/update.md -->
<!-- Group: rotate-and-repair | Steps: 7_rotate_ancestor_and_version, 7b_repair_hooks -->

<process>

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
# Re-install/repair Claude Code hooks after scripts are merged.
#
# v2.50.x migration note: old installs may have VG hooks in BOTH
# .claude/settings.json (new scripts/hooks runner) and .claude/settings.local.json
# (legacy vg-entry-hook.py/vg-step-tracker.py/vg-verify-claim.py). Claude Code
# loads both files, so double hooks can create duplicate UserPromptSubmit,
# Stop, PreToolUse, and PostToolUse work and mis-bind hook.step_active
# telemetry across concurrent sessions. Update must actively prune legacy VG
# hooks from settings.local.json, not just install new hooks. Canonical hook
# telemetry still writes .vg/events.db after repair.
echo ""
echo "Repairing Claude enforcement hooks..."
HOOK_INSTALL="${REPO_ROOT}/.claude/scripts/hooks/install-hooks.sh"
UNINSTALL_HELPER="${REPO_ROOT}/.claude/scripts/vg_uninstall.py"

if [ -f "$HOOK_INSTALL" ]; then
  if bash "$HOOK_INSTALL" --target "${REPO_ROOT}/.claude/settings.json"; then
    echo "Claude hooks: canonical settings.json installed/repaired"
  else
    echo "⚠ Claude hooks: install failed; run bash \"$HOOK_INSTALL\" --target .claude/settings.json"
  fi
else
  echo "⚠ Claude hooks: canonical installer missing after update"
fi

LOCAL_SETTINGS="${REPO_ROOT}/.claude/settings.local.json"
if [ -f "$LOCAL_SETTINGS" ] && [ -f "$UNINSTALL_HELPER" ]; then
  PRUNE_OUT="$(python3 "$UNINSTALL_HELPER" prune-hooks --settings "$LOCAL_SETTINGS" --apply 2>/dev/null || true)"
  case "$PRUNE_OUT" in
    changed) echo "Claude hooks: pruned legacy VG entries from .claude/settings.local.json" ;;
  esac
fi
```
</step>

</process>
