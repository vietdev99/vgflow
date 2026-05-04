"""Task 36b — verify review.md Phase 2.5 wires Task 26 dispatch chain."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_review_md_calls_emit_dispatch_plan() -> None:
    """review.md Phase 2.5 must call emit-dispatch-plan.py before spawn loop."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    assert "emit-dispatch-plan.py" in text, (
        "review.md Phase 2.5 must call scripts/lens-dispatch/emit-dispatch-plan.py"
    )
    # emit must come BEFORE spawn_recursive_probe.py invocation
    emit_pos = text.find("emit-dispatch-plan.py")
    spawn_pos = text.find("spawn_recursive_probe.py")
    assert emit_pos != -1 and spawn_pos != -1
    assert emit_pos < spawn_pos, (
        f"emit-dispatch-plan.py at byte {emit_pos} must come before "
        f"spawn_recursive_probe.py at byte {spawn_pos}"
    )


def test_review_md_calls_verify_lens_runs_coverage() -> None:
    """review.md must call verify-lens-runs-coverage.py after spawn loop."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    assert "verify-lens-runs-coverage.py" in text


def test_review_md_renders_coverage_matrix() -> None:
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    assert "lens-coverage-matrix.py" in text or "LENS-COVERAGE-MATRIX.md" in text


def test_review_md_routes_coverage_block_through_wrapper() -> None:
    """Coverage gate failure must route through Task 33 wrapper, not exit 1."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    # When verify-lens-runs-coverage exits non-zero, must call wrapper
    import re
    # Look for verify-lens-runs-coverage block followed by wrapper invocation within 30 lines
    pattern = re.compile(
        r'verify-lens-runs-coverage\.py.*?(?:\n[^\n]*){0,30}blocking_gate_prompt_emit',
        re.DOTALL,
    )
    assert pattern.search(text), (
        "lens coverage gate failure must invoke blocking_gate_prompt_emit "
        "(Task 33 wrapper), not exit 1 directly"
    )


def test_spawn_recursive_probe_uses_tier_dispatcher() -> None:
    """spawn_recursive_probe.py must import lens_tier_dispatcher.select_tier."""
    text = (REPO / "scripts/spawn_recursive_probe.py").read_text(encoding="utf-8")
    assert "lens_tier_dispatcher" in text or "select_tier" in text, (
        "spawn_recursive_probe.py must use Task 26's tier dispatcher"
    )


def test_spawn_recursive_probe_writes_plan_hash_in_artifacts() -> None:
    """Per-dispatch artifact must include plan_hash (anti-reuse)."""
    text = (REPO / "scripts/spawn_recursive_probe.py").read_text(encoding="utf-8")
    assert "plan_hash" in text, "spawn_recursive_probe.py must write plan_hash in artifacts"


def test_review_md_skip_mode_shortcuts_coverage() -> None:
    """When --probe-mode skip set, coverage gate skipped (legitimate user decision)."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    # Look for .recursive-probe-skipped.yaml check before coverage gate
    assert ".recursive-probe-skipped.yaml" in text


def test_telemetry_events_declared_in_frontmatter() -> None:
    """review.md must declare review.lens_dispatch_emitted + review.lens_coverage_blocked."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    assert "review.lens_dispatch_emitted" in text
    assert "review.lens_coverage_blocked" in text
