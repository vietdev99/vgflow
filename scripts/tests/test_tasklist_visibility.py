"""
Task-list visibility anti-forge tests (2026-04-24).

User requirement: "khởi tạo 1 flow nào đều phải show được Task để AI bám vào đó
mà làm". Every pipeline command entry step MUST:
  1. Call emit-tasklist.py helper (authoritative step list from filter-steps.py)
  2. Emit {command}.tasklist_shown event for contract verification
  3. Print step list to user so AI can't start silently

This test ensures:
  - emit-tasklist.py works end-to-end (filter → print → emit)
  - Every command has the helper invocation in its entry step
  - Every command contract lists {cmd}.tasklist_shown in must_emit_telemetry
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "sync.sh").exists() and (candidate / "commands" / "vg").exists():
            return candidate
        if (
            (candidate / ".claude" / "commands" / "vg").exists()
            and (candidate / ".claude" / "scripts" / "emit-tasklist.py").exists()
        ):
            return candidate
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _repo_root()
HELPER    = REPO_ROOT / ".claude" / "scripts" / "emit-tasklist.py"
CMDS_DIR  = REPO_ROOT / ".claude" / "commands" / "vg"

COMMANDS_WITH_CONTRACT = [
    "accept", "blueprint", "build", "review", "scope", "specs", "test",
]


# ─── Helper script tests ──────────────────────────────────────────────

class TestEmitTasklistHelper:
    def test_helper_exists(self):
        assert HELPER.exists(), f"Missing {HELPER}"

    def test_helper_no_emit_mode_prints_steps(self):
        """--no-emit prints step list without touching orchestrator."""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(
            [sys.executable, str(HELPER),
             "--command", "vg:blueprint",
             "--profile", "web-fullstack",
             "--phase", "7.14",
             "--no-emit"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT), env=env, encoding="utf-8", errors="replace",
        )
        assert r.returncode == 0, r.stderr
        # Must show step list header + at least one numbered step
        assert "vg:blueprint" in r.stdout
        assert "Phase 7.14" in r.stdout
        assert "Checklists:" in r.stdout
        assert "blueprint_plan" in r.stdout
        assert "steps to execute" in r.stdout
        assert re.search(r"^\s+\d+\.\s+\w", r.stdout, re.MULTILINE)

    def test_helper_lists_authoritative_steps(self):
        """Steps must come from filter-steps.py, not AI improv."""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(
            [sys.executable, str(HELPER),
             "--command", "vg:blueprint",
             "--profile", "web-fullstack",
             "--phase", "7.14",
             "--no-emit"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT), env=env, encoding="utf-8", errors="replace",
        )
        # Known blueprint steps that filter-steps.py should emit (step names
        # come from <step name=...> in skill file, not our assertion guesses)
        assert "1_parse_args" in r.stdout
        assert "2a_plan" in r.stdout
        assert "2b_contracts" in r.stdout

    def test_helper_groups_build_steps_into_checklists(self):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(
            [sys.executable, str(HELPER),
             "--command", "vg:build",
             "--profile", "web-fullstack",
             "--phase", "7.14",
             "--no-emit"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT), env=env, encoding="utf-8", errors="replace",
        )
        assert r.returncode == 0, r.stderr
        assert "build_preflight" in r.stdout
        assert "build_execute" in r.stdout
        assert "8_execute_waves" in r.stdout

    def test_helper_fails_gracefully_on_unknown_command(self):
        r = subprocess.run(
            [sys.executable, str(HELPER),
             "--command", "vg:nonexistent",
             "--profile", "web-fullstack",
             "--phase", "7.14",
             "--no-emit"],
            capture_output=True, text=True, timeout=5,
            cwd=str(REPO_ROOT),
        )
        assert r.returncode == 1  # filter-steps returns empty → exit 1

    def test_helper_requires_all_three_args(self):
        r = subprocess.run(
            [sys.executable, str(HELPER), "--command", "vg:blueprint"],
            capture_output=True, text=True, timeout=5,
            cwd=str(REPO_ROOT),
        )
        assert r.returncode != 0


# ─── Command wiring tests ─────────────────────────────────────────────

@pytest.mark.parametrize("cmd", COMMANDS_WITH_CONTRACT)
class TestCommandWiring:
    def test_command_invokes_emit_tasklist(self, cmd):
        """Each command must call emit-tasklist.py in an entry bash block."""
        path = CMDS_DIR / f"{cmd}.md"
        text = path.read_text(encoding="utf-8")
        assert "emit-tasklist.py" in text, (
            f"{cmd}.md missing emit-tasklist.py invocation — user won't see "
            f"step plan at flow start"
        )

    def test_command_emits_tasklist_shown_event(self, cmd):
        """Each command's runtime_contract must_emit_telemetry lists tasklist_shown."""
        path = CMDS_DIR / f"{cmd}.md"
        text = path.read_text(encoding="utf-8")
        # Match ${cmd}.tasklist_shown in frontmatter
        short = cmd  # accept → accept.tasklist_shown
        pattern = rf'event_type:\s*["\']?{short}\.tasklist_shown'
        assert re.search(pattern, text), (
            f"{cmd}.md runtime_contract missing {short}.tasklist_shown event "
            f"in must_emit_telemetry"
        )
        if cmd in {"blueprint", "build", "review", "test", "accept"}:
            native_pattern = rf'event_type:\s*["\']?{short}\.native_tasklist_projected'
            assert re.search(native_pattern, text), (
                f"{cmd}.md runtime_contract missing {short}.native_tasklist_projected"
            )

    def test_emit_tasklist_invocation_passes_command_arg(self, cmd):
        """Invocation must pass --command vg:{cmd} matching the skill name.

        Searches globally (not just first emit-tasklist.py mention) because
        frontmatter comments may reference the helper before the actual
        bash invocation appears.
        """
        path = CMDS_DIR / f"{cmd}.md"
        text = path.read_text(encoding="utf-8")
        assert f'--command "vg:{cmd}"' in text or \
               f"--command 'vg:{cmd}'" in text or \
               f"--command vg:{cmd}" in text, (
            f"{cmd}.md emit-tasklist invocation must pass --command vg:{cmd}"
        )


