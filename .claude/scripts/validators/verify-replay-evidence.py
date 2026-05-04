#!/usr/bin/env python3
"""Verify scanner-claimed network calls actually return claimed responses.

Closes Phase 3.2 dogfood gap: scanner output may claim
  network: [{method: POST, url: /api/x, status: 200}]
without actually receiving a 200. Adversarial fabrication detection.

Mechanism: for each scanner-claimed mutation network entry, replay via curl
(if config.environments[ENV].api_base reachable) + compare status code.
Mismatch = scanner fabricated.

NOTE: This validator is opt-in (--enable-replay) because it requires:
  1. Auth fixture (cookies/tokens) to authenticate replay
  2. Live env reachability
  3. Idempotency tolerance (some mutations can't be replayed safely)

Default: structural-only check (URL + method exists in API-CONTRACTS).

Severity: BLOCK at /vg:review Phase 4 when --enable-replay; else WARN.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def parse_contract_endpoints(contracts_text: str) -> set[tuple[str, str]]:
    """Extract (method, path) tuples from API-CONTRACTS.md."""
    endpoints: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"(GET|POST|PUT|PATCH|DELETE)\s+(/api/[^\s|`'\"]+)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(contracts_text):
        endpoints.add((m.group(1).upper(), m.group(2)))
    return endpoints


def normalize_path(url: str) -> str:
    """Strip query string + replace IDs with :id placeholder for comparison."""
    path = url.split("?")[0].split("#")[0]
    # Replace 24-char hex IDs (Mongo ObjectId) with :id
    path = re.sub(r"/[a-f0-9]{24}\b", "/:id", path)
    # Replace numeric IDs
    path = re.sub(r"/\d{6,}\b", "/:id", path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify scanner network claims (structural + optional replay)")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="warn")
    parser.add_argument(
        "--enable-replay",
        action="store_true",
        help="Live curl-replay (requires auth fixture + reachable env)",
    )
    parser.add_argument("--allow-replay-mismatch", action="store_true")
    args = parser.parse_args()

    out = Output(validator="replay-evidence")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        runtime_path = phase_dir / "RUNTIME-MAP.json"
        contracts_path = phase_dir / "API-CONTRACTS.md"
        if not runtime_path.exists():
            emit_and_exit(out)

        try:
            runtime = json.loads(_read(runtime_path))
        except json.JSONDecodeError:
            emit_and_exit(out)

        sequences = runtime.get("goal_sequences") or {}
        contracts_text = _read(contracts_path) if contracts_path.exists() else ""
        contract_endpoints = parse_contract_endpoints(contracts_text) if contracts_text else set()

        violations = 0
        for gid, seq in sequences.items():
            if not isinstance(seq, dict):
                continue
            steps = seq.get("steps") or []
            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                network = step.get("network")
                entries = network if isinstance(network, list) else [network] if network else []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    method = str(entry.get("method") or entry.get("verb") or "").upper()
                    url = str(entry.get("url") or "")
                    if not method or not url:
                        continue

                    # Structural check: claimed method+path exists in API-CONTRACTS
                    if contract_endpoints:
                        norm_path = normalize_path(url)
                        if not any(
                            (m == method) and (norm_path == p or norm_path.endswith(p) or p.endswith(norm_path))
                            for m, p in contract_endpoints
                        ):
                            violations += 1
                            out.add(
                                Evidence(
                                    type="network_endpoint_unknown",
                                    message=(
                                        f"{gid} step[{i}]: scanner claims {method} {url} "
                                        f"but no matching endpoint in API-CONTRACTS.md"
                                    ),
                                    file=str(runtime_path),
                                    expected=f"Method+path in API-CONTRACTS.md",
                                    actual=f"{method} {norm_path}",
                                    fix_hint="Either scanner fabricated the call OR API-CONTRACTS.md is incomplete.",
                                ),
                                escalate=(args.severity == "block" and not args.allow_replay_mismatch),
                            )

        if args.enable_replay:
            # TODO Wave 3: implement live curl replay with auth fixture loaded
            # For now, document the intent
            out.add(
                Evidence(
                    type="replay_not_implemented",
                    message=(
                        "--enable-replay requested but live replay deferred to Wave 3. "
                        "Structural check completed."
                    ),
                ),
                escalate=False,
            )

        if violations and (args.severity == "warn" or args.allow_replay_mismatch):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{violations} replay/structural mismatch(es) downgraded to WARN.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
