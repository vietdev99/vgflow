#!/usr/bin/env python3
"""
Install VG Claude Code hooks into project-local settings.

Project-local is preferred over global because:
  - Enforcement travels with the repo (new clone → hooks active)
  - CI/other engineers inherit the same gates
  - No cross-project pollution on the host machine

Usage:
    python .claude/scripts/vg-hooks-install.py [--check] [--global]

    --check    Dry-run: report what would change, exit 1 if changes needed
    --global   Install to ~/.claude/settings.json instead (fallback)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(os.getcwd()).resolve()


HOOK_ENTRY = {
    "Stop": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": (
                        "python "
                        "${CLAUDE_PROJECT_DIR}/.claude/scripts/vg-verify-claim.py"
                    ),
                    "comment": (
                        "VG runtime-contract verifier. Reads last /vg:* command's "
                        "runtime_contract frontmatter + checks side-effect evidence. "
                        "Exits 2 if missing → forces Claude to continue vs claim-done."
                    ),
                }
            ]
        }
    ],
    "PostToolUse": [
        {
            "matcher": "Edit|Write|MultiEdit|NotebookEdit",
            "hooks": [
                {
                    "type": "command",
                    "command": (
                        "python "
                        "${CLAUDE_PROJECT_DIR}/.claude/scripts/vg-edit-warn.py"
                    ),
                    "comment": (
                        "VG skill-edit reload-required warning. If Claude edits a "
                        "file under .claude/commands/vg/ or .claude/skills/vg-*/, "
                        "injects warning that current session uses cached content "
                        "— edits apply next session only. Prevents 'I wired it but "
                        "it doesn't fire' 3-round confusion pattern."
                    ),
                }
            ]
        }
    ],
}


def merge_hooks(existing: dict, new_hooks: dict) -> tuple[dict, list[str]]:
    """Idempotent merge. Appends VG hook to existing events; skips if already present.
    Returns (updated_settings, changelog).
    """
    changelog = []
    existing.setdefault("hooks", {})

    # Match any VG-owned hook script name; allows adding more hooks later.
    VG_SCRIPTS = ("vg-verify-claim", "vg-edit-warn", "vg-hooks-selftest")

    for event, new_matchers in new_hooks.items():
        existing["hooks"].setdefault(event, [])
        for new_matcher in new_matchers:
            # Identify the VG script this matcher wants to install
            vg_command = None
            vg_script_name = None
            for h in new_matcher.get("hooks", []):
                cmd = h.get("command", "")
                for name in VG_SCRIPTS:
                    if name in cmd:
                        vg_command = cmd
                        vg_script_name = name
                        break
                if vg_command:
                    break

            already_present = False
            for existing_matcher in existing["hooks"][event]:
                for h in existing_matcher.get("hooks", []):
                    existing_cmd = h.get("command", "")
                    # Match by script name (command strings may differ in whitespace)
                    if vg_script_name and vg_script_name in existing_cmd:
                        already_present = True
                        break
                if already_present:
                    break

            if already_present:
                changelog.append(f"  = {event}: VG {vg_script_name} already installed")
                continue

            existing["hooks"][event].append(new_matcher)
            changelog.append(f"  + {event}: added VG {vg_script_name} hook")

    return existing, changelog


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--global", dest="is_global", action="store_true")
    args = ap.parse_args()

    if args.is_global:
        settings_path = Path.home() / ".claude" / "settings.json"
        scope = "global"
    else:
        settings_path = REPO_ROOT / ".claude" / "settings.local.json"
        scope = "project-local"

    print(f"VG hooks installer — {scope}")
    print(f"  target: {settings_path}")

    # Load existing settings (or start from empty)
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"⛔ Cannot parse existing settings ({e}). Aborting to avoid clobber.")
            return 1
    else:
        existing = {}

    # Merge
    updated, changelog = merge_hooks(existing, HOOK_ENTRY)

    if not changelog or all("already installed" in c for c in changelog):
        print("✓ VG hooks already installed — no changes needed.")
        return 0

    print("Changes:")
    for line in changelog:
        print(line)

    if args.check:
        print("\n(--check dry-run; re-run without --check to apply)")
        return 1

    # Apply
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\n✓ Installed. Hooks active on next Claude Code session start.")
    print(f"  Verify log: .vg/hook-verifier.log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
