"""
Tests for verify-container-hardening.py — Phase M Batch 1 of v2.5.2.

Pure-static checks on Dockerfile + docker-compose. No network needed.

Covers:
  - Well-hardened Dockerfile → OK
  - USER root → BLOCK
  - latest tag → BLOCK
  - Missing HEALTHCHECK → WARN
  - Compose missing cap_drop → WARN
  - No Dockerfile (default: skip, exit 0)
  - Multi-stage build detected → OK + INFO
  - JSON output parseable
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "verify-container-hardening.py"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=10, env=env,
        encoding="utf-8", errors="replace",
    )


HARDENED_DOCKERFILE = """\
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json ./
RUN npm ci

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/node_modules ./node_modules
COPY . .
USER node
HEALTHCHECK --interval=30s CMD wget -q http://localhost:3000/health || exit 1
CMD ["node", "server.js"]
"""

ROOT_DOCKERFILE = """\
FROM node:20-alpine
WORKDIR /app
COPY . .
CMD ["node", "server.js"]
"""

LATEST_DOCKERFILE = """\
FROM node:latest
WORKDIR /app
USER node
HEALTHCHECK CMD true
CMD ["node", "server.js"]
"""

MINIMAL_COMPOSE_HARDENED = """\
services:
  api:
    image: myapi:1.0
    read_only: true
    cap_drop:
      - ALL
    mem_limit: 512m
"""

MINIMAL_COMPOSE_WEAK = """\
services:
  api:
    image: myapi:1.0
"""


class TestContainerHardening:
    def test_well_hardened_passes(self, tmp_path):
        df = tmp_path / "Dockerfile"
        df.write_text(HARDENED_DOCKERFILE, encoding="utf-8")
        r = _run(["--dockerfile", str(df), "--quiet"])
        assert r.returncode == 0, (r.stdout, r.stderr)

    def test_root_user_blocks(self, tmp_path):
        df = tmp_path / "Dockerfile"
        df.write_text(ROOT_DOCKERFILE, encoding="utf-8")
        r = _run(["--dockerfile", str(df)])
        assert r.returncode == 1
        assert "root" in r.stdout.lower() or "no_user" in r.stdout.lower()

    def test_latest_tag_blocks(self, tmp_path):
        df = tmp_path / "Dockerfile"
        df.write_text(LATEST_DOCKERFILE, encoding="utf-8")
        r = _run(["--dockerfile", str(df)])
        assert r.returncode == 1
        assert "latest" in r.stdout.lower()

    def test_missing_healthcheck_warns(self, tmp_path):
        df = tmp_path / "Dockerfile"
        # Has everything except HEALTHCHECK
        df.write_text("""\
FROM node:20-alpine
WORKDIR /app
USER node
CMD ["node"]
""", encoding="utf-8")
        r = _run(["--dockerfile", str(df)])
        assert r.returncode == 0
        assert "HEALTHCHECK" in r.stdout or "healthcheck" in r.stdout.lower()

    def test_compose_missing_cap_drop_warns(self, tmp_path):
        df = tmp_path / "Dockerfile"
        df.write_text(HARDENED_DOCKERFILE, encoding="utf-8")
        compose = tmp_path / "docker-compose.yml"
        compose.write_text(MINIMAL_COMPOSE_WEAK, encoding="utf-8")
        r = _run(["--dockerfile", str(df), "--compose", str(compose)])
        assert r.returncode == 0  # only warns
        assert "cap_drop" in r.stdout.lower() or "readonly" in r.stdout.lower()

    def test_no_dockerfile_skips_by_default(self, tmp_path):
        # empty dir, auto-detect finds nothing
        r = _run(["--project-root", str(tmp_path)])
        assert r.returncode == 0

    def test_no_dockerfile_with_require_blocks(self, tmp_path):
        r = _run(["--project-root", str(tmp_path), "--require"])
        assert r.returncode == 1

    def test_multi_stage_detected(self, tmp_path):
        df = tmp_path / "Dockerfile"
        df.write_text(HARDENED_DOCKERFILE, encoding="utf-8")
        r = _run(["--dockerfile", str(df), "--json"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        # Should see an INFO about multi-stage
        infos = [v for v in data["violations"]
                 if v.get("severity") == "INFO"]
        assert any("multi" in (v.get("check") or "") for v in infos)

    def test_json_output_parseable(self, tmp_path):
        df = tmp_path / "Dockerfile"
        df.write_text(HARDENED_DOCKERFILE, encoding="utf-8")
        r = _run(["--dockerfile", str(df), "--json"])
        data = json.loads(r.stdout)
        assert "dockerfile" in data
        assert "violations" in data
        assert "block_count" in data
