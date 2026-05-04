"""
OHOK Batch 1 — specs.md runtime_contract + enforcement.

specs.md used to be 100% performative (zero runtime_contract, zero markers,
zero validators). Batch 1 added:
- runtime_contract frontmatter with 8 markers + 2 telemetry events
- parse_args phase-exists bash gate (grep ROADMAP.md || exit 1)
- generate_draft USER_APPROVAL bash gate (exit 2 if not approve)
- load_context step removed (inlined as process preamble)

These tests lock the contract in place so future refactor can't silently
loosen enforcement.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "vg-orchestrator"))

import contracts  # type: ignore  # noqa: E402


SPECS_MD = (Path(__file__).resolve().parents[2]
            / "commands" / "vg" / "specs.md")


def _read_specs_full() -> str:
    """Read slim entry + all refs concatenated.

    R6 Task 11: VG harness moved to slim entry pattern — `commands/vg/specs.md`
    is short routing-only, and step bodies live in `commands/vg/_shared/specs/*.md`.
    Tests that parse only the slim entry miss step bodies in refs (false-pass).
    Same pattern as test_review_tasklist_projection.py fixed in R3.
    """
    repo = Path(__file__).resolve().parents[2]
    body = (repo / "commands/vg/specs.md").read_text(encoding="utf-8")
    refs_dir = repo / "commands/vg/_shared/specs"
    if refs_dir.is_dir():
        for ref_path in sorted(refs_dir.glob("**/*.md")):
            body += "\n\n# === REF: " + str(ref_path.relative_to(repo)) + " ===\n\n"
            body += ref_path.read_text(encoding="utf-8")
    return body


@pytest.fixture(scope="module")
def specs_text() -> str:
    assert SPECS_MD.exists(), f"specs.md missing at {SPECS_MD}"
    return _read_specs_full()


# ═══════════════════════════ Contract frontmatter ═══════════════════════════

def test_specs_has_runtime_contract(specs_text):
    """specs.md MUST declare runtime_contract — was 100% performative before Batch 1."""
    contract = contracts.parse("vg:specs")
    assert contract is not None, "runtime_contract parse failed"
    assert "must_write" in contract
    assert "must_touch_markers" in contract
    assert "must_emit_telemetry" in contract


def test_specs_must_write_includes_SPECS_and_interface_standards(specs_text):
    contract = contracts.parse("vg:specs")
    must_write = contracts.normalize_must_write(contract.get("must_write") or [])
    paths = [item["path"] for item in must_write]
    assert any("SPECS.md" in p for p in paths), (
        f"must_write missing SPECS.md: {paths}"
    )
    assert any("INTERFACE-STANDARDS.md" in p for p in paths), (
        f"must_write missing INTERFACE-STANDARDS.md: {paths}"
    )
    assert any("INTERFACE-STANDARDS.json" in p for p in paths), (
        f"must_write missing INTERFACE-STANDARDS.json: {paths}"
    )


def test_specs_contract_lists_all_8_markers(specs_text):
    """Every step in body must appear in must_touch_markers."""
    contract = contracts.parse("vg:specs")
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    names = [m["name"] for m in markers]

    # Step body declares these 8 steps (after removing load_context A1)
    expected = {
        "parse_args", "check_existing", "choose_mode",
        "guided_questions", "generate_draft", "write_specs",
        "write_interface_standards", "commit_and_next",
    }
    actual = set(names)
    missing = expected - actual
    extra = actual - expected
    assert not missing, f"markers missing from contract: {missing}"
    assert not extra, f"contract has phantom markers not in body: {extra}"


def test_specs_guided_questions_is_waivable_in_auto_mode(specs_text):
    """--auto skips guided_questions — marker must be waived, not block."""
    contract = contracts.parse("vg:specs")
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    gq = next((m for m in markers if m["name"] == "guided_questions"), None)
    assert gq is not None, "guided_questions marker missing"
    assert gq["severity"] == "warn", (
        f"guided_questions should be severity=warn (auto mode skips it), got {gq['severity']}"
    )
    assert gq["required_unless_flag"] == "--auto", (
        f"guided_questions should be waived by --auto, got {gq['required_unless_flag']}"
    )


def test_specs_emits_started_and_approved_events(specs_text):
    contract = contracts.parse("vg:specs")
    telemetry = contracts.normalize_telemetry(
        contract.get("must_emit_telemetry") or []
    )
    event_types = [t["event_type"] for t in telemetry]
    assert "specs.started" in event_types
    assert "specs.approved" in event_types


# ═══════════════════════════ Step body enforcement ═══════════════════════════

def test_parse_args_has_roadmap_grep_gate(specs_text):
    """B2: parse_args must have bash grep vs ROADMAP.md with exit 1 — was prose fail-fast."""
    # Extract parse_args step block
    match = re.search(
        r'<step name="parse_args">(.+?)</step>',
        specs_text, re.DOTALL,
    )
    assert match, "parse_args step missing"
    block = match.group(1)

    # Must have grep + exit 1 path
    assert re.search(r'grep.*ROADMAP.*exit 1', block, re.DOTALL), (
        "parse_args: missing grep ROADMAP → exit 1 gate"
    )
    # Must check PHASE_NUMBER not empty
    assert re.search(r'\[\s*-z\s*"\${PHASE_NUMBER:-}"', block), (
        "parse_args: missing empty PHASE_NUMBER check"
    )


def test_generate_draft_has_approval_bash_gate(specs_text):
    """B3: generate_draft must have case $USER_APPROVAL ... approve|edit|discard."""
    match = re.search(
        r'<step name="generate_draft">(.+?)</step>',
        specs_text, re.DOTALL,
    )
    assert match, "generate_draft step missing"
    block = match.group(1)

    assert 'USER_APPROVAL' in block, "generate_draft: missing USER_APPROVAL reference"
    assert re.search(r'case\s+"\${USER_APPROVAL', block), (
        "generate_draft: missing case $USER_APPROVAL switch"
    )
    assert re.search(r'\bapprove\)', block), "generate_draft: missing approve branch"
    assert re.search(r'\bedit\)', block), "generate_draft: missing edit branch"
    assert re.search(r'\bdiscard\)', block), "generate_draft: missing discard branch"

    # Must exit 2 on non-approve — silent approval forbidden
    assert re.search(r'exit 2', block), (
        "generate_draft: missing exit 2 on unapproved path"
    )


def test_generate_draft_emits_approved_or_rejected_event(specs_text):
    """Approval decisions must be telemetry-visible."""
    match = re.search(
        r'<step name="generate_draft">(.+?)</step>',
        specs_text, re.DOTALL,
    )
    block = match.group(1)
    assert 'emit-event "specs.approved"' in block
    assert 'emit-event "specs.rejected"' in block


# ═══════════════════════════ A1: load_context removed ═══════════════════════════

def test_load_context_step_removed(specs_text):
    """A1: load_context was pure documentation — should be process preamble now, not <step>."""
    # No <step name="load_context"> declaration
    assert not re.search(r'<step name="load_context">', specs_text), (
        "load_context still declared as step — A1 requires inline preamble"
    )
    # But the preamble mention still exists for documentation
    assert "Context loading" in specs_text or "load context" in specs_text.lower()


# ═══════════════════════════ Marker file emission ═══════════════════════════

def test_all_8_steps_emit_markers(specs_text):
    """Every <step name="X"> must have touch .step-markers/X.done in body."""
    step_names = re.findall(r'<step name="([^"]+)">', specs_text)
    for name in step_names:
        # Extract step block
        match = re.search(
            rf'<step name="{re.escape(name)}">(.+?)</step>',
            specs_text, re.DOTALL,
        )
        block = match.group(1)
        assert f'{name}.done' in block, (
            f'step "{name}" missing `touch .step-markers/{name}.done` emit'
        )


# ═══════════════════════════ Run-complete validation hook ═══════════════════════════

def test_commit_and_next_calls_run_complete(specs_text):
    """Final step must trigger orchestrator run-complete so contract is validated."""
    match = re.search(
        r'<step name="commit_and_next">(.+?)</step>',
        specs_text, re.DOTALL,
    )
    block = match.group(1)
    assert 'vg-orchestrator run-complete' in block
    assert 'RUN_RC' in block, "missing rc check after run-complete"
    assert 'exit $RUN_RC' in block, "missing exit on run-complete failure"


def test_specs_generates_interface_standards_before_commit(specs_text):
    step = re.search(
        r'<step name="write_interface_standards">(.+?)</step>',
        specs_text,
        re.DOTALL,
    )
    assert step, "write_interface_standards step missing"
    block = step.group(1)
    assert "generate-interface-standards.py" in block
    assert "verify-interface-standards.py" in block
    assert "--no-scan-source" in block
    commit = re.search(
        r'<step name="commit_and_next">(.+?)</step>',
        specs_text,
        re.DOTALL,
    ).group(1)
    assert "INTERFACE-STANDARDS.md" in commit
    assert "INTERFACE-STANDARDS.json" in commit
