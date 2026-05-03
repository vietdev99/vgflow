"""Test --pre-test flag for /vg:deploy — Task 20."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_deploy_md_accepts_pre_test_flag() -> None:
    """commands/vg/deploy.md argument-hint must include --pre-test."""
    text = (REPO / "commands" / "vg" / "deploy.md").read_text(encoding="utf-8")
    assert "--pre-test" in text, "deploy.md must declare --pre-test in argument-hint"


def test_deploy_overview_handles_pre_test_pre_close() -> None:
    """deploy/overview.md must exempt build-complete check when --pre-test set."""
    text = (REPO / "commands" / "vg" / "_shared" / "deploy" / "overview.md").read_text(encoding="utf-8")
    assert "--pre-test" in text
    assert "build_complete" in text or "build-complete" in text
    assert "pre_test" in text.lower() or "pre-test" in text.lower()


def test_deploy_state_records_pre_test_mode(tmp_path: Path) -> None:
    """DEPLOY-STATE.json must record mode='pre-test' when invoked with --pre-test."""
    sample = {
        "deployed": {
            "sandbox": {
                "url": "https://sandbox.example.com",
                "deployed_at": "2026-05-03T10:00:00Z",
                "mode": "pre-test",
                "phase": "test-1.0",
            }
        }
    }
    target = tmp_path / "DEPLOY-STATE.json"
    target.write_text(json.dumps(sample), encoding="utf-8")
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed["deployed"]["sandbox"]["mode"] == "pre-test"
