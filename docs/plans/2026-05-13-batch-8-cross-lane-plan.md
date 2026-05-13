# Batch 8 — Cross-lane integration (H7 + H12) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close 2 cross-lane integration gaps. C11 was absorbed in Batch 2.

- **H7** (MEDIUM): HARD-GATE skip directives in test lane (`runtime.md`, `regression-security.md`) skip steps by profile without `/vg:accept` audit that a substitute step ran. 8+ skip directives, no central skip-manifest.
- **H12** (LOW): CrossAI runs/ output stranded — `review/preflight.md:646` describes drop scan results into `runs/{tool}/`. Test-spec lane never reads.

**Tech Stack:** Bash + Python.

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/`
- Regression sweep: `python -m pytest tests/ -q --tb=no -k "h7 or h12 or skip_substitute or crossai_runs"`
- Single `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` per commit

---

## Task 1: H7 — HARD-GATE skip emit + accept audit

**Files:**
- Modify: `commands/vg/_shared/test/runtime.md` (skip directives emit event)
- Modify: `commands/vg/_shared/test/regression-security.md` (same)
- Modify: `commands/vg/_shared/accept/audit.md` (consume skip events, verify substitute)
- Mirrors
- Test: `tests/test_h7_skip_substitute_audit.py`

**Step 1: Failing test**

```python
"""tests/test_h7_skip_substitute_audit.py — H7 HARD-GATE skip audit."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
RUNTIME = REPO / "commands" / "vg" / "_shared" / "test" / "runtime.md"
REGSEC = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"
ACCEPT = REPO / "commands" / "vg" / "_shared" / "accept" / "audit.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_test_runtime_emits_skip_event():
    body = _read(RUNTIME)
    # When step is skipped by HARD-GATE, must emit test.step_skipped_by_profile event
    assert "test.step_skipped_by_profile" in body, (
        "H7: runtime.md HARD-GATE skip directives must emit "
        "test.step_skipped_by_profile event with step + profile + substitute"
    )


def test_regression_security_emits_skip_event():
    body = _read(REGSEC)
    assert "test.step_skipped_by_profile" in body, (
        "H7: regression-security.md HARD-GATE skip directives must emit "
        "test.step_skipped_by_profile event"
    )


def test_accept_audit_reads_skip_events():
    body = _read(ACCEPT)
    # accept/audit.md must reference skip events or skip-manifest verification
    assert ("test.step_skipped_by_profile" in body or
            "skip_substitute" in body or
            "skip-manifest" in body), (
        "H7: accept/audit.md must verify each test step skipped by profile "
        "has the substitute step's event present"
    )
```

**Step 2: Run** → 3 fail.

**Step 3: Implement**

Add skip-event emit helper at top of `commands/vg/_shared/test/runtime.md` (after preflight section). New helper function:

```bash
# H7 Batch 8: HARD-GATE skip emit helper
emit_step_skipped_by_profile() {
  local step="$1"
  local profile="${2:-${PHASE_PROFILE:-${PROFILE:-unknown}}}"
  local substitute="${3:-}"
  "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event \
    "test.step_skipped_by_profile" \
    --payload "{\"phase\":\"${PHASE_NUMBER:-unknown}\",\"step\":\"${step}\",\"profile\":\"${profile}\",\"substitute\":\"${substitute}\"}" \
    >/dev/null 2>&1 || true
}
```

For each HARD-GATE skip directive in runtime.md (lines 24, 128, 164, 264) and regression-security.md (lines 69, 233, 380, 555), add immediately after the skip prose:

```bash
# H7 Batch 8: emit skip event for accept-time audit
case "${PHASE_PROFILE:-${PROFILE:-}}" in
  ${SKIP_PATTERN})
    emit_step_skipped_by_profile "${STEP_NAME}" "${PHASE_PROFILE}" "${SUBSTITUTE_STEP:-}"
    ;;
esac
```

Pragmatic minimal approach: at top of each step body wrap the skip prose with shell logic that emits when skip condition matches. Example for runtime.md line 24 (`5b_runtime_contract_verify` — skipped on web-frontend-only + mobile-*):

```bash
case "${PHASE_PROFILE:-${PROFILE:-}}" in
  web-frontend-only|mobile-*)
    emit_step_skipped_by_profile "5b_runtime_contract_verify" "${PHASE_PROFILE}" ""
    # downstream skip handled by HARD-GATE prose
    ;;
esac
```

Do this for each HARD-GATE skip. Substitutes (when known):
- `5b_runtime_contract_verify` skipped on mobile/web-frontend → no substitute (truly N/A)
- `5c_smoke` skipped on web-backend-only/mobile → substitute = `5b_runtime_contract_verify`
- `5c_flow` skipped on web-backend-only/mobile → substitute = `5b_runtime_contract_verify`
- `5f_security_audit` skipped on mobile-* → substitute = `5f_mobile_security_audit`
- `5f_mobile_security_audit` skipped on web-* → substitute = `5f_security_audit`

In `commands/vg/_shared/accept/audit.md`, append a section that consumes `test.step_skipped_by_profile` events from `.vg/events.jsonl` (or equivalent event store) and verifies substitutes:

```bash
# H7 Batch 8: verify each test step skipped by profile has its substitute event
EVENTS_FILE="${PHASE_DIR}/.vg/events.jsonl"
[ -f "$EVENTS_FILE" ] || EVENTS_FILE=".vg/events.jsonl"
if [ -f "$EVENTS_FILE" ]; then
  ${PYTHON_BIN:-python3} - <<PYEOF
import json
from pathlib import Path
events_path = Path("${EVENTS_FILE}")
skip_events = []
all_events = []
for line in events_path.read_text(encoding="utf-8").splitlines():
    try:
        e = json.loads(line)
    except Exception:
        continue
    all_events.append(e)
    if e.get("event") == "test.step_skipped_by_profile":
        skip_events.append(e)

missing_substitutes = []
for skip in skip_events:
    substitute = (skip.get("payload") or {}).get("substitute") or ""
    if not substitute:
        continue  # truly N/A
    # Verify substitute step has a mark-step event in this phase
    sub_present = any(
        e.get("payload", {}).get("step") == substitute or
        e.get("event") == f"test.{substitute}"
        for e in all_events
    )
    if not sub_present:
        missing_substitutes.append({"skipped": (skip.get("payload") or {}).get("step"), "expected_substitute": substitute})

if missing_substitutes:
    print("⛔ H7 audit: skipped steps missing substitute evidence:")
    for m in missing_substitutes:
        print(f"  - {m['skipped']} skipped but {m['expected_substitute']} not present")
    import sys; sys.exit(1)
print(f"✓ H7 audit: {len(skip_events)} skips, all substitutes accounted for")
PYEOF
fi
```

**Step 4-6:** pass + mirror + commit.

```bash
git add commands/vg/_shared/test/{runtime,regression-security}.md \
        commands/vg/_shared/accept/audit.md \
        .claude/commands/vg/_shared/test/{runtime,regression-security}.md \
        .claude/commands/vg/_shared/accept/audit.md \
        tests/test_h7_skip_substitute_audit.py
git commit -m "feat(test+accept): H7 — HARD-GATE skip events + accept audit (Batch 8)

Audit Gap H7 (MEDIUM): 8+ HARD-GATE skip directives (e.g. 'mobile-* MUST
skip 5f_security_audit, use 5f_mobile_security_audit instead') existed
in test/runtime.md + test/regression-security.md. No central skip
manifest. /vg:accept never verified the substitute step actually ran.

Fix:
- emit_step_skipped_by_profile() helper at top of runtime.md emits
  test.step_skipped_by_profile event with {phase, step, profile,
  substitute} payload when HARD-GATE skip condition matches.
- Each HARD-GATE skip directive now emits the event before falling
  through to skip prose.
- accept/audit.md consumes events.jsonl, finds skip events with non-
  empty substitute, verifies substitute event present in same phase.
  Missing substitute → BLOCK.

Tests: tests/test_h7_skip_substitute_audit.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: H12 — CrossAI runs/{tool}/ consumed by test-spec

**Files:**
- Modify: `commands/vg/_shared/test/preflight.md` (read crossai runs)
- Modify: `commands/vg/_shared/test/codegen/overview.md` (include in prompt context if any)
- Mirrors
- Test: `tests/test_h12_crossai_runs_consumed.py`

**Step 1: Failing test**

```python
"""tests/test_h12_crossai_runs_consumed.py — H12 stranded CrossAI output."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
PREFLIGHT = REPO / "commands" / "vg" / "_shared" / "test" / "preflight.md"


