---
name: vg:install
description: Install or repair VGFlow global-only harness at ~/.vgflow and prune project-local .claude/.codex VG files.
argument-hint: "[--target=global] [--repair]"
allowed-tools:
  - AskUserQuestion
  - Bash
  - Read
  - Write
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "install.started"
    - event_type: "install.completed"
---

<objective>
Install the VG harness globally for this project, then wire hooks via
`vg-cli-dispatcher.sh`.

Global-only contract:
- Workflow source lives in `~/.vgflow/`.
- Codex skills live in `~/.codex/skills`.
- Claude hooks live in `~/.claude/settings.json`.
- Codex hooks live in `~/.codex/hooks.json` and are enabled by `codex_hooks = true`.
- Project-local VG-owned `.claude/` and `.codex/` surfaces are pruned on every install/update.
- `.vg/.install-target` is written as `global`.

Architectural reference: docs/plans/2026-05-09-vg-global-install-design.md (Section 3 install + upgrade flow).
</objective>

<process>

<step name="0_parse_args">
```bash
set -u
ARGS="${ARGUMENTS:-}"

TARGET=""
REPAIR=0
for tok in $ARGS; do
  case "$tok" in
    --target=*) TARGET="${tok#--target=}" ;;
    --repair)   REPAIR=1 ;;
    *)          ;;
  esac
done

REPO_ROOT="$(pwd)"
MARKER="${REPO_ROOT}/.vg/.install-target"
LEGACY_VERSION="${REPO_ROOT}/.claude/VGFLOW-VERSION"
HOME_VGFLOW="${HOME}/.vgflow"

CURRENT=""
[ -f "$MARKER" ] && CURRENT="$(tr -d '[:space:]' < "$MARKER")"

echo "vg:install detect:"
echo "  cwd:           ${REPO_ROOT}"
echo "  marker:        ${CURRENT:-(absent)}"
echo "  ~/.vgflow/:    $([ -d "$HOME_VGFLOW" ] && echo present || echo absent)"
echo "  .claude/legacy: $([ -f "$LEGACY_VERSION" ] && echo "yes (v$(cat "$LEGACY_VERSION" 2>/dev/null))" || echo no)"
echo "  --target arg:  ${TARGET:-(unset; global-only)}"
echo "  --repair:      ${REPAIR}"
```
</step>

<step name="1_decide_target">
**Decision matrix:**

| Marker | Legacy | --target | --repair | Action |
|---|---|---|---|---|
| any | any | unset/global | any | Install global, prune project-local VG files, write marker=global |
| any | any | project/switch | any | Deprecated input; coerce to global and print warning |

```bash
if [ -n "$TARGET" ] && [ "$TARGET" != "global" ]; then
  echo "⚠ --target=${TARGET} is deprecated; VGFlow is global-only now. Coercing to global."
fi
RESOLVED="global"

echo "Resolved target: ${RESOLVED}"
```
</step>

<step name="2_apply">
**Backup legacy project harness before pruning.**

```bash
NEED_BACKUP=0
if [ -d "${REPO_ROOT}/.claude/commands/vg" ] || [ -d "${REPO_ROOT}/.codex/skills" ]; then
  NEED_BACKUP=1
fi

if [ "$NEED_BACKUP" = "1" ]; then
  TS="$(date -u +%Y%m%dT%H%M%SZ)"
  BACKUP_DIR="${REPO_ROOT}/.vg/.backup-${TS}"
  mkdir -p "$BACKUP_DIR"
  for d in .claude/commands .claude/skills .claude/scripts; do
    if [ -d "${REPO_ROOT}/${d}" ]; then
      cp -R "${REPO_ROOT}/${d}" "${BACKUP_DIR}/$(basename "$d")" 2>/dev/null || true
    fi
  done
  if [ -f "${REPO_ROOT}/.claude/settings.json" ]; then
    cp "${REPO_ROOT}/.claude/settings.json" "${BACKUP_DIR}/settings.json.bak" 2>/dev/null || true
  fi
  echo "vg:install backup: ${BACKUP_DIR}"
fi
```

**Apply target via dispatcher.** Resolve dispatcher path:

```bash
DISPATCHER=""
for candidate in \
  "${HOME_VGFLOW}/bin/vg-cli-dispatcher.sh" \
  "${VG_HOME:-}/bin/vg-cli-dispatcher.sh" \
  "${REPO_ROOT}/bin/vg-cli-dispatcher.sh"; do
  if [ -f "$candidate" ]; then
    DISPATCHER="$candidate"
    break
  fi
done

if [ -z "$DISPATCHER" ]; then
  echo "⛔ vg-cli-dispatcher.sh not found. Install vgflow first:"
  echo "  npm install -g vgflow"
  echo "  OR  git clone https://github.com/vietdev99/vgflow ~/.vgflow"
  exit 1
fi

VG_HOME="$(dirname "$(dirname "$DISPATCHER")")" \
  bash "$DISPATCHER" install "--${RESOLVED}"
```

The dispatcher writes the marker (Stage 4 wiring). Verify:

```bash
NEW_MARKER="$(tr -d '[:space:]' < "$MARKER" 2>/dev/null || true)"
if [ "$NEW_MARKER" != "$RESOLVED" ]; then
  echo "⚠ marker mismatch: expected ${RESOLVED}, got ${NEW_MARKER:-(absent)}"
  echo "  Re-running marker write directly..."
  mkdir -p "${REPO_ROOT}/.vg"
  printf '%s\n' "$RESOLVED" > "$MARKER"
fi

echo "vg:install applied: ${RESOLVED}"
```
</step>

<step name="3_complete">
Emit telemetry + summary:

```bash
${PYTHON_BIN:-python3} - <<EOF
import json, time, urllib.request, sys
ts = int(time.time() * 1000)
payload = {"target": "${RESOLVED}", "previous": "${CURRENT}", "repair": ${REPAIR}, "ts_ms": ts}
print(f"vg:install telemetry: {json.dumps(payload)}")
EOF

echo ""
echo "✓ vg:install complete"
echo "  target:    ${RESOLVED}"
echo "  marker:    ${MARKER}"
echo "  hooks at:  ${HOME}/.claude/settings.json"
echo "  codex:     ${HOME}/.codex/hooks.json"
[ "$NEED_BACKUP" = "1" ] && echo "  backup:    ${BACKUP_DIR}"
echo ""
echo "Restart Claude Code / Codex session to load updated hooks."
```
</step>

</process>

<success_criteria>
- `.vg/.install-target` written with `global`
- `~/.claude/settings.json` contains VG hook entries in global mode
- `~/.codex/hooks.json` contains VG hook entries in global mode
- Project-local VG-owned `.claude/` and `.codex/` files are removed or backed up
- `install.started` + `install.completed` telemetry events emitted
- Restart hint printed to stdout
</success_criteria>
