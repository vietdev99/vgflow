"""v3.4.0 — #173 Stage 4: route inventory gate tests.

Coverage:
1. validator content + mirror byte-identity
2. fix-loop-and-goals.md adds verify-route-inventory to verdict gate loop
3. PASS when contract.route_inventory matches runtime views (normalized)
4. BLOCK when runtime view absent from contract (UNDECLARED)
5. BLOCK when contract route absent from runtime (UNREACHED)
6. PASS skip when contract missing
7. PASS skip when skip_reason populated
8. severity=warn downgrades BLOCK → WARN
9. path normalization (numeric/UUID → :id, trailing slash, query strip)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-route-inventory.py"
VALIDATOR_MIRROR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-route-inventory.py"
REVIEW_FIX_LOOP_CANON = REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "fix-loop-and-goals.md"


# ── content + wiring ──────────────────────────────────────────────────────


def test_validator_exists():
    assert VALIDATOR.is_file()
    body = VALIDATOR.read_text(encoding="utf-8")
    assert "def normalize_path" in body
    assert "collect_contract_routes" in body
    assert "collect_runtime_routes" in body
    assert "route_inventory_undeclared" in body
    assert "route_inventory_unreached" in body


def test_validator_mirror_byte_identity():
    assert VALIDATOR.read_bytes() == VALIDATOR_MIRROR.read_bytes()


def test_review_fix_loop_wires_validator():
    body = REVIEW_FIX_LOOP_CANON.read_text(encoding="utf-8")
    assert "verify-route-inventory" in body, (
        "review fix-loop-and-goals.md must include verify-route-inventory in verdict gate loop"
    )


# ── functional ────────────────────────────────────────────────────────────


def _write_phase(tmp_path: Path, contract: dict | None, rmap: dict | None) -> Path:
    phase = tmp_path / "phase-99"
    phase.mkdir()
    if contract is not None:
        (phase / "UI-RUNTIME-CONTRACT.json").write_text(json.dumps(contract), encoding="utf-8")
    if rmap is not None:
        (phase / "RUNTIME-MAP.json").write_text(json.dumps(rmap), encoding="utf-8")
    return phase


def _run(phase_dir: Path, extra: list[str] | None = None) -> tuple[int, str]:
    args = [sys.executable, str(VALIDATOR), "--phase-dir", str(phase_dir), "--json"]
    if extra:
        args.extend(extra)
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def _contract(routes: list[str], skip_reason: str | None = None) -> dict:
    return {
        "version": "1",
        "phase_id": "phase-99",
        "generated_at": "2026-05-11T00:00:00Z",
        "source_artifacts": {},
        "required_tailwind_tokens": [],
        "first_viewport_surfaces": [],
        "route_inventory": [{"path": r, "source": "test", "auth_required": True} for r in routes],
        "env_contract": {"status": "present"},
        "min_spec_count": {"count": 0, "source": "test"},
        "acceptance_criteria": ["test"],
        "skip_reason": skip_reason,
    }


def _rmap(views: list[str]) -> dict:
    return {"views": {v: {"elements": []} for v in views}, "goal_sequences": {}}


def test_pass_when_routes_match(tmp_path):
    phase = _write_phase(
        tmp_path,
        _contract(["/sites", "/users"]),
        _rmap(["/sites", "/users"]),
    )
    rc, out = _run(phase)
    assert rc == 0
    payload = json.loads(out.strip().split("\n")[0])
    assert payload["verdict"] == "PASS"


def test_block_undeclared_route(tmp_path):
    phase = _write_phase(
        tmp_path,
        _contract(["/sites"]),
        _rmap(["/sites", "/admin/secret"]),
    )
    rc, out = _run(phase)
    assert rc == 1
    payload = json.loads(out.strip().split("\n")[0])
    types = [e["type"] for e in payload["evidence"]]
    assert "route_inventory_undeclared" in types


def test_block_unreached_route(tmp_path):
    phase = _write_phase(
        tmp_path,
        _contract(["/sites", "/users", "/forgotten"]),
        _rmap(["/sites", "/users"]),
    )
    rc, out = _run(phase)
    assert rc == 1
    payload = json.loads(out.strip().split("\n")[0])
    types = [e["type"] for e in payload["evidence"]]
    assert "route_inventory_unreached" in types


def test_pass_skip_no_contract(tmp_path):
    phase = tmp_path / "phase-99"
    phase.mkdir()
    rc, out = _run(phase)
    assert rc == 0
    payload = json.loads(out.strip().split("\n")[0])
    types = [e["type"] for e in payload["evidence"]]
    assert "route_inventory_no_contract" in types


def test_pass_skip_when_skip_reason(tmp_path):
    phase = _write_phase(
        tmp_path,
        _contract(["/sites"], skip_reason="backend-only"),
        _rmap(["/never-visited"]),  # mismatch — but skip should win
    )
    rc, out = _run(phase)
    assert rc == 0
    payload = json.loads(out.strip().split("\n")[0])
    types = [e["type"] for e in payload["evidence"]]
    assert "route_inventory_skipped" in types


def test_severity_warn_downgrades(tmp_path):
    phase = _write_phase(
        tmp_path,
        _contract(["/sites"]),
        _rmap(["/admin/secret"]),
    )
    rc, out = _run(phase, extra=["--severity", "warn"])
    assert rc == 0
    payload = json.loads(out.strip().split("\n")[0])
    assert payload["verdict"] == "WARN"


def test_path_normalization_numeric(tmp_path):
    """Contract /sites/:id matches runtime /sites/42."""
    phase = _write_phase(
        tmp_path,
        _contract(["/sites/:id"]),
        _rmap(["/sites/42"]),
    )
    rc, out = _run(phase)
    assert rc == 0, f"numeric segment should normalize, got rc={rc}, out={out}"


def test_path_normalization_uuid(tmp_path):
    """Contract /sites/:id matches runtime /sites/<uuid>."""
    phase = _write_phase(
        tmp_path,
        _contract(["/sites/:id"]),
        _rmap(["/sites/3f7c2a14-9d12-4baa-a8e4-1234567890ab"]),
    )
    rc, out = _run(phase)
    assert rc == 0, f"UUID segment should normalize, got rc={rc}, out={out}"


def test_path_normalization_query_strip(tmp_path):
    """Runtime URL with query string normalizes to path."""
    phase = _write_phase(
        tmp_path,
        _contract(["/sites"]),
        _rmap(["https://app.example.com/sites?page=2"]),
    )
    rc, out = _run(phase)
    assert rc == 0, f"query string should strip, got rc={rc}, out={out}"


def test_path_normalization_trailing_slash(tmp_path):
    phase = _write_phase(
        tmp_path,
        _contract(["/sites"]),
        _rmap(["/sites/"]),
    )
    rc, out = _run(phase)
    assert rc == 0
