"""R8-A — RCRURDR test-codegen full-lifecycle enforcement.

Codex audit (2026-05-05) found test layer PARTIAL on RCRURDR closed-loop:
codegen required only `expectReadAfterWrite()` (1 step) — full 7-phase
helper `expectLifecycleRoundtrip()` existed but wasn't required.

This test pins the new behavior:
  - `lifecycle: rcrurdr` goal + `expectLifecycleRoundtrip` spec → PASS
  - `lifecycle: rcrurdr` goal + only `expectReadAfterWrite` spec → BLOCK
  - non-rcrurdr (default `rcrurd`) goal + `expectReadAfterWrite` → PASS (back-compat)
  - canonical helper `expectLifecycleRoundtrip` exists in
    `scripts/codegen-helpers/expectReadAfterWrite.ts`
  - Skill + delegation docs document the new rule.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-codegen-rcrurd-helper.py"
HELPER_TS = REPO_ROOT / "scripts" / "codegen-helpers" / "expectReadAfterWrite.ts"
SKILL_MD = REPO_ROOT / "agents" / "vg-test-codegen" / "SKILL.md"
DELEGATION_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Full 7-phase RCRURDR invariant in inline yaml-rcrurd fence.
RCRURDR_GOAL_MD = """\
# Goal G-04 — Full lifecycle site CRUD

**goal_type:** mutation

## Read-after-write invariant

```yaml-rcrurd
goal_type: mutation
lifecycle: rcrurdr
lifecycle_phases:
  - phase: read_empty
    read:
      method: GET
      endpoint: /api/sites
      cache_policy: no_store
      settle:
        mode: immediate
    assert:
      - path: $.items
        op: equals
        value_from: literal:[]
  - phase: create
    write:
      method: POST
      endpoint: /api/sites
    read:
      method: GET
      endpoint: /api/sites
      cache_policy: no_store
      settle:
        mode: immediate
    assert:
      - path: $.items[*].name
        op: contains
        value_from: action.name
  - phase: read_populated
    read:
      method: GET
      endpoint: /api/sites
      cache_policy: no_store
      settle:
        mode: immediate
    assert:
      - path: $.items[*].name
        op: contains
        value_from: action.name
  - phase: update
    write:
      method: PUT
      endpoint: /api/sites/123
    read:
      method: GET
      endpoint: /api/sites/123
      cache_policy: no_store
      settle:
        mode: immediate
    assert:
      - path: $.name
        op: equals
        value_from: action.new_name
  - phase: read_updated
    read:
      method: GET
      endpoint: /api/sites/123
      cache_policy: no_store
      settle:
        mode: immediate
    assert:
      - path: $.name
        op: equals
        value_from: action.new_name
  - phase: delete
    write:
      method: DELETE
      endpoint: /api/sites/123
    read:
      method: GET
      endpoint: /api/sites
      cache_policy: no_store
      settle:
        mode: immediate
    assert:
      - path: $.items[*].id
        op: not_contains
        value_from: literal:123
  - phase: read_after_delete
    read:
      method: GET
      endpoint: /api/sites
      cache_policy: no_store
      settle:
        mode: immediate
    assert:
      - path: $.items[*].id
        op: not_contains
        value_from: literal:123
```
"""

# Legacy single-cycle invariant (lifecycle defaults to 'rcrurd').
SIMPLE_GOAL_MD = """\
# Goal G-05 — Simple write-then-read

**goal_type:** mutation

## Read-after-write invariant

```yaml-rcrurd
goal_type: mutation
read_after_write_invariant:
  write:
    method: POST
    endpoint: /api/sites
  read:
    method: GET
    endpoint: /api/sites/123
    cache_policy: no_store
    settle:
      mode: immediate
  assert:
    - path: $.name
      op: equals
      value_from: action.name
```
"""

SPEC_USING_LIFECYCLE_HELPER = """\
import { test, expect } from '@playwright/test';
import { expectLifecycleRoundtrip } from '../helpers/expectReadAfterWrite';

test('G-04 full lifecycle', async ({ page, request }) => {
  await expectLifecycleRoundtrip(page, request, invariantG04, { name: 'Test' });
});
"""

SPEC_USING_SIMPLE_HELPER = """\
import { test, expect } from '@playwright/test';
import { expectReadAfterWrite } from '../helpers/expectReadAfterWrite';

test('G mutation', async ({ page, request }) => {
  await expectReadAfterWrite(page, request, invariantG, { name: 'Test' });
});
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_phase(tmp_path: Path, *, goal_id: str, goal_md: str, spec_text: str) -> tuple[Path, Path]:
    """Create goals_dir/{goal_id}.md + specs_dir/{goal_id}.spec.ts."""
    goals_dir = tmp_path / "TEST-GOALS"
    goals_dir.mkdir()
    (goals_dir / f"{goal_id}.md").write_text(goal_md, encoding="utf-8")

    specs_dir = tmp_path / "e2e"
    specs_dir.mkdir()
    (specs_dir / f"{goal_id}.spec.ts").write_text(spec_text, encoding="utf-8")
    return goals_dir, specs_dir


