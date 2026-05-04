"""
R8-F — Tests for FOUNDATION→SPECS goal traceability validator
(scripts/validators/verify-foundation-to-specs.py).

Closes codex closed-loop audit (2026-05-05): /vg:specs ignored FOUNDATION.md
entirely. Phase SPECS could declare goals with no link back to project
milestone. New validator + preflight wiring + override flag close the gap.

Coverage (7 cases):

  Validator behaviour (4 verdict cases):
    - test_pass_when_specs_cites_foundation_goal      (rc=0 PASS, F-XX hit)
    - test_pass_when_specs_quotes_milestone           (rc=0 PASS, textual cite)
    - test_block_when_specs_no_citation               (rc=1 BLOCK)
    - test_warn_when_foundation_absent                (rc=0 WARN)

  Multi-location resolution (1 case):
    - test_validator_handles_multiple_foundation_locations

  Wiring (2 frontmatter/preflight assertions):
    - test_skill_md_frontmatter_has_override_flag
    - test_preflight_allowlist_has_override_flag

Validator emit_and_exit semantics (per scripts/validators/_common.py):
  - rc 0 → PASS or WARN
  - rc 1 → BLOCK
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-foundation-to-specs.py"
SPECS_MD = REPO_ROOT / "commands" / "vg" / "specs.md"
PREFLIGHT_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "specs" / "preflight.md"


# ─── Helpers ──────────────────────────────────────────────────────────


FOUNDATION_BODY = """\
# FOUNDATION.md

## 4. Decisions

### F-01: Platform = web-saas
**Reasoning:** SaaS multi-tenant model
**Reverse cost:** HIGH

### F-02: Frontend = React + Vite
**Reasoning:** Modern toolchain

### F-04: Backend topology = monolith Fastify
**Reasoning:** Simple ops profile

### F-05: Database = Postgres
**Reasoning:** Relational core
"""


def _make_phase_dir(tmp_path: Path, phase_id: str = "9.99") -> Path:
    """Create a tmp phase dir matching `${PHASES_DIR}/${phase_id}-slug` shape."""
    phases_dir = tmp_path / ".vg" / "phases"
    phases_dir.mkdir(parents=True, exist_ok=True)
    phase_dir = phases_dir / f"{phase_id}-rfc-test"
    phase_dir.mkdir()
    return phase_dir


def _write_foundation(tmp_path: Path, location: str = ".vg") -> Path:
    """Write FOUNDATION.md at one of the canonical locations.

    location ∈ {".vg", ".planning", "root"} — exercises multi-location lookup.
    """
    if location == ".vg":
        target_dir = tmp_path / ".vg"
    elif location == ".planning":
        target_dir = tmp_path / ".planning"
    elif location == "root":
        target_dir = tmp_path
    else:
        raise ValueError(f"unknown location: {location}")
    target_dir.mkdir(parents=True, exist_ok=True)
    foundation = target_dir / "FOUNDATION.md"
    foundation.write_text(FOUNDATION_BODY, encoding="utf-8")
    return foundation


def _write_specs(phase_dir: Path, body: str) -> Path:
    specs = phase_dir / "SPECS.md"
    specs.write_text(body, encoding="utf-8")
    return specs


def _run_validator(phase_dir: Path, repo_root: Path) -> subprocess.CompletedProcess:
    """Invoke the validator with VG_REPO_ROOT pointed at the tmp tree."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(repo_root)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase-dir", str(phase_dir)],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace",
    )


def _parse_output(proc: subprocess.CompletedProcess) -> dict:
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    return json.loads(line)


# ─── Validator behavioural tests (4 verdict cases) ────────────────────


def test_pass_when_specs_cites_foundation_goal(tmp_path):
    """SPECS.md with explicit `F-XX` reference → PASS (rc=0)."""
    phase_dir = _make_phase_dir(tmp_path)
    _write_foundation(tmp_path)
    _write_specs(phase_dir, """\
# Phase 9.99 SPECS

## Goal
Implements F-04 (Backend topology = monolith Fastify) by adding the
order-events queue inside the existing Fastify monolith.

## Scope
In: queue persistence, retry policy.
Out: distributed worker pool.
""")

    proc = _run_validator(phase_dir, tmp_path)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["validator"] == "foundation-to-specs"
    assert out["verdict"] == "PASS"


