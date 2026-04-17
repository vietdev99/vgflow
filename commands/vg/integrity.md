---
name: vg:integrity
description: Artifact manifest integrity sweep — hash-validates every phase artifact, reports CORRUPT/MISSING/VALID per phase
argument-hint: "[phase]"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
---

<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Markdown headers for progress. Long Bash > 30s → `run_in_background: true`.

**Translate English terms (RULE)** — first-occurrence English term phải có giải thích VN trong ngoặc. Ví dụ: `manifest (kê khai)`, `integrity (toàn vẹn)`, `corruption (hư hỏng)`, `hash mismatch (lệch băm)`, `artifact (tạo phẩm)`, `sweep (quét)`. Không áp dụng: file path, code ID.
</NARRATION_POLICY>

<rules>
1. **Read-only** — sweep compares file hashes against `.artifact-manifest.json`. Never repairs. Recovery belongs in `/vg:recover`.
2. **Delegates to `artifact_manifest_validate`** — no reimplementation.
3. **No-arg = all phases. `{phase}` arg = that phase only.**
4. **Graceful** — missing manifest = LEGACY (WARN), not corruption. Exit 1 only on bad args.
5. **Emit single `integrity_run` event** per invocation.
</rules>

<objective>
Answer: "Are any artifacts corrupted or missing on disk?"

Produces a 3-bucket report (VALID / LEGACY / CORRUPT) per phase. Each CORRUPT row points at `/vg:recover {phase}` for remediation.
</objective>

<process>

<step name="0_parse_load">
## Step 0: Parse + load helpers

```bash
PLANNING_DIR=".planning"
PHASES_DIR="${PLANNING_DIR}/phases"
PYTHON_BIN="${PYTHON_BIN:-python3}"

source .claude/commands/vg/_shared/lib/artifact-manifest.sh 2>/dev/null || {
  echo "⛔ artifact-manifest.sh missing — cannot run integrity sweep" >&2
  exit 1
}
source .claude/commands/vg/_shared/lib/telemetry.sh 2>/dev/null || true

PHASE_ARG=""
for arg in $ARGUMENTS; do
  case "$arg" in
    --*) echo "⚠ Unknown flag: $arg" ;;
    *)   PHASE_ARG="$arg" ;;
  esac
done

export VG_CURRENT_COMMAND="vg:integrity"
type telemetry_init >/dev/null 2>&1 && telemetry_init

echo ""
if [ -n "$PHASE_ARG" ]; then
  echo "🔍 ━━━ /vg:integrity — phase ${PHASE_ARG} ━━━"
else
  echo "🔍 ━━━ /vg:integrity — all phases ━━━"
fi
echo ""
```
</step>

<step name="1_select_phases">
## Step 1: Select phase list to sweep

```bash
TARGET_PHASES=()
if [ -n "$PHASE_ARG" ]; then
  for d in "${PHASES_DIR}"/*; do
    [ -d "$d" ] || continue
    base=$(basename "$d")
    if [[ "$base" == "${PHASE_ARG}"* ]] || [[ "$base" == "${PHASE_ARG}-"* ]]; then
      TARGET_PHASES+=("$d"); break
    fi
  done
  if [ ${#TARGET_PHASES[@]} -eq 0 ]; then
    echo "⛔ Phase ${PHASE_ARG} not found under ${PHASES_DIR}"
    exit 1
  fi
else
  while IFS= read -r d; do
    [ -d "$d" ] && TARGET_PHASES+=("$d")
  done < <(find "$PHASES_DIR" -maxdepth 1 -mindepth 1 -type d | sort)
fi

if [ ${#TARGET_PHASES[@]} -eq 0 ]; then
  echo "⚠ No phases to sweep. Run /vg:roadmap."
  exit 0
fi
```
</step>

<step name="2_sweep">
## Step 2: Sweep loop

```bash
total=0; valid=0; legacy=0; corrupt=0
issues=()

echo "## Sweep results"
echo ""
echo "| Phase | Status | Detail |"
echo "|-------|--------|--------|"

for phase_dir in "${TARGET_PHASES[@]}"; do
  total=$((total + 1))
  phase_name=$(basename "$phase_dir")
  phase_num=$(echo "$phase_name" | grep -oE '^[0-9.]+')

  output=$(artifact_manifest_validate "$phase_dir" 2>&1)
  rc=$?
  case $rc in
    0)
      valid=$((valid + 1))
      printf "| %s | ✓ VALID | all artifacts match manifest |\n" "$phase_num"
      ;;
    1)
      legacy=$((legacy + 1))
      printf "| %s | ⚠ LEGACY | no manifest (auto-backfill on next read) |\n" "$phase_num"
      ;;
    2)
      corrupt=$((corrupt + 1))
      first_line=$(echo "$output" | head -1 | sed 's/|/ /g')
      printf "| %s | ⛔ CORRUPT | %s |\n" "$phase_num" "$first_line"
      issues+=("${phase_num}|${output}")
      ;;
    *)
      printf "| %s | ? unknown rc=%d | %s |\n" "$phase_num" "$rc" "$output"
      ;;
  esac
done
echo ""

echo "## Totals"
echo "   Total:    ${total}"
echo "   ✓ Valid:   ${valid}"
echo "   ⚠ Legacy:  ${legacy}  (auto-backfills — no action needed)"
echo "   ⛔ Corrupt: ${corrupt}"
echo ""
```
</step>

<step name="3_corruption_detail">
## Step 3: Corruption detail + recovery pointer

```bash
if [ "$corrupt" -gt 0 ]; then
  echo "## Corruption details"
  echo ""
  for entry in "${issues[@]}"; do
    phase="${entry%%|*}"
    detail="${entry#*|}"
    echo "### Phase ${phase}"
    echo "$detail" | sed 's/^/  /'
    echo ""
    echo "  **Recovery:** /vg:recover ${phase}"
    echo ""
  done
else
  echo "🎉 No corruption detected."
  echo ""
fi
```
</step>

<step name="4_telemetry">
## Step 4: Emit single event

```bash
if type emit_telemetry_v2 >/dev/null 2>&1; then
  emit_telemetry_v2 "integrity_run" "${PHASE_ARG:-project}" "integrity.sweep" \
    "" "PASS" "{\"total\":${total},\"valid\":${valid},\"legacy\":${legacy},\"corrupt\":${corrupt}}" \
    >/dev/null 2>&1 || true
fi
```
</step>

</process>

<success_criteria>
- Read-only; no repair attempt.
- Uses `artifact_manifest_validate` for all checks.
- Output = 3-bucket table + corruption detail + recovery pointer.
- Single `integrity_run` telemetry event.
</success_criteria>
</content>
</invoke>