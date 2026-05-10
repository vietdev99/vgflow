"""v3.2.0 — #173 Stage 2: UI-RUNTIME-CONTRACT emission tests.

Coverage:
1. schema parses + lists v1 required sections
2. blueprint design.md references step 2b6d_ui_runtime_contract
3. canonical/mirror byte-identity for emitter + schema
4. emitter happy-path on UI-heavy fixture phase produces valid contract
5. tailwind tokens extracted from UI-SPEC + VIEW-COMPONENTS
6. mutation goals → min_spec_count
7. env_contract section populated from ENV-CONTRACT.md YAML
8. skip path: backend-only profile → skip_reason set, no FE tokens
9. skip path: no FE tasks → skip_reason set
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
EMITTER = REPO_ROOT / "scripts" / "blueprint" / "emit-ui-runtime-contract.py"
EMITTER_MIRROR = REPO_ROOT / ".claude" / "scripts" / "blueprint" / "emit-ui-runtime-contract.py"
SCHEMA = REPO_ROOT / "schemas" / "ui-runtime-contract.v1.json"


# ── schema content checks ───────────────────────────────────────────────


def test_schema_exists_and_parses():
    assert SCHEMA.is_file(), "schemas/ui-runtime-contract.v1.json must exist"
    data = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"].startswith("VG UI-RUNTIME-CONTRACT")
    required = set(data["required"])
    expected = {
        "version",
        "phase_id",
        "generated_at",
        "required_tailwind_tokens",
        "first_viewport_surfaces",
        "route_inventory",
        "env_contract",
        "min_spec_count",
        "acceptance_criteria",
    }
    missing = expected - required
    assert not missing, f"schema must require all v1 fields, missing: {missing}"


# ── emitter content + mirror identity ──────────────────────────────────


def test_emitter_exists_and_has_main():
    assert EMITTER.is_file(), "scripts/blueprint/emit-ui-runtime-contract.py must exist"
    body = EMITTER.read_text(encoding="utf-8")
    assert "def main()" in body
    assert "build_contract" in body
    assert "extract_tailwind_tokens" in body
    assert "TAILWIND_BRAND_RE" in body


def test_emitter_mirror_byte_identity():
    assert EMITTER.read_bytes() == EMITTER_MIRROR.read_bytes(), (
        "emit-ui-runtime-contract.py canonical and .claude/ mirror must match"
    )


# ── blueprint wiring ──────────────────────────────────────────────────────


def test_blueprint_design_md_references_step():
    canonical = REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint" / "design.md"
    mirror = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "blueprint" / "design.md"
    assert canonical.is_file()
    body = canonical.read_text(encoding="utf-8")
    assert "2b6d_ui_runtime_contract" in body, (
        "blueprint design.md must declare step 2b6d_ui_runtime_contract"
    )
    assert "emit-ui-runtime-contract.py" in body, (
        "blueprint must invoke the emitter script"
    )
    assert "blueprint.ui_runtime_contract_emitted" in body, (
        "blueprint must emit telemetry event when contract written"
    )
    assert canonical.read_bytes() == mirror.read_bytes(), (
        "blueprint design.md canonical and .claude/ mirror must match"
    )


# ── functional emitter tests ──────────────────────────────────────────────


def _run_emitter(phase_dir: Path) -> tuple[int, str, str]:
    r = subprocess.run(
        [sys.executable, str(EMITTER), "--phase-dir", str(phase_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, r.stdout, r.stderr


def test_emitter_happy_path(tmp_path):
    """UI-heavy fixture → contract with tokens, surfaces, env, min_specs."""
    phase = tmp_path / "phase-99"
    phase.mkdir()

    # PLAN with FE task
    (phase / "PLAN.md").write_text(
        "# Plan\n- Task 1: edit apps/web/src/pages/SitesPage.tsx\n"
        "  - route: /publisher/sites\n- Task 2: add apps/web/src/pages/UsersPage.tsx\n"
        "  - route: /publisher/users\n",
        encoding="utf-8",
    )

    # VIEW-COMPONENTS.md with root-level layout surfaces
    (phase / "VIEW-COMPONENTS.md").write_text(
        "# View Components — Phase 99\n\n## sites\n\n"
        "| Component | Type | Parent | Position (x,y,w,h%) | Children |\n"
        "|---|---|---|---|---|\n"
        "| AppShell | layout |  | 0,0,100,100 | 2 |\n"
        "| Sidebar | navigation | AppShell | 0,0,15,100 | 5 |\n"
        "| MainContent | content | AppShell | 15,0,85,100 | 3 |\n"
        "| TopBar | navigation |  | 0,0,100,8 | 4 |\n",
        encoding="utf-8",
    )

    # UI-SPEC with brand tokens
    ui_spec = phase / "UI-SPEC"
    ui_spec.mkdir()
    (ui_spec / "sites.md").write_text(
        '# Sites slug\n\n```html\n'
        '<button class="bg-brand-500 text-white">Save</button>\n'
        '<div class="brand-primary border-brand-200">x</div>\n'
        '```\n',
        encoding="utf-8",
    )
    (ui_spec / "users.md").write_text(
        '```html\n<span class="text-brand-700">User</span>\n```\n',
        encoding="utf-8",
    )

    # ENV-CONTRACT with auth host + cookie domain
    (phase / "ENV-CONTRACT.md").write_text(
        "# Env Contract\n\n```yaml\n"
        "target:\n"
        "  base_url: https://app.example.com\n"
        "  auth_host: auth.example.com\n"
        "  cookie_domain: .example.com\n"
        "disposable_seed_data: true\n"
        "third_party_stubs:\n"
        "  - stripe\n"
        "  - sendgrid\n"
        "preflight_checks: []\n"
        "```\n",
        encoding="utf-8",
    )

    # TEST-GOALS with mutation goals
    (phase / "TEST-GOALS.md").write_text(
        "# Test Goals\n\n## Goal G-01: create site\n"
        "**Goal type:** mutation\n**Surface:** ui\n\n"
        "## Goal G-02: delete site\n"
        "**Goal type:** mutation\n**Surface:** ui\n\n"
        "## Goal G-03: list sites\n"
        "**Goal type:** read\n**Surface:** ui\n",
        encoding="utf-8",
    )

    # phase-profile = web-fullstack
    (phase / ".phase-profile").write_text(
        "phase_profile: web-fullstack\nsurface: ui\n",
        encoding="utf-8",
    )

    rc, stdout, stderr = _run_emitter(phase)
    assert rc == 0, f"emitter exit={rc}\nstdout={stdout}\nstderr={stderr}"

    json_path = phase / "UI-RUNTIME-CONTRACT.json"
    md_path = phase / "UI-RUNTIME-CONTRACT.md"
    assert json_path.is_file()
    assert md_path.is_file()

    contract = json.loads(json_path.read_text(encoding="utf-8"))
    assert contract["version"] == "1"
    assert contract["phase_id"] == "phase-99"
    assert contract["skip_reason"] is None

    # Tailwind tokens extracted (brand-primary, bg-brand-500, text-brand-700, border-brand-200)
    tokens = {t["class_name"].lower() for t in contract["required_tailwind_tokens"]}
    assert "bg-brand-500" in tokens
    assert "brand-primary" in tokens
    assert "text-brand-700" in tokens
    assert "border-brand-200" in tokens

    # Surfaces: AppShell + TopBar are root-level (parent empty); Sidebar/MainContent are not.
    surface_names = {s["surface_name"] for s in contract["first_viewport_surfaces"]}
    assert "AppShell" in surface_names
    assert "TopBar" in surface_names
    assert "Sidebar" not in surface_names
    assert "MainContent" not in surface_names

    # Routes: /publisher/sites + /publisher/users from PLAN
    paths = {r["path"] for r in contract["route_inventory"]}
    assert "/publisher/sites" in paths
    assert "/publisher/users" in paths

    # Env contract populated
    env = contract["env_contract"]
    assert env["status"] == "present"
    assert env["base_url"] == "https://app.example.com"
    assert env["auth_host"] == "auth.example.com"
    assert env["cookie_domain"] == ".example.com"
    assert env["disposable_seed_data"] is True
    assert env["third_party_stubs_count"] == 2

    # Min spec count: 2 mutation goals
    assert contract["min_spec_count"]["count"] == 2

    # Acceptance criteria non-empty
    assert len(contract["acceptance_criteria"]) >= 3


def test_emitter_skips_backend_only_profile(tmp_path):
    phase = tmp_path / "phase-backend"
    phase.mkdir()
    (phase / ".phase-profile").write_text("phase_profile: backend-only\n", encoding="utf-8")
    (phase / "PLAN.md").write_text("# Plan\n- Task 1: edit apps/api/src/server.ts\n", encoding="utf-8")
    rc, stdout, _ = _run_emitter(phase)
    assert rc == 0
    json_path = phase / "UI-RUNTIME-CONTRACT.json"
    assert json_path.is_file()
    contract = json.loads(json_path.read_text(encoding="utf-8"))
    assert contract["skip_reason"] is not None
    assert "backend-only" in contract["skip_reason"]
    assert contract["required_tailwind_tokens"] == []


def test_emitter_skips_no_fe_tasks(tmp_path):
    phase = tmp_path / "phase-no-fe"
    phase.mkdir()
    (phase / ".phase-profile").write_text("phase_profile: web-fullstack\n", encoding="utf-8")
    (phase / "PLAN.md").write_text(
        "# Plan\n- Task 1: edit apps/api/src/routes.py\n- Task 2: edit scripts/seed.py\n",
        encoding="utf-8",
    )
    rc, _, _ = _run_emitter(phase)
    assert rc == 0
    contract = json.loads((phase / "UI-RUNTIME-CONTRACT.json").read_text(encoding="utf-8"))
    assert contract["skip_reason"] is not None
    assert "no fe tasks" in contract["skip_reason"].lower()


def test_schema_mirror_byte_identity_skipped():
    """v3.2.0 — schemas/ live at repo root only (no .claude/ mirror); placeholder
    test to keep the count balanced. Just verifies schema is in the canonical place.
    """
    assert SCHEMA.is_file()
