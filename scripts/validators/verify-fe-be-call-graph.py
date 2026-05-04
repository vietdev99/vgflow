#!/usr/bin/env python3
"""verify-fe-be-call-graph.py — L4a-i gate.

Compares FE call graph (extract-fe-api-calls.py) against BE route registry
(extract-be-route-registry.py). If FE calls (method, path_template) for which
no BE route exists, emits BuildWarningEvidence (severity=BLOCK) and exits 1.

Path matching:
  - `:param` (BE route param) ≡ `:param` (FE template var normalized).
  - Both ends normalized via _normalize_path.

Usage:
  verify-fe-be-call-graph.py --fe-root <dir> --be-root <dir> --phase <N>
                             [--evidence-out <path>]

Exit codes:
  0 = no gaps
  1 = gaps detected (evidence written)
  2 = extractor error
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FE_EXTRACTOR = REPO / "scripts" / "extractors" / "extract-fe-api-calls.py"
BE_EXTRACTOR = REPO / "scripts" / "extractors" / "extract-be-route-registry.py"


def _run_extractor(script: Path, root: str) -> dict:
    result = subprocess.run(
        ["python3", str(script), "--root", root, "--format", "json"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print(f"ERROR: extractor {script.name} failed: {result.stderr}", file=sys.stderr)
        sys.exit(2)
    return json.loads(result.stdout)


def _normalize_path(p: str) -> str:
    # Already normalized by extractors; defensive idempotent pass.
    import re
    return re.sub(r":[A-Za-z_][A-Za-z0-9_]*", ":param", p)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fe-root", required=True)
    parser.add_argument("--be-root", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--evidence-out")
    args = parser.parse_args()

    fe_calls = _run_extractor(FE_EXTRACTOR, args.fe_root)["calls"]
    be_routes = _run_extractor(BE_EXTRACTOR, args.be_root)["routes"]

    be_set: set[tuple[str, str]] = {
        (r["method"], _normalize_path(r["path_template"])) for r in be_routes
    }

    gaps: list[dict] = []
    for c in fe_calls:
        key = (c["method"], _normalize_path(c["path_template"]))
        if key not in be_set:
            gaps.append({
                "fe_file": c["file"],
                "fe_line": c["line"],
                "method": c["method"],
                "path_template": c["path_template"],
            })

    if not gaps:
        print(f"✓ FE→BE call graph: 0 gaps ({len(fe_calls)} FE calls, {len(be_routes)} BE routes)")
        return 0

    summary_lines = [
        f"{g['method']} {g['path_template']} called from {g['fe_file']}:{g['fe_line']} — no BE route"
        for g in gaps
    ]
    summary = f"{len(gaps)} FE→BE call graph gap(s):\n  " + "\n  ".join(summary_lines)

    evidence = {
        "warning_id": f"fe-be-gap-{args.phase}-{len(gaps)}",
        "severity": "BLOCK",
        "category": "fe_be_call_graph",
        "phase": args.phase,
        "evidence_refs": [
            {"file": g["fe_file"], "line": g["fe_line"],
             "endpoint": f"{g['method']} {g['path_template']}"}
            for g in gaps
        ],
        "summary": summary,
        "detected_by": "verify-fe-be-call-graph.py",
        "detected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "owning_artifact": "API-CONTRACTS.md",
        "recommended_action": (
            "BE: add the missing routes; OR FE: change the call to use an existing endpoint. "
            "Update API-CONTRACTS.md to reflect the chosen direction."
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
