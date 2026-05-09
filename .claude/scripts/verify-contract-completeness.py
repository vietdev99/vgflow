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


# v2.67.0 (Issue #159): centralized scan-skip directory list.
# Pre-fix: each rglob loop (grep_db_models / grep_background_jobs /
# grep_webhooks) inlined its own subset of skip names, so backup, archive,
# legacy, _archive, and .vg artifacts were scanned and polluted the
# inventory diff. Codex round 5 dogfood flagged stale `_backup/`
# routes/models showing up as "uncovered" findings even though they were
# explicitly retired code paths.
#
# Adding new skip names here applies to all three loops at once.
DEFAULT_SKIP_DIR_NAMES: tuple[str, ...] = (
    # canonical build/runtime directories (preserved from v2.39.0)
    "node_modules", "dist", "build", ".next", "venv", "__pycache__", ".git",
    # v2.67.0 #159 — exclude backup/archive/legacy by default so retired
    # code paths don't surface as uncovered routes/models/jobs/webhooks
    "_backup", "backup", "_archive", "archive", "legacy", "_legacy",
    # phase artifact tree shouldn't be scanned as production code
    ".vg",
)

# Background-jobs and webhooks loops historically also skip test trees so
# fixture queues/handlers don't pollute the inventory. Keep that behavior
# isolated to the loops that opted in (the models loop did NOT skip tests).
_TEST_SKIP_DIR_NAMES: tuple[str, ...] = ("test", "tests")


def _should_skip_path(path: Path, *, include_tests: bool = False) -> bool:
    """v2.67.0 #159 — return True if any path segment matches the
    centralized skip list. Case-insensitive on the segment name. Pass
    include_tests=True for the bg-jobs/webhooks loops which additionally
    skip `test`/`tests` directories.
    """
    parts_lower = [p.lower() for p in path.parts]
    skip_set = set(s.lower() for s in DEFAULT_SKIP_DIR_NAMES)
    if include_tests:
        skip_set.update(s.lower() for s in _TEST_SKIP_DIR_NAMES)
    return any(seg in skip_set for seg in parts_lower)


# v2.64.1 (Issue #147): profile-aware scope.
# Pre-fix: validator unconditionally grepped DB models, background jobs, and
# webhooks even on web-frontend-only phases, producing irrelevant warnings
# for the FE-only user. Skip BE inventory entirely on FE-only profiles, and
# skip FE-only signals on web-backend-only profiles.
_FRONTEND_ONLY_PROFILES = {"web-frontend-only"}
_BACKEND_ONLY_PROFILES = {"web-backend-only"}
_PROFILE_FRONTMATTER_RE = re.compile(
    r"^\s*(?:platform|surface|profile)\s*:\s*[\"']?([\w\-]+)[\"']?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_PROFILE_INLINE_RE = re.compile(
    r"^\s*\*\*\s*(?:Platform|Surface|Profile)\s*:?\s*\*\*\s*[`\"']?([\w\-]+)[`\"']?",
    re.IGNORECASE | re.MULTILINE,
)


def detect_phase_platform_profile(phase_dir: Path) -> str:
    """Lite mirror of phase-profile.sh's detect_phase_platform_profile.

    Reads frontmatter (platform/surface/profile) from SPECS.md, PLAN.md,
    TEST-GOALS.md, CONTEXT.md. Returns one of:
        web-fullstack | web-frontend-only | web-backend-only |
        mobile-* | cli-tool | library
    or "web-fullstack" as fallback.
    """
    valid = {
        "web-fullstack", "web-frontend-only", "web-backend-only",
        "mobile-rn", "mobile-flutter", "mobile-native-ios",
        "mobile-native-android", "mobile-hybrid", "cli-tool", "library",
    }
    for filename in ("SPECS.md", "PLAN.md", "TEST-GOALS.md", "CONTEXT.md"):
        fp = phase_dir / filename
        if not fp.is_file():
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Frontmatter block (between leading ---) takes priority.
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        scan_blocks = []
        if fm_match:
            scan_blocks.append(fm_match.group(1))
        scan_blocks.append(text)
        for block in scan_blocks:
            for m in _PROFILE_FRONTMATTER_RE.finditer(block):
                value = m.group(1).strip().lower()
                if value in valid:
                    return value
            for m in _PROFILE_INLINE_RE.finditer(block):
                value = m.group(1).strip().lower()
                if value in valid:
                    return value
    return "web-fullstack"


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


def grep_db_models(code_root: Path) -> tuple[set[str], int]:
    """v2.67.0 #159 — return (matched models, scanned file count).
    The scanned count gives cross-artifact reconciliation the real
    "files inspected" denominator alongside `len(out)` (the matches).
    """
    out: set[str] = set()
    scanned = 0
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
            # v2.67.0 #159 — centralized skip-list includes _backup, archive,
            # legacy, _archive, .vg in addition to node_modules/dist/...
            if _should_skip_path(fp):
                continue
            scanned += 1
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pat in patterns:
                for m in pat.finditer(text):
                    out.add(m.group(1))
    return out, scanned


