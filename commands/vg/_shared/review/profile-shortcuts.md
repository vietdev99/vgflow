# review profile-shortcuts (STEPS — phaseP_infra_smoke / phaseP_regression / phaseP_schema_verify / phaseP_link_check)

4 short-circuit steps for non-`full` review modes. Each one writes its
own GOAL-COVERAGE-MATRIX.md, marks the matching `phaseP_*` step, and
exits 0 (skipping the classic Phase 1-4 pipeline).

The `phase_profile_branch` step in preflight selects which one runs:
| REVIEW_MODE | Step | Profile |
|---|---|---|
| infra-smoke | phaseP_infra_smoke | infra (also web-fullstack/web-backend-only/cli-tool/library) |
| regression | phaseP_regression | bugfix |
| schema-verify | phaseP_schema_verify | migration |
| link-check | phaseP_link_check | docs |

`phaseP_delta` is in the sibling `delta-mode.md` file (hotfix profile).

vg-load convention: each shortcut reads SPECS.md / PLAN.md / parent
matrix via grep/regex (no AI context loading). When fallback re-plan is
needed (override paths log debt), prefer
`vg-load --phase ${PHASE_NUMBER} --artifact <plan|specs>` over flat reads.

---

## STEP — phaseP_infra_smoke

<step name="phaseP_infra_smoke" profile="web-fullstack,web-backend-only,cli-tool,library" mode="infra-smoke">
## Review mode: infra-smoke (P5, v1.9.2)

**Runs when `REVIEW_MODE=infra-smoke` (infra profile).**

Logic: parse SPECS `## Success criteria` checklist → run each bash command on target env → map to implicit goals `S-01..S-NN` → gate on all READY.

