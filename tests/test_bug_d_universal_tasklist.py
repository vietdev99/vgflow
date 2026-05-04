"""Bug D 2026-05-04 — universal tasklist enforcement across all VG mainline flows.

Sếp dogfood discovery: /vg:review 4.1 ran without creating TodoWrite tasklist;
audit showed enforcement was applied to review only, not blueprint/build/test/
specs/roam etc. This test file pins the universal contract:

1. STATIC slim-entry checks — every mainline command's slim entry declares
   TodoWrite as an allowed tool, includes a HARD-GATE block, and lists
   `{cmd}.native_tasklist_projected` in must_emit_telemetry.

2. STATIC preflight ref checks — every mainline preflight has an explicit
   `vg-orchestrator tasklist-projected --adapter` bash call, not just
   instruction text (which AI was previously skipping).

3. INTEGRATION universal Stop-hook gate — cmd_run_complete refuses to PASS
   when mainline command's run lacks the projection event, even if the
   per-command runtime_contract forgot to declare it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMANDS_DIR = REPO_ROOT / "commands" / "vg"
SHARED_DIR = COMMANDS_DIR / "_shared"

# Mainline commands under universal Bug D contract. Excluded: amend, polish,
# debug — short-lived auxiliary flows where tasklist projection is optional.
MAINLINE_CMDS = [
    "specs", "scope", "blueprint", "build",
    "review", "test", "accept", "deploy", "roam",
]

# Commands that route their tasklist projection through a _shared/<cmd>/preflight.md
# (multi-step decomposed flows). Other commands (specs, scope, deploy, roam)
# keep the projection inline in the slim entry.
PREFLIGHT_REF_CMDS = ["blueprint", "build", "test", "accept"]


# ── STATIC slim-entry checks ──────────────────────────────────────────────


@pytest.mark.parametrize("cmd", MAINLINE_CMDS)
def test_slim_entry_has_todowrite_allowed_tool(cmd: str) -> None:
    """Every mainline slim entry must list TodoWrite under allowed-tools."""
    entry = COMMANDS_DIR / f"{cmd}.md"
    text = entry.read_text(encoding="utf-8")
    # Frontmatter spans from line 1 to first '---' closer.
    fm_end = text.index("\n---\n", 4)
    frontmatter = text[:fm_end]
    assert "TodoWrite" in frontmatter, (
        f"{cmd}.md frontmatter does not list TodoWrite as allowed-tool — "
        f"AI cannot project tasklist; Bug D will recur."
    )


@pytest.mark.parametrize("cmd", MAINLINE_CMDS)
def test_slim_entry_declares_native_tasklist_projected_telemetry(cmd: str) -> None:
    """must_emit_telemetry must include `{cmd}.native_tasklist_projected`."""
    entry = COMMANDS_DIR / f"{cmd}.md"
    text = entry.read_text(encoding="utf-8")
    expected = f'event_type: "{cmd}.native_tasklist_projected"'
    assert expected in text, (
        f"{cmd}.md must declare {expected} in must_emit_telemetry — "
        f"otherwise run-complete cannot enforce projection."
    )


@pytest.mark.parametrize("cmd", MAINLINE_CMDS)
def test_slim_entry_has_tasklist_enforcement_language(cmd: str) -> None:
    """Every mainline slim entry must explicitly reference TodoWrite together
    with enforcement language (one of: PreToolUse, step-active, Stop hook,
    PostToolUse, native_tasklist_projected) somewhere in the file. The
    proximity check ensures the wording isn't decorative — TodoWrite must
    appear close to the enforcement mechanism, not 50KB away in unrelated
    prose."""
    entry = COMMANDS_DIR / f"{cmd}.md"
    text = entry.read_text(encoding="utf-8")
    assert "TodoWrite" in text, (
        f"{cmd}.md does not mention TodoWrite at all — Bug D regression."
    )
    enforcement_keywords = (
        "PreToolUse", "step-active", "Stop hook",
        "native_tasklist_projected", "PostToolUse",
    )
    # Find the densest TodoWrite mention with enforcement keyword within 1.5KB
    # window in either direction (≈ one screenful of context).
    found = False
    pos = -1
    while True:
        pos = text.find("TodoWrite", pos + 1)
        if pos == -1:
            break
        window = text[max(0, pos - 1500): pos + 1500]
        if any(kw in window for kw in enforcement_keywords):
            found = True
            break
    assert found, (
        f"{cmd}.md mentions TodoWrite but never within 1.5KB of any "
        f"enforcement keyword {enforcement_keywords}. Decorative mentions "
        f"don't prevent Bug D — wording must explain why AI cannot skip."
    )


# ── STATIC preflight ref checks ──────────────────────────────────────────


@pytest.mark.parametrize("cmd", PREFLIGHT_REF_CMDS)
def test_preflight_has_explicit_tasklist_projected_bash_call(cmd: str) -> None:
    """Bug D root cause: blueprint/build had instruction text only, no bash
    call. Hook still blocked at PreToolUse but `{cmd}.native_tasklist_projected`
    event never fired → run-complete couldn't audit it. Fix: every preflight
    must contain an EXECUTABLE `vg-orchestrator tasklist-projected --adapter`
    bash invocation."""
    pre = SHARED_DIR / cmd / "preflight.md"
    if not pre.exists():
        pytest.skip(f"{pre} does not exist for this command")
    text = pre.read_text(encoding="utf-8")
    # Match line: `vg-orchestrator tasklist-projected \` (continuation) OR
    # `vg-orchestrator tasklist-projected --adapter ...`
    has_bash_call = (
        "vg-orchestrator tasklist-projected \\" in text
        or "vg-orchestrator tasklist-projected --adapter" in text
        or "vg-orchestrator tasklist-projected" in text
        and "--adapter" in text
    )
    assert has_bash_call, (
        f"{pre} lacks executable `vg-orchestrator tasklist-projected --adapter ...` "
        f"bash call. Instruction-text-only is insufficient — AI was empirically "
        f"skipping the call (Bug D dogfood evidence 2026-05-04)."
    )


def test_specs_md_has_create_task_tracker_step() -> None:
    """specs.md was the worst Bug D gap: no TodoWrite, no create_task_tracker
    step. Pin: specs.md MUST contain the create_task_tracker step block."""
    text = (COMMANDS_DIR / "specs.md").read_text(encoding="utf-8")
    assert '<step name="create_task_tracker">' in text, (
        "specs.md missing create_task_tracker step — Bug D regression risk."
    )
    assert "tasklist-projected" in text, (
        "specs.md missing tasklist-projected reference — Bug D regression risk."
    )


def test_specs_md_lists_create_task_tracker_in_must_touch_markers() -> None:
    """specs.md runtime_contract must require the create_task_tracker marker."""
    text = (COMMANDS_DIR / "specs.md").read_text(encoding="utf-8")
    assert '"create_task_tracker"' in text or '- "create_task_tracker"' in text, (
        "specs.md must_touch_markers must include create_task_tracker."
    )


# ── INTEGRATION: universal Stop-hook gate (Task 92) ──────────────────────


def test_orchestrator_main_has_universal_tasklist_projection_gate() -> None:
    """The defense-in-depth gate in cmd_run_complete must list all mainline
    commands. If a future command is added without per-command telemetry
    declaration, this universal check catches it."""
    main = (REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py").read_text(
        encoding="utf-8"
    )
    assert "MAINLINE_CMDS_FOR_TASKLIST" in main, (
        "Universal Bug D gate missing from .claude/scripts/vg-orchestrator/__main__.py"
    )
    # Verify the gate covers exactly the mainline set.
    for cmd in MAINLINE_CMDS:
        assert f'"vg:{cmd}"' in main, (
            f"MAINLINE_CMDS_FOR_TASKLIST missing vg:{cmd} — gate would not "
            f"catch a future contract that forgets to declare the projection event."
        )
    assert "tasklist_projection_required" in main, (
        "Violation type 'tasklist_projection_required' missing — "
        "block message will not be specific to Bug D."
    )


def test_orchestrator_source_copy_has_universal_tasklist_projection_gate() -> None:
    """Mirror copy at scripts/vg-orchestrator must stay in sync with the
    canonical .claude/ copy. Otherwise dev-time tests pass but installed
    runtime lacks the gate."""
    main = (REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py").read_text(
        encoding="utf-8"
    )
    assert "MAINLINE_CMDS_FOR_TASKLIST" in main, (
        "Universal Bug D gate missing from scripts/vg-orchestrator/__main__.py "
        "(source copy diverged from .claude/ canonical)"
    )
