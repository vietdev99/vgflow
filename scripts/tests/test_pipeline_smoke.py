"""
OHOK Batches 1-3 smoke tests — runtime behavior verification.

Previous tests (test_specs_contract, test_phaseP_real_verification,
test_uat_quorum_gate) check STRUCTURE: contract fields present, regex
patterns match, markers declared. They don't prove the bash gates
actually BLOCK when the adversarial condition is simulated.

These smoke tests extract the bash from each skill-MD and run it in
isolation with mocked env, verifying:
1. UAT quorum gate exits 1 when 5 critical skips in .uat-responses.json
2. Specs approval gate exits 2 when USER_APPROVAL is empty / invalid
3. phaseP_delta blocks orthogonal hotfix (no overlap with parent files)
4. phaseP_regression blocks empty bugfix (no code delta)

Approach: extract bash blocks from <step name="X">, run with shimmed
orchestrator/override-debt (no-op functions), assert exit code +
side effects (marker, debt entry, event call).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ACCEPT_MD = REPO_ROOT / ".claude" / "commands" / "vg" / "accept.md"
SPECS_MD = REPO_ROOT / ".claude" / "commands" / "vg" / "specs.md"
REVIEW_MD = REPO_ROOT / ".claude" / "commands" / "vg" / "review.md"


def _extract_bash_blocks(md_text: str, step_name: str) -> str:
    """Concat all ```bash blocks inside <step name="X">."""
    match = re.search(
        rf'<step name="{re.escape(step_name)}"[^>]*>(.+?)</step>',
        md_text, re.DOTALL,
    )
    assert match, f"step {step_name} not found"
    block = match.group(1)
    bashes = re.findall(r'```bash\n(.+?)\n```', block, re.DOTALL)
    assert bashes, f"step {step_name} has no ```bash block"
    return "\n".join(bashes)


def _run_bash(bash_code: str, env: dict, cwd: Path, shims: str = "") -> subprocess.CompletedProcess:
    """Run bash script with shims prepended. shims = function defs that
    override real orchestrator / override-debt calls to no-ops.

    Writes to tempfile then invokes bash <path> — Windows bash -c has
    issues with large multi-line args (newlines/heredocs get mangled)."""
    import tempfile
    script = shims + "\n" + bash_code
    full_env = {**os.environ, **env, "PYTHONIOENCODING": "utf-8",
                "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False, encoding="utf-8",
        dir=str(cwd),
    ) as f:
        f.write(script)
        script_path = f.name
    try:
        return subprocess.run(
            ["bash", script_path],
            cwd=str(cwd), capture_output=True,
            encoding="utf-8", errors="replace",
            env=full_env, timeout=30,
        )
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


# Standard shims used by multiple tests — replace external calls with no-ops
STD_SHIMS = textwrap.dedent("""
    # Mock orchestrator — swallow all args, print for debug, exit 0
    orchestrator_mock() { echo "[mock-orch] $@" >&2; return 0; }

    # Override python invocations that call orchestrator script paths.
    # We create a fake script in a temp bin on PATH.
    _SHIM_BIN=$(mktemp -d)
    mkdir -p "$_SHIM_BIN/.claude/scripts"
    cat > "$_SHIM_BIN/.claude/scripts/vg-orchestrator" <<'MOCK'
#!/usr/bin/env python3
import sys
print("[mock-orch]", *sys.argv[1:], file=sys.stderr)
sys.exit(0)
MOCK
    chmod +x "$_SHIM_BIN/.claude/scripts/vg-orchestrator"

    # Shadow repo's orchestrator via PATH manipulation — prepend a dir
    # that contains a `python3` wrapper catching vg-orchestrator calls.
    # Simpler: create a symlink at ./.claude/scripts/vg-orchestrator if
    # the test's cwd doesn't already have it.
    mkdir -p .claude/scripts 2>/dev/null
    [ -f .claude/scripts/vg-orchestrator ] || \
      cp "$_SHIM_BIN/.claude/scripts/vg-orchestrator" .claude/scripts/vg-orchestrator

    # override-debt shim — avoid sourcing the real helper (it needs env we
    # haven't set up). Provide no-op so `type -t log_override_debt` finds it.
    log_override_debt() { echo "[mock-debt] $@" >&2; return 0; }
    export -f log_override_debt 2>/dev/null || true

    # PYTHON_BIN default
    export PYTHON_BIN="${PYTHON_BIN:-python3}"
""")


# ═══════════════════════════════════════════════════════════════════════
# Test 1 — UAT quorum gate blocks 5 critical skips
# ═══════════════════════════════════════════════════════════════════════

