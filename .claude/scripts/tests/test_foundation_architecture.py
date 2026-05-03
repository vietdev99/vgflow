"""
Phase D v2.5 (2026-04-23) — verify-foundation-architecture.py tests.

Validates FOUNDATION.md §9 "Architecture Lock" section:
- §9 missing + phase < cutover → WARN (grandfather)
- §9 missing + phase >= cutover → HARD BLOCK
- Subsection missing + phase >= cutover → HARD BLOCK
- Subsection header present but < 3 bullets → WARN
- FOUNDATION.md absent → SKIP (PASS, advisory)
- Config override for required_subsections honored
- Narration t() keys don't crash
- Validator registered in vg:blueprint + UNQUARANTINABLE
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = (
    REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-foundation-architecture.py"
)


# ── Fixture helpers ────────────────────────────────────────────────────────

def _setup(tmp_path: Path,
           foundation_md: str | None,
           config_md: str | None = None) -> Path:
    """Create a minimal repo fixture under tmp_path.

    - foundation_md: content for .planning/FOUNDATION.md  (None = don't create)
    - config_md: content for .claude/vg.config.md  (None = don't create)
    Copies narration YAML files so t() resolves properly.
    """
    # Copy narration YAML
    src_shared = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst_shared = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst_shared.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src_shared / name
        if s.exists():
            (dst_shared / name).write_text(
                s.read_text(encoding="utf-8"), encoding="utf-8"
            )

    if foundation_md is not None:
        planning = tmp_path / ".planning"
        planning.mkdir(parents=True, exist_ok=True)
        (planning / "FOUNDATION.md").write_text(foundation_md, encoding="utf-8")

    if config_md is not None:
        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "vg.config.md").write_text(config_md, encoding="utf-8")

    return tmp_path


def _run(repo: Path, phase: str = "9") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", phase],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )


def _parse(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        s = line.strip()
        if s.startswith("{"):
            return json.loads(s)
    raise AssertionError(f"no JSON in stdout:\n{stdout}")


# ── Fixtures ────────────────────────────────────────────────────────────────

def _full_section9() -> str:
    """FOUNDATION.md with §9 containing all 8 subsections, ≥3 bullets each."""
    return """\
# FOUNDATION

## 1. Vision

Some content.

## 9. Architecture Lock

### Tech Stack Matrix
- Language: TypeScript 5.x — typed safety across monorepo
- Framework: Fastify 4.x — low-overhead HTTP, plugin ecosystem
- Database: MongoDB 7 native driver + Zod schema validation

### Module Boundary
- apps/api — HTTP surface, routes, controllers
- apps/rtb-engine — Rust binary, no Node dependency
- packages/shared — cross-app types and utilities

### Folder Convention
- Route files in src/routes/{domain}/index.ts
- Tests colocated at src/routes/{domain}/index.test.ts
- Assets served from apps/web/public/

### Cross-Cutting Concerns
- Logging: pino structured JSON, correlation-id header injected
- Error handling: domain errors extend AppError, mapped to HTTP codes in plugin
- Async pattern: async/await everywhere, no callbacks

### Security Baseline
- Session: HttpOnly + Secure + SameSite=Strict cookies
- TLS: 1.2 minimum via HAProxy, 1.3 preferred
- Auth: JWT RS256 signed, 15min access + 7d refresh rotation

### Performance Baseline
- p95 target: 50ms RTB, 200ms API reads, 500ms API writes
- Cache: Redis 7 for sessions and hot bid data, TTL 5min
- Bundle: route-level code-split, max 250KB per route

### Testing Baseline
- Unit runner: Vitest with jsdom
- E2E: Playwright v1.40+, login via form only
- Coverage threshold: 80% lines for apps/api

### Model-Portable Code Style
- Explicit named exports (no default exports in lib code)
- Type annotations on all function signatures
- Import order: node stdlib → third-party → local (enforced by eslint)
"""


def _section9_one_bullet_each() -> str:
    """§9 present but each subsection has only 1 bullet — should WARN."""
    return """\
# FOUNDATION

## 9. Architecture Lock

### Tech Stack Matrix
- Language: TypeScript

### Module Boundary
- apps/api boundary

### Folder Convention
- Route files in src/

### Cross-Cutting Concerns
- Logging: pino

### Security Baseline
- Session: HttpOnly cookies

### Performance Baseline
- p95: 200ms

### Testing Baseline
- Unit: Vitest

### Model-Portable Code Style
- Named exports only
"""


def _section9_missing_two_subsections() -> str:
    """§9 present but missing folder_convention and code_style subsections."""
    return """\
# FOUNDATION

## 9. Architecture Lock

### Tech Stack Matrix
- Language: TypeScript 5.x
- Framework: Fastify 4.x
- Database: MongoDB 7

### Module Boundary
- apps/api — HTTP surface
- packages/shared — cross-app types
- Dependency rule: packages cannot import from apps

### Cross-Cutting Concerns
- Logging: pino structured JSON
- Error handling: domain errors mapped to HTTP
- Async: async/await throughout

### Security Baseline
- Session: HttpOnly + Secure cookies
- TLS 1.2 minimum
- CORS whitelist: vollx.com only

### Performance Baseline
- p95 API reads: 200ms
- Cache: Redis TTL 5min
- Bundle: max 250KB per route

### Testing Baseline
- Unit: Vitest
- E2E: Playwright
- Coverage: 80% lines
"""


def _foundation_no_section9() -> str:
    """FOUNDATION.md with no §9 at all."""
    return """\
# FOUNDATION

## 1. Vision
Some content.

## 2. Tech Principles
More content.
"""


# ── Tests ──────────────────────────────────────────────────────────────────

def test_full_section9_all_subsections_passes(tmp_path):
    """Full §9 with all 8 subsections ≥3 bullets each → PASS."""
    repo = _setup(tmp_path, _full_section9())
    r = _run(repo, phase="9")
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"
    assert out["evidence"] == []


def test_section9_missing_phase_below_cutover_warns(tmp_path):
    """§9 absent + phase 7 (< cutover 14) → WARN, rc=0."""
    repo = _setup(tmp_path, _foundation_no_section9())
    r = _run(repo, phase="7")
    out = _parse(r.stdout)
    assert r.returncode == 0, f"Expected rc=0 (WARN), got {r.returncode}\n{r.stdout}"
    assert out["verdict"] == "WARN"
    assert any(
        "section9_missing" in e["type"] for e in out["evidence"]
    ), f"Expected section9_missing evidence, got: {out['evidence']}"


def test_section9_missing_phase_at_cutover_blocks(tmp_path):
    """§9 absent + phase 14 (= cutover) → BLOCK, rc=1."""
    repo = _setup(tmp_path, _foundation_no_section9())
    r = _run(repo, phase="14")
    out = _parse(r.stdout)
    assert r.returncode == 1, f"Expected rc=1 (BLOCK), got {r.returncode}\n{r.stdout}"
    assert out["verdict"] == "BLOCK"
    ev_types = [e["type"] for e in out["evidence"]]
    assert "foundation_section9_missing" in ev_types


def test_subsection_missing_phase_at_cutover_blocks(tmp_path):
    """1 subsection missing + phase=14 → BLOCK."""
    repo = _setup(tmp_path, _section9_missing_two_subsections())
    r = _run(repo, phase="14")
    out = _parse(r.stdout)
    assert r.returncode == 1, f"Expected BLOCK rc=1\n{r.stdout}"
    assert out["verdict"] == "BLOCK"
    ev_types = [e["type"] for e in out["evidence"]]
    assert "foundation_subsection_missing" in ev_types


def test_all_headers_present_but_one_bullet_each_warns(tmp_path):
    """All 8 headers present but each has only 1 bullet → WARN, rc=0."""
    repo = _setup(tmp_path, _section9_one_bullet_each())
    r = _run(repo, phase="14")
    out = _parse(r.stdout)
    # Should not BLOCK — empty subsections are WARN only
    assert r.returncode == 0, f"Expected rc=0 (WARN), got {r.returncode}\n{r.stdout}"
    assert out["verdict"] == "WARN"
    ev_types = [e["type"] for e in out["evidence"]]
    assert "foundation_subsection_empty" in ev_types


def test_foundation_absent_skips(tmp_path):
    """No FOUNDATION.md at all → PASS (SKIP advisory, not a block)."""
    repo = _setup(tmp_path, foundation_md=None)
    r = _run(repo, phase="14")
    out = _parse(r.stdout)
    assert r.returncode == 0, f"Expected rc=0 (SKIP), got {r.returncode}\n{r.stdout}"
    assert out["verdict"] == "PASS"


def test_legacy_foundation_no_section9_phase7_warns(tmp_path):
    """Legacy FOUNDATION.md without §9, phase=7 → WARN (not BLOCK)."""
    legacy = """\
# Foundation Document

## Tech Stack
We use Node.js and MongoDB.

## Principles
Keep it simple.
"""
    repo = _setup(tmp_path, legacy)
    r = _run(repo, phase="7")
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "WARN"


def test_config_override_required_subsections(tmp_path):
    """Config sets required_subsections to only 4 → only those 4 checked."""
    # §9 has only tech_stack, module_boundary, security_baseline, testing_baseline
    partial_section9 = """\
# FOUNDATION

## 9. Architecture Lock

### Tech Stack Matrix
- Language: TypeScript 5.x
- Framework: Fastify 4.x
- Database: MongoDB 7

### Module Boundary
- apps/api boundary
- packages/shared — shared types
- Dependency: no circular imports

### Security Baseline
- HttpOnly + Secure cookies
- TLS 1.2 minimum
- CORS whitelist only

### Testing Baseline
- Unit: Vitest
- E2E: Playwright
- Coverage: 80%
"""
    # Config says only require these 4
    config = """\
architecture:
  required_subsections: [tech_stack, module_boundary, security_baseline, testing_baseline]
"""
    repo = _setup(tmp_path, partial_section9, config_md=config)
    r = _run(repo, phase="14")
    out = _parse(r.stdout)
    # Should PASS — only 4 required, all 4 present with ≥3 bullets
    assert r.returncode == 0, f"Expected PASS rc=0\n{r.stdout}\n{r.stderr}"
    assert out["verdict"] == "PASS"


def test_narration_keys_render_without_crash(tmp_path):
    """t() calls in validator don't crash — narration YAML is loadable."""
    # Trigger a WARN path (§9 missing, phase < cutover) and check
    # that evidence message is a non-empty human string (not a raw key).
    repo = _setup(tmp_path, _foundation_no_section9())
    r = _run(repo, phase="7")
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["evidence"], "Expected at least one evidence entry"
    for ev in out["evidence"]:
        msg = ev.get("message", "")
        # Should not be the raw key literal
        assert not msg.startswith("foundation_arch."), (
            f"Narration key not resolved: {msg!r}"
        )
        assert len(msg) > 10, f"Message suspiciously short: {msg!r}"


def test_validator_registered_in_blueprint_and_unquarantinable():
    """verify-foundation-architecture registered in vg:blueprint + UNQUARANTINABLE."""
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main",
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_main"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    assert "verify-foundation-architecture" in mod.COMMAND_VALIDATORS.get(
        "vg:blueprint", []
    ), "Missing from COMMAND_VALIDATORS['vg:blueprint']"
    assert "verify-foundation-architecture" in mod.UNQUARANTINABLE, (
        "Missing from UNQUARANTINABLE"
    )


def test_section9_above_cutover_via_decimal_phase(tmp_path):
    """Phase 14.5 (decimal, > cutover 14) still triggers BLOCK on missing §9."""
    repo = _setup(tmp_path, _foundation_no_section9())
    r = _run(repo, phase="14.5")
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert out["verdict"] == "BLOCK"


def test_foundation_in_vg_fallback_path(tmp_path):
    """FOUNDATION.md in .vg/ (not .planning/) is found via fallback."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir(parents=True, exist_ok=True)
    (vg_dir / "FOUNDATION.md").write_text(_full_section9(), encoding="utf-8")
    # Copy narration YAML
    src_shared = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst_shared = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst_shared.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src_shared / name
        if s.exists():
            (dst_shared / name).write_text(s.read_text(encoding="utf-8"), encoding="utf-8")
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "14"],
        cwd=tmp_path, capture_output=True, text=True, timeout=20, env=env,
    )
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"
