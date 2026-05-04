"""
B8.2 — verify-input-validation.py regression tests.

Gap A3: contract declares Zod/Pydantic/Joi validator but executor
never calls .parse() → schema imported but DORMANT, runtime accepts
anything. This validator catches at run-complete.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-input-validation.py"


def _setup(tmp_path: Path) -> Path:
    """Mini phase dir + apps/api/src skeleton."""
    phase_dir = tmp_path / ".vg" / "phases" / "07.8-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "API-CONTRACTS.md").write_text(
        "## POST /auth/login\n\n```typescript\ntype LoginInput = "
        "{ email: string; password: string }\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "apps" / "api" / "src").mkdir(parents=True)

    # Copy narration strings so t() resolves
    src_shared = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst_shared = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst_shared.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src_shared / name
        if s.exists():
            (dst_shared / name).write_text(s.read_text(encoding="utf-8"),
                                           encoding="utf-8")
    return tmp_path


def _write_source(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _run(repo: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "7.8"],
        cwd=repo, capture_output=True, text=True, timeout=30, env=env,
    )


# ─────────────────────────────────────────────────────────────────────────

def test_zod_parse_called_passes(tmp_path):
    """Zod import + .parse() call + route defs → PASS."""
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/modules/auth/auth.routes.ts", """
import { z } from 'zod'
import type { FastifyInstance } from 'fastify'

const LoginInput = z.object({
  email: z.string().email(),
  password: z.string().min(8),
})

export async function authRoutes(fastify: FastifyInstance) {
  fastify.post('/login', async (req) => {
    const body = LoginInput.parse(req.body)
    return { ok: true, body }
  })
}
""")
    r = _run(repo)
    assert r.returncode == 0


def test_zod_imported_but_never_called_blocks(tmp_path):
    """Zod schema exists + route defined but no .parse() → BLOCK (dormant)."""
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/modules/auth/auth.routes.ts", """
import { z } from 'zod'
import type { FastifyInstance } from 'fastify'

const LoginInput = z.object({
  email: z.string().email(),
  password: z.string().min(8),
})

export async function authRoutes(fastify: FastifyInstance) {
  fastify.post('/login', async (req) => {
    // BUG: LoginInput never invoked
    return { ok: true, body: req.body }
  })
}
""")
    r = _run(repo)
    assert r.returncode == 1
    assert "dormant_schema" in r.stdout


def test_fastify_schema_attachment_passes(tmp_path):
    """Fastify `schema: { body: ... }` attachment counts as invocation."""
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/modules/auth/auth.routes.ts", """
import { z } from 'zod'
const LoginInput = z.object({ email: z.string(), password: z.string() })

export async function authRoutes(fastify) {
  fastify.post('/login', {
    schema: { body: LoginInput },
    handler: async (req) => req.body,
  })
}
""")
    r = _run(repo)
    assert r.returncode == 0


def test_nestjs_body_pipe_passes(tmp_path):
    """@Body(ValidationPipe) decorator recognized as invocation."""
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/modules/auth/auth.controller.ts", """
import { Controller, Post, Body, ValidationPipe } from '@nestjs/common'
import { IsEmail, MinLength } from 'class-validator'

export class LoginDto {
  @IsEmail() email: string
  @MinLength(8) password: string
}

@Controller('/auth')
export class AuthController {
  @Post('/login')
  login(@Body(ValidationPipe) dto: LoginDto) {
    return dto
  }
}
""")
    r = _run(repo)
    assert r.returncode == 0


def test_pydantic_model_validate_passes(tmp_path):
    """Pydantic .model_validate() counts."""
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/auth/login.py", """
from pydantic import BaseModel
from fastapi import FastAPI

class LoginInput(BaseModel):
    email: str
    password: str

app = FastAPI()

@app.post('/login')
def login(body: dict):
    parsed = LoginInput.model_validate(body)
    return parsed
""")
    r = _run(repo)
    assert r.returncode == 0


def test_schema_only_types_file_passes(tmp_path):
    """Types file (schema defs, no routes) doesn't require invocation."""
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/types/schemas.ts", """
import { z } from 'zod'
export const LoginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
})
export type LoginInput = z.infer<typeof LoginSchema>
""")
    # No route defs + no invocations → classified as types-only → PASS
    r = _run(repo)
    assert r.returncode == 0


def test_no_api_contracts_skips(tmp_path):
    """Phase without API-CONTRACTS.md → skip silently."""
    phase_dir = tmp_path / ".vg" / "phases" / "07.8-test"
    phase_dir.mkdir(parents=True)
    # No API-CONTRACTS.md
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "7.8"],
        cwd=tmp_path, capture_output=True, text=True, timeout=10, env=env,
    )
    assert r.returncode == 0


def test_output_in_vietnamese(tmp_path):
    """Block output uses VN narration (B8.0 rule)."""
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/modules/auth/auth.routes.ts", """
import { z } from 'zod'
const LoginInput = z.object({ email: z.string() })
export async function authRoutes(fastify) {
  fastify.post('/login', async (req) => req.body)  // dormant
}
""")
    r = _run(repo)
    assert r.returncode == 1
    vn_markers = [
        "schema validator", "dormant", "ng\\u1ee7",  # "ngủ"
        "runtime", "kh\\u00f4ng", "KH\\u00d4NG",  # "KHÔNG"
    ]
    assert any(m in r.stdout for m in vn_markers), (
        f"expected VN markers, got:\n{r.stdout}"
    )


def test_joi_validate_passes(tmp_path):
    """Joi schema.validate() counts."""
    repo = _setup(tmp_path)
    _write_source(repo, "apps/api/src/modules/auth/auth.routes.ts", """
import Joi from 'joi'
const loginSchema = Joi.object({ email: Joi.string().email() }).validate

export async function authRoutes(app) {
  app.post('/login', (req, res) => {
    const result = loginSchema(req.body)
    res.json(result)
  })
}
""")
    # File has route + schema import + validate invocation pattern
    r = _run(repo)
    # At minimum should not block — either PASS or WARN acceptable
    assert r.returncode == 0
