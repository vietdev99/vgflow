"""
Tests for HARDCODE-REGISTER drift detection (Phase K5, v2.7).

Companion to:
- .vg/HARDCODE-REGISTER.md (audit register)
- .claude/scripts/validators/verify-no-hardcoded-paths.py (BLOCK validator)

The register declares the universe of acceptable hardcoded SSH/path/port
literals (operational REPLACE_WITH_CONFIG, INTENTIONAL_HARDCODE, or
ALREADY_PARAMETRIZED). When code drifts (a new `ssh vollx` literal slips
in without a register entry), CI catches it via this test BEFORE the
validator BLOCK at /vg:accept time.

Cases (per PLAN-v2.7 K5):
  1. Register count matches grep count exactly — no drift, PASS
  2. Drift detected — register has 50 entries but grep finds 55 → BLOCK
  3. Allowlist — test fixture lines with `# INTENTIONAL_HARDCODE` skip
     detection cleanly
  4. Schema valid — every entry has the required columns
     (file, line, category, remediation)
  5. Register stale > 30 days → WARN suggesting re-audit
  6. Empty register OR not-yet-created → graceful PASS with explanation

Test mirrors prior tests' VG_REPO_ROOT scoping pattern: each case writes
a tmp register + tmp source files, points VG_REPO_ROOT at tmp_path, and
runs the drift validator subprocess.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT_REAL = Path(__file__).resolve().parents[3]
DRIFT_VALIDATOR = (
    REPO_ROOT_REAL / ".claude" / "scripts" / "validators"
    / "verify-hardcode-register-drift.py"
)


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(DRIFT_VALIDATOR), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(cwd),
        timeout=30,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


REGISTER_HEADER_TEMPLATE = textwrap.dedent(
    """\
    # HARDCODE-REGISTER

    **Generated:** {generated}
    **Auditor:** test fixture
    **Plan:** synthetic

    ## 4. Active occurrence registry

    ### Category: `ssh_alias` — `ssh vollx`

    | file | line | literal | remediation | config_key |
    |------|------|---------|-------------|------------|
    {rows}

    ## 7. Auto-generated count summary

    ```
    TOTAL operational occurrences:  {total}
    ```
    """
)


def _make_register(
    tmp_path: Path,
    rows: list[tuple[str, int]],
    *,
    generated: str | None = None,
) -> Path:
    """Build a synthetic .vg/HARDCODE-REGISTER.md with N rows."""
    register_path = tmp_path / ".vg" / "HARDCODE-REGISTER.md"
    register_path.parent.mkdir(parents=True, exist_ok=True)
    if generated is None:
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row_lines = []
    for file_rel, line_no in rows:
        row_lines.append(
            f"| {file_rel} | {line_no} | `ssh vollx` | REPLACE_WITH_CONFIG | "
            "environments.sandbox.run_prefix |"
        )
    register_path.write_text(
        REGISTER_HEADER_TEMPLATE.format(
            generated=generated,
            rows="\n".join(row_lines),
            total=len(rows),
        ),
        encoding="utf-8",
    )
    return register_path


def _make_source_with_literals(tmp_path: Path, hits: list[tuple[str, int]]) -> None:
    """Plant `ssh vollx` literals at specific (file, line) locations."""
    grouped: dict[str, list[int]] = {}
    for file_rel, line_no in hits:
        grouped.setdefault(file_rel, []).append(line_no)
    for file_rel, lines in grouped.items():
        max_line = max(lines)
        contents = []
        for i in range(1, max_line + 1):
            if i in lines:
                contents.append("ssh vollx 'pm2 reload all'")
            else:
                contents.append(f"# placeholder line {i}")
        _write(tmp_path / file_rel, "\n".join(contents) + "\n")


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


class TestHardcodeRegisterDrift:
    def test_count_matches_grep_passes(self, tmp_path):
        """Case 1: register count == grep count → PASS."""
        rows = [("apps/api/x.sh", 5), ("apps/api/y.sh", 7)]
        _make_register(tmp_path, rows)
        _make_source_with_literals(tmp_path, rows)
        r = _run([], tmp_path)
        assert r.returncode == 0, f"matching counts should PASS: {r.stdout}\n{r.stderr}"
        assert "PASS" in r.stdout or '"verdict": "PASS"' in r.stdout

    def test_drift_detected_blocks(self, tmp_path):
        """Case 2: 5 grep hits but register only declares 2 → BLOCK."""
        registered_rows = [("apps/api/x.sh", 5), ("apps/api/y.sh", 7)]
        _make_register(tmp_path, registered_rows)
        # Plant MORE hits than registered
        all_hits = registered_rows + [
            ("apps/api/extra1.sh", 3),
            ("apps/api/extra2.sh", 4),
            ("apps/api/extra3.sh", 5),
        ]
        _make_source_with_literals(tmp_path, all_hits)
        r = _run([], tmp_path)
        assert r.returncode == 1, f"drift should BLOCK: {r.stdout}\n{r.stderr}"
        assert "BLOCK" in r.stdout or '"verdict": "BLOCK"' in r.stdout

    def test_intentional_hardcode_annotation_skipped(self, tmp_path):
        """Case 3: lines with `# INTENTIONAL_HARDCODE` annotation aren't counted."""
        # Only 1 unannotated literal — register declares 1
        rows = [("apps/api/x.sh", 3)]
        _make_register(tmp_path, rows)
        # Plant 1 unannotated + 2 annotated literals
        _write(
            tmp_path / "apps/api/x.sh",
            textwrap.dedent(
                """\
                # placeholder
                # placeholder
                ssh vollx 'pm2 reload all'
                # placeholder
                # detection-test fixture below
                ssh vollx 'fake'  # INTENTIONAL_HARDCODE: test data
                ssh vollx 'fake2'  # INTENTIONAL_HARDCODE: test data
                """
            ),
        )
        r = _run([], tmp_path)
        assert r.returncode == 0, (
            f"annotation should skip from drift count: {r.stdout}\n{r.stderr}"
        )

    def test_schema_validity_required_columns(self, tmp_path):
        """Case 4: register row missing required columns → BLOCK with schema error."""
        register_path = tmp_path / ".vg" / "HARDCODE-REGISTER.md"
        register_path.parent.mkdir(parents=True, exist_ok=True)
        # Register with malformed row (only 2 columns instead of 5)
        register_path.write_text(
            textwrap.dedent(
                """\
                # HARDCODE-REGISTER

                ## 4. Active occurrence registry

                ### Category: `ssh_alias` — `ssh vollx`

                | file | line |
                |------|------|
                | apps/api/x.sh | 5 |
                """
            ),
            encoding="utf-8",
        )
        r = _run(["--schema-only"], tmp_path)
        assert r.returncode == 1, (
            f"malformed schema should BLOCK: {r.stdout}\n{r.stderr}"
        )
        assert "schema" in r.stdout.lower() or "schema" in r.stderr.lower()

    def test_stale_register_warns(self, tmp_path):
        """Case 5: register `Generated:` >30 days old → WARN."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%d")
        rows = [("apps/api/x.sh", 5)]
        _make_register(tmp_path, rows, generated=old_date)
        _make_source_with_literals(tmp_path, rows)
        r = _run([], tmp_path)
        # Stale should not BLOCK (counts match), but should WARN
        assert r.returncode == 0, (
            f"stale-only should not BLOCK: {r.stdout}\n{r.stderr}"
        )
        assert (
            "stale" in r.stdout.lower()
            or "WARN" in r.stdout
            or "30 days" in r.stdout
            or "30 ngày" in r.stdout
        )

    def test_register_missing_passes_gracefully(self, tmp_path):
        """Case 6: no register file → PASS with explanation, no crash."""
        # No .vg/HARDCODE-REGISTER.md created
        # Plant a few literals — without a register, drift detection is
        # bootstrapped (no audit yet → graceful PASS).
        _make_source_with_literals(
            tmp_path, [("apps/api/x.sh", 5), ("apps/api/y.sh", 7)]
        )
        r = _run([], tmp_path)
        assert r.returncode == 0, (
            f"missing register should PASS gracefully: "
            f"{r.stdout}\n{r.stderr}"
        )
        # Either explicit "no audit yet" message or PASS verdict
        out_lower = (r.stdout + r.stderr).lower()
        assert (
            "no audit" in out_lower
            or "not yet" in out_lower
            or "missing" in out_lower
            or "PASS" in r.stdout
        )
