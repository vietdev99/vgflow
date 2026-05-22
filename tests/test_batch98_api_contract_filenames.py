"""B98 v4.69.1 — issue #204 API-CONTRACTS filename Windows-safe gate.

User report (2026-05-22, sig f1e0de01):

> "Windows git refuses checkout/pull these files because core.protectNTFS=true
> (default since git 2.21) blocks reserved chars on NTFS, including colon.
> Repro on Windows: git clone <repo> -> error: invalid path
> .vg/phases/phase-{id}/API-CONTRACTS/get-api-vphase-{id}:id-pdf.md (x16 files)"

Spec in `agents/vg-blueprint-contracts/SKILL.md:76-77` said strip path params
(`:id` → `id`). Implementation drifted — `:` from path templates leaked into
filenames. macOS/Linux silently accept + push upstream. Windows fails.

Affected files (sample): get-api-vphase-{id}:id.md,
post-api-vphase-{id}:id-payments-:payment_id-reverse.md.

## Fix

New `scripts/validators/verify-api-contract-filenames.py` — scans
`**/API-CONTRACTS/*` for files matching `[:<>"|?*]` (Windows-reserved per
core.protectNTFS). `--fix` flag renames each via `git mv` (preserves history)
or `os.rename` fallback. Default severity=block, phases [blueprint, accept].

`agents/vg-blueprint-contracts/SKILL.md` slug rules expanded with explicit
forbidden chars + 3 example renames showing colon strip.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-api-contract-filenames.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-api-contract-filenames.py"
REGISTRY = REPO_ROOT / "scripts" / "validators" / "registry.yaml"
SKILL = REPO_ROOT / "agents" / "vg-blueprint-contracts" / "SKILL.md"


def _run(repo: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), *extra],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8", errors="replace",
    )


# B98 tests that seed files with Windows-reserved chars CANNOT run on Windows
# itself — Windows refuses to create those filenames in the first place (which
# is exactly the bug). These tests run on macOS/Linux CI. Pure-logic tests
# (registry/skill/mirror) run everywhere.
_REQUIRES_POSIX = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Cannot create reserved-char filenames on Windows (bug is platform-specific).",
)


def _seed_contracts(repo: Path, names: list[str]) -> Path:
    contracts_dir = repo / ".vg" / "phases" / "phase-test" / "API-CONTRACTS"
    contracts_dir.mkdir(parents=True)
    for n in names:
        (contracts_dir / n).write_text("# fake contract\n", encoding="utf-8")
    return contracts_dir


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

@_REQUIRES_POSIX
def test_b98_detects_colon_in_filename(tmp_path: Path) -> None:
    _seed_contracts(tmp_path, ["get-api-vphase-{id}:id-pdf.md"])
    proc = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert out["status"] == "FAIL"
    assert out["offender_count"] == 1
    off = out["offenders"][0]
    assert ":" in off["reserved_chars"]
    assert ":" not in off["suggested_rename"]


def test_b98_clean_filename_passes(tmp_path: Path) -> None:
    _seed_contracts(tmp_path, ["post-api-v1-sites-id.md", "get-api-v1-users.md"])
    proc = _run(tmp_path)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["status"] == "PASS"
    assert out["offender_count"] == 0


@_REQUIRES_POSIX
def test_b98_detects_multiple_offenders(tmp_path: Path) -> None:
    _seed_contracts(tmp_path, [
        "get-api-vphase-{id}:id.md",
        "post-api-vphase-{id}:id-payments-:payment_id-reverse.md",
        "put-api-vphase-{id}:id-complete.md",
        "clean-file.md",  # no colon — should be ignored
    ])
    proc = _run(tmp_path)
    out = json.loads(proc.stdout)
    assert out["offender_count"] == 3


@_REQUIRES_POSIX
def test_b98_other_reserved_chars_detected(tmp_path: Path) -> None:
    """Pipe and question-mark also reserved."""
    _seed_contracts(tmp_path, ["get-foo|bar.md", "post-baz?qux.md"])
    proc = _run(tmp_path)
    out = json.loads(proc.stdout)
    assert out["offender_count"] == 2


@_REQUIRES_POSIX
def test_b98_suggested_rename_collapses_double_hyphens(tmp_path: Path) -> None:
    _seed_contracts(tmp_path, ["get-api-{id}::pdf.md"])
    proc = _run(tmp_path)
    out = json.loads(proc.stdout)
    new = out["offenders"][0]["suggested_rename"]
    assert "--" not in new
    assert new.endswith(".md")


# ---------------------------------------------------------------------------
# --fix flag
# ---------------------------------------------------------------------------

@_REQUIRES_POSIX
def test_b98_fix_renames_via_os_rename(tmp_path: Path) -> None:
    """No git repo → fallback to os.rename."""
    contracts_dir = _seed_contracts(tmp_path, [
        "get-api-vphase-{id}:id.md",
        "post-api-vphase-{id}:id-apply.md",
    ])
    proc = _run(tmp_path, "--fix")
    assert proc.returncode == 0  # PASS after fix
    out = json.loads(proc.stdout)
    assert out["status"] == "PASS"
    assert out["remaining_offender_count"] == 0
    # Original files gone
    assert not (contracts_dir / "get-api-vphase-{id}:id.md").exists()
    assert not (contracts_dir / "post-api-vphase-{id}:id-apply.md").exists()
    # Renamed versions present
    renamed = sorted(p.name for p in contracts_dir.iterdir())
    assert all(":" not in n for n in renamed)


@_REQUIRES_POSIX
def test_b98_fix_skips_target_exists(tmp_path: Path) -> None:
    """If suggested_rename collides with existing file → skip + record reason.

    Suggested-rename strips ONLY reserved chars `[:<>"|?*]`. Braces `{}` and
    other safe chars are preserved. So `get-api-:id.md` renames to
    `get-api--id.md` → collapsed to `get-api-id.md`. Collision seed must
    match that exact target.
    """
    contracts_dir = _seed_contracts(tmp_path, [
        "get-api-:id.md",       # rename target: get-api-id.md
        "get-api-id.md",        # collision
    ])
    proc = _run(tmp_path, "--fix")
    out = json.loads(proc.stdout)
    failed = out["fix_applied"]["failed"]
    assert len(failed) == 1
    assert "exists" in failed[0]["reason"]


# ---------------------------------------------------------------------------
# Severity gate
# ---------------------------------------------------------------------------

@_REQUIRES_POSIX
def test_b98_severity_warn_exits_zero_with_findings(tmp_path: Path) -> None:
    _seed_contracts(tmp_path, ["get-api-{id}:id.md"])
    proc = _run(tmp_path, "--severity", "warn")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["status"] == "FAIL"  # status still FAIL, just exit 0


@_REQUIRES_POSIX
def test_b98_severity_block_exits_one_with_findings(tmp_path: Path) -> None:
    _seed_contracts(tmp_path, ["get-api-{id}:id.md"])
    proc = _run(tmp_path, "--severity", "block")
    assert proc.returncode == 1


# ---------------------------------------------------------------------------
# Empty / no API-CONTRACTS dir
# ---------------------------------------------------------------------------

def test_b98_no_contracts_dir_passes(tmp_path: Path) -> None:
    proc = _run(tmp_path)
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# Registry + skill doc presence
# ---------------------------------------------------------------------------

def test_b98_registry_has_entry() -> None:
    body = REGISTRY.read_text(encoding="utf-8")
    assert "id: api-contract-filenames" in body
    idx = body.index("id: api-contract-filenames")
    region = body[idx:idx + 1000]
    assert "severity: block" in region
    assert "added_in: v4.69.1" in region
    assert "blueprint" in region


def test_b98_skill_doc_forbids_reserved_chars() -> None:
    body = SKILL.read_text(encoding="utf-8")
    assert "MUST NOT contain" in body
    assert "core.protectNTFS" in body
    assert "verify-api-contract-filenames.py" in body


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b98_validator_mirror_parity() -> None:
    assert VALIDATOR.read_bytes() == MIRROR.read_bytes()


def test_b98_registry_mirror_parity() -> None:
    mirror = REPO_ROOT / ".claude" / "scripts" / "validators" / "registry.yaml"
    assert REGISTRY.read_bytes() == mirror.read_bytes()


def test_b98_skill_mirror_parity() -> None:
    mirror = REPO_ROOT / ".claude" / "agents" / "vg-blueprint-contracts" / "SKILL.md"
    assert SKILL.read_bytes() == mirror.read_bytes()
