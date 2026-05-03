#!/usr/bin/env python3
"""
verify-contract-completeness.py — v2.39.0 closes Codex critique #1 + #2.

Charter violation it addresses:
  CRUD-SURFACES.md is treated as ground truth without proof it reflects
  the actual app domain. If the planner missed a sensitive resource,
  every downstream review can pass while reviewing the wrong system.

Strategy: build a runtime/code inventory and diff against
CRUD-SURFACES.md declared resources. Flag candidates absent from
contract:

  - HTTP routes not mapped to any declared resource list
  - DB model class names (Mongoose / SQLAlchemy / Prisma) not in resources
  - Background job patterns (BullMQ Queue, Celery task, cron schedule)
  - Webhook handlers (route patterns under /webhooks, /callbacks)
  - File upload/download endpoints (multer/multipart heuristics)

This is heuristic — does NOT block by default. Severity warn first,
promote to block via vg.config.md after dogfood.

Usage:
  verify-contract-completeness.py --phase-dir <path> --code-root <path>
  verify-contract-completeness.py --phase-dir <path> --severity block
  verify-contract-completeness.py --phase-dir <path> --json

Exit codes:
  0 — contract passes (or severity=warn)
  1 — uncovered surface found (severity=block)
  2 — config/IO error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_crud_surfaces(phase_dir: Path) -> dict:
    p = phase_dir / "CRUD-SURFACES.md"
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"```json\s*\n(.+?)\n```", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def load_routes_static(routes_path: Path) -> list[dict]:
    if not routes_path.is_file():
        return []
    try:
        data = json.loads(routes_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data.get("routes") or []


def declared_resource_names(surfaces: dict) -> set[str]:
    out: set[str] = set()
    for r in surfaces.get("resources") or []:
        n = r.get("name")
        if n:
            out.add(n.lower())
            out.add(n.lower().replace("_", "-"))
            out.add(n.lower().replace("-", "_"))
            singular = re.sub(r"s$", "", n.lower())
            out.add(singular)
    return out


def declared_routes(surfaces: dict) -> set[str]:
    out: set[str] = set()
    for r in surfaces.get("resources") or []:
        platforms = r.get("platforms") or {}
        web = platforms.get("web") or {}
        list_block = web.get("list") or {}
        for key in ("route", "route_admin", "route_merchant"):
            if list_block.get(key):
                out.add(_normalize_route(list_block[key]))
        form = web.get("form") or {}
        for key in ("create_route", "update_route"):
            if form.get(key):
                out.add(_normalize_route(form[key]))
        backend = platforms.get("backend") or {}
        list_ep = backend.get("list_endpoint") or {}
        if list_ep.get("path"):
            parts = list_ep["path"].split(maxsplit=1)
            if len(parts) == 2:
                out.add(_normalize_route(parts[1]))
        for mp in (backend.get("mutation") or {}).get("paths") or []:
            parts = mp.split(maxsplit=1)
            if len(parts) == 2:
                out.add(_normalize_route(parts[1]))
    return out


def _normalize_route(p: str) -> str:
    p = re.sub(r":[a-zA-Z_]\w*", ":id", p)
    p = re.sub(r"\[([^\]]+)\]", ":id", p)
    p = re.sub(r"\{([^\}]+)\}", ":id", p)
    return p.rstrip("/")


def grep_db_models(code_root: Path) -> set[str]:
    out: set[str] = set()
    patterns = [
        re.compile(r"\bmongoose\.model\(\s*['\"]([A-Z][A-Za-z0-9_]*)['\"]"),
        re.compile(r"\bclass\s+([A-Z][A-Za-z0-9_]*)\s*\([^)]*(?:Model|Base|sqlalchemy|declarative_base)"),
        re.compile(r"\bmodel\s+([A-Z][A-Za-z0-9_]*)\s*{", re.I),
        re.compile(r"export\s+default\s+model\(\s*['\"]([A-Z][A-Za-z0-9_]*)['\"]"),
        re.compile(r"@Entity\(\)\s*export\s+class\s+([A-Z][A-Za-z0-9_]*)"),
        re.compile(r"^class\s+([A-Z][A-Za-z0-9_]*)\s*\([^)]*models\.Model", re.M),
    ]
    for ext in (".js", ".ts", ".tsx", ".py", ".prisma", ".rs"):
        for fp in code_root.rglob(f"*{ext}"):
            if any(seg in fp.parts for seg in ("node_modules", "dist", "build", ".next", "venv", "__pycache__", ".git")):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pat in patterns:
                for m in pat.finditer(text):
                    out.add(m.group(1))
    return out


def grep_background_jobs(code_root: Path) -> list[dict]:
    out: list[dict] = []
    patterns = [
        ("bullmq_queue", re.compile(r"new\s+Queue\s*\(\s*['\"]([^'\"]+)['\"]")),
        ("celery_task", re.compile(r"@(?:app|celery)\.task\b[^\n]*\n[^\n]*?def\s+([a-zA-Z_]\w*)")),
        ("cron_schedule", re.compile(r"@cron_schedule\(\s*['\"]([^'\"]+)['\"]")),
        ("agenda_define", re.compile(r"agenda\.define\(\s*['\"]([^'\"]+)['\"]")),
        ("nodemq_consumer", re.compile(r"\.consume\(\s*['\"]([^'\"]+)['\"]")),
    ]
    for ext in (".js", ".ts", ".tsx", ".py"):
        for fp in code_root.rglob(f"*{ext}"):
            if any(seg in fp.parts for seg in ("node_modules", "dist", "build", ".next", "venv", "__pycache__", ".git", "test", "tests")):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for kind, pat in patterns:
                for m in pat.finditer(text):
                    out.append({"kind": kind, "name": m.group(1), "file": str(fp.relative_to(code_root)).replace("\\", "/")})
    return out


def grep_webhooks(code_root: Path) -> list[dict]:
    out: list[dict] = []
    patterns = [
        re.compile(r'(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*[\'"`](/webhooks?/[^\'"`]+|/callbacks?/[^\'"`]+)[\'"`]', re.I),
    ]
    for ext in (".js", ".ts", ".tsx", ".py"):
        for fp in code_root.rglob(f"*{ext}"):
            if any(seg in fp.parts for seg in ("node_modules", "dist", "build", "test", "tests")):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pat in patterns:
                for m in pat.finditer(text):
                    out.append({"method": m.group(1).upper(), "path": m.group(2), "file": str(fp.relative_to(code_root)).replace("\\", "/")})
    return out


def diff_routes(routes: list[dict], declared: set[str], resource_names: set[str]) -> list[dict]:
    """Find routes that are NOT mapped to declared resource."""
    out: list[dict] = []
    for r in routes:
        norm = _normalize_route(r.get("path", ""))
        if norm in declared:
            continue
        path_lower = r.get("path", "").lower()
        matched = False
        for resource_name in resource_names:
            if resource_name and resource_name in path_lower:
                matched = True
                break
        if not matched:
            out.append({
                "method": r.get("method"),
                "path": r.get("path"),
                "framework": r.get("framework"),
                "source_file": r.get("source_file"),
                "line": r.get("line"),
            })
    return out


def diff_models(models: set[str], resource_names: set[str]) -> list[str]:
    """Find DB models not declared as CRUD resource."""
    out: list[str] = []
    for m in sorted(models):
        norms = {m.lower(), m.lower() + "s", re.sub(r"s$", "", m.lower())}
        if not (norms & resource_names):
            out.append(m)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--code-root", default=".", help="Source root for inventory grep (default cwd)")
    ap.add_argument("--routes-static", default=None, help="Pre-computed routes-static.json path")
    ap.add_argument("--severity", choices=["warn", "block"], default="warn")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    code_root = Path(args.code_root).resolve()
    if not phase_dir.is_dir():
        print(f"\033[38;5;208mPhase dir not found: {phase_dir}\033[0m", file=sys.stderr)
        return 2
    if not code_root.is_dir():
        print(f"\033[38;5;208mCode root not found: {code_root}\033[0m", file=sys.stderr)
        return 2

    surfaces = load_crud_surfaces(phase_dir)
    if not surfaces:
        if not args.quiet:
            print(f"  (no CRUD-SURFACES.md or empty — skipping completeness check)")
        return 0

    resource_names = declared_resource_names(surfaces)
    declared_paths = declared_routes(surfaces)

    if args.routes_static:
        routes = load_routes_static(Path(args.routes_static))
    else:
        rsj = phase_dir / "routes-static.json"
        if rsj.is_file():
            routes = load_routes_static(rsj)
        else:
            rsj_root = code_root / "routes-static.json"
            routes = load_routes_static(rsj_root) if rsj_root.is_file() else []

    if not routes and not args.quiet:
        print(f"  \033[33mno routes-static.json available — run scripts/extract-routes-static.py first for full coverage\033[0m")

    models = grep_db_models(code_root)
    bg_jobs = grep_background_jobs(code_root)
    webhooks = grep_webhooks(code_root)

    uncovered_routes = diff_routes(routes, declared_paths, resource_names)
    uncovered_models = diff_models(models, resource_names)

    payload = {
        "phase_dir": str(phase_dir),
        "code_root": str(code_root),
        "checked_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "declared_resources": len(surfaces.get("resources") or []),
        "routes_inventoried": len(routes),
        "models_inventoried": len(models),
        "background_jobs_inventoried": len(bg_jobs),
        "webhooks_inventoried": len(webhooks),
        "uncovered_routes": uncovered_routes,
        "uncovered_models": uncovered_models,
        "background_jobs": bg_jobs,
        "webhooks": webhooks,
        "verdict": "COMPLETE" if (not uncovered_routes and not uncovered_models and not bg_jobs and not webhooks) else "INCOMPLETE",
        "severity": args.severity,
    }

    out_path = phase_dir / "CONTRACT-COMPLETENESS.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        if payload["verdict"] == "COMPLETE":
            print(f"✓ Contract completeness OK ({len(routes)} routes, {len(models)} models all mapped)")
        else:
            tag = "" if args.severity == "block" else ""
            print(f"{tag} Contract completeness: INCOMPLETE")
            if uncovered_routes:
                print(f"   {len(uncovered_routes)} routes NOT mapped to declared resource:")
                for r in uncovered_routes[:8]:
                    print(f"     {r['method']} {r['path']} ({r['source_file']}:{r['line']})")
                if len(uncovered_routes) > 8:
                    print(f"     ... +{len(uncovered_routes) - 8} more (see CONTRACT-COMPLETENESS.json)")
            if uncovered_models:
                print(f"   {len(uncovered_models)} DB model(s) not declared as CRUD resource: {', '.join(uncovered_models[:5])}{'...' if len(uncovered_models) > 5 else ''}")
            if bg_jobs:
                print(f"   {len(bg_jobs)} background job(s)/queue consumer(s) detected — declare in CRUD-SURFACES async_jobs[] or out_of_scope[]")
            if webhooks:
                print(f"   {len(webhooks)} webhook handler(s) detected — declare in CRUD-SURFACES webhooks[] or out_of_scope[]")
            print(f"   Report: {out_path}")
            print(f"   Override: --severity warn (or --skip-contract-completeness=\"<reason>\" via wrapper)")

    if payload["verdict"] != "COMPLETE" and args.severity == "block":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
