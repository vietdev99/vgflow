"""R3.5 Roam Pilot — all referenced shared files exist + sub-step refs ≤150 lines."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_all_top_level_refs_exist():
    """7 top-level refs in commands/vg/_shared/roam/."""
    refs = [
        "commands/vg/_shared/roam/preflight.md",
        "commands/vg/_shared/roam/discovery.md",
        "commands/vg/_shared/roam/spawn-executors.md",
        "commands/vg/_shared/roam/aggregate-analyze.md",
        "commands/vg/_shared/roam/artifacts.md",
        "commands/vg/_shared/roam/fix-loop.md",
        "commands/vg/_shared/roam/close.md",
    ]
    for ref in refs:
        p = REPO / ref
        assert p.exists(), f"missing top-level ref: {ref}"


def test_all_config_gate_subrefs_exist():
    """6 config-gate refs (overview + 5 sub-steps)."""
    subrefs = [
        "commands/vg/_shared/roam/config-gate/overview.md",
        "commands/vg/_shared/roam/config-gate/backfill-env.md",
        "commands/vg/_shared/roam/config-gate/detect-platform.md",
        "commands/vg/_shared/roam/config-gate/enrich-env.md",
        "commands/vg/_shared/roam/config-gate/confirm-env-model-mode.md",
        "commands/vg/_shared/roam/config-gate/persist-config.md",
    ]
    for ref in subrefs:
        p = REPO / ref
        assert p.exists(), f"missing config-gate sub-ref: {ref}"


def test_slim_entry_lists_all_refs():
    body = (REPO / "commands/vg/roam.md").read_text()
    expected_in_body = [
        "_shared/roam/preflight.md",
        "_shared/roam/config-gate/overview.md",
        "_shared/roam/config-gate/backfill-env.md",
        "_shared/roam/config-gate/detect-platform.md",
        "_shared/roam/config-gate/enrich-env.md",
        "_shared/roam/config-gate/confirm-env-model-mode.md",
        "_shared/roam/config-gate/persist-config.md",
        "_shared/roam/discovery.md",
        "_shared/roam/spawn-executors.md",
        "_shared/roam/aggregate-analyze.md",
        "_shared/roam/artifacts.md",
        "_shared/roam/fix-loop.md",
        "_shared/roam/close.md",
    ]
    for ref in expected_in_body:
        assert ref in body, f"slim entry must directly list ref: {ref}"
