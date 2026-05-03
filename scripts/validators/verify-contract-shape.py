#!/usr/bin/env python3
"""verify-contract-shape.py — L4a-ii gate.

For each FE call, find the matching contract (by path_template) and verify:
  - method matches
  - (path matches by virtue of lookup)
  - auth requirement present in FE call if contract requires it
    (header pattern: Authorization | Bearer in nearby lines)
  - response status documented in contract (informational; not blocking)

This is a CONSERVATIVE gate: it only emits BLOCK on definite method
mismatches today. Body shape + auth header introspection are P3 (require
AST-level FE parsing). The gate is intentionally LOW false-positive.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FE_EXTRACTOR = REPO / "scripts" / "extractors" / "extract-fe-api-calls.py"

METHOD_RE = re.compile(r"\*\*Method:\*\*\s*([A-Z]+)", re.IGNORECASE)
PATH_RE = re.compile(r"\*\*Path:\*\*\s*(\S+)")


def _parse_contract(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = METHOD_RE.search(text)
    p = PATH_RE.search(text)
    if not m or not p:
        return None
    import re as _re
    norm = _re.sub(r":[A-Za-z_][A-Za-z0-9_]*", ":param", p.group(1))
    return {"method": m.group(1).upper(), "path_template": norm, "file": str(path)}


def _run_fe_extractor(root: str) -> list[dict]:
    result = subprocess.run(
        ["python3", str(FE_EXTRACTOR), "--root", root, "--format", "json"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print(f"ERROR: FE extractor failed: {result.stderr}", file=sys.stderr)
        sys.exit(2)
    return json.loads(result.stdout)["calls"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts-dir", required=True)
    parser.add_argument("--fe-root", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--evidence-out")
    args = parser.parse_args()

    contracts_dir = Path(args.contracts_dir)
    if not contracts_dir.exists():
        print(f"ERROR: contracts dir missing: {contracts_dir}", file=sys.stderr)
        return 2

    contracts: list[dict] = []
    for cp in contracts_dir.glob("*.md"):
        if cp.name == "index.md":
            continue
        c = _parse_contract(cp)
        if c:
            contracts.append(c)

    by_path: dict[str, list[dict]] = {}
    for c in contracts:
        by_path.setdefault(c["path_template"], []).append(c)

    fe_calls = _run_fe_extractor(args.fe_root)

    mismatches: list[dict] = []
    for call in fe_calls:
        candidates = by_path.get(call["path_template"], [])
        if not candidates:
            continue  # no contract — handled by Task 3 (FE→BE call graph)
        if not any(c["method"] == call["method"] for c in candidates):
            mismatches.append({
                "fe_file": call["file"],
                "fe_line": call["line"],
                "fe_method": call["method"],
                "path_template": call["path_template"],
                "contract_methods": sorted({c["method"] for c in candidates}),
                "contract_files": [c["file"] for c in candidates],
            })

    if not mismatches:
        print(f"✓ contract shape: 0 method mismatches ({len(fe_calls)} FE calls, {len(contracts)} contracts)")
        return 0

    summary_lines = [
        f"{m['fe_file']}:{m['fe_line']} calls {m['fe_method']} {m['path_template']} "
        f"but contract declares {m['contract_methods']}"
        for m in mismatches
    ]
    summary = f"{len(mismatches)} contract method mismatch(es):\n  " + "\n  ".join(summary_lines)

    evidence = {
        "warning_id": f"contract-shape-{args.phase}-{len(mismatches)}",
        "severity": "BLOCK",
        "category": "contract_shape_mismatch",
        "phase": args.phase,
        "evidence_refs": [
            {"file": m["fe_file"], "line": m["fe_line"],
             "endpoint": f"{m['fe_method']} {m['path_template']}"}
            for m in mismatches
        ],
        "summary": summary,
        "detected_by": "verify-contract-shape.py",
        "detected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "owning_artifact": "API-CONTRACTS.md",
        "recommended_action": (
            "Reconcile FE call method with API contract. Update FE call OR amend "
            "contract via /vg:amend with --reason='contract shape correction'."
        ),
        "confidence": 1.0,
    }

    print(f"⛔ {summary}", file=sys.stderr)
    if args.evidence_out:
        Path(args.evidence_out).write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"  Evidence: {args.evidence_out}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
