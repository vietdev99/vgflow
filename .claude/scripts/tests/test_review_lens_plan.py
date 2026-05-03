from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "review-lens-plan.py"


def _run(repo: Path, phase_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--phase-dir", str(phase_dir), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_review_lens_plan_requires_filter_paging_from_contracts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-api"
    phase.mkdir(parents=True)
    (phase / "TEST-GOALS.md").write_text(
        "## Goal G-09: Admin topup queue list with filters\n"
        "**Surface:** ui\n"
        "**interactive_controls:**\n"
        "url_sync: true\n"
        "filters:\n"
        "  - {name: status, options: [pending, flagged], url_param: status}\n",
        encoding="utf-8",
    )
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

    result = _run(repo, phase, "--profile", "web-fullstack", "--mode", "full", "--write", "--json")
    assert result.returncode == 0, result.stderr
    plan = json.loads((phase / "REVIEW-LENS-PLAN.json").read_text(encoding="utf-8"))
    required = {p["id"] for p in plan["plugins"] if p["required"]}
    checklists = {c["id"]: c for c in plan["checklists"]}
    assert "be_check" in checklists
    assert "fe_check" in checklists
    assert "api_docs_contract_coverage" in required
    assert "api_contract_runtime_probe" in required
    assert "goal_security_declaration_gate" in required
    assert "security_baseline_gate" in required
    assert "goal_performance_budget_gate" in required
    assert "browser_surface_inventory" in required
    assert "api_error_message_lens" in required
    assert "url_state_lens" in required
    assert "filter_lens" in required
    assert "paging_lens" in required
    assert any(p["id"] == "filter_lens" and p["step"] == "phase2_8_url_state_runtime"
               for p in plan["plugins"])
    assert any(p["id"] == "api_error_message_lens" and p["step"] == "phase2_9_error_message_runtime"
               for p in plan["plugins"])


def test_review_lens_plan_validate_flags_evidence_location_drift(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-api"
    (phase / "_evidence").mkdir(parents=True)
    (phase / "TEST-GOALS.md").write_text(
        "## Goal G-01: UI list\n**Surface:** ui\n",
        encoding="utf-8",
    )
    (phase / "_evidence" / "scan-admin.json").write_text("{}", encoding="utf-8")

    result = _run(repo, phase, "--profile", "web-fullstack", "--mode", "full", "--validate-only", "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    reasons = [m["reason"] for m in payload["missing"]]
    assert any("RUNTIME-MAP.json missing" in r for r in reasons)
    assert any("only under _evidence" in r for r in reasons)


def test_review_lens_plan_validate_requires_each_required_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-api"
    phase.mkdir(parents=True)
    (phase / "TEST-GOALS.md").write_text(
        "## Goal G-09: Admin topup queue list with filters\n"
        "**Surface:** ui\n"
        "**interactive_controls:**\n"
        "url_sync: true\n"
        "filters:\n"
        "  - {name: status, options: [pending, flagged], url_param: status}\n",
        encoding="utf-8",
    )
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
    (phase / "api-contract-precheck.txt").write_text("ok", encoding="utf-8")

    result = _run(repo, phase, "--profile", "web-fullstack", "--mode", "full", "--validate-only", "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(
        m["plugin"] == "api_docs_contract_coverage"
        and m.get("expected") == "api-docs-check.txt"
        for m in payload["missing"]
    )


def test_review_lens_plan_backend_profile_wires_be_without_browser(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-api"
    phase.mkdir(parents=True)
    (phase / "API-CONTRACTS.md").write_text(
        "## POST /api/orders\n\n"
        "```ts\n"
        "export const CreateOrderBody = z.object({id: z.string()});\n"
        "```\n",
        encoding="utf-8",
    )

    result = _run(repo, phase, "--profile", "web-backend-only", "--mode", "full", "--write", "--json")
    assert result.returncode == 0, result.stderr
    plan = json.loads((phase / "REVIEW-LENS-PLAN.json").read_text(encoding="utf-8"))
    required = {p["id"] for p in plan["plugins"] if p["required"]}
    assert "api_docs_contract_coverage" in required
    assert "api_contract_runtime_probe" in required
    assert "goal_security_declaration_gate" in required
    assert "security_baseline_gate" in required
    assert "backend_mutation_evidence" in required
    assert "browser_surface_inventory" not in required
    be = next(c for c in plan["checklists"] if c["id"] == "be_check")
    assert "phase2a_api_contract_probe" in be["steps"]
    security = next(c for c in plan["checklists"] if c["id"] == "security_check")
    assert "phase4_goal_comparison" in security["steps"]


def test_review_lens_plan_cli_profile_wires_cli_surface(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-cli"
    phase.mkdir(parents=True)
    result = _run(repo, phase, "--profile", "cli-tool", "--mode", "full", "--write", "--json")
    assert result.returncode == 0, result.stderr
    plan = json.loads((phase / "REVIEW-LENS-PLAN.json").read_text(encoding="utf-8"))
    required = {p["id"] for p in plan["plugins"] if p["required"]}
    assert "cli_goal_surface_probe" in required
    assert "browser_surface_inventory" not in required


def test_review_lens_plan_non_full_modes_have_profile_plugins(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-infra"
    phase.mkdir(parents=True)
    result = _run(repo, phase, "--profile", "web-backend-only", "--mode", "infra-smoke", "--write", "--json")
    assert result.returncode == 0, result.stderr
    plan = json.loads((phase / "REVIEW-LENS-PLAN.json").read_text(encoding="utf-8"))
    required = {p["id"] for p in plan["plugins"] if p["required"]}
    assert "infra_success_criteria_smoke" in required
    assert any(c["id"] == "infra_check" and "phaseP_infra_smoke" in c["steps"]
               for c in plan["checklists"])


def test_review_command_runs_security_and_perf_validators_with_phase_args() -> None:
    text = (REPO_ROOT / "commands" / "vg" / "review.md").read_text(encoding="utf-8")
    assert "verify-interface-standards verify-goal-security verify-goal-perf verify-security-baseline" in text
    assert "verify-error-message-runtime" in text
    assert "verify-interface-standards)" in text
    assert "verify-error-message-runtime)" in text
    assert "verify-goal-security|verify-goal-perf)" in text
    assert '"$VAL_PATH" --phase "${PHASE_NUMBER}"' in text
    assert "verify-security-baseline)" in text
    assert '"$VAL_PATH" --phase "${PHASE_NUMBER}" --scope all' in text


def test_review_lens_plan_injects_phase_local_plugin_overlay(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-ui"
    phase.mkdir(parents=True)
    (phase / "TEST-GOALS.md").write_text(
        "## Goal G-01: UI export\n**Surface:** ui\n",
        encoding="utf-8",
    )
    (phase / "REVIEW-LENS-PLUGINS.json").write_text(
        json.dumps({
            "plugins": [
                {
                    "id": "export_csv_lens",
                    "title": "Export CSV semantics",
                    "checklist": "fe_check",
                    "step": "phase2_8_url_state_runtime",
                    "evidence": ["export-csv-probe.json"],
                    "reason": "Export buttons need file content evidence.",
                    "required_when": {
                        "profiles": ["web-*"],
                        "modes": ["full"],
                        "text_contains_any": [
                            {"path": "TEST-GOALS.md", "contains": "export"}
                        ],
                    },
                }
            ]
        }),
        encoding="utf-8",
    )

    result = _run(repo, phase, "--profile", "web-fullstack", "--mode", "full", "--validate-only", "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    required = {p["id"] for p in payload["plan"]["plugins"] if p["required"]}
    assert "export_csv_lens" in required
    assert any(m["plugin"] == "export_csv_lens" and m["expected"] == "export-csv-probe.json"
               for m in payload["missing"])


def test_review_lens_plan_custom_overlay_checklist(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "14-api"
    phase.mkdir(parents=True)
    (phase / "REVIEW-LENS-PLUGINS.json").write_text(
        json.dumps({
            "plugins": [
                {
                    "id": "websocket_lens",
                    "title": "WebSocket event stream",
                    "checklist": "realtime_check",
                    "checklist_title": "Realtime checks",
                    "step": "phase4_goal_comparison",
                    "evidence": ["websocket-probe.json"],
                    "required": True,
                }
            ]
        }),
        encoding="utf-8",
    )

    result = _run(repo, phase, "--profile", "web-fullstack", "--mode", "full", "--write", "--json")
    assert result.returncode == 0, result.stderr
    plan = json.loads((phase / "REVIEW-LENS-PLAN.json").read_text(encoding="utf-8"))
    assert any(c["id"] == "realtime_check" and c["title"] == "Realtime checks"
               for c in plan["checklists"])
    assert any(p["id"] == "websocket_lens" and p["source"].endswith("REVIEW-LENS-PLUGINS.json")
               for p in plan["plugins"])
