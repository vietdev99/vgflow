from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if candidate.name == ".claude" and (candidate / "commands" / "vg").exists():
            return candidate.parent
        if (candidate / "sync.sh").exists() and (candidate / "commands" / "vg").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _repo_root()
CMDS_DIR = REPO_ROOT / ".claude" / "commands" / "vg"
FILTER_STEPS = REPO_ROOT / ".claude" / "scripts" / "filter-steps.py"


def _command_text(cmd: str) -> str:
    return (CMDS_DIR / f"{cmd}.md").read_text(encoding="utf-8")


def _frontmatter(text: str) -> str:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "missing YAML frontmatter"
    return match.group(1)


def _filtered_steps(cmd: str, profile: str) -> list[str]:
    r = subprocess.run(
        [
            sys.executable,
            str(FILTER_STEPS),
            "--command",
            str(CMDS_DIR / f"{cmd}.md"),
            "--profile",
            profile,
            "--output-ids",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=REPO_ROOT,
    )
    assert r.returncode == 0, r.stderr
    return [s for s in r.stdout.strip().split(",") if s]


def _declared_markers(cmd: str) -> set[str]:
    fm = _frontmatter(_command_text(cmd))
    return set(re.findall(r'(?:-\s*"|- name:\s*")([A-Za-z0-9_]+)"', fm))


def test_test_and_accept_project_native_tasklist():
    for cmd in ("test", "accept"):
        text = _command_text(cmd)
        assert "<TASKLIST_POLICY>" in text
        assert "tasklist-contract.json" in text
        assert "tasklist-projected" in text
        assert f"{cmd}.native_tasklist_projected" in text
        assert "TodoWrite" in _frontmatter(text)
        assert "TaskCreate" in _frontmatter(text)
        assert "TaskUpdate" in _frontmatter(text)


def test_test_policy_no_longer_bans_native_tasks():
    text = _command_text("test")
    assert "DO NOT USE TodoWrite / TaskCreate / TaskUpdate" not in text
    assert "NO TaskCreate" not in text


def test_shared_lifecycle_allows_contract_backed_native_tasklist():
    text = (CMDS_DIR / "_shared" / "session-lifecycle.md").read_text(encoding="utf-8")
    assert "Native tasklist projection is REQUIRED" in text
    assert "tasklist-contract.json" in text
    assert "Do not create ad-hoc todos/tasks" in text
    assert "DO NOT USE TodoWrite / TaskCreate / TaskUpdate" not in text


def test_filtered_test_steps_are_declared_as_contract_markers():
    declared = _declared_markers("test")
    for profile in ("web-fullstack", "web-frontend-only", "web-backend-only", "mobile-rn", "cli-tool"):
        for step in _filtered_steps("test", profile):
            assert step in declared, f"test {profile} step not in runtime_contract: {step}"


def test_filtered_accept_steps_are_declared_as_contract_markers():
    declared = _declared_markers("accept")
    for profile in ("web-fullstack", "web-frontend-only", "web-backend-only", "mobile-rn", "cli-tool"):
        for step in _filtered_steps("accept", profile):
            assert step in declared, f"accept {profile} step not in runtime_contract: {step}"


def test_accept_does_not_mark_nonexistent_accept_step():
    text = _command_text("accept")
    assert "mark-step accept accept" not in text
    assert ".step-markers/accept.done" not in text
    assert "6_write_uat_md.done" in text


def test_profile_marker_gate_present_in_test_and_accept():
    for cmd, event in (("test", "test.marker_gate_blocked"), ("accept", "accept.marker_gate_blocked")):
        text = _command_text(cmd)
        assert "filter-steps.py" in text
        assert event in text
        assert ".step-markers/${STEP_ID}.done" in text


def test_filtered_steps_have_explicit_marker_write_instruction():
    for cmd, namespace in (("test", "test"), ("accept", "accept")):
        text = _command_text(cmd)
        profiles = ("web-fullstack", "web-frontend-only", "web-backend-only", "mobile-rn", "cli-tool")
        steps = {step for profile in profiles for step in _filtered_steps(cmd, profile)}
        for step in sorted(steps):
            marker = f".step-markers/{step}.done"
            orchestrator = f"mark-step {namespace} {step}"
            assert marker in text or orchestrator in text, (
                f"{cmd} step lacks explicit marker write instruction: {step}"
            )
