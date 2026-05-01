"""Tests for scripts/spawn-diagnostic-l2.py — RFC v9 PR-D3."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "spawn-diagnostic-l2.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.diagnostic_l2 import load_proposal, proposal_dir  # noqa: E402


def _run(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "PYTHONPATH": str(REPO_ROOT / "scripts")}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        env=env, capture_output=True, text=True, timeout=30,
    )


def _make_stub_cli(tmp_path: Path, response: str) -> str:
    """Create a python script that, when run, prints `response` on stdout.

    Returns the shlex-joined command for --cli override. On Windows,
    `sys.executable` and `tmp_path` typically contain spaces (e.g.
    `C:\\Users\\Lionel Messi\\...\\python.exe`); joining with a bare space
    breaks `shlex.split` round-tripping. `shlex.join` quotes each token
    so the downstream split reconstructs the original 2-element argv.
    """
    stub = tmp_path / "stub_cli.py"
    stub.write_text(
        f"import sys\nprint({response!r})\n",
        encoding="utf-8",
    )
    return shlex.join([str(sys.executable), str(stub)])


def test_dry_run_emits_stub_proposal(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    result = _run(
        "--gate-id", "missing-evidence",
        "--block-family", "provenance",
        "--phase-dir", str(phase_dir),
        "--gate-context", "test gate",
        "--evidence-json", '{"goal":"G-10"}',
        "--dry-run",
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    out = json.loads(result.stdout)
    assert out["dry_run"] is True
    assert out["confidence"] == 0.0
    assert out["proposal_id"].startswith("l2-")
    # File written
    pid = out["proposal_id"]
    proposal = load_proposal(phase_dir, pid)
    assert proposal.gate_id == "missing-evidence"


def test_live_invocation_with_stub_cli(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    response = json.dumps({
        "diagnosis": "Mutation step at G-10/step[2] missing evidence.source",
        "proposed_fix": "Re-run scanner with /vg:review --re-scan-goals=G-10",
        "confidence": 0.85,
    })
    cli_cmd = _make_stub_cli(tmp_path, response)
    result = _run(
        "--gate-id", "missing-evidence",
        "--block-family", "provenance",
        "--phase-dir", str(phase_dir),
        "--gate-context", "G-10 lacks evidence after retry",
        "--evidence-json", '{"goal":"G-10"}',
        "--cli", cli_cmd,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = json.loads(result.stdout)
    assert out["confidence"] == 0.85
    assert "Re-run scanner" in out["proposed_fix"]
    proposal = load_proposal(phase_dir, out["proposal_id"])
    assert proposal.confidence == 0.85
    assert proposal.diagnosis.startswith("Mutation step")


def test_subagent_returns_short_diagnosis_fails(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    response = json.dumps({"diagnosis": "x", "proposed_fix": "y", "confidence": 0.5})
    cli_cmd = _make_stub_cli(tmp_path, response)
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
    )
    assert result.returncode == 1
    assert "too short" in json.loads(result.stdout)["error"]


def test_subagent_confidence_out_of_range(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    response = json.dumps({
        "diagnosis": "long enough diagnosis text",
        "proposed_fix": "long enough proposed fix text",
        "confidence": 1.5,
    })
    cli_cmd = _make_stub_cli(tmp_path, response)
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
    )
    assert result.returncode == 1
    assert "out of range" in json.loads(result.stdout)["error"]


def test_subagent_missing_fields_fails(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    # Missing confidence
    response = json.dumps({
        "diagnosis": "long enough diagnosis text",
        "proposed_fix": "long enough proposed fix text",
    })
    cli_cmd = _make_stub_cli(tmp_path, response)
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
    )
    assert result.returncode == 1
    assert "missing fields" in json.loads(result.stdout)["error"]


def test_subagent_emits_prose_around_json_still_parses(tmp_path):
    """Tolerance for models that wrap JSON in prose despite our instruction."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    json_block = json.dumps({
        "diagnosis": "long enough diagnosis here",
        "proposed_fix": "long enough proposed fix here",
        "confidence": 0.7,
    })
    response = f"Here's my analysis:\\n\\n{json_block}\\n\\nLet me know if you need more."
    cli_cmd = _make_stub_cli(tmp_path, response)
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
    )
    assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"


def test_subagent_invalid_json_fails(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    cli_cmd = _make_stub_cli(tmp_path, "not json at all")
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
    )
    assert result.returncode == 1
    assert "not valid JSON" in json.loads(result.stdout)["error"]


def test_subagent_nonzero_exit_fails(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    failing = tmp_path / "fail.py"
    failing.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
    cli_cmd = shlex.join([str(sys.executable), str(failing)])
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
    )
    assert result.returncode == 1
    assert "exited 2" in json.loads(result.stdout)["error"]


