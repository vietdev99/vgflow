#!/usr/bin/env python3
"""Low-cost API readiness probe for /vg:review before browser discovery.

Reads API-CONTRACTS.md, probes each declared endpoint against a live base URL,
and writes a human-readable report. GET endpoints use GET. Mutations are probed
with OPTIONS only, so this step proves route readiness without creating side
effects.

Exit codes:
  0 = all endpoints returned acceptable "route exists" statuses
  1 = one or more endpoints failed readiness probe
  2 = setup / parse error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin


# v2.67.0 #157 — add WS|WEBSOCKET to all 3 method regexes so contracts that
# declare WebSocket endpoints surface in the parsed list (previously dropped
# silently → 0 endpoints → setup-error exit).
HEADER_RE = re.compile(
    r"(?m)^###?\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|WS|WEBSOCKET)\s+(\S+)"
)
PARAM_SEGMENT_RE = re.compile(r"/(:[A-Za-z0-9_]+|\{[^}/]+\})")
GET_ACCEPTABLE = set(range(200, 300)) | {400, 401, 403, 405, 409, 422, 428}
MUTATION_ACCEPTABLE = {200, 201, 202, 204, 400, 401, 403, 405, 409, 415, 422, 428}
# v2.67.0 #157 — WS/WEBSOCKET methods cannot be HTTP-probed (they require
# upgrade handshake). probe_endpoint() short-circuits these to a SKIP verdict.
WS_METHODS = {"WS", "WEBSOCKET"}


@dataclass
class Endpoint:
    method: str
    path: str
    auth: str | None = None

    @property
    def probe_method(self) -> str:
        return "GET" if self.method == "GET" else "OPTIONS"

    @property
    def materialized_path(self) -> str:
        path = self.path
        if PARAM_SEGMENT_RE.search(path):
            collapsed = PARAM_SEGMENT_RE.sub("", path).rstrip("/")
            if collapsed:
                return collapsed
        return path


@dataclass
class ProbeResult:
    endpoint: Endpoint
    url: str
    status: int
    verdict: str
    detail: str


TABLE_ROW_RE = re.compile(
    r"^\|\s*\S+\s*\|\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|WS|WEBSOCKET)\s*\|\s*(\S+)\s*\|",
    re.MULTILINE | re.IGNORECASE,
)
SPLIT_FILE_HEAD_RE = re.compile(
    r"^#\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|WS|WEBSOCKET)\s+(/\S+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _parse_legacy_headings(text: str) -> list[Endpoint]:
    """Layer 3 / legacy: `### METHOD /path` heading + body block."""
    matches = list(HEADER_RE.finditer(text))
    endpoints: list[Endpoint] = []
    for idx, match in enumerate(matches):
        method, ep_path = match.groups()
        body_start = match.end()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[body_start:body_end]
        auth_match = re.search(r"(?m)^\*\*Auth:\*\*\s*(.+?)\s*$", body)
        endpoints.append(
            Endpoint(
                method=method.upper(),
                path=ep_path,
                auth=auth_match.group(1).strip() if auth_match else None,
            )
        )
    return endpoints


def _parse_index_table(text: str) -> list[Endpoint]:
    """Layer 2: `| <slug> | METHOD | /path | <file> |` index table rows."""
    endpoints: list[Endpoint] = []
    for m in TABLE_ROW_RE.finditer(text):
        method = m.group(1).upper()
        ep_path = m.group(2)
        endpoints.append(Endpoint(method=method, path=ep_path, auth=None))
    return endpoints


def _parse_split_files(index_path: Path) -> list[Endpoint]:
    """Layer 1: walk siblings of index.md (API-CONTRACTS/<slug>.md) and parse
    first `# METHOD /path` heading per file."""
    endpoints: list[Endpoint] = []
    parent = index_path.parent
    if not parent.is_dir():
        return endpoints
    for fp in sorted(parent.glob("*.md")):
        if fp.name == "index.md":
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = SPLIT_FILE_HEAD_RE.search(text)
        if not m:
            continue
        method = m.group(1).upper()
        ep_path = m.group(2)
        body = text[m.end():]
        auth_match = re.search(r"(?m)^\*\*Auth:\*\*\s*(.+?)\s*$", body)
        endpoints.append(
            Endpoint(
                method=method,
                path=ep_path,
                auth=auth_match.group(1).strip() if auth_match else None,
            )
        )
    return endpoints


def parse_contracts(path: Path) -> list[Endpoint]:
    """3-layer split format support (v2.64.1, issues #146/#145/#144).

    Pre-fix: parser scanned for `### METHOD /path` headings only. New phases
    use 3-layer pattern (Layer 2 index table + Layer 1 per-endpoint files),
    which produced 0 endpoints and a setup-error exit code.

    Strategy: try legacy headings → index-table rows → split files; return
    the first non-empty result (or empty list if all 3 yield nothing).
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""

    legacy = _parse_legacy_headings(text)
    if legacy:
        return legacy

    table = _parse_index_table(text)
    if table:
        return table

    return _parse_split_files(path)


# v2.67.0 #157 — OpenAPI schema validity pre-gate.
#
# When openapi-generation.log shows the API server failed to emit a valid
# schema (FST_ERR_INVALID_SCHEMA from Fastify, or HTTP 500 from the
# /openapi.json route), docs-derived probes are not trustworthy: API-CONTRACTS
# may have been derived from a broken schema, or the live OpenAPI endpoint
# may itself return 500. In either case the probe report would mislead.
#
# Returns (valid, reason). When invalid, callers should exit 2 (setup error)
# rather than burn time on probes whose verdicts cannot be trusted.
_OPENAPI_INVALID_PATTERNS = (
    "FST_ERR_INVALID_SCHEMA",
    "openapi schema invalid",
    "openapi generation failed",
)


def _openapi_schema_valid(phase_dir: Path) -> tuple[bool, str]:
    """Inspect ``openapi-generation.log`` (if present) for failure signals.

    Args:
        phase_dir: Phase directory (typically ``$PHASE_DIR``) where the log
            is expected to live.

    Returns:
        ``(valid, reason)`` — ``valid=True`` when no log exists OR the log
        is clean. ``valid=False`` when FST_ERR_INVALID_SCHEMA, an explicit
        500 against an OpenAPI route, or another invalid-schema marker is
        present.
    """
    log = phase_dir / "openapi-generation.log"
    if not log.exists():
        return True, "no openapi-generation.log — pre-gate skipped"
    try:
        text = log.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        # Cannot read log → don't punish the run; log the reason.
        return True, f"openapi-generation.log unreadable: {exc}"

    text_lower = text.lower()
    for pat in _OPENAPI_INVALID_PATTERNS:
        if pat.lower() in text_lower:
            return False, (
                f"OpenAPI generation failed — found '{pat}' in "
                f"openapi-generation.log; docs-derived probes unreliable"
            )

    # Look for HTTP 500 specifically associated with openapi (avoid false
    # positives from unrelated 500 strings).
    if re.search(
        r"(HTTP/[\d.]+\s+500|status[:= ]+500).*openapi|openapi.*\b500\b",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        return False, (
            "OpenAPI route returned 500 in openapi-generation.log — "
            "docs-derived probes unreliable"
        )

    return True, "openapi-generation.log clean"


def _json_top_keys(body: bytes, content_type: str) -> str:
    if "json" not in (content_type or "").lower() or not body:
        return ""
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return ""
    if isinstance(data, dict):
        return ",".join(sorted(data.keys())[:12])
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return ",".join(sorted(data[0].keys())[:12])
    return ""


def _curl(
    url: str, method: str, headers: Iterable[str], timeout: int
) -> tuple[int, str, int, bytes, str]:
    with tempfile.NamedTemporaryFile(delete=False) as body_tmp:
        body_path = body_tmp.name
    with tempfile.NamedTemporaryFile(delete=False) as hdr_tmp:
        hdr_path = hdr_tmp.name
    cmd = [
        "curl",
        "-sS",
        "-m",
        str(timeout),
        "-o",
        body_path,
        "-D",
        hdr_path,
        "-w",
        "%{http_code}\t%{content_type}",
        "-X",
        method,
        url,
    ]
    for header in headers:
        cmd.extend(["-H", header])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        body = Path(body_path).read_bytes()
    except OSError:
        body = b""
    try:
        curl_meta = proc.stdout.strip().split("\t", 1)
        status = int(curl_meta[0]) if curl_meta and curl_meta[0].isdigit() else 0
        content_type = curl_meta[1] if len(curl_meta) > 1 else ""
    finally:
        for p in (body_path, hdr_path):
            try:
                os.unlink(p)
            except OSError:
                pass
    return proc.returncode, proc.stderr.strip(), status, body, content_type


def probe_endpoint(base_url: str, endpoint: Endpoint, headers: list[str], timeout: int) -> ProbeResult:
    # v2.67.0 #157 — WS/WebSocket endpoints cannot be HTTP-probed. Short-circuit
    # with a SKIP verdict so the run still inventories the endpoint without
    # falsely failing it on a 4xx GET/OPTIONS against a WS upgrade handler.
    method_upper = (endpoint.method or "").upper()
    if method_upper in WS_METHODS:
        return ProbeResult(
            endpoint=endpoint,
            url="",
            status=0,
            verdict="SKIP",
            detail=(
                f"probe={endpoint.method}; WS/WebSocket endpoint not probed "
                f"via HTTP — verify externally (upgrade handshake required)"
            ),
        )

    probe_path = endpoint.materialized_path
    url = urljoin(base_url.rstrip("/") + "/", probe_path.lstrip("/"))
    curl_rc, curl_err, status, body, content_type = _curl(
        url, endpoint.probe_method, headers, timeout
    )
    if curl_rc != 0:
        return ProbeResult(
            endpoint=endpoint,
            url=url,
            status=0,
            verdict="FAIL",
            detail=f"curl_rc={curl_rc} {curl_err[:220]}".strip(),
        )

    acceptable = GET_ACCEPTABLE if endpoint.method == "GET" else MUTATION_ACCEPTABLE
    if status in acceptable:
        verdict = "PASS" if 200 <= status < 300 else "ACCEPTABLE"
        detail_bits = [f"probe={endpoint.probe_method}", f"status={status}"]
        if endpoint.materialized_path != endpoint.path:
            detail_bits.append(f"materialized_from={endpoint.path}")
        keys = _json_top_keys(body, content_type)
        if keys:
            detail_bits.append(f"json_keys={keys}")
        if endpoint.auth:
            detail_bits.append(f"auth={endpoint.auth}")
        return ProbeResult(
            endpoint=endpoint,
            url=url,
            status=status,
            verdict=verdict,
            detail="; ".join(detail_bits),
        )

    return ProbeResult(
        endpoint=endpoint,
        url=url,
        status=status,
        verdict="FAIL",
        detail=f"probe={endpoint.probe_method}; status={status}; content_type={content_type or '?'}",
    )


def probe_endpoints(
    endpoints: list[Endpoint],
    base_url: str,
    headers: list[str],
    timeout: int,
    *,
    parallel: int = 1,
) -> list[ProbeResult]:
    """Probe ``endpoints`` against ``base_url`` and return ProbeResults.

    v2.65.0 A2: when ``parallel > 1`` use ThreadPoolExecutor with up to
    ``parallel`` concurrent workers. ``probe_endpoint`` shells out to curl
    via ``subprocess.run`` (blocking I/O), so threads (not processes) are
    the right primitive — we just need overlapping waits, not CPU-parallel
    python work. Result ordering is preserved via indexed futures.

    Args:
        endpoints: Parsed endpoints from ``parse_contracts``.
        base_url: Live API base URL passed to each ``probe_endpoint`` call.
        headers: Extra curl headers (e.g. Authorization bearer).
        timeout: Per-request curl timeout in seconds.
        parallel: Max concurrent workers. ``1`` (default) keeps the
            sequential list-comprehension codepath for full back-compat.
            Values >1 dispatch via ThreadPoolExecutor.

    Returns:
        ``list[ProbeResult]`` — one entry per input endpoint, in input
        order regardless of completion order.

    Partial-failure handling: when ``parallel > 1``, each worker call is
    wrapped in try/except so a single raise doesn't crash the whole batch.
    The error shape mirrors the existing ``curl_rc != 0`` path in
    ``probe_endpoint`` itself (``status=0, verdict="FAIL"``) plus a
    ``worker_raise:`` detail prefix carrying the exception message — this
    keeps a single ``r.verdict == "FAIL" and r.status == 0`` predicate
    covering connectivity failures and worker exceptions uniformly (A1
    homogeneous-shape principle).
    """
    if parallel <= 1:
        return [
            probe_endpoint(base_url, endpoint, headers, timeout)
            for endpoint in endpoints
        ]

    # Parallel branch — preserve ordering via indexed futures.
    n = len(endpoints)
    results_indexed: list[ProbeResult | None] = [None] * n

    def _run_one(idx: int) -> tuple[int, ProbeResult]:
        endpoint = endpoints[idx]
        try:
            return idx, probe_endpoint(base_url, endpoint, headers, timeout)
        except Exception as exc:  # noqa: BLE001 — preserve any worker failure
            # Error shape mirrors the curl_rc != 0 path in probe_endpoint
            # (status=0, verdict="FAIL"). The ``worker_raise:`` detail prefix
            # lets a downstream consumer distinguish exception failures from
            # connectivity failures while keeping the canonical FAIL+status=0
            # predicate intact.
            url = urljoin(
                base_url.rstrip("/") + "/",
                endpoint.materialized_path.lstrip("/"),
            )
            return idx, ProbeResult(
                endpoint=endpoint,
                url=url,
                status=0,
                verdict="FAIL",
                detail=f"worker_raise: {exc}",
            )

    with ThreadPoolExecutor(max_workers=parallel) as ex:
        for idx, res in ex.map(_run_one, range(n)):
            results_indexed[idx] = res

    return [r for r in results_indexed if r is not None]


def render_report(base_url: str, endpoints: list[Endpoint], results: list[ProbeResult]) -> str:
    lines = [
        f"▸ API contract probe against {base_url}",
        f"▸ Parsed endpoints: {len(endpoints)}",
        "",
    ]
    for result in results:
        lines.append(
            f"  {result.verdict:<10} {result.endpoint.method:<6} {result.endpoint.path:<45} -> {result.url}"
        )
        if result.detail:
            lines.append(f"             {result.detail}")
    lines.append("")
    pass_n = sum(1 for r in results if r.verdict == "PASS")
    acceptable_n = sum(1 for r in results if r.verdict == "ACCEPTABLE")
    fail_n = sum(1 for r in results if r.verdict == "FAIL")
    lines.append("Summary")
    lines.append(f"  PASS: {pass_n} | ACCEPTABLE: {acceptable_n} | FAIL: {fail_n} | total: {len(results)}")
    if fail_n:
        lines.append("")
        lines.append("Failing endpoints:")
        for result in results:
            if result.verdict == "FAIL":
                lines.append(
                    f"  - {result.endpoint.method} {result.endpoint.path} -> {result.detail}"
                )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--contracts", required=True, help="Path to API-CONTRACTS.md")
    ap.add_argument("--base-url", required=True, help="Live API base URL")
    ap.add_argument("--out", required=True, help="Report output file")
    ap.add_argument("--header", action="append", default=[], help="Extra curl header")
    ap.add_argument("--timeout", type=int, default=12, help="Per-request timeout seconds")
    # v2.65.0 A2 — parallel dispatch control. Default 1 = full back-compat
    # (sequential list-comp). Values >1 enable ThreadPoolExecutor; result
    # order is preserved regardless of completion order.
    ap.add_argument("--parallel", type=int, default=1, metavar="N",
                    help="Max concurrent probe workers. Default 1 "
                         "(sequential, full back-compat). N>1 uses "
                         "ThreadPoolExecutor; result order is preserved.")
    args = ap.parse_args()

    contracts_path = Path(args.contracts)
    out_path = Path(args.out)
    if not contracts_path.exists():
        print(f"missing contracts file: {contracts_path}", file=sys.stderr)
        return 2

    # v2.67.0 #157 — OpenAPI schema validity pre-gate. The phase dir is the
    # parent of the contracts file (API-CONTRACTS.md typically sits at the
    # phase root). If the OpenAPI generator emitted FST_ERR_INVALID_SCHEMA or
    # a 500 for /openapi.json, docs-derived probes are unreliable; exit 2 so
    # /vg:review handles this as a setup error instead of trusting probe
    # verdicts produced from a broken contract.
    phase_dir = contracts_path.parent
    valid, reason = _openapi_schema_valid(phase_dir)
    if not valid:
        print(
            f"⛔ API contract probe pre-gate BLOCK: {reason}",
            file=sys.stderr,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            f"⛔ OpenAPI schema invalid — pre-gate BLOCK: {reason}\n",
            encoding="utf-8",
        )
        return 2

    endpoints = parse_contracts(contracts_path)
    if not endpoints:
        out_path.write_text(
            "⛔ API contract probe setup error — 0 endpoints parsed from API-CONTRACTS.md\n",
            encoding="utf-8",
        )
        return 2

    results = probe_endpoints(
        endpoints,
        base_url=args.base_url,
        headers=args.header,
        timeout=args.timeout,
        parallel=max(1, int(args.parallel)),
    )
    report = render_report(args.base_url, endpoints, results)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    return 1 if any(r.verdict == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
