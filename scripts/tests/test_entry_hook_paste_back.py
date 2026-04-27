"""
test_entry_hook_paste_back.py — v2.8.6 hotfix coverage for vg-entry-hook
phantom run-start gap.

Pins:
1. /vg:cmd at first non-empty line → register run.
2. /vg:cmd embedded in prose body → skip (NOT at first line).
3. /vg:cmd in middle of long IDE-context prompt → skip.
4. <system-reminder> tags in prompt → paste-back detected, skip.
5. Vietnamese imperative prefix ("chạy /vg:build", "vậy chạy /vg:scope") → skip.
6. Diff hunk markers (--- a/, +++ b/) → paste-back detected.
7. Long prompt (>2KB) with /vg:cmd + Windows abs path → paste-back detected.
8. Stop-hook feedback markers still trigger paste-back (regression).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO_ROOT / "scripts" / "vg-entry-hook.py"


def _load_hook(repo_root: Path):
    # Set VG_REPO_ROOT for module-level constant evaluation. Use try/finally
    # to ensure pollution doesn't leak to other tests in the suite.
    # Pattern used: caller's tmp_path fixture is per-test, so this is safe
    # within a single test's scope. Test fixtures auto-clean tmp_path.
    # We DO NOT cleanup here because the loaded module references env var
    # internally — but this is acceptable because each new _load_hook call
    # overwrites with current tmp_path. The leak is between THIS test file
    # and others (e.g. test_tasklist_visibility.py). Restore at session end
    # via the autouse _cleanup_env fixture below.
    os.environ["VG_REPO_ROOT"] = str(repo_root)
    spec = importlib.util.spec_from_file_location("eh_test", HOOK_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _cleanup_vg_repo_root_env():
    """Auto-cleanup: ensure VG_REPO_ROOT env var doesn't leak between tests
    (or between test files in full suite run). Saves original value and
    restores it after each test.
    """
    original = os.environ.get("VG_REPO_ROOT")
    yield
    if original is None:
        os.environ.pop("VG_REPO_ROOT", None)
    else:
        os.environ["VG_REPO_ROOT"] = original


# ---------------------------------------------------------------------------
# First-non-empty-line match
# ---------------------------------------------------------------------------


def test_pure_slash_command_matches(tmp_path):
    mod = _load_hook(tmp_path)
    assert mod._vg_cmd_at_first_nonempty_line("/vg:scope 7.14.3") is not None
    assert mod._vg_cmd_at_first_nonempty_line("/vg:build 14") is not None


def test_slash_command_after_blank_lines_matches(tmp_path):
    """User typing with leading blank lines still recognized."""
    mod = _load_hook(tmp_path)
    assert mod._vg_cmd_at_first_nonempty_line("\n\n/vg:scope 7.14.3") is not None
    assert mod._vg_cmd_at_first_nonempty_line("   \n   /vg:build 14") is not None


def test_slash_command_after_prose_skipped(tmp_path):
    """Prose first, then /vg: → not a fresh invocation."""
    mod = _load_hook(tmp_path)
    assert mod._vg_cmd_at_first_nonempty_line(
        "Hello\n/vg:scope 7.14.3"
    ) is None
    assert mod._vg_cmd_at_first_nonempty_line(
        "# Doc\n## Section\n/vg:scope 7.14.3"
    ) is None
    assert mod._vg_cmd_at_first_nonempty_line(
        "please run /vg:scope 7.14.3 for me"
    ) is None


def test_vietnamese_prose_then_cmd_skipped(tmp_path):
    """Common pattern: 'chạy /vg:build 14 đi' should NOT register."""
    mod = _load_hook(tmp_path)
    assert mod._vg_cmd_at_first_nonempty_line(
        "chạy /vg:build 14 đi"
    ) is None
    assert mod._vg_cmd_at_first_nonempty_line(
        "vậy thì chạy /vg:scope 7.14.3 dùm"
    ) is None


# ---------------------------------------------------------------------------
# Paste-back detection
# ---------------------------------------------------------------------------


def test_system_reminder_marker_detected(tmp_path):
    mod = _load_hook(tmp_path)
    prompt = "<system-reminder>foo</system-reminder>\n/vg:scope 7.14.3"
    assert mod._looks_like_paste_back(prompt) is True


def test_diff_hunk_markers_detected(tmp_path):
    mod = _load_hook(tmp_path)
    p1 = "--- a/foo.py\n+++ b/foo.py\n@@ ...\n/vg:scope 7"
    assert mod._looks_like_paste_back(p1) is True


def test_stop_hook_feedback_still_detected(tmp_path):
    """Regression: original v2.5.2.5 markers still work."""
    mod = _load_hook(tmp_path)
    cases = [
        "Stop hook feedback: foo",
        "runtime_contract violations — cannot complete",
        "Missing evidence: PLAN.md (missing)",
        "vg-orchestrator override --flag X",
        "vg-orchestrator run-abort --reason Y",
    ]
    for p in cases:
        assert mod._looks_like_paste_back(p) is True, f"failed for: {p!r}"


def test_skill_frontmatter_dump_detected(tmp_path):
    """Pasting a skill body into prompt (e.g. for review) should not
    trigger a run. Frontmatter has `user-invocable: true` + `argument-hint:`.
    """
    mod = _load_hook(tmp_path)
    prompt = (
        "---\n"
        "description: Foo\n"
        "user-invocable: true\n"
        "argument-hint: <phase>\n"
        "---\n"
        "/vg:scope 7.14.3\n"
    )
    assert mod._looks_like_paste_back(prompt) is True


def test_long_prompt_with_abspath_detected(tmp_path):
    """File dump heuristic: long prompt + Windows abs path + /vg: → paste-back."""
    mod = _load_hook(tmp_path)
    long_prompt = (
        "D:\\Workspace\\Messi\\Code\\RTB\\.vg\\phases\\7.14.3\\PLAN.md content:\n"
        + "x" * 2000
        + "\n/vg:build 7.14.3"
    )
    assert mod._looks_like_paste_back(long_prompt) is True


def test_short_pure_command_not_paste_back(tmp_path):
    """Real user typing '/vg:scope 7.14.3' must NOT trigger paste-back."""
    mod = _load_hook(tmp_path)
    assert mod._looks_like_paste_back("/vg:scope 7.14.3") is False
    assert mod._looks_like_paste_back("/vg:build 14") is False


def test_short_prose_with_vg_not_paste_back(tmp_path):
    """User asking question that mentions /vg: — short, no triggers, NO paste-back."""
    mod = _load_hook(tmp_path)
    cases = [
        "what does /vg:scope do?",
        "should I run /vg:blueprint 14 now?",
        "tell me about /vg:test phase 7",
    ]
    for p in cases:
        assert mod._looks_like_paste_back(p) is False, f"false-positive on: {p!r}"


def test_short_path_reference_not_paste_back(tmp_path):
    """Short prompt with abs path + /vg: but UNDER 2KB threshold → not paste-back.
    Heuristic requires both abs path AND >2KB. User mentioning a file
    path while asking about /vg: shouldn't trip.
    """
    mod = _load_hook(tmp_path)
    p = "look at D:\\Workspace\\Messi\\Code\\RTB\\foo.py and run /vg:scope 7"
    assert mod._looks_like_paste_back(p) is False


# ---------------------------------------------------------------------------
# Combined flow simulation (paste-back + line check)
# ---------------------------------------------------------------------------


def test_phantom_scenario_v28_6(tmp_path):
    """Simulates the actual phantom run from this session: PLAN.md content
    with /vg:cmd appears in middle of prompt body. Should NOT register.

    Triggers TWO defenses:
      1. paste-back (long prompt + abs path)
      2. /vg: not at first non-empty line
    """
    mod = _load_hook(tmp_path)
    prompt = (
        "User opened d:\\Workspace\\Messi\\Code\\RTB\\.vg\\workflow-hardening-v2.7\\PLAN.md\n\n"
        "## v2.7 PLAN — execution order\n\n"
        "Phase A — runtime probe Playwright (3-4d)\n"
        + "blah " * 500
        + "\n\n## Examples\n\nUser would type:\n```\n/vg:scope 7.14.3.1\n/vg:blueprint 7.14.3.1\n```\n"
        + "More context: " + "x" * 500
        + "\nWhat should I do?"
    )
    # Defense 1: first-line check fails
    assert mod._vg_cmd_at_first_nonempty_line(prompt) is None
    # Defense 2: paste-back also flags it (size + abs path heuristic)
    assert mod._looks_like_paste_back(prompt) is True


def test_legitimate_invocation_passes(tmp_path):
    """Real user input pattern: just `/vg:cmd phase`. All defenses pass."""
    mod = _load_hook(tmp_path)
    for prompt in ("/vg:scope 7.14.3", "/vg:build 14", "  /vg:test 7.6"):
        assert mod._vg_cmd_at_first_nonempty_line(prompt) is not None
        assert mod._looks_like_paste_back(prompt) is False