def test_uat_quorum_blocks_5_critical_skips(tmp_path):
    """Simulate user skipping 5 critical items (3 decisions + 2 READY goals).
    Default threshold is 0 → must BLOCK."""
    phase_dir = tmp_path / "phase-test"
    phase_dir.mkdir()
    (phase_dir / ".step-markers").mkdir()

    resp = {
        "decisions": {
            "pass": 0, "fail": 0, "skip": 3,
            "items": [
                {"id": "P1.D-01", "verdict": "s", "ts": "2026-01-01T00:00:00Z"},
                {"id": "P1.D-02", "verdict": "s", "ts": "2026-01-01T00:00:00Z"},
                {"id": "P1.D-03", "verdict": "s", "ts": "2026-01-01T00:00:00Z"},
            ],
        },
        "goals": {
            "pass": 0, "fail": 0, "skip": 2,
            "items": [
                {"id": "G-01", "status_before": "READY", "verdict": "s", "ts": "2026-01-01T00:00:00Z"},
                {"id": "G-02", "status_before": "READY", "verdict": "s", "ts": "2026-01-01T00:00:00Z"},
            ],
        },
        "final": {"verdict": "DEFER", "ts": "2026-01-01T00:00:00Z"},
    }
    (phase_dir / ".uat-responses.json").write_text(
        json.dumps(resp), encoding="utf-8"
    )

    bash = _extract_bash_blocks(
        ACCEPT_MD.read_text(encoding="utf-8"), "5_uat_quorum_gate"
    )

    env = {
        "PHASE_DIR": str(phase_dir),
        "PHASE_NUMBER": "1",
        "REPO_ROOT": str(tmp_path),
        "ARGUMENTS": "",  # no --allow-uat-skips
    }
    result = _run_bash(bash, env, tmp_path, shims=STD_SHIMS)

    assert result.returncode == 1, (
        f"UAT quorum gate should BLOCK (exit 1) for 5 critical skips but got "
        f"rc={result.returncode}\nstderr={result.stderr}\nstdout={result.stdout}"
    )
    # Verify the block message mentions the count
    assert "5" in result.stderr and "critical skips" in result.stderr.lower()


def test_uat_quorum_passes_all_critical_verified(tmp_path):
    """All decisions passed, all READY goals passed → no skips → quorum passes."""
    phase_dir = tmp_path / "phase-test"
    phase_dir.mkdir()
    (phase_dir / ".step-markers").mkdir()

    resp = {
        "decisions": {"pass": 3, "fail": 0, "skip": 0, "items": []},
        "goals": {"pass": 2, "fail": 0, "skip": 0, "items": []},
        "final": {"verdict": "ACCEPT", "ts": "2026-01-01T00:00:00Z"},
    }
    (phase_dir / ".uat-responses.json").write_text(json.dumps(resp), encoding="utf-8")

    bash = _extract_bash_blocks(
        ACCEPT_MD.read_text(encoding="utf-8"), "5_uat_quorum_gate"
    )
    env = {
        "PHASE_DIR": str(phase_dir),
        "PHASE_NUMBER": "1",
        "REPO_ROOT": str(tmp_path),
        "ARGUMENTS": "",
    }
    result = _run_bash(bash, env, tmp_path, shims=STD_SHIMS)

    assert result.returncode == 0, (
        f"UAT quorum gate should PASS (exit 0) with 0 skips but got "
        f"rc={result.returncode}\nstderr={result.stderr}"
    )
    assert (phase_dir / ".step-markers" / "5_uat_quorum_gate.done").exists()


def test_uat_quorum_blocks_missing_response_json(tmp_path):
    """No .uat-responses.json written → gate must BLOCK (prevents theatre)."""
    phase_dir = tmp_path / "phase-test"
    phase_dir.mkdir()
    (phase_dir / ".step-markers").mkdir()

    bash = _extract_bash_blocks(
        ACCEPT_MD.read_text(encoding="utf-8"), "5_uat_quorum_gate"
    )
    env = {
        "PHASE_DIR": str(phase_dir),
        "PHASE_NUMBER": "1",
        "REPO_ROOT": str(tmp_path),
        "ARGUMENTS": "",  # no --allow-empty-uat
    }
    result = _run_bash(bash, env, tmp_path, shims=STD_SHIMS)

    assert result.returncode == 1, (
        f"UAT quorum gate should BLOCK when response JSON missing, got "
        f"rc={result.returncode}\nstderr={result.stderr}"
    )
    assert ".uat-responses.json" in result.stderr


