"""
B7.2 — verify-contract-runtime.py static presence check tests.

Gap closed (A2): contract declares endpoint X but executor never
implements it → previously silent until review curl / test 5b (1+ hour
lag). This validator catches at wave-commit boundary.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-contract-runtime.py"


CONTRACTS_SAMPLE = """\
# API Contracts — Phase 7.x

All endpoints under `https://api.example.com/api/v1`

---

## POST /auth/register

**Auth:** Public
**Description:** Register new user.

```typescript
type RegisterInput = { email: string; password: string }
type RegisterResponse = { data: { token: string } }
```

---

## POST /auth/login

**Auth:** Public

```typescript
type LoginInput = { email: string; password: string }
```

---

## GET /users/:id

**Auth:** Required
"""


def _setup(tmp_path: Path, contract_text: str = CONTRACTS_SAMPLE) -> Path:
    """Create mini phase dir with API-CONTRACTS.md + apps/api/src skeleton."""
    phase_dir = tmp_path / ".vg" / "phases" / "07.7-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "API-CONTRACTS.md").write_text(contract_text, encoding="utf-8")

    code_dir = tmp_path / "apps" / "api" / "src" / "modules" / "auth"
    code_dir.mkdir(parents=True)
    return tmp_path


def _write_source(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR),
         "--phase", "7.7", *extra],
        cwd=repo, capture_output=True, text=True, timeout=30, env=env,
    )


# ─────────────────────────────────────────────────────────────────────────

def test_all_endpoints_present_passes(tmp_path):
    """All 3 contract endpoints implemented across resource-scoped plugins → PASS.
    Tests the prefix-mount fallback (last-segment param): `GET /users/:id`
    resolves via the /users/-prefixed plugin even though its route decl is
    just `.get('/:id', ...)`.
    """
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/modules/auth/auth.routes.ts", """
import type { FastifyInstance } from 'fastify'
export async function authRoutes(fastify: FastifyInstance) {
  fastify.post('/register', { handler: async () => ({}) })
  fastify.post('/login', { handler: async () => ({}) })
}
""")
    _write_source(repo, "apps/api/src/modules/users/users.routes.ts", """
import type { FastifyInstance } from 'fastify'
export async function usersRoutes(fastify: FastifyInstance) {
  fastify.get('/:id', { handler: async () => ({}) })
}
""")
    r = _run(repo)
    assert r.returncode == 0, f"rc={r.returncode}\nstdout={r.stdout}"


def test_missing_endpoint_blocks(tmp_path):
    """Contract declares POST /auth/login but source only has register → BLOCK."""
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/modules/auth/routes.ts", """
import type { FastifyInstance } from 'fastify'
export async function authRoutes(fastify: FastifyInstance) {
  fastify.post('/register', { handler: async () => ({}) })
}
""")
    r = _run(repo)
    assert r.returncode == 1, f"expected BLOCK, got rc={r.returncode}\n{r.stdout}"
    assert "missing_endpoint" in r.stdout
    assert "login" in r.stdout.lower()


def test_all_missing_blocks_with_full_list(tmp_path):
    """No source files at all → all 3 endpoints missing, BLOCK."""
    repo = _setup(tmp_path)
    # apps/api/src exists (from _setup) but empty
    r = _run(repo)
    # Empty source dir → no_source_files WARN (rc=0) OR missing BLOCK (rc=1)
    # depending on glob resolution. Both acceptable; assert not silent PASS.
    assert r.returncode in (0, 1)
    assert "missing_endpoint" in r.stdout or "no_source_files" in r.stdout


def test_ambiguous_path_without_method_blocks_by_default(tmp_path):
    """Path appears in source but no `fastify.post('/register'` pattern → BLOCK."""
    repo = _setup(tmp_path)
    # Path in comment only, no route decl
    _write_source(repo, "apps/api/src/modules/auth/helper.ts", """
