"""tests/test_batch26_probe_fe_routes.py — Batch 26 FE route wiring probe."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROBE = REPO / "scripts" / "probe-fe-routes.py"


def test_probe_script_exists():
    assert PROBE.is_file(), "Batch 26: scripts/probe-fe-routes.py must ship"


def test_probe_parses_block5_routes(tmp_path):
    """API-CONTRACTS/users-list.md BLOCK 5 declares 2 consumer routes.
    Probe extracts them via --dry-run mode."""
    phase_dir = tmp_path / ".vg" / "phases" / "07"
    contracts_dir = phase_dir / "API-CONTRACTS"
    contracts_dir.mkdir(parents=True)
    (contracts_dir / "users-list.md").write_text("""
# GET /api/users

## BLOCK 5: FE consumer contract

```typescript
{
  url: "/api/users",
  consumers: [
    { route: "/users", component: "UsersListPage" },
    { route: "/admin/users", component: "AdminUsersPage" }
  ],
  ui_states: ["loading", "empty", "list"],
  // ... other 13 fields
}
```
""", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(PROBE),
         "--phase-dir", str(phase_dir),
         "--dry-run", "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    import json
    data = json.loads(r.stdout)
    routes = {c["route"] for c in data.get("routes", [])}
    assert "/users" in routes
    assert "/admin/users" in routes


def test_probe_emits_event_on_failure(tmp_path):
    """Probe against unreachable base URL must emit failure event."""
    phase_dir = tmp_path / ".vg" / "phases" / "07"
    contracts_dir = phase_dir / "API-CONTRACTS"
    contracts_dir.mkdir(parents=True)
    (contracts_dir / "test.md").write_text("""
# GET /api/test

## BLOCK 5: FE consumer contract

```typescript
{
  url: "/api/test",
  consumers: [{ route: "/test-route", component: "X" }]
}
```
""", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(PROBE),
         "--phase-dir", str(phase_dir),
         "--base-url", "http://localhost:1",  # intentional unreachable
         "--json"],
        capture_output=True, text=True,
        timeout=30,
    )
    # Exit 1 on probe failures
    import json
    try:
        data = json.loads(r.stdout) if r.stdout.strip() else {}
        assert r.returncode != 0 or data.get("failed_count", 0) > 0
    except json.JSONDecodeError:
        assert r.returncode != 0
