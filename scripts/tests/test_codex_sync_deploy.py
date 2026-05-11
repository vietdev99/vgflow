"""Global-only install/sync tests for Claude + Codex surfaces."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "VERSION").exists() and (parent / ".git").exists():
            return parent
    return here.parents[2]


REPO_ROOT = _find_repo_root()
SYNC_SH = REPO_ROOT / "sync.sh"
INSTALL_SH = REPO_ROOT / "install.sh"
EXPECTED_SKILLS = {
    "api-contract",
    "flow-runner",
    "vg-project",
    "vg-scope",
    "vg-blueprint",
    "vg-build",
    "vg-test-spec",
    "vg-review",
    "vg-test",
    "vg-accept",
}
EXPECTED_AGENTS = {
    "vgflow-orchestrator.toml",
    "vgflow-executor.toml",
    "vgflow-classifier.toml",
}


def _working_bash() -> str | None:
    for candidate in [os.environ.get("VG_BASH"), "bash"]:
        if not candidate:
            continue
        try:
            result = subprocess.run(
                [candidate, "-lc", "printf OK"],
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
                errors="replace",
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and result.stdout == "OK":
            return candidate
    return None


def _bash_path(bash: str, path: Path) -> str:
    result = subprocess.run(
        [bash, "-lc", f"cygpath -u {shlex.quote(str(path))}"],
        capture_output=True,
        text=True,
        timeout=10,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return path.as_posix()


def _skill_names(root: Path) -> set[str]:
    skill_root = root / ".codex" / "skills"
    if not skill_root.is_dir():
        return set()
    return {p.name for p in skill_root.iterdir() if p.is_dir()}


def _agent_names(root: Path) -> set[str]:
    agent_root = root / ".codex" / "agents"
    if not agent_root.is_dir():
        return set()
    return {p.name for p in agent_root.glob("*.toml")}


def _canonical_codex_skill_count() -> int:
    return sum(
        1
        for path in (REPO_ROOT / "codex-skills").iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def _write_project_local_vg_files(target: Path) -> None:
    (target / ".codex" / "skills" / "vg-accept").mkdir(parents=True)
    (target / ".codex" / "skills" / "vg-accept" / "SKILL.md").write_text("stale", encoding="utf-8")
    (target / ".claude" / "commands" / "vg").mkdir(parents=True)
    (target / ".claude" / "commands" / "vg" / "review.md").write_text("stale", encoding="utf-8")
    (target / ".claude" / "settings.local.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 .claude/scripts/hooks/vg-run-bash-hook.py .claude/scripts/hooks/vg-stop.sh",
                                },
                                {"type": "command", "command": "echo user-hook"},
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )


def _write_fake_global_surface(fake_home: Path) -> None:
    (fake_home / ".vgflow").mkdir(parents=True)
    (fake_home / ".codex" / "skills").mkdir(parents=True)
    (fake_home / ".codex" / "hooks.json").write_text("{}", encoding="utf-8")
    (fake_home / ".claude").mkdir(parents=True, exist_ok=True)
    (fake_home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")


def _assert_global_install(fake_home: Path, target: Path) -> None:
    assert len(_skill_names(fake_home)) == _canonical_codex_skill_count()
    assert EXPECTED_SKILLS <= _skill_names(fake_home)
    assert _agent_names(fake_home) == EXPECTED_AGENTS
    assert not (target / ".codex" / "skills" / "vg-accept").exists()
    assert not (target / ".claude" / "commands" / "vg").exists()
    assert (target / ".vg" / ".install-target").read_text(encoding="utf-8").strip() == "global"

    settings = fake_home / ".claude" / "settings.json"
    assert settings.is_file()
    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = "\n".join(
        hook.get("command", "")
        for matchers in data.get("hooks", {}).values()
        for matcher in matchers
        for hook in matcher.get("hooks", [])
    )
    assert "vg-stop.sh" in commands
    assert "vg-user-prompt-submit.sh" in commands


def test_sync_global_only_prunes_project_and_refreshes_global_codex(tmp_path: Path) -> None:
    bash = _working_bash()
    if bash is None:
        pytest.skip("working bash not found")

    target = tmp_path / "target-project"
    fake_home = tmp_path / "home"
    target.mkdir()
    (target / ".git").mkdir()
    (fake_home / ".codex").mkdir(parents=True)
    (fake_home / ".claude").mkdir(parents=True)
    _write_project_local_vg_files(target)

    result = subprocess.run(
        [
            bash,
            "-lc",
            (
                f"cd {shlex.quote(_bash_path(bash, REPO_ROOT))} && "
                f"HOME={shlex.quote(_bash_path(bash, fake_home))} "
                f"DEV_ROOT={shlex.quote(_bash_path(bash, target))} "
                "bash sync.sh"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    _assert_global_install(fake_home, target)


def test_install_sh_global_only_prunes_project_and_refreshes_global_codex(tmp_path: Path) -> None:
    bash = _working_bash()
    if bash is None:
        pytest.skip("working bash not found")

    target = tmp_path / "installed-project"
    fake_home = tmp_path / "home"
    target.mkdir()
    (target / ".git").mkdir()
    (fake_home / ".codex").mkdir(parents=True)
    (fake_home / ".claude").mkdir(parents=True)
    _write_project_local_vg_files(target)

    result = subprocess.run(
        [
            bash,
            "-lc",
            (
                f"cd {shlex.quote(_bash_path(bash, REPO_ROOT))} && "
                f"HOME={shlex.quote(_bash_path(bash, fake_home))} "
                f"bash {shlex.quote(_bash_path(bash, INSTALL_SH))} "
                f"{shlex.quote(_bash_path(bash, target))}"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    _assert_global_install(fake_home, target)


def test_sync_check_does_not_deploy_project_local_surfaces(tmp_path: Path) -> None:
    bash = _working_bash()
    if bash is None:
        pytest.skip("working bash not found")

    target = tmp_path / "target-project"
    fake_home = tmp_path / "home"
    target.mkdir()
    fake_home.mkdir()
    _write_fake_global_surface(fake_home)

    result = subprocess.run(
        [
            bash,
            "-lc",
            (
                f"cd {shlex.quote(_bash_path(bash, REPO_ROOT))} && "
                f"HOME={shlex.quote(_bash_path(bash, fake_home))} "
                f"DEV_ROOT={shlex.quote(_bash_path(bash, target))} "
                "bash sync.sh --check"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (target / ".codex").exists()
    assert not (target / ".claude").exists()


def test_sync_check_reports_missing_global_surface_without_writes(tmp_path: Path) -> None:
    bash = _working_bash()
    if bash is None:
        pytest.skip("working bash not found")

    target = tmp_path / "target-project"
    fake_home = tmp_path / "home"
    target.mkdir()
    fake_home.mkdir()

    result = subprocess.run(
        [
            bash,
            "-lc",
            (
                f"cd {shlex.quote(_bash_path(bash, REPO_ROOT))} && "
                f"HOME={shlex.quote(_bash_path(bash, fake_home))} "
                f"DEV_ROOT={shlex.quote(_bash_path(bash, target))} "
                "bash sync.sh --check"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 1
    assert "MISSING global source" in result.stdout
    assert not (target / ".codex").exists()
    assert not (target / ".claude").exists()


def test_sync_check_reports_stale_project_local_surfaces(tmp_path: Path) -> None:
    bash = _working_bash()
    if bash is None:
        pytest.skip("working bash not found")

    target = tmp_path / "target-project"
    fake_home = tmp_path / "home"
    target.mkdir()
    fake_home.mkdir()
    _write_fake_global_surface(fake_home)
    _write_project_local_vg_files(target)

    result = subprocess.run(
        [
            bash,
            "-lc",
            (
                f"cd {shlex.quote(_bash_path(bash, REPO_ROOT))} && "
                f"HOME={shlex.quote(_bash_path(bash, fake_home))} "
                f"DEV_ROOT={shlex.quote(_bash_path(bash, target))} "
                "bash sync.sh --check"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 1
    assert "STALE project-local VG surfaces" in result.stdout
    assert ".claude/commands/vg" in result.stdout
    assert ".codex/skills/vg-accept" in result.stdout
