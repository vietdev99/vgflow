---
name: vg:recover
description: Guided recovery for stuck/corrupted phases — classifies corruption type + prints safe recovery commands. Add --apply for assisted execution.
argument-hint: "{phase} [--apply]"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "recover.started"
    - event_type: "recover.completed"
---

<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Markdown headers for progress. Long Bash > 30s → `run_in_background: true`.

**Translate English terms (RULE)** — first-occurrence English term phải có giải thích VN trong ngoặc. Ví dụ: `recovery (khôi phục)`, `corruption (hư hỏng)`, `manifest (kê khai)`, `stuck (tắc nghẽn)`, `hash mismatch (lệch băm)`, `rollback (quay lui)`, `artifact (tạo phẩm)`. Không áp dụng: file path, code ID.
</NARRATION_POLICY>

<rules>
1. **Suggest-only by default** — prints recovery commands. Does NOT execute anything destructive unless `--apply` + second user confirm.
2. **--apply requires AskUserQuestion confirm** — even safe helpers get a "proceed? yes/no" prompt before running.
3. **Phase arg mandatory** — `/vg:recover` without phase → exit 1 with usage hint.
4. **Delegate classification to `artifact_manifest_validate`** — exit code + stderr pattern selects recovery template.
5. **Never call `git reset --hard`, `rm -rf`, `git push --force`** — always print those as user-run commands, never execute.
6. **Emit single `recover_run` event** per invocation.
</rules>

<objective>
Answer: "How do I un-break phase X?"

Classifies corruption into 6 types (clean / legacy-no-manifest / manifest-self-corruption / missing-artifacts / hash-mismatch / unknown-corruption), maps each to a safe recovery template, and prints it. `--apply` mode runs ONLY non-destructive helpers (re-read triggers, progress checks) after confirm.
</objective>

<process>

<step name="0_parse_load">
## Step 0: Parse args + load helpers

```bash
PLANNING_DIR=".planning"
PHASES_DIR="${PLANNING_DIR}/phases"
PYTHON_BIN="${PYTHON_BIN:-python3}"

source .claude/commands/vg/_shared/lib/artifact-manifest.sh 2>/dev/null || {
  echo "⛔ artifact-manifest.sh missing — cannot classify corruption" >&2
  exit 1
}
source .claude/commands/vg/_shared/lib/telemetry.sh 2>/dev/null || true

PHASE_ARG=""
APPLY_FLAG=false
for arg in $ARGUMENTS; do
  case "$arg" in
    --apply) APPLY_FLAG=true ;;
    --*)     echo "⚠ Unknown flag: $arg" ;;
    *)       PHASE_ARG="$arg" ;;
  esac
done

if [ -z "$PHASE_ARG" ]; then
  echo "⛔ /vg:recover requires {phase} argument"
  echo "   Usage: /vg:recover 07.12 [--apply]"
  echo "   Scan corrupted phases first: /vg:integrity"
  exit 1
fi

export VG_CURRENT_COMMAND="vg:recover"
type telemetry_init >/dev/null 2>&1 && telemetry_init

echo ""
echo "🔧 ━━━ /vg:recover — phase ${PHASE_ARG} ━━━"
[ "$APPLY_FLAG" = "true" ] && echo "   Mode: --apply (will prompt before safe helpers)"
[ "$APPLY_FLAG" = "false" ] && echo "   Mode: suggest-only (prints commands, runs nothing)"
echo ""

# Resolve phase dir
phase_dir=""
for d in "${PHASES_DIR}"/*; do
  [ -d "$d" ] || continue
  base=$(basename "$d")
  if [[ "$base" == "${PHASE_ARG}"* ]] || [[ "$base" == "${PHASE_ARG}-"* ]]; then
    phase_dir="$d"; break
  fi
done

if [ -z "$phase_dir" ]; then
  echo "⛔ Phase ${PHASE_ARG} not found. Run /vg:health to list phases."
  exit 1
fi
```
</step>

<step name="1_classify">
## Step 1: Classify corruption type

```bash
echo "## Detecting corruption type"
echo ""

corruption_type="unknown"
corruption_detail=""

val_output=$(artifact_manifest_validate "$phase_dir" 2>&1)
val_rc=$?
case $val_rc in
  0)
    corruption_type="clean"
    corruption_detail="Manifest valid. No file-level corruption."
    ;;
  1)
    corruption_type="legacy-no-manifest"
    corruption_detail="Missing .artifact-manifest.json (legacy phase)."
    ;;
  2)
    if echo "$val_output" | grep -q "ARTIFACT MISSING"; then
      corruption_type="missing-artifacts"
    elif echo "$val_output" | grep -q "ARTIFACT CORRUPTION"; then
      corruption_type="hash-mismatch"
    elif echo "$val_output" | grep -q "MANIFEST CORRUPTION"; then
      corruption_type="manifest-self-corruption"
    else
      corruption_type="unknown-corruption"
    fi
    corruption_detail="$val_output"
    ;;
esac

# Pipeline staleness check
stuck="no"
pipeline_state="${phase_dir}/PIPELINE-STATE.json"
if [ -f "$pipeline_state" ]; then
  stuck=$(${PYTHON_BIN} - "$pipeline_state" <<'PY' 2>/dev/null
import json, sys, os, datetime
try:
  s = json.loads(open(sys.argv[1], encoding='utf-8').read())
  mtime = os.path.getmtime(sys.argv[1])
  age_hours = (datetime.datetime.now().timestamp() - mtime) / 3600
  last_step = s.get("last_step") or s.get("current_step") or "?"
  if age_hours > 24 and last_step not in ("accept", "done"):
    print(f"stuck@{last_step}(age {int(age_hours)}h)")
  else:
    print("no")
except:
  print("no")
PY
)
fi

echo "  Type:     **${corruption_type}**"
[ "$stuck" != "no" ] && echo "  Pipeline: ${stuck}"
echo ""
[ -n "$corruption_detail" ] && echo "$corruption_detail" | sed 's/^/  /'
echo ""
```
</step>

