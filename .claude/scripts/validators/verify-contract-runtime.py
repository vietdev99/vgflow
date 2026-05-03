#!/usr/bin/env python3
"""
Validator: verify-contract-runtime.py

B7.2 (OHOK gap A2): every endpoint declared in a phase's API-CONTRACTS.md
MUST have a matching route definition in source code. Phantom endpoints
(declared in contract, never implemented) previously surfaced only at
review step 5b curl or test 5b — 1+ hours after the wave committed.

This validator runs right after an executor wave commits and BEFORE the
next wave spawns so drift stops propagating.

Scope (MVP — iteration 1):
  - STATIC: parse `## METHOD /path` headers → search source for matching
    route registrations.
  - Framework-agnostic regex: matches Fastify / Express / Hono / NestJS /
    generic router patterns.
  - Evidence granularity: per-endpoint presence (pass | missing | ambiguous).

Deferred (iteration 2+, tracked in plan):
  - Zod / Pydantic schema wiring detection (verify-input-validation.py
    in B8.2 handles this).
  - Runtime curl verification against a live dev server.
  - Response shape matching against contract sample.

Usage:
  verify-contract-runtime.py --phase <N>
  verify-contract-runtime.py --phase <N> --source-globs 'apps/*/src/**/*.ts'

Exit codes:
  0  PASS or WARN (endpoints present; some ambiguous)
  1  BLOCK (one or more declared endpoints not found in source)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402
from _i18n import t  # noqa: E402 — B8.0: localized user-facing messages

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# API-CONTRACTS.md endpoint header: `## POST /auth/register` OR `### POST /...`
# (case-insensitive method). v2.45 fail-closed PR: relaxed to accept ## / ### / ####
# because Phase 3.2 dogfood used level-3 headers ("### POST /api/v1/...") under a
# level-2 group header ("## Topup Endpoints"), and the previous level-2-only regex
# parsed 0 endpoints + warned silently.
ENDPOINT_HEADER_RE = re.compile(
    r"^#{2,4}\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Default source-file globs — can be overridden via --source-globs or
# `contract_format.source_globs` in vg.config.md (future).
DEFAULT_SOURCE_GLOBS = [
    "apps/*/src/**/*.ts",
    "apps/*/src/**/*.tsx",
    "apps/*/src/**/*.js",
    "apps/*/src/**/*.jsx",
    "apps/*/src/**/*.py",
    "apps/*/src/**/*.rs",
    "packages/*/src/**/*.ts",
]


def parse_contract_endpoints(contracts_path: Path) -> list[tuple[str, str]]:
    """Return list of (METHOD, path) tuples from `## METHOD /path` headers."""
    if not contracts_path.exists():
        return []
    try:
        text = contracts_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    endpoints: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in ENDPOINT_HEADER_RE.finditer(text):
        method = m.group(1).upper()
        path = m.group(2).strip().rstrip("/")
        # Normalize bare slash (e.g. "POST /") but keep meaningful paths.
        if not path:
            path = "/"
        key = (method, path)
        if key in seen:
            continue
        seen.add(key)
        endpoints.append(key)
    return endpoints


def _path_search_patterns(path: str) -> list[re.Pattern[str]]:
    """Build regex patterns that could match this endpoint in source.

    We tolerate:
      - Routes registered with a prefix (so `/auth/register` matches
        `'/register'` inside an auth-prefixed plugin).
      - Path params: `/users/:id` in contract ↔ `/users/:id` OR `/users/${id}`.
      - Trailing slash variance.

    Strategy: match on the path's LAST meaningful segment (non-param),
    since that segment is the most unique + least likely to be shared.
    Fallback: match on the full path literal if last segment is a param.
    """
    patterns: list[re.Pattern[str]] = []

    # Normalize: split into segments, drop empty.
    segments = [s for s in path.split("/") if s]
    if not segments:
        # Root "/" — match literal route decl e.g. `.get('/', ...)`
        patterns.append(re.compile(r"""['"]/['"]"""))
        return patterns

    # Pattern 1: full path as literal string (quoted)
    full_escaped = re.escape(path)
    patterns.append(re.compile(rf"""['"`]{full_escaped}['"`/?]"""))

    # Pattern 2: match against the deepest non-param segment + adjacency
    last_static = None
    for seg in reversed(segments):
        if not seg.startswith(":") and not seg.startswith("{"):
            last_static = seg
            break

    if last_static:
        # Match `/<segment>` OR `/<segment>/` in source strings.
        # Constrain to route-like occurrence (quoted strings, route decorators).
        esc = re.escape(last_static)
        patterns.append(re.compile(
            rf"""['"`][^'"`]*/{esc}(?:['"`]|/[^'"`]*['"`])"""
        ))

    return patterns


