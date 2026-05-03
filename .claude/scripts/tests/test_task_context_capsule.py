from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_EXECUTOR = REPO_ROOT / "scripts" / "pre-executor-check.py"
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-task-context-capsule.py"
BUILD_MD = REPO_ROOT / "commands" / "vg" / "build.md"


def _make_phase(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "09-capsule"
    phase.mkdir(parents=True)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "vg.config.md").write_text(
        "build_gates:\n"
        "  typecheck_cmd: pnpm typecheck\n"
        "contract_format:\n"
        "  generated_types_path: packages/contracts\n",
        encoding="utf-8",
    )
    (phase / "PLAN.md").write_text(
        "## Task 1: Campaign create form\n\n"
        "<file-path>apps/web/src/campaigns/CreateCampaign.tsx</file-path>\n"
        "<context-refs>P9.D-01</context-refs>\n"
        "<goals-covered>G-01</goals-covered>\n"
        "<edits-endpoint>POST /api/campaigns</edits-endpoint>\n"
        "Build the create form and persist campaign rows.\n",
        encoding="utf-8",
    )
    (phase / "CONTEXT.md").write_text(
        "### P9.D-01 Campaign creation\n\n"
        "**Endpoints:** POST /api/campaigns\n"
        "**Test Scenarios:** create campaign and refresh list\n",
        encoding="utf-8",
    )
    (phase / "API-CONTRACTS.md").write_text(
        "### POST /api/campaigns\n\n"
        "Request: name, status. Response: id, name, status.\n",
        encoding="utf-8",
    )
    (phase / "TEST-GOALS.md").write_text(
        "## Goal G-01: Create campaign\n\n"
        "**Mutation evidence:** POST /api/campaigns returns 201 and list row +1\n\n"
        "**Persistence check:** refresh and re-read campaign row.\n",
        encoding="utf-8",
    )
    (phase / "CRUD-SURFACES.md").write_text(
        "```json\n"
        + json.dumps({
            "version": "1",
            "resources": [{
                "name": "Campaign",
                "operations": ["create"],
                "base": {
                    "roles": ["admin"],
                    "business_flow": {"invariants": ["tenant scoped"]},
                    "security": {"object_auth": "tenant scope", "field_auth": "allowlist"},
                    "abuse": {"duplicate_submit_guard": "idempotency key"},
                    "performance": {"api_p95_ms": 250},
                },
                "platforms": {
                    "web": {
                        "form": {
                            "route": "/campaigns/new",
                            "heading": "New campaign",
                            "fields": ["name", "status"],
                            "validation": ["name required"],
                            "submit": {"duplicate_submit_guard": True},
                        }
                    },
                    "backend": {
                        "api": {
                            "field_allowlist": ["name", "status"],
                            "idempotency": "required",
                        }
                    },
                },
            }],
        })
        + "\n```\n",
        encoding="utf-8",
    )
    return repo


def _run(cmd: list[str], repo: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        cmd,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_pre_executor_writes_task_context_capsule(tmp_path: Path) -> None:
    repo = _make_phase(tmp_path)
    phase = repo / ".vg" / "phases" / "09-capsule"
    capsule_path = phase / ".task-context-capsules" / "task-1.json"

    result = _run([
        sys.executable,
        str(PRE_EXECUTOR),
        "--phase-dir",
        str(phase),
        "--task-num",
        "1",
        "--config",
        str(repo / ".claude" / "vg.config.md"),
        "--repo-root",
        str(repo),
        "--capsule-out",
        str(capsule_path),
    ], repo)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    assert payload["task_context_capsule"] == capsule
    assert capsule["capsule_version"] == "1"
    assert capsule["task_num"] == 1
    assert capsule["goals"] == ["G-01"]
    assert capsule["context_refs"] == ["P9.D-01"]
    assert "POST /api/campaigns" in capsule["endpoints"]
    assert capsule["execution_contract"]["requires_persistence_check"] is True
    assert capsule["required_context"]["crud_surface_context"] == "present"


def test_capsule_validator_blocks_prompt_without_capsule(tmp_path: Path) -> None:
    repo = _make_phase(tmp_path)
    phase = repo / ".vg" / "phases" / "09-capsule"
    prompt_dir = phase / ".build" / "wave-1" / "executor-prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "1.meta.json").write_text(json.dumps({"task_id": 1}), encoding="utf-8")
    (prompt_dir / "1.prompt.md").write_text("<task_context>only body</task_context>\n", encoding="utf-8")
    capsule_dir = phase / ".task-context-capsules"
    capsule_dir.mkdir()
    (capsule_dir / "task-1.json").write_text(
        json.dumps({
            "capsule_version": "1",
            "task_num": 1,
            "source_artifacts": {},
            "required_context": {"task_context": "present"},
            "execution_contract": {},
            "goals": [],
            "endpoints": [],
            "file_paths": [],
            "anti_lazy_read_rules": [],
        }),
        encoding="utf-8",
    )

    result = _run([sys.executable, str(VALIDATOR), "--phase", "09"], repo)
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["verdict"] == "BLOCK"
    assert any(e["type"] == "capsule_not_in_prompt" for e in payload["evidence"])


def test_capsule_validator_passes_when_prompt_contains_capsule(tmp_path: Path) -> None:
    repo = _make_phase(tmp_path)
    phase = repo / ".vg" / "phases" / "09-capsule"
    capsule = {
        "capsule_version": "1",
        "task_num": 1,
        "source_artifacts": {},
        "required_context": {
            "task_context": "present",
            "contract_context": "present",
            "goals_context": "present",
            "crud_surface_context": "present",
        },
        "execution_contract": {
            "must_follow_api_contract": True,
            "requires_persistence_check": True,
            "must_follow_crud_surface": True,
        },
        "goals": ["G-01"],
        "endpoints": ["POST /api/campaigns"],
        "file_paths": ["apps/web/src/campaigns/CreateCampaign.tsx"],
        "anti_lazy_read_rules": ["read capsule first"],
    }
    prompt_dir = phase / ".build" / "wave-1" / "executor-prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "1.meta.json").write_text(json.dumps({"task_id": 1}), encoding="utf-8")
    (prompt_dir / "1.prompt.md").write_text(
        "<task_context_capsule>\n"
        + json.dumps(capsule, indent=2)
        + "\n</task_context_capsule>\n",
        encoding="utf-8",
    )
    capsule_dir = phase / ".task-context-capsules"
    capsule_dir.mkdir()
    (capsule_dir / "task-1.json").write_text(json.dumps(capsule), encoding="utf-8")

    result = _run([sys.executable, str(VALIDATOR), "--phase", "09"], repo)
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["verdict"] == "PASS"


def test_build_workflow_wires_capsule_generation_and_prompt_injection() -> None:
    build = BUILD_MD.read_text(encoding="utf-8")

    assert "--capsule-out \"$TASK_CAPSULE_PATH\"" in build
    assert "TASK_CONTEXT_CAPSULE=" in build
    assert "<task_context_capsule path=" in build
    assert ".task-context-capsules" in build
