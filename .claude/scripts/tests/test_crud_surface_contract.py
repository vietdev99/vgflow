"""Regression tests for verify-crud-surface-contract.py."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-crud-surface-contract.py"


def _run(repo: Path, phase: str = "9") -> tuple[int, dict]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", phase, "--config", str(repo / ".claude" / "vg.config.md")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    return proc.returncode, payload


def _phase(repo: Path, profile: str = "web-fullstack") -> Path:
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "vg.config.md").write_text(f"profile: {profile}\n", encoding="utf-8")
    phase = repo / ".vg" / "phases" / "09-crud"
    phase.mkdir(parents=True, exist_ok=True)
    (phase / "SPECS.md").write_text(
        "Build Campaign list table with filter, paging, create form, update form, and delete confirm.\n",
        encoding="utf-8",
    )
    (phase / "API-CONTRACTS.md").write_text(
        "### GET /api/campaigns\n\n### POST /api/campaigns\n\n### PATCH /api/campaigns/{id}\n\n### DELETE /api/campaigns/{id}\n",
        encoding="utf-8",
    )
    (phase / "TEST-GOALS.md").write_text(
        "## G-01: Campaigns list table\n\n## G-02: Create campaign form\n",
        encoding="utf-8",
    )
    return phase


def _contract(*, include_web: bool = True, include_backend: bool = True, include_mobile: bool = False) -> dict:
    platforms: dict = {}
    if include_web:
        platforms["web"] = {
            "list": {
                "route": "/campaigns",
                "heading": "Campaigns",
                "description": "Manage campaigns",
                "states": ["loading", "empty", "error", "ready"],
                "data_controls": {
                    "filters": [{"name": "status", "url_param": "status"}],
                    "search": {"url_param": "q", "debounce_ms": 300},
                    "sort": {"columns": ["created_at"], "url_param_field": "sort"},
                    "pagination": {"url_param_page": "page", "page_size": 20},
                },
                "table": {
                    "columns": ["name", "status", "created_at"],
                    "row_actions": ["edit", "delete"],
                },
                "accessibility": {"table_headers": "scope=col", "aria_sort": "aria-sort"},
            },
            "form": {
                "fields": ["name", "status"],
                "validation": {"name": "required"},
                "error_summary": "top of form",
                "duplicate_submit_guard": "disable while pending",
            },
            "delete": {
                "confirm_dialog": "Requires campaign name confirmation",
                "post_delete_state": "row removed and empty state if last row",
            },
        }
    if include_backend:
        platforms["backend"] = {
            "list_endpoint": {
                "path": "GET /api/campaigns",
                "pagination": {"max_page_size": 100},
                "filter_sort_allowlist": ["status", "created_at"],
                "stable_default_sort": "created_at desc, id desc",
                "invalid_query_behavior": "400 with error code",
            },
            "mutation": {
                "paths": ["POST /api/campaigns", "PATCH /api/campaigns/{id}", "DELETE /api/campaigns/{id}"],
                "validation_4xx": "422 field errors",
                "object_authz": "tenant scope on every id",
                "mass_assignment_guard": "field allowlist",
                "idempotency": "Idempotency-Key required for create/update/delete retries",
                "audit_log": "actor, before, after",
            },
        }
    if include_mobile:
        platforms["mobile"] = {
            "list": {
                "screen": "CampaignList",
                "deep_link_state": "campaigns?status=active&page=2",
                "pull_to_refresh": "refresh current filter",
                "pagination_pattern": "load-more",
                "tap_target_min_px": 44,
                "states": ["loading", "empty", "error", "ready"],
                "network_error_state": "retry banner",
            },
            "form": {
                "screen": "CampaignForm",
                "keyboard_avoidance": "enabled",
                "native_picker_behavior": "status picker",
                "submit_disabled_during_request": "true",
                "offline_submit_policy": "queue disabled; show offline error",
            },
            "delete": {
                "confirm_sheet": "destructive bottom sheet",
                "undo_or_soft_delete_policy": "soft delete with undo snackbar",
            },
        }
    return {
        "version": "1",
        "generated_from": ["SPECS.md", "API-CONTRACTS.md", "TEST-GOALS.md", "PLAN.md"],
        "resources": [{
            "name": "Campaign",
            "operations": ["list", "create", "update", "delete"],
            "base": {
                "roles": ["admin"],
                "business_flow": {"invariants": ["campaign belongs to tenant"]},
                "security": {
                    "object_auth": "tenant scoped",
                    "field_auth": "role-based field allowlist",
                    "rate_limit": "60/minute per actor",
                },
                "abuse": {
                    "enumeration_guard": "404 across tenants",
                    "replay_guard": "idempotency key",
                },
                "performance": {"api_p95_ms": 300},
                "delete_policy": {
                    "confirm": "destructive confirmation required",
                    "reversible_policy": "soft delete for 30 days",
                    "audit_log": "delete audit row",
                },
            },
            "platforms": platforms,
        }],
    }


def _write_contract(phase: Path, data: dict) -> None:
    phase.joinpath("CRUD-SURFACES.md").write_text(
        "```json\n" + json.dumps(data, indent=2) + "\n```\n",
        encoding="utf-8",
    )


def test_web_fullstack_contract_with_web_and_backend_passes(tmp_path: Path) -> None:
    phase = _phase(tmp_path, "web-fullstack")
    _write_contract(phase, _contract())
    rc, payload = _run(tmp_path)
    assert rc == 0, payload
    assert payload["verdict"] == "PASS"


def test_missing_contract_blocks_when_crud_signals_exist(tmp_path: Path) -> None:
    _phase(tmp_path, "web-fullstack")
    rc, payload = _run(tmp_path)
    assert rc == 1
    assert payload["verdict"] == "BLOCK"
    assert any(e["type"] == "crud_surface_contract_missing" for e in payload["evidence"])


def test_mobile_profile_requires_mobile_overlay_not_web_table_overlay(tmp_path: Path) -> None:
    phase = _phase(tmp_path, "mobile-app")
    _write_contract(phase, _contract(include_web=False, include_backend=False, include_mobile=True))
    rc, payload = _run(tmp_path)
    assert rc == 0, payload
    assert payload["verdict"] == "PASS"


def test_backend_mutation_missing_mass_assignment_guard_blocks(tmp_path: Path) -> None:
    phase = _phase(tmp_path, "web-backend-only")
    data = _contract(include_web=False, include_backend=True)
    del data["resources"][0]["platforms"]["backend"]["mutation"]["mass_assignment_guard"]
    _write_contract(phase, data)
    rc, payload = _run(tmp_path)
    assert rc == 1
    assert payload["verdict"] == "BLOCK"
    assert "mass_assignment_guard" in json.dumps(payload["evidence"])


def test_no_crud_signals_and_no_contract_passes(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "vg.config.md").write_text("profile: cli-tool\n", encoding="utf-8")
    phase = tmp_path / ".vg" / "phases" / "09-docs"
    phase.mkdir(parents=True)
    (phase / "SPECS.md").write_text("Polish README wording only.\n", encoding="utf-8")
    rc, payload = _run(tmp_path)
    assert rc == 0
    assert payload["verdict"] == "PASS"

def test_cli_no_crud_reason_allows_metadata_and_interface_words(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "vg.config.md").write_text("profile: cli-tool\n", encoding="utf-8")
    phase = tmp_path / ".vg" / "phases" / "09-cli-health"
    phase.mkdir(parents=True)
    (phase / "SPECS.md").write_text(
        "---\n"
        "profile: feature\n"
        "platform: cli-tool\n"
        "created_at: \"2026-05-04\"\n"
        "created: \"2026-05-04\"\n"
        "---\n"
        "Codex path can create specs and validate phase artifacts.\n",
        encoding="utf-8",
    )
    (phase / "PLAN.md").write_text(
        "---\nprofile: feature\nplatform: cli-tool\n---\n"
        "## Wave 1\n- Task 01: CLI health behavior only.\n",
        encoding="utf-8",
    )
    (phase / "API-CONTRACTS.md").write_text(
        "# CLI Contract\n\n"
        "There is no HTTP transport and no persistent resource mutation.\n",
        encoding="utf-8",
    )
    _write_contract(phase, {
        "version": "1",
        "generated_from": ["CONTEXT.md", "API-CONTRACTS.md", "TEST-GOALS.md", "PLAN.md"],
        "no_crud_reason": (
            "CLI-only health behavior; no user resource CRUD, no HTTP API, "
            "no frontend/mobile UI, no database."
        ),
        "resources": [],
    })
    rc, payload = _run(tmp_path)
    assert rc == 0, payload
    assert payload["verdict"] == "PASS"

def test_web_phase_empty_resources_still_blocks(tmp_path: Path) -> None:
    phase = _phase(tmp_path, "web-fullstack")
    _write_contract(phase, {
        "version": "1",
        "generated_from": ["SPECS.md", "API-CONTRACTS.md", "TEST-GOALS.md", "PLAN.md"],
        "no_crud_reason": "incorrectly declared no CRUD",
        "resources": [],
    })
    rc, payload = _run(tmp_path)
    assert rc == 1
    assert payload["verdict"] == "BLOCK"
    assert any(e["type"] == "crud_surface_resources_empty" for e in payload["evidence"])

def test_be_only_phase_in_fullstack_skips_web_overlay(tmp_path: Path) -> None:
    """Issue #26: Backend-only phase in a web-fullstack project.

    Phase has API/DB content (matches WEB_SIGNAL_RE prose like "table",
    "form", "view" because of "wallet table schema" / "form validation
    in handler") but PLAN.md has zero FE source paths. Validator should
    require platforms.backend ONLY — not platforms.web.
    """
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "vg.config.md").write_text(
        "profile: web-fullstack\n", encoding="utf-8")
    phase = tmp_path / ".vg" / "phases" / "03-wallet-ledger"
    phase.mkdir(parents=True)
    # FE-leaning prose in SPECS (table/form) — these are the false-positive
    # words from real BE-only phase docs ("wallet table schema",
    # "form validation in handler") that triggered the bug.
    (phase / "SPECS.md").write_text(
        "Wallet ledger foundation: balance table schema with audit log,\n"
        "credit/debit handler with form validation, view permissions on\n"
        "GET /api/wallet/{id}, mutation guards on POST /api/wallet/credit.\n",
        encoding="utf-8")
    (phase / "API-CONTRACTS.md").write_text(
        "### GET /api/wallet/{id}\n\n### POST /api/wallet/credit\n\n"
        "### POST /api/wallet/debit\n",
        encoding="utf-8")
    # PLAN.md task list with NO FE source paths — only backend files.
    (phase / "PLAN.md").write_text(
        "## Wave 1\n"
        "- Task 01: apps/api/src/wallet/ledger.ts handler\n"
        "- Task 02: apps/api/src/wallet/migration.sql\n"
        "- Task 03: apps/api/test/wallet.test.ts\n",
        encoding="utf-8")
    # CRUD contract supplies backend overlay only.
    contract = _contract(include_web=False, include_backend=True)
    _write_contract(phase, contract)
    rc, payload = _run(tmp_path, phase="3")
    assert rc == 0, payload
    assert payload["verdict"] == "PASS"


def test_fullstack_phase_with_fe_source_in_plan_requires_web(tmp_path: Path) -> None:
    """Counter-test: PLAN.md cites apps/admin/ → require platforms.web."""
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "vg.config.md").write_text(
        "profile: web-fullstack\n", encoding="utf-8")
    phase = tmp_path / ".vg" / "phases" / "08-admin-dashboard"
    phase.mkdir(parents=True)
    (phase / "SPECS.md").write_text(
        "Admin dashboard for campaigns.\n", encoding="utf-8")
    (phase / "API-CONTRACTS.md").write_text(
        "### GET /api/campaigns\n", encoding="utf-8")
    (phase / "PLAN.md").write_text(
        "## Wave 1\n"
        "- Task 01: apps/admin/src/pages/Campaigns.tsx\n"
        "- Task 02: apps/api/src/campaigns/list.ts\n",
        encoding="utf-8")
    # Contract with backend only — should BLOCK because PLAN cites .tsx
    contract = _contract(include_web=False, include_backend=True)
    _write_contract(phase, contract)
    rc, payload = _run(tmp_path, phase="8")
    assert rc == 1
    assert payload["verdict"] == "BLOCK"
    assert any("platforms.web" in e.get("message", "") for e in payload["evidence"])
