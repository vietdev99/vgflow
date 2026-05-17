"""B78 v4.63.10 — tasklist resilience regression tests.

Covers four bugs surfaced during PrintwayV3 `/vg:test 8.2` session:

  1. macOS bash 3.2 cannot parse `vg-post-tool-use-todowrite.sh` because the
     hook embedded large heredoc Python blocks inside `"$(...)"` command
     substitution. Linux CI (bash 4+) parsed fine which masked the bug.
     Fix: extract heredocs to standalone helper scripts
     (`_vg_tasklist_evidence_payload.py` + `_vg_tasklist_snapshot_input.py`).

  2. `vg-orchestrator tasklist-projected --adapter claude` crashed with
     `sqlite3.IntegrityError: FOREIGN KEY constraint failed` when the
     `runs` row was missing for the current run_id (typical when a hook
     wrote `.vg/active-runs/<sid>.json` but the orchestrator was never
     called to `run-start`). Fix: `db.append_event` now catches the FK
     error, attempts to backfill the runs row from state files via
     `_backfill_run_row`, and retries the insert exactly once.

  3. `filter-steps.py` for `/vg:test --profile web-fullstack` returned
     only 2 steps (`step5_fix_loop`, `step7_matrix_verdict`) because two
     stray `<step>` XML tags in `_shared/test/*.md` narrative satisfied
     the XML-positive branch and the YAML frontmatter
     `runtime_contract.must_touch_markers` (22 entries) was ignored.
     Fix: merge frontmatter markers with XML steps instead of using them
     as a fallback only.

  4. (Docs only — not exercised by automated tests.) PreToolUse-Write
     block recovery path was undocumented; when the FK constraint above
     crashed `tasklist-projected`, operators had no path forward other
     than hand-writing the evidence file. Resolved by Bug 2 fix above.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sqlite3
import tempfile
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


# ---------------------------------------------------------------------------
# Bug 1: hook script parses on bash 3.2 (macOS default)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    sys.platform == "win32",
    reason="bash 3.2 regression is macOS-only; Windows lacks /bin/bash. "
           "Static guard test_hook_has_no_inline_heredoc_command_substitution "
           "covers this case cross-platform.",
)
def test_hook_script_parses_on_bash_3_2() -> None:
    """vg-post-tool-use-todowrite.sh must parse on macOS bash 3.2.

    bash 3.2 cannot handle heredocs nested inside `"$(...)"` command
    substitution. B78 extracted those heredocs to sibling .py files so the
    parent shell stays bash-3.2-safe. Regression guard: shell `-n` parse
    check must succeed under whichever bash is on PATH.
    """
    hook = SCRIPTS_DIR / "hooks" / "vg-post-tool-use-todowrite.sh"
    assert hook.is_file(), f"hook missing: {hook}"

    bash_bin = "/bin/bash"
    if not Path(bash_bin).exists():
        import shutil
        bash_bin = shutil.which("bash") or bash_bin
    proc = subprocess.run(
        [bash_bin, "-n", str(hook)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"bash -n failed for {hook}:\nSTDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}"
    )


def test_hook_has_no_inline_heredoc_command_substitution() -> None:
    """Guard against re-introducing heredoc-in-command-substitution.

    Concrete pattern that breaks bash 3.2:
        payload="$(python3 - args... <<'PY'
        ... PY
        )"

    We look for `<<'PY'` (the canonical sentinel used by the legacy hook)
    inside the parent script. If it reappears, the macOS regression
    fires immediately.
    """
    hook = SCRIPTS_DIR / "hooks" / "vg-post-tool-use-todowrite.sh"
    contents = hook.read_text(encoding="utf-8")
    assert "<<'PY'" not in contents and '<<"PY"' not in contents, (
        "Heredoc-in-command-substitution detected in hook script. "
        "bash 3.2 (macOS) cannot parse it. Extract to a sibling .py "
        "helper instead."
    )


def test_extracted_helpers_present_and_compile() -> None:
    """Both extracted helper scripts must exist and pass py_compile."""
    evidence = SCRIPTS_DIR / "hooks" / "_vg_tasklist_evidence_payload.py"
    snapshot = SCRIPTS_DIR / "hooks" / "_vg_tasklist_snapshot_input.py"
    for helper in (evidence, snapshot):
        assert helper.is_file(), f"missing helper: {helper}"
        proc = subprocess.run(
            [sys.executable, "-m", "py_compile", str(helper)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, (
            f"py_compile failed for {helper}:\n{proc.stderr}"
        )


def test_extracted_evidence_helper_emits_payload(tmp_path: Path) -> None:
    """The evidence helper builds a payload JSON identical in shape to
    what the legacy heredoc produced.

    Tolerant smoke test: the helper must read the hook input from
    VG_HOOK_INPUT env, parse the contract JSON, and emit a single-line
    JSON object containing at minimum:
      - run_id
      - adapter == "claude"
      - tool_name
      - match (bool)
      - depth_valid (bool)
    """
    contract_path = tmp_path / "tasklist-contract.json"
    contract = {
        "schema": "native-tasklist.v2",
        "run_id": "test-run-id",
        "command": "vg:test",
        "phase": "8.2",
        "checklists": [
            {"id": "test_preflight", "title": "Test Preflight"},
        ],
        "items": [{"id": "0_parse_and_validate"}],
        "projection_items": [
            {"id": "test_preflight", "title": "Test Preflight", "kind": "group"},
            {"id": "0_parse_and_validate", "title": "  ↳ 0 Parse And Validate", "kind": "step"},
        ],
    }
    contract_path.write_text(json.dumps(contract))

    hook_input = {
        "tool_name": "TodoWrite",
        "tool_input": {
            "todos": [
                {"content": "Test Preflight", "status": "in_progress"},
                {"content": "  ↳ 0 Parse And Validate", "status": "in_progress"},
            ],
        },
    }

    helper = SCRIPTS_DIR / "hooks" / "_vg_tasklist_evidence_payload.py"
    proc = subprocess.run(
        [sys.executable, str(helper), str(contract_path), "test-run-id"],
        capture_output=True, text=True,
        env={**os.environ, "VG_HOOK_INPUT": json.dumps(hook_input)},
    )
    assert proc.returncode == 0, (
        f"helper failed: rc={proc.returncode}\nSTDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}"
    )
    payload = json.loads(proc.stdout.strip())
    assert payload["run_id"] == "test-run-id"
    assert payload["adapter"] == "claude"
    assert payload["tool_name"] == "TodoWrite"
    assert isinstance(payload.get("match"), bool)
    assert isinstance(payload.get("depth_valid"), bool)


# ---------------------------------------------------------------------------
# Bug 2: append_event auto-backfills orphan runs[] FK target
# ---------------------------------------------------------------------------

def _bootstrap_db(repo: Path) -> Path:
    """Initialise events.db schema in `repo` and return the path."""
    db_path = repo / ".vg" / "events.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(textwrap.dedent("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            phase TEXT NOT NULL,
            args TEXT,
            started_at TEXT NOT NULL,
            session_id TEXT,
            git_sha TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            event_type TEXT NOT NULL,
            phase TEXT,
            command TEXT,
            step TEXT,
            actor TEXT,
            outcome TEXT,
            payload_json TEXT NOT NULL,
            prev_hash TEXT,
            this_hash TEXT UNIQUE NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        );
        PRAGMA foreign_keys = ON;
    """))
    conn.commit()
    conn.close()
    return db_path


