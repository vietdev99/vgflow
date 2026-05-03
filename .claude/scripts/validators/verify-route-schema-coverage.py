#!/usr/bin/env python3
"""Verify Fastify routes declare schema (validation + OpenAPI generation).

Background: PrintwayV3 P1.D-24/54 chose
  fastify-type-provider-zod + @fastify/swagger + @fastify/swagger-ui
as the canonical stack. Routes attach Zod schemas via
  fastify.withTypeProvider<ZodTypeProvider>().<verb>(path, { schema })
which auto-generates OpenAPI 3.x and validates request/response.

Reality check (audit 2026-05-02): 334 route registrations, 0 routes use
withTypeProvider, only 3 have a raw `schema:` block — 99% gap. Result:
openapi.json published at /api/v1/openapi.json is mostly empty, FE
codegen can't infer types, /vg:review Haiku scanner has no ground truth
for form values → 4xx noise from bogus test data.

This validator catches new routes shipped without schema. Threshold is
configurable (default 80%) so a phase can land 4 of 5 new routes
schema-attached without blocking on a single migration; existing 99%
gap requires a separate hygiene phase, not blocked by this gate.

Detection heuristic (regex, not AST — we don't need 100% precision).

Route declarations matched: fastify.{verb}(, app.{verb}(, server.{verb}(,
.withTypeProvider<ZodTypeProvider>().{verb}(, where verb is one of
{get, post, put, patch, delete, route, all}.

Schema attachment markers (any one counts as "has schema"):
  - `schema:` followed by `{` or an identifier ending in
    Schema/Body/Params/Querystring/Reply/Response,
  - file uses `.withTypeProvider<ZodTypeProvider>()` at least once
    (Zod auto-attaches schema to all routes in the chain).

CLI:
  --paths a/b c/d        — directories to scan (defaults: apps/api/src,
                           apps/server/src, packages/*/src)
  --threshold 0.8        — minimum coverage to PASS (block below)
  --severity block|warn  — default block
  --report-md PATH       — write per-file breakdown
  --baseline-file PATH   — store previous coverage; BLOCK only on
                           regression vs last accepted baseline
                           (closes "existing 99% gap" trap)
  --allow-coverage-regression  — override flag (logs override-debt)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, timer  # noqa: E402


# Route registration patterns — capture method + line number for evidence
ROUTE_RE = re.compile(
    r"\b(?:fastify|app|server|router|api)\s*\.\s*"
    r"(get|post|put|patch|delete|route|all|head|options)\s*\(",
    re.IGNORECASE,
)

# withTypeProvider chain — counts as schema-attached (Zod auto-attaches)
TYPE_PROVIDER_RE = re.compile(
    r"\.withTypeProvider\s*<\s*ZodTypeProvider\s*>\s*\(\s*\)",
)

# In-block schema attachment markers
SCHEMA_BLOCK_RE = re.compile(
    r"schema\s*:\s*[{\w]",
)
# Schema imported and referenced (e.g. `schema: createTopupBodySchema`)
SCHEMA_IDENT_RE = re.compile(
    r"schema\s*:\s*\w+(?:Schema|Body|Params|Querystring|Reply|Response)",
)


@dataclass
class FileScan:
    path: str
    total_routes: int = 0
    schema_routes: int = 0
    type_provider_used: bool = False
    sample_unschema_lines: list[int] = field(default_factory=list)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def scan_file(p: Path) -> FileScan:
    text = _read(p)
    fs = FileScan(path=str(p))
    if not text:
        return fs

    # File-level signal: withTypeProvider used → all routes in this file
    # are "schema-attached" via the type provider chain.
    fs.type_provider_used = bool(TYPE_PROVIDER_RE.search(text))

    # Count routes by walking matches; check a small lookahead window
    # for schema markers to associate route ↔ schema.
    for m in ROUTE_RE.finditer(text):
        verb = m.group(1).lower()
        if verb in ("head", "options"):
            # Skip pre-flight/CORS noise
            continue
        fs.total_routes += 1
        # Look at next 500 chars — fastify route call signature
        # `fastify.get('/path', { schema: ..., ... }, handler)` is usually
        # one line or a few lines.
        window = text[m.start():m.start() + 500]
        if (
            fs.type_provider_used
            or SCHEMA_BLOCK_RE.search(window)
            or SCHEMA_IDENT_RE.search(window)
        ):
            fs.schema_routes += 1
        else:
            line_no = text[:m.start()].count("\n") + 1
            if len(fs.sample_unschema_lines) < 3:
                fs.sample_unschema_lines.append(line_no)
    return fs


def discover_route_files(roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.ts"):
            if any(part in ("node_modules", "dist", "build", ".next")
                   for part in p.parts):
                continue
            # Heuristic: file must contain at least one route registration
            # OR have "route" / "router" / "controller" in its name. Avoids
            # scanning every type-only .ts file.
            stem = p.stem.lower()
            looks_like_route = any(
                t in stem for t in ("route", "router", "controller", "handler")
            )
            if not looks_like_route:
                # Quick read to check for fastify call
                text = _read(p)
                if not ROUTE_RE.search(text):
                    continue
            if p in seen:
                continue
            seen.add(p)
            out.append(p)
    return sorted(out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify Fastify routes declare schema (P1.D-24/54).",
    )
    parser.add_argument(
        "--paths", nargs="*",
        default=["apps/api/src", "apps/server/src"],
        help="Directories to scan (relative to --repo-root)",
    )
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("VG_REPO_ROOT") or os.getcwd(),
    )
    parser.add_argument(
        "--threshold", type=float, default=0.8,
        help="Minimum schema coverage (0.0-1.0). Default 0.8 = 80%%.",
    )
    parser.add_argument(
        "--severity", choices=["block", "warn"], default="block",
    )
    parser.add_argument(
        "--baseline-file",
        help="Path to baseline JSON; BLOCK only on regression vs baseline. "
             "Lets a phase land alongside existing legacy gap without "
             "demanding an immediate cleanup.",
    )
    parser.add_argument(
        "--allow-coverage-regression", action="store_true",
        help="Override: tolerate coverage regression. Logs override-debt.",
    )
    parser.add_argument("--report-md", help="Write per-file markdown report.")
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    out = Output(validator="route-schema-coverage")

    with timer(out):
        roots = [(repo / p) for p in args.paths]
        files = discover_route_files(roots)
        scans = [scan_file(p) for p in files]

        total = sum(s.total_routes for s in scans)
        schemed = sum(s.schema_routes for s in scans)
        coverage = (schemed / total) if total else 1.0

        out.add(
            Evidence(
                type="coverage_summary",
                message=(
                    f"Fastify route schema coverage: {schemed}/{total} = "
                    f"{coverage*100:.1f}% across {len(files)} files. "
                    f"Threshold: {args.threshold*100:.0f}%."
                ),
            ),
            escalate=False,
        )

        # Baseline regression check
        prev_coverage = None
        if args.baseline_file:
            bp = Path(args.baseline_file)
            if bp.exists():
                try:
                    prev = json.loads(bp.read_text(encoding="utf-8"))
                    prev_coverage = prev.get("coverage")
                except json.JSONDecodeError:
                    pass

        is_regression = (
            prev_coverage is not None and coverage < prev_coverage - 0.01
        )
        below_threshold = coverage < args.threshold
        # BLOCK criteria:
        #   - if baseline given: regression only (legacy gap tolerated)
        #   - else: below threshold (strict)
        gate_fail = is_regression if prev_coverage is not None else below_threshold

        if gate_fail and not args.allow_coverage_regression:
            severity_active = args.severity == "block"
            if is_regression:
                msg = (
                    f"Route schema coverage REGRESSED: was "
                    f"{prev_coverage*100:.1f}%, now {coverage*100:.1f}%."
                )
            else:
                msg = (
                    f"Route schema coverage {coverage*100:.1f}% is below "
                    f"threshold {args.threshold*100:.0f}%."
                )
            fix_hint = (
                "Attach Zod schema via fastify-type-provider-zod: "
                "`fastify.withTypeProvider<ZodTypeProvider>().post(path, "
                "{ schema: { body: bodySchema, response: { 200: replySchema } } }, "
                "handler)`. See plugins/swagger.ts for the canonical setup."
            )
            out.add(
                Evidence(
                    type="schema_coverage_gate", message=msg,
                    fix_hint=fix_hint,
                ),
                escalate=severity_active,
            )

        # Top offenders (files with lowest schema ratio + ≥3 routes)
        offenders = [
            s for s in scans
            if s.total_routes >= 3 and s.schema_routes < s.total_routes
        ]
        offenders.sort(
            key=lambda s: (s.schema_routes / s.total_routes if s.total_routes else 1.0),
        )
        for s in offenders[:8]:
            ratio = s.schema_routes / s.total_routes if s.total_routes else 1.0
            out.add(
                Evidence(
                    type="route_schema_gap",
                    message=(
                        f"{Path(s.path).relative_to(repo)}: "
                        f"{s.schema_routes}/{s.total_routes} routes have schema "
                        f"({ratio*100:.0f}%)"
                    ),
                    file=s.path,
                    line=(s.sample_unschema_lines[0] if s.sample_unschema_lines else None),
                ),
                escalate=False,
            )

        # Optional markdown report
        if args.report_md:
            _write_report(Path(args.report_md), scans, total, schemed, coverage)

        # Severity downgrade
        if gate_fail and args.severity == "warn":
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"Coverage gate failure downgraded to WARN (--severity warn)",
                ),
                escalate=False,
            )

        # Update baseline if PASS
        if args.baseline_file and not gate_fail:
            bp = Path(args.baseline_file)
            bp.parent.mkdir(parents=True, exist_ok=True)
            bp.write_text(
                json.dumps({
                    "coverage": coverage,
                    "schemed": schemed,
                    "total": total,
                    "files": len(files),
                }, indent=2) + "\n",
                encoding="utf-8",
            )

    emit_and_exit(out)


def _write_report(path: Path, scans, total, schemed, coverage) -> None:
    lines = [
        "# Route Schema Coverage",
        "",
        f"Total routes: {total}",
        f"Routes with schema: {schemed}",
        f"Coverage: {coverage*100:.1f}%",
        "",
        "## Per-file breakdown",
        "",
        "| File | Routes | With schema | Coverage | Type provider |",
        "|------|--------|-------------|----------|---------------|",
    ]
    for s in sorted(scans, key=lambda x: x.path):
        if s.total_routes == 0:
            continue
        ratio = s.schema_routes / s.total_routes if s.total_routes else 1.0
        tp = "✓" if s.type_provider_used else "—"
        lines.append(
            f"| `{s.path}` | {s.total_routes} | {s.schema_routes} | "
            f"{ratio*100:.0f}% | {tp} |"
        )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