def test_uat_quorum_override_forces_DEFER(tmp_path):
    """--allow-uat-skips lets it pass but forces verdict=DEFER."""
    phase_dir = tmp_path / "phase-test"
    phase_dir.mkdir()
    (phase_dir / ".step-markers").mkdir()

    resp = {
        "decisions": {"pass": 0, "fail": 0, "skip": 5, "items": []},
        "goals": {"pass": 0, "fail": 0, "skip": 0, "items": []},
        "final": {"verdict": "ACCEPT", "ts": "2026-01-01T00:00:00Z"},
    }
    resp_path = phase_dir / ".uat-responses.json"
    resp_path.write_text(json.dumps(resp), encoding="utf-8")

    bash = _extract_bash_blocks(
        ACCEPT_MD.read_text(encoding="utf-8"), "5_uat_quorum_gate"
    )
    env = {
        "PHASE_DIR": str(phase_dir),
        "PHASE_NUMBER": "1",
        "REPO_ROOT": str(tmp_path),
        "ARGUMENTS": "--allow-uat-skips",
    }
    result = _run_bash(bash, env, tmp_path, shims=STD_SHIMS)

    assert result.returncode == 0, (
        f"Override should let gate pass but got rc={result.returncode}\n"
        f"stderr={result.stderr}"
    )
    # Verify the verdict was forced to DEFER
    updated = json.loads(resp_path.read_text(encoding="utf-8"))
    assert updated["final"]["verdict"] == "DEFER", (
        f"Override must force verdict=DEFER, got {updated['final']['verdict']}"
    )
    assert updated["final"].get("forced_by") == "uat_quorum_override"


# ═══════════════════════════════════════════════════════════════════════
# Test 2 — Specs approval gate
# ═══════════════════════════════════════════════════════════════════════

def test_specs_approval_gate_blocks_unset_USER_APPROVAL(tmp_path):
    """USER_APPROVAL empty → exit 2 (no silent approval)."""
    phase_dir = tmp_path / "phase-test"
    phase_dir.mkdir()
    (phase_dir / ".step-markers").mkdir()

    bash = _extract_bash_blocks(
        SPECS_MD.read_text(encoding="utf-8"), "generate_draft"
    )
    env = {
        "PHASE_DIR": str(phase_dir),
        "PHASE_NUMBER": "1",
        "REPO_ROOT": str(tmp_path),
        "ARGUMENTS": "",
        "AUTO_MODE": "false",
        "USER_APPROVAL": "",  # adversarial: empty
    }
    result = _run_bash(bash, env, tmp_path, shims=STD_SHIMS)
    assert result.returncode == 2, (
        f"Unset USER_APPROVAL must exit 2, got rc={result.returncode}\n"
        f"stderr={result.stderr}"
    )


def test_specs_approval_gate_passes_approve(tmp_path):
    phase_dir = tmp_path / "phase-test"
    phase_dir.mkdir()
    (phase_dir / ".step-markers").mkdir()

    bash = _extract_bash_blocks(
        SPECS_MD.read_text(encoding="utf-8"), "generate_draft"
    )
    env = {
        "PHASE_DIR": str(phase_dir),
        "PHASE_NUMBER": "1",
        "REPO_ROOT": str(tmp_path),
        "ARGUMENTS": "",
        "AUTO_MODE": "true",
        "USER_APPROVAL": "approve",
    }
    result = _run_bash(bash, env, tmp_path, shims=STD_SHIMS)
    assert result.returncode == 0, (
        f"USER_APPROVAL=approve must pass, got rc={result.returncode}\n"
        f"stderr={result.stderr}"
    )
    assert (phase_dir / ".step-markers" / "generate_draft.done").exists()