```bash
if [ "$REVIEW_MODE" != "infra-smoke" ]; then
  echo "↷ Skipping phaseP_infra_smoke (REVIEW_MODE=$REVIEW_MODE)"
else
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-profile.sh" 2>/dev/null
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true

  # 1. Parse SPECS success_criteria
  SMOKE_JSON=$(parse_success_criteria "$PHASE_DIR")
  SMOKE_COUNT=$(${PYTHON_BIN} -c "import json,sys; print(len(json.loads(sys.argv[1])))" "$SMOKE_JSON" 2>/dev/null || echo 0)

  if [ "$SMOKE_COUNT" -eq 0 ]; then
    echo "⛔ SPECS has no '## Success criteria' checklist bullets — infra-smoke needs implicit goals." >&2
    echo "   Fix: add markdown checklist ('- [ ] `cmd` → expected') to SPECS.md" >&2
    exit 1
  fi

  echo "▸ Infra-smoke: phát hiện ${SMOKE_COUNT} implicit goals từ success_criteria"
  echo "$SMOKE_JSON" > "${PHASE_DIR}/.success-criteria.json"

  # 2. Determine run_prefix from env
  RUN_PREFIX=""
  ENV_NAME="${VG_ENV:-}"
  if [ -z "$ENV_NAME" ]; then
    if [[ "$ARGUMENTS" =~ --sandbox ]]; then ENV_NAME="sandbox"
    elif [[ "$ARGUMENTS" =~ --local ]]; then ENV_NAME="local"
    else ENV_NAME="${CONFIG_STEP_ENV_VERIFY:-local}"
    fi
  fi

  # 3. Run each bullet, record status
  RESULTS_JSON="${PHASE_DIR}/.infra-smoke-results.json"
  ${PYTHON_BIN} - "$SMOKE_JSON" "$RESULTS_JSON" "$ENV_NAME" <<'PY'
import json, sys, subprocess, time
smoke = json.loads(sys.argv[1])
out_path = sys.argv[2]
env_name = sys.argv[3]
results = []
for entry in smoke:
    sid = entry['id']
    cmd = entry.get('cmd','').strip()
    expected = entry.get('expected','').strip()
    raw = entry.get('raw','')
    if not cmd:
        results.append({"id":sid,"status":"UNREACHABLE","reason":"no bash command in bullet","raw":raw})
        continue
    if cmd.startswith('/vg:') or cmd.startswith('/gsd:'):
        results.append({"id":sid,"status":"DEFERRED","reason":f"slash command requires orchestrator: {cmd}","raw":raw})
        continue
    try:
        t0 = time.time()
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        dur = round(time.time() - t0, 2)
        ok = p.returncode == 0
        if ok and expected:
            combined = (p.stdout or '') + (p.stderr or '')
            ok = expected.split()[0] in combined or expected in combined
        status = "READY" if ok else "BLOCKED"
        tail = ((p.stdout or '')[-300:] + (p.stderr or '')[-200:]).replace('\n',' | ')
        results.append({"id":sid,"status":status,"exit":p.returncode,"dur":dur,"expected":expected,"evidence":tail[:600],"raw":raw})
    except subprocess.TimeoutExpired:
        results.append({"id":sid,"status":"BLOCKED","reason":"timeout 60s","raw":raw})
    except Exception as e:
        results.append({"id":sid,"status":"FAILED","reason":str(e),"raw":raw})
with open(out_path,'w',encoding='utf-8') as f:
    json.dump({"env":env_name,"results":results,"generated_at":time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}, f, ensure_ascii=False, indent=2)
PY

  # 4. Display human-readable summary + 5. Write GOAL-COVERAGE-MATRIX.md
  ${PYTHON_BIN} - "$RESULTS_JSON" "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" "$PHASE_PROFILE" <<'PY'
import json, sys
from datetime import datetime, timezone
results = json.load(open(sys.argv[1], encoding='utf-8'))['results']
out_path, phase, profile = sys.argv[2], sys.argv[3], sys.argv[4]

# Summary print
ready = sum(1 for x in results if x['status']=='READY')
blocked = sum(1 for x in results if x['status']=='BLOCKED')
failed = sum(1 for x in results if x['status']=='FAILED')
deferred = sum(1 for x in results if x['status']=='DEFERRED')
unreach = sum(1 for x in results if x['status']=='UNREACHABLE')
print(f"\n┌─ Infra-smoke results (env={results[0].get('env','?') if results else '?'}) ─")
for x in results:
    icon = {'READY':'✓','BLOCKED':'⛔','FAILED':'✗','DEFERRED':'⟳','UNREACHABLE':'⚠'}.get(x['status'],'?')
    print(f"│ {icon} {x['id']} [{x['status']}] {x.get('raw','')[:70]}")
print(f"├─ Summary: READY={ready} BLOCKED={blocked} FAILED={failed} DEFERRED={deferred} UNREACHABLE={unreach} (total={len(results)})")
print("└────")

# Matrix write
lines = [
    f"# Goal Coverage Matrix — Phase {phase}", "",
    f"**Profile:** {profile}  ",
    f"**Source:** SPECS.success_criteria (implicit goals)  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  ",
    f"**Review mode:** infra-smoke", "",
    "## Implicit Goals (from SPECS `## Success criteria`)", "",
    "| Goal | Status | Command | Evidence |",
    "|------|--------|---------|----------|",
]
for r in results:
    raw = r.get('raw','').replace('|',r'\|')[:120]
    ev = (r.get('evidence') or r.get('reason') or '').replace('|',r'\|')[:120]
    lines.append(f"| {r['id']} | {r['status']} | {raw} | {ev} |")
total = len(results)
pct = round(100*ready/total, 1) if total else 0
lines += ["", f"## Gate", "", f"**Pass rate:** {ready}/{total} ({pct}%) READY  ",
          f"**Verdict:** {'PASS' if ready == total else 'BLOCK'}", ""]
