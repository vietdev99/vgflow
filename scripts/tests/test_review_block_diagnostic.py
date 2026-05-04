from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "review-block-diagnostic.py"


def _run(tmp_path: Path, gate_id: str, payload: dict | str) -> str:
    phase = tmp_path / ".vg" / "phases" / "03.2-demo"
    phase.mkdir(parents=True)
    inp = phase / ".tmp" / "input.json"
    inp.parent.mkdir(parents=True)
    if isinstance(payload, str):
        inp.write_text(payload, encoding="utf-8")
    else:
        inp.write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--gate-id",
            gate_id,
            "--phase-dir",
            str(phase),
            "--input",
            str(inp),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_api_docs_diagnostic_recommends_build_and_force_review(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        "review.api_docs_contract_coverage",
        {
            "evidence": [
                {
                    "type": "api_docs_query_param_missing",
                    "expected": "status",
                }
            ]
        },
    )
    assert "API-DOCS.md is stale" in out
    assert "/vg:build 3.2" in out
    assert "/vg:review 3.2 --mode=full --force" in out


def test_url_runtime_diagnostic_requires_probe_semantics(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        "review.url_state_runtime",
        {"evidence": [{"type": "url_runtime_probe_missing"}]},
    )
    assert "url-runtime-probe.json" in out
    assert "result_semantics" in out


def test_lens_plan_diagnostic_groups_missing_plugins(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        "review.lens_plan_gate",
        {
            "missing": [
                {
                    "plugin": "api_docs_contract_coverage",
                    "reason": "required plugin evidence artifact missing",
                    "expected": "api-docs-check.txt",
                },
                {
                    "plugin": "browser_surface_inventory",
                    "reason": "required plugin evidence artifact missing",
                    "expected": "RUNTIME-MAP.json",
                }
            ]
        },
    )
    assert "Required review checklist plugins did not produce evidence" in out
    assert "api_docs_contract_coverage" in out
    assert "browser_surface_inventory" in out


def test_error_message_diagnostic_recommends_adapter_and_probe(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        "review.error_message_runtime",
        {"evidence": [{"type": "error_message_transport_text_visible", "actual": "Request failed with status 403"}]},
    )
    assert "API error message is not proven" in out
    assert "error-message-probe.json" in out
    assert "error.user_message || error.message" in out


def test_interface_diagnostic_recommends_standard_generation(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        "review.interface_standards",
        {"evidence": [{"type": "interface_md_missing"}]},
    )
    assert "Interface standards are missing" in out
    assert "INTERFACE-STANDARDS.md" in out
    assert "Regenerate API contracts/docs" in out