def grep_background_jobs(code_root: Path) -> tuple[list[dict], int]:
    """v2.67.0 #159 — return (matched jobs, scanned file count)."""
    out: list[dict] = []
    scanned = 0
    patterns = [
        ("bullmq_queue", re.compile(r"new\s+Queue\s*\(\s*['\"]([^'\"]+)['\"]")),
        ("celery_task", re.compile(r"@(?:app|celery)\.task\b[^\n]*\n[^\n]*?def\s+([a-zA-Z_]\w*)")),
        ("cron_schedule", re.compile(r"@cron_schedule\(\s*['\"]([^'\"]+)['\"]")),
        ("agenda_define", re.compile(r"agenda\.define\(\s*['\"]([^'\"]+)['\"]")),
        ("nodemq_consumer", re.compile(r"\.consume\(\s*['\"]([^'\"]+)['\"]")),
    ]
    for ext in (".js", ".ts", ".tsx", ".py"):
        for fp in code_root.rglob(f"*{ext}"):
            # v2.67.0 #159 — also skips `test`/`tests` so fixture queues
            # don't pollute the inventory (parity with pre-fix loop behavior).
            if _should_skip_path(fp, include_tests=True):
                continue
            scanned += 1
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for kind, pat in patterns:
                for m in pat.finditer(text):
                    out.append({"kind": kind, "name": m.group(1), "file": str(fp.relative_to(code_root)).replace("\\", "/")})
    return out, scanned


def grep_webhooks(code_root: Path) -> tuple[list[dict], int]:
    """v2.67.0 #159 — return (matched webhooks, scanned file count)."""
    out: list[dict] = []
    scanned = 0
    patterns = [
        re.compile(r'(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*[\'"`](/webhooks?/[^\'"`]+|/callbacks?/[^\'"`]+)[\'"`]', re.I),
    ]
    for ext in (".js", ".ts", ".tsx", ".py"):
        for fp in code_root.rglob(f"*{ext}"):
            # v2.67.0 #159 — centralized skip + skip test trees.
            if _should_skip_path(fp, include_tests=True):
                continue
            scanned += 1
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pat in patterns:
                for m in pat.finditer(text):
                    out.append({"method": m.group(1).upper(), "path": m.group(2), "file": str(fp.relative_to(code_root)).replace("\\", "/")})
    return out, scanned


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

    # v2.64.1 (Issue #147) — profile-aware scope routing.
    platform_profile = detect_phase_platform_profile(phase_dir)
    is_fe_only = platform_profile in _FRONTEND_ONLY_PROFILES
    is_be_only = platform_profile in _BACKEND_ONLY_PROFILES

    if args.routes_static:
        routes = load_routes_static(Path(args.routes_static))
    else:
        rsj = phase_dir / "routes-static.json"
        if rsj.is_file():
            routes = load_routes_static(rsj)
        else:
            rsj_root = code_root / "routes-static.json"
            routes = load_routes_static(rsj_root) if rsj_root.is_file() else []

    # v2.67.0 #159 — track scanned file counts per loop so the output
    # JSON reports the inspected denominator alongside hit counts.
    scanned_models = 0
    scanned_jobs = 0
    scanned_webhooks = 0

    if is_fe_only:
        # Pure FE phase — backend route inventory not relevant. Skip the
        # routes-static.json warning entirely (it would only be needed for
        # BE coverage which we are not performing).
        routes = []
        models: set[str] = set()
        bg_jobs: list[dict] = []
        webhooks: list[dict] = []
        if not args.quiet:
            print(f"  profile={platform_profile} — skipping BE inventory (DB models, background jobs, webhooks)")
    else:
        if not routes and not args.quiet:
            print(f"  \033[33mno routes-static.json available — run scripts/extract-routes-static.py first for full coverage\033[0m")
        models, scanned_models = grep_db_models(code_root)
        bg_jobs, scanned_jobs = grep_background_jobs(code_root)
        webhooks, scanned_webhooks = grep_webhooks(code_root)
        if is_be_only and not args.quiet:
            # BE-only — keep BE inventory active, but downstream FE-only
            # warnings (route-vs-resource diff for SPA-only paths) are
            # irrelevant. The current diff already focuses on routes
            # declared by CRUD-SURFACES.md, so no extra suppression needed
            # for the BE-only path beyond surfacing the profile.
            print(f"  profile={platform_profile} — running BE inventory only")

    uncovered_routes = diff_routes(routes, declared_paths, resource_names)
    uncovered_models = diff_models(models, resource_names)

    payload = {
        "phase_dir": str(phase_dir),
        "code_root": str(code_root),
        "checked_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platform_profile": platform_profile,
        "declared_resources": len(surfaces.get("resources") or []),
        "routes_inventoried": len(routes),
        "models_inventoried": len(models),
        "background_jobs_inventoried": len(bg_jobs),
        "webhooks_inventoried": len(webhooks),
        # v2.67.0 #159 — scanned denominator per loop. *_inventoried counts
        # only matched items; scanned_*_count records files inspected (after
        # skip-list filter), giving cross-artifact reconciliation a stable
        # "files looked at" metric independent of pattern hit-rate.
        "scanned_models_count": scanned_models,
        "scanned_jobs_count": scanned_jobs,
        "scanned_webhooks_count": scanned_webhooks,
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
