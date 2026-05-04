#!/usr/bin/env python3
"""
verify-test-ids-injected.py — v2.43.5

Validator for /vg:build wave commit step.

Asserts: every `<id value="...">` declared in PLAN task `<test_ids>` block
appears verbatim in the wave's committed source files (as `data-testid="..."`
or framework equivalent).

Triggered by:
  - Task XML contains `<test_ids>` block
  - Wave staged files include any of the task's <files>

Outcome:
  - PASS  → all declared values found in committed source
  - WARN  → some values missing (default — log debt, allow wave commit)
  - FAIL  → critical values missing (kind=button|form|input + severity=block)

Override: --allow-missing-injection="<reason>"

Usage:
  verify-test-ids-injected.py --phase-dir <path> --task-id <N> [--severity warn|block]
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path


def extract_test_ids_from_task(plan_path: Path, task_index: int) -> list[dict]:
    """Returns list of {kind, value, files} from the Nth task in PLAN.md."""
    if not plan_path.exists():
        return []
    text = plan_path.read_text(encoding="utf-8")
    tasks = list(re.finditer(r"<task[^>]*>(?P<body>.*?)</task>", text, re.DOTALL))
    if task_index < 1 or task_index > len(tasks):
        return []
    body = tasks[task_index - 1].group("body")

    # Files block
    files_block = re.search(r"<files>(.*?)</files>", body, re.DOTALL)
    files = (
        re.findall(r"[\w/.-]+\.(?:tsx|jsx|vue|svelte)", files_block.group(1))
        if files_block else []
    )

    # test_ids block
    ti_block = re.search(r"<test_ids>(.*?)</test_ids>", body, re.DOTALL)
    if not ti_block:
        return []

    ids = []
    for m in re.finditer(r'<id\s+kind="([^"]+)"\s+value="([^"]+)"', ti_block.group(1)):
        ids.append({"kind": m.group(1), "value": m.group(2), "files": files})
    return ids


def check_value_in_files(value: str, files: list[Path]) -> bool:
    """Returns True if value appears as data-testid in any of the source files."""
    # Substitute template placeholders {var} with .* for grep
    pattern_value = re.sub(r"\{[^}]+\}", r".*", re.escape(value))
    pattern_value = pattern_value.replace(r"\.\*", ".*")  # un-escape regex parts
    pattern = re.compile(
        rf'data-testid\s*=\s*[`"\']?\s*[`"\']?{pattern_value}[`"\']?',
        re.IGNORECASE,
    )

    for f in files:
        if not f.exists():
            continue
        try:
            content = f.read_text(encoding="utf-8")
            if pattern.search(content):
                return True
            # Also check JSX dynamic form: data-testid={`...`}
            if re.search(rf'data-testid\s*=\s*\{{\s*[`"\'][^`"\']*{pattern_value}[^`"\']*[`"\']', content):
                return True
        except Exception:
            continue
    return False


CRITICAL_KINDS = {"button", "form", "input"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--task-id", type=int, required=True)
    ap.add_argument("--severity", default="warn", choices=["warn", "block"])
    ap.add_argument("--allow-missing-injection", default=None)
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    plan_path = phase_dir / "PLAN.md"

    ids = extract_test_ids_from_task(plan_path, args.task_id)
    if not ids:
        print(f"SKIP: task #{args.task_id} has no <test_ids> block (or no UI files)")
        return 0

    repo_root = Path.cwd()
    missing = []
    found = []
    for entry in ids:
        files = [repo_root / f for f in entry["files"]]
        if check_value_in_files(entry["value"], files):
            found.append(entry)
        else:
            missing.append(entry)

    if not missing:
        print(f"PASS: {len(found)}/{len(ids)} declared test IDs found in source")
        return 0

    print(f"VIOLATION: {len(missing)}/{len(ids)} test IDs missing in committed source:")
    for m in missing:
        print(f"  ⛔ {m['kind']:12} {m['value']:40} (expected in: {m['files'][:2]})")

    critical_missing = [m for m in missing if m["kind"] in CRITICAL_KINDS]

    if args.allow_missing_injection:
        print(f"\n⚠ Override: --allow-missing-injection=\"{args.allow_missing_injection}\"")
        return 0

    if args.severity == "warn" and not critical_missing:
        print("\nSeverity: warn (no critical kinds missing). Wave commit allowed.")
        return 0

    if critical_missing:
        print(f"\n⛔ {len(critical_missing)} CRITICAL kinds (button/form/input) missing.")
        print("   These break test specs immediately. Wave will be reopened.")
    print("\nFix: edit the component file(s), inject `data-testid=\"<value>\"` per planner Rule 10.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
