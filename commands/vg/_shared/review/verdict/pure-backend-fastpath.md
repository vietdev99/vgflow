# review verdict — pure-backend fast-path (UI_GOAL_COUNT == 0 branch)

This branch fires when TEST-GOALS.md has zero `**Surface:** ui` rows —
i.e., a pure backend / API / library / CLI phase. Browser discovery is
skipped (overview.md branches before reaching here); we use surface
probes to stamp every goal with READY / BLOCKED / INFRA_PENDING based on
filesystem + grep evidence.

## Why fast-path

Pre-fast-path behavior: empty RUNTIME-MAP → every goal NOT_SCANNED →
4c-pre block-resolver loop → user override required even when the phase
has no UI by design. Closes that false-positive surface for backend-
only milestones.

vg-load convention: per-goal context (when surface probe needs to load
a goal's success criteria for grep targeting) calls `vg-load --phase
${PHASE_NUMBER} --artifact goals --goal G-NN`. The surface-probe.sh
helper itself uses regex against TEST-GOALS.md (no AI context).

---

## STEP 7.A — pure-backend fast-path

### Empty RUNTIME-MAP stub

```bash
# Emit empty RUNTIME-MAP if not written yet, skip browser-discovery costs.
[ -f "${PHASE_DIR}/RUNTIME-MAP.json" ] || echo '{"views":{},"goal_sequences":{}}' > "${PHASE_DIR}/RUNTIME-MAP.json"
echo "🧭 Pure-backend phase (không có goal UI) — bỏ qua browser discovery (khám phá trình duyệt), dùng surface probes." >&2
```

### Run surface probes for every backend goal

```bash
# Surface-aware routing: every goal here is non-UI, so probe per surface kind.
# - api        → grep apps/**/src/** for route handler matching contract path → READY if present
# - data       → grep migrations + config.infra_deps for table/collection → READY if present; INFRA_PENDING if service unavailable
# - time-driven→ grep cron/scheduler registration in apps/workers/**/apps/api/** → READY if handler wired
# - integration→ check ${PHASE_DIR}/test-runners/fixtures/${gid}.integration.sh exists AND downstream caller found → READY
# - custom     → goal-specific evidence; falls back to BLOCKED if no probe matches

source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/surface-probe.sh" 2>/dev/null || true
PROBE_RESULTS_JSON="${PHASE_DIR}/.surface-probe-results.json"

if type -t run_surface_probe >/dev/null 2>&1; then
  echo '{"probed_at":"'"$(date -u +%FT%TZ)"'","results":{' > "$PROBE_RESULTS_JSON"
  FIRST=true

  ${PYTHON_BIN} -c "
import re
tg = open('${PHASE_DIR}/TEST-GOALS.md', encoding='utf-8').read()
for gid, surface in re.findall(r'^## Goal (G-[\w]+):.*?^\*\*Surface:\*\* (\w[\w-]*)', tg, re.M|re.S):
    print(f'{gid} {surface}')
" | while read -r gid surface; do
    surface="${surface%$'\r'}"

    PROBE=$(run_surface_probe "$gid" "$surface" "$PHASE_DIR" 2>/dev/null)
    STATUS=$(echo "$PROBE" | cut -d'|' -f1)
    EVIDENCE=$(echo "$PROBE" | cut -d'|' -f2- | sed 's/"/\\"/g')

    [ "$FIRST" = "true" ] && FIRST=false || echo "," >> "$PROBE_RESULTS_JSON"
    printf '"%s":{"surface":"%s","status":"%s","evidence":"%s"}' \
           "$gid" "$surface" "$STATUS" "$EVIDENCE" >> "$PROBE_RESULTS_JSON"
  done

  echo '}}' >> "$PROBE_RESULTS_JSON"

  PROBED=$(${PYTHON_BIN} -c "
import json
d = json.load(open('$PROBE_RESULTS_JSON'))['results']
from collections import Counter
c = Counter(r['status'] for r in d.values())
print(f'Phase 4a surface probes: {len(d)} backend goals probed → {dict(c)}')")
  echo "▸ $PROBED"

  # v2.48.1 (Issue #85) — backfill synthetic goal_sequences[gid] for non-UI
  # goals from probe results so verify-matrix-evidence-link.py (which only
  # inspects RUNTIME-MAP goal_sequences[]) sees backend evidence.
  if [ -f "${REPO_ROOT}/.claude/scripts/backfill-surface-probe-runtime.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/backfill-surface-probe-runtime.py" \
      --phase-dir "$PHASE_DIR" 2>&1 | sed 's/^/▸ /' || true
  fi
else
  echo "⛔ surface-probe.sh missing — pure-backend fast-path needs the helper" >&2
  exit 1
fi
```

### Infra dependency filter (config-driven)

```bash
# If goal has `**Infra deps:**` field (e.g., [clickhouse, kafka, pixel_server]),
# check each dep against current environment. INFRA_PENDING goals are excluded
# from gate calculation when config.infra_deps.unmet_behavior == "skip".
for dep in $(grep -oE '\*\*Infra deps:\*\*[^\n]+' "${PHASE_DIR}/TEST-GOALS.md" | tr ',' ' '); do
  SERVICE_CHECK=$(vg_config_get "infra_deps.services.${dep}.check_${VG_ENV}" "" 2>/dev/null)
  if [ -n "$SERVICE_CHECK" ] && ! eval "$SERVICE_CHECK" 2>/dev/null; then
    echo "▸ ${dep} not available on ${VG_ENV} — affected goals will be marked INFRA_PENDING"
  fi
done
```

### Console noise filter (config-driven)

Backend phase has no console errors to filter, but the helper still
runs (no-op when scan-*.json absent). Skipped here.

### Run matrix-merger.sh (canonical write)

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/matrix-merger.sh" 2>/dev/null || true
if type -t merge_and_write_matrix >/dev/null 2>&1; then
  MERGE_OUTPUT=$(merge_and_write_matrix "$PHASE_DIR" \
    "${PHASE_DIR}/TEST-GOALS.md" \
    "${PHASE_DIR}/RUNTIME-MAP.json" \
    "${PHASE_DIR}/.surface-probe-results.json" \
    "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" 2>&1)

  VERDICT=$(echo "$MERGE_OUTPUT" | grep '^VERDICT=' | cut -d= -f2)
  READY=$(echo "$MERGE_OUTPUT" | grep '^READY=' | cut -d= -f2)
  BLOCKED=$(echo "$MERGE_OUTPUT" | grep '^BLOCKED=' | cut -d= -f2)
  NOT_SCANNED=$(echo "$MERGE_OUTPUT" | grep '^NOT_SCANNED=' | cut -d= -f2)
  INTERMEDIATE=$(echo "$MERGE_OUTPUT" | grep '^INTERMEDIATE=' | cut -d= -f2)
  export VERDICT READY BLOCKED NOT_SCANNED INTERMEDIATE

  echo "✓ GOAL-COVERAGE-MATRIX.md (pure-backend): VERDICT=$VERDICT (ready=$READY blocked=$BLOCKED)"
else
  echo "⛔ matrix-merger.sh missing — pure-backend fast-path requires the helper" >&2
  exit 1
fi
```

### Reduced invariants gate

Pure-backend fast-path runs a **subset** of the 8 invariant validators:
the UI-specific ones (verify-haiku-scan-completeness, verify-runtime-map-coverage,
verify-error-message-runtime) are skipped because there is no browser
RUNTIME-MAP body; the API-side ones still apply.

```bash
if [[ ! "$ARGUMENTS" =~ --skip-content-invariants ]]; then
  for VALIDATOR in verify-interface-standards verify-goal-security verify-goal-perf verify-security-baseline verify-crud-runs-coverage; do
    VAL_PATH="${REPO_ROOT}/.claude/scripts/validators/${VALIDATOR}.py"
    if [ -f "$VAL_PATH" ]; then
      mkdir -p "${PHASE_DIR}/.tmp"
      VAL_OUT="${PHASE_DIR}/.tmp/${VALIDATOR}-diagnostic-input.txt"
      case "$VALIDATOR" in
        verify-interface-standards)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" --profile "${PROFILE:-${CONFIG_PROFILE:-web-backend-only}}" > "$VAL_OUT" 2>&1
          ;;
        verify-goal-security|verify-goal-perf)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" > "$VAL_OUT" 2>&1
          ;;
        verify-security-baseline)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" --scope all > "$VAL_OUT" 2>&1
          ;;
        *)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase-dir "$PHASE_DIR" > "$VAL_OUT" 2>&1
          ;;
      esac
      VAL_RC=$?
      cat "$VAL_OUT"
      if [ "$VAL_RC" -ne 0 ]; then
        echo ""
        echo "⛔ Verdict gate invariant FAILED (pure-backend): ${VALIDATOR}"
        emit_telemetry_v2 "review_verdict_invariant_failed" "${PHASE_NUMBER}" \
          "review.4-verdict" "${VALIDATOR}" "BLOCK" "{}" 2>/dev/null || true
        exit 1
      fi
    fi
  done
fi
```

### 4c-pre + 4d + 4e + 4f gate (shared with web-fullstack — see profile-branches.md)

Pure-backend phases STILL run the NOT_SCANNED resolution gate (4c-pre)
because surface probe SKIPPED status falls through to NOT_SCANNED. The
4d inline triage + 4e count + 4f decision blocks are identical to the
full pipeline — see `web-fullstack.md` STEP 7.B-4c-pre through 7.B-4f
for verbatim implementation.

After the gate decides PASS / BLOCK, control returns to overview.md for
step-end marker write.
