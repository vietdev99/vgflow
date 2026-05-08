import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROBER = ".claude/scripts/bootstrap-attribute-outcome.py"


def _make_rule(tmp_path: Path, sequence_yaml: str) -> Path:
    """Helper: write a procedural rule with the given sequence section."""
    rule = tmp_path / "rule.md"
    rule.write_text(
        "---\n"
        "slug: test\n"
        "type: procedural\n"
        "authority: advisory\n"
        "target_step: deploy\n"
        f"{sequence_yaml}"
        "success_signals: []\n"
        "attribution_required: true\n"
        "---\n",
        encoding="utf-8",
    )
    return rule


def _run_prober(rule_path: Path, log_path: Path) -> dict:
    result = subprocess.run(
        [sys.executable, PROBER, "--rule", str(rule_path), "--log", str(log_path), "--json"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"prober failed: {result.stderr}"
    return json.loads(result.stdout)


def test_full_match_returns_all_steps(tmp_path):
    rule = _make_rule(
        tmp_path,
        "sequence:\n"
        "  - id: s1\n"
        "    cmd: \"npm run build\"\n"
        "    expected_signals: [\"exit=0\"]\n"
        "  - id: s2\n"
        "    cmd: \"flyctl deploy --remote-only\"\n"
        "    expected_signals: [\"exit=0\"]\n"
    )
    log = tmp_path / "deploy.log"
    log.write_text(
        "$ npm run build\n"
        "built in 3.2s\n"
        "exit=0\n"
        "$ flyctl deploy --remote-only\n"
        "==> Building image...\n"
        "exit=0\n",
        encoding="utf-8",
    )
    payload = _run_prober(rule, log)
    assert payload["executed_step_ids"] == ["s1", "s2"]
    assert payload["total_steps"] == 2
    assert payload["matched_signals_count"] == 2


def test_partial_match_returns_subset(tmp_path):
    rule = _make_rule(
        tmp_path,
        "sequence:\n"
        "  - id: s1\n"
        "    cmd: \"npm run build\"\n"
        "    expected_signals: [\"exit=0\"]\n"
        "  - id: s2\n"
        "    cmd: \"flyctl deploy\"\n"
        "    expected_signals: [\"exit=0\"]\n"
    )
    log = tmp_path / "log.txt"
    log.write_text("$ npm run build\nexit=0\n", encoding="utf-8")
    payload = _run_prober(rule, log)
    assert payload["executed_step_ids"] == ["s1"]
    assert payload["total_steps"] == 2
    assert payload["matched_signals_count"] == 1


def test_no_execution_returns_empty(tmp_path):
    rule = _make_rule(
        tmp_path,
        "sequence:\n"
        "  - id: s1\n"
        "    cmd: \"npm run build\"\n"
        "    expected_signals: [\"exit=0\"]\n"
    )
    log = tmp_path / "empty.txt"
    log.write_text("", encoding="utf-8")
    payload = _run_prober(rule, log)
    assert payload["executed_step_ids"] == []
    assert payload["total_steps"] == 1
    assert payload["matched_signals_count"] == 0


def test_out_of_order_does_not_count(tmp_path):
    """Steps must execute IN ORDER. Log has s2 first then s1 -> only s2 (cursor)."""
    rule = _make_rule(
        tmp_path,
        "sequence:\n"
        "  - id: s1\n"
        "    cmd: \"alpha-cmd\"\n"
        "    expected_signals: []\n"
        "  - id: s2\n"
        "    cmd: \"beta-cmd\"\n"
        "    expected_signals: []\n"
    )
    log = tmp_path / "log.txt"
    log.write_text("$ beta-cmd\noutput\n$ alpha-cmd\noutput\n", encoding="utf-8")
    payload = _run_prober(rule, log)
    # Cursor: scan for s1 (alpha-cmd) -> found at offset N.
    # Then scan for s2 (beta-cmd) starting AFTER s1 -- but beta-cmd was BEFORE alpha-cmd in log.
    # So s2 NOT found via forward cursor.
    # Only s1 should match.
    assert payload["executed_step_ids"] == ["s1"]


def test_signals_only_matched_within_4096_bytes_after_cmd(tmp_path):
    rule = _make_rule(
        tmp_path,
        "sequence:\n"
        "  - id: s1\n"
        "    cmd: \"my-cmd\"\n"
        "    expected_signals: [\"DONE\"]\n"
    )
    log = tmp_path / "log.txt"
    # cmd at offset 0, DONE at offset 5000 (beyond 4096 window)
    log.write_text("$ my-cmd\n" + ("X" * 5000) + "\nDONE\n", encoding="utf-8")
    payload = _run_prober(rule, log)
    assert payload["executed_step_ids"] == ["s1"]
    # Signal beyond window -> not counted
    assert payload["matched_signals_count"] == 0


def test_missing_rule_file_errors(tmp_path):
    log = tmp_path / "log.txt"
    log.write_text("", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, PROBER, "--rule", str(tmp_path / "nonexistent.md"),
         "--log", str(log), "--json"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
