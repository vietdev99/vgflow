"""tests/test_field_test_skill_structure.py — skill body structural invariants."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "commands" / "vg" / "field-test.md"
MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "field-test.md"


def _frontmatter(body: str) -> str:
    m = re.match(r"^---\n(.*?)\n---\n", body, re.DOTALL)
    if not m:
        raise AssertionError("no frontmatter found")
    return m.group(1)


def test_skill_exists():
    assert SKILL.is_file()


def test_mirror_byte_identity():
    assert SKILL.read_bytes() == MIRROR.read_bytes()


def test_frontmatter_name_and_description():
    body = SKILL.read_text(encoding="utf-8")
    fm = _frontmatter(body)
    assert re.search(r"^name:\s*vg:field-test\s*$", fm, re.MULTILINE), (
        "frontmatter must declare 'name: vg:field-test'"
    )
    assert re.search(r"^description:\s*.+", fm, re.MULTILINE), (
        "frontmatter must include a description"
    )


def test_argument_hint_no_resume_no_preset():
    body = SKILL.read_text(encoding="utf-8")
    fm = _frontmatter(body)
    arg_hint_match = re.search(r"^argument-hint:\s*\"([^\"]+)\"", fm, re.MULTILINE)
    assert arg_hint_match, "argument-hint must be quoted string"
    hint = arg_hint_match.group(1)
    assert "--resume" not in hint, (
        "v2.1 scope cut: --resume must NOT appear in argument-hint"
    )
    assert "--preset" not in hint, (
        "v2.1 scope cut: --preset enum must NOT appear in argument-hint"
    )


def test_allowed_tools_include_playwright1():
    body = SKILL.read_text(encoding="utf-8")
    fm = _frontmatter(body)
    required = [
        "mcp__playwright1__browser_navigate",
        "mcp__playwright1__browser_evaluate",
        "mcp__playwright1__browser_take_screenshot",
        "mcp__playwright1__browser_snapshot",
        "mcp__playwright1__browser_console_messages",
    ]
    for tool in required:
        assert tool in fm, f"allowed-tools must include {tool}"


def test_must_emit_telemetry_four_events_with_mark_recorded_flag():
    body = SKILL.read_text(encoding="utf-8")
    fm = _frontmatter(body)
    required = [
        "field_test.session_started",
        "field_test.session_stopped",
        "field_test.analysis_completed",
        "field_test.mark_recorded",
    ]
    for ev in required:
        assert ev in fm, f"must_emit_telemetry missing {ev}"
    # mark_recorded must carry required_unless_flag
    pattern = re.compile(
        r'event_type:\s*"field_test\.mark_recorded".*?required_unless_flag:\s*"--allow-zero-marks"',
        re.DOTALL,
    )
    assert pattern.search(fm), (
        "mark_recorded must declare required_unless_flag: --allow-zero-marks"
    )


def test_body_uses_atomic_mkdir_lock_not_echo():
    body = SKILL.read_text(encoding="utf-8")
    assert "mkdir" in body and ".vg/field-test/.active" in body, (
        "v2.1 §3: skill body must use atomic 'mkdir .vg/field-test/.active' lock"
    )
    # Confirm there is no TOCTOU echo-based lock
    forbidden = re.search(r"echo\s+.*>\s*\"?[^\"]*\.active(?!_)", body)
    assert not forbidden, (
        "v2.1 forbids 'echo > .active' lock (TOCTOU race)"
    )


def test_body_uses_browser_evaluate_state_polling():
    body = SKILL.read_text(encoding="utf-8")
    assert "browser_evaluate" in body, "v2.1 §1: skill must poll via browser_evaluate"
    assert "__VG_FT_STATE" in body, "skill must reference overlay state object"
    assert "marks.length" in body, "polling must read marks.length offset"
    assert "reload_epoch" in body, "v2.1 SPA reload: skill must read reload_epoch"


def test_body_documents_spa_reload_epoch_reset():
    body = SKILL.read_text(encoding="utf-8")
    # MUST-4: epoch K→0 (or epoch < last_epoch) → reset last_consumed
    assert ("last_consumed = 0" in body) or ("last_consumed=0" in body), (
        "skill must document last_consumed reset to 0 on SPA full reload"
    )


def test_hard_gate_warns_screenshots_not_redacted():
    body = SKILL.read_text(encoding="utf-8")
    hg = re.search(r"<HARD-GATE>(.*?)</HARD-GATE>", body, re.DOTALL)
    assert hg, "skill must contain <HARD-GATE>...</HARD-GATE> banner"
    hg_text = hg.group(1).lower()
    assert "screenshot" in hg_text and ("not redacted" in hg_text or "NOT redacted".lower() in hg_text), (
        "HARD-GATE banner must warn that screenshots are NOT redacted"
    )


def test_body_references_check_quota_per_iter():
    body = SKILL.read_text(encoding="utf-8")
    assert "check-quota.py" in body, (
        "v2.1 MUST-2: skill body must invoke check-quota.py each poll iter"
    )


def test_body_references_build_bundle_and_analyze():
    body = SKILL.read_text(encoding="utf-8")
    assert "build-bundle.py" in body, "Stop step must invoke build-bundle.py"
    assert "analyze.py" in body, "Analyze step must invoke analyze.py"


def test_body_no_dev_phases_mirror():
    body = SKILL.read_text(encoding="utf-8")
    assert "dev-phases" not in body, (
        "v2.1 scope cut: NO dev-phases/<N>/ mirror for field-test bundles"
    )


def test_body_emits_evidence_manifest_for_field_report_and_bundle():
    """v2.1 / #175: Stop step records evidence-manifest entries for
    FIELD-REPORT.md and bundle manifest.json so downstream consumers can
    verify freshness."""
    body = SKILL.read_text(encoding="utf-8")
    assert "emit-evidence-manifest" in body, (
        "v2.1 / #175 integration: Stop step must emit evidence-manifest entries"
    )


def test_must_touch_markers_lifecycle_complete():
    body = SKILL.read_text(encoding="utf-8")
    fm = _frontmatter(body)
    for marker in ("0_preflight", "5_capture_loop", "6_stop_finalize",
                   "7_analyze", "complete"):
        assert marker in fm, f"must_touch_markers missing {marker!r}"


def test_step1_documents_redact_flag_precedence():
    """I2 fix: Step 1 must document that --redact=<regex> in $ARGUMENTS
    skips the AskUserQuestion prompt for redaction."""
    body = SKILL.read_text(encoding="utf-8")
    # Locate Step 1 block (between "## Step 1" and "## Step 2")
    m = re.search(r"## Step 1:.*?(?=## Step 2:)", body, re.DOTALL)
    assert m, "Step 1 section not found"
    step1 = m.group(0)
    assert "--redact" in step1, "Step 1 must reference --redact flag"
    # Look for precedence wording
    assert "precedence" in step1.lower() or "skip" in step1.lower(), (
        "Step 1 must document --redact precedence over AskUserQuestion"
    )


def test_step7_re_resolves_emit_manifest_variable():
    """I3 fix: Step 7 must re-assign EMIT_MANIFEST to survive subshell isolation
    from Step 6."""
    body = SKILL.read_text(encoding="utf-8")
    m = re.search(r"## Step 7:.*?(?=## Step 8:)", body, re.DOTALL)
    assert m, "Step 7 section not found"
    step7 = m.group(0)
    # Count emit-manifest path assignments in Step 7 — must include the canonical or fallback path
    assert "emit-evidence-manifest.py" in step7
    # Step 7 must assign EMIT_MANIFEST (not just reuse from Step 6)
    assert re.search(r'EMIT_MANIFEST\s*=\s*"', step7), (
        "Step 7 must re-assign EMIT_MANIFEST (subshell-safe)"
    )
