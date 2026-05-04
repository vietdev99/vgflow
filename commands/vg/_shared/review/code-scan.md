# review code-scan (STEP 2 — full mode only)

3 steps for the classic-pipeline pre-discovery sweep:
- `phase1_code_scan` — RFC v9 preflight + grep-based contract/element/i18n checks
- `phase1_5_ripple_and_god_node` — graphify cross-module impact analysis
- `phase2a_api_contract_probe` — curl probe + API-DOCS coverage gate before browser

Skipped when `REVIEW_MODE != full` (handled by `phase_profile_branch` in
preflight). When `--skip-scan` is set, `phase1_code_scan` short-circuits;
gate logged to override-debt.

<HARD-GATE>
You MUST execute `phase2a_api_contract_probe` before browser discovery on
web-* phases. Stale/broken API surface = hidden discovery noise. Failure
opens blocking-gate-prompt for user resolution (Leg 2).

API-DOCS coverage gate is HARD: missing API-DOCS.md endpoints relative to
API-CONTRACTS.md = exit 1. Diagnostic emitted to
`.tmp/api-docs-diagnostic.md`.

vg-load convention: where downstream phases (verdict, fix-loop) need PLAN
or API-CONTRACTS body in AI context, prefer `vg-load --phase
${PHASE_NUMBER} --artifact contracts --index` followed by per-endpoint
`--endpoint <slug>` over flat reads. Validator scripts in this ref read
flat artifacts (grep / curl / regex) — those do NOT enter AI context and
remain as-is per spec §1.5 + plan §7. API-DOCS.md is build-generated and
KEEP-FLAT (read with `Read ${PHASE_DIR}/API-DOCS.md`).
</HARD-GATE>

---

## STEP 2.1 — phase1 code scan (phase1_code_scan)

<step name="phase1_code_scan" mode="full">
## Phase 0.5: RFC v9 preflight (data invariants + RCRURD + cache hygiene)

**RFC v9 PR-D1/D2/F integration.** Runs deterministic gates BEFORE the
scanner so we fail fast on broken sandbox state instead of burning Haiku
tokens on a doomed scan.