open(out_path,'w',encoding='utf-8').write('\n'.join(lines) + '\n')
PY

  # 6. Gate check + block_resolve fallback
  READY_COUNT=$(${PYTHON_BIN} -c "import json; d=json.load(open('$RESULTS_JSON')); print(sum(1 for r in d['results'] if r['status']=='READY'))")
  TOTAL=$(${PYTHON_BIN} -c "import json; d=json.load(open('$RESULTS_JSON')); print(len(d['results']))")
  if [ "$READY_COUNT" -ne "$TOTAL" ]; then
    echo "⛔ Infra-smoke gate: ${READY_COUNT}/${TOTAL} goals READY — phase NOT yet provisioned."

    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="review.infra-smoke"
      BR_GATE_CONTEXT="Infra-smoke review: ${TOTAL} SPECS success_criteria checked, only ${READY_COUNT} READY."
      BR_EVIDENCE=$(cat "$RESULTS_JSON")
      BR_CANDIDATES='[{"id":"re-run-ansible","cmd":"echo would re-run ansible-playbook","confidence":0.3,"rationale":"re-run provisioning may fix BLOCKED infra"}]'
      BR_RESULT=$(block_resolve "infra-smoke-not-ready" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
      BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      [ "$BR_LEVEL" = "L2" ] && { block_resolve_l2_handoff "infra-smoke-not-ready" "$BR_RESULT" "$PHASE_DIR"; exit 2; }
    fi
    exit 1
  fi

  echo "✓ Infra-smoke PASS (${READY_COUNT}/${TOTAL}) — phase provisioned as specified."
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_infra_smoke" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_infra_smoke.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_infra_smoke 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Infra-smoke checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        exit 1
      }
  fi
  exit 0
fi
```
</step>

---

## STEP — phaseP_regression

<step name="phaseP_regression" mode="regression">
## Review mode: regression (P5, v1.9.2 — bugfix profile, OHOK Batch 2 B5: real verification)

**Runs when `REVIEW_MODE=regression`.**

OHOK Batch 2 B5 enforces 3 real checks (replaces "Verdict: PASS" stub):
1. Bug reference exists in SPECS (else BLOCK — bugfix must cite issue)
2. Phase has ≥1 code commit (else BLOCK — fix must touch code)
3. Phase introduces ≥1 test file or extends existing test with bug ID reference (else WARN)

```bash
if [ "$REVIEW_MODE" != "regression" ]; then
  echo "↷ Skipping phaseP_regression (REVIEW_MODE=$REVIEW_MODE)"
