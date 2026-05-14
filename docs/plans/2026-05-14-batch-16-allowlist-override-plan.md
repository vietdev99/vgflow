# Batch 16 — Flag allowlist + override CLI fixes (F1+F2+F9) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close 3 HIGH audit findings — documented skip flags are silently rejected by preflight or fail to emit override evidence.

- **F1**: `--skip-pre-test` + `--skip-contract-runtime` documented in `build.md:4` but missing from `preflight.md:151` `VALID_FLAGS_PATTERN` → preflight rejects as unknown.
- **F2**: `pre-test-gate.md:50` calls `vg-orchestrator override-use` (does not exist) instead of `override`. `${OVERRIDE_REASON}` env var unset (must parse from `--override-reason=<text>` arg).
- **F9**: `blueprint.md` declares `required_unless_flag: --skip-form-api-map / --skip-ui-spec` but blueprint sub-step shell never emits `override` event → `forbidden_without_override` contract validator cannot detect skips.

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/`
- Sweep: `python -m pytest tests/ -q --tb=no -k "allowlist or override or skip_pre_test or skip_contract_runtime or f1 or f2 or f9 or preflight"`
- Single Co-Authored-By trailer per commit

---

## Task 1: F1 — Add 2 flags to preflight allowlist

**Files:**
- Modify: `commands/vg/_shared/build/preflight.md` (line 151 VALID_FLAGS_PATTERN + help text 167-173)
- Mirror
- Test: `tests/test_f1_build_allowlist.py`

**Step 1: Failing test**

```python
"""tests/test_f1_build_allowlist.py — F1 build preflight allowlist."""
from __future__ import annotations
import re
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
PRE = REPO / "commands" / "vg" / "_shared" / "build" / "preflight.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_allowlist_includes_skip_pre_test():
    body = _read(PRE)
    # Find VALID_FLAGS_PATTERN line
    m = re.search(r"VALID_FLAGS_PATTERN='[^']+'", body)
    assert m, "F1: VALID_FLAGS_PATTERN line missing"
    pattern = m.group(0)
    assert "skip-pre-test" in pattern, (
        "F1: --skip-pre-test documented in build.md:4 but missing from "
        "preflight VALID_FLAGS_PATTERN → preflight rejects as unknown flag"
    )


def test_allowlist_includes_skip_contract_runtime():
    body = _read(PRE)
    m = re.search(r"VALID_FLAGS_PATTERN='[^']+'", body)
    pattern = m.group(0)
    assert "skip-contract-runtime" in pattern, (
        "F1: --skip-contract-runtime documented in build.md:4 but missing from "
        "preflight VALID_FLAGS_PATTERN"
    )


def test_help_text_mentions_new_flags():
    body = _read(PRE)
    # Help block must mention new flags so user sees them when typo error fires
    assert "--skip-pre-test" in body and "--skip-contract-runtime" in body, (
        "F1: help text must list --skip-pre-test + --skip-contract-runtime"
    )
```

**Step 2-6:** RED → add `skip-pre-test|skip-contract-runtime` to VALID_FLAGS_PATTERN alternation + append to help text → GREEN → mirror → commit.

```bash
git commit -m "fix(build): F1 — allowlist --skip-pre-test + --skip-contract-runtime (Batch 16)

Codex audit Finding F1 (HIGH): build.md:4 documented both flags, build.md
runtime_contract declared them under forbidden_without_override, but
preflight.md VALID_FLAGS_PATTERN (line 151) omitted both → preflight
rejected them as 'unknown flag' before the override logic could engage.

Fix: add 'skip-pre-test|skip-contract-runtime' to alternation. Append to
help text (line 167-173) so typo-error message lists them.

Tests: tests/test_f1_build_allowlist.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: F2 — Fix override CLI invocation + parse --override-reason

**Files:**
- Modify: `commands/vg/_shared/build/pre-test-gate.md` (lines 42-58 override block)
- Audit other `override-use` callers via grep
- Mirror
- Test: `tests/test_f2_override_cli_fix.py`

**Step 1: Failing test**

```python
"""tests/test_f2_override_cli_fix.py — F2 override CLI fix."""
from __future__ import annotations
import re
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]


def test_no_override_use_callers_remain():
    """vg-orchestrator CLI registers 'override' subcommand. 'override-use' is
    not registered — any caller silently fails."""
    matches = []
    for p in REPO.rglob("*.md"):
        if "node_modules" in str(p) or ".git" in str(p):
            continue
        try:
            body = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in body.splitlines():
            if "override-use" in line and "vg-orchestrator" in line:
                # Skip historical changelog / audit references
                if "CHANGELOG" in str(p) or "audit" in str(p).lower() or "/plans/" in str(p):
                    continue
                matches.append(f"{p.relative_to(REPO)}: {line.strip()[:120]}")
    assert not matches, (
        "F2: vg-orchestrator subcommand is 'override' not 'override-use'. "
        "Callers still using override-use will silently fail:\n  " + "\n  ".join(matches)
    )


def test_pre_test_gate_parses_override_reason_from_arg():
    body = (REPO / "commands/vg/_shared/build/pre-test-gate.md").read_text(encoding="utf-8")
    # Find the --skip-pre-test branch
    idx = body.find("--skip-pre-test")
    assert idx > 0
    block = body[idx:idx + 1500]
    # Must extract --override-reason=<text> from $ARGUMENTS, not rely on
    # undefined $OVERRIDE_REASON env var
    assert ("OVERRIDE_REASON=" in block and ("sed" in block or "grep" in block or "awk" in block or "${ARGUMENTS" in block)), (
        "F2: pre-test-gate.md --skip-pre-test branch must parse --override-reason=<text> "
        "from ARGUMENTS before calling vg-orchestrator override"
    )
```

