from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_planner_contract_requires_plan_schema_anchors():
    text = (REPO / "agents/vg-blueprint-planner/SKILL.md").read_text(encoding="utf-8")

    for required in (
        "phase:",
        "profile:",
        "platform:",
        "goal_summary:",
        "total_waves:",
        "total_tasks:",
        "generated_at:",
        "## Wave 1",
        "## Verification",
        "## Risks",
        ".claude/schemas/plan.v1.json",
        "Do NOT put `cli-tool` or `library` in `profile`",
        "<implements-decision>",
        "<goals-covered>",
        "Covers goal:",
        "Human-readable `**Goals covered:**` and `**Decisions implemented:**` lines",
    ):
        assert required in text


def test_plan_delegation_injects_schema_requirements():
    text = (REPO / "commands/vg/_shared/blueprint/plan-delegation.md").read_text(
        encoding="utf-8",
    )

    assert "PLAN SCHEMA REQUIREMENTS (BLOCKING)" in text
    assert "set `profile: feature` and set `platform: ${PROFILE}`" in text
    assert "Layer 2 index.md MUST include the same frontmatter" in text
    assert "`## Wave 1` through `## Wave <wave_count>`" in text
    assert "TRACEABILITY TAGS (BLOCKING)" in text
    assert "<implements-decision>D-ID</implements-decision>" in text
    assert "<goals-covered>G-XX,...</goals-covered>" in text
    assert "Do not rely only on human-readable `**Goals covered:**`" in text


def test_blueprint_ui_markers_profile_gated_for_cli():
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/filter-steps.py"),
            "--command",
            str(REPO / "commands/vg/blueprint.md"),
            "--profile",
            "cli-tool",
            "--output-ids",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, result.stderr
    steps = {part.strip() for part in result.stdout.split(",") if part.strip()}
    assert "2b6c_view_decomposition" not in steps
    assert "2b6_ui_spec" not in steps
    assert "2b6b_ui_map" not in steps


def test_codex_adapter_warns_against_unquoted_spawn_heredocs():
    text = (REPO / "scripts/generate-codex-skills.sh").read_text(encoding="utf-8")

    assert "cat > \"\\$PROMPT_FILE\" <<'EOF'" in text
    assert "Do not use unquoted \\`<<EOF\\`" in text

def test_contracts_agent_supports_cli_no_http_contracts():
    text = (REPO / "agents/vg-blueprint-contracts/SKILL.md").read_text(
        encoding="utf-8",
    )

    for required in (
        "`API-CONTRACTS` means the phase interface contract, not always HTTP",
        "`platform: cli-tool`",
        "`API-CONTRACTS/cli-health.md`",
        "`HTTP endpoint count = 0`",
        "Return JSON `endpoint_count` MUST be `0`",
        "Do NOT use HTTP endpoint headings",
        "enumerate every supported invocation form",
        "`resources: []` plus `no_crud_reason`",
    ):
        assert required in text

def test_contract_delegation_injects_cli_no_http_rules():
    text = (
        REPO / "commands/vg/_shared/blueprint/contracts-delegation.md"
    ).read_text(encoding="utf-8")

    for required in (
        "Profile-aware interface contract rules",
        "`API-CONTRACTS` is the phase interface contract",
        "profile: ${PROFILE}",
        "write CLI/library interface files",
        "`HTTP endpoint count = 0`",
        "Return JSON `endpoint_count` MUST be `0`",
        "Do NOT use endpoint headings matching",
        "enumerate every supported invocation form",
        "generate interface contracts instead and keep `endpoint_count=0`",
    ):
        assert required in text
