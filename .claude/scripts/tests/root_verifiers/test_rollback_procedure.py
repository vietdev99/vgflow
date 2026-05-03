"""
Tests for verify-rollback-procedure.py — UNQUARANTINABLE.

Closes ORG 6-Dimension Gate dimension 6 (rollback). Per orchestrator
allowlist: destructive PLAN tasks need rollback path. AI tends to ship
DROP TABLE / DELETE / TRUNCATE without recovery plan.

Covers:
  - Missing phase-dir → PASS (graceful)
  - Feature phase, no destructive tasks, no ROLLBACK.md → PASS or WARN
  - Migration phase WITH ROLLBACK.md (substantive) → PASS
  - Migration phase WITHOUT ROLLBACK.md → BLOCK
  - PLAN task with `DROP TABLE` and inline **Rollback:** → PASS
  - PLAN task with `DROP TABLE` and no rollback declaration → BLOCK
  - PLAN with destructive task but phase-level ROLLBACK.md covers it → PASS
  - --strict flag recognized
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-rollback-procedure.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=15, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _setup(tmp_path: Path, slug: str = "99.0-rollback") -> Path:
    pdir = tmp_path / ".vg" / "phases" / slug
    pdir.mkdir(parents=True)
    return pdir


def _verdict(stdout: str) -> str | None:
    try:
        return json.loads(stdout).get("verdict")
    except (json.JSONDecodeError, AttributeError):
        return None


class TestRollbackProcedure:
    def test_missing_phase_graceful(self, tmp_path):
        r = _run(["--phase", "99.99"], tmp_path)
        # find_phase_dir returns None → emit_and_exit with PASS verdict
        assert r.returncode == 0
        assert "Traceback" not in r.stderr

    def test_feature_phase_no_destructive_passes(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text("# Specs\nprofile: feature\n", encoding="utf-8")
        (pdir / "PLAN.md").write_text(
            "# Plan\n## Task 1: Add component\nWrite a new file.\n",
            encoding="utf-8",
        )
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 0, f"benign feature phase should PASS, stdout={r.stdout}"

    def test_migration_with_rollback_passes(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text(
            "# Specs\nprofile: migration\nMigrate users table up/down.\n",
            encoding="utf-8",
        )
        rollback_text = (
            "# Rollback procedure\n\n"
            "If the migration fails:\n\n"
            "1. Run `pnpm db:migrate:down 20260426_add_users`.\n"
            "2. Verify schema reverted via `\\d users`.\n"
            "3. pm2 restart api && curl /health.\n"
            + "Additional context line.\n" * 5
        )
        (pdir / "ROLLBACK.md").write_text(rollback_text, encoding="utf-8")
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 0, f"migration with rollback should PASS, stdout={r.stdout}"

    def test_migration_without_rollback_blocks(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text(
            "# Specs\nprofile: migration\nMigrate down up revert.\n",
            encoding="utf-8",
        )
        (pdir / "PLAN.md").write_text("# Plan\n## Task 1: Migrate\n", encoding="utf-8")
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 1, \
            f"migration without ROLLBACK.md should BLOCK, rc={r.returncode}, stdout={r.stdout}"
        assert _verdict(r.stdout) == "BLOCK"

    def test_destructive_task_with_inline_rollback_passes(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text("# Specs\nprofile: feature\n", encoding="utf-8")
        (pdir / "PLAN.md").write_text(
            "# Plan\n\n## Task 1: Drop legacy table\n"
            "Run: `DROP TABLE legacy_users;`.\n\n"
            "**Rollback:** Restore from snapshot S3 path; replay journal "
            "since 2026-04-25.\n",
            encoding="utf-8",
        )
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 0, f"inline rollback should PASS, stdout={r.stdout}"

    def test_destructive_task_no_rollback_blocks(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text("# Specs\nprofile: feature\n", encoding="utf-8")
        (pdir / "PLAN.md").write_text(
            "# Plan\n\n## Task 1: Drop legacy table\n"
            "Run: `DROP TABLE legacy_users;`. No rollback.\n",
            encoding="utf-8",
        )
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 1, \
            f"destructive task without rollback should BLOCK, rc={r.returncode}, stdout={r.stdout}"

    def test_phase_level_rollback_covers_destructive(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text("# Specs\nprofile: feature\n", encoding="utf-8")
        (pdir / "PLAN.md").write_text(
            "# Plan\n\n## Task 1: Drop unused index\n"
            "Run: `DROP INDEX old_idx;`.\n",
            encoding="utf-8",
        )
        rollback_text = (
            "# Rollback procedure\n\n"
            "If the index drop causes regressions, recreate it via:\n\n"
            "  CREATE INDEX old_idx ON users(email);\n\n"
            "Test query plan with EXPLAIN ANALYZE before re-deploying.\n"
            + "Filler context.\n" * 6
        )
        (pdir / "ROLLBACK.md").write_text(rollback_text, encoding="utf-8")
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 0, f"phase-level rollback should cover, stdout={r.stdout}"

    def test_strict_flag_recognized(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text("# Specs\nprofile: feature\n", encoding="utf-8")
        r = _run(["--phase", "99.0", "--strict"], tmp_path)
        assert r.returncode in (0, 1)
        assert "unrecognized arguments" not in r.stderr.lower()
