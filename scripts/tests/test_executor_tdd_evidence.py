"""
R6 Task 9 — Tests for TDD evidence enforcement in executor return schema.

Coverage:
  Schema parity:
    - test_skill_md_lists_tdd_evidence_fields
    - test_waves_delegation_lists_tdd_evidence_fields

  Validator (scripts/validators/verify-tdd-evidence.py):
    - test_validator_passes_on_valid_tdd_evidence       (happy path)
    - test_validator_blocks_on_missing_red              (BLOCK)
    - test_validator_blocks_on_missing_green            (BLOCK)
    - test_validator_blocks_on_red_passing              (BLOCK)
    - test_validator_blocks_on_green_failing            (BLOCK)
    - test_validator_blocks_on_wrong_order              (BLOCK)
    - test_validator_skips_task_with_tdd_required_false (PASS skip)

  Timestamp robustness (R6 Task 9 follow-up I2):
    - test_validator_handles_mixed_iso_precision        (BLOCK on equal instant)
    - test_validator_handles_timezone_offsets           (PASS — UTC-normalized)
    - test_validator_blocks_on_malformed_timestamp      (BLOCK + new Evidence type)

Validator emit_and_exit semantics (per scripts/validators/_common.py):
  - rc 0 → PASS or WARN
  - rc 1 → BLOCK
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-tdd-evidence.py"
SKILL_MD = REPO_ROOT / "agents" / "vg-build-task-executor" / "SKILL.md"
WAVES_DELEGATION_MD = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "waves-delegation.md"
)


# ─── Schema parity tests ──────────────────────────────────────────────


def _field_table_has(text: str, field: str, required: str) -> bool:
    """Check that the markdown field table has a row for `field` with the
    given required-column value (`yes`, `maybe`, `optional`)."""
    pattern = re.compile(
        rf"\|\s*`{re.escape(field)}`\s*\|\s*{re.escape(required)}\s*\|",
        re.IGNORECASE,
    )
    return bool(pattern.search(text))


def test_skill_md_lists_tdd_evidence_fields():
    """SKILL.md Output JSON contract field table must list both new fields
    as `maybe` required (NULL when tdd_required=false)."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert _field_table_has(text, "test_red_evidence_path", "maybe"), (
        "SKILL.md field table missing `test_red_evidence_path | maybe |` row"
    )
    assert _field_table_has(text, "test_green_evidence_path", "maybe"), (
        "SKILL.md field table missing `test_green_evidence_path | maybe |` row"
    )
    # Sanity: also appears in the JSON example block
    assert "test_red_evidence_path" in text
    assert "test_green_evidence_path" in text


def test_waves_delegation_lists_tdd_evidence_fields():
    """waves-delegation.md (load-bearing contract) must mirror the same fields."""
    text = WAVES_DELEGATION_MD.read_text(encoding="utf-8")
    assert _field_table_has(text, "test_red_evidence_path", "maybe"), (
        "waves-delegation.md field table missing `test_red_evidence_path | maybe |` row"
    )
    assert _field_table_has(text, "test_green_evidence_path", "maybe"), (
        "waves-delegation.md field table missing `test_green_evidence_path | maybe |` row"
    )
    assert "test_red_evidence_path" in text
    assert "test_green_evidence_path" in text


# ─── Validator behavioral tests ───────────────────────────────────────


def _stage_phase(
    tmp_path: Path,
    *,
    tdd_required: bool,
    red: dict | None,
    green: dict | None,
    task_id: str = "task-04",
) -> Path:
    """Stage a tmp phase dir with one capsule + optional red/green evidence."""
    phase_dir = tmp_path / "07.99-test"
    phase_dir.mkdir(parents=True)

    # Capsule
    capsule_dir = phase_dir / ".task-capsules"
    capsule_dir.mkdir()
    capsule = {
        "task_id": task_id,
        "task_context": {},
        "contract_context": {},
        "goals_context": {},
        "sibling_context": {},
        "downstream_callers": [],
        "build_config": {},
        "tdd_required": tdd_required,
    }
    (capsule_dir / f"{task_id}.capsule.json").write_text(
        json.dumps(capsule), encoding="utf-8",
    )

    # Evidence files
    if red is not None or green is not None:
        ev_dir = phase_dir / ".test-evidence"
        ev_dir.mkdir()
        if red is not None:
            (ev_dir / f"{task_id}.red.json").write_text(
                json.dumps(red), encoding="utf-8",
            )
        if green is not None:
            (ev_dir / f"{task_id}.green.json").write_text(
                json.dumps(green), encoding="utf-8",
            )

    return phase_dir


