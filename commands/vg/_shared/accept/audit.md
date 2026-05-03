# accept audit (STEP 7 — security baseline + learn + UAT.md write)

> **Size exception (F3-r2):** This ref is intentionally over the soft
> 400-line cap (current ~534 lines). It bundles three sub-steps that
> share a write-once finalization sequence:
> `6b_security_baseline` (~65 lines), `6c_learn_auto_surface` (~240
> lines, dominated by the bootstrap shadow/conflict pipeline),
> `6_write_uat_md` (~190 lines including the markdown template).
> Splitting would fragment the finalization order and force the entry
> contract to track three refs instead of one. Treat as an
> "audit bundle" — keep it monolithic until any single sub-step needs a
> dedicated ref.

Maps to 3 steps: `6b_security_baseline`, `6c_learn_auto_surface`,
`6_write_uat_md`. Combined ref because they share a write-once
finalization sequence.

<HARD-GATE>
You MUST run all 3 sub-steps in order:

1. `6b_security_baseline` — `verify-security-baseline.py` subprocess,
   idempotent. Result feeds UAT.md security section.
2. `6c_learn_auto_surface` — calls `/vg:learn --auto-surface` for y/n/e/s
   gate; surfaces lessons learned from this run for user adjudication.
3. `6_write_uat_md` — write `${PHASE_DIR}/${PHASE_NUMBER}-UAT.md` with
   Verdict line. content_min_bytes=200, content_required_sections=["Verdict:"]
   enforced by must_write contract (anti-forge).

Use `vg-load --priority` (NOT flat TEST-GOALS.md) to enumerate goals when
writing UAT.md (Phase F Task 30 absorption).
</HARD-GATE>

---

<step name="6b_security_baseline">
## Step 6b — Project-wide Security Baseline Gate (v2.5 Phase B.3)

Trước khi write UAT, verify project-wide security baseline (TLS/headers/
secrets/cookie flags/CORS/lockfile) đang đạt tầng 2+3 của security. Đây
là gate LAST defense trước production — nếu baseline drift sau các phase
trước, block accept + require fix.

Validator `verify-security-baseline.py` grep codebase + deploy scripts
(idempotent, khoảng 2-3 giây). Gate HARD cho critical findings (TLS
outdated, wildcard CORS + credentials, real secret trong .env.example),
WARN cho missing headers/cookie flags/lockfile.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 6b_security_baseline 2>/dev/null || true

echo ""
echo "━━━ Step 6b — Project-wide Security Baseline ━━━"

BASELINE_OUT=$(${PYTHON_BIN:-python3} \
  .claude/scripts/validators/verify-security-baseline.py \
  --phase "${PHASE_NUMBER}" --scope all 2>&1)
BASELINE_RC=$?

# Surface verdict + evidence
echo "$BASELINE_OUT" | tail -1 | ${PYTHON_BIN:-python3} -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    verdict = d.get('verdict', '?')
    ev = d.get('evidence', [])
    print(f'  verdict: {verdict} ({len(ev)} finding(s))')
    for e in ev[:5]:
        print(f'    - {e.get(\"type\")}: {e.get(\"message\",\"\")[:200]}')
    if len(ev) > 5:
        print(f'    ... +{len(ev)-5} more — see full output')
except Exception as exc:
    print(f'  (parse error: {exc})')
" 2>/dev/null || true

if [ "$BASELINE_RC" -ne 0 ]; then
  if [[ "$ARGUMENTS" =~ --allow-baseline-drift ]]; then
    BASELINE_REASON=$(echo "$ARGUMENTS" | grep -oE -- "--override-reason=\"[^\"]+\"" | sed "s/--override-reason=\"//; s/\"$//")
    [ -z "$BASELINE_REASON" ] && BASELINE_REASON=$(echo "$ARGUMENTS" | grep -oE -- "--override-reason='[^']+'" | sed "s/--override-reason='//; s/'$//")
    [ -z "$BASELINE_REASON" ] && BASELINE_REASON="critical baseline drift accepted by user"
    echo "⚠ Security baseline drift — OVERRIDE accepted via --allow-baseline-drift"
    # Canonical override emit — fires override.used + OVERRIDE-DEBT entry.
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
      --flag "--allow-baseline-drift" --reason "$BASELINE_REASON" 2>/dev/null || true
    type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
      "--allow-baseline-drift" "$PHASE_NUMBER" "accept.6b.security-baseline" \
      "$BASELINE_REASON" \
      "accept-baseline-${PHASE_NUMBER}"
    echo "override: baseline-drift phase=${PHASE_NUMBER} ts=$(date -u +%FT%TZ)" \
      >> "${PHASE_DIR}/accept-state.log" 2>/dev/null || true
  else
    echo ""
    echo "⛔ Security baseline failed project-wide check."
    echo "   Fix the findings above (TLS/CORS/secrets/headers/cookies/lockfile),"
    echo "   re-run /vg:accept ${PHASE_NUMBER}."
    echo ""
    echo "   Override (NOT recommended, logs to override-debt):"
    echo "     /vg:accept ${PHASE_NUMBER} --allow-baseline-drift --override-reason=\"<text>\""
    exit 1
  fi
