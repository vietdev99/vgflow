#!/usr/bin/env python3
"""
Validator: verify-input-validation.py

B8.2 (OHOK A3): contract declares request schema but executor may ship
endpoint that never CALLS the validator — paste Zod import, forget
.parse(), route silently accepts any payload.

This validator pairs with verify-contract-runtime.py: the latter checks
route existence, this one checks the validator actually executes.

Check per route file (heuristic):
  - File has schema import pattern: z./Zod/BaseModel/Joi/Yup/class-validator
  - File has at least one validator invocation within same file:
      * Zod: .parse( / .parseAsync( / .safeParse( / .safeParseAsync(
      * Pydantic: ModelName(**body) / ModelName.model_validate(
      * class-validator: validateOrReject( / validate(
      * NestJS pipe: @Body(  with pipe argument
      * Fastify schema attachment: schema: { body: X }
  - If schema import present but no invocation → BLOCK: dormant schema

Limitations (MVP — iteration 1):
  - File-level heuristic, not per-endpoint binding. If a file has
    1 schema + 1 .parse() + 5 routes, we assume the .parse() covers
    all routes (good enough for most codebases).
  - Doesn't verify request-body specifically — a .parse() on query
    string also counts. Run /vg:test invalid-input e2e for true check.
  - Doesn't cover GraphQL resolvers (separate validation surface).

Deferred:
  - Per-endpoint binding via AST parse
  - Response validation (separate concern — contract-runtime covers
    endpoint existence, response shape is harder to verify static)

Usage:
  verify-input-validation.py --phase <N>
  verify-input-validation.py --phase <N> --source-globs 'apps/api/src/**/*.ts'

Exit codes:
  0 PASS (no dormant schemas) or WARN (partial)
  1 BLOCK (schema imported but never invoked in routed file)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Import patterns — "this file uses a validation library"
SCHEMA_IMPORT_PATTERNS = [
    re.compile(r"(?:^|\n)\s*import\s+(?:\*\s+as\s+)?(?:\{[^}]*\b(?:z|Zod|zod)\b[^}]*\}|z|Zod|zod)\s+from\s+['\"]zod['\"]"),
    re.compile(r"from\s+pydantic\s+import\s+(?:[^;\n]*\b)?(?:BaseModel|Field|validator|model_validator)"),
    re.compile(r"from\s+['\"]class-validator['\"]\s*;?"),
    re.compile(r"from\s+['\"]joi['\"]\s*;?"),
    re.compile(r"from\s+['\"]yup['\"]\s*;?"),
    re.compile(r"(?:^|\n)\s*const\s+\w+\s*=\s*require\(['\"]zod['\"]\)"),
    re.compile(r"import\s+\*\s+as\s+Joi\s+from\s+['\"]joi['\"]"),
]

# Invocation patterns — "the schema is actually called"
INVOCATION_PATTERNS = [
    # Zod
    re.compile(r"\.(?:parse|parseAsync|safeParse|safeParseAsync)\s*\("),
    # Pydantic
    re.compile(r"\.model_validate(?:_json)?\s*\("),
    re.compile(r"(?:^|\W)\w+Model\s*\(\s*\*\*"),  # ModelName(**kwargs) Python
    # class-validator
    re.compile(r"\b(?:validateOrReject|validate)\s*\([^)]*\bbody\b"),
    # NestJS pipe on @Body/@Query/@Param
    re.compile(r"@(?:Body|Query|Param)\s*\(\s*\w+[^)]*\)"),
    # Fastify schema attachment
    re.compile(r"\bschema\s*:\s*\{[^}]*\b(?:body|querystring|params)\s*:"),
    # Joi validate — `.validate(` or `.validate:` (method chain or property ref)
    re.compile(r"\bJoi\.\w+[\s\S]{0,200}?\.\s*validate[\s\S]{0,30}?\("),
    # Joi `.validate` reference (end-of-chain access, not called yet —
    # common pattern: `const fn = schema.validate; fn(body)`)
    re.compile(r"\.\s*validate\b(?!\w)"),
    # Yup validate / validateSync
    re.compile(r"\.\s*(?:validate|validateSync)\s*\("),
]

# Route-definition marker — file must look like a route handler file,
# otherwise schema-only types file without invocation is normal (base
# schemas in packages/schemas/ don't need parse — consumers do).
ROUTE_MARKER_PATTERNS = [
    re.compile(r"(?:fastify|app|router)\.(?:get|post|put|patch|delete|head|options)\s*\("),
    re.compile(r"@(?:Get|Post|Put|Patch|Delete)\s*\("),
    re.compile(r"@RequestMapping|@app\.route"),
    re.compile(r"addRoute|route\s*\(\s*\{"),
]

DEFAULT_SOURCE_GLOBS = [
    "apps/*/src/**/*.ts",
    "apps/*/src/**/*.tsx",
    "apps/*/src/**/*.js",
    "apps/*/src/**/*.py",
    "apps/*/src/**/routes/**/*",
    "apps/*/src/**/*.routes.ts",
    "apps/*/src/**/*.controller.ts",
]


def _classify_file(path: Path) -> tuple[bool, bool, bool]:
    """Return (has_schema_import, has_invocation, has_route_def)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False, False, False

    schema = any(p.search(text) for p in SCHEMA_IMPORT_PATTERNS)
    invoked = any(p.search(text) for p in INVOCATION_PATTERNS)
    route = any(p.search(text) for p in ROUTE_MARKER_PATTERNS)
    return schema, invoked, route


def _scan_files(globs: list[str]) -> list[Path]:
    seen: set[Path] = set()
    files: list[Path] = []
    for pat in globs:
        try:
            for p in REPO_ROOT.glob(pat):
                if p.is_file() and p not in seen:
                    seen.add(p)
                    files.append(p)
                if len(files) >= 3000:
                    return files
        except Exception:
            continue
    return files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--source-globs", action="append", default=None)
    args = ap.parse_args()

    out = Output(validator="verify-input-validation")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        contracts_path = phase_dir / "API-CONTRACTS.md"
        if not contracts_path.exists():
            # No contract — nothing to validate against; skip
            emit_and_exit(out)

        globs = args.source_globs or DEFAULT_SOURCE_GLOBS
        files = _scan_files(globs)
        if not files:
            emit_and_exit(out)

        dormant: list[Path] = []         # schema imported, no invocation, IS route file
        ok: list[Path] = []              # schema + invocation + route
        schema_only_type_files: list[Path] = []  # schema + no invocation + NOT route

        for f in files:
            schema, invoked, route = _classify_file(f)
            if not schema:
                continue
            if route:
                if invoked:
                    ok.append(f)
                else:
                    dormant.append(f)
            else:
                # Type / schema declaration file — fine.
                schema_only_type_files.append(f)

        def _rel(p: Path) -> str:
            try:
                return str(p.relative_to(REPO_ROOT)).replace("\\", "/")
            except ValueError:
                return str(p)

        if dormant:
            sample = dormant[:10]
            out.add(Evidence(
                type="dormant_schema",
                message=t(
                    "input_validation.dormant_schema.message",
                    count=len(dormant),
                ),
                actual="; ".join(_rel(p) for p in sample),
                fix_hint=t("input_validation.dormant_schema.fix_hint"),
            ))
        elif ok:
            # All validated files actually invoke — emit advisory summary
            out.warn(Evidence(
                type="validation_verified",
                message=t(
                    "input_validation.validation_verified.message",
                    count=len(ok),
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