def _run_validator(phase_dir: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase-dir", str(phase_dir)],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace",
    )


def _parse_output(proc: subprocess.CompletedProcess) -> dict:
    """Parse the JSON line emitted by the validator."""
    # _common.emit_and_exit() prints exactly one JSON line on stdout.
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    return json.loads(line)


# Canonical valid evidence pair
_VALID_RED = {
    "task_id": "task-04",
    "phase": "tdd_red",
    "captured_at": "2026-05-05T12:00:00Z",
    "test_command": "npx playwright test foo.spec.ts",
    "exit_code": 1,
    "test_output_tail": "FAIL: foo",
    "expected_outcome": "FAIL_BEFORE_FIX",
}
_VALID_GREEN = {
    "task_id": "task-04",
    "phase": "tdd_green",
    "captured_at": "2026-05-05T12:05:00Z",  # strictly after red
    "test_command": "npx playwright test foo.spec.ts",
    "exit_code": 0,
    "test_output_tail": "PASS: foo",
    "expected_outcome": "PASS_AFTER_FIX",
}


def test_validator_passes_on_valid_tdd_evidence(tmp_path):
    """Capsule tdd_required=true + valid red+green → PASS (rc=0)."""
    phase_dir = _stage_phase(
        tmp_path, tdd_required=True,
        red=dict(_VALID_RED), green=dict(_VALID_GREEN),
    )
    proc = _run_validator(phase_dir)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] in ("PASS", "WARN"), out


def test_validator_blocks_on_missing_red(tmp_path):
    """Capsule tdd_required=true + green only → BLOCK."""
    phase_dir = _stage_phase(
        tmp_path, tdd_required=True,
        red=None, green=dict(_VALID_GREEN),
    )
    proc = _run_validator(phase_dir)
    assert proc.returncode == 1, (
        f"Expected BLOCK rc=1, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK"
    types = {e.get("type") for e in out["evidence"]}
    assert "tdd_evidence_missing" in types, types


def test_validator_blocks_on_missing_green(tmp_path):
    """Capsule tdd_required=true + red only → BLOCK."""
    phase_dir = _stage_phase(
        tmp_path, tdd_required=True,
        red=dict(_VALID_RED), green=None,
    )
    proc = _run_validator(phase_dir)
    assert proc.returncode == 1, proc.stdout
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK"
    types = {e.get("type") for e in out["evidence"]}
    assert "tdd_evidence_missing" in types, types


def test_validator_blocks_on_red_passing(tmp_path):
    """Red exit_code=0 (test trivially passed before fix) → BLOCK."""
    bad_red = dict(_VALID_RED)
    bad_red["exit_code"] = 0  # broken: red should fail
    phase_dir = _stage_phase(
        tmp_path, tdd_required=True,
        red=bad_red, green=dict(_VALID_GREEN),
    )
    proc = _run_validator(phase_dir)
    assert proc.returncode == 1, proc.stdout
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK"
    types = {e.get("type") for e in out["evidence"]}
    assert "tdd_red_passing" in types, types


def test_validator_blocks_on_green_failing(tmp_path):
    """Green exit_code != 0 (test still failed after fix) → BLOCK."""
    bad_green = dict(_VALID_GREEN)
    bad_green["exit_code"] = 1  # broken: fix didn't satisfy test
    phase_dir = _stage_phase(
        tmp_path, tdd_required=True,
        red=dict(_VALID_RED), green=bad_green,
    )
    proc = _run_validator(phase_dir)
    assert proc.returncode == 1, proc.stdout
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK"
    types = {e.get("type") for e in out["evidence"]}
    assert "tdd_green_failing" in types, types


def test_validator_blocks_on_wrong_order(tmp_path):
    """Green captured_at <= red captured_at → BLOCK (wrong temporal order)."""
    swapped_red = dict(_VALID_RED)
    swapped_green = dict(_VALID_GREEN)
    # Swap timestamps so green is BEFORE red
    swapped_red["captured_at"] = "2026-05-05T13:00:00Z"
    swapped_green["captured_at"] = "2026-05-05T12:00:00Z"
    phase_dir = _stage_phase(
        tmp_path, tdd_required=True,
        red=swapped_red, green=swapped_green,
    )
    proc = _run_validator(phase_dir)
    assert proc.returncode == 1, proc.stdout
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK"
    types = {e.get("type") for e in out["evidence"]}
    assert "tdd_evidence_wrong_order" in types, types


def test_validator_skips_task_with_tdd_required_false(tmp_path):
    """Capsule tdd_required=false + no evidence files → PASS (skip path)."""
    phase_dir = _stage_phase(
        tmp_path, tdd_required=False,
        red=None, green=None,
    )
    proc = _run_validator(phase_dir)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0 (skip path), got rc={proc.returncode}\n"
        f"stdout={proc.stdout}"
    )
    out = _parse_output(proc)
    assert out["verdict"] in ("PASS", "WARN"), out


