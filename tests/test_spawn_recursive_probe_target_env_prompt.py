"""Test interactive target_env prompt (v2.40.1).

The dispatcher (`scripts/spawn_recursive_probe.py`) prompts the operator at
Phase 2b-2.5 to pick a target env when no `--target-env` flag is passed and
`--non-interactive` is not set. Prod selection requires typing the phase name
exactly to confirm — analog to GitHub repo-deletion safety.

These tests exercise the helper directly via dependency-injected
``stdin``/``stdout`` ``StringIO`` objects, avoiding any real-terminal contact.
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_module():
    spec = importlib.util.spec_from_file_location(
        "spawn_recursive_probe",
        REPO_ROOT / "scripts" / "spawn_recursive_probe.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prompt_returns_local_for_l():
    mod = load_module()
    stdin = io.StringIO("l\n")
    stdout = io.StringIO()
    result = mod.prompt_target_env("test-phase", stdin, stdout)
    assert result == "local"


def test_prompt_returns_sandbox_for_s():
    mod = load_module()
    stdin = io.StringIO("s\n")
    stdout = io.StringIO()
    assert mod.prompt_target_env("test-phase", stdin, stdout) == "sandbox"


def test_prompt_default_sandbox_on_enter():
    mod = load_module()
    stdin = io.StringIO("\n")
    stdout = io.StringIO()
    assert mod.prompt_target_env("test-phase", stdin, stdout) == "sandbox"


def test_prompt_returns_staging_for_g():
    mod = load_module()
    stdin = io.StringIO("g\n")
    stdout = io.StringIO()
    assert mod.prompt_target_env("test-phase", stdin, stdout) == "staging"


def test_prompt_invalid_choice_exits_2():
    mod = load_module()
    stdin = io.StringIO("x\n")
    stdout = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        mod.prompt_target_env("test-phase", stdin, stdout)
    assert exc.value.code == 2


def test_prod_requires_typed_phase_name():
    mod = load_module()
    # User selects p, then types exact phase name to confirm.
    stdin = io.StringIO("p\nmy-test-phase\n")
    stdout = io.StringIO()
    assert mod.prompt_target_env("my-test-phase", stdin, stdout) == "prod"


def test_prod_aborts_on_wrong_phase_name():
    mod = load_module()
    stdin = io.StringIO("p\nwrong-name\n")
    stdout = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        mod.prompt_target_env("my-test-phase", stdin, stdout)
    assert exc.value.code == 1


def test_prod_aborts_on_empty_confirmation():
    mod = load_module()
    stdin = io.StringIO("p\n\n")
    stdout = io.StringIO()
    with pytest.raises(SystemExit):
        mod.prompt_target_env("my-test-phase", stdin, stdout)
