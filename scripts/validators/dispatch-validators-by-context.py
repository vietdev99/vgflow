#!/usr/bin/env python3
"""dispatch-validators-by-context.py — context-aware validator dispatcher.

Reads .claude/scripts/validators/dispatch-manifest.json and returns the list of
validators applicable for a (command, step, profile, platform, env) tuple.

Replaces hardcoded COMMAND_VALIDATORS in vg-orchestrator/__main__.py: new
validators register in the manifest only, no orchestrator code edit needed.

Usage
-----
    # List validators for a build run on a web-fullstack feature phase
    python3 dispatch-validators-by-context.py \\
        --command vg:build --profile feature --platform web-fullstack --env local

    # Audit: which on-disk validators have no manifest entry?
    python3 dispatch-validators-by-context.py --audit

    # Show one validator's full record
    python3 dispatch-validators-by-context.py --show blueprint-completeness

Output (default mode)
---------------------
Comma-separated validator names, sorted, on stdout. Empty string if none match.
Exit 0 always (no error states); diagnostics on stderr.

Filter semantics
----------------
- '*' in any context list matches everything for that key
- A validator with `triggers.commands` list NOT containing the given command is
  excluded (no '*' default at command level — explicit only)
- Steps default to '*' (validator applies to all steps of the command) unless
  declared otherwise
- profile / platform / env: missing CLI arg → don't filter on that key
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = THIS_DIR / "dispatch-manifest.json"


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        sys.stderr.write(f"⛔ manifest not found: {MANIFEST_PATH}\n")
        return {"validators": {}}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"⛔ manifest JSON parse error: {exc}\n")
        return {"validators": {}}


def _matches(value: str | None, allowed: list[str]) -> bool:
    """Return True when the CLI value matches the allowed list.

    - allowed=['*'] always matches
    - value=None means "don't filter on this dimension" → matches
    """
    if value is None:
        return True
    if "*" in allowed:
        return True
    return value in allowed


def dispatch(
    command: str,
    step: str | None = None,
    profile: str | None = None,
    platform: str | None = None,
    env: str | None = None,
    severity_filter: str | None = None,
) -> list[dict]:
    """Return list of validator records matching the context tuple."""
    manifest = load_manifest()
    chosen: list[dict] = []
    for name, spec in manifest.get("validators", {}).items():
        triggers = spec.get("triggers", {})
        contexts = spec.get("contexts", {})

        cmds = triggers.get("commands", [])
        if command not in cmds and "*" not in cmds:
            continue

        steps = triggers.get("steps", ["*"])
        if not _matches(step, steps):
            continue

        if not _matches(profile, contexts.get("profiles", ["*"])):
            continue
        if not _matches(platform, contexts.get("platforms", ["*"])):
            continue
        if not _matches(env, contexts.get("envs", ["*"])):
            continue

        if severity_filter and spec.get("severity") != severity_filter:
            continue

        chosen.append(
            {
                "name": name,
                "severity": spec.get("severity", "WARN"),
                "unquarantinable": spec.get("unquarantinable", False),
                "description": spec.get("description", ""),
            }
        )
    chosen.sort(key=lambda v: v["name"])
    return chosen


def audit_unmapped() -> list[str]:
    """List validators that exist on disk but have no manifest entry."""
    manifest = load_manifest()
    declared = set(manifest.get("validators", {}).keys())
    on_disk = set()
    for path in THIS_DIR.glob("verify-*.py"):
        on_disk.add(path.stem)
    # Also include unprefixed validators (phase-exists, commit-attribution, etc.)
    # They live as scripts elsewhere — manifest catches them via name.
    extras = {
        "phase-exists",
        "commit-attribution",
        "context-structure",
        "plan-granularity",
        "task-goal-binding",
        "vg-design-coherence",
        "runtime-evidence",
        "override-debt-balance",
        "test-first",
        "build-crossai-required",
        "wave-verify-isolated",
        "review-skip-guard",
        "secrets-scan",
        "accessibility-scan",
        "i18n-coverage",
        "build-telemetry-surface",
        "goal-coverage",
        "deferred-evidence",
        "mutation-layers",
        "not-scanned-replay",
        "dast-scan-report",
        "event-reconciliation",
        "acceptance-reconciliation",
    }
    on_disk.update(extras)

    unmapped = sorted(on_disk - declared)
    return unmapped


def show_one(name: str) -> dict | None:
    manifest = load_manifest()
    return manifest.get("validators", {}).get(name)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--command", help="vg:scope | vg:blueprint | vg:build | vg:review | vg:test | vg:accept")
    p.add_argument("--step", help="Optional sub-step name")
    p.add_argument("--profile", help="feature | infra | hotfix | bugfix | migration | docs")
    p.add_argument(
        "--platform",
        help="web-fullstack | web-frontend-only | web-backend-only | mobile-rn | mobile-flutter | mobile-native | desktop-electron | desktop-tauri | cli-tool | library | server-setup | server-management",
    )
    p.add_argument("--env", help="local | sandbox | production")
    p.add_argument(
        "--severity",
        help="Filter to BLOCK / WARN / INFO only",
    )
    p.add_argument(
        "--format",
        choices=["csv", "json", "lines", "verbose"],
        default="csv",
        help="Output format (default: csv = comma-separated names)",
    )
    p.add_argument("--audit", action="store_true", help="List validators on disk without manifest entries")
    p.add_argument("--show", help="Show one validator's full manifest record")
    p.add_argument("--list-all", action="store_true", help="List every validator declared in the manifest")
    args = p.parse_args()

    if args.audit:
        unmapped = audit_unmapped()
        if not unmapped:
            print("✓ All on-disk validators are mapped in dispatch-manifest.json")
            return 0
        print(f"⚠ {len(unmapped)} validator(s) on disk without manifest entry:")
        for name in unmapped:
            print(f"  - {name}")
        print()
        print("Add entries to .claude/scripts/validators/dispatch-manifest.json to make them context-aware.")
        return 0

    if args.show:
        record = show_one(args.show)
        if not record:
            sys.stderr.write(f"⛔ no manifest entry for: {args.show}\n")
            return 1
        print(json.dumps({args.show: record}, indent=2))
        return 0

    if args.list_all:
        manifest = load_manifest()
        for name, spec in sorted(manifest.get("validators", {}).items()):
            print(
                f"{name:50s} {spec.get('severity', 'WARN'):6s} "
                f"{'UNQ' if spec.get('unquarantinable') else '   '} "
                f"{spec.get('description', '')[:80]}"
            )
        return 0

    if not args.command:
        sys.stderr.write("⛔ --command required (or --audit / --show / --list-all)\n")
        p.print_help(sys.stderr)
        return 1

    matches = dispatch(
        command=args.command,
        step=args.step,
        profile=args.profile,
        platform=args.platform,
        env=args.env,
        severity_filter=args.severity,
    )

    if args.format == "json":
        print(json.dumps(matches, indent=2))
    elif args.format == "verbose":
        for v in matches:
            unq = "UNQUARANTINABLE" if v["unquarantinable"] else "quarantinable"
            print(f"  {v['name']:50s} [{v['severity']}] [{unq}] {v['description']}")
        print(f"\nTotal: {len(matches)} validator(s)")
    elif args.format == "lines":
        for v in matches:
            print(v["name"])
    else:  # csv
        print(",".join(v["name"] for v in matches))

    return 0


if __name__ == "__main__":
    sys.exit(main())
