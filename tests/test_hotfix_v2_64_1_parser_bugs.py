#!/usr/bin/env python3
"""Hotfix v2.64.1 — 3-layer split parser bugs.

Closes 6 GitHub issues from a darwin user on vg 2.48.1, all sharing one
root cause: parsers expected legacy heading/block formats but the artifact
ecosystem shifted to a 3-layer split pattern (Layer 3 flat / Layer 2 index
table / Layer 1 per-file split).

Tests:
  1. matrix-merger.sh counts goals from index table (issue #148 HIGH)
  2. matrix-merger.sh counts goals from split files (issue #148 HIGH)
  3. review-api-contract-probe.py parses table format (issues #146/#145)
  4. review-api-contract-probe.py parses split files (issue #144)
  5. generate-api-docs.py parses table format (issue #143)
  6. generate-api-docs.py parses split files (issue #143)
  7. verify-contract-completeness scope skips BE for FE profile (issue #147)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
MATRIX_MERGER_SH = REPO_ROOT / "commands" / "vg" / "_shared" / "lib" / "matrix-merger.sh"


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return path


def _run_matrix_merger(phase_dir: Path) -> dict[str, str]:
    """Source matrix-merger.sh, call merge_and_write_matrix, parse stdout into dict."""
    bash = shutil.which("bash") or "/bin/bash"
    if not Path(bash).exists() and sys.platform == "win32":
        bash = shutil.which("bash.exe") or shutil.which("git-bash") or "bash"
    cmd = [
        bash,
        "-c",
        f"set -e; source '{MATRIX_MERGER_SH.as_posix()}'; "
        f"merge_and_write_matrix '{phase_dir.as_posix()}' '' '' '' ''",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"merge_and_write_matrix failed (rc={proc.returncode}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    out = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# ───────────────────────────────────────────────────────────────────────────
# Test 1 — matrix-merger counts goals from index table (issue #148 HIGH)
# ───────────────────────────────────────────────────────────────────────────


def test_matrix_merger_counts_goals_from_index_table(tmp_path: Path):
    """Phase has TEST-GOALS/index.md with 3 goals listed in the table.

    Pre-fix: merger parses TEST-GOALS.md (flat) only, finds 0 goals → TOTAL=0
             → BLOCK or silent FALSE-PASS.
    Post-fix: merger reads index table when flat parse yields 0.
    """
    if sys.platform == "win32" and not shutil.which("bash"):
        pytest.skip("bash unavailable on Windows runner")

    phase_dir = tmp_path / "06.1-test"
    # Empty/minimal flat TEST-GOALS.md (no `## Goal G-XX:` headings)
    _write(phase_dir / "TEST-GOALS.md", """
        # Test Goals — Phase 6.1

        See `TEST-GOALS/index.md` for per-goal split files.
    """)
    _write(phase_dir / "TEST-GOALS" / "index.md", """
        # Test Goals — Phase 6.1

        ## Goal Index (3 goals)

        | ID | Surface | Priority | File |
        |----|---------|----------|------|
        | G-01 | login | P0 | G-01.md |
        | G-02 | signup | P0 | G-02.md |
        | G-03 | logout | P1 | G-03.md |
    """)

    result = _run_matrix_merger(phase_dir)
    assert int(result.get("TOTAL", "0")) == 3, (
        f"Expected TOTAL=3 from index table parse, got result={result}"
    )


# ───────────────────────────────────────────────────────────────────────────
# Test 2 — matrix-merger counts goals from split files (issue #148 HIGH)
# ───────────────────────────────────────────────────────────────────────────


def test_matrix_merger_counts_goals_from_split_files(tmp_path: Path):
    """Phase has TEST-GOALS/G-NN.md per-goal files, no index table.

    Pre-fix: 0 goals from flat or table → TOTAL=0.
    Post-fix: walks TEST-GOALS/G-*.md as last-resort, takes max of all sources.
    """
    if sys.platform == "win32" and not shutil.which("bash"):
        pytest.skip("bash unavailable on Windows runner")

    phase_dir = tmp_path / "06.2-test"
    # No flat headings, no index table — split files only.
    _write(phase_dir / "TEST-GOALS.md", "# Test Goals — Phase 6.2\n\nSee split files.\n")
    for gid in ("G-01", "G-02", "G-03", "G-04"):
        _write(phase_dir / "TEST-GOALS" / f"{gid}.md", f"""
            # {gid}: stub

            **Surface:** ui
            **Priority:** important
        """)

    result = _run_matrix_merger(phase_dir)
    assert int(result.get("TOTAL", "0")) == 4, (
        f"Expected TOTAL=4 from split files, got result={result}"
    )


def test_matrix_merger_legacy_block_format_still_works(tmp_path: Path):
    """Backward-compat — ensure legacy `## Goal G-XX:` block parsing untouched."""
    if sys.platform == "win32" and not shutil.which("bash"):
        pytest.skip("bash unavailable on Windows runner")

    phase_dir = tmp_path / "01-legacy"
    _write(phase_dir / "TEST-GOALS.md", """
        # Test Goals — Phase 1

        ## Goal G-01: Login flow
        **Priority:** critical
        **Surface:** ui

        ## Goal G-02: Signup flow
        **Priority:** important
        **Surface:** ui
    """)
    result = _run_matrix_merger(phase_dir)
    assert int(result.get("TOTAL", "0")) == 2, f"legacy parse broke: {result}"


# ───────────────────────────────────────────────────────────────────────────
# Test 3 — review-api-contract-probe parses table format (issues #146/#145)
# ───────────────────────────────────────────────────────────────────────────


def _load_api_probe():
    """Import scripts/review-api-contract-probe.py as a Python module.

    Registers in sys.modules under a stable name so dataclass introspection
    works (dataclasses look up `cls.__module__` in sys.modules).
    """
    import importlib.util
    name = "review_api_contract_probe"
    if name in sys.modules:
        return sys.modules[name]
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            name, SCRIPTS / "review-api-contract-probe.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    finally:
        if str(SCRIPTS) in sys.path:
            sys.path.remove(str(SCRIPTS))
    return mod


def test_api_probe_parses_table_format(tmp_path: Path):
    """API-CONTRACTS.md (or API-CONTRACTS/index.md) uses table format only.

    Pre-fix: parser looks for `### METHOD /path` headings → 0 endpoints.
    Post-fix: falls back to table-row parser when heading-parse yields 0.
    """
    mod = _load_api_probe()

    phase_dir = tmp_path / "07-api-table"
    _write(phase_dir / "API-CONTRACTS" / "index.md", """
        # API Contracts — Phase 7

        ## Endpoint Index

        | Slug | Method | Path | File |
        |------|--------|------|------|
        | auth-login | POST | /api/auth/login | auth-login.md |
        | user-list  | GET  | /api/users      | user-list.md  |
        | user-create | POST | /api/users     | user-create.md |
    """)

    endpoints = mod.parse_contracts(phase_dir / "API-CONTRACTS" / "index.md")
    assert len(endpoints) == 3, f"expected 3 from table, got {len(endpoints)}"
    methods = {(e.method, e.path) for e in endpoints}
    assert ("POST", "/api/auth/login") in methods
    assert ("GET", "/api/users") in methods
    assert ("POST", "/api/users") in methods


# ───────────────────────────────────────────────────────────────────────────
# Test 4 — review-api-contract-probe parses split files (issue #144)
# ───────────────────────────────────────────────────────────────────────────


def test_api_probe_parses_split_files(tmp_path: Path):
    """API-CONTRACTS/<slug>.md per-endpoint files; no useful index/flat content."""
    mod = _load_api_probe()

    phase_dir = tmp_path / "07-api-split"
    # Index has no parseable rows
    _write(phase_dir / "API-CONTRACTS" / "index.md", """
        # API Contracts — Phase 7

        See per-endpoint files.
    """)
    _write(phase_dir / "API-CONTRACTS" / "auth-login.md", """
        # POST /api/auth/login

        **Auth:** none

        **Request:**

        | Field | Type | Required | Description |
        |-------|------|----------|-------------|
        | email | string | yes | user email |
    """)
    _write(phase_dir / "API-CONTRACTS" / "user-create.md", """
        # POST /api/users

        **Auth:** bearer
    """)

    endpoints = mod.parse_contracts(phase_dir / "API-CONTRACTS" / "index.md")
    assert len(endpoints) == 2, f"expected 2 from split files, got {len(endpoints)}"
    methods = {(e.method, e.path) for e in endpoints}
    assert ("POST", "/api/auth/login") in methods
    assert ("POST", "/api/users") in methods


def test_api_probe_legacy_heading_format_still_works(tmp_path: Path):
    """Backward-compat — ensure legacy `### METHOD /path` heading still parses."""
    mod = _load_api_probe()

    phase_dir = tmp_path / "01-legacy-api"
    _write(phase_dir / "API-CONTRACTS.md", """
        # API Contracts — Phase 1

        ### GET /api/health
        **Auth:** none

        ### POST /api/login
        **Auth:** none
    """)
    endpoints = mod.parse_contracts(phase_dir / "API-CONTRACTS.md")
    assert len(endpoints) == 2, f"legacy parse broke: got {len(endpoints)}"


# ───────────────────────────────────────────────────────────────────────────
# Test 5 + 6 — generate-api-docs parses table + split (issue #143)
# ───────────────────────────────────────────────────────────────────────────


def test_generate_api_docs_parses_table_format(tmp_path: Path):
    """parse_contract_sections returns sections from index table when no headings."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        from api_docs_common import parse_contract_sections
    finally:
        sys.path.remove(str(SCRIPTS))

    index = _write(tmp_path / "API-CONTRACTS" / "index.md", """
        # API Contracts — Phase 8

        | Slug | Method | Path | File |
        |------|--------|------|------|
        | health | GET | /api/health | health.md |
        | login  | POST | /api/login | login.md  |
    """)
    sections = parse_contract_sections(index)
    assert len(sections) == 2, f"table parse failed: {len(sections)}"
    paths = {(s.method, s.path) for s in sections}
    assert ("GET", "/api/health") in paths
    assert ("POST", "/api/login") in paths


