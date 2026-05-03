# Accept gates — STEP 2 (3-tier preflight gates)

> **Size exception (F3-r2):** This ref is intentionally over the soft
> 400-line cap (current ~629 lines). It bundles five fail-fast accept
> gates (`1_artifact_precheck`, `2_marker_precheck`,
> `3_sandbox_verdict_gate`, `3b_unreachable_triage_gate`,
> `3c_override_resolution_gate`) that share the same pre-spawn lifecycle
> + block-resolver wiring. Splitting them per-step would duplicate the
> shared sourcing of `block-resolver.sh` / `override-debt.sh` /
> `rationalization-guard.sh` across five files and double the audit
> surface for the contract-binder. Treat as an appendix-style "gates
> bundle" — keep it monolithic until any single gate exceeds 200 lines
> and warrants its own ref.

5 gate steps: `1_artifact_precheck`, `2_marker_precheck`,
`3_sandbox_verdict_gate`, `3b_unreachable_triage_gate`,
`3c_override_resolution_gate`. Each gate fail-fast.

<HARD-GATE>
You MUST execute every gate before STEP 3 (UAT checklist build). Each gate
exits non-zero on fail; do NOT bypass with `--override-reason` unless
explicitly authorized by the user. Override-debt register (gate 3c) hard-blocks
unresolved blocking-severity entries.
</HARD-GATE>

---

<step name="1_artifact_precheck">
**Gate 1: All required artifacts exist**

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 1_artifact_precheck 2>/dev/null || true

MISSING=""
REQUIRED=(
  "SPECS.md"
  "CONTEXT.md"
  "API-CONTRACTS.md"
  "TEST-GOALS.md"
  "GOAL-COVERAGE-MATRIX.md"
)
for f in "${REQUIRED[@]}"; do
  [ -f "${PHASE_DIR}/${f}" ] || MISSING="$MISSING $f"
