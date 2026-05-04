from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate-api-docs.py"
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-api-docs-coverage.py"


def _run(cmd: list[str], repo: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        cmd,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_generate_api_docs_emits_machine_readable_entries(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-api"
    phase.mkdir(parents=True)
    contracts = phase / "API-CONTRACTS.md"
    contracts.write_text(
        "# API Contracts\n\n"
        "## GET /api/campaigns\n\n"
        "**Auth:** admin\n\n"
        "**Request:**\n"
        "| Field | Type | Required | Source |\n"
        "|---|---|---|---|\n"
        "| status | string | no | query param, enum: pending/flagged |\n"
        "| page | number | no | query param |\n"
        "| limit | number | no | query param |\n\n"
        "**Response:**\n"
        "| Field | Type | Description | Source |\n"
        "|---|---|---|---|\n"
        "| data | array | Campaign objects | Zod |\n"
        "| data[].id | string | id | Zod |\n",
        encoding="utf-8",
    )
    (phase / "PLAN.md").write_text("# PLAN\n", encoding="utf-8")
    (phase / "TEST-GOALS.md").write_text(
        "## Goal G-01\n\ntrigger GET /api/campaigns\n", encoding="utf-8"
    )
    standards = {
        "schema": "interface-standards.v1",
        "surfaces": {"api": True, "frontend": True},
        "api": {
            "error_envelope": {
                "message_priority": ["error.user_message", "error.message", "message"],
                "required_shape": {"ok": False, "error": {"code": "string", "message": "string"}},
            }
        },
        "frontend": {"http_status_text_banned": True},
    }
    (phase / "INTERFACE-STANDARDS.json").write_text(json.dumps(standards), encoding="utf-8")
    route_file = repo / "apps" / "api" / "src" / "campaigns.ts"
    route_file.parent.mkdir(parents=True, exist_ok=True)
    route_file.write_text("app.get('/campaigns')\n", encoding="utf-8")
    out = phase / "API-DOCS.md"

    result = _run([
        sys.executable, str(GENERATOR),
        "--phase", "14",
        "--contracts", str(contracts),
        "--plan", str(phase / "PLAN.md"),
        "--goals", str(phase / "TEST-GOALS.md"),
        "--interface-standards", str(phase / "INTERFACE-STANDARDS.json"),
        "--out", str(out),
    ], repo)

    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "## GET /api/campaigns" in text
    assert "\"status\"" in text
    assert "\"pending\"" in text
    assert "\"paging_semantics\"" in text
    assert "\"error_handling\"" in text
    assert "error.user_message" in text
    assert "Do not display HTTP status/statusText" in text


def test_generate_api_docs_extracts_zod_query_shape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-api"
    phase.mkdir(parents=True)
    contracts = phase / "API-CONTRACTS.md"
    contracts.write_text(
        "# API Contracts\n\n"
        "## GET /api/v1/admin/topup-requests\n\n"
        "**Purpose:** Admin lists all topup requests across merchants with filters.\n\n"
        "```ts\n"
        "export const AdminListTopupRequestsQuery = z.object({\n"
        "  status: z.enum(['pending', 'approved', 'rejected', 'flagged']).optional(),\n"
        "  merchant: z.string().optional(),\n"
        "  gateway: z.string().optional(),\n"
        "  flagged: z.coerce.boolean().optional(),\n"
        "  cursor: z.string().optional(),\n"
        "});\n"
        "```\n",
        encoding="utf-8",
    )
    out = phase / "API-DOCS.md"
    result = _run([
        sys.executable, str(GENERATOR),
        "--phase", "14",
        "--contracts", str(contracts),
        "--out", str(out),
    ], repo)

    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "\"status\"" in text
    assert "\"flagged\"" in text
    assert "\"cursor\"" in text
    assert "status must constrain returned rows/items" in text
    assert "changing filter/search must reset pagination" in text


def test_api_docs_validator_blocks_missing_endpoint(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-api"
    phase.mkdir(parents=True)
    (phase / "API-CONTRACTS.md").write_text(
        "## GET /api/campaigns\n\n**Request:**\n| Field | Type | Required | Source |\n"
        "|---|---|---|---|\n| page | number | no | query param |\n",
        encoding="utf-8",
    )
    (phase / "API-DOCS.md").write_text("# API Docs\n", encoding="utf-8")

    result = _run([
        sys.executable, str(VALIDATOR),
        "--contracts", str(phase / "API-CONTRACTS.md"),
        "--docs", str(phase / "API-DOCS.md"),
    ], repo)

    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert result.returncode == 1
    assert payload["verdict"] == "BLOCK"
    assert any(e["type"] in {"api_docs_no_entries", "api_docs_endpoint_missing"}
               for e in payload["evidence"])


def test_api_docs_validator_blocks_missing_zod_query_param(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-api"
    phase.mkdir(parents=True)
    (phase / "API-CONTRACTS.md").write_text(
        "## GET /api/v1/admin/topup-requests\n\n"
        "```ts\n"
        "export const AdminListTopupRequestsQuery = z.object({\n"
        "  status: z.enum(['pending', 'flagged']).optional(),\n"
        "  cursor: z.string().optional(),\n"
        "});\n"
        "```\n",
        encoding="utf-8",
    )
    (phase / "API-DOCS.md").write_text(
        "# API Docs\n\n"
        "## GET /api/v1/admin/topup-requests\n\n"
        "```json\n"
        + json.dumps({
            "method": "GET",
            "path": "/api/v1/admin/topup-requests",
            "purpose": "Admin list",
            "request": {"query": {}},
            "response": {"fields": []},
            "implementation": {"route_hits": ["apps/api/src/routes.ts"]},
            "ai_notes": {"filter_semantics": [], "paging_semantics": []},
        })
        + "\n```\n",
        encoding="utf-8",
    )

    result = _run([
        sys.executable, str(VALIDATOR),
        "--contracts", str(phase / "API-CONTRACTS.md"),
        "--docs", str(phase / "API-DOCS.md"),
    ], repo)

    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert result.returncode == 1
    assert any(e["type"] == "api_docs_query_param_missing" for e in payload["evidence"])


def test_api_docs_validator_requires_error_handling_when_interface_standard_exists(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-api"
    phase.mkdir(parents=True)
    (phase / "API-CONTRACTS.md").write_text(
        "## GET /api/campaigns\n\n"
        "**Response:**\n"
        "| Field | Type | Description | Source |\n"
        "|---|---|---|---|\n"
        "| data | array | Campaign objects | Zod |\n",
        encoding="utf-8",
    )
    (phase / "INTERFACE-STANDARDS.json").write_text(
        json.dumps({"schema": "interface-standards.v1", "surfaces": {"api": True}}),
        encoding="utf-8",
    )
    (phase / "API-DOCS.md").write_text(
        "# API Docs\n\n"
        "## GET /api/campaigns\n\n"
        "```json\n"
        + json.dumps({
            "method": "GET",
            "path": "/api/campaigns",
            "purpose": "List campaigns",
            "request": {"query": {}},
            "response": {"fields": ["data"]},
            "implementation": {"route_hits": ["apps/api/src/routes.ts"]},
            "ai_notes": {},
        })
        + "\n```\n",
        encoding="utf-8",
    )

    result = _run([
        sys.executable, str(VALIDATOR),
        "--contracts", str(phase / "API-CONTRACTS.md"),
        "--docs", str(phase / "API-DOCS.md"),
    ], repo)

    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert result.returncode == 1
    assert any(e["type"] == "api_docs_error_handling_missing" for e in payload["evidence"])
