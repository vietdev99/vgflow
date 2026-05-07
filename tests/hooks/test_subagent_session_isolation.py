"""Issue #135 + #136 — subagent hooks must use hook stdin's session_id.

When Claude Code spawns a subagent (Agent tool), each hook fired from
the subagent receives the SUBAGENT's session_id in stdin JSON.
CLAUDE_HOOK_SESSION_ID env var may be empty or leak the parent's value.
The legacy resolver fell through to .vg/.session-context.json which
holds the PARENT's sid — so subagent hooks routed to the parent's slot:
- vg-pre-tool-use-write.sh fired the parent's tasklist gate against the
  subagent's Write call; subagent has no TodoWrite tool to satisfy →
  every /vg:build wave-1 task BLOCKed (#135).
- vg-user-prompt-submit.sh saw the subagent's envelope, matched any
  embedded `/vg:<cmd>` at line 1, and overwrote the parent's
  active-runs/<parent_sid>.json lock (#136).

v2.51.13+: hooks call vg_resolve_session_id_from_input "$input" first.
Stdin sid wins over env when both are set; env-only callers (e.g.
tests) keep the legacy behavior.
"""
from __future__ import annotations

import json
from pathlib import Path

from .conftest import run_hook


def _hook_stdin(*, prompt: str | None = None, file_path: str | None = None,
                session_id: str | None = None) -> str:
    payload: dict = {}
    if session_id is not None:
        payload["session_id"] = session_id
    if prompt is not None:
        payload["prompt"] = prompt
    if file_path is not None:
        payload["tool_input"] = {"file_path": file_path}
    return json.dumps(payload)


def test_write_hook_routes_to_subagent_sid_via_stdin(tmp_workspace):
    """Parent has active run; subagent fires Write hook with its own sid.

    Expectation: hook resolves to subagent-sid → no run-file at that path
    → hook early-exits 0. Parent's tasklist gate does NOT fire.
    """
    parent_run = tmp_workspace / ".vg" / "active-runs"
    parent_run.mkdir(parents=True)
    (parent_run / "test-session.json").write_text(
        '{"run_id": "parent-run-001", "command": "vg:build", "phase": "5", "session_id": "test-session"}'
    )
    # No evidence file written → parent's gate would fire if hook resolved
    # to test-session. We send subagent-distinct sid in stdin.
    result = run_hook(
        "write",
        stdin=_hook_stdin(
            session_id="subagent-distinct-sid",
            file_path="apps/api/src/sites/handler.ts",
        ),
    )
    assert result.returncode == 0, (
        f"Subagent Write hook must exit 0 (no run-file for subagent sid). "
        f"Got rc={result.returncode}\nstderr: {result.stderr}"
    )


def test_write_hook_falls_back_to_env_when_stdin_sid_absent(tmp_workspace):
    """Stdin without session_id → env path used (legacy behaviour).

    Parent's run-file present, no evidence → gate fires (legacy behaviour
    preserved when stdin sid missing).
    """
    parent_run = tmp_workspace / ".vg" / "active-runs"
    parent_run.mkdir(parents=True)
    (parent_run / "test-session.json").write_text(
        '{"run_id": "parent-run-002", "command": "vg:build", "phase": "5", "session_id": "test-session"}'
    )
    result = run_hook(
        "write",
        stdin=_hook_stdin(
            file_path="apps/api/src/sites/handler.ts",
            # session_id intentionally omitted
        ),
    )
    # Without evidence file the gate denies (rc=2).
    assert result.returncode == 2, (
        f"Without stdin sid the env-derived sid must hit parent's slot and "
        f"fire the gate. Got rc={result.returncode}\nstderr: {result.stderr}"
    )


def test_user_prompt_submit_does_not_overwrite_parent_lock_with_stdin_sid(
    tmp_workspace,
):
    """Subagent envelope with /vg:<cmd> on line 1 must NOT overwrite parent.

    Parent's active-runs file is keyed by `test-session`. Subagent fires
    UserPromptSubmit hook with `subagent-xyz` in stdin and an envelope
    that happens to start with `/vg:blueprint 6`. Hook should write to
    `.vg/active-runs/subagent-xyz.json`, leaving the parent's file
    untouched.
    """
    parent_run_dir = tmp_workspace / ".vg" / "active-runs"
    parent_run_dir.mkdir(parents=True)
    parent_file = parent_run_dir / "test-session.json"
    parent_file.write_text(
        '{"run_id": "parent-run-003", "command": "vg:build", "phase": "5", "session_id": "test-session"}'
    )

    result = run_hook(
        "user-prompt-submit",
        stdin=_hook_stdin(
            session_id="subagent-xyz",
            prompt="/vg:blueprint 6\n<envelope body>",
        ),
    )
    # Hook may exit 0 (success) or 2 (refuse) — either way parent file
    # must not have been overwritten.
    parent_after = json.loads(parent_file.read_text())
    assert parent_after["command"] == "vg:build" and parent_after["phase"] == "5", (
        f"Parent active-runs file was overwritten by subagent hook!\n"
        f"After: {parent_after}\nstderr: {result.stderr}"
    )


def test_cross_phase_mainline_overwrite_refused(tmp_workspace):
    """Defense-in-depth #136: even if env sid leaks parent's value, a
    cross-phase mainline overwrite must be refused with exit 2.

    Parent: vg:build phase=5 (mainline). Incoming via env-only sid path:
    /vg:blueprint 6 (mainline, different phase). Hook must REFUSE.
    """
    parent_run_dir = tmp_workspace / ".vg" / "active-runs"
    parent_run_dir.mkdir(parents=True)
    parent_file = parent_run_dir / "test-session.json"
    parent_file.write_text(
        '{"run_id": "parent-run-004", "command": "vg:build", "phase": "5",'
        ' "session_id": "test-session", "started_at": "2099-01-01T00:00:00Z"}'
    )

    # No stdin session_id — env CLAUDE_HOOK_SESSION_ID=test-session resolves
    # straight to parent's slot. Cross-phase mainline overwrite triggered.
    result = run_hook(
        "user-prompt-submit",
        stdin=_hook_stdin(prompt="/vg:blueprint 6"),
    )
    assert result.returncode == 2, (
        f"Cross-phase mainline overwrite must be refused (exit 2). "
        f"Got rc={result.returncode}\nstderr: {result.stderr}"
    )
    # Parent file untouched.
    parent_after = json.loads(parent_file.read_text())
    assert parent_after["command"] == "vg:build" and parent_after["phase"] == "5"
