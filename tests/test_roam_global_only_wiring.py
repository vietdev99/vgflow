from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _roam_files() -> list[Path]:
    return [
        REPO_ROOT / "commands" / "vg" / "roam.md",
        *sorted((REPO_ROOT / "commands" / "vg" / "_shared" / "roam").rglob("*.md")),
    ]


def test_roam_runtime_snippets_use_global_script_root() -> None:
    for path in _roam_files():
        body = path.read_text(encoding="utf-8")
        assert ".claude/scripts/" not in body, (
            f"{path.relative_to(REPO_ROOT)} must use VG_SCRIPT_ROOT/global "
            "scripts so global-only installs work after project-local prune"
        )
        assert "bash scripts/vg-narrate-spawn.sh" not in body


def test_roam_codex_skill_has_marker_hardgate() -> None:
    body = (REPO_ROOT / "codex-skills" / "vg-roam" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "<HARD-GATE-CODEX>" in body
    for marker in (
        "0_parse_and_validate",
        "0a_backfill_env_pref",
        "0a_detect_platform_tools",
        "0a_enrich_env_options",
        "0a_confirm_env_model_mode",
        "0a_persist_config",
        "0aa_resume_check",
        "1_discover_surfaces",
        "2_compose_briefs",
        "3_spawn_executors",
        "4_aggregate_logs",
        "5_analyze_findings",
        "6_emit_artifacts",
        "complete",
    ):
        assert f"mark-step roam {marker}" in body