def _run_validator(goals_dir: Path, specs_dir: Path, phase: str = "test-phase") -> tuple[int, str, str]:
    proc = subprocess.run(
        [
            sys.executable, str(VALIDATOR),
            "--specs-dir", str(specs_dir),
            "--goals-dir", str(goals_dir),
            "--phase", phase,
        ],
        capture_output=True, text=True, timeout=15,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pass_when_rcrurdr_goal_uses_full_lifecycle(tmp_path):
    """rcrurdr goal + spec imports/calls expectLifecycleRoundtrip → PASS."""
    goals_dir, specs_dir = _setup_phase(
        tmp_path, goal_id="G-04",
        goal_md=RCRURDR_GOAL_MD,
        spec_text=SPEC_USING_LIFECYCLE_HELPER,
    )
    rc, stdout, stderr = _run_validator(goals_dir, specs_dir)
    assert rc == 0, f"Expected PASS (rc=0), got rc={rc}\nstdout={stdout}\nstderr={stderr}"
    assert "rcrurdr_full_lifecycle=1" in stdout, (
        f"Expected rcrurdr_full_lifecycle=1 in stdout, got: {stdout}"
    )


def test_block_when_rcrurdr_goal_uses_only_read_after_write(tmp_path):
    """rcrurdr goal + spec uses only expectReadAfterWrite → BLOCK (R8-A)."""
    goals_dir, specs_dir = _setup_phase(
        tmp_path, goal_id="G-04",
        goal_md=RCRURDR_GOAL_MD,
        spec_text=SPEC_USING_SIMPLE_HELPER,
    )
    rc, stdout, stderr = _run_validator(goals_dir, specs_dir)
    assert rc == 1, f"Expected BLOCK (rc=1), got rc={rc}\nstdout={stdout}\nstderr={stderr}"
    assert "lifecycle: rcrurdr" in stderr, (
        f"Expected explanation mentioning 'lifecycle: rcrurdr' in stderr, got: {stderr}"
    )
    assert "expectLifecycleRoundtrip" in stderr, (
        f"Expected R8-A failure to mention expectLifecycleRoundtrip, got: {stderr}"
    )


def test_pass_when_non_rcrurdr_goal_uses_simple_helper(tmp_path):
    """Default (rcrurd) goal + spec uses expectReadAfterWrite → PASS (back-compat)."""
    goals_dir, specs_dir = _setup_phase(
        tmp_path, goal_id="G-05",
        goal_md=SIMPLE_GOAL_MD,
        spec_text=SPEC_USING_SIMPLE_HELPER,
    )
    rc, stdout, stderr = _run_validator(goals_dir, specs_dir)
    assert rc == 0, f"Expected PASS (rc=0), got rc={rc}\nstdout={stdout}\nstderr={stderr}"
    assert "rcrurdr_full_lifecycle=0" in stdout, (
        f"Expected rcrurdr_full_lifecycle=0 in stdout, got: {stdout}"
    )


def test_helper_exists_in_codegen_helpers():
    """expectLifecycleRoundtrip MUST be defined in canonical helper file."""
    assert HELPER_TS.exists(), f"Canonical helper missing: {HELPER_TS}"
    text = HELPER_TS.read_text(encoding="utf-8")
    assert "export async function expectLifecycleRoundtrip" in text, (
        f"expectLifecycleRoundtrip not exported from {HELPER_TS.name}"
    )
    # Must accept lifecycle_phases iteration (R8-A capability).
    assert "lifecycle_phases" in text, (
        "expectLifecycleRoundtrip must reference lifecycle_phases iteration"
    )


def test_skill_md_documents_full_lifecycle_rule():
    """agents/vg-test-codegen/SKILL.md MUST document R8-A rule."""
    assert SKILL_MD.exists(), f"Skill MD missing: {SKILL_MD}"
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "expectLifecycleRoundtrip" in text, (
        "SKILL.md must mention expectLifecycleRoundtrip helper"
    )
    assert "lifecycle: rcrurdr" in text, (
        "SKILL.md must reference the lifecycle: rcrurdr flag"
    )
    assert "R8-A" in text, "SKILL.md must label the rule R8-A"


def test_delegation_md_documents_full_lifecycle_rule():
    """commands/vg/_shared/test/codegen/delegation.md MUST document R8-A."""
    assert DELEGATION_MD.exists(), f"Delegation MD missing: {DELEGATION_MD}"
    text = DELEGATION_MD.read_text(encoding="utf-8")
    assert "expectLifecycleRoundtrip" in text, (
        "delegation.md must mention expectLifecycleRoundtrip helper"
    )
    assert "lifecycle: rcrurdr" in text, (
        "delegation.md must reference the lifecycle: rcrurdr flag"
    )
    assert "R8-A" in text, "delegation.md must label the rule R8-A"
