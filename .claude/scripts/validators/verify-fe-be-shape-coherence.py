#!/usr/bin/env python3
"""verify-fe-be-shape-coherence.py — B95 v4.68.0 (issue #197 build-gate proposal).

Purpose
-------
Detect FE-BE response shape drift at build-close time. PrintwayV3 Phase 8.2
shipped 6 FE bugs (F-ROAM-01..06) through `/vg:build` + `/vg:review` +
`/vg:test` PASS because no validator checked that FE code consumes the
shape BE returns. Bugs caught only at post-test `/vg:roam`.

Documented bug classes from the issue:
  - FE `_id` vs BE `id` (mongo-vs-pg field name drift)
  - FE `.rows` vs BE flat array envelope
  - FE flat envelope vs BE nested envelope
  - Route param `:id` vs `useParams<{blueprintId}>` name mismatch
  - `apiClient` function-vs-object cast mismatch

Scope (B95)
-----------
v4.68.0 ships this as an ADVISORY (registry `severity: warn`) static
heuristic that flags suspicious patterns from FE source. Full runtime
1-GET-per-FE-route check requires a dev server and is deferred to a
future batch.

Heuristics shipped:
  H1. FE files using both `_id` AND `id` on same response handler — drift signal.
  H2. FE files dereferencing `.rows` AND `.data` on same response — envelope drift.
  H3. FE `useParams<{X}>` where X is NOT the route declaration param name
      (when the route declaration is discoverable).

Algorithm: regex AST-lite. Scans `apps/*/src/**/*.tsx` + `*.ts`. Emits
JSON report with per-finding file + line + classification.

Exit codes
----------
  0 - PASS (or WARN under --severity warn)
  1 - FAIL (under --severity block)
  2 - Internal error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# --- Heuristic regex bank ---------------------------------------------------

# H1: response handler with both _id and id reads
H1_MIXED_ID_RE = re.compile(
    r"(?:response|data|result|payload|res)\.(_id|id)\b"
)

# H2: same file with both .rows and .data deref on common identifiers
H2_ROWS_RE = re.compile(r"(?:response|data|result|payload|res)\.rows\b")
H2_DATA_RE = re.compile(r"(?:response|data|result|payload|res)\.data\b")

# H3: useParams<{X}> generic — capture X
H3_USEPARAMS_RE = re.compile(
    r"useParams\s*<\s*\{\s*(\w+)\s*[:?]?", re.MULTILINE
)
# Route declaration: `path: '/.../:id'` or `path="/.../:id"` etc.
H3_ROUTE_PARAM_RE = re.compile(
    r"path\s*[:=]\s*['\"](?P<path>[^'\"]+)['\"]"
)


def find_fe_sources(repo_root: Path) -> list[Path]:
    """Glob FE source files."""
    apps_dir = repo_root / "apps"
    if not apps_dir.is_dir():
        return []
    files: list[Path] = []
    for app in apps_dir.iterdir():
        if not app.is_dir():
            continue
        src = app / "src"
        if not src.is_dir():
            continue
        files.extend(src.rglob("*.tsx"))
        files.extend(src.rglob("*.ts"))
    return files


def scan_h1(path: Path, text: str) -> list[dict]:
    """H1: file uses BOTH `_id` and `id` field accesses → mongo/pg drift."""
    findings: list[dict] = []
    matches_id = [m for m in H1_MIXED_ID_RE.finditer(text) if m.group(1) == "id"]
    matches_under = [m for m in H1_MIXED_ID_RE.finditer(text) if m.group(1) == "_id"]
    if matches_id and matches_under:
        findings.append({
            "heuristic": "H1",
            "kind": "mixed_id_field",
            "file": str(path),
            "evidence": (
                f"{len(matches_id)} `.id` reads + {len(matches_under)} `._id` "
                "reads in same file — mongo-vs-pg field name drift signal."
            ),
        })
    return findings


def scan_h2(path: Path, text: str) -> list[dict]:
    """H2: file uses BOTH `.rows` and `.data` access → envelope drift."""
    findings: list[dict] = []
    if H2_ROWS_RE.search(text) and H2_DATA_RE.search(text):
        findings.append({
            "heuristic": "H2",
            "kind": "mixed_envelope",
            "file": str(path),
            "evidence": (
                "file dereferences both `.rows` and `.data` — likely flat-vs-"
                "nested response envelope drift."
            ),
        })
    return findings


def scan_h3(path: Path, text: str) -> list[dict]:
    """H3: useParams<{X}> where X doesn't appear in route path declarations.

    Tolerant: looks at route paths in same file. Cross-file route registration
    requires a project-wide route map (out of scope for B95 advisory).
    """
    findings: list[dict] = []
    use_params_names = {m.group(1) for m in H3_USEPARAMS_RE.finditer(text)}
    if not use_params_names:
        return findings
    route_params: set[str] = set()
    for m in H3_ROUTE_PARAM_RE.finditer(text):
        path_str = m.group("path")
        for piece in path_str.split("/"):
            if piece.startswith(":"):
                route_params.add(piece[1:])
    if not route_params:
        return findings
    mismatched = use_params_names - route_params
    if mismatched:
        findings.append({
            "heuristic": "H3",
            "kind": "useparams_route_mismatch",
            "file": str(path),
            "evidence": (
                f"useParams<{{{', '.join(sorted(mismatched))}}}> doesn't match "
                f"route params {sorted(route_params)} in same file."
            ),
        })
    return findings


def scan_all(repo_root: Path) -> dict:
    files = find_fe_sources(repo_root)
    findings: list[dict] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        findings.extend(scan_h1(f, text))
        findings.extend(scan_h2(f, text))
        findings.extend(scan_h3(f, text))
    return {
        "scanned": len(files),
        "findings": findings,
        "by_heuristic": {
            h: sum(1 for f in findings if f["heuristic"] == h)
            for h in ("H1", "H2", "H3")
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="verify-fe-be-shape-coherence",
        description=(
            "B95 v4.68.0 advisory — detect FE-BE response shape drift "
            "(issue #197 build-gate proposal, partial). Static heuristics "
            "only; runtime per-route GET check deferred to a future batch."
        ),
    )
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--severity", choices=("warn", "block"), default="warn",
                    help="warn = exit 0 with findings listed; block = exit 1 on findings")
    ap.add_argument("--json", dest="json_out", action="store_true", default=True)
    ap.add_argument("--no-json", dest="json_out", action="store_false")
    args = ap.parse_args()
    try:
        repo = Path(args.repo_root).resolve()
        result = scan_all(repo)
        result["severity"] = args.severity
        status = "FAIL" if result["findings"] else "PASS"
        result["status"] = status
        if args.json_out:
            print(json.dumps(result))
        else:
            print(f"verify-fe-be-shape-coherence — {status}")
            print(f"  scanned: {result['scanned']} files")
            print(f"  by_heuristic: {result['by_heuristic']}")
            if result["findings"]:
                print("  findings:")
                for f in result["findings"][:30]:
                    print(f"    - [{f['heuristic']}] {f['file']}: {f['evidence']}")
        if result["findings"] and args.severity == "block":
            return 1
        return 0
    except Exception as exc:
        print(f"verify-fe-be-shape-coherence: internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
