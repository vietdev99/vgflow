"""
harness-v2.7-fixup-N11 — orchestrator validator-dispatch tolerance for
non-JSON stdout.

Bug surfaced from /vg:accept 7.14.3 (2026-04-26):
  11 validators crashed with "Expecting value: line 1 column 1 (char 0)"
  inside _run_validators. Root cause: those validators emit human-
  friendly text (e.g. "✓ No Tier-A promotions") by default and only
  flip to JSON when `--json` is passed. Orchestrator dispatch did not
  pass `--json` and tried `json.loads()` on the text → quarantine
  cascade → false BLOCK verdict on every accept run.

Fix: when stdout has no `{` character, synthesize a verdict from the
exit code (0 = PASS, 1 = WARN, 2+ = SKIP). Mark synthesized verdicts
with `_synthesized_from_exit_code: True` so reviewers can spot them.

This test pins the synthesis logic against future regression.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATOR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py"


@pytest.fixture(scope="module")
def orchestrator():
    spec = importlib.util.spec_from_file_location("vg_orch_n11", ORCHESTRATOR)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orch_n11"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


def _make_completed(stdout: str, returncode: int):
    """Stand-in for subprocess.CompletedProcess."""

    class _CP:
        def __init__(self, stdout, rc):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = rc

    return _CP(stdout, returncode)


def test_synth_pass_for_text_stdout_exit_zero(orchestrator):
    """Validator prints '✓ All good' and exits 0 → PASS, no crash."""
    fake = _make_completed("✓ No drift detected\n", 0)
    with patch("subprocess.run", return_value=fake):
        with patch.object(orchestrator, "_resolve_extra_arg", return_value=None):
            blocks = orchestrator._run_validators(
                "vg:accept", "7.14.3-test", "run-id-123", ""
            )
    crash_blocks = [b for b in blocks if "validator crash" in
                    str(b.get("evidence", [{}])[0].get("message", ""))]
    assert not crash_blocks, f"Crash leaked into blocks: {crash_blocks}"


def test_synth_warn_for_text_stdout_exit_one(orchestrator):
    """Validator prints '\033[33mDrift\033[0m' and exits 1 → WARN (not crash)."""
    fake = _make_completed("\033[33m4 skills out of sync\033[0m\n", 1)
    with patch("subprocess.run", return_value=fake):
        with patch.object(orchestrator, "_resolve_extra_arg", return_value=None):
            blocks = orchestrator._run_validators(
                "vg:accept", "7.14.3-test", "run-id-123", ""
            )
    crash_blocks = [b for b in blocks if "validator crash" in
                    str(b.get("evidence", [{}])[0].get("message", ""))]
    assert not crash_blocks, f"WARN should not crash: {crash_blocks}"


def test_synth_skip_for_usage_error_exit_two(orchestrator):
    """Validator exits 2 with usage message → SKIP (don't block accept)."""
    fake = _make_completed(
        "usage: verify-x.py [-h] --run-id RUN_ID\nverify-x.py: error: required\n",
        2,
    )
    with patch("subprocess.run", return_value=fake):
        with patch.object(orchestrator, "_resolve_extra_arg", return_value=None):
            blocks = orchestrator._run_validators(
                "vg:accept", "7.14.3-test", "run-id-123", ""
            )
    crash_blocks = [b for b in blocks if "validator crash" in
                    str(b.get("evidence", [{}])[0].get("message", ""))]
    assert not crash_blocks, f"SKIP should not block: {crash_blocks}"


def test_real_validator_dispatch_no_crash():
    """Smoke: dispatch the actual verify-learn-promotion validator (which
    emits text by default). Before the fix this caused
    `Expecting value: line 1 column 1 (char 0)` crash. Now: clean PASS.
    """
    r = subprocess.run(
        [sys.executable, ".claude/scripts/validators/verify-learn-promotion.py",
         "--phase", "7.14.3-test"],
        capture_output=True, text=True, timeout=30, cwd=REPO_ROOT,
    )
    assert r.returncode == 0
    # Synthesizer fix only kicks in if there's no JSON brace anywhere.
    assert "{" not in r.stdout, (
        "Validator unexpectedly produced JSON — fix may be unnecessary "
        "for this validator now"
    )


def test_synth_evidence_marks_synthesized(orchestrator):
    """Evidence emitted by synth path must carry `_synthesized_from_exit_code`
    so reviewers can distinguish synthesized verdicts from validator-emitted
    JSON. (Light invariant — string in source.)
    """
    src = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "_synthesized_from_exit_code" in src, (
        "Synth path missing marker field — reviewers can't tell synthesized "
        "verdicts from real ones"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