<step name="2_suggest">
## Step 2: Print recovery template for classified type

```bash
echo "## Suggested recovery commands"
echo ""
case "$corruption_type" in
  clean)
    echo "  ✓ No corruption. Nothing to recover."
    if [ "$stuck" != "no" ]; then
      echo "  Pipeline appears ${stuck}:"
      echo "    /vg:next ${PHASE_ARG}       # auto-advance to next step"
      echo "    /vg:progress ${PHASE_ARG}   # inspect current state"
    fi
    ;;
  legacy-no-manifest)
    echo "  Manifest auto-backfills on next read (no action required)."
    echo "  Force explicit backfill:"
    echo "    /vg:progress ${PHASE_ARG}"
    ;;
  manifest-self-corruption)
    echo "  Manifest file tampered/corrupted. Regenerate via the producer command:"
    echo "    /vg:blueprint ${PHASE_ARG}   # if PLAN/CONTRACTS/TEST-GOALS exist"
    echo "    /vg:review ${PHASE_ARG}      # if RUNTIME-MAP exists"
    ;;
  missing-artifacts)
    echo "  Files referenced by manifest are gone. Choose one:"
    echo "    /vg:blueprint ${PHASE_ARG}   # regenerate from scratch"
    echo "    git checkout HEAD -- ${phase_dir}/   # restore from last commit"
    ;;
  hash-mismatch)
    echo "  Artifact content changed after manifest write (manual edit suspected)."
    echo "  Option 1 — keep edits, refresh manifest:"
    echo "    /vg:blueprint ${PHASE_ARG}"
    echo "  Option 2 — revert to manifest version:"
    echo "    git checkout ${phase_dir}/"
    ;;
  unknown-corruption|unknown)
    echo "  Could not classify. Manual inspection:"
    echo "    cat ${phase_dir}/.artifact-manifest.json"
    echo "    /vg:health ${PHASE_ARG}   # deep phase inspection"
    ;;
esac
echo ""
```
</step>

<step name="3_apply">
## Step 3 (--apply only): Run SAFE helpers after confirm

Only non-destructive helpers are auto-runnable. Destructive ops (`git checkout`, regeneration that overwrites) always require user to run manually.

```bash
if [ "$APPLY_FLAG" = "true" ]; then
  echo "## --apply mode"
  echo ""

  case "$corruption_type" in
    legacy-no-manifest)
      echo "  Safe helper available: trigger manifest backfill via /vg:progress."
      echo "  This is a read-only command; it will not modify any artifacts."
      ;;
    clean)
      if [ "$stuck" != "no" ]; then
        echo "  Safe helper available: /vg:next ${PHASE_ARG} to auto-advance."
      else
        echo "  Nothing to apply — state is clean."
        exit 0
      fi
      ;;
    *)
      echo "  ⚠ --apply is NOT safe for corruption type '${corruption_type}'."
      echo "  Destructive ops (git checkout, regeneration) must be run manually."
      echo "  See suggested commands above."
      exit 0
      ;;
  esac

  echo ""
  echo "  Proceed with safe helper? (use AskUserQuestion to confirm)"
  echo "  [This block would invoke AskUserQuestion with yes/no options.]"
  # Actual AskUserQuestion invocation happens in the caller model, not shell.
  # Shell output signals the model to prompt the user.
fi
```

When `--apply` mode is engaged AND corruption type is `legacy-no-manifest` or `clean+stuck`, the outer model SHOULD:
1. Call `AskUserQuestion` with "Proceed with safe helper X?" question.
2. On "yes" → invoke the appropriate read-only command via Skill tool (`vg:progress` or `vg:next`).
3. On "no" → print "Aborted. No action taken." and exit.
</step>

<step name="4_telemetry">
## Step 4: Emit single event

```bash
if type emit_telemetry_v2 >/dev/null 2>&1; then
  payload="{\"type\":\"${corruption_type}\",\"stuck\":\"${stuck}\",\"apply\":${APPLY_FLAG}}"
  emit_telemetry_v2 "recover_run" "${PHASE_ARG}" "recover.${corruption_type}" \
    "" "PASS" "$payload" >/dev/null 2>&1 || true
fi
```
</step>

</process>

<success_criteria>
- Suggest-only by default — no destructive ops execute without `--apply` + user confirm.
- 6 corruption types mapped to distinct recovery templates.
- Delegates classification to `artifact_manifest_validate`.
- `--apply` mode restricted to non-destructive helpers.
- Single `recover_run` telemetry event.
</success_criteria>
</content>
</invoke>