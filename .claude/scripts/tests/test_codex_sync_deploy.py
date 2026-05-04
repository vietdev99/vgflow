"""Integration tests for VGFlow Codex sync deployment.

These tests run `sync.sh` against a temporary project and fake HOME. They pin
the behavior that matters for Codex parity:

- all generated Codex skills deploy locally and globally
- Codex agent templates deploy locally and globally
- global Codex config registers the VGFlow agents with usable paths
- installed-project validators pass against the deployed target
"""
from __future__ import annotations

import json
import os
import shutil
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_SH = REPO_ROOT / "sync.sh"
INSTALL_SH = REPO_ROOT / "install.sh"
EQUIV = REPO_ROOT / "scripts" / "verify-codex-mirror-equivalence.py"
MIRROR_SYNC = (
    REPO_ROOT / "scripts" / "validators" / "verify-codex-skill-mirror-sync.py"
)
RUNTIME_ADAPTER = (
    REPO_ROOT / "scripts" / "validators" / "verify-codex-runtime-adapter.py"
)
EXPECTED_SKILLS = {
    "api-contract",
    "flow-runner",
    "vg-project",
    "vg-scope",
    "vg-blueprint",
    "vg-build",
    "vg-review",
    "vg-test",
    "vg-accept",
    "vg-codegen-interactive",
    "vg-design-scanner",
    "vg-reflector",
    "vg-haiku-scanner",
}
EXPECTED_AGENTS = {
    "vgflow-orchestrator.toml",
    "vgflow-executor.toml",
    "vgflow-classifier.toml",
}


def _working_bash() -> str | None:
    candidates: list[str] = []
    if os.environ.get("VG_BASH"):
        candidates.append(os.environ["VG_BASH"])
    if os.name == "nt":
        candidates.extend(
            [
                r"C:\Program Files\Git\usr\bin\bash.exe",
                r"C:\Program Files\Git\bin\bash.exe",
            ]
        )
    candidates.append("bash")

    for candidate in candidates:
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
    assert skill_root.is_dir(), f"missing Codex skills dir: {skill_root}"
    return {p.name for p in skill_root.iterdir() if p.is_dir()}


def _agent_names(root: Path) -> set[str]:
    agent_root = root / ".codex" / "agents"
    assert agent_root.is_dir(), f"missing Codex agents dir: {agent_root}"
    return {p.name for p in agent_root.glob("*.toml")}