else
  echo "  ✓ Project-wide security baseline PASS"
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "6b_security_baseline" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/6b_security_baseline.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 6b_security_baseline 2>/dev/null || true
```
</step>

<step name="6c_learn_auto_surface">
## Step 6c — Learn Auto-Surface (v2.5 Phase H)

Invoke tier-based candidate surface to close the UX loop. Previously user had to
remember `/vg:learn --review` + duyệt 10+ candidate cùng lúc → fatigue → defer-all.
Phase H limits surface to max 2 Tier B candidates per phase with dedupe pre-pass.

Config gate: skip entirely if `bootstrap.auto_surface_at_accept: false`.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 6c_learn_auto_surface 2>/dev/null || true

AUTO_SURFACE=$(${PYTHON_BIN:-python3} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*auto_surface_at_accept:\s*(true|false)', line, re.IGNORECASE)
    if m: print(m.group(1).lower()); break
" 2>/dev/null || echo "true")

if [ "$AUTO_SURFACE" != "true" ]; then
  echo "ℹ Learn auto-surface disabled (bootstrap.auto_surface_at_accept=false). Skip."
  touch "${PHASE_DIR}/.step-markers/6c_learn_auto_surface.done"
else
  echo ""
  echo "━━━ Step 6c — Learn Auto-Surface (Phase H v2.5) ━━━"

  CAND_FILE=".vg/bootstrap/CANDIDATES.md"
  if [ ! -f "$CAND_FILE" ]; then
    echo "  (no CANDIDATES.md — reflector hasn't drafted any yet, skip)"
  else
    # 1. Dedupe pass — merge title-similar candidates in-place
    ${PYTHON_BIN:-python3} .claude/scripts/learn-dedupe.py --apply 2>&1 | tail -5 || \
      echo "  (dedupe dry-run or failed, non-blocking)"

    # 2a. (v2.6 Phase A) Shadow evaluator — compute adaptive correctness rate per candidate.
    #     Output JSONL fed to classifier as --shadow-jsonl override. Critic flag
    #     opt-in via bootstrap.critic_enabled in vg.config.md.
    SHADOW_JSONL="${PHASE_DIR}/.shadow-eval.jsonl"
    CRITIC_ENABLED=$(${PYTHON_BIN:-python3} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*critic_enabled:\s*(true|false)', line, re.IGNORECASE)
    if m: print(m.group(1).lower()); break
" 2>/dev/null || echo "false")
    SHADOW_ARGS=""
    [ "$CRITIC_ENABLED" = "true" ] && SHADOW_ARGS="--critic"
    ${PYTHON_BIN:-python3} .claude/scripts/bootstrap-shadow-evaluator.py \
      $SHADOW_ARGS --output-jsonl "$SHADOW_JSONL" 2>/dev/null || \
      echo "  (shadow evaluator unavailable — classifier falls back to fixed-threshold)"

    # 2b. Classify all pending candidates by tier (adaptive override when shadow JSONL exists)
    if [ -s "$SHADOW_JSONL" ]; then
      TIER_JSONL=$(${PYTHON_BIN:-python3} .claude/scripts/learn-tier-classify.py \
        --all --shadow-jsonl "$SHADOW_JSONL" 2>/dev/null || echo "")
    else
      TIER_JSONL=$(${PYTHON_BIN:-python3} .claude/scripts/learn-tier-classify.py --all 2>/dev/null || echo "")
    fi

    if [ -z "$TIER_JSONL" ]; then
      echo "  (no pending candidates to surface)"
    else
      # 3. Tier A auto-promote (silent, 1-line log per promote)
      TIER_A_IDS=$(echo "$TIER_JSONL" | ${PYTHON_BIN:-python3} -c "
import json, sys
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        d = json.loads(line)
        if d.get('tier') == 'A':
            print(d['id'])
    except Exception: pass
")
      A_COUNT=0
      for AID in $TIER_A_IDS; do
        [ -z "$AID" ] && continue
        echo "  ✓ Auto-promoted Tier A candidate ${AID} (adaptive shadow correctness ≥ threshold)"
        # Emit telemetry — actual promote happens via /vg:learn --promote (orchestrator must invoke)
        type -t emit_telemetry >/dev/null 2>&1 && \
          emit_telemetry "bootstrap.rule_promoted" "PASS" "{\"id\":\"${AID}\",\"tier\":\"A\",\"auto\":true,\"path\":\"shadow_adaptive\"}" 2>/dev/null || true
        A_COUNT=$((A_COUNT+1))
      done
      [ "$A_COUNT" -gt 0 ] && echo ""

      # 3a. (v2.6 Phase A) Stale Tier A demotion — evaluator flagged demote=true
      #     for promoted rules whose correctness dropped below shadow_correctness_important.
      DEMOTE_IDS=$(echo "$TIER_JSONL" | ${PYTHON_BIN:-python3} -c "
import json, sys
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        d=json.loads(line)
        if d.get('demote') is True:
            print(d['id'])
    except Exception: pass
")
      for DID in $DEMOTE_IDS; do
        [ -z "$DID" ] && continue
        echo "  ⚠ Stale Tier A demote: ${DID} (correctness dropped below threshold over stale_phases window)"
        type -t emit_telemetry >/dev/null 2>&1 && \
          emit_telemetry "bootstrap.rule_demoted" "WARN" "{\"id\":\"${DID}\",\"reason\":\"stale_low_correctness\"}" 2>/dev/null || true
      done

      # 4. Tier B surface — cap via config, interactive y/n/e/s
      TIER_B_MAX=$(${PYTHON_BIN:-python3} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*tier_b_max_per_phase:\s*(\d+)', line)
    if m: print(m.group(1)); break
" 2>/dev/null || echo "2")

      TIER_B_COUNT=$(echo "$TIER_JSONL" | ${PYTHON_BIN:-python3} -c "
import json, sys
n=0
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        d=json.loads(line)
        if d.get('tier')=='B': n+=1
    except Exception: pass
print(n)
")

      if [ "${TIER_B_COUNT:-0}" -gt 0 ]; then
        echo "  ▸ ${TIER_B_COUNT} Tier B candidate(s) pending. Surface max ${TIER_B_MAX} now;"
        echo "    rest defer to next phase. Access all via: /vg:learn --review --all"
        echo ""

        # v2.6 Phase D — show proposed phase_pattern alongside each Tier B candidate.
        # Reflector populates phase_pattern based on evidence commit majors. Operator
        # can widen/narrow via e (edit) mode in the y/n/e/s gate before promotion.
        echo "$TIER_JSONL" | ${PYTHON_BIN:-python3} -c "
import json, sys
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        d=json.loads(line)
    except Exception: continue
    if d.get('tier') != 'B': continue
    pat = d.get('phase_pattern', '.*')
    pat_note = '' if pat == '.*' else ' [phase_pattern=' + pat + ']'
    print('    • {id}{note}: {title}'.format(
        id=d.get('id','?'),
        note=pat_note,
        title=d.get('title','(untitled)')[:80],
    ))
" 2>/dev/null || true

        # Orchestrator must call /vg:learn --auto-surface interactively for user y/n/e/s
        echo "  → Invoking /vg:learn --auto-surface (interactive)"
        # Emit surfaced event
        type -t emit_telemetry >/dev/null 2>&1 && \
          emit_telemetry "bootstrap.candidate_surfaced" "PASS" "{\"phase\":\"${PHASE_NUMBER}\",\"tier_b_count\":${TIER_B_COUNT},\"tier_b_limit\":${TIER_B_MAX}}" 2>/dev/null || true
      else
        echo "  (no Tier B candidates pending surface)"
      fi

      # 5. Tier C silent — access only via --review --all
      TIER_C_COUNT=$(echo "$TIER_JSONL" | ${PYTHON_BIN:-python3} -c "
import json, sys
n=0
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        d=json.loads(line)
        if d.get('tier')=='C': n+=1
    except Exception: pass
print(n)
")
      [ "${TIER_C_COUNT:-0}" -gt 0 ] && echo "  (Tier C parking: ${TIER_C_COUNT} low-confidence, silent — /vg:learn --review --all to view)"
    fi

    # v2.6 Phase C — pairwise conflict surface. Reuses the SAME y/n/e/s loop
    # as Tier B above (no new step number). When a contradiction is detected
    # between two ACTIVE candidates (similar prose OR opposing verbs), the
    # operator chooses to retire the loser, defer, edit, or skip. Winner is
    # auto-suggested via Phase A correctness → evidence_count fallback.
    CONFLICT_JSONL="${PHASE_DIR}/.conflict-pairs.jsonl"
    ${PYTHON_BIN:-python3} .claude/scripts/bootstrap-conflict-detector.py \
      --output-jsonl "$CONFLICT_JSONL" >/dev/null 2>&1 || \
      echo "  (conflict detector unavailable — skip conflict surface)"

    if [ -s "$CONFLICT_JSONL" ]; then
      CONFLICT_COUNT=$(wc -l < "$CONFLICT_JSONL" | tr -d ' ')
      echo ""
      echo "  ▸ ${CONFLICT_COUNT} conflict pair(s) detected between ACTIVE candidates."
      echo "    Each pair surfaces in the same y/n/e/s prompt loop as Tier B above."
      echo "    Options: y=retire loser+keep winner, n=defer both, e=edit, s=skip."
      echo ""
      ${PYTHON_BIN:-python3} -c "
import json, sys
with open(r'''${CONFLICT_JSONL}''', encoding='utf-8') as fh:
    for line in fh:
        line = line.strip()
        if not line: continue
        try:
            c = json.loads(line)
        except Exception:
            continue
        verb = c.get('opposing_verb')
        sim = c.get('similarity', 0.0)
        winner = c.get('winner') or 'TIE — operator decides'
        ec_a = c.get('evidence_count_a', 0)
        ec_b = c.get('evidence_count_b', 0)
        co_a = c.get('correctness_a')
        co_b = c.get('correctness_b')
        co_str = lambda v: f'{v:.2f}' if isinstance(v,(int,float)) else 'n/a'
        print(f\"    • {c['id_a']} vs {c['id_b']}\")
        sig = f'similarity={sim:.2f}'
        if verb: sig += f', opposing={verb}'
        print(f'      {sig}')
        print(f\"      winner suggestion: {winner} \"
              f\"(correctness {co_str(co_a)}/{co_str(co_b)}, evidence {ec_a}/{ec_b})\")
"
      # Orchestrator must call /vg:learn --auto-surface interactively to
      # process conflict pairs in the same loop as Tier B candidates.
      echo "  → Invoking /vg:learn --auto-surface (conflict resolution interactive)"
      type -t emit_telemetry >/dev/null 2>&1 && \
        emit_telemetry "bootstrap.conflict_surfaced" "PASS" "{\"phase\":\"${PHASE_NUMBER}\",\"conflict_count\":${CONFLICT_COUNT}}" 2>/dev/null || true
    fi
  fi

  touch "${PHASE_DIR}/.step-markers/6c_learn_auto_surface.done"
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 6c_learn_auto_surface 2>/dev/null || true
```