def test_test_preflight_scans_crossai_runs():
    body = PREFLIGHT.read_text(encoding="utf-8")
    # Test preflight must reference review/runs/ scanning
    assert "review/runs" in body or "crossai/runs" in body or "review-runs" in body, (
        "H12: test/preflight.md must scan .vg/phases/{phase}/review/runs/{tool}/ "
        "(or equivalent path) and surface CrossAI findings to downstream codegen"
    )


def test_codegen_overview_includes_crossai_context():
    overview = REPO / "commands" / "vg" / "_shared" / "test" / "codegen" / "overview.md"
    body = overview.read_text(encoding="utf-8")
    # Codegen prompt context must include CrossAI findings when present
    assert ("CROSSAI_FINDINGS" in body or
            "crossai" in body.lower() or
            "review/runs" in body), (
        "H12: codegen/overview.md must include CrossAI runs findings in "
        "subagent prompt context when present (env var or context file)"
    )
```

**Step 2: Run** → 2 fail.

**Step 3: Implement**

In `commands/vg/_shared/test/preflight.md`, append a section after existing preflight checks:

```bash
# H12 Batch 8: surface CrossAI runs/ findings to downstream test-spec/test
CROSSAI_RUNS_DIR="${PHASE_DIR}/review/runs"
[ -d "$CROSSAI_RUNS_DIR" ] || CROSSAI_RUNS_DIR="${PHASE_DIR}/crossai/runs"
if [ -d "$CROSSAI_RUNS_DIR" ]; then
  # Find any CrossAI tool runs (codex, gemini, claude subdirs)
  CROSSAI_FINDINGS_OUT="${PHASE_DIR}/.tmp/crossai-findings.md"
  mkdir -p "$(dirname "$CROSSAI_FINDINGS_OUT")"
  {
    echo "# CrossAI findings — collected from review/runs/"
    echo ""
    for tool_dir in "$CROSSAI_RUNS_DIR"/*/; do
      [ -d "$tool_dir" ] || continue
      tool="$(basename "$tool_dir")"
      echo "## Tool: ${tool}"
      for result in "$tool_dir"*.{md,json,xml}; do
        [ -f "$result" ] || continue
        echo "### $(basename "$result")"
        head -50 "$result" 2>/dev/null
        echo ""
      done
    done
  } > "$CROSSAI_FINDINGS_OUT"
  export VG_CROSSAI_FINDINGS_PATH="$CROSSAI_FINDINGS_OUT"
  echo "✓ CrossAI findings collected: ${CROSSAI_FINDINGS_OUT}"
else
  echo "ℹ no review/runs/ dir — skipping CrossAI findings collection"
fi
```

In `commands/vg/_shared/test/codegen/overview.md`, add a note in the prompt-rendering section about including CrossAI findings:

Append after the existing prompt context description:

```markdown
## CrossAI context (H12 Batch 8)

When `$VG_CROSSAI_FINDINGS_PATH` is set (populated by test/preflight.md
from `.vg/phases/{phase}/review/runs/{tool}/`), the codegen subagent
prompt template MUST include:

```
crossai_findings_path: ${VG_CROSSAI_FINDINGS_PATH}
crossai_findings_note: |
  Review-time CrossAI scans (codex/gemini/claude) produced findings at the
  path above. Inspect for FE-BE drift, missing endpoints, security concerns
  that may affect generated test specs. Reference findings by tool name in
  generated spec headers when relevant.
```

This wires up the stranded review/runs/ output as test-spec/codegen context.
```

**Step 4-6:** pass + mirror + commit.

```bash
git add commands/vg/_shared/test/preflight.md \
        commands/vg/_shared/test/codegen/overview.md \
        .claude/commands/vg/_shared/test/preflight.md \
        .claude/commands/vg/_shared/test/codegen/overview.md \
        tests/test_h12_crossai_runs_consumed.py
git commit -m "feat(test): H12 — CrossAI runs/ findings flow into codegen context (Batch 8)

Audit Gap H12 (LOW): review/preflight.md drops CrossAI tool scan results
into .vg/phases/{phase}/review/runs/{tool}/ (codex, gemini, claude). No
consumer in test/test-spec lanes. Findings stranded.

Fix:
- test/preflight.md scans review/runs/ subdirs, collects findings into
  .tmp/crossai-findings.md, exports \$VG_CROSSAI_FINDINGS_PATH for
  downstream consumers.
- codegen/overview.md documents how codegen subagent prompt includes
  the findings path so test specs can reference CrossAI signals.

Tests: tests/test_h12_crossai_runs_consumed.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Regression sweep + release v4.8.0

Bump VERSION 4.7.0 → 4.8.0. CHANGELOG entry per gaps. Tag v4.8.0. Push. Re-sync ~/.vgflow for modified files (runtime.md, regression-security.md, accept/audit.md, test/preflight.md, codegen/overview.md).

End of Batch 8 plan. Estimated 2-3 hours.