```bash
# RFC v9 preflight — Codex-HIGH-5-ter fix: outer guard checks scripts/runtime
# only. The inner gates check their own artifacts (ENV-CONTRACT.md for
# invariants, FIXTURES/ for RCRURD). Previously the outer guard required
# BOTH scripts/runtime AND ENV-CONTRACT, so a phase with FIXTURES+lifecycle
# but no ENV-CONTRACT skipped RCRURD entirely.
PRE_OK=1
VG_SCRIPT_ROOT="${REPO_ROOT}/.claude/scripts"
[ -d "${VG_SCRIPT_ROOT}/runtime" ] || VG_SCRIPT_ROOT="${REPO_ROOT}/scripts"
if [ -d "${VG_SCRIPT_ROOT}/runtime" ]; then
  RFC_V9_GATE_RAN=0
  # Only echo the banner once when at least one gate has work to do
  HAS_INVARIANTS_FILE=0
  HAS_FIXTURES_DIR=0
  [ -f "${PHASE_DIR}/ENV-CONTRACT.md" ] && HAS_INVARIANTS_FILE=1
  [ -d "${PHASE_DIR}/FIXTURES" ] && HAS_FIXTURES_DIR=1
  if [ "$HAS_INVARIANTS_FILE" = "1" ] || [ "$HAS_FIXTURES_DIR" = "1" ]; then
    echo ""
    echo "━━━ Phase 0.5 — RFC v9 preflight ━━━"

    # 1. Reap expired leases + orphans (PR-F) — only if FIXTURES exist
    if [ "$HAS_FIXTURES_DIR" = "1" ] && [ -f "${VG_SCRIPT_ROOT}/fixture-prune.py" ]; then
      "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/fixture-prune.py" \
        --phase "$PHASE_NUMBER" --apply --skip-orphans 2>&1 | sed 's/^/  prune: /'
    fi

    # Codex-HIGH-1-ter fix: delete stale snapshot at entry. Otherwise post
    # mode at run-complete may load a snapshot from a PRIOR run.
    rm -f "${PHASE_DIR}/.rcrurd-pre-snapshot.json" 2>/dev/null || true
  fi  # end OR guard (banner + prune + snapshot reset)

  # 2. data_invariants N-consumer check (PR-C, live HTTP wiring stub-1 fix)
  # Codex-HIGH-5-ter: guarded by ENV-CONTRACT.md only — independent of FIXTURES.
  if [ -f "${VG_SCRIPT_ROOT}/preflight-invariants.py" ] && \
     [ -f "${PHASE_DIR}/ENV-CONTRACT.md" ]; then
    # Codex-R4-HIGH-2 fix: PREVIOUSLY parsed step_env.sandbox_test from
    # vg.config.md, but that's an ENV NAME like "local", not a URL. The
    # actual URL lives in ENV-CONTRACT.md under `target.base_url`. Use
    # that as canonical source; fall back to VG_BASE_URL env override.
    PRE_BASE=$("${PYTHON_BIN:-python3}" -c "
import re, sys
text = open('${PHASE_DIR}/ENV-CONTRACT.md', encoding='utf-8').read()
# Match \`target:\n  base_url: \"...\"\` block (handles single+double quotes)
m = re.search(r'^target:\s*\n((?:[ \t].*\n)+)', text, re.MULTILINE)
if m:
    body = m.group(1)
    bm = re.search(r'^\s*base_url:\s*[\"\\']?([^\"\\'\s#]+)', body, re.MULTILINE)
    if bm: print(bm.group(1))
" 2>/dev/null)
    [ -z "$PRE_BASE" ] && PRE_BASE="${VG_BASE_URL:-}"
    if [ -n "$PRE_BASE" ]; then
      PRE_OUT=$("${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/preflight-invariants.py" \
        --phase "$PHASE_NUMBER" --base-url "$PRE_BASE" \
        --severity "${VG_PREFLIGHT_SEVERITY:-block}" 2>&1)
      PRE_RC=$?
      echo "  preflight invariants: $(echo "$PRE_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    v = d.get("verdict","?")
    if v == "BLOCK":
        print(f"BLOCK ({len(d.get(\"gaps\",[]))} gap(s))")
    elif v == "WARN":
        print(f"WARN ({len(d.get(\"gaps\",[]))} gap(s) — VG_PREFLIGHT_SEVERITY=warn override active)")
    elif v == "PASS":
        print(f"PASS (checked {d.get(\"invariants_checked\",\"?\")} invariants)")
    elif v == "DRY_RUN":
        print("DRY_RUN")
    else:
        print(f"ERROR: {d.get(\"error\",\"unknown\")[:200]}")
except: print("parse-error")
')"
      # Codex-HIGH-5 fix: setup errors (RC=2) ALWAYS block, regardless of
      # severity gate. Missing api_index, bad creds, or missing base_url
      # mean we cannot proceed safely — silent skip would let scan run on
      # broken sandbox state.
      if [ "$PRE_RC" -eq 2 ]; then
        echo "⛔ Phase 0.5 preflight setup error — cannot proceed (RFC v9 PR-C):"
        echo "$PRE_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(f"   {d.get(\"error\",\"unknown setup error\")[:300]}")
except: print("   (could not parse error)")
'
        echo "   Fix path: ENV-CONTRACT.md must declare api_index for every"
        echo "   resource referenced in data_invariants. Verify vg.config.md"
        echo "   credentials_map covers all count_role values."
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.preflight_setup_error" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
        exit 1
      fi
      if [ "$PRE_RC" -eq 1 ] && [ "${VG_PREFLIGHT_SEVERITY:-block}" = "block" ]; then
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.preflight_invariants_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

        source scripts/lib/blocking-gate-prompt.sh
        EVIDENCE_PATH="${PHASE_DIR}/.vg/preflight-invariants-evidence.json"
        mkdir -p "$(dirname "$EVIDENCE_PATH")"
        cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "preflight_invariants",
  "summary": "Phase 0.5 preflight invariants gate BLOCK",
  "fix_hint": "Fix the data invariant gaps reported by the preflight validator. Check fix_hint in each gap entry."
}
JSON
        blocking_gate_prompt_emit "preflight_invariants" "$EVIDENCE_PATH" "error"
        # AI controller calls AskUserQuestion → resolve via Leg 2.
        # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
      fi
    else
      # Codex-HIGH-5-bis fix: missing base_url WAS silent skip — that's
      # the original "RFC v9 silently bypassed" failure mode. If
      # ENV-CONTRACT.md declares data_invariants, missing base_url IS a
      # setup error → block. If no invariants declared, this is a no-op
      # phase and skip is fine.
      HAS_INVARIANTS=$(grep -cE '^\s*data_invariants:' "${PHASE_DIR}/ENV-CONTRACT.md" 2>/dev/null || echo 0)
      if [ "$HAS_INVARIANTS" -gt 0 ] && [ "${VG_PREFLIGHT_SEVERITY:-block}" = "block" ]; then
        echo "⛔ Phase 0.5 preflight setup error — ENV-CONTRACT.md declares"
        echo "   data_invariants but no sandbox base_url found."
        echo "   Fix path: set step_env.sandbox_test in vg.config.md OR"
        echo "             export VG_BASE_URL=https://your-sandbox/."
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.preflight_no_base_url" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
        exit 1
      fi
      echo "  preflight invariants: SKIPPED (no base_url + no data_invariants — no-op)"
    fi
  fi

  # 3. RCRURD pre_state gate (PR-D2, live wiring stub-2 fix)
  # Calls scripts/rcrurd-preflight.py: walks FIXTURES/*.yaml, runs pre_state
  # GET + assert_jsonpath for each lifecycle block. Fail-fast before scan.
  if [ -f "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" ] && \
     [ -d "${PHASE_DIR}/FIXTURES" ]; then
    PRE_BASE_RC="${PRE_BASE:-${VG_BASE_URL:-}}"
    if [ -n "$PRE_BASE_RC" ]; then
      # Codex-HIGH-1-ter fix: capture snapshot in the SAME pre-mode call
      # (not a follow-up). The snapshot is read by post-mode at run-complete
      # to compute increased_by_at_least deltas against real pre-action state.
      RCRURD_SNAP="${PHASE_DIR}/.rcrurd-pre-snapshot.json"
      RCRURD_OUT=$("${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" \
        --phase "$PHASE_NUMBER" --base-url "$PRE_BASE_RC" \
        --severity "${VG_RCRURD_SEVERITY:-block}" \
        --capture-snapshot "$RCRURD_SNAP" 2>&1)
      RCRURD_RC=$?
      echo "  RCRURD pre_state: $(echo "$RCRURD_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    v = d.get("verdict","?")
    if v == "BLOCK":
        print(f"BLOCK ({d.get(\"failed\",0)}/{d.get(\"checked\",0)} failed)")
    elif v == "WARN":
        print(f"WARN ({d.get(\"failed\",0)}/{d.get(\"checked\",0)} failed — VG_RCRURD_SEVERITY=warn override active)")
    elif v == "PASS":
        print(f"PASS (checked {d.get(\"checked\",0)} fixtures)")
    else:
        print(f"ERROR: {d.get(\"error\",\"unknown\")[:200]}")
except: print("parse-error")
')"
      # Codex-HIGH-5 fix: RCRURD setup errors (RC=2) ALWAYS block.
      if [ "$RCRURD_RC" -eq 2 ]; then
        echo "⛔ Phase 0.5 RCRURD setup error — cannot proceed:"
        echo "$RCRURD_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(f"   {d.get(\"error\",\"unknown setup error\")[:300]}")
except: print("   (could not parse error)")
'
        echo "   Fix path: vg.config.md credentials_map must cover every role"
        echo "   referenced in FIXTURES/{G-XX}.yaml lifecycle.pre_state."
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_setup_error" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
        exit 1
      fi
      if [ "$RCRURD_RC" -eq 1 ] && [ "${VG_RCRURD_SEVERITY:-block}" = "block" ]; then
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_preflight_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

        source scripts/lib/blocking-gate-prompt.sh
        EVIDENCE_PATH="${PHASE_DIR}/.vg/rcrurd-preflight-evidence.json"
        mkdir -p "$(dirname "$EVIDENCE_PATH")"
        cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "rcrurd_preflight",
  "summary": "Phase 0.5 RCRURD gate BLOCK — fixture pre_state assertions failed",
  "fix_hint": "Ensure sandbox seed data matches each fixture's lifecycle.pre_state assertions"
}
JSON
        blocking_gate_prompt_emit "rcrurd_preflight" "$EVIDENCE_PATH" "error"
        # AI controller calls AskUserQuestion → resolve via Leg 2.
        # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
      fi

      # Codex-HIGH-1-ter fix: validate snapshot was captured. If pre-mode
      # passed assertions but snapshot file missing, post-mode delta
      # assertions will be wrong. Block if any fixture declares an
      # increased_by_at_least assertion (those NEED snapshot).
      if [ "$RCRURD_RC" -eq 0 ] && [ -d "${PHASE_DIR}/FIXTURES" ]; then
        NEEDS_SNAPSHOT=$(grep -lE 'increased_by_at_least|decreased_by_at_least' \
          "${PHASE_DIR}/FIXTURES"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
        if [ "$NEEDS_SNAPSHOT" -gt 0 ] && [ ! -f "$RCRURD_SNAP" ]; then
          echo "⛔ Phase 0.5 RCRURD setup error — pre-state snapshot not"
          echo "   captured but ${NEEDS_SNAPSHOT} fixture(s) declare delta"
          echo "   assertions (increased_by_at_least / decreased_by_at_least)."
          echo "   Without snapshot, post-mode would compare post-action to"
          echo "   post-action → delta=0 false-fail."
          "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_snapshot_missing" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
          exit 1
        fi
      fi
    else
      # Codex-HIGH-5-bis: missing base_url + FIXTURES with lifecycle = setup error
      HAS_LIFECYCLE=$(grep -lE '^lifecycle:' "${PHASE_DIR}/FIXTURES"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
      if [ "$HAS_LIFECYCLE" -gt 0 ] && [ "${VG_RCRURD_SEVERITY:-block}" = "block" ]; then
        echo "⛔ Phase 0.5 RCRURD setup error — FIXTURES declare ${HAS_LIFECYCLE}"
        echo "   lifecycle blocks but no sandbox base_url found."
        echo "   Fix path: set step_env.sandbox_test in vg.config.md OR"
        echo "             export VG_BASE_URL=https://your-sandbox/."
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_no_base_url" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
        exit 1
      fi
      echo "  RCRURD pre_state: SKIPPED (no base_url + no lifecycle — no-op)"
    fi
  fi
fi
```