**Orchestrator hook:** khi step này echo `→ Invoking /vg:learn --auto-surface`, orchestrator MUST call the slash command inline so user can make y/n/e/s decisions. Non-interactive fallback: Tier B candidates stay in CANDIDATES.md for next phase's accept surface.

**v2.6 Phase C — conflict pair handler:** trong cùng prompt loop, nếu user chọn `y` cho pair (id_a vs id_b, winner=L-WIN), orchestrator MUST call:

```bash
source .claude/commands/vg/_shared/lib/override-debt.sh
override_auto_resolve_clean_run --target rule-retire <LOSER_ID> "winner=<WINNER_ID> conflict-resolved-at-accept"
```

Loser is whichever id ≠ winner; if winner=null (tie) and user picks `y`, prompt for a manual winner first. Mirrors override-debt auto-resolve pattern (single helper, two consumers).
</step>

<step name="6_write_uat_md">
Write `${PHASE_DIR}/${PHASE_NUMBER}-UAT.md` with ALL collected data.

**D2-r2 fix — pre-write `vg-load --priority` enumeration (NOT flat TEST-GOALS.md).**

Hydrate the per-priority goal lists used by Section B + Section B.2 via
`vg-load`. Output is consumed by the markdown template below. If the
checklist-builder subagent already produced `${VG_TMP}/uat-goals.txt`,
the per-priority files refine it with priority groupings; if not (e.g.
checklist-builder skipped Section B for an empty phase), this gives the
write step a deterministic source.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 6_write_uat_md 2>/dev/null || true

