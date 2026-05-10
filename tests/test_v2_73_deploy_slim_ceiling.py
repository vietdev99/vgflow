"""v2.73.0 T4 — deploy.md slim ceiling."""
from pathlib import Path


def test_deploy_md_under_slim_ceiling():
    body = Path("commands/vg/deploy.md").read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    # 574 -> target <= 200 (65%+ reduction)
    assert line_count <= 200, \
        f"v2.73.0 deploy split target: <= 200 lines (got {line_count})"


def test_shared_deploy_dir_has_5_files():
    md_files = sorted(Path("commands/vg/_shared/deploy").glob("*.md"))
    # 2 existing (overview, per-env-executor-contract) + 3 NEW (preflight, execute, persist-and-close)
    assert len(md_files) >= 5, \
        f"Expected >=5 sub-files (got {len(md_files)})"


def test_deploy_md_routes_to_each_subfile():
    body = Path("commands/vg/deploy.md").read_text(encoding="utf-8")
    expected = ["preflight.md", "execute.md", "persist-and-close.md"]
    missing = [s for s in expected if f"_shared/deploy/{s}" not in body]
    assert not missing, f"deploy.md missing routes: {missing}"
