#!/usr/bin/env python3
"""Run one CrossAI CLI command in an isolated working directory.

The child CLI must not inherit repo-local hook/config discovery from the
current project checkout. We keep the user's auth/config HOME, but run from a
fresh temp cwd and scrub session-specific variables that can re-attach the
child to the parent workflow runtime.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SCRUB_ENV_KEYS = {
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_SANDBOX",
    "CODEX_CLI_SANDBOX",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "VG_PROVIDER",
    "VG_REPO_ROOT",
    "VG_RUNTIME",
}


def _shell_binary() -> str:
    for name in ("bash", "sh"):
        path = shutil.which(name)
        if path:
            return path
    raise FileNotFoundError("bash/sh not found in PATH")


def _isolated_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in SCRUB_ENV_KEYS:
        env.pop(key, None)
    env["VG_CROSSAI_ISOLATED"] = "1"
    return env


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", errors="replace")


def _escape_for_quote(value: str, quote: str) -> str:
    if quote == "'":
        return value.replace("'", "'\"'\"'")
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )


def _replace_shell_placeholder(template: str, placeholder: str, value: str) -> str:
    """Replace shell placeholders safely whether template quotes them or not."""
    def quote_at(pos: int) -> str:
        quote = ""
        escaped = False
        for ch in template[:pos]:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if quote:
                if ch == quote:
                    quote = ""
                continue
            if ch in ("'", '"'):
                quote = ch
        return quote

    out: list[str] = []
    idx = 0
    plen = len(placeholder)
    while True:
        pos = template.find(placeholder, idx)
        if pos < 0:
            out.append(template[idx:])
            break
        out.append(template[idx:pos])
        quote = quote_at(pos)
        after_pos = pos + plen
        if quote:
            out.append(_escape_for_quote(value, quote))
        else:
            out.append(shlex.quote(value))
        idx = after_pos
    return "".join(out)


def run_one(
    *,
    name: str,
    command_template: str,
    prompt: str,
    context_file: Path,
    output_dir: Path,
    timeout_s: int,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    result_file = output_dir / f"result-{name}.xml"
    err_file = output_dir / f"result-{name}.err"
    exit_file = output_dir / f"result-{name}.exit"
    meta_file = output_dir / f"result-{name}.meta.json"

    context_value = str(context_file.resolve())
    command = _replace_shell_placeholder(command_template, "{prompt}", prompt)
    command = _replace_shell_placeholder(command, "{context}", context_value)
    shell = _shell_binary()
    isolated_cwd = Path(
        tempfile.mkdtemp(prefix="vg-crossai-run-", dir=os.environ.get("VG_TMP"))
    )
    env = _isolated_env()

    stdout_text = ""
    stderr_text = ""
    exit_code = 0
    try:
        proc = subprocess.run(
            [shell, "-lc", command],
            cwd=str(isolated_cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            encoding="utf-8",
            errors="replace",
        )
        stdout_text = proc.stdout
        stderr_text = proc.stderr
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout_text = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr_text = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        stderr_text = (stderr_text + "\n" if stderr_text else "") + (
            f"CrossAI runner timeout after {timeout_s}s"
        )
        exit_code = 124
    except FileNotFoundError as exc:
        stderr_text = f"{exc}\n"
        exit_code = 127

    _write(result_file, stdout_text)
    _write(err_file, stderr_text)
    _write(exit_file, f"{exit_code}\n")
    meta_file.write_text(
        json.dumps(
            {
                "name": name,
                "cwd": str(isolated_cwd),
                "command": command,
                "timeout_s": timeout_s,
                "shell": shell,
                "isolated": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "name": name,
        "cwd": str(isolated_cwd),
        "exit_code": exit_code,
        "result_file": str(result_file),
        "err_file": str(err_file),
        "meta_file": str(meta_file),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--context-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run_one(
        name=args.name,
        command_template=args.command,
        prompt=args.prompt,
        context_file=Path(args.context_file),
        output_dir=Path(args.output_dir),
        timeout_s=args.timeout,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"CrossAI runner complete: {report['name']} exit={report['exit_code']} "
            f"cwd={report['cwd']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