def _method_anchored_pattern(method: str, path: str) -> re.Pattern[str]:
    """Regex matching `<router>.<method>(...'<path-ish>'...)` for the given
    HTTP method. Case-sensitive on method to avoid false hits (`getUser()`).

    Frameworks covered:
      - Fastify:     fastify.post('/x', ...)
      - Express:     app.post('/x', ...) / router.post('/x', ...)
      - Hono:        app.post('/x', ...)
      - NestJS:      @Post('/x')
      - Generic:     anything ending with .<method>(
    """
    method_lower = method.lower()
    method_cap = method.capitalize()
    # Last static segment for loose matching
    segments = [s for s in path.split("/") if s]
    last_static = ""
    for seg in reversed(segments):
        if not seg.startswith(":") and not seg.startswith("{"):
            last_static = seg
            break
    target = re.escape(last_static) if last_static else re.escape(path)

    # Build alternation
    return re.compile(
        rf"""(?:"""
        rf"""(?:\w+|\))\.{method_lower}\s*\([^)]*['"`][^'"`]*{target}"""
        rf"""|@{method_cap}\s*\(\s*['"`][^'"`]*{target}"""
        rf""")"""
    )


def scan_source_files(globs: list[str]) -> list[Path]:
    """Expand globs → file paths. Capped at ~5000 files to avoid runaway."""
    files: list[Path] = []
    for pat in globs:
        try:
            for p in REPO_ROOT.glob(pat):
                if p.is_file():
                    files.append(p)
                if len(files) >= 5000:
                    return files
        except Exception:
            continue
    return files