done
# Plans (numbered or not)
ls "${PHASE_DIR}"/*PLAN*.md >/dev/null 2>&1 || MISSING="$MISSING PLAN*.md"
ls "${PHASE_DIR}"/*SUMMARY*.md >/dev/null 2>&1 || MISSING="$MISSING SUMMARY*.md"
ls "${PHASE_DIR}"/*SANDBOX-TEST.md >/dev/null 2>&1 || MISSING="$MISSING SANDBOX-TEST.md"
# RUNTIME-MAP only required for web profiles
case "$PROFILE" in
  web-fullstack|web-frontend-only)
    [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ] || MISSING="$MISSING RUNTIME-MAP.json"
    ;;
  mobile-*)
    # Mobile profile: build-state.log MUST exist (it holds mobile-gate-* entries).
    # Screenshots from phase2_mobile_discovery are optional — host may lack simulator/emulator.
    [ -f "${PHASE_DIR}/build-state.log" ] || MISSING="$MISSING build-state.log"
    ;;
esac

if [ -n "$MISSING" ]; then
  echo "⛔ Missing required artifacts:$MISSING"
  echo "   Run prior pipeline steps first (/vg:build, /vg:review, /vg:test)"
  exit 1
fi

CRUD_VAL="${REPO_ROOT:-.}/.claude/scripts/validators/verify-crud-surface-contract.py"
if [ -x "$CRUD_VAL" ]; then
  mkdir -p "${PHASE_DIR}/.tmp"
  "${PYTHON_BIN:-python3}" "$CRUD_VAL" --phase "${PHASE_NUMBER}" \
    --config "${REPO_ROOT:-.}/.claude/vg.config.md" \
    > "${PHASE_DIR}/.tmp/crud-surface-accept.json" 2>&1
  CRUD_RC=$?
  if [ "$CRUD_RC" != "0" ]; then
    echo "⛔ CRUD-SURFACES.md contract invalid — see ${PHASE_DIR}/.tmp/crud-surface-accept.json"
    exit 2
  fi
fi

# Harness v2.6.1 (2026-04-26): rule-cards drift gate. WARN if any
# .codex/skills/vg-*/SKILL.md is newer than its RULES-CARDS.md sibling.
# Per AUDIT.md D4 finding (drift gate not wired into accept pipeline).
# Non-blocking — operator runs extract-rule-cards.py to refresh.
if [ -f "${REPO_ROOT:-.}/.claude/scripts/validators/verify-rule-cards-fresh.py" ]; then
  echo ""
  echo "━━━ Rule-cards freshness check ━━━"
  "${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-rule-cards-fresh.py 2>&1 | tail -5
  echo ""
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "1_artifact_precheck" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/1_artifact_precheck.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 1_artifact_precheck 2>/dev/null || true
```
</step>

<step name="2_marker_precheck">
**Gate 2: Step markers (deterministic — AI did not skip silently)**

Profile determines which steps must have markers. Use `filter-steps.py` to compute the expected set per command, then verify each marker exists.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 2_marker_precheck 2>/dev/null || true

MARKER_DIR="${PHASE_DIR}/.step-markers"
mkdir -p "$MARKER_DIR"

# Load marker schema library (OHOK Batch 5b / E1) — content-aware verify
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/marker-schema.sh" 2>/dev/null || true

MISSED=""
FORGED=""
LEGACY=""
for cmd in build review test; do
  CMD_FILE=".claude/commands/vg/${cmd}.md"
  [ -f "$CMD_FILE" ] || continue
  EXPECTED=$(${PYTHON_BIN} .claude/scripts/filter-steps.py \
    --command "$CMD_FILE" --profile "$PROFILE" --output-ids 2>/dev/null)
  [ -z "$EXPECTED" ] && continue
  for step in $(echo "$EXPECTED" | tr ',' ' '); do
    # v2.5.2.11 — marker path dual-convention fallback.
    # Historical: flat `${MARKER_DIR}/${step}.done`.
    # Current:    subdir  `${MARKER_DIR}/${cmd}/${step}.done` (prevents name
    #             collisions across commands, e.g. build:1_parse_args vs
    #             review:1_parse_args). Subdir convention is what the skills
    #             actually write today. Accept gate must look for either.
    MARKER_FILE_FLAT="${MARKER_DIR}/${step}.done"
    MARKER_FILE_SUBDIR="${MARKER_DIR}/${cmd}/${step}.done"
    if [ -f "$MARKER_FILE_SUBDIR" ]; then
      MARKER_FILE="$MARKER_FILE_SUBDIR"
    elif [ -f "$MARKER_FILE_FLAT" ]; then
      MARKER_FILE="$MARKER_FILE_FLAT"
    else
      MISSED="$MISSED ${cmd}:${step}"
      continue
    fi
    # Content-aware verification (CrossAI R6 Batch 5b fix)
    if type -t verify_marker >/dev/null 2>&1; then
      verify_marker "$MARKER_FILE" "$PHASE_NUMBER" "$step" 30 2>/dev/null
      rc=$?
      case $rc in
        0) : ;;  # valid
        2) LEGACY="$LEGACY ${cmd}:${step}" ;;  # empty marker (pre-5b)
        3|4|5|6|7) FORGED="$FORGED ${cmd}:${step}(rc=$rc)" ;;
      esac
    fi
  done
done

if [ -n "$(echo "$MISSED" | xargs)" ]; then
  echo "⛔ Missing step markers — pipeline incomplete per profile '$PROFILE':"
  for m in $MISSED; do echo "   - $m"; done
  echo ""
  echo "   Resume: /vg:next  (auto-detects which step to rerun)"
  exit 1
fi

# Batch 5b: hard-block on content integrity violations (forged/mismatched/stale)
if [ -n "$(echo "$FORGED" | xargs)" ]; then
  echo "⛔ Marker content integrity violations detected (forgery / mismatch / stale):" >&2
  for m in $FORGED; do echo "   - $m" >&2; done
  echo "" >&2
  echo "   rc=3 schema, rc=4 phase mismatch, rc=5 step mismatch," >&2
  echo "   rc=6 git_sha not ancestor of HEAD (likely forged via touch)," >&2
  echo "   rc=7 marker older than 30 days (stale run state)." >&2
  echo "" >&2
  echo "   Re-run the affected step to emit a fresh valid marker." >&2
  echo "   Override (NOT recommended): --allow-forged-markers (log debt)." >&2
  if [[ ! "${ARGUMENTS:-}" =~ --allow-forged-markers ]]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "accept.marker_forgery_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"count\":$(echo $FORGED | wc -w)}" >/dev/null 2>&1 || true
    exit 1
  fi
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "accept-marker-forgery" "${PHASE_NUMBER}" \
    "forged/mismatched/stale markers: $(echo $FORGED | xargs)" "${PHASE_DIR}"
fi

# Legacy empty markers — WARN only, nudge user to migrate
if [ -n "$(echo "$LEGACY" | xargs)" ]; then
  LEGACY_COUNT=$(echo $LEGACY | wc -w)
  echo "⚠ ${LEGACY_COUNT} legacy empty markers (pre-Batch-5b format):" >&2
  for m in $LEGACY; do echo "   - $m" >&2; done
  echo "   Run once: python .claude/scripts/marker-migrate.py --planning ${PLANNING_DIR:-.vg}" >&2
  echo "   Strict mode: export VG_MARKER_STRICT=1 to BLOCK on legacy markers." >&2
fi

echo "✓ All expected step markers present for profile: $PROFILE"
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2_marker_precheck" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2_marker_precheck.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 2_marker_precheck 2>/dev/null || true
```
</step>

