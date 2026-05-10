"""v2.73.0 T11 — update.md slim ceiling."""
from pathlib import Path


def test_update_md_under_slim_ceiling():
    body = Path("commands/vg/update.md").read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    # 676 -> target <= 250 (63%+ reduction). Actual after T6-T10 is ~103 lines.
    assert line_count <= 250, \
        f"v2.73.0 update split target: <= 250 lines (got {line_count})"


def test_shared_update_dir_has_5_files():
    md_files = sorted(Path("commands/vg/_shared/update").glob("*.md"))
    # 5 NEW sub-files: preflight, version-and-changelog, fetch-and-merge,
    # rotate-and-repair, sync-and-report.
    assert len(md_files) >= 5, \
        f"Expected >=5 sub-files in _shared/update/ (got {len(md_files)})"


def test_update_md_routes_to_each_subfile():
    body = Path("commands/vg/update.md").read_text(encoding="utf-8")
    expected = [
        "preflight.md",
        "version-and-changelog.md",
        "fetch-and-merge.md",
        "rotate-and-repair.md",
        "sync-and-report.md",
    ]
    missing = [s for s in expected if f"_shared/update/{s}" not in body]
    assert not missing, f"update.md missing routes: {missing}"