def test_phase_dir_missing_returns_2(tmp_path):
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(tmp_path / "nonexistent"),
        "--evidence-json", "{}",
        "--dry-run",
    )
    assert result.returncode == 2


def test_invalid_evidence_json_returns_2(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "not json",
        "--dry-run",
    )
    assert result.returncode == 2


def test_env_scrubbed_secrets_not_passed_to_subagent(tmp_path):
    """Codex-R4-HIGH-4: spawned CLI must NOT inherit secrets via env.
    Confirm CLAUDE_API_KEY etc. don't reach the subagent's env."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    # Stub CLI that dumps its env to stdout
    dump_env = tmp_path / "dump_env.py"
    dump_env.write_text(
        "import json, os, sys\n"
        "envs = sorted(os.environ)\n"
        "print(json.dumps({\n"
        "  'diagnosis': 'env keys: ' + str(envs[:5]) + '... long enough text',\n"
        "  'proposed_fix': 'inspect env keys: ' + str(envs[:5]),\n"
        "  'confidence': 0.5,\n"
        "}))\n",
        encoding="utf-8",
    )
    cli_cmd = shlex.join([str(sys.executable), str(dump_env)])
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
        env_extra={
            "CLAUDE_API_KEY": "sk-secret-test-key-12345",
            "AWS_SECRET_ACCESS_KEY": "aws-secret-test",
        },
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    diagnosis = out["diagnosis"]
    # Subagent saw HOME / PATH / etc. but NOT CLAUDE_API_KEY or AWS_SECRET
    assert "CLAUDE_API_KEY" not in diagnosis
    assert "AWS_SECRET_ACCESS_KEY" not in diagnosis


def test_evidence_secrets_redacted_before_prompt(tmp_path):
    """Codex-R4-HIGH-4: secret-keyed evidence fields redacted before
    going into the prompt sent to the subagent."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    # Stub CLI that echoes the prompt back so we can see what was sent
    echo_prompt = tmp_path / "echo.py"
    echo_prompt.write_text(
        "import json, sys\n"
        "prompt = sys.argv[-1]\n"
        "# Look at the EVIDENCE section specifically\n"
        "ev_start = prompt.find('## Evidence')\n"
        "ev_section = prompt[ev_start:ev_start + 800] if ev_start >= 0 else ''\n"
        "print(json.dumps({\n"
        "  'diagnosis': 'evidence section: ' + ev_section,\n"
        "  'proposed_fix': 'review the prompt content above for leaks',\n"
        "  'confidence': 0.5,\n"
        "}))\n",
        encoding="utf-8",
    )
    cli_cmd = shlex.join([str(sys.executable), str(echo_prompt)])
    evidence = {
        "user_id": "real-user-123",
        "auth_token": "Bearer sk-secret-bearer-456",
        "api_key": "real-api-key-789",
        "request_body": {"password": "p@ssw0rd"},
    }
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", json.dumps(evidence),
        "--cli", cli_cmd,
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    diagnosis = out["diagnosis"]
    # user_id was passed verbatim (not a secret-keyed field)
    assert "real-user-123" in diagnosis
    # Secrets redacted
    assert "[REDACTED]" in diagnosis
    assert "sk-secret-bearer-456" not in diagnosis
    assert "real-api-key-789" not in diagnosis
    assert "p@ssw0rd" not in diagnosis


