"""B101 v4.69.4 — issue #198 override-resolve YAML format trio.

User report (sig 937529b6, severity MEDIUM):
> "/vg:override-resolve OD-30179 OD-30180 --status=RESOLVED.
> Observed: skill exits 0 silently, row unchanged."

## Three bugs in one report

### Bug 1: override_resolve_by_id NOT in .sh library

The function was documented in `commands/vg/_shared/override-debt.md`
(line 224, inside markdown code fence) but absent from the runnable
`lib/override-debt.sh`. Slash command sourced the .md file via
`source ... 2>/dev/null || true` — bash treats markdown headers as
syntax errors, silently swallowed → function never defined → call
silently no-op'd.

### Bug 2: Status name mismatch — "OPEN" vs "active"

Markdown table format uses `OPEN`. YAML block format (newer
orchestrator-CLI-written) uses `active`. Pre-B101 skill Step 1 did
`grep | awk -F '|'` extracting column 9 — works for table, returns
empty for YAML. Then `"" != "OPEN"` → false-success message "đã ở
trạng thái (empty)" → silent exit 0 without resolving.

### Bug 3: No batch mode

Skill processed only the FIRST matched DEBT-ID per invocation. Real
sessions batch IDs (e.g. `OD-30179 OD-30180`) — second ID silently
dropped.

## Fix

1. Ported `override_resolve_by_id` from .md → `lib/override-debt.sh`.
   Function checks both `OPEN` and `active` case-insensitively. Emits
   override_resolved telemetry. Prints event_id on success.
2. Slash command sources `.sh` (line 38 + 220), not `.md`.
3. Skill Step 1: per-ID status check. YAML format (OD-/BF-) parsed via
   awk between `- id: <id>` and next `- ` line. Table format uses old
   column-9 path. Normalize current status to lowercase, accept both
   `open` + `active`.
4. Skill Step 3 loops over `${PROCESS[@]}` instead of single ID. Tracks
   resolved_count, skipped, failed; non-zero exit only when failures.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / "commands" / "vg" / "_shared" / "lib" / "override-debt.sh"
LIB_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "lib" / "override-debt.sh"
SLASH = REPO_ROOT / "commands" / "vg" / "override-resolve.md"
SLASH_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "override-resolve.md"


# B101 tests that invoke bash functions need a POSIX shell. Skip bash-exec
# tests on Windows entirely — Git Bash MSYS path conversion mangles the
# command string when running `bash -c "export X=...; ..."` (the bare word
# `export` gets rewritten into a filesystem path by MSYS). Linux CI runs
# these tests cleanly. Source-level + mirror checks run everywhere.
_REQUIRES_BASH = pytest.mark.skipif(
    sys.platform == "win32",
    reason="MSYS path conversion breaks bash -c on Windows — tests run on Linux CI",
)


# ---------------------------------------------------------------------------
# Source-level guards
# ---------------------------------------------------------------------------

def test_b101_lib_defines_override_resolve_by_id() -> None:
    body = LIB.read_text(encoding="utf-8")
    assert "override_resolve_by_id()" in body, (
        "override_resolve_by_id must be defined in lib/override-debt.sh"
    )
    assert "B101 v4.69.4" in body, "B101 marker missing"


def test_b101_lib_accepts_active_status() -> None:
    body = LIB.read_text(encoding="utf-8")
    # Function checks both 'active' and 'open' case-insensitively
    assert "('active', 'open')" in body or "'active'" in body and "'open'" in body, (
        "Must accept both YAML 'active' and table 'OPEN' status names"
    )


def test_b101_slash_sources_sh_not_md() -> None:
    body = SLASH.read_text(encoding="utf-8")
    # Step 1 region
    assert "source .claude/commands/vg/_shared/lib/override-debt.sh" in body, (
        "Slash command must source the .sh (runnable), not the .md"
    )


def test_b101_slash_supports_batch_ids() -> None:
    body = SLASH.read_text(encoding="utf-8")
    assert "DEBT_IDS" in body, "Slash command must declare DEBT_IDS (plural)"
    assert "for DEBT_ID in" in body, "Slash command must iterate over IDs"
    assert "PROCESS" in body and "SKIPPED" in body, (
        "Skill must track per-ID outcome buckets"
    )


def test_b101_slash_status_check_supports_yaml_format() -> None:
    body = SLASH.read_text(encoding="utf-8")
    # YAML branch keys off OD-/BF- prefix + awk between `- id:` and next entry
    assert '[[ "$DEBT_ID" =~ ^(OD-|BF-) ]]' in body
    assert "- id: $DEBT_ID" in body
    # Normalized check accepts both forms
    assert '"open"' in body and '"active"' in body, (
        "Skill must compare normalized current status against both"
    )


def test_b101_slash_loops_over_resolve_call() -> None:
    body = SLASH.read_text(encoding="utf-8")
    # Step 3 batch loop
    assert 'for DEBT_ID in "${PROCESS[@]}"' in body, (
        "Step 3 must loop over PROCESS array"
    )
    assert "RESOLVED_COUNT" in body


# ---------------------------------------------------------------------------
# Bash-exec validation
# ---------------------------------------------------------------------------

@_REQUIRES_BASH
def test_b101_function_is_sourceable() -> None:
    """Source the .sh and `type` the function — proves it's defined."""
    proc = subprocess.run(
        ["bash", "-c", f"source '{LIB}' && type override_resolve_by_id"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "override_resolve_by_id is a function" in proc.stdout


@_REQUIRES_BASH
def test_b101_resolves_yaml_block_with_active_status(tmp_path: Path) -> None:
    """Seed a YAML-format register with `status: active`, call
    override_resolve_by_id, assert row flipped to RESOLVED + resolved_at +
    resolved_event_id + resolution_reason added."""
    register = tmp_path / "OVERRIDE-DEBT.md"
    register.write_text(
        "# OVERRIDE-DEBT\n\n"
        "- id: OD-30180\n"
        "  logged_at: 2026-05-21T16:51:49Z\n"
        "  status: active\n"
        "  reason: original reason\n"
        "  gate: PreToolUse-tasklist\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", "-c",
         f"export CONFIG_DEBT_REGISTER_PATH='{register}' PLANNING_DIR='{tmp_path}'; "
         f"source '{LIB}' && override_resolve_by_id 'OD-30180' 'RESOLVED' 'B101 test'"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    result = register.read_text(encoding="utf-8")
    assert "status: RESOLVED" in result
    assert "resolved_at:" in result
    assert "resolved_event_id:" in result
    assert 'resolution_reason: "B101 test"' in result
    # Original active status replaced (no longer present)
    assert "status: active" not in result


@_REQUIRES_BASH
def test_b101_returns_nonzero_on_unknown_id(tmp_path: Path) -> None:
    register = tmp_path / "OVERRIDE-DEBT.md"
    register.write_text(
        "- id: OD-99999\n  status: active\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", "-c",
         f"export CONFIG_DEBT_REGISTER_PATH='{register}' PLANNING_DIR='{tmp_path}'; "
         f"source '{LIB}' && override_resolve_by_id 'OD-NEVER' 'RESOLVED' 'test'"],
        capture_output=True, text=True,
    )
    # The Python block exits 2 on not-found; bash function returns that exit
    assert proc.returncode != 0, "Should fail when DEBT-ID not in register"


@_REQUIRES_BASH
def test_b101_no_change_when_already_resolved(tmp_path: Path) -> None:
    register = tmp_path / "OVERRIDE-DEBT.md"
    initial = (
        "- id: OD-30180\n"
        "  status: RESOLVED\n"
        "  resolved_at: 2026-05-01T00:00:00Z\n"
    )
    register.write_text(initial, encoding="utf-8")
    proc = subprocess.run(
        ["bash", "-c",
         f"export CONFIG_DEBT_REGISTER_PATH='{register}' PLANNING_DIR='{tmp_path}'; "
         f"source '{LIB}' && override_resolve_by_id 'OD-30180' 'RESOLVED' 'retry'"],
        capture_output=True, text=True,
    )
    # Python exits 3 when no row matched OPEN/active → bash function returns nonzero
    assert proc.returncode != 0


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b101_lib_mirror_parity() -> None:
    assert LIB.read_bytes() == LIB_MIRROR.read_bytes()


def test_b101_slash_mirror_parity() -> None:
    assert SLASH.read_bytes() == SLASH_MIRROR.read_bytes()
