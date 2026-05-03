"""Tests for Codex runtime adapter contract coverage."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = (
    REPO_ROOT / "scripts" / "validators" / "verify-codex-runtime-adapter.py"
)


def test_runtime_adapter_validator_passes_on_source_repo():
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--quiet"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, (
        f"runtime adapter validator failed\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


def test_runtime_adapter_validator_detects_missing_contract(tmp_path):
    command_dir = tmp_path / "commands" / "vg"
    command_dir.mkdir(parents=True)
    mirror_dir = tmp_path / "codex-skills" / "vg-build"
    mirror_dir.mkdir(parents=True)

    (command_dir / "build.md").write_text(
        "# Build\n\nAgent(subagent_type=\"general-purpose\", model=\"sonnet\")\n",
        encoding="utf-8",
    )
    (mirror_dir / "SKILL.md").write_text(
        "---\nname: vg-build\n---\n\n# Build mirror without adapter\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 1
    assert "missing_runtime_contract" in result.stdout
    assert "vg-build" in result.stdout


def test_runtime_adapter_validator_detects_missing_support_skill_mirror(tmp_path):
    support_dir = tmp_path / "skills" / "flow-runner"
    support_dir.mkdir(parents=True)
    (support_dir / "SKILL.md").write_text(
        "---\nname: flow-runner\n---\n\nExecute via Playwright MCP.\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 1
    assert "missing_support_skill_mirror" in result.stdout
    assert "flow-runner" in result.stdout


def test_runtime_adapter_validator_accepts_installed_layout(tmp_path):
    command_dir = tmp_path / ".claude" / "commands" / "vg"
    command_dir.mkdir(parents=True)
    support_dir = tmp_path / ".claude" / "skills" / "flow-runner"
    support_dir.mkdir(parents=True)
    mirror_command_dir = tmp_path / ".codex" / "skills" / "vg-build"
    mirror_command_dir.mkdir(parents=True)
    mirror_support_dir = tmp_path / ".codex" / "skills" / "flow-runner"
    mirror_support_dir.mkdir(parents=True)
    for special in ("vg-reflector", "vg-haiku-scanner"):
        (tmp_path / ".codex" / "skills" / special).mkdir(parents=True)
        (tmp_path / ".codex" / "skills" / special / "SKILL.md").write_text(
            _runtime_adapter_text(),
            encoding="utf-8",
        )

    (command_dir / "build.md").write_text(
        "# Build\n\nAgent(subagent_type=\"general-purpose\", model=\"sonnet\")\n",
        encoding="utf-8",
    )
    (support_dir / "SKILL.md").write_text(
        "---\nname: flow-runner\n---\n\nExecute via Playwright MCP.\n",
        encoding="utf-8",
    )
    (mirror_command_dir / "SKILL.md").write_text(_runtime_adapter_text(), encoding="utf-8")
    (mirror_support_dir / "SKILL.md").write_text(_runtime_adapter_text(), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(tmp_path), "--quiet"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout


def test_runtime_adapter_requires_explicit_codex_spawn_precedence(tmp_path):
    command_dir = tmp_path / "commands" / "vg"
    command_dir.mkdir(parents=True)
    mirror_dir = tmp_path / "codex-skills" / "vg-review"
    mirror_dir.mkdir(parents=True)

    (command_dir / "review.md").write_text(
        "# Review\n\nAgent(model=\"haiku\")\n",
        encoding="utf-8",
    )
    (mirror_dir / "SKILL.md").write_text(
        """
<codex_skill_adapter>
<codex_runtime_contract>
Provider mapping
Claude path
Codex path
Never skip source workflow gates
BLOCK instead of silently degrading
commands/vg/_shared/lib/codex-spawn.sh
MCP-heavy work in the main Codex orchestrator
UI/UX, security, and business-flow checks
</codex_runtime_contract>
</codex_skill_adapter>
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 1
    assert "Codex spawn precedence" in result.stdout
    assert "review.haiku_scanner_spawned" in result.stdout


def test_runtime_adapter_requires_codex_hook_parity(tmp_path):
    command_dir = tmp_path / "commands" / "vg"
    command_dir.mkdir(parents=True)
    mirror_dir = tmp_path / "codex-skills" / "vg-build"
    mirror_dir.mkdir(parents=True)

    (command_dir / "build.md").write_text(
        "# Build\n\nAgent(subagent_type=\"general-purpose\", model=\"sonnet\")\n",
        encoding="utf-8",
    )
    (mirror_dir / "SKILL.md").write_text(
        """
<codex_skill_adapter>
<codex_runtime_contract>
Provider mapping
Codex spawn precedence
Claude path
Codex path
Never skip source workflow gates
BLOCK instead of silently degrading
commands/vg/_shared/lib/codex-spawn.sh
--spawn-role
.codex-spawn-manifest.jsonl
VG_CODEX_MODEL_EXECUTOR
VG_CODEX_MODEL_SCANNER
review.haiku_scanner_spawned
MUST run the scanner protocol
MCP-heavy work in the main Codex orchestrator
UI/UX, security, and business-flow checks
</codex_runtime_contract>
</codex_skill_adapter>
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 1
    assert "Codex hook parity" in result.stdout
    assert "vg-orchestrator run-complete" in result.stdout


def _runtime_adapter_text() -> str:
    return """
<codex_skill_adapter>
<codex_runtime_contract>
Provider mapping
Codex hook parity
UserPromptSubmit
vg-entry-hook.py
vg-verify-claim.py
vg-step-tracker.py
codex-hooks/vg-pre-tool-use-apply-patch.py
.vg/events.db
vg-orchestrator run-start
vg-orchestrator mark-step
vg-orchestrator run-complete
Codex spawn precedence
Claude path
Codex path
Never skip source workflow gates
BLOCK instead of silently degrading
commands/vg/_shared/lib/codex-spawn.sh
--spawn-role
.codex-spawn-manifest.jsonl
VG_CODEX_MODEL_EXECUTOR
VG_CODEX_MODEL_SCANNER
review.haiku_scanner_spawned
MUST run the scanner protocol
MCP-heavy work in the main Codex orchestrator
UI/UX, security, and business-flow checks
Model mapping
Pattern A
INLINE ORCHESTRATOR
MCP
codex exec
</codex_runtime_contract>
</codex_skill_adapter>
"""
