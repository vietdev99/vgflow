"""pre-executor-check.py should inject the relevant CRUD-SURFACES.md slice."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "pre-executor-check.py"


def test_pre_executor_outputs_matching_crud_surface_slice(tmp_path: Path) -> None:
    phase = tmp_path / ".vg" / "phases" / "09-crud"
    phase.mkdir(parents=True)
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "vg.config.md").write_text(
        "profile: web-fullstack\n"
        "build_gates:\n"
        "  typecheck_cmd: pnpm typecheck\n"
        "contract_format:\n"
        "  generated_types_path: packages/contracts\n",
        encoding="utf-8",
    )
    (phase / "PLAN.md").write_text(
        "## Task 1: Campaign list table\n\n"
        "<goals-covered>G-01</goals-covered>\n"
        "<edits-endpoint>GET /api/campaigns</edits-endpoint>\n"
        "Build the Campaign list table with paging and filters.\n",
        encoding="utf-8",
    )
    (phase / "API-CONTRACTS.md").write_text(
        "### GET /api/campaigns\n\nReturns paginated Campaign rows.\n",
        encoding="utf-8",
    )
    (phase / "TEST-GOALS.md").write_text(
        "## Goal G-01: Campaign list table\n\n"
        "User can filter and page Campaign records.\n",
        encoding="utf-8",
    )
    (phase / "CRUD-SURFACES.md").write_text(
        "```json\n"
        + json.dumps({
            "version": "1",
            "resources": [{
                "name": "Campaign",
                "operations": ["list"],
                "base": {
                    "roles": ["admin"],
                    "business_flow": {"invariants": ["tenant scoped"]},
                    "security": {
                        "object_auth": "tenant scope",
                        "field_auth": "visible fields only",
                        "rate_limit": "60/min",
                    },
                    "abuse": {
                        "enumeration_guard": "no cross-tenant ids",
                        "replay_guard": "safe GET only",
                    },
                    "performance": {"api_p95_ms": 250},
                },
                "platforms": {
                    "web": {
                        "list": {
                            "route": "/campaigns",
                            "heading": "Campaigns",
                            "description": "Manage campaigns",
                            "states": ["loading", "empty", "error"],
                            "data_controls": {
                                "filters": [{"name": "status"}],
                                "search": {"url_param": "q"},
                                "sort": {"columns": ["created_at"]},
                                "pagination": {"url_param_page": "page"},
                            },
                            "table": {
                                "columns": ["name", "status"],
                                "row_actions": ["view"],
                            },
                            "accessibility": {
                                "table_headers": "scope=col",
                                "aria_sort": "aria-sort",
                            },
                        }
                    }
                },
            }],
        }, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--phase-dir",
            str(phase),
            "--task-num",
            "1",
            "--config",
            str(tmp_path / ".claude" / "vg.config.md"),
            "--repo-root",
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ready"
    crud = payload["crud_surface_context"]
    assert "CRUD-SURFACES.md" in crud
    assert "Campaign" in crud
    assert "/campaigns" in crud
    assert "table" in crud
