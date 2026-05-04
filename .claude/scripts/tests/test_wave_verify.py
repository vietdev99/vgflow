"""
Phase A (v2.5 hardening, 2026-04-23) — wave-verify-isolated.py tests.

Post-wave independent verification. Spawns fresh subprocess re-running
typecheck/tests/contract-runtime, compares with executor claims in
commit messages. Divergence → BLOCK + rollback wave.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "wave-verify-isolated.py"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=15,
    )


def _setup_repo(tmp_path: Path, commits: list[tuple[str, str, str]]) -> Path:
    """Create a fake repo with wave-start tag + commits.

    commits: list of (filename, content, commit_msg). Last commit = HEAD.
    Returns the wave tag name; tag placed at first commit.
    """
    (tmp_path / ".vg" / "phases" / "09-test").mkdir(parents=True)

    # Copy narration strings
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "a@b.c")
    _git(tmp_path, "config", "user.name", "t")

    # Seed commit
    (tmp_path / "README.md").write_text("seed", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "seed")

    # Wave-start tag placed here
    tag = "vg-build-9-wave-1-start"
    _git(tmp_path, "tag", tag)

    # Add wave commits
    for fname, content, msg in commits:
        f = tmp_path / fname
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", msg)

    return tmp_path, tag


def _write_config(repo: Path, cfg: dict) -> None:
    cfg_file = repo / ".claude" / "vg.config.md"
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", "independent_verify:"]
    for k, v in cfg.items():
        if isinstance(v, bool):
            lines.append(f"  {k}: {'true' if v else 'false'}")
        elif isinstance(v, int):
            lines.append(f"  {k}: {v}")
        else:
            lines.append(f"  {k}: \"{v}\"")
    lines.append("---")
    cfg_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(repo: Path, tag: str, mode: str | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    args = [sys.executable, str(VALIDATOR), "--phase", "9", "--wave-tag", tag]
    if mode:
        args += ["--mode", mode]
    return subprocess.run(args, cwd=repo, capture_output=True, text=True,
                          timeout=60, env=env)


def _parse(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line.strip())
    raise AssertionError(f"no JSON:\n{stdout}")


# ─────────────────────────────────────────────────────────────────────────

def test_disabled_config_skips(tmp_path):
    repo, tag = _setup_repo(tmp_path, [("a.ts", "x", "feat: a\n\ntypecheck: PASS")])
    _write_config(repo, {"enabled": False})
    r = _run(repo, tag)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_wave_tag_unresolvable_warns(tmp_path):
    repo, tag = _setup_repo(tmp_path, [("a.ts", "x", "feat: a")])
    _write_config(repo, {
        "enabled": True,
        "typecheck_cmd": "echo skip",
        "test_cmd_affected": "echo skip",
        "contract_runtime": False,
    })
    r = _run(repo, "nonexistent-tag")
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert any(e["type"] == "wave_tag_unresolvable" for e in out["evidence"])


def test_zero_commits_since_tag_skips(tmp_path):
    repo, tag = _setup_repo(tmp_path, [])  # no commits after tag
    _write_config(repo, {"enabled": True, "typecheck_cmd": "echo x"})
    r = _run(repo, tag)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_matching_claim_and_result_passes(tmp_path):
    """Executor claimed typecheck PASS, subprocess returns rc=0 → consistent."""
    repo, tag = _setup_repo(tmp_path, [
        ("a.ts", "export const x = 1;", "feat(9-01): add x\n\ntypecheck: PASS"),
    ])
    _write_config(repo, {
        "enabled": True,
        "typecheck_cmd": "exit 0",       # subprocess PASS
        "test_cmd_affected": "exit 0",
        "contract_runtime": False,
        "timeout_seconds": 10,
    })
    r = _run(repo, tag)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_divergence_strict_blocks(tmp_path):
    """Executor claimed PASS but subprocess fails → BLOCK in strict mode."""
    repo, tag = _setup_repo(tmp_path, [
        ("a.ts", "broken", "feat(9-01): add x\n\ntypecheck: PASS\ntests: 5/5"),
    ])
    _write_config(repo, {
        "enabled": True,
        "mode": "strict",
        "typecheck_cmd": "exit 1",        # subprocess FAIL
        "test_cmd_affected": "exit 0",
        "contract_runtime": False,
        "timeout_seconds": 10,
    })
    r = _run(repo, tag)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert any(e["type"] == "wave_verify_divergence" for e in out["evidence"])


def test_divergence_advisory_warns(tmp_path):
    repo, tag = _setup_repo(tmp_path, [
        ("a.ts", "broken", "feat(9-01): add x\n\ntypecheck: PASS"),
    ])
    _write_config(repo, {
        "enabled": True,
        "mode": "advisory",
        "typecheck_cmd": "exit 1",
        "test_cmd_affected": "exit 0",
        "contract_runtime": False,
        "timeout_seconds": 10,
    })
    r = _run(repo, tag)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "WARN"
    assert any(e["type"] == "wave_verify_divergence_advisory"
               for e in out["evidence"])


def test_cli_mode_overrides_config(tmp_path):
    """--mode advisory overrides config mode=strict."""
    repo, tag = _setup_repo(tmp_path, [
        ("a.ts", "broken", "feat(9-01)\n\ntypecheck: PASS"),
    ])
    _write_config(repo, {
        "enabled": True,
        "mode": "strict",
        "typecheck_cmd": "exit 1",
        "test_cmd_affected": "exit 0",
        "contract_runtime": False,
        "timeout_seconds": 10,
    })
    r = _run(repo, tag, mode="advisory")
    assert r.returncode == 0   # CLI advisory overrides config strict


def test_no_claim_no_comparison(tmp_path):
    """If commit doesn't claim anything, no divergence possible."""
    repo, tag = _setup_repo(tmp_path, [
        ("a.ts", "x", "feat(9-01): plain commit without claims"),
    ])
    _write_config(repo, {
        "enabled": True,
        "mode": "strict",
        "typecheck_cmd": "exit 1",  # would fail, but no claim → skip compare
        "test_cmd_affected": "exit 0",
        "contract_runtime": False,
        "timeout_seconds": 10,
    })
    r = _run(repo, tag)
    out = _parse(r.stdout)
    # subprocess ran with rc=1, but no claim → no compare → PASS
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_tests_claim_parse(tmp_path):
    """Claim 'tests: 12/12' parsed as PASS, 'tests: 10/12' as FAIL."""
    repo, tag = _setup_repo(tmp_path, [
        ("a.ts", "x", "feat\n\ntests: 10/12"),   # partial pass = claim FAIL
    ])
    _write_config(repo, {
        "enabled": True,
        "mode": "strict",
        "typecheck_cmd": "",
        "test_cmd_affected": "exit 0",   # subprocess says PASS → diverges
        "contract_runtime": False,
        "timeout_seconds": 10,
    })
    r = _run(repo, tag)
    out = _parse(r.stdout)
    assert r.returncode == 1
    # Divergence: claim FAIL, actual PASS — also a real signal (claimed broken, now passes? weird)
    ev = out["evidence"][0]
    assert "tests" in ev["actual"]


