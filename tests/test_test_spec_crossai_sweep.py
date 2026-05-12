"""tests/test_test_spec_crossai_sweep.py — Option B+A CrossAI sweep wiring."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_SPEC_MD = REPO_ROOT / "commands" / "vg" / "test-spec.md"
TEST_SPEC_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "test-spec.md"


def _frontmatter(body: str) -> str:
    m = re.match(r"^---\n(.*?)\n---\n", body, re.DOTALL)
    assert m
    return m.group(1)


def test_argument_hint_lists_crossai_flags():
    body = TEST_SPEC_MD.read_text(encoding="utf-8")
    fm = _frontmatter(body)
    arg = re.search(r"^argument-hint:\s*\"([^\"]+)\"", fm, re.MULTILINE).group(1)
    assert "--crossai-review" in arg, "argument-hint must list --crossai-review"
    assert "--no-crossai-review" in arg, "argument-hint must list --no-crossai-review"


def test_must_touch_markers_include_crossai_sweep():
    body = TEST_SPEC_MD.read_text(encoding="utf-8")
    fm = _frontmatter(body)
    assert "crossai_sweep" in fm, "must_touch_markers must include crossai_sweep step"


def test_must_emit_telemetry_includes_crossai_events():
    body = TEST_SPEC_MD.read_text(encoding="utf-8")
    fm = _frontmatter(body)
    # CrossAI events: skipped, started, completed (with verdict in payload)
    assert "test_spec.crossai_sweep_skipped" in fm or \
           "test_spec.crossai_skipped" in fm, "must declare crossai_skipped event"
    assert "test_spec.crossai_completed" in fm, "must declare crossai_completed event"


def test_body_documents_conditional_auto_trigger():
    """Option B: auto-fire CrossAI when goals are mutation/multi-actor/realtime/
    financial, lifecycle-depth WARN, or profile in high-stakes set."""
    body = TEST_SPEC_MD.read_text(encoding="utf-8")
    # Must reference at least one auto-trigger condition
    keywords = ("mutation", "multi-actor", "realtime", "financial", "high-stakes")
    matches = [k for k in keywords if k.lower() in body.lower()]
    assert len(matches) >= 2, (
        f"body must document conditional auto-trigger keywords; found only {matches}"
    )


def test_body_documents_flag_precedence():
    """--no-crossai-review > --crossai-review > auto-trigger > skip"""
    body = TEST_SPEC_MD.read_text(encoding="utf-8")
    assert "--no-crossai-review" in body, "skip flag documented"
    assert "--crossai-review" in body, "force flag documented"
    # Both flags must reference precedence handling
    body_lower = body.lower()
    assert "precedence" in body_lower or "override" in body_lower or "force" in body_lower, (
        "body must explain flag precedence"
    )


def test_body_invokes_crossai_invoke_shared():
    """Uses the same shared crossai-invoke.md pattern as blueprint/verify.md."""
    body = TEST_SPEC_MD.read_text(encoding="utf-8")
    assert "crossai-invoke" in body, "must delegate to _shared/crossai-invoke.md"
    # Required env vars per blueprint pattern
    for env_var in ("CONTEXT_FILE", "OUTPUT_DIR", "LABEL"):
        assert env_var in body, f"crossai-invoke contract requires {env_var}"
    # Verdict handling
    assert "CROSSAI_VERDICT" in body, "must consume CROSSAI_VERDICT from invoker"


def test_body_handles_all_4_verdicts():
    """Must handle pass / flag / block / inconclusive verdicts."""
    body = TEST_SPEC_MD.read_text(encoding="utf-8")
    for verdict in ("pass", "flag", "block", "inconclusive"):
        assert verdict in body.lower(), f"verdict '{verdict}' branch missing"


def test_body_writes_crossai_summary_artifact():
    """Output to TEST-SPEC-CROSSAI.md so review can consume."""
    body = TEST_SPEC_MD.read_text(encoding="utf-8")
    assert "TEST-SPEC-CROSSAI.md" in body or \
           "${PHASE_DIR}/crossai/" in body, (
        "CrossAI output must be persisted for review consumption"
    )


def test_crossai_sweep_runs_before_complete():
    """The new step must be ordered before 4_complete."""
    body = TEST_SPEC_MD.read_text(encoding="utf-8")
    fm = _frontmatter(body)
    markers_block = re.search(
        r"must_touch_markers:\s*\n((?:\s+-\s+\"?[\w_]+\"?\s*\n)+)", fm
    )
    assert markers_block, "must_touch_markers block parse fail"
    order = re.findall(r"-\s+\"?([\w_]+)\"?", markers_block.group(1))
    assert "crossai_sweep" in " ".join(order), "crossai_sweep marker missing"
    # crossai_sweep must come BEFORE 4_complete
    crossai_idx = next(i for i, m in enumerate(order) if "crossai" in m)
    complete_idx = next(i for i, m in enumerate(order) if "complete" in m and "crossai" not in m)
    assert crossai_idx < complete_idx, (
        f"crossai_sweep (idx {crossai_idx}) must come before complete (idx {complete_idx})"
    )


def test_mirror_byte_identical():
    assert TEST_SPEC_MD.read_bytes() == TEST_SPEC_MIRROR.read_bytes(), \
        "test-spec.md mirror diverged"