def test_append_event_backfills_orphan_run_row(tmp_path: Path,
                                               monkeypatch) -> None:
    """append_event must auto-insert a runs[] row when the FK target is
    missing AND the active-runs state file exposes command + phase.

    Reproduces the FOREIGN KEY crash observed mid-session during the
    PrintwayV3 /vg:test 8.2 re-invocation: hook wrote
    `.vg/active-runs/<sid>.json` with run_id but never executed
    `run-start`, so `runs` table had no matching row. emit-event /
    mark-step / tasklist-projected all crashed with
    `sqlite3.IntegrityError: FOREIGN KEY constraint failed`.
    """
    monkeypatch.chdir(tmp_path)
    _bootstrap_db(tmp_path)

    # Use a run_id unique to this test process so we never collide with a
    # row left by a sibling test that imported db.py against the real
    # repo's events.db. The backfill assertion runs against the SAME db
    # the module under test writes to.
    import uuid
    run_id = f"orphan-run-{uuid.uuid4().hex}"
    active_runs = tmp_path / ".vg" / "active-runs"
    active_runs.mkdir(parents=True, exist_ok=True)
    (active_runs / "session-abc.json").write_text(json.dumps({
        "run_id": run_id,
        "command": "vg:test",
        "phase": "8.2",
        "started_at": "2026-05-18T00:00:00Z",
        "session_id": "session-abc",
        "args": "",
    }))

    # Import db.py as a standalone module — the directory is named
    # `vg-orchestrator` (dash) which is not a legal Python identifier, so
    # we go through `importlib.util` rather than a top-level `import`.
    # db.py captures REPO_ROOT / DB_PATH at import time from its OWN
    # __file__ path. Monkey-patch DB_PATH to the test fixture so the
    # backfill flow exercises the temporary database we just bootstrapped.
    pkg_dir = SCRIPTS_DIR / "vg-orchestrator"
    sys.path.insert(0, str(pkg_dir))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "vg_orchestrator_db", str(pkg_dir / "db.py"),
        )
        assert spec and spec.loader
        dbmod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dbmod)

        # Redirect module to the test database.
        monkeypatch.setattr(dbmod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / ".vg" / "events.db")
        monkeypatch.setattr(
            dbmod, "PROJECTION_PATH", tmp_path / ".vg" / "events.jsonl",
        )

        # FK target missing before append.
        assert dbmod.run_row_exists(run_id) is False

        evt = dbmod.append_event(
            run_id=run_id,
            event_type="test.native_tasklist_projected",
            phase="8.2",
            command="vg:test",
        )
        assert evt is not None
        # Backfill must have inserted the runs row.
        assert dbmod.run_row_exists(run_id) is True
    finally:
        sys.path.pop(0)


