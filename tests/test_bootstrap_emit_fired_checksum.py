"""Tests for vg_bootstrap_compute_sequence_checksum helper.

Stage 3 task 1/3 of meta-memory v1.1 (Approach B1):
NEW helper added to bootstrap-inject.sh, computes sha256(joined sequence cmds)
for procedural rules. Used by Task 3.2 prober to verify the sequence WE BELIEVE
ran matches what ACTUALLY ran in deploy/test log.

Without this checksum, outcome attribution is cargo-cult — rule fires + phase
passes => rule logged PASS even when executor bypassed sequence entirely
(Codex #9 / design Section 13.4).
"""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _bash_exe() -> str:
    """Locate a POSIX bash. On Windows, prefer Git Bash over WSL bash —
    WSL bash runs in Linux namespace and cannot see Windows tmp paths."""
    if os.name == "nt":
        candidates = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ]
        for c in candidates:
            if Path(c).exists():
                return c
        # Fallback: hope PATH bash is Git Bash, not WSL.
        found = shutil.which("bash")
        if found and "system32" in found.lower():
            pytest.skip("only WSL bash found on PATH; install Git Bash to run these tests")
        return found or "bash"
    return "bash"


def _to_bash_path(p: Path) -> str:
    """Convert Windows path to MSYS-style /c/Users/... for bash."""
    rp = str(p)
    if os.name == "nt" and len(rp) > 2 and rp[1] == ":":
        rp = "/" + rp[0].lower() + rp[2:].replace("\\", "/")
    elif os.name == "nt":
        rp = rp.replace("\\", "/")
    return rp


def _make_rule_file(tmp_path: Path, name: str, frontmatter: str, body: str = "# body\n") -> Path:
    p = tmp_path / name
    p.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return p


def _compute_checksum(rule_path: Path) -> dict:
    """Source bootstrap-inject.sh and call vg_bootstrap_compute_sequence_checksum."""
    bash_path = _to_bash_path(rule_path)
    # Use single-quote then escape any literal single-quotes in path.
    safe = bash_path.replace("'", "'\\''")
    script = (
        "set -euo pipefail; "
        "source commands/vg/_shared/lib/bootstrap-inject.sh; "
        f"vg_bootstrap_compute_sequence_checksum '{safe}' --json"
    )
    result = subprocess.run(
        [_bash_exe(), "-c", script],
        capture_output=True, text=True, cwd=os.getcwd(),
    )
    assert result.returncode == 0, (
        f"compute_checksum failed: rc={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout)


def test_procedural_rule_includes_sequence_checksum(tmp_path):
    rule_path = _make_rule_file(
        tmp_path, "rule.md",
        "slug: test-procedural\n"
        "title: \"test\"\n"
        "type: procedural\n"
        "authority: advisory\n"
        "target_step: deploy\n"
        "sequence:\n"
        "  - id: s1\n"
        "    cmd: \"npm run build\"\n"
        "    expected_signals: [\"exit=0\"]\n"
        "  - id: s2\n"
        "    cmd: \"flyctl deploy\"\n"
        "    expected_signals: [\"exit=0\"]\n"
        "success_signals: [\"phase.deploy_completed.outcome == PASS\"]\n"
        "attribution_required: true\n"
    )
    expected = hashlib.sha256(b"npm run build\nflyctl deploy").hexdigest()
    payload = _compute_checksum(rule_path)
    assert payload.get("sequence_checksum") == expected
    assert payload.get("rule_type") == "procedural"
    assert payload.get("slug") == "test-procedural"


def test_declarative_rule_omits_sequence_checksum(tmp_path):
    """Non-procedural rules MUST NOT have sequence_checksum (clean payload)."""
    rule_path = _make_rule_file(
        tmp_path, "rule.md",
        "slug: test-decl\n"
        "title: \"test\"\n"
        "type: declarative\n"
        "target_step: build\n"
    )
    payload = _compute_checksum(rule_path)
    assert "sequence_checksum" not in payload
    assert payload.get("rule_type") == "declarative"


def test_procedural_with_single_step(tmp_path):
    rule_path = _make_rule_file(
        tmp_path, "rule.md",
        "slug: single-step\n"
        "title: \"test\"\n"
        "type: procedural\n"
        "authority: advisory\n"
        "target_step: deploy\n"
        "sequence:\n"
        "  - id: only\n"
        "    cmd: \"echo hi\"\n"
        "    expected_signals: [\"exit=0\"]\n"
        "success_signals: [\"pass\"]\n"
        "attribution_required: true\n"
    )
    expected = hashlib.sha256(b"echo hi").hexdigest()
    payload = _compute_checksum(rule_path)
    assert payload.get("sequence_checksum") == expected


def test_rule_without_id_or_slug_uses_id_field(tmp_path):
    """If rule uses id: instead of slug:, helper accepts both (loader uses id)."""
    rule_path = _make_rule_file(
        tmp_path, "rule.md",
        "id: rule-with-id\n"
        "title: \"test\"\n"
        "type: declarative\n"
        "target_step: build\n"
    )
    payload = _compute_checksum(rule_path)
    # Either slug or id key should map to identifier
    identifier = payload.get("slug") or payload.get("id")
    assert identifier == "rule-with-id"