def _canonical_codex_skill_count() -> int:
    return sum(
        1
        for path in (REPO_ROOT / "codex-skills").iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def _canonical_claude_skill_count() -> int:
    return sum(
        1
        for path in (REPO_ROOT / "skills").iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def _claude_skill_names(root: Path) -> set[str]:
    skill_root = root / ".claude" / "skills"
    assert skill_root.is_dir(), f"missing Claude skills dir: {skill_root}"
    return {p.name for p in skill_root.iterdir() if p.is_dir()}


def _assert_toml_smoke(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib  # type: ignore[import-not-found]

        tomllib.loads(text)
        return
    except ModuleNotFoundError:
        pass
    except Exception as exc:  # pragma: no cover - exact exception varies by Python
        pytest.fail(f"invalid TOML in {path}: {exc}")

    in_multiline = False
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        triple_count = line.count("'''")
        if in_multiline:
            if triple_count % 2 == 1:
                in_multiline = False
            continue
        if line.startswith("[") and line.endswith("]"):
            continue
        assert " = " in line, f"{path}:{lineno} is not a simple TOML assignment"
        if triple_count % 2 == 1:
            in_multiline = True
    assert not in_multiline, f"{path} has an unterminated multiline TOML string"


def _assert_claude_hooks_installed(root: Path) -> None:
    settings = root / ".claude" / "settings.local.json"
    assert settings.is_file(), f"missing Claude hook settings: {settings}"
    data = json.loads(settings.read_text(encoding="utf-8"))
    commands: list[str] = []
    for matchers in data.get("hooks", {}).values():
        for matcher in matchers:
            for hook in matcher.get("hooks", []):
                commands.append(hook.get("command", ""))
    joined = "\n".join(commands)
    assert "vg-entry-hook.py" in joined
    assert "vg-verify-claim.py" in joined
    assert "vg-edit-warn.py" in joined
    assert "vg-step-tracker.py" in joined
    assert "UserPromptSubmit" in data["hooks"]
    assert "Stop" in data["hooks"]
    post_tool = data["hooks"]["PostToolUse"]
    assert any(matcher.get("matcher") == "Bash" for matcher in post_tool)


def _assert_codex_hooks_installed(root: Path) -> None:
    hooks_path = root / ".codex" / "hooks.json"
    config_path = root / ".codex" / "config.toml"
    assert hooks_path.is_file(), f"missing Codex hooks: {hooks_path}"
    assert config_path.is_file(), f"missing Codex config: {config_path}"
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    commands: list[str] = []
    for matchers in hooks.get("hooks", {}).values():
        for matcher in matchers:
            for hook in matcher.get("hooks", []):
                commands.append(hook.get("command", ""))
    joined = "\n".join(commands)
    assert "vg-entry-hook.py" in joined
    assert "codex-hooks/vg-pre-tool-use-bash.py" in joined
    assert "codex-hooks/vg-pre-tool-use-apply-patch.py" in joined
    assert "codex-hooks/vg-post-tool-use-bash.py" in joined
    assert "codex-hooks/vg-stop.py" in joined
    assert "UserPromptSubmit" in hooks["hooks"]
    assert "PreToolUse" in hooks["hooks"]
    assert "PostToolUse" in hooks["hooks"]
    assert "Stop" in hooks["hooks"]
    assert "codex_hooks = true" in config_path.read_text(encoding="utf-8")


def _assert_no_python_cache_synced(root: Path) -> None:
    scripts = root / ".claude" / "scripts"
    assert not list(scripts.rglob("__pycache__"))
    assert not list(scripts.rglob("*.pyc"))


def _assert_playwright_mcp_configured(home: Path) -> None:
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for i in range(1, 6):
        entry = settings["mcpServers"][f"playwright{i}"]
        assert entry["command"] == "npx"
        args = entry["args"]
        assert "@playwright/mcp@latest" in args
        assert "--user-data-dir" in args
        assert args[args.index("--user-data-dir") + 1].replace("\\", "/").endswith(
            f"/.claude/playwright-profile-{i}"
        )

    config = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    for i in range(1, 6):
        assert f"[mcp_servers.playwright{i}]" in config
        assert "@playwright/mcp@latest" in config
        assert f"/.codex/playwright-profile-{i}" in config.replace("\\", "/")

    lock = home / ".claude" / "playwright-locks" / "playwright-lock.sh"
    lock_text = lock.read_text(encoding="utf-8")
    assert "VG_PLAYWRIGHT_LOCK_DIR" in lock_text
    assert "C:/Users/Lionel Messi" not in lock_text


def test_sync_deploys_full_codex_surface_to_project_and_fake_global(tmp_path):
    bash = _working_bash()
    if bash is None:
        pytest.skip("working bash not found; sync.sh integration requires bash")

    target = tmp_path / "target-project"
    fake_home = tmp_path / "home"
    (fake_home / ".codex").mkdir(parents=True)
    target.mkdir()
    stale_local = target / ".codex" / "skills" / "vg-accept" / "RULES-CARDS.md"
    stale_global = fake_home / ".codex" / "skills" / "vg-accept" / "RULES-CARDS.md"
    stale_local.parent.mkdir(parents=True)
    stale_global.parent.mkdir(parents=True)
    stale_local.write_text("stale", encoding="utf-8")
    stale_global.write_text("stale", encoding="utf-8")

    repo_bash = _bash_path(bash, REPO_ROOT)
    target_bash = _bash_path(bash, target)
    home_bash = _bash_path(bash, fake_home)

    command = (
        f"cd {shlex.quote(repo_bash)} && "
        f"HOME={shlex.quote(home_bash)} "
        f"DEV_ROOT={shlex.quote(target_bash)} "
        "bash sync.sh"
    )
    result = subprocess.run(
        [bash, "-lc", command],
        capture_output=True,
        text=True,
        timeout=180,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, (
        f"sync.sh failed\nSTDOUT:\n{result.stdout[-4000:]}\n"
        f"STDERR:\n{result.stderr[-4000:]}"
    )

    local_skills = _skill_names(target)
    global_skills = _skill_names(fake_home)
    expected_count = _canonical_codex_skill_count()
    assert len(local_skills) == expected_count
    assert len(global_skills) == expected_count
    assert EXPECTED_SKILLS <= local_skills
    assert EXPECTED_SKILLS <= global_skills
    assert not stale_local.exists()
    assert not stale_global.exists()

    assert _agent_names(target) == EXPECTED_AGENTS
    assert _agent_names(fake_home) == EXPECTED_AGENTS
    assert (target / ".codex" / "config.template.toml").is_file()
    config_template = (
        target / ".codex" / "config.template.toml"
    ).read_text(encoding="utf-8")
    assert "VG_CODEX_MODEL_EXECUTOR" in config_template
    assert "codex_hooks = true" in config_template
    assert "Sonnet-class build quality" in config_template
    assert "VG_CODEX_MODEL_SCANNER" in config_template
    assert "cheap/fast read-only model" in config_template
    assert (
        target
        / ".codex"
        / "skills"
        / "vg-codegen-interactive"
        / "filter-test-matrix.mjs"
    ).is_file()
    assert (
        fake_home
        / ".codex"
        / "skills"
        / "vg-codegen-interactive"
        / "filter-test-matrix.mjs"
    ).is_file()
    assert (
        target / ".claude" / "commands" / "vg" / "_shared" / "lib" / "codex-spawn.sh"
    ).is_file()
    assert (target / ".claude" / "scripts" / "codex-spawn-record.py").is_file()
    assert (
        target / ".claude" / "scripts" / "codex-hooks" / "vg-codex-spawn-guard.py"
    ).is_file()
    helper_exec = subprocess.run(
        [
            bash,
            "-lc",
            f"test -x {shlex.quote(target_bash + '/.claude/commands/vg/_shared/lib/codex-spawn.sh')}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        encoding="utf-8",
        errors="replace",
    )
    assert helper_exec.returncode == 0, "codex-spawn.sh should be executable after sync"
    assert (
        target / ".claude" / "VGFLOW-VERSION"
    ).read_text(encoding="utf-8").strip() == (
        REPO_ROOT / "VGFLOW-VERSION"
    ).read_text(encoding="utf-8").strip()
    _assert_claude_hooks_installed(target)
    _assert_codex_hooks_installed(target)
    _assert_no_python_cache_synced(target)

    config_text = (fake_home / ".codex" / "config.toml").read_text(encoding="utf-8")
    _assert_playwright_mcp_configured(fake_home)
    _assert_toml_smoke(fake_home / ".codex" / "config.toml")
    _assert_toml_smoke(target / ".codex" / "config.template.toml")
    _assert_toml_smoke(target / ".codex" / "config.toml")
    for agent_file in EXPECTED_AGENTS:
        agent_path = fake_home / ".codex" / "agents" / agent_file
        _assert_toml_smoke(agent_path)
        agent_text = agent_path.read_text(encoding="utf-8")
        assert "description = " in agent_text
        assert "gpt-5" not in agent_text

    for agent in ("vgflow-orchestrator", "vgflow-executor", "vgflow-classifier"):
        assert f"[agents.{agent}]" in config_text
        assert f"/.codex/agents/{agent}.toml" in config_text.replace("\\", "/")
    if os.name == "nt":
        agent_lines = [
            line for line in config_text.splitlines() if line.startswith("config_file = ")
        ]
        assert agent_lines, config_text
        assert all('config_file = "/' not in line for line in agent_lines)

    codex = shutil.which("codex")
    if codex:
        smoke_env = os.environ.copy()
        smoke_env.update(
            {
                "CODEX_HOME": str(fake_home / ".codex"),
                "HOME": str(fake_home),
                "USERPROFILE": str(fake_home),
            }
        )
        codex_smoke = subprocess.run(
            [codex, "features", "list"],
            capture_output=True,
            text=True,
            timeout=30,
            env=smoke_env,
            encoding="utf-8",
            errors="replace",
        )
        assert codex_smoke.returncode == 0, (
            f"Codex CLI could not parse generated config\nSTDOUT:\n{codex_smoke.stdout}\n"
            f"STDERR:\n{codex_smoke.stderr}"
        )

    validator_env = os.environ.copy()
    validator_env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "REPO_ROOT": str(target),
            "VGFLOW_REPO": str(REPO_ROOT),
            "HOME": str(fake_home),
            "USERPROFILE": str(fake_home),
        }
    )

    equiv = subprocess.run(
        [sys.executable, str(EQUIV), "--json"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        env=validator_env,
        encoding="utf-8",
        errors="replace",
    )
    assert equiv.returncode == 0, equiv.stderr
    equiv_json = json.loads(equiv.stdout)
    assert equiv_json["checked"] == expected_count
    assert equiv_json["drift_count"] == 0

    mirror = subprocess.run(
        [sys.executable, str(MIRROR_SYNC), "--quiet"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        env=validator_env,
        encoding="utf-8",
        errors="replace",
    )
    assert mirror.returncode == 0, (
        f"mirror sync validator failed\nSTDOUT:\n{mirror.stdout}\n"
        f"STDERR:\n{mirror.stderr}"
    )

    runtime = subprocess.run(
        [sys.executable, str(RUNTIME_ADAPTER), "--root", str(target), "--quiet"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        env=validator_env,
        encoding="utf-8",
        errors="replace",
    )
    assert runtime.returncode == 0, (
        f"runtime adapter validator failed\nSTDOUT:\n{runtime.stdout}\n"
        f"STDERR:\n{runtime.stderr}"
    )


def test_install_deploys_full_claude_and_codex_surfaces(tmp_path):
    bash = _working_bash()
    if bash is None:
        pytest.skip("working bash not found; install.sh integration requires bash")

    target = tmp_path / "installed-project"
    fake_home = tmp_path / "home"
    (fake_home / ".codex").mkdir(parents=True)
    (fake_home / ".claude").mkdir(parents=True)
    target.mkdir()
    stale_local = target / ".codex" / "skills" / "vg-accept" / "RULES-CARDS.md"
    stale_global = fake_home / ".codex" / "skills" / "vg-accept" / "RULES-CARDS.md"
    stale_local.parent.mkdir(parents=True)
    stale_global.parent.mkdir(parents=True)
    stale_local.write_text("stale", encoding="utf-8")
    stale_global.write_text("stale", encoding="utf-8")

    repo_bash = _bash_path(bash, REPO_ROOT)
    target_bash = _bash_path(bash, target)
    home_bash = _bash_path(bash, fake_home)

    command = (
        f"cd {shlex.quote(repo_bash)} && "
        f"HOME={shlex.quote(home_bash)} "
        "VGFLOW_SKIP_GRAPHIFY_INSTALL=true "
        f"bash {shlex.quote(_bash_path(bash, INSTALL_SH))} "
        f"{shlex.quote(target_bash)}"
    )
    result = subprocess.run(
        [bash, "-lc", command],
        capture_output=True,
        text=True,
        timeout=180,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, (
        f"install.sh failed\nSTDOUT:\n{result.stdout[-4000:]}\n"
        f"STDERR:\n{result.stderr[-4000:]}"
    )

    expected_codex_count = _canonical_codex_skill_count()
    expected_claude_count = _canonical_claude_skill_count()

    assert len(_claude_skill_names(target)) == expected_claude_count
    assert len(_skill_names(target)) == expected_codex_count
    assert len(_skill_names(fake_home)) == expected_codex_count
    assert EXPECTED_SKILLS <= _skill_names(target)
    assert not stale_local.exists()
    assert not stale_global.exists()
    assert _agent_names(target) == EXPECTED_AGENTS
    assert _agent_names(fake_home) == EXPECTED_AGENTS
    assert (
        target / ".claude" / "commands" / "vg" / "_shared" / "lib" / "codex-spawn.sh"
    ).is_file()
    assert (target / ".claude" / "scripts" / "codex-spawn-record.py").is_file()
    assert (target / ".claude" / "scripts" / "vg_update.py").is_file()
    assert (target / ".claude" / "schemas").is_dir()
    _assert_claude_hooks_installed(target)
    _assert_no_python_cache_synced(target)
    config_template = (
        target / ".codex" / "config.template.toml"
    ).read_text(encoding="utf-8")
    assert "VG_CODEX_MODEL_EXECUTOR" in config_template
    assert "codex_hooks = true" in config_template
    assert "VG_CODEX_MODEL_SCANNER" in config_template
    _assert_playwright_mcp_configured(fake_home)
    _assert_codex_hooks_installed(target)
    _assert_toml_smoke(target / ".codex" / "config.toml")
    assert (
        target / ".claude" / "scripts" / "codex-hooks" / "vg-pre-tool-use-apply-patch.py"
    ).is_file()
    assert (
        target / ".claude" / "scripts" / "codex-hooks" / "vg-codex-spawn-guard.py"
    ).is_file()

    validator_env = os.environ.copy()
    validator_env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "REPO_ROOT": str(target),
            "VGFLOW_REPO": str(REPO_ROOT),
            "HOME": str(fake_home),
            "USERPROFILE": str(fake_home),
        }
    )

    equiv = subprocess.run(
        [sys.executable, str(EQUIV), "--json"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        env=validator_env,
        encoding="utf-8",
        errors="replace",
    )
    assert equiv.returncode == 0, equiv.stderr
    equiv_json = json.loads(equiv.stdout)
    assert equiv_json["checked"] == expected_codex_count
    assert equiv_json["drift_count"] == 0

    mirror = subprocess.run(
        [sys.executable, str(MIRROR_SYNC), "--quiet"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        env=validator_env,
        encoding="utf-8",
        errors="replace",
    )
    assert mirror.returncode == 0, (
        f"installed mirror sync validator failed\nSTDOUT:\n{mirror.stdout}\n"
        f"STDERR:\n{mirror.stderr}"
    )

    runtime = subprocess.run(
        [sys.executable, str(RUNTIME_ADAPTER), "--root", str(target), "--quiet"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        env=validator_env,
        encoding="utf-8",
        errors="replace",
    )
    assert runtime.returncode == 0, (
        f"installed runtime adapter validator failed\nSTDOUT:\n{runtime.stdout}\n"
        f"STDERR:\n{runtime.stderr}"
    )
