"""v2.71.0 T6 — project.md slim ceiling."""
from pathlib import Path


def test_project_md_under_slim_ceiling():
    """After full split, project.md should be slim routing + frontmatter only."""
    body = Path("commands/vg/project.md").read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    # Original 1590 lines → split target ≤ 600 (60%+ reduction)
    assert line_count <= 600, \
        f"v2.71.0 split target: project.md ≤ 600 lines (got {line_count})"


def test_shared_project_dir_has_5_files():
    project_dir = Path("commands/vg/_shared/project")
    md_files = sorted(project_dir.glob("*.md"))
    assert len(md_files) >= 5, \
        f"v2.71.0 split target: ≥5 sub-files in _shared/project/ (got {len(md_files)})"


def test_project_md_routes_to_each_subfile():
    body = Path("commands/vg/project.md").read_text(encoding="utf-8")
    expected_subfiles = [
        "preflight.md", "routing.md", "first-time-rounds.md",
        "update-modes.md", "migrate-and-init.md",
    ]
    missing = [s for s in expected_subfiles if f"_shared/project/{s}" not in body]
    assert not missing, f"project.md missing routes: {missing}"
