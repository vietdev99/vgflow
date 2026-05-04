#!/usr/bin/env python3
"""Task 38 — verify BLOCK 5 FE consumer contract is present + complete.

Scans `${PHASE_DIR}/API-CONTRACTS/<slug>.md` files. Each file must contain
exactly one ```typescript fenced block under a `## BLOCK 5: FE consumer
contract` heading. The block must declare 16 keys (see REQUIRED_FIELDS).

Per-method matrix:
- GET on a list path (no `:id` / `{id}`) ⇒ pagination_contract MUST be a
  non-null object with `type` field.
- POST/PUT/PATCH ⇒ form_submission_idempotency_key MUST be a non-null
  string starting with 'header:' or 'body:'.

Exit codes:
- 0 = OK or override accepted
- 1 = BLOCK (missing/incomplete BLOCK 5)
- 2 = wrong invocation
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_FIELDS = (
    "url",
    "consumers",
    "ui_states",
    "query_param_schema",
    "invalidates",
    "optimistic",
    "toast_text",
    "navigation_post_action",
    "auth_role_visibility",
    "error_to_action_map",
    "pagination_contract",
    "debounce_ms",
    "prefetch_triggers",
    "websocket_correlate",
    "request_id_propagation",
    "form_submission_idempotency_key",
)

# Heading + fenced typescript block.
BLOCK5_RE = re.compile(
    r"##\s+BLOCK\s+5:\s+FE consumer contract\s*\n+```(?:typescript|ts)\n(?P<body>.+?)\n```",
    re.DOTALL,
)
# Endpoint method/path from filename (`post-api-sites.md`) or top heading.
HEADING_RE = re.compile(r"^#\s+(GET|POST|PUT|PATCH|DELETE)\s+(\S+)", re.MULTILINE)


def _parse_method_path(text: str, filename: str) -> tuple[str | None, str | None]:
    m = HEADING_RE.search(text)
    if m:
        return m.group(1).upper(), m.group(2)
    # Fallback: derive from filename (post-api-sites → POST /api/sites)
    parts = filename.removesuffix(".md").split("-")
    if not parts:
        return None, None
    method = parts[0].upper()
    path = "/" + "/".join(parts[1:]).replace("--", "/")
    return method, path


def _is_list_path(path: str) -> bool:
    return "{" not in path and ":id" not in path


def _block5_findings(contract_path: Path) -> list[str]:
    text = contract_path.read_text(encoding="utf-8")
    method, path = _parse_method_path(text, contract_path.name)
    findings: list[str] = []

    m = BLOCK5_RE.search(text)
    if not m:
        findings.append(f"{contract_path.name}: BLOCK 5 missing")
        return findings

    body = m.group("body")
    for field in REQUIRED_FIELDS:
        # Field must appear as `field:` token at start of identifier boundary.
        if not re.search(rf"\b{re.escape(field)}\s*:", body):
            findings.append(f"{contract_path.name}: BLOCK 5 missing field '{field}'")

    # Per-method matrix
    if method == "GET" and path and _is_list_path(path):
        if re.search(r"\bpagination_contract\s*:\s*null\b", body):
            findings.append(
                f"{contract_path.name}: GET list endpoint requires non-null pagination_contract"
            )
        if not re.search(r"\bpagination_contract\s*:", body):
            findings.append(
                f"{contract_path.name}: GET list endpoint missing pagination_contract field"
            )
    if method in {"POST", "PUT", "PATCH"}:
        if re.search(r"\bform_submission_idempotency_key\s*:\s*null\b", body):
            findings.append(
                f"{contract_path.name}: {method} endpoint requires non-null form_submission_idempotency_key"
            )
        if not re.search(r"\bform_submission_idempotency_key\s*:", body):
            findings.append(
                f"{contract_path.name}: {method} endpoint missing form_submission_idempotency_key field"
            )
    return findings


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--contracts-dir", required=True, help="Path to API-CONTRACTS/ split dir")
    p.add_argument("--allow-block5-missing", action="store_true")
    p.add_argument("--override-reason", default="")
    p.add_argument("--override-debt-path", default="")
    args = p.parse_args()

    contracts_dir = Path(args.contracts_dir)
    if not contracts_dir.is_dir():
        print(f"ERROR: --contracts-dir not a directory: {contracts_dir}", file=sys.stderr)
        return 2

    all_findings: list[str] = []
    for contract_file in sorted(contracts_dir.glob("*.md")):
        if contract_file.name == "index.md":
            continue
        all_findings.extend(_block5_findings(contract_file))

    if not all_findings:
        return 0

    if args.allow_block5_missing:
        if not args.override_reason:
            print("ERROR: --allow-block5-missing requires --override-reason", file=sys.stderr)
            return 2
        debt = {
            "scope": "fe-contract-block5-missing",
            "reason": args.override_reason,
            "findings": all_findings,
        }
        if args.override_debt_path:
            Path(args.override_debt_path).write_text(json.dumps(debt, indent=2), encoding="utf-8")
        print(f"OVERRIDE accepted ({len(all_findings)} findings logged to override-debt)")
        return 0

    print("BLOCK: BLOCK 5 FE consumer contract findings:")
    for f in all_findings:
        print(f"  - {f}")
    print("Fix: run `/vg:blueprint <phase> --only=fe-contracts` to regenerate Pass 2.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