def test_timeout_or_failure_reports_divergence(tmp_path):
    """Subprocess timeout OR hard failure → report as divergence.

    On Windows cmd.exe with shell=True, escaped python path is
    finicky. Use `python -c` unquoted — if python not in PATH it'll
    fail with rc != 0, which ALSO surfaces as divergence since claim
    was PASS. Either way test asserts divergence caught.
    """
    repo, tag = _setup_repo(tmp_path, [
        ("a.ts", "x", "feat\n\ntypecheck: PASS"),
    ])
    _write_config(repo, {
        "enabled": True,
        "mode": "strict",
        "typecheck_cmd": "python -c \"import time; time.sleep(10)\"",
        "test_cmd_affected": "",
        "contract_runtime": False,
        "timeout_seconds": 1,      # force timeout or quick fail
    })
    r = _run(repo, tag)
    out = _parse(r.stdout)
    # Either subprocess timed out (takes >1s), or command failed to parse
    # (returns nonzero quickly) — both = claim PASS diverges from actual FAIL
    assert r.returncode == 1, (
        f"Expected BLOCK (rc=1) from divergence, got {r.returncode}.\n"
        f"stdout={r.stdout}"
    )
    assert any(e["type"] in ("wave_verify_divergence",)
               for e in out["evidence"])


def test_registered_in_build_validators():
    """wave-verify-isolated must be in COMMAND_VALIDATORS[vg:build]."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main",
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_main"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    assert "wave-verify-isolated" in mod.COMMAND_VALIDATORS.get("vg:build", [])


def test_unquarantinable_includes_wave_verify():
    """wave-verify-isolated must be UNQUARANTINABLE (AI can't disable it)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main",
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_main"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    assert "wave-verify-isolated" in mod.UNQUARANTINABLE