mkdir -p "${VG_TMP}" 2>/dev/null
for prio in critical important nice-to-have; do
  bash "${REPO_ROOT:-.}/.claude/scripts/vg-load.sh" \
    --phase "${PHASE_NUMBER}" --artifact goals --priority "$prio" 2>/dev/null \
    > "${VG_TMP}/uat-goals-${prio}.txt" || true
done
```

```markdown
# Phase {PHASE_NUMBER} — UAT Results

**Date:** {ISO timestamp}
**Tester:** {git user.name} (human UAT driven by VG artifacts)
**Profile:** {PROFILE}
**Verdict:** {ACCEPTED | REJECTED | DEFERRED}
**Test verdict (pre-UAT):** {VERDICT from SANDBOX-TEST.md}

## A. Decisions (CONTEXT.md P{phase}.D-XX — or legacy D-XX)
| ID | Title | Result | Note |
|----|-------|--------|------|
| P7.10.1.D-01 | {...} | PASS / FAIL / SKIP | {...} |
| D-02 (legacy) | {...} | PASS | run migrate-d-xx-namespace.py to normalize |
| ... | ... | ... | ... |

Totals: {passed}P / {failed}F / {skipped}S

## A.1 Foundation Citations (FOUNDATION.md F-XX — only populated if cited in phase artifacts)
| F-XX | Title | Result | Note |
|------|-------|--------|------|
| F-01 | Platform = web-saas | PASS / FAIL / SKIP | verified F-XX assumption holds for this phase |
| ... | ... | ... | ... |

