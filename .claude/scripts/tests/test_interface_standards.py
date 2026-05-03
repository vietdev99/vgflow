from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "commands" / "vg").exists() and (parent / "scripts").exists():
            return parent
        if (parent / ".claude" / "commands" / "vg").exists() and (parent / ".claude" / "scripts").exists():
            return parent
    raise AssertionError("repo root not found")


REPO_ROOT = _find_repo_root()
SCRIPT_ROOT = REPO_ROOT / "scripts"
if not (SCRIPT_ROOT / "generate-interface-standards.py").exists():
    SCRIPT_ROOT = REPO_ROOT / ".claude" / "scripts"
COMMAND_ROOT = REPO_ROOT / "commands" / "vg"
if not COMMAND_ROOT.exists():
    COMMAND_ROOT = REPO_ROOT / ".claude" / "commands" / "vg"
GENERATOR = SCRIPT_ROOT / "generate-interface-standards.py"
VALIDATOR = SCRIPT_ROOT / "validators" / "verify-interface-standards.py"
ERROR_RUNTIME = SCRIPT_ROOT / "validators" / "verify-error-message-runtime.py"


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


def _phase(repo: Path, name: str = "14-api") -> Path:
    phase = repo / ".vg" / "phases" / name
    phase.mkdir(parents=True, exist_ok=True)
    return phase


def _write_contract_with_interface_rule(phase: Path) -> None:
    (phase / "API-CONTRACTS.md").write_text(
        "# API Contracts\n\n"
        "## POST /api/orders\n\n"
        "Block 3 follows INTERFACE-STANDARDS.md.\n"
        "FE toast rule: response.data.error.user_message || response.data.error.message.\n",
        encoding="utf-8",
    )


def _write_standard(phase: Path) -> None:
    (phase / "INTERFACE-STANDARDS.json").write_text(
        json.dumps({
            "schema": "interface-standards.v1",
            "phase": "14",
            "profile": "web-fullstack",
            "surfaces": {"api": True, "frontend": True, "cli": False, "mobile": False},
            "api": {
                "error_envelope": {
                    "required_fields": [
                        "error.code", "error.message", "error.user_message",
                        "error.field_errors", "error.request_id",
                    ],
                    "message_priority": ["error.user_message", "error.message", "message", "network_fallback"],
                    "required_shape": {"ok": False, "error": {"code": "string", "message": "string"}},
                }
            },
            "frontend": {
                "api_error_message_priority": ["error.user_message", "error.message", "message", "network_fallback"],
                "http_status_text_banned": True,
            },
            "cli": {"machine_mode": "--json"},
        }),
        encoding="utf-8",
    )
    (phase / "INTERFACE-STANDARDS.md").write_text(
        "# Interface Standards\n\n"
        "## API Standard\n\n"
        "## Frontend Error Handling Standard\n\n"
        "## CLI Standard\n\n"
        "## Harness Enforcement\n\n",
        encoding="utf-8",
    )