<step name="3_sandbox_verdict_gate">
**Gate 3: Test verdict**

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 3_sandbox_verdict_gate 2>/dev/null || true

SANDBOX=$(ls "${PHASE_DIR}"/*SANDBOX-TEST.md 2>/dev/null | head -1)
# OHOK-8 round-4 Codex fix: accept emits verdict in 3 formats across versions.
# Parser now accepts all:
#   `**Verdict:** PASSED`           (bold inline)
#   `Verdict: PASSED`                (plain prefix)
#   `## Verdict: PASSED`             (markdown heading — test.md canonical)
#   `status: passed` (YAML frontmatter, lowercased values)
# Previous regex only matched the first two → test.md's heading format
# produced a false BLOCK "verdict not parseable" after a valid /vg:test.
VERDICT=$(grep -iE "^\s*#+\s*Verdict:?|^\s*\*\*Verdict:?\*\*|^\s*Verdict:|^\s*status:" "$SANDBOX" \
  | head -1 \
  | grep -oiE "PASSED|GAPS_FOUND|FAILED|passed|gaps_found|failed" \
  | head -1 \
  | tr '[:lower:]' '[:upper:]')

case "$VERDICT" in
  PASSED|GAPS_FOUND)
    echo "✓ Test verdict: $VERDICT"
    ;;
  FAILED)
    # ⛔ HARD GATE: FAILED blocks accept.
    # v1.9.1 R2+R4: block-resolver trước khi raw exit 1 — L1 thử gaps-only rebuild,
    # L2 architect đề xuất structural change (refactor / sub-phase / config tuning).
    echo "⛔ Test verdict: FAILED. Cannot accept."
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="accept.test-verdict"
      BR_CTX="SANDBOX-TEST verdict=FAILED. Accept blocked. L1 may attempt gaps-only rebuild + retest; L2 may propose refactor / sub-phase / config change."
      BR_EV=$(printf '{"sandbox_test":"%s","verdict":"FAILED"}' "${SANDBOX}")
      BR_CANDS='[{"id":"gaps-only-rebuild","cmd":"echo L1-SAFE: orchestrator would run /vg:build '"${PHASE_NUMBER}"' --gaps-only then /vg:test '"${PHASE_NUMBER}"'; skipping in shell resolver safe mode","confidence":0.5,"rationale":"gap-rebuild is documented first response"}]'
      BR_RES=$(block_resolve "test-verdict-failed" "$BR_CTX" "$BR_EV" "$PHASE_DIR" "$BR_CANDS")
      BR_LVL=$(echo "$BR_RES" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      if [ "$BR_LVL" = "L1" ]; then
        echo "✓ Block resolver L1 applied gaps-only rebuild — re-run /vg:accept ${PHASE_NUMBER}"
        exit 0
      elif [ "$BR_LVL" = "L2" ]; then
        block_resolve_l2_handoff "test-verdict-failed" "$BR_RES" "$PHASE_DIR"
        exit 2
      else
        block_resolve_l4_stuck "test-verdict-failed" "L1 gaps-rebuild declined, L2 architect unavailable"
      fi
    fi
    echo "   Fix failures first: /vg:build ${PHASE_NUMBER} --gaps-only → /vg:test ${PHASE_NUMBER}"
    exit 1
    ;;
  *)
    echo "⛔ Test verdict not parseable from $SANDBOX — cannot determine pass/fail state."
    echo "   Re-run /vg:test ${PHASE_NUMBER} to regenerate SANDBOX-TEST with a clear verdict."
    exit 1
    ;;
esac

# ⛔ HARD GATE (tightened 2026-04-17): build-state regression overrides surface here.
# If build was accepted with --override-reason=, accept step must acknowledge.
BUILD_STATE="${PHASE_DIR}/build-state.log"
if [ -f "$BUILD_STATE" ]; then
  OVERRIDES=$(grep -E "^(override|regression-guard.*OVERRIDE|regression-guard.*WARN|skip-design-check|missing-summaries)" "$BUILD_STATE" 2>/dev/null)
  if [ -n "$OVERRIDES" ]; then
    echo "⚠ Build-phase overrides detected (require human acknowledgment):"
    echo "$OVERRIDES" | sed 's/^/   /'
    echo ""
    echo "   Proceeding will record these in UAT.md 'Build Overrides' section."
    # Write to be picked up by write_uat_md step
    echo "$OVERRIDES" > "${VG_TMP}/uat-build-overrides.txt"
  fi
fi

# Git cleanliness check (non-blocking, informational)
DIRTY=$(git status --porcelain 2>/dev/null | head -5)
if [ -n "$DIRTY" ]; then
  echo "⚠ Working tree has uncommitted changes — may or may not be intentional:"
  echo "$DIRTY" | head -5 | sed 's/^/   /'
fi

# ⛔ HARD GATE (tightened 2026-04-17): regression surface check
# If /vg:regression ran and REGRESSION-REPORT.md has REGRESSION_COUNT > 0 without --fix,
# block accept unless user explicitly overrides.
REG_REPORT=$(ls "${PHASE_DIR}"/REGRESSION-REPORT*.md 2>/dev/null | head -1)
if [ -n "$REG_REPORT" ]; then
  REG_COUNT=$(grep -oE 'REGRESSION_COUNT:\s*[0-9]+' "$REG_REPORT" | grep -oE '[0-9]+' | head -1)
  REG_FIXED=$(grep -q "fix-loop: applied" "$REG_REPORT" && echo "yes" || echo "no")
  if [ -n "$REG_COUNT" ] && [ "$REG_COUNT" -gt 0 ] && [ "$REG_FIXED" != "yes" ]; then
    echo "⛔ Regressions detected in ${REG_REPORT}: ${REG_COUNT} goals regressed, fix-loop NOT run."
    echo "   Fix: /vg:regression --fix  (auto-fix loop then re-run accept)"
    if [[ ! "$ARGUMENTS" =~ --override-regressions= ]]; then
      # v1.9.2 P4 — block-resolver before exit
      source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
      if type -t block_resolve >/dev/null 2>&1; then
        export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="accept.regression-gate"
        BR_GATE_CONTEXT="${REG_COUNT} regressed goals detected in ${REG_REPORT}. Fix-loop was NOT run. Shipping now would ship known broken behavior."
        BR_EVIDENCE=$(printf '{"reg_count":"%s","reg_report":"%s","reg_fixed":"%s"}' "$REG_COUNT" "$REG_REPORT" "$REG_FIXED")
        BR_CANDIDATES='[{"id":"run-regression-fix","cmd":"echo \"/vg:regression --fix required — orchestrator must dispatch slash command\" && exit 1","confidence":0.5,"rationale":"Standard remediation path"}]'
        BR_RESULT=$(block_resolve "accept-regression" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
        BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
        [ "$BR_LEVEL" = "L1" ] && echo "✓ L1 — regression fix-loop applied" >&2 && REG_FIXED="yes"
        [ "$BR_LEVEL" = "L2" ] && { block_resolve_l2_handoff "accept-regression" "$BR_RESULT" "$PHASE_DIR"; exit 2; }
        [ "$REG_FIXED" != "yes" ] && exit 1
      else
        exit 1
      fi
    else
      echo "⚠ --override-regressions set — recording in UAT.md"
    fi
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "3_sandbox_verdict_gate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/3_sandbox_verdict_gate.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 3_sandbox_verdict_gate 2>/dev/null || true
```
</step>

<step name="3b_unreachable_triage_gate">
**Gate 3b: UNREACHABLE triage gate (added 2026-04-17)**

⛔ HARD GATE: if `/vg:review` produced `.unreachable-triage.json` and any verdict is `bug-this-phase`, `cross-phase-pending:*`, or `scope-amend`, BLOCK accept unless `--allow-unreachable` + `--reason='...'` is supplied.

Rationale: UNREACHABLE goals previously got "tracked separately" and shipped silently. They are bugs (or fictional roadmap entries) until proven otherwise. The triage produced by `/vg:review` distinguishes legitimate cross-phase ownership from bugs — only `cross-phase:{X.Y}` (owner already accepted + runtime-verified) is acceptance-safe.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 3b_unreachable_triage_gate 2>/dev/null || true

TRIAGE_JSON="${PHASE_DIR}/.unreachable-triage.json"

if [ -f "$TRIAGE_JSON" ]; then
  # Parse blocking verdicts
  BLOCKING_LIST=$(${PYTHON_BIN} - "$TRIAGE_JSON" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
blocking = []
for gid, v in data.get("verdicts", {}).items():
    if v.get("blocks_accept"):
        blocking.append(f"{gid}|{v['verdict']}|{v['title'][:80]}")
print("\n".join(blocking))
PY
)

  if [ -n "$BLOCKING_LIST" ]; then
    BLOCKING_COUNT=$(echo "$BLOCKING_LIST" | wc -l)
    echo ""
    echo "⛔ /vg:accept BLOCKED — ${BLOCKING_COUNT} UNREACHABLE goals need resolution before phase ${PHASE_NUMBER} can ship:"
    echo ""
    echo "$BLOCKING_LIST" | while IFS='|' read -r gid verdict title; do
      echo "  • ${gid} [${verdict}] — ${title}"
    done
    echo ""
    echo "See ${PHASE_DIR}/UNREACHABLE-TRIAGE.md for evidence + required actions."
    echo ""
    echo "Fix paths by verdict:"
    echo "  bug-this-phase       → /vg:build ${PHASE_NUMBER} --gaps-only"
    echo "  cross-phase-pending  → wait for owning phase to reach 'accepted', OR /vg:amend ${PHASE_NUMBER}"
    echo "  scope-amend          → /vg:amend ${PHASE_NUMBER}  (remove goal or move to new phase)"
    echo ""

    # v1.9.2 P4 — attempt block_resolve before hard exit (only when no --allow-unreachable)
    if [[ ! "$ARGUMENTS" =~ --allow-unreachable ]]; then
      source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
      if type -t block_resolve >/dev/null 2>&1; then
        export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="accept.unreachable-gate"
        BR_GATE_CONTEXT="${BLOCKING_COUNT} UNREACHABLE goals block accept. Verdicts include bug-this-phase / cross-phase-pending / scope-amend. Shipping without resolution = phantom-done phase."
        BR_EVIDENCE=$(printf '{"blocking_count":"%s","triage_file":"%s"}' "$BLOCKING_COUNT" "$TRIAGE_JSON")
        BR_CANDIDATES='[{"id":"auto-scope-amend","cmd":"echo \"would open /vg:amend for scope_amend items — requires orchestrator\" && exit 1","confidence":0.35,"rationale":"scope-amend verdicts often resolvable by moving goal to new phase"}]'
        BR_RESULT=$(block_resolve "accept-unreachable" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
        BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
        case "$BR_LEVEL" in
          L1) echo "✓ L1 resolved — triage updated inline" >&2 ;;
          L2) block_resolve_l2_handoff "accept-unreachable" "$BR_RESULT" "$PHASE_DIR"; exit 2 ;;
          *)  exit 1 ;;
        esac
      fi
    fi

    if [[ "$ARGUMENTS" =~ --allow-unreachable ]]; then
      # Canonical override flag is --override-reason="..." (entry contract).
      # Accept legacy --reason='...' for backward compat but warn if used.
      REASON=$(echo "$ARGUMENTS" | grep -oE -- "--override-reason=\"[^\"]+\"" | sed "s/--override-reason=\"//; s/\"$//")
      if [ -z "$REASON" ]; then
        REASON=$(echo "$ARGUMENTS" | grep -oE -- "--override-reason='[^']+'" | sed "s/--override-reason='//; s/'$//")
      fi
      if [ -z "$REASON" ]; then
        REASON=$(echo "$ARGUMENTS" | grep -oE -- "--reason='[^']+'" | sed "s/--reason='//; s/'$//")
        [ -n "$REASON" ] && echo "⚠ --reason='...' is legacy; prefer --override-reason=\"...\" (entry contract)" >&2
      fi
      if [ -z "$REASON" ]; then
        echo "⛔ --allow-unreachable requires --override-reason=\"<why shipping with known gaps>\""
        exit 1
      fi
      # v1.9.0 T1: rationalization guard — shipping with known UNREACHABLE goals is critical bypass.
      RATGUARD_RESULT=$(rationalization_guard_check "unreachable-triage" \
        "UNREACHABLE with bug-this-phase/cross-phase-pending/scope-amend verdict = known gap. Shipping without fix or amend creates phantom-done phases." \
        "blocking_list=${BLOCKING_LIST} reason=${REASON}")
      if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "unreachable-triage" "--allow-unreachable" "$PHASE_NUMBER" "accept.unreachable-gate" "$REASON"; then
        exit 1
      fi
      echo "⚠ --allow-unreachable set with reason: ${REASON}"
      echo "   Recording to override-debt register + UAT.md 'Unreachable Debt' section"
      # Canonical override emit — fires override.used (run-complete contract) + OVERRIDE-DEBT entry.
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag "--allow-unreachable" --reason "$REASON" 2>/dev/null || \
        override_debt_record "unreachable-accept" "$PHASE_NUMBER" "$REASON" 2>/dev/null || \
        echo "unreachable-accept: phase=${PHASE_NUMBER} reason=\"${REASON}\" ts=$(date -u +%FT%TZ)" \
          >> "${PHASE_DIR}/build-state.log"
      # Stash for write_uat_md to surface
      echo "$BLOCKING_LIST" > "${VG_TMP}/uat-unreachable-debt.txt"
      echo "$REASON" > "${VG_TMP}/uat-unreachable-reason.txt"
    else
      exit 1
    fi
  fi

  # Surface RESOLVED (cross-phase) entries — informational, requires acknowledgment in UAT
  RESOLVED_LIST=$(${PYTHON_BIN} - "$TRIAGE_JSON" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
resolved = []
for gid, v in data.get("verdicts", {}).items():
    if not v.get("blocks_accept") and v["verdict"].startswith("cross-phase:"):
        owner = v["verdict"].split(":", 1)[1]
        resolved.append(f"{gid}|{owner}|{v['title'][:80]}")
print("\n".join(resolved))
PY
)
  if [ -n "$RESOLVED_LIST" ]; then
    echo "✓ UNREACHABLE triage resolved (cross-phase, owner accepted):"
    echo "$RESOLVED_LIST" | while IFS='|' read -r gid owner title; do
      echo "  • ${gid} → owned by Phase ${owner} — ${title}"
    done
    echo "$RESOLVED_LIST" > "${VG_TMP}/uat-unreachable-resolved.txt"
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "3b_unreachable_triage_gate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/3b_unreachable_triage_gate.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 3b_unreachable_triage_gate 2>/dev/null || true
```
</step>

<step name="3c_override_resolution_gate">
**Gate 3c: Override resolution gate (T5 — event-based, v1.8.0+)**

⛔ HARD GATE: if the override-debt register contains OPEN entries that are NOT resolved by a telemetry event (and NOT explicitly `--wont-fix`), BLOCK accept. Time-based expiry is BANNED — an override only clears when its bypassed gate re-runs cleanly OR the user explicitly declines to fix.

Rationale (from M9 claude reviewer): prior `auto_expire_days` model silently forgave real debt. An override entry must stay OPEN until either (a) the bypassed gate re-runs cleanly (auto-resolved via telemetry `override_resolved` event correlation), or (b) the user explicitly marks `--wont-fix` with justification.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 3c_override_resolution_gate 2>/dev/null || true

# Load helpers (v1.9.0 T3: source .sh, NOT .md — .md contains YAML frontmatter
# that bash cannot source. If .sh missing → real install bug, surface it.)
source .claude/commands/vg/_shared/lib/override-debt.sh 2>/dev/null || \
  echo "⚠ override-debt.sh missing — override resolution gate degraded" >&2

# Migrate any pre-v1.8.0 legacy entries (idempotent — adds legacy:true flag)
override_migrate_legacy 2>/dev/null || true

# List unresolved entries
UNRESOLVED_JSON=$(override_list_unresolved 2>/dev/null || echo "[]")
UNRESOLVED_COUNT=$(echo "$UNRESOLVED_JSON" | ${PYTHON_BIN} -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)

if [ "${UNRESOLVED_COUNT:-0}" -gt 0 ]; then
  # Filter to blocking-severity entries for THIS phase only
  BLOCKING_SEV="${CONFIG_DEBT_BLOCKING_SEVERITY:-critical}"
  BLOCKING_LIST=$(echo "$UNRESOLVED_JSON" | ${PYTHON_BIN} - "$BLOCKING_SEV" "$PHASE_NUMBER" <<'PY'
import json, sys
entries = json.load(sys.stdin)
blocking_sev = set(sys.argv[1].split())
phase = sys.argv[2]
out = []
for e in entries:
    if e.get("severity") in blocking_sev and e.get("phase") == phase:
        age_days = "?"
        try:
            from datetime import datetime, timezone
            ts = datetime.fromisoformat(e["logged_ts"].replace("Z","+00:00"))
            age_days = (datetime.now(timezone.utc) - ts).days
        except Exception: pass
        legacy_tag = " [LEGACY (cũ)]" if e.get("legacy") else ""
        out.append(f"  • {e['id']} [{e['severity']}] {e['flag']} · gate={e.get('gate_id') or 'n/a'} · age={age_days}d{legacy_tag}")
        out.append(f"     step: {e['step']}")
        out.append(f"     reason: {e['reason']}")
print("\n".join(out))
PY
)

  if [ -n "$BLOCKING_LIST" ]; then
    echo ""
    echo "⛔ Override resolution gate BLOCKED — unresolved overrides (bỏ qua, chưa giải quyết) for phase ${PHASE_NUMBER}:"
    echo ""
    echo "$BLOCKING_LIST"
    echo ""
    echo "Resolution paths (giải quyết):"
    echo "  1. Re-run the bypassed gate cleanly → auto-resolved via telemetry event (preferred)"
    echo "     Example: /vg:build ${PHASE_NUMBER} --gaps-only  OR  /vg:review ${PHASE_NUMBER}  OR  /vg:test ${PHASE_NUMBER}"
    echo ""
    echo "  2. /vg:override-resolve <DEBT-ID> --reason='<why>' [--wont-fix]"
    echo "     (v1.9.0+ — for overrides without natural re-run trigger. --wont-fix = permanent decline via AskUserQuestion confirmation. Marks WONT_FIX, logs telemetry.)"
    echo ""
    echo "  3. /vg:accept ${PHASE_NUMBER} --allow-unresolved-overrides --override-reason=\"<justification>\""
    echo "     (Accept path — logs NEW debt entry, still blocks the NEXT accept. Not a forgive, a defer.)"
    echo ""

    if [[ "$ARGUMENTS" =~ --allow-unresolved-overrides ]]; then
      REASON=$(echo "$ARGUMENTS" | grep -oE -- "--override-reason=\"[^\"]+\"" | sed "s/--override-reason=\"//; s/\"$//")
      if [ -z "$REASON" ]; then
        REASON=$(echo "$ARGUMENTS" | grep -oE -- "--override-reason='[^']+'" | sed "s/--override-reason='//; s/'$//")
      fi
      if [ -z "$REASON" ]; then
        REASON=$(echo "$ARGUMENTS" | grep -oE -- "--reason='[^']+'" | sed "s/--reason='//; s/'$//")
        [ -n "$REASON" ] && echo "⚠ --reason='...' is legacy; prefer --override-reason=\"...\" (entry contract)" >&2
      fi
      if [ -z "$REASON" ]; then
        echo "⛔ --allow-unresolved-overrides requires --override-reason=\"<why shipping with unresolved overrides>\""
        exit 1
      fi
      # v1.9.0 T1: rationalization guard — meta-override (forgive prior overrides). Highest-risk gate.
      RATGUARD_RESULT=$(rationalization_guard_check "override-resolution-gate" \
        "Accept gate blocks while critical OPEN overrides are unresolved. --allow-unresolved-overrides compounds debt — a meta-override forgiving prior overrides." \
        "unresolved_count=${UNRESOLVED_COUNT} reason=${REASON}")
      if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "override-resolution-gate" "--allow-unresolved-overrides" "$PHASE_NUMBER" "accept.override-resolution-gate" "$REASON"; then
        exit 1
      fi
      echo "⚠ --allow-unresolved-overrides set with reason: ${REASON}"
      echo "   Recording NEW debt entry (this acceptance itself becomes tracked debt)."
      # Canonical override emit — fires override.used + OVERRIDE-DEBT entry.
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag "--allow-unresolved-overrides" --reason "$REASON" 2>/dev/null || true
      # Log as new override-debt entry (critical severity — shows up on NEXT accept too)
      if type -t log_override_debt >/dev/null 2>&1; then
        log_override_debt "--allow-unresolved-overrides" "$PHASE_NUMBER" \
          "accept.override-resolution-gate" "$REASON" "override-resolution-gate"
      fi
      # Emit telemetry
      if type -t emit_telemetry_v2 >/dev/null 2>&1; then
        emit_telemetry_v2 "override_used" "$PHASE_NUMBER" "accept.override-resolution-gate" \
          "override-resolution-gate" "OVERRIDE" \
          "{\"flag\":\"--allow-unresolved-overrides\",\"reason\":\"${REASON//\"/\\\"}\",\"unresolved_count\":${UNRESOLVED_COUNT}}"
      fi
      # Stash for UAT.md surfacing
      echo "$BLOCKING_LIST" > "${VG_TMP}/uat-unresolved-overrides.txt"
      echo "$REASON" > "${VG_TMP}/uat-unresolved-override-reason.txt"
    else
      exit 1
    fi
  fi

  # Surface legacy (pre-v1.8.0) entries informationally — they need triage but don't auto-block
  # unless they're also at blocking severity (already caught above)
  LEGACY_LIST=$(echo "$UNRESOLVED_JSON" | ${PYTHON_BIN} <<'PY'
import json, sys
entries = json.load(sys.stdin)
legacy = [e for e in entries if e.get("legacy")]
for e in legacy:
    print(f"  • {e['id']} [{e['severity']}] {e['flag']} — logged {e['logged_ts']}")
PY
)
  if [ -n "$LEGACY_LIST" ]; then
    echo ""
    echo "⚠ Legacy (cũ) override entries detected — pre-v1.8.0, no telemetry gate_id link:"
    echo "$LEGACY_LIST"
    echo "   These need manual triage. Recommended: re-run the original gate OR mark --wont-fix."
  fi
fi

# ─── P20 D-06 — greenfield design Form B critical block ───────────────────
# Form B no-asset:greenfield-* entries (logged when /vg:blueprint D-12
# user picks "skip" or planner emits Form B for greenfield) are treated as
# critical-severity. ANY single greenfield Form B BLOCKs accept until
# resolved via /vg:design-scaffold or /vg:override-resolve with rationale.
# Distinct from P19 D-07 (count-based threshold for general design-*).
GREENFIELD_REPORT="${VG_TMP}/greenfield-debt.json"
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-override-debt-threshold.py \
  --debt-file "${PLANNING_DIR}/OVERRIDE-DEBT.md" \
  --kind 'design-greenfield-*' \
  --threshold 1 \
  --status unresolved \
  --output "${GREENFIELD_REPORT}" >/dev/null 2>&1
GF_RC=$?
if [ "$GF_RC" != "0" ] && [[ ! "$ARGUMENTS" =~ --allow-greenfield-shipped ]]; then
  GF_COUNT=$("${PYTHON_BIN:-python3}" -c "import json; print(json.load(open('${GREENFIELD_REPORT}')).get('count',0))" 2>/dev/null || echo 0)
  echo ""
  echo "⛔ P20 D-06 greenfield design block — ${GF_COUNT} unresolved Form B 'no-asset:greenfield-*' entries"
  echo ""
  echo "Resolution paths:"
  echo "  1. /vg:design-scaffold     (recommended — generate mockups, replace Form B with Form A slug)"
  echo "  2. /vg:override-resolve <ID> --rationale='<concrete reason ship without design>'"
  echo "  3. /vg:accept ${PHASE_NUMBER} --allow-greenfield-shipped --reason='<why>' (rationalization-guard)"
  echo ""
  echo "  Detail: ${GREENFIELD_REPORT}"
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "accept_greenfield_block" "${PHASE_NUMBER}" "accept.3c" \
      "design_greenfield" "BLOCK" "{\"count\":${GF_COUNT}}"
  fi
  exit 1
fi

# ─── P19 D-07 — design override-debt threshold gate ────────────────────────
# The 4-layer pixel pipeline has 4 override flags
# (--skip-design-pixel-gate / --skip-fingerprint-check / --skip-build-visual /
# --allow-design-drift). Each logs override-debt with kind=design-*. Without
# a count threshold, an executor can stack all 4 overrides per phase and ship
# silently. This gate caps that: ≥2 unresolved kind=design-* → BLOCK accept.
DESIGN_DEBT_THRESHOLD="$(vg_config_get override_debt.design_threshold 2 2>/dev/null || echo 2)"
DESIGN_DEBT_REPORT="${VG_TMP}/design-debt-threshold.json"
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-override-debt-threshold.py \
  --debt-file "${PLANNING_DIR}/OVERRIDE-DEBT.md" \
  --kind 'design-*' \
  --threshold "${DESIGN_DEBT_THRESHOLD}" \
  --status unresolved \
  --output "${DESIGN_DEBT_REPORT}" >/dev/null 2>&1
DESIGN_DEBT_RC=$?
if [ "$DESIGN_DEBT_RC" != "0" ] && [[ ! "$ARGUMENTS" =~ --allow-design-debt-threshold ]]; then
  DESIGN_DEBT_COUNT=$("${PYTHON_BIN:-python3}" -c "import json; print(json.load(open('${DESIGN_DEBT_REPORT}')).get('count',0))" 2>/dev/null || echo 0)
  echo ""
  echo "⛔ P19 D-07 design-debt threshold gate BLOCKED — ${DESIGN_DEBT_COUNT} unresolved kind=design-* entries (threshold: ${DESIGN_DEBT_THRESHOLD})"
  echo ""
  echo "Resolution paths:"
  echo "  1. /vg:override-resolve <ID> per entry — re-run gate cleanly OR mark WONT_FIX with rationalization-guard"
  echo "  2. /vg:build ${PHASE_NUMBER} --gaps-only — re-trigger affected gates so they auto-resolve"
  echo "  3. /vg:accept ${PHASE_NUMBER} --allow-design-debt-threshold --reason='<why shipping with stacked design overrides>'"
  echo ""
  echo "  Detail: ${DESIGN_DEBT_REPORT}"
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "accept_design_debt_threshold" "${PHASE_NUMBER}" "accept.3c" \
      "design_debt_threshold" "BLOCK" "{\"count\":${DESIGN_DEBT_COUNT},\"threshold\":${DESIGN_DEBT_THRESHOLD}}"
  fi
  exit 1
fi
```

**NEW command placeholder:** `/vg:override-resolve {gate_id} --wont-fix --reason='...'` — explicit decline path for overrides that will never be clean-resolved. Ships in v1.9+. Until then, use `--allow-unresolved-overrides` inline path (logs new debt entry, still blocks next accept — forces eventual confrontation).

Final action:
```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "3c_override_resolution_gate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/3c_override_resolution_gate.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 3c_override_resolution_gate 2>/dev/null || true
```
</step>