## Phase 1: CODE SCAN (automated, <10 sec)

**If --skip-scan, skip this phase.**

```bash
# Echo scanner choice from step 0a so user sees their --scanner choice was honored
echo ""
echo "━━━ Phase 1 — Code scan (scanner=${VG_SCANNER:-haiku-only}) ━━━"
case "${VG_SCANNER:-haiku-only}" in
  haiku-only)
    echo "  Mode: Haiku-only — fastest path, default depth."
    ;;
  codex-inline)
    echo "  Mode: Codex inline scanner — main orchestrator owns MCP/browser; no Haiku spawn."
    ;;
  codex-supplement)
    echo "  Mode: Haiku + Codex CLI supplement (queued for v2.42.2 wiring)."
    echo "  Note: v2.42.1 records the choice; supplemental Codex scan invocation lands in next iter."
    ;;
  gemini-supplement)
    echo "  Mode: Haiku + Gemini CLI supplement (queued for v2.42.2 wiring)."
    echo "  Note: v2.42.1 records the choice; supplemental Gemini scan invocation lands in next iter."
    ;;
  council-all)
    echo "  Mode: Haiku + Codex + Gemini + Claude council (queued for v2.42.2 wiring)."
    echo "  Note: v2.42.1 records the choice; full council scan invocation lands in next iter."
    ;;
esac
echo ""
```

