"""R6 Task 14: Mobile flow ordering — 5d_mobile_codegen MUST run BEFORE 5c_mobile_flow.

Bug: must_touch_markers in test.md previously listed 5c_mobile_flow BEFORE
5d_mobile_codegen. Stop hook walks markers in declaration order, so the first
/vg:test run tried to execute mobile flow against an empty Maestro directory.
Codegen had not yet produced .maestro.yaml files, so flow exited silently with
"No Maestro flows found" warning AND still touched the marker as done. Stop
hook saw green marker; run reported success with zero actual mobile testing
(false-positive completion).

Fix:
1. Swap order in test.md must_touch_markers — codegen first, flow second.
2. Replace silent-touch in runtime.md empty-flows branch with fail-loud BLOCK
   + actionable error + paired --skip-mobile-flow / --override-reason path.
3. Add --skip-mobile-flow to test.md forbidden_without_override + preflight.md
   FORBIDDEN_FLAGS allowlist.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_MD = REPO_ROOT / "commands/vg/test.md"
RUNTIME_MD = REPO_ROOT / "commands/vg/_shared/test/runtime.md"
PREFLIGHT_MD = REPO_ROOT / "commands/vg/_shared/test/preflight.md"


def _extract_must_touch_markers_block(body: str) -> str:
    """Extract the must_touch_markers: block from test.md frontmatter."""
    # Block starts at "must_touch_markers:" and ends at the next top-level key
    # under runtime_contract (must_emit_telemetry, forbidden_without_override).
    m = re.search(
        r"must_touch_markers:\s*\n(.*?)(?=^\s{2}must_emit_telemetry:|^\s{2}forbidden_without_override:)",
        body,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "Could not locate must_touch_markers: block in test.md frontmatter"
    return m.group(1)


def test_mobile_codegen_listed_before_mobile_flow_in_test_md():
    """test.md must_touch_markers: 5d_mobile_codegen MUST appear before 5c_mobile_flow.

    Stop hook walks markers in declaration order. Reverse order causes
    false-positive completion on first /vg:test run (flow runs against empty
    Maestro dir, prints warning, still touches marker — Stop hook accepts).
    """
    body = TEST_MD.read_text(encoding="utf-8")
    block = _extract_must_touch_markers_block(body)

    # Find the FIRST occurrence of each marker name in declaration order.
    codegen_match = re.search(r'name:\s*"5d_mobile_codegen"', block)
    flow_match = re.search(r'name:\s*"5c_mobile_flow"', block)

    assert codegen_match, "5d_mobile_codegen not found in must_touch_markers"
    assert flow_match, "5c_mobile_flow not found in must_touch_markers"
    assert codegen_match.start() < flow_match.start(), (
        f"R6 Task 14 violation: 5d_mobile_codegen (idx={codegen_match.start()}) must "
        f"appear BEFORE 5c_mobile_flow (idx={flow_match.start()}) in must_touch_markers. "
        f"Reverse order causes Stop hook to walk flow before codegen → empty Maestro "
        f"dir → silent skip → false-positive completion."
    )


def test_runtime_md_empty_flows_branch_fail_loud():
    """runtime.md empty-flows branch must fail-loud (not silent-touch).

    After Task 14 ordering swap, this branch is UNREACHABLE in normal flow
    (codegen runs first). Hitting it now means real error: codegen failed
    silently, flows_dir misconfigured, or --skip-codegen used.
    """
    body = RUNTIME_MD.read_text(encoding="utf-8")
    # Locate the if [ -z "$FLOW_FILES" ]; then block in 5c_mobile_flow step.
    m = re.search(
        r'if\s*\[\s*-z\s*"\$FLOW_FILES"\s*\]\s*;\s*then(.*?)\nfi\b',
        body,
        re.DOTALL,
    )
    assert m, "Could not find empty-flows branch in runtime.md 5c_mobile_flow step"
    branch = m.group(1)

    assert "⛔" in branch, (
        "runtime.md empty-flows branch must use ⛔ (fail-loud BLOCK glyph), "
        "not ⚠ (silent warning). After Task 14 this branch is UNREACHABLE in "
        "normal flow — hitting it = real error."
    )
    assert "5d_mobile_codegen" in branch and "FIRST" in branch, (
        "runtime.md empty-flows branch must explain that 5d_mobile_codegen "
        "runs FIRST (sets operator expectation for fail diagnosis)."
    )


def test_runtime_md_has_skip_mobile_flow_override():
    """runtime.md must offer --skip-mobile-flow override path with paired --override-reason."""
    body = RUNTIME_MD.read_text(encoding="utf-8")
    # Locate empty-flows branch.
    m = re.search(
        r'if\s*\[\s*-z\s*"\$FLOW_FILES"\s*\]\s*;\s*then(.*?)\nfi\b',
        body,
        re.DOTALL,
    )
    assert m, "Could not find empty-flows branch in runtime.md"
    branch = m.group(1)

    assert "--skip-mobile-flow" in branch, (
        "runtime.md empty-flows branch must offer --skip-mobile-flow override path"
    )
    assert "--override-reason" in branch, (
        "runtime.md empty-flows branch must require paired --override-reason "
        "with --skip-mobile-flow (forbidden_without_override contract)"
    )
    # Paired check: both flags referenced in the same conditional.
    assert re.search(
        r'--skip-mobile-flow.*--override-reason|--override-reason.*--skip-mobile-flow',
        branch,
        re.DOTALL,
    ), "runtime.md must check that --skip-mobile-flow and --override-reason appear together"


def test_test_md_frontmatter_has_skip_mobile_flow():
    """test.md forbidden_without_override list MUST include --skip-mobile-flow."""
    body = TEST_MD.read_text(encoding="utf-8")
    # Locate forbidden_without_override: block.
    m = re.search(
        r"forbidden_without_override:\s*\n(.*?)(?=^---|\Z)",
        body,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "Could not find forbidden_without_override: in test.md frontmatter"
    block = m.group(1)
    assert '"--skip-mobile-flow"' in block, (
        "test.md forbidden_without_override must list --skip-mobile-flow — paired "
        "--override-reason enforcement runs through preflight.md FORBIDDEN_FLAGS."
    )


def test_preflight_allowlist_has_skip_mobile_flow():
    """preflight.md FORBIDDEN_FLAGS array MUST include --skip-mobile-flow."""
    body = PREFLIGHT_MD.read_text(encoding="utf-8")
    m = re.search(r"FORBIDDEN_FLAGS=\(([^)]+)\)", body)
    assert m, "Could not find FORBIDDEN_FLAGS array in preflight.md"
    flags = m.group(1)
    assert "--skip-mobile-flow" in flags, (
        f"preflight.md FORBIDDEN_FLAGS must include --skip-mobile-flow. "
        f"Current: {flags!r}"
    )
