"""tests/test_deploy_steps_source_load.py — Batch 20 deploy steps source loader."""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_test_deploy_step_sources_loader():
    body = (REPO / "commands/vg/_shared/test/deploy.md").read_text(encoding="utf-8")
    assert "deploy-contract-load.py" in body, (
        "Batch 20: test/deploy.md STEP 5a_deploy must source deploy-contract-load.py "
        "to export DEPLOY_BUILD/DEPLOY_RESTART/DEPLOY_HEALTH from contract"
    )
    # The export must be USED — at least one $DEPLOY_BUILD / $DEPLOY_RESTART reference
    assert "$DEPLOY_BUILD" in body or "$DEPLOY_RESTART" in body or "$DEPLOY_HEALTH" in body, (
        "Batch 20: must reference exported $DEPLOY_* vars (not just source then ignore)"
    )


def test_deploy_execute_sources_loader():
    body = (REPO / "commands/vg/_shared/deploy/execute.md").read_text(encoding="utf-8")
    assert "deploy-contract-load.py" in body, (
        "Batch 20: deploy/execute.md must source deploy-contract-load.py"
    )


def test_deploy_preflight_bootstrap_check():
    body = (REPO / "commands/vg/_shared/deploy/preflight.md").read_text(encoding="utf-8")
    assert "DEPLOY-CONTRACT.json" in body, (
        "Batch 20: deploy/preflight.md must check for DEPLOY-CONTRACT.json "
        "and suggest --init if missing"
    )
