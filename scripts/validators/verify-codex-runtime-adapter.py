#!/usr/bin/env python3
"""Verify Codex mirrors carry runtime-adaptive contracts for Claude primitives.

This does not prove a full end-to-end phase run. It prevents a weaker failure
mode: a source command gains Agent/Playwright/CrossAI runtime behavior, but the
generated Codex mirror lacks instructions for preserving that behavior on Codex.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

RUNTIME_MARKERS = (
    "Agent(",
    "Task(",
    "Playwright",
    "Maestro",
    "CrossAI",
    "crossai",
    "mcp__",
    "review.haiku_scanner_spawned",
)

GENERIC_REQUIRED = (
    "<codex_runtime_contract>",
    "Provider mapping",
    "Codex hook parity",
    "UserPromptSubmit",
    "vg-entry-hook.py",
    "vg-verify-claim.py",
    "vg-step-tracker.py",
    ".vg/events.db",
    "vg-orchestrator run-start",
    "vg-orchestrator mark-step",
    "vg-orchestrator run-complete",
    "Codex spawn precedence",
    "Claude path",
    "Codex path",
    "Never skip source workflow gates",
    "BLOCK instead of silently degrading",
    "commands/vg/_shared/lib/codex-spawn.sh",
    "VG_CODEX_MODEL_EXECUTOR",
    "VG_CODEX_MODEL_SCANNER",
    "review.haiku_scanner_spawned",
    "MUST run the scanner protocol",
    "MCP-heavy work in the main Codex orchestrator",
    "UI/UX, security, and business-flow checks",
)

SUPPORT_REQUIRED = {
    "vg-reflector": (
        "<codex_skill_adapter>",
        "commands/vg/_shared/lib/codex-spawn.sh",
        "VG_CODEX_MODEL_SCANNER",
        "Model mapping",
    ),
    "vg-haiku-scanner": (
        "<codex_skill_adapter>",
        "INLINE ORCHESTRATOR",
        "MCP",
        "Pattern A",
        "codex exec",
    ),
}


def _resolve_repo_root(root_arg: str | None) -> Path:
    if root_arg:
        return Path(root_arg).resolve()
    env = os.environ.get("REPO_ROOT") or os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env).resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return Path(out.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd().resolve()


def _has_runtime_marker(text: str) -> bool:
    return any(marker in text for marker in RUNTIME_MARKERS)


def _command_files(root: Path) -> list[Path]:
    cmd_dir = root / "commands" / "vg"
    if not cmd_dir.is_dir():
        cmd_dir = root / ".claude" / "commands" / "vg"
    if not cmd_dir.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(cmd_dir.glob("*.md")):
        name = path.stem
        if name.startswith("_") or name.endswith("-insert"):
            continue
        files.append(path)
    return files


def _support_skill_files(root: Path) -> list[Path]:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        skills_dir = root / ".claude" / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(
        path / "SKILL.md"
        for path in skills_dir.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def _issue(kind: str, path: Path, detail: str) -> dict[str, str]:
    return {"kind": kind, "path": str(path), "detail": detail}


def _mirror_root(root: Path) -> Path:
    source_mirror = root / "codex-skills"
    if source_mirror.is_dir():
        return source_mirror
    return root / ".codex" / "skills"


def _skill_name_from_command(command_path: Path) -> str:
    return f"vg-{command_path.stem}"


def validate(root: Path) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    runtime_commands: list[str] = []
    support_skills: list[str] = []
    runtime_support_skills: list[str] = []
    mirrors_dir = _mirror_root(root)

    for command_path in _command_files(root):
        source_text = command_path.read_text(encoding="utf-8")
        if not _has_runtime_marker(source_text):
            continue

        runtime_commands.append(command_path.name)
        mirror_path = mirrors_dir / _skill_name_from_command(command_path) / "SKILL.md"
        if not mirror_path.is_file():
            issues.append(_issue("missing_mirror", mirror_path, command_path.name))
            continue

        mirror_text = mirror_path.read_text(encoding="utf-8")
        for required in GENERIC_REQUIRED:
            if required not in mirror_text:
                issues.append(
                    _issue(
                        "missing_runtime_contract",
                        mirror_path,
                        f"{command_path.name}: missing {required!r}",
                    )
                )

    for skill_name, required_strings in SUPPORT_REQUIRED.items():
        skill_path = mirrors_dir / skill_name / "SKILL.md"
        if not skill_path.is_file():
            issues.append(_issue("missing_support_skill", skill_path, skill_name))
            continue
        skill_text = skill_path.read_text(encoding="utf-8")
        for required in required_strings:
            if required not in skill_text:
                issues.append(
                    _issue(
                        "missing_support_runtime_contract",
                        skill_path,
                        f"{skill_name}: missing {required!r}",
                    )
                )

    for source_skill in _support_skill_files(root):
        skill_name = source_skill.parent.name
        support_skills.append(skill_name)
        mirror_path = mirrors_dir / skill_name / "SKILL.md"
        if not mirror_path.is_file():
            issues.append(_issue("missing_support_skill_mirror", mirror_path, skill_name))
            continue

        source_text = source_skill.read_text(encoding="utf-8")
        if not _has_runtime_marker(source_text):
            continue

        runtime_support_skills.append(skill_name)
        mirror_text = mirror_path.read_text(encoding="utf-8")
        required_strings = SUPPORT_REQUIRED.get(skill_name, GENERIC_REQUIRED)
        for required in required_strings:
            if required not in mirror_text:
                issues.append(
                    _issue(
                        "missing_support_runtime_contract",
                        mirror_path,
                        f"{skill_name}: missing {required!r}",
                    )
                )

    return {
        "root": str(root),
        "runtime_command_count": len(runtime_commands),
        "runtime_commands": runtime_commands,
        "support_skill_count": len(support_skills),
        "runtime_support_skill_count": len(runtime_support_skills),
        "runtime_support_skills": runtime_support_skills,
        "issue_count": len(issues),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", help="Repository root to validate")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    result = validate(_resolve_repo_root(args.root))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif result["issue_count"]:
        print(
            f"Codex runtime adapter drift: {result['issue_count']} issue(s) "
            f"across {result['runtime_command_count']} runtime command(s)."
        )
        for issue in result["issues"]:
            print(f"- {issue['kind']}: {issue['path']} :: {issue['detail']}")
    elif not args.quiet:
        print(
            "OK: Codex runtime adapter contracts present for "
            f"{result['runtime_command_count']} runtime command(s)."
        )

    return 1 if result["issue_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
