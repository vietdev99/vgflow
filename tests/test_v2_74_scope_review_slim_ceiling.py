"""v2.74.0 T4 — ceiling test for slim scope-review.md routing entry."""
from pathlib import Path


def test_scope_review_md_under_slim_ceiling():
    body = Path("commands/vg/scope-review.md").read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    # 670 -> target <= 200
    assert line_count <= 200, f"got {line_count}"


def test_shared_scope_review_dir_has_3_files():
    md_files = sorted(Path("commands/vg/_shared/scope-review").glob("*.md"))
    assert len(md_files) >= 3


def test_scope_review_md_routes_to_each_subfile():
    body = Path("commands/vg/scope-review.md").read_text(encoding="utf-8")
    expected = ["preflight.md", "cross-ref-review-write.md", "resolve-and-close.md"]
    missing = [s for s in expected if f"_shared/scope-review/{s}" not in body]
    assert not missing
