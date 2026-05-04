from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_build_uses_shared_design_ref_check_before_executor_spawn() -> None:
    build = _read("commands/vg/build.md")
    pre_executor_idx = build.find("design-ref-check.py")
    spawn_idx = build.find("### 8c: Spawn executor per task in wave")

    assert pre_executor_idx > 0
    assert spawn_idx > pre_executor_idx
    assert "DESIGN_REF_STALE_WAVE" in build
    assert "rm -rf \"${PHASE_DIR}/.wave-tasks\"" in build
    assert "build.design-ref-resolve" in build


def test_scaffold_writes_to_resolver_phase_design_dir() -> None:
    scaffold = _read("commands/vg/design-scaffold.md")

    assert "design-path-resolver.sh" in scaffold
    assert "vg_resolve_design_dir \"$PHASE_DIR\" phase" in scaffold
    assert "${PHASE_DIR}/design/<slug>" in scaffold


def test_review_l4_uses_shared_design_ref_resolver() -> None:
    review = _read("commands/vg/review.md")

    assert "resolve_design_assets" in review
    assert "parse_config_file" in review
    assert "DF_BASELINE_DIR" not in review
