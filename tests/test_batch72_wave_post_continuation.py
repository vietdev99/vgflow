"""tests/test_batch72_wave_post_continuation.py — B72 wave→post-build auto-continuation.

User report: "build xong từng wave với --wave, hết wave cuối không tự kích
hoạt nốt các bước sau build". Root cause analysis (parallel investigator):
  - waves-overview.md prose "exit to step 9" was ambiguous; AI sometimes
    interpreted as "exit now" after final wave commits.
  - Stop hook cascade gates 4a/4b/4c/4d/4e detect missing post-build steps
    AND `exit 2 + stderr` but relied on Claude Code re-injecting stderr,
    which is fragile.

Fix:
  1. waves-overview.md emits explicit `<system-reminder>` AUTO-CONTINUE
     directive AFTER `.is-final-wave=true` marker write.
  2. waves-overview.md `--wave` mode echo now states both branches: partial
     (exit) vs final (continue STEP 5/6/7 inline).
  3. Stop hook adds JSON `{"decision":"block","reason":"..."}` stdout
     emission per Claude Code Stop hook decision protocol — more reliable
     than stderr-only.

Tests:
  - waves-overview contains the new directive block.
  - waves-overview --wave mode prose enumerates both branches.
  - Stop hook emits JSON decision when failures fire.
  - Stop hook backward-compat: still exit 2 + stderr.
  - Mirror parity.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WAVES_OVERVIEW = REPO / "commands" / "vg" / "_shared" / "build" / "waves-overview.md"
WAVES_OVERVIEW_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "build" / "waves-overview.md"
STOP_HOOK = REPO / "scripts" / "hooks" / "vg-stop.sh"
STOP_HOOK_MIRROR = REPO / ".claude" / "scripts" / "hooks" / "vg-stop.sh"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# waves-overview.md — AUTO-CONTINUE directive.
# ---------------------------------------------------------------------------


def test_b72_waves_overview_emits_auto_continue_directive():
    body = _read(WAVES_OVERVIEW)
    assert "B72 v4.63.4" in body
    assert "AUTO-CONTINUE — FINAL WAVE COMPLETE" in body
    # The heredoc tag.
    assert "AUTO_CONTINUE_DIRECTIVE" in body


def test_b72_waves_overview_directive_within_is_final_wave_branch():
    """Directive must be guarded by `if [ "$IS_FINAL_WAVE" = "true" ]; then`."""
    body = _read(WAVES_OVERVIEW)
    idx = body.find("AUTO-CONTINUE — FINAL WAVE COMPLETE")
    assert idx > 0
    preceding = body[max(0, idx - 400):idx]
    assert 'IS_FINAL_WAVE' in preceding and '= "true"' in preceding


def test_b72_waves_overview_directive_lists_all_4_required_markers():
    body = _read(WAVES_OVERVIEW)
    idx = body.find("AUTO-CONTINUE — FINAL WAVE COMPLETE")
    block = body[idx:idx + 1500]
    for marker in (
        "9_post_execution.done",
        "11_crossai_build_verify_loop.done",
        "10_postmortem_sanity.done",
        "12_run_complete.done",
    ):
        assert marker in block, f"missing marker reference: {marker}"


def test_b72_waves_overview_directive_cites_cascade_gates():
    body = _read(WAVES_OVERVIEW)
    idx = body.find("AUTO-CONTINUE — FINAL WAVE COMPLETE")
    block = body[idx:idx + 1500]
    # Cite 4a-4e cascade so AI knows the enforcement mechanism.
    assert "4a" in block and "4e" in block


def test_b72_waves_overview_wave_filter_echo_states_both_branches():
    """--wave mode echo must clarify partial-vs-final outcomes (was: 'exit to step 9' only)."""
    body = _read(WAVES_OVERVIEW)
    # New prose mentions both partial and final.
    assert "partial run" in body or "partial-wave" in body.lower()
    assert "FINAL wave" in body or "final wave" in body
    assert "DO NOT END TURN" in body


# ---------------------------------------------------------------------------
# Stop hook — JSON decision protocol emission.
# ---------------------------------------------------------------------------


def test_b72_stop_hook_emits_json_decision_block():
    body = _read(STOP_HOOK)
    assert "B72 v4.63.4" in body
    assert "JSON_DECISION_PY" in body
    assert '"decision":"block"' in body or '"decision": "block"' in body
    # The Python heredoc that builds the JSON.
    assert "json.dumps" in body


def test_b72_stop_hook_decision_includes_full_failure_list():
    body = _read(STOP_HOOK)
    # The heredoc iterates failures[] and appends each as a reason line.
    assert "failures = sys.argv[5:]" in body
    assert "for f in failures" in body or 'for f in failures:' in body


def test_b72_stop_hook_decision_instructs_continue_in_same_turn():
    body = _read(STOP_HOOK)
    assert "continue in the SAME assistant turn" in body.replace(
        "  ", " "
    ).replace("SAME assistant", "SAME assistant")


def test_b72_stop_hook_backward_compat_keeps_exit_2():
    """Old Claude Code reads stderr from non-zero exit. v4.63.4 keeps exit 2."""
    body = _read(STOP_HOOK)
    idx = body.find("JSON_DECISION_PY")
    assert idx > 0
    tail = body[idx:idx + 1500]
    assert "exit 2" in tail


def test_b72_stop_hook_keeps_orange_title_stderr_log():
    """Backward-compat: stderr orange-title printf still emitted."""
    body = _read(STOP_HOOK)
    assert "\\033[38;5;208m" in body
    assert "for run %s (%s)" in body


# ---------------------------------------------------------------------------
# Stop hook subprocess behavior — JSON appears on stdout when failures fire.
# ---------------------------------------------------------------------------


@pytest.fixture
def stop_hook_runner(tmp_path: Path):
    """Build a synthetic project that triggers Stop hook cascade gate 4a.

    Setup:
      - .vg/active-runs/<sid>.json with command=vg:build, phase_dir=.vg/phases/T/.
      - .vg/phases/T/.step-markers/wave-1.done present (waves_done > 0).
      - .step-markers/9_post_execution.done MISSING.
      - .vg/runs/<rid>/.is-final-wave = "true".
      - events.db file (sqlite stub) so hook doesn't error reading it.
    """
    project = tmp_path
    sid = "sess-test-b72"
    rid = "run-test-b72"
    phase_dir = project / ".vg" / "phases" / "T"
    (phase_dir / ".step-markers").mkdir(parents=True, exist_ok=True)
    (phase_dir / ".step-markers" / "wave-1.done").write_text("done", encoding="utf-8")
    active_runs = project / ".vg" / "active-runs"
    active_runs.mkdir(parents=True, exist_ok=True)
    (active_runs / f"{sid}.json").write_text(json.dumps({
        "session_id": sid,
        "run_id": rid,
        "command": "vg:build",
        "phase": "T",
        "phase_dir": str(phase_dir),
    }), encoding="utf-8")
    runs_dir = project / ".vg" / "runs" / rid
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / ".is-final-wave").write_text("true", encoding="utf-8")
    (project / ".vg" / "events.db").write_bytes(b"")
    return {
        "project": project,
        "session_id": sid,
        "run_id": rid,
        "phase_dir": phase_dir,
    }


def test_b72_stop_hook_subprocess_emits_json_decision_to_stdout(
    stop_hook_runner: dict, tmp_path: Path,
):
    """When cascade 4a fires, JSON decision MUST appear on stdout."""
    import os
    project = stop_hook_runner["project"]
    sid = stop_hook_runner["session_id"]
    # Stop hook reads session_id from stdin JSON OR env. Pipe JSON.
    stdin = json.dumps({"session_id": sid})
    env = {**os.environ,
           "VG_REPO_ROOT": str(project),
           "VG_HOME": str(REPO / ".claude"),
           "CLAUDE_HOOK_SESSION_ID": sid,
           "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        ["bash", str(STOP_HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(project),
        timeout=15,
    )
    # Cascade gate 4a should fire; exit 2.
    assert result.returncode == 2, (
        f"expected exit 2 (failures), got {result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    # JSON decision block on stdout.
    assert '"decision"' in result.stdout, (
        f"missing JSON decision on stdout\nstdout={result.stdout!r}"
    )
    # Parseable.
    try:
        # The whole stdout may have only one JSON object.
        decision = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        # If trailing/leading text, try extracting the JSON object.
        m = re.search(r"\{.*\}", result.stdout, re.DOTALL)
        assert m, f"no JSON object in stdout: {result.stdout!r}"
        decision = json.loads(m.group(0))
    assert decision.get("decision") == "block"
    assert "POST-WAVE CONTINUATION" in decision.get("reason", "")


# ---------------------------------------------------------------------------
# Mirror parity.
# ---------------------------------------------------------------------------


def test_b72_waves_overview_mirror_byte_identical():
    assert WAVES_OVERVIEW.read_bytes() == WAVES_OVERVIEW_MIRROR.read_bytes()


def test_b72_stop_hook_mirror_byte_identical():
    assert STOP_HOOK.read_bytes() == STOP_HOOK_MIRROR.read_bytes()
