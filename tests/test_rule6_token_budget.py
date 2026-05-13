"""tests/test_rule6_token_budget.py — Rule 6 token budget tracker."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
TB = REPO / "scripts" / "token-budget.py"


def test_tracker_script_exists():
    assert TB.is_file(), "Rule 6: scripts/token-budget.py must ship"


def test_tracker_add_accumulates(tmp_path):
    """Calling --add N twice must accumulate."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    for n in (1000, 1500):
        r = subprocess.run(
            [sys.executable, str(TB), "--phase-dir", str(phase_dir),
             "--task", "T-01", "--add", str(n)],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
    ledger = phase_dir / ".token-budget.json"
    assert ledger.is_file()
    data = json.loads(ledger.read_text(encoding="utf-8"))
    assert data["tasks"]["T-01"]["used"] == 2500


def test_tracker_check_warns_at_80_percent(tmp_path):
    """At >=80% of per_task budget, --check must report WARN."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    # Default per_task=4000 from tinbeta. Set used=3500 (87.5%).
    subprocess.run(
        [sys.executable, str(TB), "--phase-dir", str(phase_dir),
         "--task", "T-01", "--add", "3500"],
        capture_output=True, text=True,
    )
    r = subprocess.run(
        [sys.executable, str(TB), "--phase-dir", str(phase_dir),
         "--task", "T-01", "--check"],
        capture_output=True, text=True,
    )
    assert "WARN" in r.stdout or "warn" in r.stdout.lower() or "80" in r.stdout, (
        f"Rule 6: 3500/4000 (87.5%) must trigger WARN. Got: {r.stdout!r}"
    )


def test_tracker_check_blocks_at_100_percent(tmp_path):
    """At >100% of per_task budget, --check must exit non-zero unless --allow-overrun."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    subprocess.run(
        [sys.executable, str(TB), "--phase-dir", str(phase_dir),
         "--task", "T-02", "--add", "5000"],
        capture_output=True, text=True,
    )
    r = subprocess.run(
        [sys.executable, str(TB), "--phase-dir", str(phase_dir),
         "--task", "T-02", "--check"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, (
        f"Rule 6: 5000/4000 over-budget must exit non-zero. Got rc={r.returncode}"
    )


def test_tracker_allow_overrun_bypasses(tmp_path):
    """--allow-overrun bypasses BLOCK."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    subprocess.run(
        [sys.executable, str(TB), "--phase-dir", str(phase_dir),
         "--task", "T-03", "--add", "5000"],
        capture_output=True, text=True,
    )
    r = subprocess.run(
        [sys.executable, str(TB), "--phase-dir", str(phase_dir),
         "--task", "T-03", "--check", "--allow-overrun"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, "Rule 6: --allow-overrun must let over-budget pass with WARN"


def test_config_template_documents_token_budget_block():
    config_paths = [
        REPO / "vg.config.template.md",
        REPO / "templates" / "vg" / "vg.config.template.md",
    ]
    found = False
    for p in config_paths:
        if p.is_file():
            body = p.read_text(encoding="utf-8")
            if "token_budget" in body and "per_task" in body and "per_session" in body:
                found = True
                break
    assert found, (
        "Rule 6: vg.config.template.md must document token_budget.{per_task, per_session} block"
    )
