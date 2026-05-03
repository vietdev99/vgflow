from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "spawn-diagnostic-l2.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("spawn_diagnostic_l2", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _clear_runtime_env(monkeypatch) -> None:
    for name in (
        "VG_RUNTIME",
        "VG_PROVIDER",
        "VG_DIAGNOSTIC_L2_CLI",
        "VG_CODEX_MODEL_SCANNER",
        "CLAUDE_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_PROJECT_DIR",
        "CODEX_SANDBOX",
        "CODEX_CLI_SANDBOX",
        "CODEX_HOME",
    ):
        monkeypatch.delenv(name, raising=False)


def test_default_l2_cli_preserves_claude_haiku_for_unknown_runtime(monkeypatch) -> None:
    mod = _load_module()
    _clear_runtime_env(monkeypatch)

    assert mod._default_cli() == ["claude", "--model", "haiku", "-p"]


def test_default_l2_cli_uses_codex_adapter_when_runtime_is_codex(monkeypatch) -> None:
    mod = _load_module()
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("VG_RUNTIME", "codex")
    monkeypatch.setenv("VG_CODEX_MODEL_SCANNER", "gpt-test-scanner")

    assert mod._default_cli() == [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--model",
        "gpt-test-scanner",
    ]


def test_l2_cli_override_wins_over_runtime_adapter(monkeypatch) -> None:
    mod = _load_module()
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("VG_RUNTIME", "codex")
    monkeypatch.setenv("VG_DIAGNOSTIC_L2_CLI", "custom-cli --flag")

    assert mod._default_cli() == ["custom-cli", "--flag"]