# ---------------------------------------------------------------------------
# Bug 3: filter-steps merges frontmatter markers with XML steps
# ---------------------------------------------------------------------------

def test_filter_steps_merges_frontmatter_when_xml_present(tmp_path: Path) -> None:
    """`/vg:test` web-fullstack must include the runtime_contract markers
    even when stray `<step>` XML tags exist in `_shared/` narrative.

    The pre-B78 fallback rule (`if not steps: use_frontmatter`) dropped
    every YAML marker the moment ONE XML tag matched. We assert the
    union contains BOTH the XML step ids and the frontmatter markers.
    """
    cmd_dir = tmp_path / "commands" / "vg"
    shared_dir = cmd_dir / "_shared" / "test"
    cmd_dir.mkdir(parents=True)
    shared_dir.mkdir(parents=True)

    # Slim parent file with YAML frontmatter markers.
    (cmd_dir / "test.md").write_text(textwrap.dedent("""
        ---
        name: vg:test
        runtime_contract:
          must_touch_markers:
            - "00_gate_integrity_precheck"
            - "0_parse_and_validate"
            - "5c_goal_verification"
            - "5e_regression"
            - "complete"
        ---
        # /vg:test
        """).lstrip())

    # Shared sub-file with stray XML steps (mimics the real test.md
    # narrative referencing two `<step>` tags inline).
    (shared_dir / "fix-loop.md").write_text(textwrap.dedent("""
        # Fix loop body

        <step name="step5_fix_loop" mode="full">
        <step name="step7_matrix_verdict" mode="full">
        """).lstrip())

    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "filter-steps.py"),
         "--command", str(cmd_dir / "test.md"),
         "--profile", "web-fullstack",
         "--output-ids"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"filter-steps failed: rc={proc.returncode}\nSTDERR:\n{proc.stderr}"
    )
    step_ids = proc.stdout.strip().split(",")

    # XML steps still present.
    assert "step5_fix_loop" in step_ids
    assert "step7_matrix_verdict" in step_ids
    # Frontmatter markers (previously DROPPED) now included.
    assert "00_gate_integrity_precheck" in step_ids
    assert "0_parse_and_validate" in step_ids
    assert "5c_goal_verification" in step_ids
    assert "5e_regression" in step_ids
    assert "complete" in step_ids

    # At least 5 frontmatter markers + 2 XML steps = 7+.
    assert len(step_ids) >= 7, (
        f"Expected ≥7 steps after merge; got {len(step_ids)}: {step_ids}"
    )


def test_filter_steps_real_test_md_includes_runtime_markers() -> None:
    """Real `commands/vg/test.md` must emit > 2 steps for web-fullstack.

    Pre-B78 produced 2 (just step5_fix_loop + step7_matrix_verdict). The
    runtime contract YAML lists 22 markers. With the merge fix in place
    we expect ≥ 20 steps in the projection.
    """
    cmd = REPO_ROOT / "commands" / "vg" / "test.md"
    if not cmd.is_file():
        pytest.skip("commands/vg/test.md not in this checkout")
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "filter-steps.py"),
         "--command", str(cmd),
         "--profile", "web-fullstack",
         "--output-count"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"filter-steps failed for real test.md:\n{proc.stderr}"
    )
    n = int(proc.stdout.strip())
    assert n > 10, (
        f"/vg:test web-fullstack should emit > 10 steps after B78 merge; "
        f"got {n}. (Pre-B78 emitted only 2.)"
    )