# ─── Timestamp robustness tests (R6 Task 9 follow-up I2) ──────────────
#
# These tests guard against ISO-8601 string compare bugs:
#   Bug A (false-PASS): red '2026-05-05T12:00:00.000Z' vs green
#     '2026-05-05T12:00:00Z' lex'd '.' < 'Z' → red < green → PASS but
#     timestamps are equal as instants. Validator must BLOCK.
#   Bug B (false-BLOCK): red '2026-05-05T12:05:00+07:00' (= 05:05Z) vs
#     green '2026-05-05T05:10:00Z' lex'd '+' > '0' → red > green → false
#     BLOCK even though red is genuinely 5min before green. Validator
#     must PASS after UTC normalization.
#   Bug C (silent-wrong-verdict): garbage timestamps must produce an
#     explicit Evidence row, not be coerced into < or >.


def test_validator_handles_mixed_iso_precision(tmp_path):
    """Red 12:00:00.000Z and green 12:00:00Z are SAME instant — must BLOCK.

    Pre-fix: lex compare ('.' < 'Z') reported red < green → PASS
    (false-PASS — TDD discipline broken because red is not strictly
    earlier). Post-fix: UTC-normalized parsing recognizes equal instants
    and BLOCKs because temporal order requires strict <.
    """
    eq_red = dict(_VALID_RED)
    eq_green = dict(_VALID_GREEN)
    eq_red["captured_at"] = "2026-05-05T12:00:00.000Z"
    eq_green["captured_at"] = "2026-05-05T12:00:00Z"
    phase_dir = _stage_phase(
        tmp_path, tdd_required=True,
        red=eq_red, green=eq_green,
    )
    proc = _run_validator(phase_dir)
    assert proc.returncode == 1, (
        f"Expected BLOCK rc=1 (equal instants violate strict <), got "
        f"rc={proc.returncode}\nstdout={proc.stdout}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK"
    types = {e.get("type") for e in out["evidence"]}
    assert "tdd_evidence_wrong_order" in types, types


def test_validator_handles_timezone_offsets(tmp_path):
    """Red 12:05:00+07:00 (= 05:05Z) is BEFORE green 05:10:00Z by 5 min — must PASS.

    Pre-fix: lex compare on raw strings '2026-05-05T12:05:00+07:00' vs
    '2026-05-05T05:10:00Z' said red > green ('+'/'1' > '0') → false
    BLOCK. Post-fix: UTC-normalize both → red=05:05Z < green=05:10Z →
    PASS.
    """
    tz_red = dict(_VALID_RED)
    tz_green = dict(_VALID_GREEN)
    tz_red["captured_at"] = "2026-05-05T12:05:00+07:00"  # = 05:05:00Z
    tz_green["captured_at"] = "2026-05-05T05:10:00Z"
    phase_dir = _stage_phase(
        tmp_path, tdd_required=True,
        red=tz_red, green=tz_green,
    )
    proc = _run_validator(phase_dir)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0 (red genuinely earlier after UTC normalization), "
        f"got rc={proc.returncode}\nstdout={proc.stdout}"
    )
    out = _parse_output(proc)
    assert out["verdict"] in ("PASS", "WARN"), out


def test_validator_blocks_on_malformed_timestamp(tmp_path):
    """Garbage captured_at must produce explicit Evidence, not silent verdict.

    Pre-fix: any string compared lexically — `not-a-real-date` < or >
    a real ISO string would be evaluated and accepted, possibly
    producing a wrong PASS/BLOCK depending on the compare. Post-fix:
    parse failure → tdd_evidence_bad_timestamp_format Evidence + BLOCK.
    """
    bad_red = dict(_VALID_RED)
    bad_green = dict(_VALID_GREEN)
    bad_red["captured_at"] = "not-a-real-date"
    bad_green["captured_at"] = "2026-05-05T05:10:00Z"
    phase_dir = _stage_phase(
        tmp_path, tdd_required=True,
        red=bad_red, green=bad_green,
    )
    proc = _run_validator(phase_dir)
    assert proc.returncode == 1, (
        f"Expected BLOCK rc=1 on unparseable timestamp, got "
        f"rc={proc.returncode}\nstdout={proc.stdout}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK"
    types = {e.get("type") for e in out["evidence"]}
    assert "tdd_evidence_bad_timestamp_format" in types, (
        f"Expected new Evidence type for unparseable timestamp; saw {types}"
    )