def search_endpoint_in_source(
    method: str, path: str, files: list[Path],
) -> tuple[bool, bool, list[str]]:
    """Search source files for this endpoint.

    Returns (has_method_match, has_path_match, hit_files).
      - has_method_match: strong signal — method + path near each other
      - has_path_match:   weak signal — path literal appears but method unclear
      - hit_files:        up to 3 file paths that matched (relative)

    Fallback for prefix-mounted routes (common in Fastify/Express): when
    an endpoint's path ends with a param (e.g. `/users/:id`), its route
    decl in source may just be `.get('/:id', ...)` inside a plugin/file
    whose filename encodes the static segment (`modules/users/...`). We
    accept those as path-matches when (a) file path contains the static
    segment and (b) file has a `.<method>(` call for the right verb.
    """
    method_re = _method_anchored_pattern(method, path)
    path_res = _path_search_patterns(path)

    # Static segments from contract path — used for filename-prefix fallback
    static_segs = [
        s for s in path.split("/")
        if s and not s.startswith(":") and not s.startswith("{")
    ]

    # Param-bearing alt regex for prefix-mounted routes. Matches
    # `.get('/:id', ...)` or `.get('/:any-name', ...)` regardless of
    # static prefix. Only used when static_segs non-empty and filename
    # itself encodes the static segment.
    param_route_re = re.compile(
        rf"""(?:\w+|\))\.{method.lower()}\s*\(\s*['"`]/?:\w+""",
    )
    nest_param_decorator_re = re.compile(
        rf"""@{method.capitalize()}\s*\(\s*['"`]/?:\w+""",
    )

    method_hits: set[Path] = set()
    path_hits: set[Path] = set()

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if method_re.search(text):
            method_hits.add(f)
            continue  # strong match — no need to check weak

        # Prefix-mount fallback — param-only route decl inside resource-scoped
        # file. Runs BEFORE path_res so we can upgrade to method_hit if the
        # filename encodes the static segment AND file has a verb-matched
        # route decl, even when the path literal is present elsewhere in the
        # same file (e.g. @Controller('/users') decorator).
        fallback_hit = False
        if static_segs:
            file_str = str(f).replace("\\", "/").lower()
            if any(s.lower() in file_str for s in static_segs):
                if param_route_re.search(text) or nest_param_decorator_re.search(text):
                    method_hits.add(f)
                    fallback_hit = True
        if fallback_hit:
            continue

        for p_re in path_res:
            if p_re.search(text):
                path_hits.add(f)
                break

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(REPO_ROOT)).replace("\\", "/")
        except ValueError:
            return str(p)

    hits = [_rel(p) for p in list(method_hits)[:3]]
    if not hits:
        hits = [_rel(p) for p in list(path_hits)[:3]]

    return bool(method_hits), bool(path_hits), hits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--source-globs", action="append", default=None,
                    help="Glob(s) to scan. Repeatable. Default: apps/*/src/**/*.{ts,tsx,js,jsx,py,rs}")
    ap.add_argument("--allow-ambiguous", action="store_true",
                    help="Treat 'method uncertain' as WARN instead of BLOCK")
    args = ap.parse_args()

    out = Output(validator="verify-contract-runtime")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            # No phase dir → skip (another validator handles missing phase)
            emit_and_exit(out)

        contracts_path = phase_dir / "API-CONTRACTS.md"
        if not contracts_path.exists():
            # Contract optional for non-feature profiles. Skip.
            emit_and_exit(out)

        endpoints = parse_contract_endpoints(contracts_path)
        if not endpoints:
            # FAIL CLOSED (v2.45 PR fix/fail-closed-validators): API-CONTRACTS.md
            # exists but no `## METHOD /path` / `### METHOD /path` headers parsed.
            # Previously WARN — passed silently when contract format drifted.
            # If the contract is genuinely empty (non-feature profile), the file
            # shouldn't exist; the early return above handles that case. Reaching
            # here means file exists but format is wrong → BLOCK.
            out.add(Evidence(
                type="empty_contract",
                message=t("contract_runtime.empty_contract.message"),
                actual=str(contracts_path.relative_to(REPO_ROOT)),
                fix_hint=t("contract_runtime.empty_contract.fix_hint"),
            ))
            emit_and_exit(out)

        globs = args.source_globs or DEFAULT_SOURCE_GLOBS
        files = scan_source_files(globs)
        if not files:
            out.warn(Evidence(
                type="no_source_files",
                message=t("contract_runtime.no_source_files.message"),
                actual=f"globs: {', '.join(globs)}",
                fix_hint=t("contract_runtime.no_source_files.fix_hint"),
            ))
            emit_and_exit(out)

        missing: list[tuple[str, str]] = []
        ambiguous: list[tuple[str, str, list[str]]] = []
        verified: list[tuple[str, str, list[str]]] = []

        for method, path in endpoints:
            method_ok, path_ok, hits = search_endpoint_in_source(
                method, path, files,
            )
            if method_ok:
                verified.append((method, path, hits))
            elif path_ok:
                ambiguous.append((method, path, hits))
            else:
                missing.append((method, path))

        # Emit evidence
        if missing:
            sample = missing[:10]
            out.add(Evidence(
                type="missing_endpoint",
                message=t(
                    "contract_runtime.missing_endpoint.message",
                    count=len(missing), total=len(endpoints),
                ),
                actual="; ".join(f"{m} {p}" for m, p in sample),
                fix_hint=t("contract_runtime.missing_endpoint.fix_hint"),
            ))

        if ambiguous:
            sample = ambiguous[:5]
            evidence_str = "; ".join(
                f"{m} {p} (path present in {', '.join(hits)} — method unclear)"
                for m, p, hits in sample
            )
            severity_fn = out.warn if args.allow_ambiguous else out.add
            severity_fn(Evidence(
                type="ambiguous_endpoint",
                message=t(
                    "contract_runtime.ambiguous_endpoint.message",
                    count=len(ambiguous), total=len(endpoints),
                ),
                actual=evidence_str,
                fix_hint=t("contract_runtime.ambiguous_endpoint.fix_hint"),
            ))

        # Success summary (only emitted when others are also present, to
        # keep the JSON audit compact on clean runs).
        if (missing or ambiguous) and verified:
            sample_ok = verified[:3]
            out.warn(Evidence(
                type="verified_sample",
                message=t(
                    "contract_runtime.verified_sample.message",
                    count=len(verified),
                ),
                actual="; ".join(f"{m} {p}" for m, p, _ in sample_ok),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
