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

    def test_helper_no_emit_mode_prints_summary(self):
        """--no-emit prints compact summary line.

        Bug F (2026-05-04 token-audit Priority 3): emit-tasklist.py stdout
        was reduced from 95 lines to 1 line. Items live in tasklist-
        contract.json on disk; AI projects via TodoWrite (not from stdout).
        Test asserts the new compact summary contract: command + phase +
        profile + step/group/item counts.
        """
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
        # Summary line must contain command + phase + profile + counts
        assert "vg:blueprint" in r.stdout
        assert "Phase 7.14" in r.stdout
        assert "web-fullstack" in r.stdout
        # Must report step count + group count + projection items count
        assert re.search(r"\d+\s*step", r.stdout)
        assert re.search(r"\d+\s*group", r.stdout)
        assert re.search(r"\d+\s*projection", r.stdout)

    def test_helper_writes_authoritative_contract(self):
        """Steps must come from filter-steps.py, not AI improv. After Bug F
        compact-stdout fix, step names live in tasklist-contract.json
        (not stdout). Test verifies the contract file format independently."""
        # Note: contract file is written when --no-emit is omitted AND there's
        # an active run; in standalone tests, _write_contract returns None.
        # Instead validate filter-steps.py directly emits the expected step
        # names (this is the same source emit-tasklist.py uses).
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        filter_steps = REPO_ROOT / ".claude" / "scripts" / "filter-steps.py"
        cmd_file = REPO_ROOT / ".claude" / "commands" / "vg" / "blueprint.md"
        r = subprocess.run(
            [sys.executable, str(filter_steps),
             "--command", str(cmd_file),
             "--profile", "web-fullstack",
             "--output-ids"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT), env=env, encoding="utf-8", errors="replace",
        )
        assert r.returncode == 0, r.stderr
        # Known blueprint steps from <step name=...> in skill file
        assert "1_parse_args" in r.stdout
        assert "2a_plan" in r.stdout
        assert "2b_contracts" in r.stdout

    def test_helper_groups_build_steps_into_checklists(self):
        """Build command must produce checklists matching CHECKLIST_DEFS.
        After Bug F compact-stdout fix, group names live in tasklist-
        contract.json (not stdout). Test reads CHECKLIST_DEFS directly."""
        # Import emit-tasklist module to verify CHECKLIST_DEFS content
        import importlib.util
        helper_path = REPO_ROOT / "scripts" / "emit-tasklist.py"
        spec = importlib.util.spec_from_file_location("emit_tasklist", helper_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        defs = mod.CHECKLIST_DEFS["vg:build"]
        group_ids = {g[0] for g in defs}
        assert "build_preflight" in group_ids
        assert "build_execute" in group_ids
        # 8_execute_waves must be a member of build_execute checklist
        execute_steps = [g[2] for g in defs if g[0] == "build_execute"][0]
        assert "8_execute_waves" in execute_steps

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
            frontmatter = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL).group(1)
            assert "TodoWrite" in frontmatter, (
                f"{cmd}.md must expose Claude Code's native TodoWrite tasklist tool"
            )
            assert "tasklist-contract.json" in text, (
                f"{cmd}.md must bind native tasklist to tasklist-contract.json"
            )
            assert "replace-on-start" in text, (
                f"{cmd}.md must replace stale native tasklists at workflow start"
            )
            assert "close-on-complete" in text, (
                f"{cmd}.md must close/clear native tasklists at workflow completion"
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


def test_lifecycle_contract_in_slim_entry_or_shared_ref():
    """Bug F (2026-05-04 token-audit Priority 3): emit-tasklist.py stdout
    was reduced from 95 lines to 1-line summary. Lifecycle prose moved to
    canonical _shared/lib/tasklist-projection-instruction.md (referenced
    from every slim entry's Tasklist policy). Test asserts the lifecycle
    contract still exists somewhere AI/operator can read it — either in
    slim entry directly OR in the shared instruction ref."""
    blueprint_md = (CMDS_DIR / "blueprint.md").read_text(encoding="utf-8")
    instruction_ref = REPO_ROOT / "commands" / "vg" / "_shared" / "lib" / "tasklist-projection-instruction.md"

    text_to_search = blueprint_md
    if instruction_ref.exists():
        text_to_search += "\n" + instruction_ref.read_text(encoding="utf-8")

    assert "replace-on-start" in text_to_search and "close-on-complete" in text_to_search, (
        "Lifecycle contract (replace-on-start + close-on-complete) must appear "
        "in either slim entry blueprint.md or _shared/lib/tasklist-projection-"
        "instruction.md per Anthropic skill standard (progressive disclosure)."
    )


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