Empty if no F-XX references found in phase artifacts.

## B. Goals (TEST-GOALS.md G-XX)
| G-XX | Title | Coverage Status | UAT Result | Note |
|------|-------|----------------|------------|------|
| G-01 | {...} | READY | PASS | {...} |
| G-02 | {...} | BLOCKED | — | Known gap |
| ... | ... | ... | ... | ... |

Totals: {passed}P / {failed}F / {skipped}S  (+ {N} pre-known gaps not gated)

## B.1 CRUD Surfaces (CRUD-SURFACES.md)

| Resource | Operations | Platform overlays | UAT Result | Note |
|----------|------------|-------------------|------------|------|
| Campaign | list,create,update,delete | web,backend | PASS / FAIL / SKIP | verify heading/filter/table/form/delete/security contract |
| ... | ... | ... | ... | ... |

Totals: {passed}P / {failed}F / {skipped}S

## B.2 UNREACHABLE Triage (from UNREACHABLE-TRIAGE.md)

Surfaced only when `/vg:review` produced triage. Each entry shows verdict + resolution path.

### Resolved (cross-phase, owner accepted) — informational
| G-XX | Owning phase | Title |
|------|-------------|-------|
| (populated from `${VG_TMP}/uat-unreachable-resolved.txt`) |

### Unreachable Debt (only present when `--allow-unreachable` was used)
**Override reason:** {from `${VG_TMP}/uat-unreachable-reason.txt`}

| G-XX | Verdict | Title | Required follow-up |
|------|---------|-------|---------------------|
| (populated from `${VG_TMP}/uat-unreachable-debt.txt`) |

These goals shipped with known gaps. Auto-tracked in override-debt register; will surface in `/vg:telemetry` and milestone audit until cleared.

## C. Ripple Acknowledgment (RIPPLE-ANALYSIS.md)
- Total HIGH callers: {N}
- Response: {acknowledged | risk-accepted | review-deferred}
- Affected files: {first 20}

## D. Design Fidelity (PLAN <design-ref>)
| Design ref | Result | Note |
|------------|--------|------|
| {ref} | PASS / FAIL / SKIP | {...} |

Totals: {passed}P / {failed}F / {skipped}S

### D.1 Mobile simulator captures (mobile-* only; omit for web)
| Screenshot path | Compared against | Result | Note |
|-----------------|------------------|--------|------|
| {phase/discover/G-01-ios.png} | {design-ref} | PASS / FAIL / SKIP | {...} |