def test_generate_api_docs_parses_split_files(tmp_path: Path):
    """parse_contract_sections walks split files when index has no rows."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        from api_docs_common import parse_contract_sections
    finally:
        sys.path.remove(str(SCRIPTS))

    contracts_dir = tmp_path / "API-CONTRACTS"
    index = _write(contracts_dir / "index.md", "# API Contracts\n\nsee split files.\n")
    _write(contracts_dir / "health.md", """
        # GET /api/health

        **Auth:** none
    """)
    _write(contracts_dir / "login.md", """
        # POST /api/login

        **Auth:** none
    """)
    sections = parse_contract_sections(index)
    assert len(sections) == 2, f"split-file parse failed: {len(sections)}"


# ───────────────────────────────────────────────────────────────────────────
# Test 7 — verify-contract-completeness profile-aware scope (issue #147)
# ───────────────────────────────────────────────────────────────────────────


def test_verify_contract_completeness_skips_be_for_fe_profile(tmp_path: Path):
    """For web-frontend-only phase, BE-only signals (DB models, webhooks, jobs)
    must not be reported as uncovered.

    Pre-fix: validator reports BE warnings (DB models found, etc.) on pure FE phase.
    Post-fix: detects platform profile from frontmatter, skips BE inventory entirely.
    """
    phase_dir = tmp_path / "09-fe-only"
    _write(phase_dir / "SPECS.md", """
        ---
        platform: web-frontend-only
        ---

        # Phase 9 — FE-only refresh
    """)
    _write(phase_dir / "CRUD-SURFACES.md", """
        # CRUD Surfaces — Phase 9

        ```json
        {
          "resources": [
            {"name": "ui-only-resource", "platforms": {}}
          ]
        }
        ```
    """)

    # Code root with a BE model that would normally trigger uncovered_models warning.
    code_root = tmp_path / "code"
    _write(code_root / "src" / "user-model.py", """
        from sqlalchemy.ext.declarative import declarative_base
        Base = declarative_base()

        class UserAccount(Base):
            pass
    """)

    cmd = [
        sys.executable,
        str(SCRIPTS / "verify-contract-completeness.py"),
        "--phase-dir", str(phase_dir),
        "--code-root", str(code_root),
        "--json",
        "--quiet",
    ]
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(code_root)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert proc.returncode in (0, 1), f"unexpected rc={proc.returncode}\n{proc.stderr}"

    payload = json.loads(proc.stdout)
    # FE-only profile must skip BE inventory entirely.
    assert payload.get("models_inventoried", 0) == 0, (
        f"FE-only profile should skip BE model grep, got "
        f"models_inventoried={payload.get('models_inventoried')}"
    )
    assert payload.get("background_jobs_inventoried", 0) == 0, (
        f"FE-only profile should skip background-job grep, got "
        f"background_jobs_inventoried={payload.get('background_jobs_inventoried')}"
    )
    assert payload.get("webhooks_inventoried", 0) == 0, (
        f"FE-only profile should skip webhook grep, got "
        f"webhooks_inventoried={payload.get('webhooks_inventoried')}"
    )
    # Resulting verdict should be COMPLETE since no BE artifacts considered.
    assert payload.get("verdict") == "COMPLETE", (
        f"FE-only with empty FE diff should be COMPLETE, got {payload.get('verdict')}"
    )


def test_verify_contract_completeness_full_inventory_for_fullstack(tmp_path: Path):
    """For web-fullstack (or absent profile), keep existing full BE inventory."""
    phase_dir = tmp_path / "09-fullstack"
    _write(phase_dir / "SPECS.md", """
        ---
        platform: web-fullstack
        ---

        # Phase 9 — fullstack
    """)
    _write(phase_dir / "CRUD-SURFACES.md", """
        # CRUD Surfaces

        ```json
        {"resources": [{"name": "user", "platforms": {}}]}
        ```
    """)

    code_root = tmp_path / "code"
    _write(code_root / "src" / "stranger.py", """
        from sqlalchemy.ext.declarative import declarative_base
        Base = declarative_base()
        class StrangerThing(Base):
            pass
    """)

    cmd = [
        sys.executable,
        str(SCRIPTS / "verify-contract-completeness.py"),
        "--phase-dir", str(phase_dir),
        "--code-root", str(code_root),
        "--json",
        "--quiet",
    ]
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(code_root)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert proc.returncode in (0, 1), proc.stderr

    payload = json.loads(proc.stdout)
    # fullstack profile keeps BE inventory active
    assert payload.get("models_inventoried", 0) >= 1, (
        f"fullstack must run BE grep, got models_inventoried={payload.get('models_inventoried')}"
    )