### 1a: Contract Verify (grep)

Read `.claude/skills/api-contract/SKILL.md` — Mode: Verify-Grep.
Read `.claude/commands/vg/_shared/env-commands.md` — contract_verify_grep(phase_dir, "both").

Run contract_verify_grep against `$SCAN_PATTERNS` paths from config:
- BE routes vs API-CONTRACTS.md endpoints (grep — not loaded into AI context)
- FE API calls vs API-CONTRACTS.md endpoints (grep — not loaded into AI context)

Result:
- 0 mismatches → PASS
- Mismatches → WARNING (not block — browser discovery will confirm)

### 1b: Element Inventory (grep — reference data, NOT gate)

Count UI elements using `$SCAN_PATTERNS` from config:

```
For each source file matching config.code_patterns.web_pages:
  Run element_count(file) from env-commands.md
  → uses SCAN_PATTERNS keys (modals, tables, forms, actions, etc.)
```

Write `${PHASE_DIR}/element-counts.json` — **reference data** for discovery (not a gate).

### 1c: i18n Key Resolution Check (config-gated)

**Skip conditions:**
- `config.i18n.enabled` is false or absent → skip entirely
- `config.i18n.locale_dir` is empty → skip

**Purpose:** Verify every i18n key used in phase-changed FE files actually resolves to a
translation string. Missing keys = user sees raw key like `dashboard.title` instead of text.

```bash
I18N_ENABLED="${config.i18n.enabled:-false}"
if [ "$I18N_ENABLED" = "true" ]; then
  LOCALE_DIR="${config.i18n.locale_dir}"
  DEFAULT_LOCALE="${config.i18n.default_locale:-en}"
  KEY_FN="${config.i18n.key_function:-t}"

  # Get FE files changed in this phase
  CHANGED_FE=$(git diff --name-only HEAD~${COMMIT_COUNT:-5} HEAD -- "${config.code_patterns.web_pages}" 2>/dev/null)

  if [ -n "$CHANGED_FE" ] && [ -d "$LOCALE_DIR" ]; then
    # Extract all i18n keys from changed files
    I18N_KEYS=$(echo "$CHANGED_FE" | xargs grep -ohE "${KEY_FN}\(['\"]([^'\"]+)['\"]\)" 2>/dev/null | \
      grep -oE "['\"][^'\"]+['\"]" | tr -d "'" | tr -d '"' | sort -u)

    # Check each key resolves in default locale file
    LOCALE_FILE=$(find "$LOCALE_DIR" -path "*/${DEFAULT_LOCALE}*" -name "*.json" 2>/dev/null | head -1)
    MISSING_KEYS=0

    if [ -n "$LOCALE_FILE" ] && [ -n "$I18N_KEYS" ]; then
      while IFS= read -r KEY; do
        [ -z "$KEY" ] && continue
        # Check key exists in JSON (dot-path → nested lookup)
        EXISTS=$(${PYTHON_BIN} -c "
import json, sys
from pathlib import Path
data = json.loads(Path('$LOCALE_FILE').read_text())
keys = '$KEY'.split('.')
ref = data
for k in keys:
    if isinstance(ref, dict) and k in ref:
        ref = ref[k]
    else:
        print('MISSING')
        sys.exit(0)
print('OK')
" 2>/dev/null)
        if [ "$EXISTS" = "MISSING" ]; then
          echo "  WARN: i18n key '$KEY' not found in ${LOCALE_FILE}"
          MISSING_KEYS=$((MISSING_KEYS + 1))
        fi
      done <<< "$I18N_KEYS"
    fi

    echo "i18n check: $(echo "$I18N_KEYS" | wc -l) keys, ${MISSING_KEYS} missing"
  fi
fi
```

Result routing: `MISSING_KEYS > 0` → GAPS_FOUND (not block — may be added in later commit).

Display:
```
Phase 1 Code Scan:
  Contract verify: {PASS|WARNING — N mismatches}
  Element inventory: {N} files, ~{M} interactive elements
  i18n key check: {N keys checked, M missing|skipped (disabled)}
  (Reference data for Phase 2 — not a gate)
```

### 1d: Override Debt Auto-Resolve (v2.7 Phase M extension)

