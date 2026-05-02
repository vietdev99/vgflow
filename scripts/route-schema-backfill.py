#!/usr/bin/env python3
"""Generate Zod-schema-attachment checklist + starter patch for legacy
Fastify route files (Phase 1-3 of PrintwayV3-style projects that shipped
without `fastify-type-provider-zod`).

Background: PR-D found 333 / 334 routes lacking Zod schema attachment
→ openapi.json published but empty → FE can't codegen types → /vg:review
Haiku scanner has no ground truth → 4xx noise.

Manual refactor of 30+ legacy route files = 30-40h work. This tool
mechanizes the SAFE part (import injection, withTypeProvider wrap,
empty schema scaffold per route) and surfaces the UNSAFE part (which
schemas to attach + response shape) as a checklist for human review.

What the tool does:
  1. Parse route file via regex (no AST dep)
  2. Detect each route registration: verb, path, handler reference
  3. Locate companion handler file + scan it for Zod schemas defined
     locally + `*.parse()` / `*.safeParse()` call sites
  4. Match schemas → routes (by handler name + parse target)
  5. Generate two outputs:
     a) {file}.backfill-checklist.md — per-route action items
     b) {file}.backfill.patch     — starter unified diff with
        withTypeProvider wrap + schema scaffold (TODOs for human)

What the tool does NOT do:
  - Auto-define response schemas (handler `reply.send(X)` shapes vary too
    much; user must inspect handler output type)
  - Apply diff (user reviews + git apply manually)
  - Verify TypeScript compile after apply (caller's responsibility)

CLI:
  python3 route-schema-backfill.py <route-file.ts> [--apply-stub]
  python3 route-schema-backfill.py --phase 3.1   # process all phase routes
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ─── Patterns ──────────────────────────────────────────────────────


ROUTE_RE = re.compile(
    r"(?P<indent>^[ \t]*)"
    r"(?P<obj>fastify|app|server|router|api|\w+)\s*\.\s*"
    r"(?P<verb>get|post|put|patch|delete|route|all)\s*\(\s*"
    r"(?P<rest>.*?)\)\s*;?\s*$",
    re.MULTILINE | re.DOTALL,
)

# Quick path/handler extraction (rest of `fastify.get(rest)`)
PATH_RE = re.compile(r"^['\"]([^'\"]+)['\"]")
HANDLER_REF_RE = re.compile(r"\b(\w+(?:Handler|Controller|Route))\b")

# Zod schema detection in handler file
SCHEMA_DEF_RE = re.compile(
    r"^(?:export\s+)?const\s+(\w+(?:Schema|Body|Params|Querystring|Reply|Response))\s*=\s*z\.",
    re.MULTILINE,
)
PARSE_CALL_RE = re.compile(
    r"(\w+(?:Schema|Body|Params))\s*\.\s*(?:safeParse|parse)\s*\(\s*"
    r"req(?:uest)?\s*\.\s*(body|params|query|querystring)",
)
# Existing withTypeProvider — skip if file already migrated
TYPE_PROVIDER_RE = re.compile(r"\.withTypeProvider\s*<\s*ZodTypeProvider\s*>")


# ─── Data classes ──────────────────────────────────────────────────


@dataclass
class RouteEntry:
    line_number: int
    verb: str
    path: str
    obj: str
    handler_ref: str | None
    raw_text: str
    suggested_body: str | None = None
    suggested_params: str | None = None
    suggested_querystring: str | None = None
    suggested_response: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class HandlerScan:
    handler_name: str
    schemas_defined: list[str] = field(default_factory=list)  # names
    body_schema: str | None = None
    params_schema: str | None = None
    query_schema: str | None = None
    response_inferred: str | None = None  # shape hint, not schema name


# ─── File helpers ──────────────────────────────────────────────────


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def find_companion_handler(routes_path: Path) -> Path | None:
    """Given X.routes.ts, look for X.handler.ts or handler/*.ts in same dir."""
    base = routes_path.stem.replace(".routes", "")
    parent = routes_path.parent
    candidates = [
        parent / f"{base}.handler.ts",
        parent / "handlers.ts",
        parent / "handler.ts",
        parent.parent / f"{base}.handler.ts",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Fallback: any *.handler.ts in same dir
    handlers = list(parent.glob("*.handler.ts"))
    if handlers:
        return handlers[0]
    return None


def scan_handlers_in_file(handler_path: Path) -> list[HandlerScan]:
    """Extract all handler functions + their Zod schema usage."""
    text = _read(handler_path)
    if not text:
        return []

    # Collect schemas defined in this file
    schemas = SCHEMA_DEF_RE.findall(text)

    # Locate handler functions: `export const fooHandler = ...` or
    # `export async function fooHandler(...)`
    handler_re = re.compile(
        r"(?:^|\n)(?:export\s+)?"
        r"(?:const|async\s+function|function)\s+"
        r"(\w+(?:Handler|Controller))\b",
    )

    out: list[HandlerScan] = []
    for m in handler_re.finditer(text):
        name = m.group(1)
        # Slice from this handler to next handler (or EOF)
        start = m.start()
        next_m = handler_re.search(text, m.end())
        end = next_m.start() if next_m else len(text)
        body = text[start:end]

        scan = HandlerScan(handler_name=name, schemas_defined=schemas)
        # Find parse calls in this handler body
        for pm in PARSE_CALL_RE.finditer(body):
            schema_name = pm.group(1)
            target = pm.group(2)
            if target == "body":
                scan.body_schema = schema_name
            elif target == "params":
                scan.params_schema = schema_name
            elif target in ("query", "querystring"):
                scan.query_schema = schema_name
        # Detect response — primitive heuristic
        send_m = re.search(
            r"(?:reply|res|response)\s*\.\s*(?:send|status\([0-9]+\)\.send)\s*\(",
            body,
        )
        if send_m:
            # Look at what's inside send(...) — first 200 chars after
            scan.response_inferred = "(detected reply.send — manual define needed)"
        out.append(scan)
    return out


def parse_routes(text: str) -> list[RouteEntry]:
    """Extract every route registration in the file."""
    routes: list[RouteEntry] = []
    for m in ROUTE_RE.finditer(text):
        verb = m.group("verb").lower()
        if verb in ("head", "options"):
            continue
        rest = m.group("rest")
        path_m = PATH_RE.search(rest)
        if not path_m:
            continue
        path = path_m.group(1)
        # Find handler reference (last word matching *Handler etc.)
        handler_refs = HANDLER_REF_RE.findall(rest)
        handler = handler_refs[-1] if handler_refs else None
        line_no = text[:m.start()].count("\n") + 1
        routes.append(RouteEntry(
            line_number=line_no,
            verb=verb,
            path=path,
            obj=m.group("obj"),
            handler_ref=handler,
            raw_text=m.group(0),
        ))
    return routes


# ─── Match routes → handlers → schemas ──────────────────────────────


def match_schemas(routes: list[RouteEntry], handlers: list[HandlerScan]) -> None:
    by_name = {h.handler_name: h for h in handlers}
    for r in routes:
        if not r.handler_ref:
            r.notes.append("⚠ no handler reference detected — manual lookup")
            continue
        h = by_name.get(r.handler_ref)
        if not h:
            r.notes.append(
                f"⚠ handler '{r.handler_ref}' not found in companion file"
            )
            continue
        if h.body_schema:
            r.suggested_body = h.body_schema
        if h.params_schema:
            r.suggested_params = h.params_schema
        if h.query_schema:
            r.suggested_querystring = h.query_schema
        if h.response_inferred:
            r.suggested_response = h.response_inferred
        # Verb-specific hints
        if r.verb in ("get",) and r.suggested_body:
            r.notes.append("⚠ GET with body schema — unusual, double-check")
        if r.verb in ("post", "put", "patch") and not r.suggested_body:
            r.notes.append(
                "⚠ mutation verb without body schema detected — "
                "handler may use `req.body.x` directly without parse(); "
                "define body schema from scratch"
            )
        if not r.suggested_response:
            r.notes.append(
                "⚠ response schema not inferred — read handler `reply.send()` "
                "or `return value` and define manually"
            )


# ─── Output ────────────────────────────────────────────────────────


def render_checklist(
    route_path: Path,
    handler_path: Path | None,
    routes: list[RouteEntry],
    already_migrated: bool,
) -> str:
    lines = [
        f"# Route schema backfill checklist — `{route_path.name}`",
        "",
        f"- Source: `{route_path}`",
        f"- Handler: `{handler_path}`" if handler_path else "- Handler: (not detected)",
        f"- Routes: {len(routes)}",
        f"- Already migrated: {'YES (skip)' if already_migrated else 'no — backfill needed'}",
        "",
    ]
    if already_migrated:
        lines.append("File already uses `withTypeProvider<ZodTypeProvider>()`. "
                     "Verify each route has `{ schema: ... }` then no further action.")
        return "\n".join(lines)

    lines += [
        "## Migration steps (in order)",
        "",
        "1. Add import at top of file:",
        "   ```ts",
        "   import type { ZodTypeProvider } from 'fastify-type-provider-zod';",
        "   ```",
        "",
        "2. At plugin entry, wrap fastify with type provider:",
        "   ```ts",
        "   const app = fastify.withTypeProvider<ZodTypeProvider>();",
        "   // (rename existing `fastify.X(...)` to `app.X(...)` below)",
        "   ```",
        "",
        "3. For each route below, attach `{ schema: { ... } }` per checklist:",
        "",
    ]

    for i, r in enumerate(routes, 1):
        lines += [
            f"### {i}. `{r.verb.upper()} {r.path}` (line {r.line_number})",
            f"   Handler: `{r.handler_ref or '(unknown)'}`",
            "",
            "   Schema attachments:",
        ]
        if r.suggested_body:
            lines.append(f"   - **body**: `{r.suggested_body}` ← detected in handler `safeParse(req.body)`")
        elif r.verb in ("post", "put", "patch"):
            lines.append("   - **body**: ⚠ NOT detected — define from scratch by reading handler")
        if r.suggested_params:
            lines.append(f"   - **params**: `{r.suggested_params}` ← detected")
        elif "/:" in r.path:
            lines.append("   - **params**: ⚠ path has `:param` but no schema detected — define manually")
        if r.suggested_querystring:
            lines.append(f"   - **querystring**: `{r.suggested_querystring}` ← detected")
        elif r.verb == "get":
            lines.append("   - **querystring**: optional — define if handler reads `req.query.X`")
        if r.suggested_response:
            lines.append(f"   - **response**: {r.suggested_response}")
        else:
            lines.append("   - **response**: ⚠ define from `reply.send(...)` or handler return type")
        if r.notes:
            lines.append("")
            for n in r.notes:
                lines.append(f"   {n}")
        lines.append("")

    lines += [
        "## After applying",
        "",
        "1. `pnpm tsc --noEmit -p apps/api/tsconfig.json` — must compile clean",
        "2. `pnpm test --filter=api -- {file}` — handler tests must still pass",
        "3. Boot API + curl `/api/v1/openapi.json` — should now show this route's schema",
        "4. Commit with message `refactor(api): attach Zod schemas to {module} routes (backfill)`",
        "",
    ]
    return "\n".join(lines)


def render_starter_patch(
    route_path: Path,
    text: str,
    routes: list[RouteEntry],
    already_migrated: bool,
) -> str:
    """Produce a unified-diff starter that adds withTypeProvider wrap +
    empty schema scaffold per route. User fills in TODO_* placeholders.
    """
    if already_migrated:
        return ""

    # We don't auto-rewrite existing route bodies — too risky. Instead:
    # output a NEW HEADER block with the imports + wrap + commented
    # template for one route as guidance.
    lines = [
        f"# Starter patch hint for {route_path.name}",
        "# (NOT a unified diff — copy/paste into editor as guide)",
        "",
        "# Add at top of file (after existing imports):",
        "import type { ZodTypeProvider } from 'fastify-type-provider-zod';",
        "",
        "# Inside the plugin function, add at the start:",
        "const app = fastify.withTypeProvider<ZodTypeProvider>();",
        "",
        "# Then for each route, change `fastify.X(...)` → `app.X(path, { schema: ... }, handler)`:",
        "",
    ]

    for r in routes:
        body_line = (
            f"      body: {r.suggested_body},"
            if r.suggested_body else
            f"      // body: TODO_{r.path.replace('/', '_')}_BodySchema,"
        )
        params_line = (
            f"      params: {r.suggested_params},"
            if r.suggested_params else
            ("      // params: TODO_ParamsSchema (path has :param)"
             if "/:" in r.path else "")
        )
        query_line = (
            f"      querystring: {r.suggested_querystring},"
            if r.suggested_querystring else "")
        resp_line = "      // response: { 200: TODO_ResponseSchema },"

        schema_block_lines = [body_line, params_line, query_line, resp_line]
        schema_block = "\n".join(filter(None, schema_block_lines))

        lines += [
            f"# Route: {r.verb.upper()} {r.path}",
            f"app.{r.verb}(",
            f"  '{r.path}',",
            "  {",
            "    schema: {",
            schema_block,
            "    },",
            f"    preHandler: [/* keep existing preHandlers */],",
            "  },",
            f"  {r.handler_ref or 'TODO_handler'},",
            ");",
            "",
        ]

    return "\n".join(lines)