def test_redact_adjacent_name_value_pattern(tmp_path):
    """Codex-R5-HIGH-1: scanner-shape headers list
    `[{name: "Authorization", value: "Bearer ..."}]` must redact value
    even though `value` key isn't itself a secret-name."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    echo_prompt = tmp_path / "echo.py"
    echo_prompt.write_text(
        "import json, sys\n"
        "prompt = sys.argv[-1]\n"
        "ev_start = prompt.find('## Evidence')\n"
        "ev_section = prompt[ev_start:ev_start + 600] if ev_start >= 0 else ''\n"
        "print(json.dumps({\n"
        "  'diagnosis': 'evidence section: ' + ev_section,\n"
        "  'proposed_fix': 'review the prompt content above for leaks',\n"
        "  'confidence': 0.5,\n"
        "}))\n",
        encoding="utf-8",
    )
    cli_cmd = shlex.join([str(sys.executable), str(echo_prompt)])
    evidence = {
        "scanner_request_headers": [
            {"name": "Content-Type", "value": "application/json"},
            {"name": "Authorization", "value": "Bearer secret-token-12345"},
            {"name": "X-Cookie", "value": "sess=stealable"},
        ],
        "user": "alice",
    }
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", json.dumps(evidence),
        "--cli", cli_cmd,
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    diagnosis = out["diagnosis"]
    # Authorization header value must NOT leak
    assert "secret-token-12345" not in diagnosis
    assert "stealable" not in diagnosis
    # Innocent header value (Content-Type) preserved
    assert "application/json" in diagnosis
    # Identity field preserved
    assert "alice" in diagnosis


def test_redact_all_value_siblings_when_name_secret(tmp_path):
    """Codex-R6-HIGH-1 reproducer: multiple value-like siblings should
    ALL be redacted when the name field signals secret semantics."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    echo = tmp_path / "echo.py"
    echo.write_text(
        "import json, sys\n"
        "p = sys.argv[-1]\n"
        "i = p.find('## Evidence')\n"
        "ev = p[i:i+500] if i >= 0 else ''\n"
        "print(json.dumps({\n"
        "  'diagnosis': 'evidence: ' + ev,\n"
        "  'proposed_fix': 'verify all secret siblings redacted above',\n"
        "  'confidence': 0.5,\n"
        "}))\n",
        encoding="utf-8",
    )
    evidence = {
        "header": {
            "name": "Authorization",
            "content": "public-data",
            "value": "Bearer leak-me-secret-token",
            "data": "another-leak-attempt",
        },
    }
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", json.dumps(evidence),
        "--cli", shlex.join([str(sys.executable), str(echo)]),
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    diagnosis = out["diagnosis"]
    # ALL three value-like siblings must be redacted, not just first
    assert "leak-me-secret-token" not in diagnosis
    assert "public-data" not in diagnosis
    assert "another-leak-attempt" not in diagnosis


def test_redact_handles_key_field_alias(tmp_path):
    """Different scanners use 'key' instead of 'name'."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    echo_prompt = tmp_path / "echo2.py"
    echo_prompt.write_text(
        "import json, sys\n"
        "prompt = sys.argv[-1]\n"
        "ev_start = prompt.find('## Evidence')\n"
        "ev_section = prompt[ev_start:ev_start + 500] if ev_start >= 0 else ''\n"
        "print(json.dumps({\n"
        "  'diagnosis': 'sees: ' + ev_section,\n"
        "  'proposed_fix': 'check redaction worked above',\n"
        "  'confidence': 0.5,\n"
        "}))\n",
        encoding="utf-8",
    )
    evidence = {
        "form_fields": [
            {"key": "username", "value": "alice"},
            {"key": "password", "value": "p@ssw0rd"},
        ],
    }
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", json.dumps(evidence),
        "--cli", shlex.join([str(sys.executable), str(echo_prompt)]),
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert "p@ssw0rd" not in out["diagnosis"]
    assert "alice" in out["diagnosis"]  # username key not secret → kept


def test_env_passthrough_opt_in(tmp_path):
    """VG_DIAGNOSTIC_L2_ENV_PASSTHROUGH allowlists project-specific keys."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    dump_env = tmp_path / "dump.py"
    dump_env.write_text(
        "import json, os\n"
        "v = os.environ.get('PROJECT_API_BASE', 'NOT_SET')\n"
        "print(json.dumps({\n"
        "  'diagnosis': 'PROJECT_API_BASE=' + v + ' check this passthrough',\n"
        "  'proposed_fix': 'inspect PROJECT_API_BASE value above for passthrough',\n"
        "  'confidence': 0.5,\n"
        "}))\n",
        encoding="utf-8",
    )
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", shlex.join([str(sys.executable), str(dump_env)]),
        env_extra={
            "PROJECT_API_BASE": "https://sandbox.example.com",
            "VG_DIAGNOSTIC_L2_ENV_PASSTHROUGH": "PROJECT_API_BASE",
        },
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert "https://sandbox.example.com" in out["diagnosis"]


def test_proposal_persisted_with_evidence_round_trip(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    evidence = {"goal": "G-10", "step_idx": 2, "fail_reason": "no source"}
    response = json.dumps({
        "diagnosis": "Step 2 of G-10 missing scanner source field",
        "proposed_fix": "Re-run scanner; ensure verify-evidence-provenance threshold met",
        "confidence": 0.92,
    })
    cli_cmd = _make_stub_cli(tmp_path, response)
    result = _run(
        "--gate-id", "missing-evidence",
        "--block-family", "provenance",
        "--phase-dir", str(phase_dir),
        "--evidence-json", json.dumps(evidence),
        "--cli", cli_cmd,
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    proposal = load_proposal(phase_dir, out["proposal_id"])
    assert proposal.evidence_in == evidence
    assert proposal.confidence == 0.92
    assert proposal.gate_id == "missing-evidence"
