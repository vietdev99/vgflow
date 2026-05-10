"""v2.79.1 hotfix — issue triage batch.

Closes 5 unique issues (7 reports, 2 dups):
- #171 helper_error: bug-reporter `trap RETURN` invalid in zsh
- #170 ai_inconsistency: run-complete prints PASS for BLOCK outcome
- #167, #164 (dup): ghost active-run with run_row=null blocks new runs
- #168, #165 (dup): filter-steps zero results after slim/_shared split
- #169 gate_loop: Codex adapter parity events (deferred — needs deeper investigation)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


# ── #171: bug-reporter zsh trap RETURN ─────────────────────────────────


def test_bug_reporter_trap_return_guarded_by_bash_version():
    """trap RETURN is bash-specific; must be guarded so zsh doesn't error."""
    body = (
        REPO_ROOT / "commands" / "vg" / "_shared" / "lib" / "bug-reporter.sh"
    ).read_text(encoding="utf-8")
    # Find the trap line, ensure BASH_VERSION guard prefix is present
    assert "trap " in body and "RETURN" in body, "trap RETURN line missing"
    assert (
        '[ -n "${BASH_VERSION:-}" ] && trap "rm -f \'$body_tmp\'" RETURN'
        in body
    ), "trap RETURN must be guarded with [ -n \"${BASH_VERSION:-}\" ]"


def test_bug_reporter_mirror_byte_identity():
    canonical = (
        REPO_ROOT / "commands" / "vg" / "_shared" / "lib" / "bug-reporter.sh"
    ).read_bytes()
    mirror = (
        REPO_ROOT
        / ".claude"
        / "commands"
        / "vg"
        / "_shared"
        / "lib"
        / "bug-reporter.sh"
    ).read_bytes()
    assert canonical == mirror


# ── #170: run-complete --outcome BLOCK printed PASS ────────────────────


def test_run_complete_caller_outcome_separated_from_verdict():
    """Code path must use caller_outcome var and pass it to db.complete_run +
    differentiate terminal message when verdict=True but outcome != PASS."""
    main = (
        REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"
    ).read_text(encoding="utf-8")
    assert "caller_outcome" in main, (
        "run-complete must capture --outcome separately from contract verdict"
    )
    assert (
        'db.complete_run(run_id, outcome=caller_outcome)' in main
    ), "DB outcome must reflect --outcome, not hardcoded PASS"
    assert (
        "contract PASS, " in main
    ), "terminal msg must differentiate contract PASS from non-PASS outcome"


def test_run_complete_main_mirror_byte_identity():
    canonical = (
        REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"
    ).read_bytes()
    mirror = (
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py"
    ).read_bytes()
    assert canonical == mirror


# ── #167/#164: ghost active-run row_row=null ───────────────────────────


def test_run_start_clears_ghost_active_run():
    """run-start must auto-clear active state file when run_id missing in DB."""
    main = (
        REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"
    ).read_text(encoding="utf-8")
    assert (
        "active_run_id and not db.run_row_exists(active_run_id)" in main
    ), "run-start must probe DB for ghost detection"
    assert "run.ghost_cleared" in main, (
        "ghost clearance must emit telemetry event"
    )
    assert (
        "run_row_null_at_run_start" in main
    ), "ghost-clear payload must include reason for audit"


# ── #168/#165: filter-steps zero after slim split ──────────────────────


def test_filter_steps_concats_shared_subfiles():
    """filter-steps.py must read parent + _shared/<cmd>/*.md to find <step>
    tags after v2.71+ slim splits."""
    body = (
        REPO_ROOT / "scripts" / "filter-steps.py"
    ).read_text(encoding="utf-8")
    assert (
        'shared_dir = cmd_path.parent / "_shared" / cmd_stem' in body
    ), "filter-steps must compute _shared/<cmd_stem>/ path"
    assert "rglob" in body, "filter-steps must walk sub-files recursively"


def test_filter_steps_returns_steps_for_split_review():
    """Smoke test: review.md after split returns >0 steps."""
    if not shutil.which(sys.executable):
        pytest.skip("python missing")
    review_md = REPO_ROOT / "commands" / "vg" / "review.md"
    if not review_md.exists():
        pytest.skip("review.md absent in test env")
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "filter-steps.py"),
            "--command",
            str(review_md),
            "--profile",
            "web-fullstack",
            "--output-count",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    count = int(proc.stdout.strip())
    assert count > 0, (
        f"review.md (slim + _shared) must return >0 steps; got {count}"
    )


def test_filter_steps_returns_steps_for_split_build():
    """Smoke test: build.md after split returns >0 steps."""
    build_md = REPO_ROOT / "commands" / "vg" / "build.md"
    if not build_md.exists():
        pytest.skip("build.md absent")
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "filter-steps.py"),
            "--command",
            str(build_md),
            "--profile",
            "web-fullstack",
            "--output-count",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    count = int(proc.stdout.strip())
    assert count > 0


def test_filter_steps_mirror_byte_identity():
    canonical = (REPO_ROOT / "scripts" / "filter-steps.py").read_bytes()
    mirror = (REPO_ROOT / ".claude" / "scripts" / "filter-steps.py").read_bytes()
    assert canonical == mirror
