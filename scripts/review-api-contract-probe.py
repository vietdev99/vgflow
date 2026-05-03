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
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin


HEADER_RE = re.compile(
    r"(?m)^###?\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)"
)
PARAM_SEGMENT_RE = re.compile(r":([A-Za-z0-9_]+)|\{([^}/]+)\}")
GET_ACCEPTABLE = set(range(200, 300)) | {400, 401, 403, 405, 409, 422, 428}
GET_PARAM_ACCEPTABLE = GET_ACCEPTABLE | {404}
MUTATION_ACCEPTABLE = {200, 201, 202, 204, 400, 401, 403, 405, 409, 415, 422, 428}


def _dummy_path_value(name: str) -> str:
    lower = name.lower()
    if lower in {"id", "merchant_id", "merchantid", "request_id", "requestid", "file_id", "fileid"}:
        return "000000000000000000000000"
    if "gateway" in lower:
        return "paypal"
    if "currency" in lower:
        return "USD"
    return "test"


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
        return PARAM_SEGMENT_RE.sub(
            lambda m: _dummy_path_value(m.group(1) or m.group(2) or "id"),
            self.path,
        )

    @property
    def has_path_params(self) -> bool:
        return bool(PARAM_SEGMENT_RE.search(self.path))


@dataclass
class ProbeResult:
    endpoint: Endpoint
    url: str
    status: int
    verdict: str
    detail: str


def parse_contracts(path: Path) -> list[Endpoint]:
    text = path.read_text(encoding="utf-8")
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
                method=method,
                path=ep_path,
                auth=auth_match.group(1).strip() if auth_match else None,
            )
        )
    return endpoints


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

    acceptable = (
        GET_PARAM_ACCEPTABLE
        if endpoint.method == "GET" and endpoint.has_path_params
        else GET_ACCEPTABLE
        if endpoint.method == "GET"
        else MUTATION_ACCEPTABLE
    )
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
    args = ap.parse_args()

    contracts_path = Path(args.contracts)
    out_path = Path(args.out)
    if not contracts_path.exists():
        print(f"missing contracts file: {contracts_path}", file=sys.stderr)
        return 2

    endpoints = parse_contracts(contracts_path)
    if not endpoints:
        out_path.write_text(
            "\033[38;5;208mAPI contract probe setup error — 0 endpoints parsed from API-CONTRACTS.md\033[0m\n",
            encoding="utf-8",
        )
        return 2

    results = [
        probe_endpoint(args.base_url, endpoint, args.header, args.timeout)
        for endpoint in endpoints
    ]
    report = render_report(args.base_url, endpoints, results)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    return 1 if any(r.verdict == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
