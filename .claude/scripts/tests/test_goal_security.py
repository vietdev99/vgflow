"""
Phase B v2.5 (2026-04-23) — verify-goal-security.py tests.

Validates goal-level OWASP + CSRF + rate_limit + auth_model declarations
in TEST-GOALS.md frontmatter. Severity matrix:
- critical_goal_domain + owasp empty → HARD BLOCK
- mutation + csrf/rate_limit empty → HARD BLOCK
- auth_model mismatch vs API-CONTRACTS Block 1 → HARD BLOCK
- read-only GET + section empty → WARN
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-goal-security.py"


def _setup(tmp_path: Path, goals_md: str,
           contracts_md: str | None = None) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "09-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text(goals_md, encoding="utf-8")
    if contracts_md is not None:
        (phase_dir / "API-CONTRACTS.md").write_text(
            contracts_md, encoding="utf-8",
        )

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

GOOD_CRITICAL_AUTH_GOAL = """\
# Phase 9 test goals

---
id: G-01
title: "User login with password"
priority: critical
surface: api
trigger: "POST /api/v1/auth/login from client"
security_checks:
  owasp_top10_2021:
    - "A01:Broken-Access-Control: rate limit + CAPTCHA"
    - "A03:Injection: Zod schema parameterized query"
    - "A07:Identification-Auth: bcrypt work factor 12"
  asvs_level2:
    - "V5.1.1: input validation per field"
  rate_limit: "5/min per IP, 10/hr per user"
  csrf: "SameSite=Strict session cookie + double-submit"
  xss_protection: "React auto-escape + CSP strict"
  auth_model: "public"
  pii_fields: ["email", "password"]
perf_budget:
  p50_ms: 200
  p95_ms: 500
verification: automated
---
"""


def test_critical_goal_with_full_security_passes(tmp_path):
    repo = _setup(tmp_path, GOOD_CRITICAL_AUTH_GOAL)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_critical_domain_missing_owasp_blocks(tmp_path):
    goals = """\
---
id: G-01
title: "User login"
priority: critical
surface: api
trigger: "POST /api/v1/auth/login"
security_checks:
  auth_model: "public"
  rate_limit: "5/min"
  csrf: "SameSite Strict"
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert any(e["type"] == "security_critical_domain_missing_owasp"
               for e in out["evidence"])


def test_mutation_missing_csrf_blocks(tmp_path):
    goals = """\
---
id: G-02
title: "Create site"
priority: important
surface: api
trigger: "POST /api/v1/sites"
security_checks:
  owasp_top10_2021:
    - "A01: owner check"
  rate_limit: "10/min"
  auth_model: "authenticated"
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert any(e["type"] == "security_mutation_missing_csrf"
               for e in out["evidence"])


def test_mutation_missing_rate_limit_blocks(tmp_path):
    goals = """\
---
id: G-02
title: "Update campaign budget"
priority: important
surface: api
trigger: "PUT /api/v1/campaigns/{id}/budget"
security_checks:
  owasp_top10_2021:
    - "A01: owner check"
  csrf: "SameSite Strict"
  auth_model: "owner_only"
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert any(e["type"] == "security_mutation_missing_rate_limit"
               for e in out["evidence"])


def test_read_only_get_missing_section_warns(tmp_path):
    goals = """\
---
id: G-03
title: "List reports"
priority: important
surface: api
trigger: "GET /api/v1/reports"
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0  # WARN, not block
    assert out["verdict"] == "WARN"
    assert any(e["type"] == "security_readonly_missing_section"
               for e in out["evidence"])


def test_auth_model_mismatch_with_contract_blocks(tmp_path):
    goals = """\
---
id: G-04
title: "Delete ad unit"
priority: important
surface: api
trigger: "DELETE /api/v1/ad-units/{id}"
security_checks:
  owasp_top10_2021:
    - "A01: owner check"
  rate_limit: "5/min"
  csrf: "SameSite Strict"
  auth_model: "public"
verification: automated
---
"""
    contracts = """\
## DELETE /api/v1/ad-units/{id}

**Auth:** Owner only

Body...
"""
    repo = _setup(tmp_path, goals, contracts)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert any(e["type"] == "security_auth_model_mismatch"
               for e in out["evidence"])


def test_auth_model_matches_contract_passes(tmp_path):
    goals = """\
---
id: G-04
title: "Delete ad unit"
priority: important
surface: api
trigger: "DELETE /api/v1/ad-units/{id}"
security_checks:
  owasp_top10_2021:
    - "A01: owner check"
  rate_limit: "5/min"
  csrf: "SameSite Strict"
  auth_model: "owner_only"
verification: automated
---
"""
    contracts = """\
## DELETE /api/v1/ad-units/{id}

**Auth:** Owner only

Body...
"""
    repo = _setup(tmp_path, goals, contracts)
    r = _run(repo)
    assert r.returncode == 0


def test_multiple_violations_reported(tmp_path):
    goals = """\
---
id: G-01
title: "Login"
priority: critical
surface: api
trigger: "POST /api/auth/login"
security_checks:
  auth_model: "public"
verification: automated
---

---
id: G-02
title: "Create advert"
priority: important
surface: api
trigger: "POST /api/adverts"
security_checks:
  auth_model: "authenticated"
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    ev_types = [e["type"] for e in out["evidence"]]
    assert "security_critical_domain_missing_owasp" in ev_types  # G-01
    assert "security_mutation_missing_csrf" in ev_types          # G-02
    assert "security_mutation_missing_rate_limit" in ev_types    # G-02


def test_no_test_goals_file_skips(tmp_path):
    phase_dir = tmp_path / ".vg" / "phases" / "09-test"
    phase_dir.mkdir(parents=True)
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "9"],
        cwd=tmp_path, capture_output=True, text=True, timeout=10, env=env,
    )
    assert r.returncode == 0


def test_mutation_with_full_security_passes(tmp_path):
    goals = """\
---
id: G-02
title: "Update campaign status"
priority: important
surface: api
trigger: "PUT /api/v1/campaigns/{id}/status"
security_checks:
  owasp_top10_2021:
    - "A01:Broken-Access-Control: owner check via middleware"
    - "A03:Injection: Zod + Prisma parameterized"
  rate_limit: "20/min per user"
  csrf: "SameSite=Strict + double-submit token"
  auth_model: "owner_only"
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_non_endpoint_goal_skips_mutation_check(tmp_path):
    """Goals không có endpoint trigger (ví dụ background job) → skip
    mutation csrf/rate_limit check."""
    goals = """\
---
id: G-05
title: "Cron aggregates daily stats"
priority: important
surface: time-driven
actor: cron (system, runs 0 0 * * *)
trigger: "Cron fires at midnight UTC"
verification: automated
---
"""
    repo = _setup(tmp_path, goals)
    r = _run(repo)
    out = _parse(r.stdout)
    # No endpoint → no mutation check; no critical domain → no OWASP check;
    # no GET → no readonly warn; PASS
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_registered_in_build_and_review_and_unquarantinable():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main",
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_main"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    assert "verify-goal-security" in mod.COMMAND_VALIDATORS.get("vg:build", [])
    assert "verify-goal-security" in mod.COMMAND_VALIDATORS.get("vg:review", [])
    assert "verify-goal-security" in mod.UNQUARANTINABLE
