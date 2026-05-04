"""Task 33 — 2-leg blocking-gate-prompt wrapper tests."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WRAPPER = REPO / "scripts/lib/blocking-gate-prompt.sh"


def _bash(cmd: str, env_extra: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=15)


def test_leg1_emits_json_with_4_options(tmp_path: Path) -> None:
    """Leg 1 emits structured JSON; 4 options; severity normalized."""
    evidence = tmp_path / "ev.json"
    evidence.write_text('{"category":"api_precheck","summary":"missing endpoint"}', encoding="utf-8")
    result = _bash(f'source "{WRAPPER}"; blocking_gate_prompt_emit '
                   f'"api_precheck" "{evidence}" "error"', cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["gate_id"] == "api_precheck"
    assert payload["severity"] == "error"
    assert len(payload["options"]) == 4
    keys = {o["key"] for o in payload["options"]}
    assert keys == {"a", "s", "r", "x"}


def test_leg1_non_interactive_auto_aborts(tmp_path: Path) -> None:
    """When --non-interactive in $ARGUMENTS, Leg 1 emits abort directly."""
    evidence = tmp_path / "ev.json"
    evidence.write_text('{}', encoding="utf-8")
    result = _bash(f'export ARGUMENTS="--non-interactive"; source "{WRAPPER}"; '
                   f'blocking_gate_prompt_emit "g" "{evidence}" "error"', cwd=tmp_path)
    payload = json.loads(result.stdout)
    assert payload.get("non_interactive_auto_abort") is True


def test_leg2_skip_with_override_exits_1(tmp_path: Path) -> None:
    """Leg 2 with --user-choice=s exits 1 + emits override + debt."""
    result = _bash(f'source "{WRAPPER}"; blocking_gate_prompt_resolve "g" '
                   f'--user-choice=s --override-reason="legacy phase, skip OK"', cwd=tmp_path)
    assert result.returncode == 1


def test_leg2_route_to_amend_exits_2(tmp_path: Path) -> None:
    result = _bash(f'source "{WRAPPER}"; blocking_gate_prompt_resolve "g" '
                   f'--user-choice=r', cwd=tmp_path)
    assert result.returncode == 2


def test_leg2_abort_exits_3(tmp_path: Path) -> None:
    result = _bash(f'source "{WRAPPER}"; blocking_gate_prompt_resolve "g" '
                   f'--user-choice=x', cwd=tmp_path)
    assert result.returncode == 3


def test_severity_vocab_mapping(tmp_path: Path) -> None:
    """Wrapper severity (error/warn/critical) maps to debt vocab (high/medium/critical)."""
    result = _bash(f'source "{WRAPPER}"; '
                   f'echo "$(_map_severity_to_debt error) "'
                   f'"$(_map_severity_to_debt warn) "'
                   f'"$(_map_severity_to_debt critical)"', cwd=tmp_path)
    assert result.stdout.strip() == "high medium critical", result.stdout


def test_review_md_wrapper_call_sites_count() -> None:
    """After refactor, review.md must have >=10 wrapper invocations
    matching `blocking_gate_prompt_emit`."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    invocations = text.count("blocking_gate_prompt_emit")
    assert invocations >= 10, (
        f"expected >=10 wrapper invocations after refactor, found {invocations}"
    )


def test_review_md_no_orphan_blocked_exit_1() -> None:
    """No `emit-event review.<X>_blocked` should be immediately followed
    by `exit 1` after refactor — must call wrapper instead."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    # Find every emit-event review.X_blocked, look for exit 1 within 6 lines after
    bad_patterns = re.findall(
        r'emit-event "review\.[a-z_]+_blocked"[^\n]*\n(?:[^\n]*\n){0,6}\s*exit 1',
        text
    )
    assert not bad_patterns, (
        f"found {len(bad_patterns)} `*_blocked emit + exit 1` patterns "
        f"(should be wrapper calls):\n" + "\n---\n".join(bad_patterns[:3])
    )


def test_review_md_has_no_remaining_exit_1_after_blocked_emit() -> None:
    """Codex round-3 B2: every site that emits review.<X>_blocked MUST be
    followed by blocking_gate_prompt_emit, not exit 1."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    # Find each emit-event "review.<X>_blocked" call site
    for m in re.finditer(r'emit-event "review\.[a-z_]+_blocked"', text):
        # Look at the next ~20 lines for blocking_gate_prompt_emit before any exit 1
        tail = text[m.end():m.end() + 2000]
        first_emit = tail.find("blocking_gate_prompt_emit")
        first_exit_1 = tail.find("\nexit 1")
        assert first_emit != -1, f"site at offset {m.start()} missing blocking_gate_prompt_emit"
        if first_exit_1 != -1:
            assert first_emit < first_exit_1, \
                f"site at offset {m.start()} has exit 1 BEFORE wrapper invocation (un-refactored?)"


def test_review_md_declares_all_wrapper_telemetry_events() -> None:
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    for event in [
        "review.gate_skipped_with_override",
        "review.gate_autofix_attempted",
        "review.gate_autofix_unresolved",
        "review.routed_to_amend",
        "review.aborted_by_user",
        "review.aborted_non_interactive_block",
    ]:
        assert event in text, \
            f"review.md must_emit_telemetry must declare '{event}' (else Stop hook silent-skips)"