# ─── Contract end-to-end consistency ──────────────────────────────────

def test_all_commands_have_runtime_contract():
    """Every pipeline command file must declare runtime_contract frontmatter."""
    for cmd in COMMANDS_WITH_CONTRACT:
        path = CMDS_DIR / f"{cmd}.md"
        assert path.exists(), f"Missing {cmd}.md"
        text = path.read_text(encoding="utf-8")
        # Frontmatter between first two `---`
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        assert m, f"{cmd}.md missing YAML frontmatter"
        frontmatter = m.group(1)
        assert "runtime_contract:" in frontmatter, (
            f"{cmd}.md frontmatter missing runtime_contract block"
        )


def test_tasklist_shown_event_not_in_reserved_prefixes():
    """tasklist_shown event must be emittable via CLI (not reserved).

    Otherwise emit-tasklist.py itself would fail to register the event.
    """
    main_file = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py"
    text = main_file.read_text(encoding="utf-8")
    # Find RESERVED_EVENT_PREFIXES tuple
    m = re.search(r"RESERVED_EVENT_PREFIXES\s*=\s*\(([^)]+)\)", text, re.DOTALL)
    assert m, "RESERVED_EVENT_PREFIXES not found"
    reserved = m.group(1)
    # Must NOT include tasklist prefix
    assert '"tasklist"' not in reserved
    assert "tasklist_shown" not in reserved


def _emit_tasklist(command: str, profile: str = "web-fullstack", mode: str | None = None) -> str:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [
        sys.executable, str(HELPER),
        "--command", command,
        "--profile", profile,
        "--phase", "7.14",
        "--no-emit",
    ]
    if mode:
        cmd.extend(["--mode", mode])
    r = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=10,
        cwd=str(REPO_ROOT), env=env, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_helper_groups_test_steps_into_checklists():
    out = _emit_tasklist("vg:test", "web-fullstack")
    assert "test_preflight" in out
    assert "test_deploy" in out
    assert "test_runtime" in out
    assert "test_codegen" in out
    assert "test_regression_security" in out
    assert "5b_runtime_contract_verify" in out
    assert "5h_security_dynamic" in out


def test_helper_groups_accept_steps_into_checklists():
    out = _emit_tasklist("vg:accept", "web-fullstack")
    assert "accept_preflight" in out
    assert "accept_gates" in out
    assert "accept_uat" in out
    assert "accept_audit" in out
    assert "create_task_tracker" in out
    assert "6_write_uat_md" in out


def test_test_tasklist_respects_profile_switches():
    web = _emit_tasklist("vg:test", "web-fullstack")
    mobile = _emit_tasklist("vg:test", "mobile-rn")
    cli = _emit_tasklist("vg:test", "cli-tool")

    assert "5a_deploy" in web
    assert "5a_mobile_deploy" not in web
    assert "5c_mobile_flow" in mobile
    assert "5d_mobile_codegen" in mobile
    assert "5c_smoke" not in mobile
    assert "5b_runtime_contract_verify" not in cli
    assert "5d_deep_probe" in cli
