"""
OHOK Batch 5b (E1) — forgery-resistant step markers.

CrossAI Round 6 found: empty .done markers are forgeable. A synthetic
`touch` sweep defeats OHOK — downstream gates check file existence only.

This test suite verifies:
- mark_step() writes schema'd content
- verify_marker() accepts valid, rejects forged/mismatched/stale
- marker-migrate.py rewrites legacy empties idempotently
- legacy markers still accepted in lenient mode (backward compat)
- VG_MARKER_STRICT=1 blocks legacy markers
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MARKER_SCHEMA_SH = (
    REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "lib" / "marker-schema.sh"
)
MIGRATE_PY = REPO_ROOT / ".claude" / "scripts" / "marker-migrate.py"


# Need real bash; on Windows this may resolve to WSL and fail. Detect + skip.
def _bash_works() -> bool:
    try:
        r = subprocess.run(
            ["bash", "-c", "echo ok"],
            capture_output=True, text=True, timeout=3,
        )
        return r.returncode == 0 and "ok" in r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(
    not _bash_works(),
    reason="bash not available (Windows WSL resolution issue)",
)


def _run_bash(script: str, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    """Write script to tempfile (sidesteps Windows subprocess bash -c mangling)
    then invoke via `bash <path>`."""
    tmp = Path(cwd or Path.cwd()) / f".tmp_marker_test_{os.getpid()}.sh"
    tmp.write_text(script, encoding="utf-8")
    try:
        return subprocess.run(
            ["bash", str(tmp)],
            capture_output=True, text=True, timeout=15,
            cwd=str(cwd) if cwd else None,
            env={**os.environ, **(env or {})},
        )
    finally:
        tmp.unlink(missing_ok=True)


# ═══════════════════════════ mark_step ═══════════════════════════

def test_library_loads_cleanly():
    """Source lib, no syntax errors."""
    r = _run_bash(f'source "{MARKER_SCHEMA_SH}" && echo ok')
    assert r.returncode == 0, f"source failed:\n{r.stderr}"
    assert "ok" in r.stdout


def test_mark_step_writes_schema_content(tmp_path):
    """mark_step writes v1|phase|step|sha|ts|runid format."""
    phase_dir = tmp_path / "phases" / "13-test"
    phase_dir.mkdir(parents=True)
    r = _run_bash(
        f'source "{MARKER_SCHEMA_SH}" && mark_step "13" "build" "{phase_dir}" "run-abc"',
        cwd=REPO_ROOT,
    )
    assert r.returncode == 0, r.stderr

    marker = phase_dir / ".step-markers" / "build.done"
    assert marker.exists(), "marker file not created"
    content = marker.read_text(encoding="utf-8").strip()
    fields = content.split("|")
    assert len(fields) == 6, f"expected 6 fields, got {len(fields)}: {content}"
    assert fields[0] == "v1"
    assert fields[1] == "13"
    assert fields[2] == "build"
    # fields[3] = git_sha — should be 40 hex or "nogit"
    assert len(fields[3]) == 40 or fields[3] == "nogit"
    # fields[4] = iso_ts — starts with year
    assert fields[4].startswith("20") or fields[4] == "notime"
    assert fields[5] == "run-abc"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Pipe char in filename is reserved on Windows NTFS — test asserts "
           "Linux-style filename semantics. Sanitization-of-content semantic "
           "still applies but isn't observable when filesystem rejects the "
           "filename outright. Cross-platform fix tracked in v2.9 backlog.",
)
def test_mark_step_sanitizes_pipe_chars(tmp_path):
    """Pipe chars in phase/step/run_id must not corrupt schema."""
    phase_dir = tmp_path / "phases" / "13-test"
    phase_dir.mkdir(parents=True)
    r = _run_bash(
        f'source "{MARKER_SCHEMA_SH}" && mark_step "13|evil" "build|x" "{phase_dir}" "run|bad"',
        cwd=REPO_ROOT,
    )
    assert r.returncode == 0
    content = (phase_dir / ".step-markers" / "build|x.done").read_text(encoding="utf-8")
    # Actually bash filename with | is legal on Linux; windows = filesystem cares
    # Either way, the CONTENT should have pipes sanitized to _
    fields = content.strip().split("|")
    assert len(fields) == 6, f"pipe in arg broke schema: {content}"


# ═══════════════════════════ verify_marker ═══════════════════════════

def test_verify_valid_marker_returns_0(tmp_path):
    """mark_step then verify_marker — should pass."""
    phase_dir = tmp_path / "phases" / "13-test"
    phase_dir.mkdir(parents=True)
    r = _run_bash(
        f'source "{MARKER_SCHEMA_SH}"\n'
        f'mark_step "13" "build" "{phase_dir}" "run-1"\n'
        f'verify_marker "{phase_dir}/.step-markers/build.done" "13" "build"\n'
        f'echo "RC=$?"',
        cwd=REPO_ROOT,
    )
    assert "RC=0" in r.stdout, f"expected RC=0, got:\n{r.stdout}\n{r.stderr}"


def test_verify_blocks_phase_mismatch(tmp_path):
    """Marker written for phase 13, verify against phase 99 → rc=4."""
    phase_dir = tmp_path / "phases" / "13-test"
    phase_dir.mkdir(parents=True)
    r = _run_bash(
        f'source "{MARKER_SCHEMA_SH}"\n'
        f'mark_step "13" "build" "{phase_dir}"\n'
        f'verify_marker "{phase_dir}/.step-markers/build.done" "99" "build"\n'
        f'echo "RC=$?"',
        cwd=REPO_ROOT,
    )
    assert "RC=4" in r.stdout, f"expected RC=4 (phase mismatch): {r.stdout}"


def test_verify_blocks_step_mismatch(tmp_path):
    """Marker step='build', verify expecting 'test' → rc=5."""
    phase_dir = tmp_path / "phases" / "13-test"
    phase_dir.mkdir(parents=True)
    r = _run_bash(
        f'source "{MARKER_SCHEMA_SH}"\n'
        f'mark_step "13" "build" "{phase_dir}"\n'
        f'verify_marker "{phase_dir}/.step-markers/build.done" "13" "test"\n'
        f'echo "RC=$?"',
        cwd=REPO_ROOT,
    )
    assert "RC=5" in r.stdout, f"expected RC=5 (step mismatch): {r.stdout}"


def test_verify_blocks_forged_git_sha(tmp_path):
    """Marker with fake git_sha (not an ancestor of HEAD) → rc=6."""
    phase_dir = tmp_path / "phases" / "13-test"
    phase_dir.mkdir(parents=True)
    markers = phase_dir / ".step-markers"
    markers.mkdir()
    # Write a forged marker directly (skip mark_step) with bogus sha
    forged_sha = "deadbeef" * 5  # 40 hex chars, but not a real commit
    (markers / "build.done").write_text(
        f"v1|13|build|{forged_sha}|2026-04-23T00:00:00Z|forge-run\n",
        encoding="utf-8",
    )

    r = _run_bash(
        f'source "{MARKER_SCHEMA_SH}"\n'
        f'verify_marker "{markers}/build.done" "13" "build"\n'
        f'echo "RC=$?"',
        cwd=REPO_ROOT,
    )
    assert "RC=6" in r.stdout, f"expected RC=6 (forged sha): {r.stdout}\n{r.stderr}"


def test_verify_blocks_schema_mismatch(tmp_path):
    """Marker with only 3 fields → rc=3."""
    phase_dir = tmp_path / "phases" / "13-test"
    markers = phase_dir / ".step-markers"
    markers.mkdir(parents=True)
    (markers / "build.done").write_text("v1|13|build\n", encoding="utf-8")

    r = _run_bash(
        f'source "{MARKER_SCHEMA_SH}"\n'
        f'verify_marker "{markers}/build.done" "13" "build"\n'
        f'echo "RC=$?"',
        cwd=REPO_ROOT,
    )
    assert "RC=3" in r.stdout, f"expected RC=3 (schema): {r.stdout}"


def test_verify_blocks_stale_marker(tmp_path):
    """Marker with iso_ts > max_age_days → rc=7."""
    phase_dir = tmp_path / "phases" / "13-test"
    markers = phase_dir / ".step-markers"
    markers.mkdir(parents=True)
    old_date = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Get real HEAD sha so ancestor check passes
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    (markers / "build.done").write_text(
        f"v1|13|build|{head}|{old_date}|old-run\n",
        encoding="utf-8",
    )

    r = _run_bash(
        f'source "{MARKER_SCHEMA_SH}"\n'
        f'verify_marker "{markers}/build.done" "13" "build" 30\n'  # max 30 days
        f'echo "RC=$?"',
        cwd=REPO_ROOT,
    )
    assert "RC=7" in r.stdout, f"expected RC=7 (stale): {r.stdout}\n{r.stderr}"


def test_verify_legacy_empty_marker_lenient(tmp_path):
    """Empty marker in lenient mode → rc=2 (WARN, not BLOCK)."""
    phase_dir = tmp_path / "phases" / "13-test"
    markers = phase_dir / ".step-markers"
    markers.mkdir(parents=True)
    (markers / "build.done").touch()  # empty

    r = _run_bash(
        f'source "{MARKER_SCHEMA_SH}"\n'
        f'verify_marker "{markers}/build.done" "13" "build"\n'
        f'echo "RC=$?"',
        cwd=REPO_ROOT,
    )
    assert "RC=2" in r.stdout, f"expected RC=2 (legacy lenient): {r.stdout}"


def test_verify_legacy_empty_marker_strict_mode(tmp_path):
    """VG_MARKER_STRICT=1 + legacy empty → still rc=2, but hard-block semantics."""
    phase_dir = tmp_path / "phases" / "13-test"
    markers = phase_dir / ".step-markers"
    markers.mkdir(parents=True)
    (markers / "build.done").touch()

    r = _run_bash(
        f'source "{MARKER_SCHEMA_SH}"\n'
        f'verify_marker "{markers}/build.done" "13" "build"\n'
        f'echo "RC=$?"',
        cwd=REPO_ROOT,
        env={"VG_MARKER_STRICT": "1"},
    )
    assert "RC=2" in r.stdout
    assert "STRICT" in r.stderr, f"strict mode should emit diagnostic: {r.stderr}"


# ═══════════════════════════ verify_all_markers ═══════════════════════════

def test_verify_all_markers_clean_pass(tmp_path):
    """Multiple valid markers → exit 0, summary counts correct."""
    phase_dir = tmp_path / "phases" / "13-test"
    phase_dir.mkdir(parents=True)
    r = _run_bash(
        f'source "{MARKER_SCHEMA_SH}"\n'
        f'mark_step "13" "step_a" "{phase_dir}"\n'
        f'mark_step "13" "step_b" "{phase_dir}"\n'
        f'verify_all_markers "{phase_dir}" "13"\n'
        f'echo "RC=$?"',
        cwd=REPO_ROOT,
    )
    assert "verified=2" in r.stdout, r.stdout
    assert "RC=0" in r.stdout


def test_verify_all_blocks_on_any_forgery(tmp_path):
    """1 valid + 1 forged → overall exit 1."""
    phase_dir = tmp_path / "phases" / "13-test"
    markers = phase_dir / ".step-markers"
    markers.mkdir(parents=True)
    # Valid
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    (markers / "step_a.done").write_text(
        f"v1|13|step_a|{head}|"
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}|r1\n"
    )
    # Forged (wrong sha)
    (markers / "step_b.done").write_text(
        "v1|13|step_b|cafebabecafebabecafebabecafebabecafebabe|"
        "2026-04-23T00:00:00Z|r1\n"
    )

    r = _run_bash(
        f'source "{MARKER_SCHEMA_SH}"\n'
        f'verify_all_markers "{phase_dir}" "13"\n'
        f'echo "RC=$?"',
        cwd=REPO_ROOT,
    )
    assert "forged=1" in r.stdout, r.stdout
    assert "RC=1" in r.stdout


# ═══════════════════════════ migration script ═══════════════════════════

def test_migrate_script_runs(tmp_path):
    """marker-migrate.py --dry-run doesn't crash."""
    # Create a synthetic planning layout
    phase_dir = tmp_path / "phases" / "13-test"
    markers = phase_dir / ".step-markers"
    markers.mkdir(parents=True)
    (markers / "build.done").touch()
    (markers / "test.done").touch()

    r = subprocess.run(
        [sys.executable, str(MIGRATE_PY),
         "--planning", str(tmp_path),
         "--dry-run"],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0, f"migrate failed:\n{r.stdout}\n{r.stderr}"
    assert "2 migrated" in r.stdout or "Summary" in r.stdout
    # Dry-run means files should still be empty
    assert (markers / "build.done").read_text() == ""


def test_migrate_script_writes_content(tmp_path):
    """marker-migrate.py without --dry-run rewrites empty markers."""
    phase_dir = tmp_path / "phases" / "13-sample-phase"
    markers = phase_dir / ".step-markers"
    markers.mkdir(parents=True)
    (markers / "build.done").touch()

    r = subprocess.run(
        [sys.executable, str(MIGRATE_PY), "--planning", str(tmp_path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0
    content = (markers / "build.done").read_text(encoding="utf-8").strip()
    fields = content.split("|")
    assert len(fields) == 6
    assert fields[0] == "v1"
    assert fields[1] == "13"
    assert fields[2] == "build"


def test_migrate_idempotent(tmp_path):
    """Running migrate twice doesn't double-rewrite."""
    phase_dir = tmp_path / "phases" / "13-test"
    markers = phase_dir / ".step-markers"
    markers.mkdir(parents=True)
    (markers / "build.done").touch()

    subprocess.run(
        [sys.executable, str(MIGRATE_PY), "--planning", str(tmp_path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    first_content = (markers / "build.done").read_text(encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(MIGRATE_PY), "--planning", str(tmp_path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert "1 already had content" in r.stdout or "0 migrated" in r.stdout
    second_content = (markers / "build.done").read_text(encoding="utf-8")
    assert first_content == second_content, "migration not idempotent"