# ─── Main ──────────────────────────────────────────────────────────


def process_file(route_path: Path, write_artifacts: bool) -> dict:
    text = _read(route_path)
    if not text:
        return {"path": str(route_path), "error": "empty or unreadable"}
    already_migrated = bool(TYPE_PROVIDER_RE.search(text))
    routes = parse_routes(text)
    handler_path = find_companion_handler(route_path)
    handlers = scan_handlers_in_file(handler_path) if handler_path else []
    match_schemas(routes, handlers)

    checklist = render_checklist(route_path, handler_path, routes, already_migrated)
    patch = render_starter_patch(route_path, text, routes, already_migrated)

    if write_artifacts and not already_migrated:
        cl_path = route_path.with_suffix(route_path.suffix + ".backfill-checklist.md")
        cl_path.write_text(checklist + "\n", encoding="utf-8")
        if patch:
            p_path = route_path.with_suffix(route_path.suffix + ".backfill.hint.txt")
            p_path.write_text(patch + "\n", encoding="utf-8")

    return {
        "path": str(route_path),
        "already_migrated": already_migrated,
        "routes": len(routes),
        "schemas_detected": sum(
            1 for r in routes
            if r.suggested_body or r.suggested_params or r.suggested_querystring
        ),
        "handler": str(handler_path) if handler_path else None,
    }


