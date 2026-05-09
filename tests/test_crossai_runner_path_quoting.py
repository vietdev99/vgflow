"""v2.66.0 C1.1 (#149) — CrossAI runner path-quoting.

Issue #149: Workspace path with spaces breaks stdin pipe to all CrossAI CLIs
because scripts/crossai-runner.py used bare string substitution
(`command_template.replace("{context}", str(context_file))`) — emitting an
unquoted path that the shell splits at the space.

Fix: introduce `_materialize_command(template, context_path, prompt)` that
runs both placeholders through `shlex.quote()`, and update the invoke template
in `commands/vg/_shared/crossai-invoke.md` to wrap `{context}` in shell quotes
so the docs match the runtime behavior.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO_ROOT / "scripts" / "crossai-runner.py"
INVOKE_PATH = REPO_ROOT / "commands" / "vg" / "_shared" / "crossai-invoke.md"


def _load_runner_module():
    """Load scripts/crossai-runner.py despite the hyphenated filename."""
    spec = importlib.util.spec_from_file_location(
        "crossai_runner_under_test", str(RUNNER_PATH)
    )
    assert spec is not None and spec.loader is not None, "cannot load runner module"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_path_with_spaces_in_context_arg():
    """Context path with spaces must be quoted in the materialized command."""
    runner = _load_runner_module()
    assert hasattr(runner, "_materialize_command"), (
        "_materialize_command helper missing from crossai-runner.py"
    )

    cmd = runner._materialize_command(
        template='cat {context} | claude --model sonnet -p {prompt}',
        context_path="/path with space/ctx.md",
        prompt="hello",
    )
    # Either single-quote or double-quote must wrap the spaced path so the
    # shell does not split it at the space.
    assert (
        "'/path with space/ctx.md'" in cmd
        or '"/path with space/ctx.md"' in cmd
    ), f"Path with spaces not quoted: {cmd}"


def test_prompt_with_quotes_escaped():
    """Prompt containing quotes/special chars must not break shell parse."""
    runner = _load_runner_module()
    cmd = runner._materialize_command(
        template='cat {context} | claude --model sonnet -p {prompt}',
        context_path="/tmp/ctx.md",
        prompt='hello "world" with $vars',
    )
    # The prompt placeholder must be replaced exactly once; shlex.quote should
    # ensure the whole prompt is a single shell-safe token.
    assert cmd.count("-p ") == 1
    # Validate POSIX shell parse without executing anything.
    sh_path = "/bin/sh"
    if not Path(sh_path).exists():
        # Windows or stripped image — fall back to bash if present
        from shutil import which

        sh_path = which("bash") or which("sh") or ""
    if not sh_path:
        pytest.skip("no POSIX shell available to validate parse")
    rc = subprocess.run([sh_path, "-n", "-c", cmd]).returncode
    assert rc == 0, f"Command not shell-safe: {cmd}"


def test_template_invoke_md_uses_quoted_form():
    """commands/vg/_shared/crossai-invoke.md must wrap {context} in shell quotes."""
    body = INVOKE_PATH.read_text(encoding="utf-8")
    # The bare unquoted form must NOT appear anywhere.
    bad = re.search(r"cat\s+\{context\}", body)
    assert not bad, "Found unquoted `cat {context}` pattern in invoke template"
    # At least one `cat '{context}'` or `cat \"{context}\"` form must exist.
    assert re.search(r"cat\s+['\"]\{context\}['\"]", body), (
        "invoke template must wrap {context} in shell quotes"
    )
