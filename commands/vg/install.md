---
name: vg:install
description: First-run / re-install / switch / repair the VG harness install target (global ~/.vgflow/ vs project .claude/) — wires hooks + writes .vg/.install-target marker.
argument-hint: "[--target=global|project|switch] [--repair]"
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
Resolve the VG harness install target for this project, then wire hooks via
`vg-cli-dispatcher.sh`. Modes:

- **First-run** (no marker, no legacy): ASK global vs project, recommended global.
- **Re-install** (marker present, no flags): silent re-install matching marker.
- **Switch** (`--target=switch` or explicit `--target=<other>`): backup project legacy → install new target → flip marker.
- **Repair** (`--repair`): re-detect, re-apply hooks for current marker (handles stale `~/.vgflow/` or settings.json drift).

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
echo "  --target arg:  ${TARGET:-(unset)}"
echo "  --repair:      ${REPAIR}"
```
</step>

<step name="1_decide_target">
**Decision matrix:**

| Marker | Legacy | --target | --repair | Action |
|---|---|---|---|---|
| absent | absent  | unset    | 0 | First-run → ASK |
| absent | present | unset    | 0 | Default to `project` (preserve legacy) |
| present | * | unset                  | 0 | Re-install matching marker silently |
| * | * | global\|project              | 0 | Switch to specified target |
| * | * | switch                      | 0 | Toggle current marker (global↔project) |
| * | * | *                            | 1 | Re-apply current target (repair) |

When ASK is required, present:
1. **Global (recommended)** — single-version install at `~/.vgflow/`, hooks at `~/.claude/settings.json` apply to all projects.
2. **Project (legacy)** — per-project `.claude/`, hooks at `${REPO_ROOT}/.claude/settings.json`.

```bash
if [ "$REPAIR" = "1" ]; then
  if [ -z "$CURRENT" ]; then
    echo "⛔ --repair requires existing marker. Run 'vg:install' first." >&2
    exit 1
  fi
  RESOLVED="$CURRENT"
elif [ "$TARGET" = "switch" ]; then
  if [ -z "$CURRENT" ]; then
    echo "⛔ --target=switch requires existing marker. Run 'vg:install' without --target first." >&2
    exit 1
  fi
  case "$CURRENT" in
    global)  RESOLVED="project" ;;
    project) RESOLVED="global"  ;;
    *)       echo "⛔ unknown current marker '$CURRENT'" >&2; exit 1 ;;
  esac
elif [ -n "$TARGET" ]; then
  case "$TARGET" in
    global|project) RESOLVED="$TARGET" ;;
    *) echo "⛔ invalid --target '$TARGET' (expected global|project|switch)" >&2; exit 1 ;;
  esac
elif [ -n "$CURRENT" ]; then
  RESOLVED="$CURRENT"
elif [ -f "$LEGACY_VERSION" ]; then
  echo "Legacy .claude/VGFLOW-VERSION detected; defaulting to project mode."
  RESOLVED="project"
else
  RESOLVED="ASK"
fi

echo "Resolved target: ${RESOLVED}"
```

If `RESOLVED=ASK`, use AskUserQuestion (or Codex inline) with these options:

- **Global (recommended)** — ~/.vgflow/ + ~/.claude/settings.json
- **Project (legacy)** — ./.claude/ + ./.claude/settings.json

After user answers, re-run from `2_apply` with `RESOLVED=<choice>`.
</step>

<step name="2_apply">
**Backup if switching.** When `--target=<other>` or `--target=switch` flips the marker, backup project legacy under `.vg/.backup-{date}/`:

```bash
NEED_BACKUP=0
if [ -n "$CURRENT" ] && [ "$CURRENT" != "$RESOLVED" ]; then
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
echo "  hooks at:  $([ "$RESOLVED" = "global" ] && echo "${HOME}/.claude/settings.json" || echo "${REPO_ROOT}/.claude/settings.json")"
[ "$NEED_BACKUP" = "1" ] && echo "  backup:    ${BACKUP_DIR}"
echo ""
echo "Restart Claude Code / Codex session to load updated hooks."
```
</step>

</process>

<success_criteria>
- `.vg/.install-target` written with `global` or `project` (matches resolved target)
- `settings.json` at the appropriate path contains VG hook entries
- On switch: backup directory `.vg/.backup-<ts>/` exists with snapshot of project `.claude/`
- `install.started` + `install.completed` telemetry events emitted
- Restart hint printed to stdout
</success_criteria>