## E. Deliverables (informational, from SUMMARY)
- {N} tasks built, see SUMMARY*.md

## F. Mobile Gates (mobile-* profiles only; omit for web)

Parsed from `build-state.log` (latest occurrence per gate kept).

| Gate | Name | Status | Reason | Timestamp |
|------|------|--------|--------|-----------|
| G6 | permission_audit | passed / failed / skipped | {disabled | no-paths | ...} | {UTC iso} |
| G7 | cert_expiry | ... | ... | ... |
| G8 | privacy_manifest | ... | ... | ... |
| G9 | native_module_linking | ... | ... | ... |
| G10 | bundle_size | ... | ... | ... |

### F.1 Mobile security audit findings (from /vg:test 5f_mobile_security_audit)

| Severity | Category | Summary | Evidence file |
|----------|----------|---------|---------------|
| {CRITICAL | HIGH | MEDIUM | LOW} | {category} | {count} match(es) | mobile-security/{category}.txt |

Reviewer acknowledgment: {ACK / REJECT / RISK-ACCEPTED}

## Issues Found
{bulleted list of FAIL items across all sections, or "None"}

## Overall Summary
- Total items: {N_total}
- Passed: {N_passed}
- Failed: {N_failed}
- Skipped/deferred: {N_skipped}
- Known pre-existing gaps (not gated): {N_gaps}

## Next Step
{
  ACCEPTED: "Phase complete. Run /vg:next or proceed to next phase.",
  REJECTED: "Address failed items via /vg:build ${PHASE_NUMBER} --gaps-only, then re-run /vg:test + /vg:accept.",
  DEFERRED: "Partial accept — open items: {list}. Revisit with /vg:accept ${PHASE_NUMBER} --resume."
}

---
_Generated by /vg:accept — data-driven UAT over VG artifacts._
```

Touch marker:
```bash
# (step-active already emitted at top of this step — D2-r2 vg-load --priority block above)

# v2.7 Phase E — schema validation post-write (BLOCK on UAT.md frontmatter drift).
# Validator resolves both canonical UAT.md and legacy ${phase}-UAT.md forms.
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-artifact-schema.py \
  --phase "${PHASE_NUMBER}" --artifact uat \
  > "${PHASE_DIR}/.tmp/artifact-schema-uat.json" 2>&1
SCHEMA_RC=$?
if [ "${SCHEMA_RC}" != "0" ]; then
  echo "⛔ UAT.md schema violation — see ${PHASE_DIR}/.tmp/artifact-schema-uat.json"
  cat "${PHASE_DIR}/.tmp/artifact-schema-uat.json"
  exit 2
fi

# v2.38.0 — Flow compliance aggregate audit (blueprint+build+review+test+accept itself)
# This is the cross-flow gate: bắt patterns where AI bypassed required steps in earlier flows.
if [[ "$ARGUMENTS" =~ --skip-compliance=\"([^\"]*)\" ]]; then
  COMP_REASON="${BASH_REMATCH[1]}"
else
  COMP_REASON=""
fi
COMP_SEV=$(vg_config_get "flow_compliance.severity" "warn" 2>/dev/null || echo "warn")
COMP_ACCEPT_ARGS=( "--phase-dir" "$PHASE_DIR" "--command" "accept" "--severity" "$COMP_SEV" )
[ -n "$COMP_REASON" ] && COMP_ACCEPT_ARGS+=( "--skip-compliance=$COMP_REASON" )

${PYTHON_BIN:-python3} .claude/scripts/verify-flow-compliance.py "${COMP_ACCEPT_ARGS[@]}"
COMP_RC=$?
if [ "$COMP_RC" -ne 0 ] && [ "$COMP_SEV" = "block" ]; then
  echo ""
  echo "⛔ Cross-flow compliance failed at accept gate."
  echo "   See .flow-compliance-accept.yaml — non-compliant flows logged."
  echo "   Override: --skip-compliance=\"<reason>\" (logged to OVERRIDE-DEBT)"
  exit 1
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "6_write_uat_md" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/6_write_uat_md.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 6_write_uat_md 2>/dev/null || true

# (OHOK-3 2026-04-22) Legacy `vg_run_complete` bash helper call removed —
# canonical `python vg-orchestrator run-complete` runs at step 7 below.
# One path only; no dual lifecycle.
```
</step>