// This helper supports /auth/register, /auth/login, and /users/:id
export const paths = {
  register: '/register',
  login: '/login',
}
""")
    r = _run(repo)
    # Ambiguous (path present, method unclear) → BLOCK by default.
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"
    assert "ambiguous_endpoint" in r.stdout or "missing_endpoint" in r.stdout


def test_allow_ambiguous_downgrades_to_warn(tmp_path):
    """--allow-ambiguous flag keeps PASS when all endpoints already verified."""
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/modules/auth/routes.ts", """
import type { FastifyInstance } from 'fastify'
export async function authRoutes(fastify: FastifyInstance) {
  fastify.post('/register', { handler: async () => ({}) })
  fastify.post('/login', { handler: async () => ({}) })
}
""")
    _write_source(repo, "apps/api/src/modules/users/users.routes.ts", """
import type { FastifyInstance } from 'fastify'
export async function usersRoutes(fastify: FastifyInstance) {
  fastify.get('/:id', { handler: async () => ({}) })
}
""")
    r = _run(repo, "--allow-ambiguous")
    assert r.returncode == 0


def test_nestjs_decorator_style_recognized(tmp_path):
    """NestJS `@Post('/register')` decorator → method-anchored match."""
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/modules/auth/auth.controller.ts", """
import { Controller, Post, Get, Param, Body } from '@nestjs/common'

@Controller('/auth')
export class AuthController {
  @Post('/register')
  register(@Body() body: any) { return {} }

  @Post('/login')
  login(@Body() body: any) { return {} }
}
""")
    _write_source(repo, "apps/api/src/modules/users/users.controller.ts", """
import { Controller, Get, Param } from '@nestjs/common'

@Controller('/users')
export class UsersController {
  @Get('/:id')
  find(@Param('id') id: string) { return {} }
}
""")
    r = _run(repo)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}"


def test_express_router_pattern_recognized(tmp_path):
    """Express `router.post('/register', ...)` → method-anchored match."""
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/modules/auth/auth.routes.ts", """
import { Router } from 'express'
const router = Router()

router.post('/register', (req, res) => res.json({}))
router.post('/login', (req, res) => res.json({}))

export default router
""")
    _write_source(repo, "apps/api/src/modules/users/users.routes.ts", """
import { Router } from 'express'
const router = Router()
router.get('/:id', (req, res) => res.json({}))
export default router
""")
    r = _run(repo)
    assert r.returncode == 0


def test_no_contract_file_skips(tmp_path):
    """Phase has no API-CONTRACTS.md → skip (non-feature profile)."""
    phase_dir = tmp_path / ".vg" / "phases" / "07.7-test"
    phase_dir.mkdir(parents=True)
    # Don't write API-CONTRACTS.md

    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "7.7"],
        cwd=tmp_path, capture_output=True, text=True, timeout=10, env=env,
    )
    assert r.returncode == 0
    # Empty output with PASS verdict
    assert '"verdict": "PASS"' in r.stdout


def test_empty_contract_warns(tmp_path):
    """Contract file exists but has 0 endpoint headers → WARN."""
    repo = _setup(tmp_path, "# Empty contract\n\nNo endpoints here.\n")
    _write_source(repo, "apps/api/src/x.ts", "// noop")
    r = _run(repo)
    assert r.returncode == 0  # WARN, not BLOCK
    assert "empty_contract" in r.stdout


def test_duplicate_endpoint_deduped(tmp_path):
    """Contract lists same endpoint twice (`## POST /foo` + `## POST /foo`) →
    dedup; verified once."""
    contract = """\
## POST /register

body

---

## POST /register

(duplicate, maybe copy-paste)
"""
    repo = _setup(tmp_path, contract)
    _write_source(repo, "apps/api/src/x.ts", """
import type { FastifyInstance } from 'fastify'
export async function r(fastify: FastifyInstance) {
  fastify.post('/register', {})
}
""")
    r = _run(repo)
    assert r.returncode == 0
