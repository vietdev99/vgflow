"""
Phase B.2 v2.5 (2026-04-23) — verify-goal-perf.py tests.

Validates goal-level perf_budget declarations in TEST-GOALS.md frontmatter.
Severity matrix:
- mutation + perf_budget empty → HARD BLOCK (perf_mutation_missing_budget)
- GET list endpoint + p95_ms empty → HARD BLOCK (perf_list_missing_p95)
- Single-record GET + perf_budget empty → WARN (perf_single_missing_budget)
- surface=ui + bundle_kb_fe_route empty → WARN (perf_ui_missing_bundle)
- mutation/list + n_plus_one_max empty → WARN (perf_nplus1_missing)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-goal-perf.py"


def _setup(tmp_path: Path, goals_md: str) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "09-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text(goals_md, encoding="utf-8")

    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")
    return tmp_path


def _run(repo: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "9"],
        cwd=repo, capture_output=True, text=True, timeout=20, env=env,
    )


def _parse(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        s = line.strip()
        if s.startswith("{"):
            return json.loads(s)
    raise AssertionError(f"no JSON:\n{stdout}")


# ─────────────────────────────────────────────────────────────────────────

MUTATION_FULL_PERF = """\
---
id: G-01
title: "Create site"
priority: important
surface: api
trigger: "POST /api/v1/sites"
perf_budget:
  p50_ms: 80
  p95_ms: 250
  p99_ms: 500
  n_plus_one_max: 3
  cache_strategy: "Redis 5min TTL"
verification: automated
---
"""


def test_mutation_with_full_perf_passes(tmp_path):
    repo = _setup(tmp_path, MUTATION_FULL_PERF)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_mutation_missing_budget_blocks(tmp_path):
    goals = """\
---
id: G-02
title: "Update campaign budget"
priority: important
surface: api
trigger: "PUT /api/v1/campaigns/{id}/budget"
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert out["verdict"] == "BLOCK"
    assert any(e["type"] == "perf_mutation_missing_budget"
               for e in out["evidence"])


def test_list_get_missing_p95_blocks(tmp_path):
    goals = """\
---
id: G-03
title: "List sites"
priority: important
surface: api
trigger: "GET /api/v1/sites"
perf_budget:
  p50_ms: 80
  cache_strategy: "Redis 5min TTL"
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert out["verdict"] == "BLOCK"
    assert any(e["type"] == "perf_list_missing_p95"
               for e in out["evidence"])


def test_single_record_get_missing_warns(tmp_path):
    goals = """\
---
id: G-04
title: "Get site details"
priority: important
surface: api
trigger: "GET /api/v1/sites/{id}"
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "WARN"
    assert any(e["type"] == "perf_single_missing_budget"
               for e in out["evidence"])


def test_ui_surface_missing_bundle_warns(tmp_path):
    goals = """\
---
id: G-05
title: "Render dashboard chart"
priority: important
surface: ui
trigger: "Click dashboard tab"
perf_budget:
  p50_ms: 50
  p95_ms: 150
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "WARN"
    assert any(e["type"] == "perf_ui_missing_bundle"
               for e in out["evidence"])


def test_full_perf_non_mutation_non_list_passes(tmp_path):
    """Non-endpoint goals (or paths that are neither list nor single-record
    nor mutation) pass even without perf_budget — no rule applies."""
    goals = """\
---
id: G-06
title: "Cron aggregates daily stats"
priority: important
surface: time-driven
trigger: "Cron fires at midnight UTC"
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_mutation_missing_nplus1_warns(tmp_path):
    """Mutation has p50/p95 but missing n_plus_one_max → WARN (no BLOCK
    because perf_budget section is populated)."""
    goals = """\
---
id: G-07
title: "Create ad unit"
priority: important
surface: api
trigger: "POST /api/v1/ad-units"
perf_budget:
  p50_ms: 80
  p95_ms: 250
  cache_strategy: "no-cache"
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    # Not BLOCK — budget is populated. But n_plus_one_max empty → WARN.
    assert r.returncode == 0
    assert out["verdict"] == "WARN"
    assert any(e["type"] == "perf_nplus1_missing"
               for e in out["evidence"])
    # Should NOT block with mutation_missing since budget is populated.
    assert not any(e["type"] == "perf_mutation_missing_budget"
                   for e in out["evidence"])
