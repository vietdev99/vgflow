# Roam preflight — STEP 1

<HARD-GATE>
Roam is post-confirmation (runs AFTER /vg:review + /vg:test PASS).
You MUST verify both passes BEFORE any roam step.
TodoWrite IMPERATIVE after emit-tasklist.py.
</HARD-GATE>

Two sub-steps in this ref:

1. `0_parse_and_validate` — parse args, validate prerequisites, init output dir
2. `0aa_resume_check` — detect prior state, route fresh/force/resume/aggregate-only

---

<step name="0_parse_and_validate">
## Step 0 — Parse args, validate prerequisites

Read phase, validate `/vg:review` + `/vg:test` both completed with PASS (otherwise refuse to run). Parse flags. Initialize output dir.

```bash
vg-orchestrator step-active 0_parse_and_validate

PHASE_DIR=".vg/phases/${PHASE_NUMBER}"
ROAM_DIR="${PHASE_DIR}/roam"
mkdir -p "${ROAM_DIR}/proposed-specs"

# Refuse if review/test didn't pass
REVIEW_VERDICT=$("${PYTHON_BIN:-python3}" -c "import json; d=json.load(open('${PHASE_DIR}/PIPELINE-STATE.json')); print(d.get('steps',{}).get('review',{}).get('verdict','UNKNOWN'))" 2>/dev/null)
TEST_VERDICT=$("${PYTHON_BIN:-python3}" -c "import json; d=json.load(open('${PHASE_DIR}/PIPELINE-STATE.json')); print(d.get('steps',{}).get('test',{}).get('verdict','UNKNOWN'))" 2>/dev/null)

if [[ "$REVIEW_VERDICT" != "PASS" ]] || [[ "$TEST_VERDICT" != "PASS" ]]; then
  echo "⛔ Roam requires /vg:review and /vg:test both PASS before running."
  echo "   review verdict: $REVIEW_VERDICT"
  echo "   test verdict:   $TEST_VERDICT"
  echo "   Roam is post-confirmation janitor; no point exploring an unfinished phase."
  exit 1
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "0_parse_and_validate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0_parse_and_validate.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step roam 0_parse_and_validate 2>/dev/null || true

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "roam.session.started" \
  --actor "orchestrator" --outcome "INFO" --payload "{\"args\":\"${ARGUMENTS}\"}" 2>/dev/null || true
```
</step>

---

<step name="0aa_resume_check">
## Step 0aa — resume / force / aggregate-only detection (v2.42.6+)

If `${ROAM_DIR}/ROAM-CONFIG.json` exists, this phase had a roam run before.
Without resume logic, every re-run wastes work — re-discovers surfaces,
re-composes briefs, re-spawns executors. Detect existing state and route:

| Mode | What happens | When to use |
|------|--------------|-------------|
| `fresh` | normal flow — all steps run | first-time run, no prior state |
| `force` | wipe ROAM_DIR/* then proceed fresh | env/scope changed, want clean slate |
| `resume` | reuse config; per-step skip if artifact exists | partial run (e.g. 5/20 briefs done) |
| `aggregate-only` | skip steps 1-3 entirely, run 4-6 only | manual mode finalization (user pasted prompt to other CLI, dropped JSONL, now wants commander to aggregate + analyze) |

### Detection + branching

```bash
vg-orchestrator step-active 0aa_resume_check

EXISTING_CONFIG="${ROAM_DIR}/ROAM-CONFIG.json"
HAS_RUN_BEFORE=false
[ -f "$EXISTING_CONFIG" ] && HAS_RUN_BEFORE=true

# v2.42.9 — LEGACY state detection. Pre-v2.42.6 runs didn't write
# ROAM-CONFIG.json, but artifacts (RAW-LOG.jsonl, SURFACES.md, INSTRUCTION-*,
# observe-*) still exist. Without this, the resume prompt silently skips
# and a re-invocation overwrites prior work or treats stale state as fresh.
if [ "$HAS_RUN_BEFORE" = false ]; then
  for legacy in "${ROAM_DIR}/RAW-LOG.jsonl" "${ROAM_DIR}/SURFACES.md" "${ROAM_DIR}/ROAM-BUGS.md"; do
    [ -f "$legacy" ] && HAS_RUN_BEFORE=true && break
  done
  if [ "$HAS_RUN_BEFORE" = false ]; then
    [ -n "$(find "$ROAM_DIR" -maxdepth 3 -name 'INSTRUCTION-*.md' -print -quit 2>/dev/null)" ] && HAS_RUN_BEFORE=true
    [ -n "$(find "$ROAM_DIR" -maxdepth 3 -name 'observe-*.jsonl' -print -quit 2>/dev/null)" ] && HAS_RUN_BEFORE=true
  fi
  if [ "$HAS_RUN_BEFORE" = true ] && [ ! -f "$EXISTING_CONFIG" ]; then
    echo "▸ LEGACY roam state detected (no ROAM-CONFIG.json, artifacts present)"
    echo "   Treating as prior run — resume prompt will fire. AI must NOT silently"
    echo "   overwrite or backfill config without user confirmation."
  fi
fi

# CLI flag overrides — skip AskUserQuestion when explicit
ROAM_RESUME_MODE="fresh"
if [[ "$ARGUMENTS" =~ --force ]]; then
  ROAM_RESUME_MODE="force"
elif [[ "$ARGUMENTS" =~ --resume ]]; then
  ROAM_RESUME_MODE="resume"
elif [[ "$ARGUMENTS" =~ --aggregate-only ]]; then
  ROAM_RESUME_MODE="aggregate-only"
elif [ "$HAS_RUN_BEFORE" = true ] && [[ ! "$ARGUMENTS" =~ --non-interactive ]]; then
  PREV_ENV=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('env','?'))" 2>/dev/null)
  PREV_MODEL=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('model','?'))" 2>/dev/null)
  PREV_MODE=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('mode','?'))" 2>/dev/null)
  PREV_STARTED=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('started_at','?'))" 2>/dev/null)
  EXISTING_INSTR=$(find "$ROAM_DIR" -maxdepth 2 -name "INSTRUCTION-*.md" 2>/dev/null | wc -l | tr -d ' ')
  EXISTING_OBSERVE=$(find "$ROAM_DIR" -maxdepth 2 -name "observe-*.jsonl" 2>/dev/null | wc -l | tr -d ' ')

  echo "▸ Prior roam run detected:"
  echo "    env=${PREV_ENV} model=${PREV_MODEL} mode=${PREV_MODE} started=${PREV_STARTED}"
  echo "    INSTRUCTION-*.md: ${EXISTING_INSTR} | observe-*.jsonl: ${EXISTING_OBSERVE}"
  echo ""
  echo "AI: AskUserQuestion now with the 4-option block below before proceeding."
fi
```

### AskUserQuestion (interactive only — fires when `HAS_RUN_BEFORE=true` AND no `--force`/`--resume`/`--aggregate-only`/`--non-interactive` flag)

```
question: "Phase này đã chạy roam trước (env=$PREV_ENV, model=$PREV_MODEL, mode=$PREV_MODE, $PREV_STARTED). $EXISTING_INSTR briefs / $EXISTING_OBSERVE observed. Làm gì?"
header: "Resume?"
multiSelect: false
options:
  - label: "resume — tiếp tục từ điểm dừng (Recommended)"
    description: "Tái dùng config cũ; skip discover/compose/spawn cho artifacts đã có. Chỉ chạy bù phần thiếu + aggregate + analyze. Phù hợp khi spawn run partial (5/20 briefs xong) hoặc manual paste vẫn còn dở."
  - label: "aggregate-only — gom JSONL hiện có + analyze"
    description: "Skip discover/compose/spawn hoàn toàn. Đi thẳng vào aggregate (step 4) + analyze (step 5) + emit (step 6). Phù hợp khi manual mode đã paste xong, JSONL đã drop về model dir, chỉ cần commander gom + chấm điểm."
  - label: "force — wipe ROAM_DIR + chạy lại từ đầu"
    description: "Xóa hết SURFACES.md + INSTRUCTION-*.md + observe-*.jsonl + ROAM-BUGS.md. Phù hợp khi env/scope/lens đổi → muốn slate sạch. Sẽ hỏi lại env/model/mode."
  - label: "fresh — keep cũ + run mới (parallel)"
    description: "Giữ nguyên config + artifacts cũ; mở session mới với env/model/mode khác. Output đè lên cùng dir. CHỈ dùng khi muốn re-test cùng phase với scanner khác (vd codex → gemini)."
```

### After answer

```bash
case "$ROAM_RESUME_MODE" in
  force)
    echo "▸ Force mode — wiping ${ROAM_DIR}/* (preserving .step-markers)"
    find "$ROAM_DIR" -mindepth 1 -maxdepth 1 ! -name '.step-markers' -exec rm -rf {} +
    ROAM_RESUME_MODE="fresh"
    ;;
  resume|aggregate-only)
    # v2.42.10 — load prior config as PRE-FILL ONLY. Step 0a still fires.
    echo "▸ Resume mode: ${ROAM_RESUME_MODE} — loading PRIOR config as pre-fill (step 0a will still ask)"
    ROAM_PRIOR_ENV=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('env',''))" 2>/dev/null)
    ROAM_PRIOR_MODEL=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('model',''))" 2>/dev/null)
    ROAM_PRIOR_MODE=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('mode',''))" 2>/dev/null)
    export ROAM_PRIOR_ENV ROAM_PRIOR_MODEL ROAM_PRIOR_MODE
    export ROAM_RESUME_MODE
    echo "  prior: env=${ROAM_PRIOR_ENV} model=${ROAM_PRIOR_MODEL} mode=${ROAM_PRIOR_MODE}"
    echo "  → step 0a will fire 3-question batch with these as Recommended defaults"
    ;;
  fresh)
    :
    ;;
esac

export ROAM_RESUME_MODE

# v2.42.9 HARD GATE: write resume-mode marker + emit telemetry. Step 1 entry
# refuses to proceed unless this marker exists (or --non-interactive set).
mkdir -p "${ROAM_DIR}/.tmp"
echo "$(date +%s)|${ROAM_RESUME_MODE}" > "${ROAM_DIR}/.tmp/0aa-confirmed.marker"

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "roam.resume_mode_chosen" \
  --actor "user" --outcome "INFO" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"mode\":\"${ROAM_RESUME_MODE}\",\"had_prior_state\":${HAS_RUN_BEFORE}}" 2>/dev/null || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "0aa_resume_check" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0aa_resume_check.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step roam 0aa_resume_check 2>/dev/null || true
```

**Step 0a behavior under resume (v2.42.10):** Step 0a ALWAYS fires its 3-question batch, regardless of `$ROAM_RESUME_MODE`. Under resume, prior values are loaded as `ROAM_PRIOR_ENV/MODEL/MODE` and used as pre-fill, but user must confirm.

**Subsequent steps under resume:** each step checks `$ROAM_RESUME_MODE`:

- Step 1 (discover surfaces): SKIP if `resume` AND `SURFACES.md` exists. SKIP unconditionally if `aggregate-only`.
- Step 2 (compose briefs): SKIP if `resume` AND `INSTRUCTION-*.md` count ≥ surface count. SKIP unconditionally if `aggregate-only`.
- Step 3 (spawn/manual): per-brief skip — if `observe-${brief}.jsonl` exists with ≥1 event, skip that brief. SKIP unconditionally if `aggregate-only`.
- Steps 4-6: always run (cheap; idempotent).
</step>
