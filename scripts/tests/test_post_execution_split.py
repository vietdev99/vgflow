"""L2 skill-split regression — assert post-execution-overview.md split into 3 sub-refs.

Anthropic Skill progressive disclosure baseline: keep skill body < 200 lines,
push detail into refs on demand. The pre-split post-execution-overview.md
was 1034 lines (top context offender for /vg:build STEP 5).

This test pins:
- 3 sub-refs exist (overview slim, spawn, validation)
- Slim overview < 250 lines
- R6 Task 3 single-spawn HARD-GATE preserved
- R2 round-2 BUILD-LOG validation contract preserved
- L4a deterministic phase-level gates preserved
- build.md STEP 5 routing intact
- Step ID 9_post_execution preserved (Stop hook + tasklist read this)
- Mirror parity with .claude/commands/vg/_shared/build/
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUILD_REFS = REPO / "commands" / "vg" / "_shared" / "build"
OVERVIEW = BUILD_REFS / "post-execution-overview.md"
SPAWN = BUILD_REFS / "post-execution-spawn.md"
VALIDATION = BUILD_REFS / "post-execution-validation.md"
BUILD_MD = REPO / "commands" / "vg" / "build.md"
MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "build"


def test_three_sub_refs_exist() -> None:
    """All 3 post-execution sub-refs exist on disk."""
    for path in (OVERVIEW, SPAWN, VALIDATION):
        assert path.exists(), f"missing sub-ref: {path}"
        assert path.stat().st_size > 100, f"{path} suspiciously short"


def test_overview_is_slim() -> None:
    """Slim overview <= 250 lines per Anthropic Skill body baseline."""
    lines = OVERVIEW.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 250, (
        f"post-execution-overview.md = {len(lines)} lines, exceeds 250-line slim cap. "
        "Pre-split file was 1034 lines (top context offender)."
    )


def test_overview_has_hard_gate_block() -> None:
    """HARD-GATE preserved verbatim in slim overview — R6 Task 3 single-spawn
    enforcement is critical and MUST stay in the entry file."""
    text = OVERVIEW.read_text(encoding="utf-8")
    assert "<HARD-GATE>" in text and "</HARD-GATE>" in text, (
        "HARD-GATE block dropped from post-execution-overview.md slim overview"
    )
    assert "vg-build-post-executor" in text, (
        "post-executor subagent name dropped from HARD-GATE"
    )
    assert "Single Agent() call" in text or "single-spawn" in text or "ONE" in text, (
        "single-spawn imperative dropped from HARD-GATE"
    )


def test_overview_references_both_sub_refs() -> None:
    """Slim overview MUST reference both sub-refs by name."""
    text = OVERVIEW.read_text(encoding="utf-8")
    assert "post-execution-spawn.md" in text, "overview missing route to spawn sub-ref"
    assert "post-execution-validation.md" in text, "overview missing route to validation sub-ref"


def test_r6_task3_single_spawn_guard_preserved() -> None:
    """R6 Task 3 spawn-guard reference must exist in the split.
    `scripts/vg-agent-spawn-guard.py` enforces single-spawn for
    `vg-build-post-executor` — a 2nd Agent() call is hard-denied.
    Counter persisted at .vg/runs/<run_id>/.post-executor-spawns.json."""
    combined = (
        OVERVIEW.read_text(encoding="utf-8")
        + SPAWN.read_text(encoding="utf-8")
    )
    assert "vg-agent-spawn-guard.py" in combined or "spawn-guard" in combined, (
        "R6 Task 3 spawn-guard reference dropped from post-execution split"
    )
    assert "post-executor-spawns.json" in combined or "single-spawn" in combined, (
        "R6 Task 3 spawn counter / single-spawn language dropped"
    )


def test_r2_buildlog_validation_contract_preserved() -> None:
    """R2 round-2 BUILD-LOG layer enforcement keys (closes A4/E2/C5 drift)
    must stay in the validation sub-ref.

    Required keys: build_log_path, build_log_index_path, build_log_sha256,
    build_log_sub_files. Marker write WITHOUT this validation is a HARD VIOLATION.
    """
    text = VALIDATION.read_text(encoding="utf-8")
    for key in (
        "build_log_path",
        "build_log_index_path",
        "build_log_sha256",
        "build_log_sub_files",
        "summary_sha256",
        "gates_passed",
    ):
        assert key in text, (
            f"R2 round-2 BUILD-LOG contract key '{key}' dropped from validation sub-ref"
        )


def test_l4a_gates_preserved() -> None:
    """L4a deterministic phase-level gates (FE→BE call graph, contract shape,
    spec drift) MUST live in validation sub-ref."""
    text = VALIDATION.read_text(encoding="utf-8")
    for marker in ("L4a-i", "L4a-ii", "L4a-iii"):
        assert marker in text, f"L4a gate '{marker}' dropped from validation sub-ref"
    for script in (
        "verify-fe-be-call-graph.py",
        "verify-contract-shape.py",
        "verify-spec-drift.py",
    ):
        assert script in text, f"L4a validator script '{script}' dropped"


def test_step_marker_id_preserved() -> None:
    """Step ID `9_post_execution` is the Stop hook + tasklist contract.
    The marker write MUST exist somewhere in the split."""
    combined = (
        OVERVIEW.read_text(encoding="utf-8")
        + SPAWN.read_text(encoding="utf-8")
        + VALIDATION.read_text(encoding="utf-8")
    )
    assert "9_post_execution" in combined, (
        "Step ID '9_post_execution' dropped from post-execution split — "
        "Stop hook validates this against must_touch_markers contract"
    )
    assert "9_post_execution.done" in combined, (
        "9_post_execution.done marker write dropped"
    )


def test_build_md_step5_routing_intact() -> None:
    """commands/vg/build.md STEP 5 must still route to post-execution-overview.md."""
    text = BUILD_MD.read_text(encoding="utf-8")
    assert "_shared/build/post-execution-overview.md" in text, (
        "build.md no longer references post-execution-overview.md — STEP 5 routing broken"
    )
    assert "STEP 5" in text, "STEP 5 heading dropped from build.md"
    assert "vg-build-post-executor" in text, "post-executor subagent reference dropped"


def test_mirror_parity() -> None:
    """`.claude/commands/vg/_shared/build/` mirror MUST match canonical refs
    after split (sync.sh / install.sh deploy from this mirror)."""
    for src in (OVERVIEW, SPAWN, VALIDATION):
        mirror_path = MIRROR / src.name
        assert mirror_path.exists(), f"mirror missing: {mirror_path}"
        assert (
            mirror_path.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
        ), f"mirror drift: {mirror_path} vs {src}"


def test_pre_spawn_checklist_steps_in_spawn_ref() -> None:
    """Pre-spawn checklist Steps 1-11 must live in post-execution-spawn.md."""
    text = SPAWN.read_text(encoding="utf-8")
    for step in (
        "Step 1 — Aggregate per-wave results",
        "Step 2 — UX gates",
        "Step 3 — Cross-phase ripple",
        "Step 9 — VG-native State Update",
        "Step 10 — Per-task fingerprint existence",
        "Step 11 — Build subagent envelope inputs",
    ):
        assert step in text, f"pre-spawn checklist '{step}' dropped from spawn sub-ref"
