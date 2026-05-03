<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 5: L4a-iii — Spec drift detector (BLOCK)

**Files:**
- Create: `scripts/validators/verify-spec-drift.py`
- Test: `tests/test_spec_drift_validator.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_spec_drift_validator.py`:

```python
"""Spec drift detector — compares executor SUMMARY.md returns vs API-CONTRACTS spec.

Heuristic: contract declares 'Response 201: { id: string }' (sync). Build
output (BUILD-LOG/task-NN.md) implements 'returns 202 with task_id' (async).
That mismatch flags as BLOCK.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "validators" / "verify-spec-drift.py"


def test_sync_vs_async_drift_blocks(tmp_path: Path) -> None:
    pd = tmp_path / "phase"
    (pd / "API-CONTRACTS").mkdir(parents=True)
    (pd / "BUILD-LOG").mkdir()
    (pd / "API-CONTRACTS" / "post-api-invoices.md").write_text(textwrap.dedent("""
        # POST /api/invoices

        **Method:** POST
        **Path:** /api/invoices
        **Response 201:** { "id": "string" }
    """).strip(), encoding="utf-8")
    (pd / "BUILD-LOG" / "task-39.md").write_text(textwrap.dedent("""
        # task-39

        BE handler returns 202 with task_id (async worker enqueue).
        FE redirects to invoice list with merchant filter.
    """).strip(), encoding="utf-8")
    out = tmp_path / "evidence.json"
    result = subprocess.run(
        ["python3", str(GATE),
         "--phase-dir", str(pd),
         "--phase", "test-4.1",
         "--evidence-out", str(out)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1, result.stderr
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert ev["severity"] == "BLOCK"
    assert ev["category"] == "spec_drift"
    assert "task-39" in ev["summary"]


def test_matching_status_passes(tmp_path: Path) -> None:
    pd = tmp_path / "phase"
    (pd / "API-CONTRACTS").mkdir(parents=True)
    (pd / "BUILD-LOG").mkdir()
    (pd / "API-CONTRACTS" / "get-api-health.md").write_text(textwrap.dedent("""
        # GET /api/health

        **Method:** GET
        **Path:** /api/health
        **Response 200:** { "ok": true }
    """).strip(), encoding="utf-8")
    (pd / "BUILD-LOG" / "task-01.md").write_text(textwrap.dedent("""
        # task-01

        Implements GET /api/health returning 200 { ok: true }.
    """).strip(), encoding="utf-8")
    result = subprocess.run(
        ["python3", str(GATE),
         "--phase-dir", str(pd),
         "--phase", "test-1.0"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run failing tests**

Run: `python3 -m pytest tests/test_spec_drift_validator.py -v`
Expected: 2 failures.

- [ ] **Step 3: Write the gate**

Create `scripts/validators/verify-spec-drift.py`:

```python
#!/usr/bin/env python3
"""verify-spec-drift.py — L4a-iii gate.

Conservative spec-drift detector. Reads:
  - API-CONTRACTS/<endpoint>.md per-endpoint contracts (Response NNN: { ... })
  - BUILD-LOG/task-*.md per-task summaries from executor

Detects status-code drift (e.g. contract says 201 sync, build log says 202
async). Body shape comparison is P3 (needs JSON Schema in contract +
extracted return shape from build log).

Heuristic patterns:
  - Contract:     "Response (\d{3}):"
  - BUILD-LOG:    "(returns|returning|HTTP|status code) (\d{3})"
  - Drift:        any 2xx in build log not present in contract response statuses
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CONTRACT_STATUS_RE = re.compile(r"\*\*Response (\d{3}):\*\*", re.IGNORECASE)
LOG_STATUS_RE = re.compile(
    r"\b(?:returns?|returning|HTTP|status\s*(?:code)?)\s*[:= ]?\s*(\d{3})\b",
    re.IGNORECASE,
)
ASYNC_HINT_RE = re.compile(r"\b(async|worker[- ]?async|enqueue|background)\b", re.IGNORECASE)


def _contract_statuses(contracts_dir: Path) -> dict[str, set[str]]:
    """Map contract path → set of declared response status codes."""
    out: dict[str, set[str]] = {}
    for cp in contracts_dir.glob("*.md"):
        if cp.name == "index.md":
            continue
        try:
            text = cp.read_text(encoding="utf-8")
        except OSError:
            continue
        statuses = set(CONTRACT_STATUS_RE.findall(text))
        if statuses:
            out[str(cp)] = statuses
    return out


def _log_drift(log_path: Path, declared_statuses: set[str]) -> dict | None:
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError:
        return None
    log_statuses = {m.group(1) for m in LOG_STATUS_RE.finditer(text)}
    if not log_statuses:
        return None
    drifted = log_statuses - declared_statuses
    drifted_2xx = {s for s in drifted if s.startswith("2")}
    if not drifted_2xx:
        return None
    is_async = bool(ASYNC_HINT_RE.search(text))
    return {
        "log_file": str(log_path),
        "declared": sorted(declared_statuses),
        "logged": sorted(log_statuses),
        "drifted_2xx": sorted(drifted_2xx),
        "async_hint": is_async,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-dir", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--evidence-out")
    args = parser.parse_args()

    pd = Path(args.phase_dir)
    contracts_dir = pd / "API-CONTRACTS"
    build_log_dir = pd / "BUILD-LOG"
    if not contracts_dir.exists() or not build_log_dir.exists():
        print(f"ERROR: phase missing API-CONTRACTS/ or BUILD-LOG/", file=sys.stderr)
        return 2

    contract_statuses = _contract_statuses(contracts_dir)
    if not contract_statuses:
        print("✓ no contract status codes declared — spec drift gate skipped (vacuous)")
        return 0

    # Pool all declared statuses across all contracts in phase (relaxed match —
    # exact contract↔log file pairing is P3 with cross-ref index).
    declared_pool: set[str] = set()
    for s in contract_statuses.values():
        declared_pool |= s

    drifts: list[dict] = []
    for log in build_log_dir.glob("task-*.md"):
        d = _log_drift(log, declared_pool)
        if d:
            drifts.append(d)

    if not drifts:
        print(f"✓ spec drift: 0 detected (declared 2xx pool: {sorted(s for s in declared_pool if s.startswith('2'))})")
        return 0

    lines = []
    for d in drifts:
        task = Path(d["log_file"]).stem
        async_note = " (async hint detected)" if d["async_hint"] else ""
        lines.append(
            f"{task}: logged 2xx {d['drifted_2xx']} not in contract pool {[s for s in d['declared'] if s.startswith('2')]}{async_note}"
        )
    summary = f"{len(drifts)} task(s) with spec drift:\n  " + "\n  ".join(lines)

    evidence = {
        "warning_id": f"spec-drift-{args.phase}-{len(drifts)}",
        "severity": "BLOCK",
        "category": "spec_drift",
        "phase": args.phase,
        "evidence_refs": [
            {"file": d["log_file"], "task_id": Path(d["log_file"]).stem}
            for d in drifts
        ],
        "summary": summary,
        "detected_by": "verify-spec-drift.py",
        "detected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "owning_artifact": "API-CONTRACTS.md + BUILD-LOG/",
        "recommended_action": (
            "Either: (a) executor should re-implement to match contract status, "
            "OR (b) /vg:amend the contract to declare async response (+202)."
        ),
        "confidence": 0.7,
    }

    print(f"⛔ {summary}", file=sys.stderr)
    if args.evidence_out:
        Path(args.evidence_out).write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests + commit**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
chmod +x scripts/validators/verify-spec-drift.py
python3 -m pytest tests/test_spec_drift_validator.py -v
git add scripts/validators/verify-spec-drift.py tests/test_spec_drift_validator.py
git commit -m "feat(build-fix-loop): add L4a-iii spec drift BLOCK gate (status-code heuristic)"
```
Expected: 2 passed; commit made.

---

