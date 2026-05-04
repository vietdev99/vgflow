"""Tests for verify-codegen-rcrurd-helper.py — AST gate against generated specs."""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "validators" / "verify-codegen-rcrurd-helper.py"


def test_spec_with_helper_call_passes(tmp_path: Path) -> None:
    """Generated spec calls expectReadAfterWrite — must PASS."""
    spec = tmp_path / "G-04.spec.ts"
    spec.write_text(textwrap.dedent("""
        import { test } from '@playwright/test';
        import { expectReadAfterWrite } from '@/test-helpers/expectReadAfterWrite';
        import { invariantG04 } from './fixtures/invariants/G-04';

        test('G-04: admin grants role', async ({ page, request }) => {
          // ... action code ...
          await expectReadAfterWrite(request, invariantG04, { new_role: 'admin', roles: ['admin'] });
        });
    """).strip(), encoding="utf-8")

    goals = tmp_path / "TEST-GOALS"
    goals.mkdir()
    (goals / "G-04.md").write_text(textwrap.dedent("""
        # G-04
        **goal_type:** mutation
        ## Read-after-write invariant
        ```yaml-rcrurd
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/users/U}
          read:
            method: GET
            endpoint: /api/users/U
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - path: $.roles
              op: contains
              value_from: action.new_role
        ```
    """).strip(), encoding="utf-8")

    result = subprocess.run([
        "python3", str(GATE),
        "--specs-dir", str(tmp_path),
        "--goals-dir", str(goals),
        "--phase", "test",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_spec_without_helper_call_blocks(tmp_path: Path) -> None:
    """Mutation goal but spec doesn't call expectReadAfterWrite — must BLOCK."""
    spec = tmp_path / "G-04.spec.ts"
    spec.write_text(textwrap.dedent("""
        import { test, expect } from '@playwright/test';

        test('G-04: admin grants role', async ({ page }) => {
          await page.click('[data-testid="grant-role"]');
          await expect(page.locator('.toast-success')).toBeVisible();
        });
    """).strip(), encoding="utf-8")

    goals = tmp_path / "TEST-GOALS"
    goals.mkdir()
    (goals / "G-04.md").write_text(textwrap.dedent("""
        # G-04
        **goal_type:** mutation
        ## Read-after-write invariant
        ```yaml-rcrurd
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/users/U}
          read:
            method: GET
            endpoint: /api/users/U
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - path: $.roles
              op: contains
              value_from: action.new_role
        ```
    """).strip(), encoding="utf-8")

    result = subprocess.run([
        "python3", str(GATE),
        "--specs-dir", str(tmp_path),
        "--goals-dir", str(goals),
        "--phase", "test",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "G-04" in result.stderr
    assert "expectReadAfterWrite" in result.stderr or "helper" in result.stderr.lower()


def test_non_mutation_goal_doesnt_require_helper(tmp_path: Path) -> None:
    spec = tmp_path / "G-99.spec.ts"
    spec.write_text(
        "import { test } from '@playwright/test';\ntest('G-99: read-only health', async () => {});\n",
        encoding="utf-8",
    )
    goals = tmp_path / "TEST-GOALS"
    goals.mkdir()
    (goals / "G-99.md").write_text("# G-99\n**goal_type:** read_only\n", encoding="utf-8")

    result = subprocess.run([
        "python3", str(GATE),
        "--specs-dir", str(tmp_path),
        "--goals-dir", str(goals),
        "--phase", "test",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0
