#!/usr/bin/env python3
"""
Validator: verify-idempotency-coverage.py

Harness v2.6 (2026-04-25): mutations on critical-domain endpoints (billing,
auth, payout, payment, transaction, auction) MUST declare idempotency
guarantees. Per VG test.md step 5b-2 idempotency rule:

  "Billing, auth, and payout endpoints MUST be idempotent for mutations
   (POST/PUT/DELETE). Double-submit the same request should NOT create
   duplicate records, charge twice, or produce inconsistent state."

But test.md step 5b-2 only RUNS the idempotency check when (a) endpoint
matches critical_domains and (b) mutation. There is NO upstream gate that
forces the contract author to DECLARE the idempotency strategy. Result:
contracts ship with critical-domain mutation endpoints that have neither
**Idempotency:** declaration nor idempotency_key field — and the test
fail-open path (no fixture data) lets the missing declaration go undetected.

This validator closes the upstream gate: at /vg:blueprint stage, every
critical-domain mutation endpoint in API-CONTRACTS.md must have an
**Idempotency:** line OR an idempotency_key field in the request schema.

What counts as "declared":
  1. Line "**Idempotency:** required" / "**Idempotency:** key=Idempotency-Key"
  2. Schema includes field named idempotency_key / idempotencyKey /
     Idempotency-Key (header schema)
  3. Explicit "**Idempotency:** N/A — <reason>" with reason ≥ 10 chars
     (acknowledges decision; advisory)

Severity:
  BLOCK — critical-domain mutation endpoint without idempotency declaration
  WARN  — mutation endpoint outside critical_domains lacks declaration
          (advisory; PR review may decide it's safe)

Usage:
  verify-idempotency-coverage.py --phase 7.14
  verify-idempotency-coverage.py --phase 7.14 --include-non-critical (warn-only mode)

Exit codes:
  0  PASS or WARN-only
  1  BLOCK (critical-domain endpoint missing declaration)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

ENDPOINT_HEADER_RE = re.compile(
    r"^###\s+(?P<method>POST|PUT|DELETE|PATCH)\s+(?P<path>/\S+)",
    re.MULTILINE,
)
IDEMPOTENCY_LINE_RE = re.compile(
    r"\*\*Idempotency:?\*\*\s*(?P<value>.+?)$",
    re.IGNORECASE | re.MULTILINE,
)
IDEMPOTENCY_FIELD_RE = re.compile(
    r"(idempotency[-_]?key|Idempotency-Key)",
    re.IGNORECASE,
)
NA_REASON_RE = re.compile(r"^\s*(?:N/A|None|Not\s+applicable)\s*[—\-:]\s*(?P<reason>.+)", re.IGNORECASE)


def _read_critical_domains() -> list[str]:
    """Pull critical_domains config — single CSV string OR YAML list."""
    cfg_path = REPO_ROOT / ".claude" / "vg.config.md"
    defaults = ["billing", "auth", "payout", "payment", "transaction"]
    if not cfg_path.exists():
        return defaults
    text = cfg_path.read_text(encoding="utf-8", errors="replace")

    # CSV form: critical_domains: "billing,auth,payout"
    m = re.search(r'^\s*critical_domains:\s*["\']([^"\'\n]+)', text, re.MULTILINE)
    if m:
        return [d.strip() for d in m.group(1).split(",") if d.strip()]

    # YAML list form: critical_goal_domains: [...]
    m = re.search(r'^\s*critical_(goal_)?domains:\s*\[([^\]]+)\]', text, re.MULTILINE)
    if m:
        return [
            d.strip().strip('"\'')
            for d in m.group(2).split(",")
            if d.strip().strip('"\'')
        ]

    return defaults


def _endpoint_blocks(text: str) -> list[dict]:
    """Split API-CONTRACTS.md into per-endpoint blocks for mutations only."""
    blocks: list[dict] = []
    matches = list(ENDPOINT_HEADER_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block_text = text[m.start():end]
        blocks.append({
            "method": m.group("method"),
            "path": m.group("path"),
            "block": block_text,
        })
    return blocks


def _is_critical(path: str, critical_domains: list[str]) -> bool:
    path_lower = path.lower()
    return any(d in path_lower for d in critical_domains)


def _has_idempotency_declared(block: str) -> dict:
    """Return {declared: bool, kind: 'line'|'field'|'na'|'', value: str}."""
    m = IDEMPOTENCY_LINE_RE.search(block)
    if m:
        value = m.group("value").strip()
        # N/A justification with reason
        na = NA_REASON_RE.match(value)
        if na and len(na.group("reason").strip()) >= 10:
            return {"declared": True, "kind": "na", "value": value[:80]}
        if value and not na:
            return {"declared": True, "kind": "line", "value": value[:80]}
        # N/A without reason — not declared
        return {"declared": False, "kind": "na_no_reason", "value": value[:80]}

    if IDEMPOTENCY_FIELD_RE.search(block):
        return {"declared": True, "kind": "field", "value": "idempotency_key in schema"}

    return {"declared": False, "kind": "", "value": ""}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--include-non-critical", action="store_true",
                    help="Also WARN on non-critical mutation endpoints lacking idempotency")
    args = ap.parse_args()

    out = Output(validator="verify-idempotency-coverage")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        contracts_path = phase_dir / "API-CONTRACTS.md"
        if not contracts_path.exists():
            # Skip silently — contract may not exist for non-feature profiles
            emit_and_exit(out)

        text = contracts_path.read_text(encoding="utf-8", errors="replace")
        critical_domains = _read_critical_domains()

        endpoints = _endpoint_blocks(text)
        if not endpoints:
            emit_and_exit(out)

        block_findings: list[dict] = []
        warn_findings: list[dict] = []

        for ep in endpoints:
            method = ep["method"]
            path = ep["path"]
            decl = _has_idempotency_declared(ep["block"])
            critical = _is_critical(path, critical_domains)

            if not decl["declared"]:
                row = {
                    "method": method,
                    "path": path,
                    "critical": critical,
                    "kind": decl["kind"] or "missing",
                }
                if critical:
                    block_findings.append(row)
                elif args.include_non_critical:
                    warn_findings.append(row)

        if block_findings:
            sample = "; ".join(
                f"{f['method']} {f['path']}"
                for f in block_findings[:5]
            )
            domains_str = ", ".join(critical_domains)
            out.add(Evidence(
                type="idempotency_critical_missing",
                message=f"{len(block_findings)} critical-domain mutation endpoint(s) missing idempotency declaration",
                actual=sample,
                expected=f"Critical domains: [{domains_str}]. Each mutation must declare **Idempotency:** required (or include idempotency_key field, or **Idempotency:** N/A — <≥10 char reason>)",
                fix_hint="Add `**Idempotency:** required` line below endpoint header, OR add `idempotency_key: string` field to request schema, OR explicit `**Idempotency:** N/A — <reason>` with rationale ≥10 chars.",
            ))

        if warn_findings:
            sample = "; ".join(
                f"{f['method']} {f['path']}"
                for f in warn_findings[:5]
            )
            out.warn(Evidence(
                type="idempotency_non_critical_missing",
                message=f"{len(warn_findings)} non-critical mutation endpoint(s) without idempotency declaration (advisory)",
                actual=sample,
                fix_hint="Consider declaring idempotency strategy explicitly for retry-safety, even outside critical domains.",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
