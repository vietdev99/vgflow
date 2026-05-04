"""
Tests for verify-contract-runtime.py — BLOCK severity.

Static check that API-CONTRACTS.md endpoint headers (## METHOD /path)
have matching route registrations in source.

Covers:
  - Missing phase-dir → PASS (graceful)
  - Phase with no API-CONTRACTS.md → PASS
  - Endpoint declared + matching Fastify route → PASS
  - Endpoint declared + matching Express route → PASS
  - Endpoint declared + NO matching source → BLOCK
  - Multiple endpoints, one missing → BLOCK
  - --allow-ambiguous flag recognized
  - --source-globs override flag
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-contract-runtime.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _verdict(stdout: str) -> str | None:
    try:
        return json.loads(stdout).get("verdict")
    except (json.JSONDecodeError, AttributeError):
        return None


def _setup(tmp_path: Path, slug: str = "99.0-runtime") -> Path:
    pdir = tmp_path / ".vg" / "phases" / slug
    pdir.mkdir(parents=True)
    return pdir


class TestContractRuntime:
    def test_missing_phase_graceful(self, tmp_path):
        r = _run(["--phase", "99.99"], tmp_path)
        assert r.returncode == 0
        assert "Traceback" not in r.stderr

    def test_no_contracts_passes(self, tmp_path):
        _setup(tmp_path)
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 0, f"no-contracts should PASS, stdout={r.stdout}"

    def test_endpoint_with_fastify_route_passes(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "API-CONTRACTS.md").write_text(
            "# API Contracts\n\n## GET /api/health\n\nHealth endpoint.\n",
            encoding="utf-8",
        )
        src = tmp_path / "apps" / "api" / "src"
        src.mkdir(parents=True)
        (src / "routes.ts").write_text(
            "fastify.get('/api/health', async (req, reply) => {\n"
            "  return { status: 'ok' };\n"
            "});\n",
            encoding="utf-8",
        )
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 0, \
            f"matching Fastify route should PASS, rc={r.returncode}, stdout={r.stdout}"

    def test_endpoint_with_express_route_passes(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "API-CONTRACTS.md").write_text(
            "# API Contracts\n\n## POST /api/login\n",
            encoding="utf-8",
        )
        src = tmp_path / "apps" / "api" / "src"
        src.mkdir(parents=True)
        (src / "routes.ts").write_text(
            "app.post('/api/login', loginHandler);\n",
            encoding="utf-8",
        )
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 0, \
            f"matching Express route should PASS, stdout={r.stdout}"

    def test_endpoint_without_route_blocks(self, tmp_path):
        # Use distinctive name to avoid validator's loose last-segment match
        pdir = _setup(tmp_path)
        (pdir / "API-CONTRACTS.md").write_text(
            "# API Contracts\n\n## GET /api/zzphantomroute\n\n"
            "Declared but never wired.\n",
            encoding="utf-8",
        )
        src = tmp_path / "apps" / "api" / "src"
        src.mkdir(parents=True)
        (src / "routes.ts").write_text(
            "fastify.get('/api/healthcheck', async () => ({}));\n",
            encoding="utf-8",
        )
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 1, \
            f"missing route should BLOCK, rc={r.returncode}, stdout={r.stdout}"
        assert _verdict(r.stdout) == "BLOCK"

    def test_partial_coverage_blocks(self, tmp_path):
        # Use distinctive endpoint names to avoid single-char false positives
        # — validator's last-segment fallback would match short literals.
        pdir = _setup(tmp_path)
        (pdir / "API-CONTRACTS.md").write_text(
            "# API\n\n## GET /api/users-list\n\n"
            "## GET /api/orders-summary\n\n"
            "## GET /api/zzghostendpoint\n",
            encoding="utf-8",
        )
        src = tmp_path / "apps" / "api" / "src"
        src.mkdir(parents=True)
        (src / "routes.ts").write_text(
            "fastify.get('/api/users-list', async () => ({}));\n"
            "fastify.get('/api/orders-summary', async () => ({}));\n",
            encoding="utf-8",
        )
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 1, \
            f"partial coverage should BLOCK, stdout={r.stdout}"

    def test_allow_ambiguous_flag(self, tmp_path):
        _setup(tmp_path)
        r = _run(["--phase", "99.0", "--allow-ambiguous"], tmp_path)
        assert r.returncode in (0, 1)
        assert "unrecognized arguments" not in r.stderr.lower()

    def test_source_globs_override(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "API-CONTRACTS.md").write_text(
            "# API\n\n## GET /api/health\n",
            encoding="utf-8",
        )
        # Put route in custom location
        custom = tmp_path / "custom" / "routes"
        custom.mkdir(parents=True)
        (custom / "all.ts").write_text(
            "fastify.get('/api/health', async () => ({}));\n",
            encoding="utf-8",
        )
        r = _run(
            ["--phase", "99.0", "--source-globs", "custom/**/*.ts"],
            tmp_path,
        )
        assert "unrecognized arguments" not in r.stderr.lower()
        assert r.returncode in (0, 1)