def _payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_generator_writes_phase_local_standard_for_api_ui(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = _phase(repo)
    (phase / "SPECS.md").write_text("## Goal\nAPI UI toast handling\n", encoding="utf-8")
    _write_contract_with_interface_rule(phase)

    result = _run([
        sys.executable, str(GENERATOR),
        "--phase-dir", str(phase),
        "--profile", "web-fullstack",
        "--force",
    ], repo)

    assert result.returncode == 0, result.stderr
    payload = json.loads((phase / "INTERFACE-STANDARDS.json").read_text(encoding="utf-8"))
    assert payload["schema"] == "interface-standards.v1"
    assert payload["surfaces"]["api"] is True
    assert payload["surfaces"]["frontend"] is True
    assert payload["frontend"]["api_error_message_priority"][:2] == [
        "error.user_message", "error.message",
    ]
    assert "Request failed with status" in (phase / "INTERFACE-STANDARDS.md").read_text(encoding="utf-8")


def test_cli_surface_inference_ignores_out_of_scope_mentions(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = _phase(repo, "1-codex-fixture-cli-health")
    phase.joinpath("SPECS.md").write_text(
        "# SPECS\n\n"
        "## Goal\n\n"
        "Provide a dependency-free CLI health command with `--json` output.\n\n"
        "## Scope\n\n"
        "- Standardize stdout, stderr, exit codes, and `--json` automation output.\n\n"
        "## Out of Scope\n\n"
        "- HTTP API endpoints, frontend pages, mobile screens, and database behavior.\n",
        encoding="utf-8",
    )

    gen = _run([
        sys.executable, str(GENERATOR),
        "--phase-dir", str(phase),
        "--profile", "cli-tool",
        "--force",
    ], repo)

    assert gen.returncode == 0, gen.stderr
    payload = json.loads((phase / "INTERFACE-STANDARDS.json").read_text(encoding="utf-8"))
    assert payload["surfaces"] == {
        "api": False,
        "frontend": False,
        "cli": True,
        "mobile": False,
    }

    val = _run([
        sys.executable, str(VALIDATOR),
        "--phase-dir", str(phase),
        "--profile", "cli-tool",
        "--no-scan-source",
    ], repo)
    assert val.returncode == 0, val.stdout + val.stderr
    assert _payload(val)["verdict"] == "PASS"


def test_interface_validator_blocks_missing_standard_for_api_phase(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = _phase(repo)
    _write_contract_with_interface_rule(phase)

    result = _run([
        sys.executable, str(VALIDATOR),
        "--phase-dir", str(phase),
        "--profile", "web-fullstack",
        "--no-scan-source",
    ], repo)

    payload = _payload(result)
    assert result.returncode == 1
    assert any(e["type"] == "interface_md_missing" for e in payload["evidence"])
    assert any(e["type"] == "interface_json_missing" for e in payload["evidence"])


def test_interface_validator_blocks_raw_error_message_toast(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = _phase(repo)
    _write_contract_with_interface_rule(phase)
    _write_standard(phase)
    ui = repo / "apps" / "web" / "src" / "page.tsx"
    ui.parent.mkdir(parents=True, exist_ok=True)
    ui.write_text(
        "try { await save(); } catch (error) { toast.error(error.message); }\n",
        encoding="utf-8",
    )

    result = _run([
        sys.executable, str(VALIDATOR),
        "--phase-dir", str(phase),
        "--profile", "web-fullstack",
    ], repo)

    payload = _payload(result)
    assert result.returncode == 1
    assert any(e["type"] == "interface_bad_toast_error_message" for e in payload["evidence"])


def test_error_message_runtime_passes_when_api_message_visible(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = _phase(repo)
    _write_contract_with_interface_rule(phase)
    _write_standard(phase)
    (phase / "error-message-probe.json").write_text(
        json.dumps({
            "checks": [{
                "api_user_message": "Amount is required",
                "visible_message": "Amount is required",
                "passed": True,
            }]
        }),
        encoding="utf-8",
    )

    result = _run([sys.executable, str(ERROR_RUNTIME), "--phase-dir", str(phase)], repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _payload(result)["verdict"] == "PASS"


def test_error_message_runtime_blocks_transport_text(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase = _phase(repo)
    _write_contract_with_interface_rule(phase)
    _write_standard(phase)
    (phase / "error-message-probe.json").write_text(
        json.dumps({
            "checks": [{
                "api_error_message": "Only pending requests can be approved",
                "visible_message": "Request failed with status 403",
                "passed": True,
            }]
        }),
        encoding="utf-8",
    )

    result = _run([sys.executable, str(ERROR_RUNTIME), "--phase-dir", str(phase)], repo)

    payload = _payload(result)
    assert result.returncode == 1
    types = {e["type"] for e in payload["evidence"]}
    assert "error_message_transport_text_visible" in types
    assert "error_message_api_message_not_visible" in types


def test_workflow_commands_wire_interface_standard_and_error_lens() -> None:
    commands = COMMAND_ROOT
    specs = (commands / "specs.md").read_text(encoding="utf-8")
    blueprint = (commands / "blueprint.md").read_text(encoding="utf-8")
    build = (commands / "build.md").read_text(encoding="utf-8")
    build_waves = (
        commands / "_shared" / "build" / "waves-delegation.md"
    ).read_text(encoding="utf-8")
    review = (commands / "review.md").read_text(encoding="utf-8")
    test = (commands / "test.md").read_text(encoding="utf-8")
    test_preflight = (
        commands / "_shared" / "test" / "preflight.md"
    ).read_text(encoding="utf-8")
    tasklist = (SCRIPT_ROOT / "emit-tasklist.py").read_text(encoding="utf-8")

    assert "write_interface_standards" in specs
    assert "INTERFACE-STANDARDS.md" in blueprint
    assert (
        "<interface_standards_context>" in build
        or "<interface_standards_context>" in build_waves
    )
    assert "phase2_9_error_message_runtime" in review
    assert "verify-error-message-runtime.py" in review
    assert (
        "verify-interface-standards.py" in test
        or "verify-interface-standards.py" in test_preflight
    )
    assert "Specs And Interface Standards" in tasklist
    assert "phase2_9_error_message_runtime" in tasklist


def test_orchestrator_registers_interface_validator() -> None:
    import importlib.util

    orchestrator_path = SCRIPT_ROOT / "vg-orchestrator" / "__main__.py"
    spec = importlib.util.spec_from_file_location("vg_orchestrator_interface_test", orchestrator_path)
    assert spec and spec.loader
    orchestrator_main = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_interface_test"] = orchestrator_main
    spec.loader.exec_module(orchestrator_main)

    for command in ("vg:blueprint", "vg:build", "vg:review", "vg:test"):
        assert "verify-interface-standards" in orchestrator_main.COMMAND_VALIDATORS.get(command, [])
    assert "verify-interface-standards" in orchestrator_main.UNQUARANTINABLE
