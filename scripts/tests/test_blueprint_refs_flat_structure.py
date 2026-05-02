from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_no_nested_subdirs():
    base = REPO / "commands/vg/_shared/blueprint"
    for child in base.iterdir():
        assert not child.is_dir(), (
            f"nested subdir found: {child} — Codex fix #4 requires FLAT structure "
            f"(1-level refs, no plan/overview.md chains)"
        )