PHASE_TO_PATHS = {
    "3.1": ["wallet", "ledger"],
    "3.2": ["payments", "merchants"],
    "3.3": ["billing"],
    "3.4a": ["team", "auth", "users"],
    "3.4b": ["credit"],
    "3.5": ["billing", "notifications"],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help="Single route file to process")
    ap.add_argument("--phase", help="Process all routes for a phase (3.1-3.5)")
    ap.add_argument(
        "--api-src", default="apps/api/src/modules",
        help="Backend src root (relative to repo)",
    )
    ap.add_argument(
        "--repo-root",
        default=os.environ.get("VG_REPO_ROOT") or os.getcwd(),
    )
    ap.add_argument(
        "--apply-stub", action="store_true",
        help="Write checklist + hint files alongside route files",
    )
    args = ap.parse_args()

    if not args.file and not args.phase:
        ap.error("provide either a route file path or --phase X")

    repo = Path(args.repo_root).resolve()
    src_root = repo / args.api_src

    targets: list[Path] = []
    if args.file:
        targets = [Path(args.file).resolve()]
    elif args.phase:
        mods = PHASE_TO_PATHS.get(args.phase)
        if not mods:
            print(f"unknown phase '{args.phase}'", file=sys.stderr)
            return 2
        seen: set[Path] = set()
        for mod in mods:
            mod_dir = src_root / mod
            if not mod_dir.exists():
                continue
            for rf in mod_dir.rglob("*.routes.ts"):
                if rf not in seen:
                    seen.add(rf)
                    targets.append(rf)

    if not targets:
        print("no route files found", file=sys.stderr)
        return 1

    print(f"# Route schema backfill — {len(targets)} file(s)\n")
    for t in targets:
        result = process_file(t, write_artifacts=args.apply_stub)
        rel = t.relative_to(repo) if t.is_absolute() and repo in t.parents else t
        if result.get("already_migrated"):
            print(f"  ✓ {rel}: already migrated")
            continue
        if "error" in result:
            print(f"  ⛔ {rel}: {result['error']}")
            continue
        print(
            f"  → {rel}: {result['routes']} routes, "
            f"{result['schemas_detected']} schemas detected; "
            f"handler={result.get('handler', 'n/a')}"
        )
    if args.apply_stub:
        print(f"\nChecklist + hint files written alongside each route file.")
    else:
        print(f"\n(Pass --apply-stub to write per-file checklist + starter hint.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
