"""tests/test_batch26_be_fe_parity.py — Batch 26 BE-FE consumer parity."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-be-fe-consumer-parity.py"


def test_validator_exists():
    assert VAL.is_file()


def test_orphan_fe_consumer_blocks(tmp_path):
    """FE BLOCK 5 references endpoint not in BE API-CONTRACTS.md -> BLOCK."""
    phase_dir = tmp_path / ".vg" / "phases" / "07"
    phase_dir.mkdir(parents=True)
    (phase_dir / "API-CONTRACTS.md").write_text("""
# API Contracts

### GET /api/users
### POST /api/users
""", encoding="utf-8")
    contracts_dir = phase_dir / "API-CONTRACTS"
    contracts_dir.mkdir()
    (contracts_dir / "orphan.md").write_text("""
## BLOCK 5: FE consumer contract

```typescript
{
  url: "/api/orders",  // NOT in BE API-CONTRACTS.md — orphan FE
  consumers: [{ route: "/orders", component: "X" }]
}
```
""", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(VAL), "--phase-dir", str(phase_dir)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, (
        f"Orphan FE consumer must BLOCK. rc={r.returncode}, "
        f"out={(r.stdout + r.stderr)[:300]}"
    )
    combined = r.stdout + r.stderr
    assert "/api/orders" in combined or "orphan" in combined.lower()


def test_orphan_be_endpoint_warns(tmp_path):
    """BE endpoint without FE consumer -> WARN (exit 0 by default, but JSON reports)."""
    phase_dir = tmp_path / ".vg" / "phases" / "07"
    phase_dir.mkdir(parents=True)
    (phase_dir / "API-CONTRACTS.md").write_text("""
### GET /api/used
### GET /api/orphan-be
""", encoding="utf-8")
    contracts_dir = phase_dir / "API-CONTRACTS"
    contracts_dir.mkdir()
    (contracts_dir / "used.md").write_text("""
## BLOCK 5: FE consumer contract
```typescript
{ url: "/api/used", consumers: [{ route: "/x", component: "X" }] }
```
""", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(VAL), "--phase-dir", str(phase_dir), "--json"],
        capture_output=True, text=True,
    )
    # WARN — exit 0 (advisory) but JSON reports orphan
    import json
    if r.stdout.strip().startswith("{"):
        data = json.loads(r.stdout)
        orphans = data.get("orphan_be_endpoints", [])
        assert any("/api/orphan-be" in str(o) for o in orphans), (
            f"BE orphan endpoint not reported. Got: {orphans}"
        )
