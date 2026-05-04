#!/usr/bin/env python3
"""
verify-test-ids-declared.py — v2.43.5

Validator for /vg:blueprint step 2c (verify).

Asserts: every PLAN.md task that creates/modifies UI components
(matched against UI globs) declares a `<test_ids>` block with ≥1 `<id>`
child.

Triggered by:
  - vg.config.md > test_ids.enabled: true
  - Phase profile in {feature, feature-legacy, hotfix, bugfix} with
    surface=ui or ui-mobile

Outcome:
  - PASS  → exit 0
  - WARN  → exit 0 with warning (default during 2-week migration window)
  - FAIL  → exit 1 (when test_ids.enforce_severity: "block")
  - SKIP  → exit 0 (config disabled / non-UI phase / --skip flag)

Override: --allow-missing-testids="<reason>" logs OVERRIDE-DEBT critical.

Usage:
  verify-test-ids-declared.py --phase-dir <path> [--severity warn|block]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

UI_GLOB_PATTERNS = [
    re.compile(r'apps/[^/]+/src/(components|pages|features|views|app)/.*\.(tsx|jsx|vue|svelte)$'),
    re.compile(r'packages/[^/]+/src/.*\.(tsx|jsx|vue|svelte)$'),
]

INTERACTIVE_KIND_KEYWORDS = {
    "button", "link", "input", "select", "form",
    "table-row", "modal", "tab", "checkbox", "radio",
}


def is_ui_task(task_files: list[str]) -> bool:
    """Returns True if any file matches a UI glob."""
    return any(
        any(p.search(f) for p in UI_GLOB_PATTERNS) for f in task_files
    )


def parse_plan_tasks(plan_path: Path) -> list[dict]:
    """
    Extract tasks from PLAN.md. Returns list of dicts:
        {id, title, files, has_test_ids, test_id_count, kinds}
    """
    if not plan_path.exists():
        return []
    text = plan_path.read_text(encoding="utf-8")
    tasks = []
    # Match each `<task ...>...</task>` block (XML-flavored)
    for match in re.finditer(
        r"<task[^>]*>(?P<body>.*?)</task>", text, re.DOTALL
    ):
        body = match.group("body")
        # Extract title (best-effort — first heading or <name>)
        title_m = re.search(r"<name>(.*?)</name>|^###?\s+(.+)$", body, re.M)
        title = (title_m.group(1) or title_m.group(2) or "").strip() if title_m else "?"
        # Files list — both <files> tag and bullets
        files = []
        files_block = re.search(r"<files>(.*?)</files>", body, re.DOTALL)
        if files_block:
            files = re.findall(r"[\w/.-]+\.(?:tsx|jsx|vue|svelte|ts|js|py)", files_block.group(1))
        # test_ids block presence
        ti_block = re.search(r"<test_ids>(.*?)</test_ids>", body, re.DOTALL)
        kinds = []
        if ti_block:
            kinds = re.findall(r'kind="([^"]+)"', ti_block.group(1))
        tasks.append({
            "title": title,
            "files": files,
            "has_test_ids": bool(ti_block),
            "test_id_count": len(kinds),
            "kinds": kinds,
        })
    return tasks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--severity", default="warn", choices=["warn", "block"])
    ap.add_argument("--config", default=".claude/vg.config.md")
    ap.add_argument("--allow-missing-testids", default=None,
                    help="override reason; logs OVERRIDE-DEBT critical")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    plan_path = phase_dir / "PLAN.md"
    config_path = Path(args.config)

    # Skip if config disables feature
    config_text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    if not re.search(r"^test_ids:\s*$", config_text, re.M):
        print("SKIP: vg.config.md has no test_ids block — feature disabled.")
        return 0
    enabled_m = re.search(r"^test_ids:\s*\n(?:[^\n]*\n)*?\s+enabled:\s+(true|false)", config_text, re.M)
    if enabled_m and enabled_m.group(1) == "false":
        print("SKIP: vg.config.md test_ids.enabled=false")
        return 0

    if not plan_path.exists():
        print(f"SKIP: {plan_path} not found (blueprint hasn't run yet)")
        return 0

    tasks = parse_plan_tasks(plan_path)
    if not tasks:
        print("SKIP: no <task> blocks found in PLAN.md")
        return 0

    ui_tasks = [t for t in tasks if is_ui_task(t["files"])]
    if not ui_tasks:
        print(f"SKIP: 0 UI tasks (of {len(tasks)} total) — no testid required")
        return 0

    missing = [t for t in ui_tasks if not t["has_test_ids"]]
    empty   = [t for t in ui_tasks if t["has_test_ids"] and t["test_id_count"] == 0]

    if not missing and not empty:
        print(f"PASS: {len(ui_tasks)}/{len(ui_tasks)} UI tasks declare <test_ids> "
              f"with ≥1 <id> entry")
        return 0

    print(f"VIOLATION ({len(missing)+len(empty)}/{len(ui_tasks)} UI tasks):")
    for t in missing:
        files_short = ", ".join(t["files"][:3]) + ("..." if len(t["files"]) > 3 else "")
        print(f"  ⛔ MISSING <test_ids>: {t['title'][:60]}  ({files_short})")
    for t in empty:
        print(f"  ⛔ EMPTY <test_ids> (no <id> children): {t['title'][:60]}")

    if args.allow_missing_testids:
        print(f"\n⚠ Override: --allow-missing-testids=\"{args.allow_missing_testids}\"")
        print("   Logged to OVERRIDE-DEBT critical. Re-run /vg:blueprint to clear.")
        # Caller (blueprint orchestrator) writes the debt entry
        return 0

    if args.severity == "warn":
        print("\nSeverity: warn (per CLI flag). Continuing.")
        print("Fix during /vg:build by adding <test_ids> blocks to PLAN.md tasks.")
        return 0

    print("\nSeverity: block. /vg:blueprint will not advance to build.")
    print("Fix:")
    print("  1. Edit PLAN.md, add <test_ids> blocks per planner Rule 10")
    print("  2. Re-run /vg:blueprint <phase> --from=2c")
    print("  3. Or override: /vg:blueprint <phase> --allow-missing-testids=\"<reason>\"")
    return 1


if __name__ == "__main__":
    sys.exit(main())
