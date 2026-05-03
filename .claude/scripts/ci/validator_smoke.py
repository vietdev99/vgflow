#!/usr/bin/env python3
"""CI smoke checks for VG validator scripts.

The validators directory contains two different kinds of Python files:
runtime validators and helper/reporting utilities. Runtime validators that use
the shared ``_common.Output`` contract should emit JSON when they can run with a
minimal ``--phase`` argument. Utility scripts should still compile, but must not
be forced through that JSON contract.
"""

from __future__ import annotations

import ast
import json
import py_compile
import subprocess
import sys
from pathlib import Path


ROOT = Path("scripts/validators")
EXTRA_JSON_CONTRACT = {
    "verify-playwright-mcp-config.py",
}


def cli_flags(call: ast.Call) -> list[str]:
    flags: list[str] = []
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("--"):
            flags.append(arg.value)
    return flags


def is_required(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "required" and isinstance(kw.value, ast.Constant):
            return kw.value.value is True
    return False


def uses_json_contract(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    return ("from _common import" in text and "Output" in text) or path.name in EXTRA_JSON_CONTRACT


def phase_smokeable(path: Path) -> tuple[bool, str]:
    if not uses_json_contract(path):
        return False, "not a _common.Output JSON validator"

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    has_phase = False
    required_flags: set[str] = set()
    required_groups: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "add_mutually_exclusive_group"
            and is_required(node.value)
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    required_groups.add(target.id)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
            continue
        flags = cli_flags(node)
        if "--phase" in flags:
            has_phase = True
        if is_required(node):
            required_flags.update(flag for flag in flags if flag != "--phase")
        if isinstance(func.value, ast.Name) and func.value.id in required_groups:
            required_flags.update(flags)

    if not has_phase:
        return False, "no --phase CLI"
    if required_flags:
        return False, "requires " + ", ".join(sorted(required_flags))
    return True, ""


def run_json_smoke(path: Path) -> str | None:
    proc = subprocess.run(
        [sys.executable, str(path), "--phase", "99"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    payload = proc.stdout.strip()
    try:
        data = json.loads(payload)
    except Exception as exc:
        return (
            f"json {path.stem}: {exc}; rc={proc.returncode}; "
            f"stdout={payload[:200]!r}; stderr={proc.stderr.strip()[:200]!r}"
        )
    if not isinstance(data, dict) or "validator" not in data or "verdict" not in data:
        return f"json {path.stem}: missing validator/verdict keys"
    print(f"OK JSON {path.stem}: {data['verdict']}")
    return None


def main() -> int:
    failures: list[str] = []

    for path in sorted(ROOT.glob("*.py")):
        try:
            py_compile.compile(str(path), doraise=True)
            print(f"OK compile {path.name}")
        except Exception as exc:
            failures.append(f"compile {path.name}: {exc}")

        if path.name.startswith("_"):
            continue

        try:
            smoke, reason = phase_smokeable(path)
        except SyntaxError as exc:
            failures.append(f"inspect {path.name}: {exc}")
            continue
        if not smoke:
            print(f"- skip JSON {path.stem}: {reason}")
            continue

        failure = run_json_smoke(path)
        if failure:
            failures.append(failure)

    if failures:
        print("\nValidator smoke failures:")
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