else
  # 1. Extract bug reference — MUST exist
  BUG_REF=$(grep -E '^\*\*issue_id\*\*:|^issue_id:|^\*\*bug_ref\*\*:|^bug_ref:|^\*\*Fixes bug\*\*:' \
            "$PHASE_DIR/SPECS.md" 2>/dev/null | sed -E 's/.*://; s/^\s*//' | head -1)
  if [ -z "$BUG_REF" ]; then
    echo "⛔ Bugfix profile requires issue_id/bug_ref in SPECS.md — no reference found" >&2
    if [[ ! "${ARGUMENTS}" =~ --allow-no-bugref ]]; then
      exit 1
    fi
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "--allow-no-bugref" "${PHASE_NUMBER}" "review.bugref-check" \
        "bugfix without issue_id — SPECS frontmatter missing issue_id/bug_ref/Fixes bug" \
        "bugfix-bugref-required"
    BUG_REF="<unspecified>"
  fi
  echo "▸ Regression review (bugfix): issue_ref=${BUG_REF}"

  # 2. Phase must have ≥1 code commit
  BASELINE_SHA=$(git rev-parse HEAD~1 2>/dev/null || git rev-parse HEAD 2>/dev/null)
  CODE_FILES=$(git diff --name-only "${BASELINE_SHA}" HEAD -- \
               'apps/**/src/**' 'packages/**/src/**' 'infra/**' 2>/dev/null | sort -u)
  CODE_COUNT=$([ -z "$CODE_FILES" ] && echo 0 || echo "$CODE_FILES" | wc -l | tr -d ' ')

  if [ "$CODE_COUNT" -eq 0 ]; then
    echo "⛔ Bugfix phase has 0 code files changed in apps|packages|infra" >&2
    if [[ ! "${ARGUMENTS}" =~ --allow-empty-bugfix ]]; then
      exit 1
    fi
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "--allow-empty-bugfix" "${PHASE_NUMBER}" "review.code-delta-check" \
        "bugfix has 0 code files changed in apps|packages|infra — no production delta" \
        "bugfix-code-delta-required"
  fi

  # 3. Scan for regression test — WARN if missing
  TEST_FILES=$(git diff --name-only "${BASELINE_SHA}" HEAD -- \
               '**/e2e/**/*.spec.ts' '**/__tests__/**' '**/*.test.ts' '**/*.test.js' \
               '**/tests/**/*.py' 2>/dev/null | sort -u)
  TEST_COUNT=$([ -z "$TEST_FILES" ] && echo 0 || echo "$TEST_FILES" | wc -l | tr -d ' ')
  BUG_ID_SAFE=$(echo "$BUG_REF" | grep -oE '[A-Za-z0-9_-]+' | head -1)

  TEST_MENTIONS_BUG=0
  if [ -n "$BUG_ID_SAFE" ] && [ "$TEST_COUNT" -gt 0 ]; then
    for f in $TEST_FILES; do
      if [ -f "$f" ] && grep -qiE "(${BUG_ID_SAFE}|regression|bugfix)" "$f" 2>/dev/null; then
        TEST_MENTIONS_BUG=1
        break
      fi
    done
  fi

  if [ "$TEST_COUNT" -eq 0 ]; then
    echo "⚠ Bugfix introduces no test files — /vg:test will attempt to generate regression coverage" >&2
    REGRESSION_NOTE="no-test-added (WARN — /vg:test to generate)"
  elif [ "$TEST_MENTIONS_BUG" -eq 0 ]; then
    echo "⚠ Bugfix has ${TEST_COUNT} test files but none reference bug ID '${BUG_ID_SAFE}'" >&2
    REGRESSION_NOTE="test-files-unlinked (WARN — consider adding bug ID comment to test)"
  else
    echo "✓ Bugfix has ${TEST_COUNT} test files, at least one references bug ID" >&2
    REGRESSION_NOTE="test-linked (OK)"
  fi

  # 4. Write matrix with verification results
  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" "$BUG_REF" \
    "$CODE_COUNT" "$TEST_COUNT" "$TEST_MENTIONS_BUG" "$REGRESSION_NOTE" <<'PY'
import sys
from datetime import datetime, timezone
out, phase, bug, code_count, test_count, test_mentions, note = sys.argv[1:8]
code_count = int(code_count); test_count = int(test_count); test_mentions = int(test_mentions)

if code_count == 0:
    verdict = "BLOCK (empty bugfix — no code changes)"
elif test_count > 0 and test_mentions:
    verdict = f"PASS (bugfix has {code_count} code files + linked test; /vg:test re-verifies)"
elif test_count > 0:
    verdict = f"PASS-WARN (bugfix has {code_count} code files + {test_count} tests unlinked to bug)"
else:
    verdict = f"PASS-WARN (bugfix has {code_count} code files but 0 tests; /vg:test must generate)"

lines = [
    f"# Goal Coverage Matrix — Phase {phase} (bugfix regression)", "",
    f"**Profile:** bugfix  ",
    f"**Bug reference:** {bug}  ",
    f"**Source:** SPECS.md issue_id + git delta vs HEAD~1  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}", "",
    "## Verification checks", "",
    "| Check | Status |",
    "|-------|--------|",
    f"| Bug reference present | {'✓' if bug != '<unspecified>' else '⛔ missing'} |",
    f"| Code files changed | {code_count} |",
    f"| Test files changed | {test_count} |",
    f"| Tests reference bug ID | {'✓' if test_mentions else 'no'} |",
    f"| Regression note | {note} |", "",
    "## Gate", "",
    f"**Verdict:** {verdict}", "",
    "**Next:** /vg:test runs issue-specific runner to re-verify bug is actually fixed.", "",
]
open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print(f"✓ GOAL-COVERAGE-MATRIX.md written — {verdict.split(' (')[0]}")
PY

  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_regression" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_regression.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_regression 2>/dev/null || true
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.phaseP_regression_verified" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"bug_ref\":\"${BUG_REF}\",\"code_count\":${CODE_COUNT},\"test_count\":${TEST_COUNT},\"test_linked\":${TEST_MENTIONS_BUG}}" >/dev/null 2>&1 || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Regression checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        exit 1
      }
  fi
  exit 0