def test_specs_approval_gate_discard_exits_2(tmp_path):
    phase_dir = tmp_path / "phase-test"
    phase_dir.mkdir()
    (phase_dir / ".step-markers").mkdir()

    bash = _extract_bash_blocks(
        SPECS_MD.read_text(encoding="utf-8"), "generate_draft"
    )
    env = {
        "PHASE_DIR": str(phase_dir),
        "PHASE_NUMBER": "1",
        "REPO_ROOT": str(tmp_path),
        "ARGUMENTS": "",
        "AUTO_MODE": "false",
        "USER_APPROVAL": "discard",
    }
    result = _run_bash(bash, env, tmp_path, shims=STD_SHIMS)
    assert result.returncode == 2, (
        f"USER_APPROVAL=discard must exit 2, got rc={result.returncode}\n"
        f"stderr={result.stderr}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Test 3 — phaseP_delta blocks empty / orthogonal hotfix
# ═══════════════════════════════════════════════════════════════════════

def _make_git_repo(tmp_path: Path) -> Path:
    """Init a tiny git repo with 1 commit so HEAD~1 resolves."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    # Baseline commit
    (repo / "README.md").write_text("initial", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def test_phaseP_delta_blocks_empty_hotfix(tmp_path):
    """Hotfix phase with 0 code files changed → BLOCK unless --allow-empty-hotfix."""
    repo = _make_git_repo(tmp_path)
    phases_dir = repo / ".vg" / "phases"
    phases_dir.mkdir(parents=True)

    # Parent phase has a failed goal
    parent = phases_dir / "01-parent"
    parent.mkdir()
    (parent / "GOAL-COVERAGE-MATRIX.md").write_text(textwrap.dedent("""\
        # Goal Coverage Matrix
        | G-01 | READY | BLOCKED | desc |
    """), encoding="utf-8")

    # Current hotfix phase — SPECS cites parent, but no code delta
    hotfix = phases_dir / "02-hotfix"
    hotfix.mkdir()
    (hotfix / ".step-markers").mkdir()
    (hotfix / "SPECS.md").write_text(
        "**Parent phase:** 01\n", encoding="utf-8"
    )

    # Add ONLY a docs change (no apps/packages/infra)
    (repo / "NOTES.md").write_text("note", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "docs"], cwd=repo, check=True)

    bash = _extract_bash_blocks(
        REVIEW_MD.read_text(encoding="utf-8"), "phaseP_delta"
    )
    env = {
        "PHASE_DIR": str(hotfix),
        "PHASE_NUMBER": "02",
        "REPO_ROOT": str(repo),
        "PHASES_DIR": str(phases_dir),
        "REVIEW_MODE": "delta",
        "ARGUMENTS": "",  # no --allow-empty-hotfix
    }
    result = _run_bash(bash, env, repo, shims=STD_SHIMS)

    assert result.returncode == 1, (
        f"Empty hotfix must BLOCK, got rc={result.returncode}\n"
        f"stderr={result.stderr[-600:]}\nstdout={result.stdout[-400:]}"
    )
    assert "empty-hotfix" in result.stderr.lower() or \
           "0 code files" in result.stderr


# ═══════════════════════════════════════════════════════════════════════
# Test 4 — phaseP_regression blocks missing bug_ref
# ═══════════════════════════════════════════════════════════════════════

def test_phaseP_regression_blocks_no_bug_ref(tmp_path):
    """Bugfix SPECS without issue_id/bug_ref → BLOCK unless --allow-no-bugref."""
    repo = _make_git_repo(tmp_path)
    phases_dir = repo / ".vg" / "phases"
    phases_dir.mkdir(parents=True)

    bugfix = phases_dir / "03-bugfix"
    bugfix.mkdir()
    (bugfix / ".step-markers").mkdir()
    # SPECS WITHOUT issue_id/bug_ref
    (bugfix / "SPECS.md").write_text("# SPECS\n\nFix something.\n", encoding="utf-8")

    bash = _extract_bash_blocks(
        REVIEW_MD.read_text(encoding="utf-8"), "phaseP_regression"
    )
    env = {
        "PHASE_DIR": str(bugfix),
        "PHASE_NUMBER": "03",
        "REPO_ROOT": str(repo),
        "PHASES_DIR": str(phases_dir),
        "REVIEW_MODE": "regression",
        "ARGUMENTS": "",  # no --allow-no-bugref
    }
    result = _run_bash(bash, env, repo, shims=STD_SHIMS)

    assert result.returncode == 1, (
        f"Bugfix without bug_ref must BLOCK, got rc={result.returncode}\n"
        f"stderr={result.stderr[-600:]}"
    )
    assert "bug" in result.stderr.lower() and "ref" in result.stderr.lower()


def test_phaseP_regression_blocks_empty_bugfix(tmp_path):
    """Bugfix with bug_ref but 0 code delta → BLOCK unless --allow-empty-bugfix."""
    repo = _make_git_repo(tmp_path)
    phases_dir = repo / ".vg" / "phases"
    phases_dir.mkdir(parents=True)

    bugfix = phases_dir / "04-bugfix"
    bugfix.mkdir()
    (bugfix / ".step-markers").mkdir()
    # SPECS with bug_ref but we'll add no code changes
    (bugfix / "SPECS.md").write_text(
        "# SPECS\n\nissue_id: JIRA-123\n", encoding="utf-8"
    )

    # Only docs change, no apps/packages/infra
    (repo / "CHANGELOG.md").write_text("change", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "docs"], cwd=repo, check=True)

    bash = _extract_bash_blocks(
        REVIEW_MD.read_text(encoding="utf-8"), "phaseP_regression"
    )
    env = {
        "PHASE_DIR": str(bugfix),
        "PHASE_NUMBER": "04",
        "REPO_ROOT": str(repo),
        "PHASES_DIR": str(phases_dir),
        "REVIEW_MODE": "regression",
        "ARGUMENTS": "",
    }
    result = _run_bash(bash, env, repo, shims=STD_SHIMS)

    assert result.returncode == 1, (
        f"Bugfix without code delta must BLOCK, got rc={result.returncode}\n"
        f"stderr={result.stderr[-600:]}"
    )
    assert "0 code files" in result.stderr or "empty" in result.stderr.lower()
