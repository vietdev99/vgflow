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


def _is_wsl_launcher(path: str) -> bool:
    normalized = path.replace("/", "\\").lower()
    return (
        "\\windows\\system32\\bash.exe" in normalized
        or "\\appdata\\local\\microsoft\\windowsapps\\bash.exe" in normalized
    )


def _existing(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in paths:
        if not raw:
            continue
        path = os.path.abspath(os.path.expandvars(os.path.expanduser(raw)))
        key = os.path.normcase(path)
        if key in seen or not os.path.isfile(path):
            continue
        seen.add(key)
        out.append(path)
    return out


def _shell_binary() -> str:
    env_bash = os.environ.get("VG_BASH", "")
    path_bash = shutil.which("bash") or shutil.which("bash.exe") or ""

    if os.name != "nt":
        candidates = _existing([env_bash, path_bash, "/usr/bin/bash", "/bin/bash"])
        if candidates:
            return candidates[0]
        sh_path = shutil.which("sh")
        if sh_path:
            return sh_path
        raise FileNotFoundError("bash/sh not found in PATH")

    program_files = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("LocalAppData", ""),
    ]
    git_candidates: list[str] = []
    for root in program_files:
        if not root:
            continue
        git_candidates.extend(
            [
                str(Path(root) / "Git" / "bin" / "bash.exe"),
                str(Path(root) / "Git" / "usr" / "bin" / "bash.exe"),
                str(Path(root) / "Programs" / "Git" / "bin" / "bash.exe"),
                str(Path(root) / "Programs" / "Git" / "usr" / "bin" / "bash.exe"),
            ]
        )

    candidates = [env_bash, *git_candidates]
    if path_bash and not _is_wsl_launcher(path_bash):
        candidates.append(path_bash)
    candidates.append(path_bash)
    existing = _existing(candidates)
    if existing:
        return existing[0]
    raise FileNotFoundError("bash/sh not found in PATH")


def _isolated_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in SCRUB_ENV_KEYS:
        env.pop(key, None)
    env["VG_CROSSAI_ISOLATED"] = "1"
    return env


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", errors="replace")


def _strip_codex_banner(text: str) -> str:
    """Strip Codex CLI banner lines before persisting to result file.

    Issue #155 (v2.66.0): Codex CLI v0.118.0 emits a multi-line banner
    (``Reading additional input from stdin...`` / ``OpenAI Codex v0.118.0
    (research preview)`` / ``--------`` separator / ``workdir:`` /
    ``model:`` / ``provider:`` / ``--------`` separator / ``user`` keyword /
    ``<prompt echo>`` lines) BEFORE the actual model output. The runner
    used to write raw stdout, so the result XML file started with banner
    text instead of ``<crossai_review>`` — downstream extractor matched on
    the prompt's example XML or returned malformed_output.

    Strategy: detect Codex output via the ``OpenAI Codex`` banner header.
    For non-Codex (Claude, Gemini, ...), pass through byte-identical. For
    Codex, find the LAST ``--------`` separator (which closes the banner
    block), skip a ``user`` keyword line if present, then skip prompt
    echo lines until we hit the first line that starts with ``<`` (XML),
    ``{`` (JSON), or a code-fence opener — these mark the start of model
    output.
    """
    if "OpenAI Codex" not in text:
        return text

    lines = text.splitlines(keepends=True)
    sep_indices = [i for i, line in enumerate(lines) if line.strip() == "--------"]
    if len(sep_indices) < 2:
        # Banner shape unrecognized — be conservative and pass through.
        return text

    start = sep_indices[-1] + 1
    # Skip the ``user`` keyword line if Codex emitted one.
    if start < len(lines) and lines[start].strip() == "user":
        start += 1
    # Skip prompt echo lines until we reach actual model output.
    while start < len(lines) and not lines[start].lstrip().startswith(("<", "{", "```")):
        start += 1
    return "".join(lines[start:])


def _materialize_command(template: str, context_path: str, prompt: str) -> str:
    """Substitute {context} and {prompt} with shell-safe quoted values.

    Issue #149: bare ``str.replace`` left workspace paths with spaces unquoted
    so the shell split the pipe at the first whitespace
    (``cat: /Users/<u>/path: Is a directory``). Both placeholders are routed
    through :func:`shlex.quote` so the materialized command parses safely
    regardless of spaces/quotes/``$``-vars in either value.
    """
    return (
        template
        .replace("{context}", shlex.quote(str(context_path)))
        .replace("{prompt}", shlex.quote(str(prompt)))
    )


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

    command = _materialize_command(
        template=command_template,
        context_path=str(context_file),
        prompt=prompt,
    )
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

    # v2.66.0 (#155): strip Codex banner before persisting so the XML file
    # starts with <crossai_review> rather than `OpenAI Codex v0.118.0...`.
    _write(result_file, _strip_codex_banner(stdout_text))
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