def test_pass_when_specs_quotes_milestone(tmp_path):
    """SPECS.md without F-XX but with textual 'FOUNDATION.md' cite → PASS."""
    phase_dir = _make_phase_dir(tmp_path)
    _write_foundation(tmp_path)
    _write_specs(phase_dir, """\
# Phase 9.99 SPECS

## Goal
Per FOUNDATION.md § 4 (Decisions), this phase realizes the
Milestone goal: 'Postgres-backed event queue' established at project bootstrap.

## Scope
In: queue persistence.
Out: distributed worker pool.
""")

    proc = _run_validator(phase_dir, tmp_path)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "PASS"


def test_block_when_specs_no_citation(tmp_path):
    """FOUNDATION exists with goals + SPECS has zero trace → BLOCK (rc=1)."""
    phase_dir = _make_phase_dir(tmp_path)
    _write_foundation(tmp_path)
    _write_specs(phase_dir, """\
# Phase 9.99 SPECS

## Goal
Add a queue. Make sure it's fast. Use Postgres.

## Scope
In: queue persistence.
Out: distributed worker pool.

## Constraints
Latency p99 < 100ms.
""")

    proc = _run_validator(phase_dir, tmp_path)
    assert proc.returncode == 1, (
        f"Expected BLOCK rc=1, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK"
    types = {e.get("type") for e in out["evidence"]}
    assert "foundation_trace_missing" in types, types


def test_warn_when_foundation_absent(tmp_path):
    """No FOUNDATION.md anywhere → WARN (rc=0). Legacy/bootstrap project."""
    phase_dir = _make_phase_dir(tmp_path)
    # Note: NOT writing FOUNDATION.md
    _write_specs(phase_dir, """\
# Phase 9.99 SPECS

## Goal
Add a queue.

## Scope
In: queue persistence.
""")

    proc = _run_validator(phase_dir, tmp_path)
    assert proc.returncode == 0, (
        f"Expected WARN rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "WARN"
    types = {e.get("type") for e in out["evidence"]}
    assert "foundation_absent" in types, types


# ─── Multi-location resolution (1 case) ───────────────────────────────


@pytest.mark.parametrize("location", [".vg", ".planning", "root"])
def test_validator_handles_multiple_foundation_locations(tmp_path, location):
    """FOUNDATION.md at .vg/, .planning/, or repo root — all detected.

    Validator must traverse the canonical lookup order and find FOUNDATION
    regardless of which location the project uses (current convention is
    .vg/, legacy GSD uses .planning/, very early bootstrap may have it at
    root).
    """
    phase_dir = _make_phase_dir(tmp_path)
    _write_foundation(tmp_path, location=location)
    _write_specs(phase_dir, """\
# Phase 9.99 SPECS

## Goal
Implements F-01 (Platform = web-saas).

## Scope
In: web app surface.
""")

    proc = _run_validator(phase_dir, tmp_path)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0 for location={location}, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "PASS", (
        f"location={location}: expected PASS verdict, got {out['verdict']}"
    )


# ─── Frontmatter wiring tests (2 cases) ───────────────────────────────


def test_skill_md_frontmatter_has_override_flag():
    """commands/vg/specs.md `forbidden_without_override` list must include
    `--skip-foundation-trace`."""
    text = SPECS_MD.read_text(encoding="utf-8")
    assert "forbidden_without_override:" in text, (
        "specs.md missing `forbidden_without_override:` block"
    )
    assert (
        '"--skip-foundation-trace"' in text
        or "'--skip-foundation-trace'" in text
        or "- --skip-foundation-trace" in text
    ), (
        "specs.md `forbidden_without_override` does not list "
        "`--skip-foundation-trace`"
    )


def test_preflight_allowlist_has_override_flag():
    """commands/vg/_shared/specs/preflight.md must reference
    `--skip-foundation-trace` (so it is not silently dropped)."""
    text = PREFLIGHT_MD.read_text(encoding="utf-8")
    assert "--skip-foundation-trace" in text, (
        "preflight.md does not mention `--skip-foundation-trace` — "
        "flag will be silently dropped"
    )
    # Validator MUST be wired in
    assert "verify-foundation-to-specs.py" in text, (
        "preflight.md does not invoke verify-foundation-to-specs.py validator"
    )