When phase1_code_scan completes with no scan-driven regression (contract verify
PASS or WARNING-only, i18n missing-keys treated as non-blocking), the 5
Phase-M gate_ids on the supported list can auto-resolve any matching prior
debt entries from earlier phases.

The skip-when-current-phase-also-uses-flag guard mirrors the v2.6.1 accept.md
pattern: never resolve a gate_id whose flag is being used right now.

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
if type -t override_auto_resolve_clean_run >/dev/null 2>&1; then
  RESOLUTION_EVENT_ID="review-clean-${PHASE_NUMBER}-$(date -u +%s)"
  if [[ ! "${ARGUMENTS}" =~ --allow-orthogonal-hotfix ]]; then
    override_auto_resolve_clean_run "allow-orthogonal-hotfix" "${PHASE_NUMBER}" \
      "${RESOLUTION_EVENT_ID}" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-no-bugref ]]; then
    override_auto_resolve_clean_run "allow-no-bugref" "${PHASE_NUMBER}" \
      "${RESOLUTION_EVENT_ID}" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-empty-hotfix ]]; then
    override_auto_resolve_clean_run "allow-empty-hotfix" "${PHASE_NUMBER}" \
      "${RESOLUTION_EVENT_ID}" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-empty-bugfix ]]; then
    override_auto_resolve_clean_run "allow-empty-bugfix" "${PHASE_NUMBER}" \
      "${RESOLUTION_EVENT_ID}" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-unresolved-overrides ]]; then
    override_auto_resolve_clean_run "allow-unresolved-overrides" "${PHASE_NUMBER}" \
      "${RESOLUTION_EVENT_ID}" 2>&1 | sed 's/^/  /'
  fi
fi
```

The helper emits one `override.auto_resolved` audit event per gate_id that
matched at least one OPEN debt entry from a prior phase (R9: gate_id +
timestamp + git_sha). No-op when there are no matching entries.
</step>

---

## STEP 2.2 — ripple + god node (phase1_5_ripple_and_god_node)

<step name="phase1_5_ripple_and_god_node" mode="full">
## Phase 1.5: GRAPHIFY IMPACT ANALYSIS (cross-module ripple + god node coupling)

**Purpose**: retroactive safety net for changes that affect callers outside the phase's changed-files list. Complement to /vg:build's proactive caller graph.

**Prereq**: `_shared/config-loader.md` already resolved `$GRAPHIFY_ACTIVE`, `$GRAPHIFY_GRAPH_PATH`, `$PYTHON_BIN`, `$REPO_ROOT`, `$VG_TMP` at command start.

```bash
if [ "$GRAPHIFY_ACTIVE" != "true" ]; then
  echo "ℹ Graphify not available — skipping Phase 1.5"
  echo "RIPPLE_SKIPPED=true" > "${PHASE_DIR}/uat-ripples.txt"
  echo "RIPPLE_SKIP_REASON=graphify-inactive" >> "${PHASE_DIR}/uat-ripples.txt"
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase1_5_ripple_and_god_node" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase1_5_ripple_and_god_node.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase1_5_ripple_and_god_node 2>/dev/null || true
  # skip to Phase 2