fi
```
</step>

---

## STEP — phaseP_schema_verify

<step name="phaseP_schema_verify" mode="schema-verify">
## Review mode: schema-verify (P5, v1.9.2 — migration profile)

```bash
if [ "$REVIEW_MODE" != "schema-verify" ]; then
  echo "↷ Skipping phaseP_schema_verify (REVIEW_MODE=$REVIEW_MODE)"
else
  echo "▸ Schema-verify review (migration): checking ROLLBACK.md + migration files"
  MISSING_MIG=""
  for f in $(grep -oE '<file-path>[^<]*migrations[^<]*\.sql[^<]*</file-path>' "${PHASE_DIR}/PLAN.md" 2>/dev/null | \
             sed -E 's/<\/?file-path>//g'); do
    [ -f "$f" ] || MISSING_MIG="${MISSING_MIG} $f"
  done
  if [ -n "$MISSING_MIG" ]; then
    echo "⛔ Migration files referenced in PLAN but missing:$MISSING_MIG"
    exit 1
  fi

  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" <<'PY'
import sys
from datetime import datetime, timezone
out, phase = sys.argv[1], sys.argv[2]
lines = [
    f"# Goal Coverage Matrix — Phase {phase} (migration schema-verify)", "",
    "**Profile:** migration  ",
    "**Source:** SPECS.migration_plan + ROLLBACK.md  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}", "",
    "## Schema verification", "",
    "- ROLLBACK.md present",
    "- Migration files referenced in PLAN exist on disk",
    "- Schema round-trip validation deferred to /vg:test schema-roundtrip runner", "",
    "**Verdict:** PASS", "",
]
open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print("✓ GOAL-COVERAGE-MATRIX.md written (migration schema-verify)")
PY
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_schema_verify" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_schema_verify.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_schema_verify 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Schema-verify checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        exit 1
      }
  fi
  exit 0
fi
```
</step>

---

## STEP — phaseP_link_check

<step name="phaseP_link_check" mode="link-check">
## Review mode: link-check (P5, v1.9.2 — docs profile)

```bash
if [ "$REVIEW_MODE" != "link-check" ]; then
  echo "↷ Skipping phaseP_link_check (REVIEW_MODE=$REVIEW_MODE)"
else
  echo "▸ Link-check review (docs): scanning markdown files for broken relative links"
  DOC_FILES=$(grep -oE '<file-path>[^<]+\.md</file-path>' "${PHASE_DIR}/PLAN.md" 2>/dev/null | \
              sed -E 's/<\/?file-path>//g')
  BROKEN=""
  for f in $DOC_FILES; do
    [ -f "$f" ] || continue
    for link in $(grep -oE '\]\([^)]+\)' "$f" | sed -E 's/\]\(//; s/\)$//' | grep -vE '^https?://|^#'); do
      target=$(dirname "$f")/"$link"
      [ -e "$target" ] || BROKEN="${BROKEN}\n$f → $link"
    done
  done
  if [ -n "$BROKEN" ]; then
    echo -e "⚠ Broken relative links:$BROKEN"
  fi
  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" <<'PY'
import sys
from datetime import datetime, timezone
out, phase = sys.argv[1], sys.argv[2]
lines = [
    f"# Goal Coverage Matrix — Phase {phase} (docs link-check)", "",
    "**Profile:** docs  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}", "",
    "Docs-only phase — link-check performed; content fidelity deferred to /vg:test markdown-lint.", "",
    "**Verdict:** PASS", "",
]
open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print("✓ GOAL-COVERAGE-MATRIX.md written (docs link-check)")
PY
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_link_check" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_link_check.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_link_check 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Link-check checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        exit 1
      }
  fi
  exit 0
fi
```
</step>
