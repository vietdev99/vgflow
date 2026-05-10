"""v3.6.4 — /vg:update Codex skill dedupe.

Bug: even with tri-state VG_UPDATE_{PROJECT,GLOBAL}_CODEX env vars,
operators ended up with vgflow skills in both ~/.codex/skills/ and
<project>/.codex/skills/. Codex picker reads both → duplicates.
v3.6.1 added prune_duplicate_codex_skills() to sync.sh, but sync.sh
is NOT run by /vg:update — its own merge pipeline is.

Fix: sync-and-report.md step 8_sync_codex adds dedupe pass after both
deploy phases. Uses .vg/.install-target marker:
  - global    → prune <project>/.codex/skills (global wins)
  - project   → prune ~/.codex/skills (project wins)
  - absent    → default to prune project (v3.0.0 architecture)
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SYNC_REPORT_CANON = REPO_ROOT / "commands" / "vg" / "_shared" / "update" / "sync-and-report.md"
SYNC_REPORT_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "update" / "sync-and-report.md"


def _body() -> str:
    return SYNC_REPORT_CANON.read_text(encoding="utf-8")


def test_dedupe_block_present():
    body = _body()
    assert "v3.6.4 — marker-driven dedupe of Codex skills" in body, (
        "sync-and-report.md must declare v3.6.4 dedupe block"
    )
    assert "prune_codex_dir()" in body, "dedupe helper function must exist"
    assert ".vg/.install-target" in body, "dedupe must read .vg/.install-target marker"


def test_dedupe_handles_all_marker_states():
    body = _body()
    # Function body
    m = re.search(r"prune_codex_dir\(\) \{(.+?)^\}", body, re.M | re.S)
    assert m, "prune_codex_dir function body parse failed"
    # Match block for install-target resolution
    m2 = re.search(
        r'case "\$INSTALL_TARGET" in(.+?)esac',
        body,
        re.S,
    )
    assert m2, "case statement on INSTALL_TARGET missing"
    case_body = m2.group(1)
    assert "project)" in case_body
    assert 'global|"")' in case_body, "global + unset branch missing"
    # Validates correct prune direction
    assert 'prune_codex_dir "$HOME/.codex/skills"' in case_body, (
        "project install must prune global skills dir"
    )
    assert 'prune_codex_dir "${REPO_ROOT}/.codex/skills"' in case_body, (
        "global/unset install must prune project skills dir"
    )


def test_dedupe_only_runs_when_both_sides_populated():
    body = _body()
    assert 'PROJECT_CODEX_HAS_VGFLOW' in body
    assert 'GLOBAL_CODEX_HAS_VGFLOW' in body
    # Branch checks both
    assert re.search(
        r'if \[ "\$PROJECT_CODEX_HAS_VGFLOW" = "1" \] && \[ "\$GLOBAL_CODEX_HAS_VGFLOW" = "1" \]',
        body,
    ), "dedupe must gate on both flags being 1"


def test_dedupe_runs_after_codex_deploys():
    body = _body()
    deploy_pos = body.find("Codex mirror: skills=")
    dedupe_pos = body.find("v3.6.4 — marker-driven dedupe of Codex skills")
    assert deploy_pos > 0
    assert dedupe_pos > deploy_pos, (
        "dedupe must run AFTER the Codex deploy summary line"
    )
    verify_pos = body.find("verify-codex-mirror-equivalence.py")
    assert verify_pos > dedupe_pos, (
        "dedupe must run BEFORE codex-mirror-verify (mirror-verify expects clean state)"
    )


def test_mirror_byte_identity():
    assert SYNC_REPORT_CANON.read_bytes() == SYNC_REPORT_MIRROR.read_bytes(), (
        "sync-and-report.md canonical and .claude mirror must match"
    )
