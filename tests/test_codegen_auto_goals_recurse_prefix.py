"""Verify scripts/codegen-auto-goals.py whitelists G-RECURSE-* prefix
(in addition to G-AUTO-* / G-CRUD-*) so v2.40 recursive-probe goals
get codegen specs.

Task 26 (Phase 1.D core wiring).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "codegen-auto-goals.py"


def _build_phase(tmp_path: Path) -> Path:
    phase = tmp_path / "phase"
    phase.mkdir()
    # TEST-GOALS-DISCOVERED.md with one G-AUTO-* and one G-RECURSE-* yaml block.
    body = """\
# discovered

---
id: G-AUTO-admin-orders-add-order
title: \"Auto: click Add Order on /admin/orders\"
priority: important
surface: ui
source: review.runtime_discovery
evidence:
  view: \"/admin/orders\"
trigger: \"navigate /admin/orders, click Add Order\"
main_steps:
  - then: \"button visible\"
---

---
id: G-RECURSE-abc123def456
title: \"Recursive: row delete authz-negative on orders\"
priority: critical
surface: ui
source: review.recursive_probe
evidence:
  view: \"/admin/orders\"
  lens: lens-authz-negative
trigger: \"row delete as guest\"
main_steps:
  - then: \"403 on DELETE /api/orders/:id\"
---
"""
    (phase / "TEST-GOALS-DISCOVERED.md").write_text(body, encoding="utf-8")
    return phase


def test_codegen_emits_recurse_spec(tmp_path: Path) -> None:
    phase = _build_phase(tmp_path)
    out_dir = phase / "tests-auto"
    r = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--phase-dir", str(phase),
         "--out-dir", str(out_dir),
         "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    written = list(out_dir.glob("*.spec.ts"))
    names = sorted(p.name for p in written)
    has_auto = any("g-auto" in n.lower() for n in names)
    has_recurse = any("g-recurse" in n.lower() for n in names)
    assert has_auto, f"missing G-AUTO spec: {names}"
    assert has_recurse, f"missing G-RECURSE spec: {names}"


def test_codegen_dry_run_lists_recurse(tmp_path: Path) -> None:
    phase = _build_phase(tmp_path)
    out_dir = phase / "tests-auto"
    r = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--phase-dir", str(phase),
         "--out-dir", str(out_dir),
         "--dry-run", "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    files = payload.get("filenames") or payload.get("files") or []
    joined = " ".join(files) if isinstance(files, list) else json.dumps(payload)
    assert "g-recurse" in joined.lower(), f"recurse not in dry-run output: {payload}"
