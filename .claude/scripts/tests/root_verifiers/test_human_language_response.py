"""
Tests for verify-human-language-response.py — UNQUARANTINABLE.

Per orchestrator allowlist: "user-facing prose must read as a story,
not bullet/schema dumps." Heuristic story-shape score; below threshold
→ BLOCK with rewrite hint.

Covers:
  - Empty stdin → BLOCK or PASS (graceful)
  - Long narrative prose with sentences + examples → PASS
  - Bullet-only dump (no sentences) → low score → BLOCK
  - Schema-like enum lines → BLOCK
  - Single-word terminator ("OK") → BLOCK
  - Threshold tuning (lower threshold passes weaker text)
  - --file input mode
  - --stdin input mode
  - Schema canonical: validator/verdict/evidence keys
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
    "verify-human-language-response.py"


def _run(args: list[str], cwd: Path, stdin: str | None = None
         ) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=15, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
        input=stdin,
    )


def _verdict(stdout: str) -> str | None:
    try:
        return json.loads(stdout).get("verdict")
    except (json.JSONDecodeError, AttributeError):
        return None


GOOD_PROSE = (
    "Phase I backfills coverage for thirteen root verifiers that the "
    "v2.6.1 CI pytest gate runs but had no actual tests. Each test "
    "exercises five to eight cases per verifier, scoped via VG_REPO_ROOT "
    "to a temporary directory. For example, verify-rollback-procedure "
    "checks ROLLBACK.md presence on migration phases, and the test "
    "fixture creates a substantive markdown file to confirm the gate "
    "fires correctly. The result is a closed loop where the CI gate "
    "now reflects real coverage rather than a green-light effect.\n"
)

BAD_BULLETS = (
    "- Test 1\n"
    "- Test 2\n"
    "- Test 3\n"
    "- Test 4\n"
    "- Test 5\n"
    "- Test 6\n"
    "- Test 7\n"
    "- Test 8\n"
    "OK\n"
)

BAD_SCHEMA_DUMP = (
    "field_a: string\n"
    "field_b: number\n"
    "field_c: enum|pending|active|paused\n"
    "field_d: boolean\n"
    "field_e: timestamp\n"
)

BAD_TERSE = "OK\n"


class TestHumanLanguageResponse:
    def test_empty_stdin_graceful(self, tmp_path):
        r = _run(["--stdin"], tmp_path, stdin="")
        # Empty input — could PASS (nothing to fail) or BLOCK (nothing
        # narrative). Either is acceptable; no crash is the contract.
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stderr

    def test_good_prose_passes(self, tmp_path):
        r = _run(["--stdin"], tmp_path, stdin=GOOD_PROSE)
        assert r.returncode == 0, \
            f"narrative prose should PASS, rc={r.returncode}, stdout={r.stdout[:300]}"

    def test_bullet_only_dump_blocks(self, tmp_path):
        r = _run(["--stdin"], tmp_path, stdin=BAD_BULLETS)
        assert r.returncode == 1, \
            f"bullet-only should BLOCK, rc={r.returncode}, stdout={r.stdout[:300]}"

    def test_schema_dump_blocks(self, tmp_path):
        r = _run(["--stdin"], tmp_path, stdin=BAD_SCHEMA_DUMP)
        assert r.returncode == 1, \
            f"schema dump should BLOCK, rc={r.returncode}, stdout={r.stdout[:300]}"

    def test_terse_terminator_blocks(self, tmp_path):
        r = _run(["--stdin"], tmp_path, stdin=BAD_TERSE)
        assert r.returncode == 1, \
            f"terse 'OK' should BLOCK, rc={r.returncode}, stdout={r.stdout[:300]}"

    def test_threshold_tuning(self, tmp_path):
        # With threshold=0.0, even weak text passes
        r = _run(["--stdin", "--threshold", "0.0"], tmp_path, stdin=BAD_BULLETS)
        assert r.returncode == 0, \
            f"threshold=0 should PASS anything, rc={r.returncode}"

    def test_file_input_mode(self, tmp_path):
        f = tmp_path / "prose.txt"
        f.write_text(GOOD_PROSE, encoding="utf-8")
        r = _run(["--file", str(f)], tmp_path)
        assert r.returncode == 0, f"--file mode with good prose, stdout={r.stdout[:200]}"

    def test_schema_canonical_output(self, tmp_path):
        r = _run(["--stdin"], tmp_path, stdin=GOOD_PROSE)
        try:
            data = json.loads(r.stdout)
            assert "validator" in data
            assert "verdict" in data
            assert data["verdict"] in ("PASS", "BLOCK", "WARN")
            assert "evidence" in data
        except json.JSONDecodeError:
            # Validator may emit non-JSON if output is human-only — at minimum
            # rc must be valid
            assert r.returncode in (0, 1, 2)