**Step 2-6:** RED → replace `override-use` call + add reason parser → GREEN → mirror → commit.

In `commands/vg/_shared/build/pre-test-gate.md` replace:
```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override-use \
  --flag "--skip-pre-test" \
  --reason "${OVERRIDE_REASON}" 2>/dev/null || true
```

With:
```bash
# F2 Batch 16: parse --override-reason=<text> from ARGUMENTS + use real 'override' subcommand
OVERRIDE_REASON=$(echo "${ARGUMENTS}" | sed -nE 's/.*--override-reason=([^ ]+).*/\1/p' | head -1)
if [ -z "$OVERRIDE_REASON" ]; then
  echo "⛔ F2: --skip-pre-test requires --override-reason=<text> on the command line" >&2
  exit 1
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
  --flag "--skip-pre-test" \
  --reason "${OVERRIDE_REASON}" || true
```

Audit other files with `grep -rn "override-use" commands/ scripts/` and apply the same fix everywhere. CHANGELOG/audit/plans are documentation, leave them.

```bash
git commit -m "fix(build): F2 — pre-test-gate override CLI + reason parser (Batch 16)

Codex audit Finding F2 (HIGH): pre-test-gate.md:50 called
'vg-orchestrator override-use' but CLI registers 'override' subcommand
only (scripts/vg-orchestrator/__main__.py:5106). Override event never
fired. \${OVERRIDE_REASON} env var was undefined — no reason captured
even if the call had worked.

Fix:
- Parse --override-reason=<text> from \$ARGUMENTS via sed.
- BLOCK if reason empty (require operator to declare why).
- Call 'override' (canonical subcommand), not 'override-use'.
- Drop '2>/dev/null' on the override call so failures surface.

Tests: tests/test_f2_override_cli_fix.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: F9 — Blueprint escape flags emit override event

**Files:**
- Modify: `commands/vg/_shared/blueprint/plan-overview.md` (the `--skip-form-api-map` / `--skip-ui-spec` branches)
- Possibly `commands/vg/_shared/blueprint/design.md` if it has the same branches
- Mirror
- Test: `tests/test_f9_blueprint_override_emit.py`

**Step 1: Failing test**

```python
"""tests/test_f9_blueprint_override_emit.py — F9 blueprint override emit."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]


def test_blueprint_skip_flags_emit_override():
    """When --skip-form-api-map or --skip-ui-spec branches are taken,
    blueprint shell must emit 'vg-orchestrator override --flag=... --reason=...'
    so forbidden_without_override contract validator sees the override.used event.
    """
    candidates = [
        REPO / "commands/vg/_shared/blueprint/plan-overview.md",
        REPO / "commands/vg/_shared/blueprint/design.md",
    ]
    found_emit = False
    for p in candidates:
        if not p.is_file():
            continue
        body = p.read_text(encoding="utf-8")
        # Look for a branch that handles a --skip-* flag AND calls vg-orchestrator override
        if "--skip-form-api-map" in body or "--skip-ui-spec" in body:
            # In the SAME file, must invoke 'vg-orchestrator override'
            if "vg-orchestrator override" in body and "--reason" in body:
                found_emit = True
                break
    assert found_emit, (
        "F9: blueprint --skip-form-api-map / --skip-ui-spec branches must "
        "call 'vg-orchestrator override --flag=... --reason=...' so the "
        "forbidden_without_override contract validator can enforce reasoned skips."
    )
```

**Step 2-6:** RED → locate skip branches in blueprint sub-steps → add `vg-orchestrator override` emit alongside existing debt-log → GREEN → mirror → commit.

Pattern to apply in EACH skip branch:
```bash
OVERRIDE_REASON=$(echo "${ARGUMENTS}" | sed -nE 's/.*--override-reason=([^ ]+).*/\1/p' | head -1)
if [ -z "$OVERRIDE_REASON" ]; then
  echo "⛔ --skip-form-api-map requires --override-reason=<text>" >&2
  exit 1
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
  --flag "--skip-form-api-map" --reason "${OVERRIDE_REASON}" || true
```

```bash
git commit -m "fix(blueprint): F9 — emit vg-orchestrator override on skip flags (Batch 16)

Codex audit Finding F9 (HIGH): blueprint.md frontmatter declared
required_unless_flag: '--skip-form-api-map' and '--skip-ui-spec' but
blueprint sub-steps that took those branches only logged override-debt,
never invoked 'vg-orchestrator override --flag=... --reason=...'.
forbidden_without_override contract validator could not detect the
intentional skip → false negatives on run-complete.

Fix: each --skip-* branch now requires --override-reason=<text> (parsed
from ARGUMENTS via sed) and emits canonical vg-orchestrator override
event before short-circuiting.

Tests: tests/test_f9_blueprint_override_emit.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Release v4.19.0

Bump VERSION 4.18.0 → 4.19.0. CHANGELOG entry per F1+F2+F9. Tag v4.19.0. Push. Re-sync ~/.vgflow.

End of Batch 16 plan. Estimated 2-3 hours.