fi
```

**⛔ BUG #3 fix (2026-04-18): Stale graphify check + auto-rebuild before ripple analysis.**

Without this, ripple analysis runs against stale graph → reports "0 callers affected"
because graph doesn't know about new callers added since last build. Falsely safe verdict.

```bash
if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
  GRAPH_BUILD_EPOCH=$(stat -c %Y "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || stat -f %m "$GRAPHIFY_GRAPH_PATH" 2>/dev/null)
  COMMITS_SINCE=$(git log --since="@${GRAPH_BUILD_EPOCH}" --oneline 2>/dev/null | wc -l | tr -d ' ')
  STALE_THRESHOLD="${GRAPHIFY_STALE_WARN:-50}"

  echo "Review Phase 1.5: graphify ${COMMITS_SINCE} commits since last build"

  # Always rebuild before ripple — review is the SAFETY NET, must be accurate
  if [ "${COMMITS_SINCE:-0}" -gt 0 ]; then
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/graphify-safe.sh"
    vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "review-phase1_5-${PHASE_NUMBER}" || {
      echo "⛔ Review cannot trust ripple analysis with stale graph"
      echo "   Fix manually: ${PYTHON_BIN} -m graphify update ."
    }
  fi
fi
```

If graphify active, proceed:

### A. Collect phase's changed files (in bash)

```bash
# Prefer phase commit range if available (git tag from /vg:build step 8b: "vg-build-{phase}-wave-{N}-start")
PHASE_START_TAG=$(git tag --list "vg-build-${PHASE_NUMBER}-wave-*-start" | sort -t'-' -k5,5n | head -1)
if [ -n "$PHASE_START_TAG" ]; then
  CHANGED_FILES=$(git diff --name-only "$PHASE_START_TAG" HEAD | sort -u)
else
  # Fallback: diff against merge-base with main
  CHANGED_FILES=$(git diff --name-only $(git merge-base HEAD main) HEAD | sort -u)
fi

# Filter to source files only (exclude ${PLANNING_DIR}/, .claude/, node_modules, etc)
CHANGED_SRC=$(echo "$CHANGED_FILES" | grep -vE '^\.(planning|claude|codex)/|/node_modules/|/dist/|/build/|/target/|^graphify-out/' || true)

echo "Phase changed $(echo "$CHANGED_SRC" | wc -l) source files"
echo "$CHANGED_SRC" > "${PHASE_DIR}/.ripple-input.txt"
```

### B. Ripple analysis (bash — hybrid script, no MCP)

**Why script not MCP**: graphify TS extractor doesn't resolve path aliases (e.g., `@/hooks/X` → `src/hooks/X`). Pure MCP queries miss alias-imported callers. The hybrid script uses graphify + git grep, catches both.

```bash
${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
  --changed-files-input "${PHASE_DIR}/.ripple-input.txt" \
  --config .claude/vg.config.md \
  --graphify-graph "$GRAPHIFY_GRAPH_PATH" \
  --output "${PHASE_DIR}/.ripple.json"
```

Output (`.ripple.json`):
```json
{
  "mode": "ripple",
  "tools_used": ["grep(rg|git)", "graphify"],
  "changed_files_count": N,
  "ripples": [
    {
      "changed_file": "<path>",
      "exports_at_risk": ["SymbolA", "SymbolB"],
      "callers": [
        {"file": "<caller>", "line": N, "symbol": "SymbolA", "source": ["grep(...)"]}
      ]
    }
  ],
  "affected_callers": ["<unique caller paths>"]
}
```

Script extracts exports via stack-agnostic regex (TS/JS/Rust/Python/Go), then searches scope_apps for each symbol using grep + graphify enrichment. Every caller NOT in the changed list = at-risk.

### C. God node coupling check (bash — Python API, no MCP)

```bash
${PYTHON_BIN} - <<'PY' > "${PHASE_DIR}/.god-nodes.json"
import json
from graphify.analyze import god_nodes
from graphify.build import build_from_json
from networkx.readwrite import json_graph
from pathlib import Path
data = json.loads(Path("${GRAPHIFY_GRAPH_PATH}").read_text(encoding="utf-8"))
G = json_graph.node_link_graph(data, edges="links")
gods = god_nodes(G)[:20]  # top-20 highest-degree nodes
print(json.dumps([{"label": g.get("label"), "source_file": g.get("source_file"), "degree": g.get("degree")} for g in gods], indent=2))
PY
```

Then for each god node, check if `git diff $PHASE_START_TAG HEAD` includes lines adding an import pointing to god_node's source_file — flag as coupling warning (language-aware via config.scan_patterns).

### D. Classify caller severity (orchestrator memory, post-script)

Script returns `callers` list per changed file. Orchestrator classifies:
- **HIGH**: caller's `symbol` match is a function/class/schema name (likely direct usage)
- **LOW**: caller matches only via barrel import (symbol is the filename itself, or in a re-export block)

Default LOW for ambiguous — reverse of earlier design. Rationale: too many HIGH = noise → users ignore. Start LOW, escalate via evidence.

### D. Write RIPPLE-ANALYSIS.md

Write `${PHASE_DIR}/RIPPLE-ANALYSIS.md`:

```markdown
# Phase {N} — Ripple Analysis (Graphify)

**Generated**: {ISO timestamp}
**Changed files in phase**: {N}
**Graph**: `graphify-out/graph.json` ({node_count} nodes)

## High-Severity Ripples (REVIEW REQUIRED)

Callers of changed code that were NOT updated in this phase. Verify these callers still work with the new symbol shapes.

| Caller File | Calls Changed Symbol | Changed In | Severity |
|---|---|---|---|
| {caller.file} | {symbol} | {changed.file} | HIGH |
| ... | ... | ... | ... |

## Low-Severity Ripples (likely safe — scan for regressions)

| Caller File | Import Type | Changed In |
|---|---|---|
| {caller.file} | barrel re-export | {changed.file} |

## God Node Coupling Warnings

| God Node | Degree | New Edge From | Recommendation |
|---|---|---|---|
| {god.label} | {N} | {changed.file} | Refactor consideration |

## Summary

- HIGH ripples: {N}  (review these callers manually or via browser)
- LOW ripples: {N}
- God node warnings: {N}
- Action: Phase 2 browser discovery will prioritize checking HIGH-ripple caller paths first
```

### E. Inject findings into Phase 2 + Phase 4

**Phase 2 priority hint**: if ripple affects a specific view, browser discovery should navigate there first (higher priority in scan queue). Save `.ripple-browser-priorities.json`:

```json
{ "priority_urls": ["route1", "route2"], "reason": "high-ripple callers live here" }
```

**Phase 4 goal comparison input**: include RIPPLE-ANALYSIS.md as evidence. If a goal says "Feature X works" and Feature X uses a HIGH-ripple caller that wasn't verified → flag as UNVERIFIED instead of READY.

### Fallback (graphify disabled, empty graph, or MCP errors)

Skip Phase 1.5 with warning:
```
ℹ Phase 1.5 skipped — graphify not active. Cross-module ripple bugs may
  only be caught at Phase 2 browser discovery or Phase 5 test. To enable:
  set graphify.enabled=true in .claude/vg.config.md + graphify update .
```

Still write empty `RIPPLE-ANALYSIS.md` stub so Phase 4 doesn't error on missing file:
```
# Phase {N} — Ripple Analysis (SKIPPED)

Graphify inactive. Enable for cross-module impact detection.
```

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase1_5_ripple_and_god_node" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase1_5_ripple_and_god_node.done"`
</step>

---

## STEP 2.3 — API contract probe (phase2a_api_contract_probe)

<step name="phase2a_api_contract_probe" profile="web-fullstack,web-frontend-only,web-backend-only" mode="full">
## Phase 2a.5: API CONTRACT PROBE (curl, no browser)

**Mandatory before browser discovery for web feature phases.**

Purpose:
- prove the current run touched the live API surface before any browser scan
- fail fast on broken/stale backend routes instead of hiding the problem behind discovery noise
- create a fresh artifact that runtime_contract can enforce even on older pinned phases
- verify API-DOCS.md fully covers API-CONTRACTS.md so discovery/test use the built API reference, not stale prose

**Scope:** low-cost readiness gate only. This is NOT the full `/vg:test` runtime contract verification and NOT a project-specific mutation batch. Mutating endpoints are probed safely (OPTIONS / existence check), not executed for side effects.

**vg-load convention:** the curl probe + `verify-api-docs-coverage.py` validator
both read API-CONTRACTS.md and API-DOCS.md from disk via grep/regex
extraction — those reads do NOT enter AI context. If a downstream lens or
fix step needs an endpoint loaded for AI inspection, prefer
`vg-load --phase ${PHASE_NUMBER} --artifact contracts --endpoint <slug>`
over flat reads of the artifact.

```bash
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔎 Phase 2a.5 — API contract probe"
echo "   Curl API contracts trước browser discovery"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2a_api_contract_probe >/dev/null 2>&1 || true

API_PROBE_OUT="${PHASE_DIR}/api-contract-precheck.txt"
API_DOCS_CHECK_OUT="${PHASE_DIR}/api-docs-check.txt"
VG_SCRIPT_ROOT="${REPO_ROOT:-.}/.claude/scripts"
[ -d "$VG_SCRIPT_ROOT" ] || VG_SCRIPT_ROOT="${REPO_ROOT:-.}/scripts"
PROBE_SCRIPT="${VG_SCRIPT_ROOT}/review-api-contract-probe.py"
INTERFACE_CHECK_OUT="${PHASE_DIR}/.tmp/interface-standards-review.json"

if [ ! -f "$PROBE_SCRIPT" ]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.api_precheck_blocked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"missing_helper\"}" >/dev/null 2>&1 || true

  source scripts/lib/blocking-gate-prompt.sh
  EVIDENCE_PATH="${PHASE_DIR}/.vg/api-precheck-evidence.json"
  mkdir -p "$(dirname "$EVIDENCE_PATH")"
  cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "api_precheck",
  "summary": "API contract probe setup error — missing helper: $PROBE_SCRIPT",
  "fix_hint": "Ensure review-api-contract-probe.py exists in .claude/scripts/ or scripts/"
}
JSON
  blocking_gate_prompt_emit "api_precheck" "$EVIDENCE_PATH" "error"
  # AI controller calls AskUserQuestion → resolve via Leg 2.
  # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
fi

mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
INTERFACE_VAL="${VG_SCRIPT_ROOT}/validators/verify-interface-standards.py"
if [ -f "$INTERFACE_VAL" ]; then
  "${PYTHON_BIN:-python3}" "$INTERFACE_VAL" \
    --phase-dir "$PHASE_DIR" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
    > "$INTERFACE_CHECK_OUT" 2>&1
  INTERFACE_RC=$?
  cat "$INTERFACE_CHECK_OUT"
  if [ "$INTERFACE_RC" -ne 0 ]; then
    echo "⛔ Interface standards gate failed — review cannot continue with undefined API/FE error semantics." >&2
    DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.interface_standards" \
        --phase-dir "$PHASE_DIR" \
        --input "$INTERFACE_CHECK_OUT" \
        --out-md "${PHASE_DIR}/.tmp/interface-standards-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/interface-standards-diagnostic.md" 2>/dev/null || true
    fi
    exit 1
  fi
else
  echo "⛔ Interface standards validator missing: $INTERFACE_VAL" >&2
  exit 1
fi

"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-api-docs-coverage.py \
  --phase "${PHASE_NUMBER}" \
  > "${API_DOCS_CHECK_OUT}" 2>&1
API_DOCS_RC=$?
cat "${API_DOCS_CHECK_OUT}"
if [ "$API_DOCS_RC" -ne 0 ]; then
  echo "⛔ API docs coverage failed — browser discovery is not allowed to continue with incomplete API-DOCS.md." >&2
  DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
  if [ -f "$DIAG_SCRIPT" ]; then
    "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
      --gate-id "review.api_docs_contract_coverage" \
      --phase-dir "$PHASE_DIR" \
      --input "$API_DOCS_CHECK_OUT" \
      --out-md "${PHASE_DIR}/.tmp/api-docs-diagnostic.md" \
      >/dev/null 2>&1 || true
    cat "${PHASE_DIR}/.tmp/api-docs-diagnostic.md" 2>/dev/null || true
  fi
  exit 1
fi

"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/emit-evidence-manifest.py" \
  --path "${PHASE_DIR}/api-docs-check.txt" \
  --source-inputs "${PHASE_DIR}/API-CONTRACTS.md,${PHASE_DIR}/API-DOCS.md,.claude/vg.config.md" \
  --producer "vg:review/phase2a_api_contract_probe"
API_DOCS_MANIFEST_RC=$?
if [ "$API_DOCS_MANIFEST_RC" -ne 0 ]; then
  echo "⛔ API docs check wrote report but failed to bind evidence to current run." >&2
  exit 1
fi

# Resolve base URL from the same canonical source used by Phase 0.5 preflight.
API_PROBE_BASE=$("${PYTHON_BIN:-python3}" -c "
import re, sys
path = '${PHASE_DIR}/ENV-CONTRACT.md'
try:
    text = open(path, encoding='utf-8').read()
except OSError:
    sys.exit(0)
m = re.search(r'^target:\\s*\\n((?:[ \\t].*\\n)+)', text, re.MULTILINE)
if m:
    body = m.group(1)
    bm = re.search(r'^\\s*base_url:\\s*[\"\\']?([^\"\\'\\s#]+)', body, re.MULTILINE)
    if bm:
        print(bm.group(1))
" 2>/dev/null)
[ -z "$API_PROBE_BASE" ] && API_PROBE_BASE="${VG_BASE_URL:-}"

if [ -z "$API_PROBE_BASE" ]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.api_precheck_blocked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"missing_base_url\"}" >/dev/null 2>&1 || true

  source scripts/lib/blocking-gate-prompt.sh
  EVIDENCE_PATH="${PHASE_DIR}/.vg/api-precheck-evidence.json"
  mkdir -p "$(dirname "$EVIDENCE_PATH")"
  cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "api_precheck",
  "summary": "API contract probe setup error — no base_url found in ENV-CONTRACT.md and VG_BASE_URL is empty",
  "fix_hint": "Set target.base_url in ENV-CONTRACT.md or export VG_BASE_URL"
}
JSON
  blocking_gate_prompt_emit "api_precheck" "$EVIDENCE_PATH" "error"
  # AI controller calls AskUserQuestion → resolve via Leg 2.
  # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.api_precheck_started" \
  --payload "$(printf '{"phase":"%s","base_url":"%s"}' "${PHASE_NUMBER}" "${API_PROBE_BASE}")" >/dev/null 2>&1 || true

PROBE_CMD=("${PYTHON_BIN:-python3}" "$PROBE_SCRIPT"
  --contracts "${PHASE_DIR}/API-CONTRACTS.md"
  --base-url "$API_PROBE_BASE"
  --out "$API_PROBE_OUT")

# Optional auth token from deploy/auth bootstrap. If absent, 401/403 still count
# as route-exists evidence for auth-protected endpoints.
if [ -n "${AUTH_TOKEN:-}" ]; then
  PROBE_CMD+=(--header "Authorization: Bearer ${AUTH_TOKEN}")
fi

"${PROBE_CMD[@]}"
API_PROBE_RC=$?
cat "$API_PROBE_OUT"

if [ "$API_PROBE_RC" -ne 0 ]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.api_precheck_blocked" \
    --payload "$(printf '{"phase":"%s","base_url":"%s","rc":%s}' "${PHASE_NUMBER}" "${API_PROBE_BASE}" "${API_PROBE_RC}")" >/dev/null 2>&1 || true

  source scripts/lib/blocking-gate-prompt.sh
  EVIDENCE_PATH="${PHASE_DIR}/.vg/api-precheck-evidence.json"
  mkdir -p "$(dirname "$EVIDENCE_PATH")"
  cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "api_precheck",
  "summary": "API contract probe failed — browser discovery is not allowed to start on stale/broken API surface",
  "fix_hint": "Fix the API surface issues found in api-contract-precheck.txt before continuing review"
}
JSON
  blocking_gate_prompt_emit "api_precheck" "$EVIDENCE_PATH" "error"
  # AI controller calls AskUserQuestion → resolve via Leg 2.
  # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
fi

"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/emit-evidence-manifest.py" \
  --path "${PHASE_DIR}/api-contract-precheck.txt" \
  --source-inputs "${PHASE_DIR}/API-CONTRACTS.md,.claude/vg.config.md" \
  --producer "vg:review/phase2a_api_contract_probe"
MANIFEST_RC=$?
if [ "$MANIFEST_RC" -ne 0 ]; then
  echo "⛔ API contract probe wrote report but failed to bind evidence to current run." >&2
  exit 1
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.api_precheck_completed" \
  --payload "$(printf '{"phase":"%s","base_url":"%s","artifact":"%s"}' "${PHASE_NUMBER}" "${API_PROBE_BASE}" "api-contract-precheck.txt")" >/dev/null 2>&1 || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2a_api_contract_probe" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2a_api_contract_probe.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2a_api_contract_probe 2>/dev/null || true
```
</step>
