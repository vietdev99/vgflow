<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 3: L4a-i — FE→BE call graph gate (BLOCK)

**Files:**
- Create: `scripts/validators/verify-fe-be-call-graph.py`
- Test: extend `tests/test_fe_be_call_graph.py` with gap detection

- [ ] **Step 1: Append gap-detection test**

Append to `tests/test_fe_be_call_graph.py`:

```python
def test_gap_detector_finds_fe_call_with_no_be_route(tmp_path: Path) -> None:
    fe = tmp_path / "fe"
    be = tmp_path / "be"
    fe.mkdir()
    be.mkdir()
    (fe / "Page.tsx").write_text(
        "axios.get('/api/v1/admin/invoices/' + id + '/payments');\n",
        encoding="utf-8",
    )
    (be / "router.ts").write_text(
        "router.post('/api/v1/admin/invoices/:id/payments', h);\n",
        encoding="utf-8",
    )
    gate = REPO / "scripts" / "validators" / "verify-fe-be-call-graph.py"
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = subprocess.run(
        ["python3", str(gate),
         "--fe-root", str(fe), "--be-root", str(be),
         "--phase", "test-1.0",
         "--evidence-out", str(out_dir / "evidence.json")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1, f"expected BLOCK, got {result.returncode}: {result.stderr}"
    evidence = json.loads((out_dir / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["severity"] == "BLOCK"
    assert evidence["category"] == "fe_be_call_graph"
    assert "GET" in evidence["summary"]
    assert "/api/v1/admin/invoices/:param/payments" in evidence["summary"]


def test_gap_detector_passes_when_all_fe_calls_have_routes(tmp_path: Path) -> None:
    fe = tmp_path / "fe"
    be = tmp_path / "be"
    fe.mkdir()
    be.mkdir()
    (fe / "Page.tsx").write_text(
        "axios.get('/api/v1/health');\n",
        encoding="utf-8",
    )
    (be / "router.ts").write_text(
        "router.get('/api/v1/health', h);\n",
        encoding="utf-8",
    )
    gate = REPO / "scripts" / "validators" / "verify-fe-be-call-graph.py"
    result = subprocess.run(
        ["python3", str(gate),
         "--fe-root", str(fe), "--be-root", str(be),
         "--phase", "test-1.0"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run failing tests**

Run: `python3 -m pytest tests/test_fe_be_call_graph.py::test_gap_detector_finds_fe_call_with_no_be_route -v`
Expected: fail (gate doesn't exist).

- [ ] **Step 3: Write the gate**

Create `scripts/validators/verify-fe-be-call-graph.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
chmod +x scripts/validators/verify-fe-be-call-graph.py
python3 -m pytest tests/test_fe_be_call_graph.py -v
```
Expected: 6 passed (4 from Task 2 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/validators/verify-fe-be-call-graph.py tests/test_fe_be_call_graph.py
git commit -m "feat(build-fix-loop): add L4a-i FE→BE call graph BLOCK gate"
```

---

