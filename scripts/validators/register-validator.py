#!/usr/bin/env python3
"""register-validator.py — add a new validator to dispatch-manifest.json.

Saves the manual JSON-edit step when a new validator file lands. Reads CLI
flags + writes a new entry into the manifest, then runs `--audit` to confirm
the file exists on disk and the manifest now resolves.

Usage
-----
    python3 register-validator.py \\
        --name verify-rate-limit-coverage \\
        --commands vg:build,vg:test \\
        --steps run_complete \\
        --profiles feature \\
        --platforms web-fullstack,web-backend-only \\
        --envs '*' \\
        --severity BLOCK \\
        --unquarantinable \\
        --description "Mutation endpoints declare rate_limit + form throttle present"

The script will:
  1. Verify .claude/scripts/validators/<name>.py exists (else error)
  2. Confirm <name> not already in manifest (else error unless --update)
  3. Insert new entry alphabetically into validators dict
  4. Re-write manifest with stable indent + key order preserved
  5. Run audit + report any remaining unmapped

After registration, orchestrator must still add the validator to
COMMAND_VALIDATORS (for execution dispatch) and optionally UNQUARANTINABLE
(for unkillable status). The manifest entry alone makes the validator
discoverable but doesn't auto-wire orchestrator calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = THIS_DIR / "dispatch-manifest.json"

VALID_COMMANDS = {"vg:scope", "vg:blueprint", "vg:build", "vg:review", "vg:test", "vg:accept"}
VALID_PROFILES = {"feature", "infra", "hotfix", "bugfix", "migration", "docs", "*"}
VALID_PLATFORMS = {
    "web-fullstack", "web-frontend-only", "web-backend-only",
    "mobile-rn", "mobile-flutter", "mobile-native",
    "desktop-electron", "desktop-tauri",
    "cli-tool", "library",
    "server-setup", "server-management",
    "*",
}
VALID_ENVS = {"local", "sandbox", "production", "*"}
VALID_SEVERITY = {"BLOCK", "WARN", "INFO"}


def split_csv(value: str) -> list[str]:
    return [t.strip() for t in value.split(",") if t.strip()]


def validate_choices(values: list[str], allowed: set[str], label: str) -> None:
    bad = [v for v in values if v not in allowed]
    if bad:
        sys.stderr.write(f"\033[38;5;208minvalid {label} value(s): {bad}\033[0m\n")
        sys.stderr.write(f"   allowed: {sorted(allowed)}\n")
        sys.exit(1)


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        sys.stderr.write(f"\033[38;5;208mmanifest missing: {MANIFEST_PATH}\033[0m\n")
        sys.exit(1)
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def save_manifest(data: dict) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False)
    MANIFEST_PATH.write_text(text + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--name", required=True, help="Validator name = filename without .py (e.g. verify-rate-limit-coverage)")
    p.add_argument("--commands", required=True, help="Comma-separated command list (vg:build,vg:test)")
    p.add_argument("--steps", default="*", help="Comma-separated step names, or '*' for all (default: *)")
    p.add_argument("--profiles", default="*", help="Comma-separated phase profiles, or '*' (default: *)")
    p.add_argument("--platforms", default="*", help="Comma-separated platforms, or '*' (default: *)")
    p.add_argument("--envs", default="*", help="Comma-separated envs (local/sandbox/production), or '*' (default: *)")
    p.add_argument("--severity", choices=sorted(VALID_SEVERITY), required=True, help="BLOCK | WARN | INFO")
    p.add_argument("--unquarantinable", action="store_true", help="Validator cannot be quarantined after 3 fails (hard gates only)")
    p.add_argument("--description", required=True, help="One-line summary of what the validator checks")
    p.add_argument("--update", action="store_true", help="Allow overwriting existing entry")
    p.add_argument("--dry-run", action="store_true", help="Print would-be entry without saving")
    args = p.parse_args()

    name = args.name.strip()
    if not name:
        sys.stderr.write("\033[38;5;208m--name cannot be empty\033[0m\n")
        return 1

    validator_path = THIS_DIR / f"{name}.py"
    if not validator_path.exists():
        sys.stderr.write(f"\033[38;5;208mvalidator file does not exist: {validator_path}\033[0m\n")
        sys.stderr.write(f"   Create the validator first, then register it.\n")
        return 1

    commands = split_csv(args.commands)
    steps = split_csv(args.steps) or ["*"]
    profiles = split_csv(args.profiles) or ["*"]
    platforms = split_csv(args.platforms) or ["*"]
    envs = split_csv(args.envs) or ["*"]

    validate_choices(commands, VALID_COMMANDS, "command")
    validate_choices(profiles, VALID_PROFILES, "profile")
    validate_choices(platforms, VALID_PLATFORMS, "platform")
    validate_choices(envs, VALID_ENVS, "env")

    entry = {
        "triggers": {"commands": commands, "steps": steps},
        "contexts": {"profiles": profiles, "platforms": platforms, "envs": envs},
        "severity": args.severity,
        "unquarantinable": bool(args.unquarantinable),
        "description": args.description.strip(),
    }

    manifest = load_manifest()
    validators = manifest.setdefault("validators", {})
    if name in validators and not args.update:
        sys.stderr.write(f"⛔ validator '{name}' already registered. Use --update to overwrite.\n")
        sys.stderr.write(f"   Current entry:\n")
        sys.stderr.write(json.dumps(validators[name], indent=2) + "\n")
        return 1

    if args.dry_run:
        print("DRY-RUN — would write:")
        print(json.dumps({name: entry}, indent=2))
        return 0

    # Insert alphabetically among other keys (json.dumps preserves dict order)
    sorted_keys = sorted(set(list(validators.keys()) + [name]))
    rebuilt: dict[str, dict] = {}
    for k in sorted_keys:
        rebuilt[k] = entry if k == name else validators[k]
    manifest["validators"] = rebuilt

    save_manifest(manifest)
    print(f"✓ Registered: {name}")
    print(f"  commands={commands}  platforms={platforms}  severity={args.severity}  unquarantinable={args.unquarantinable}")
    print()
    print("Next steps:")
    print(f"  1. Add '{name}' to .claude/scripts/vg-orchestrator/__main__.py COMMAND_VALIDATORS[<command>] entry")
    if args.unquarantinable:
        print(f"  2. Add '{name}' to UNQUARANTINABLE allowlist in __main__.py")
    print(f"  3. Wire validator invocation in the relevant skill (.codex/skills/vg-*/SKILL.md or .claude/commands/vg/*.md)")
    print(f"  4. Test: python3 .claude/scripts/validators/{name}.py --help")
    print(f"  5. Verify dispatch: python3 dispatch-validators-by-context.py --command <cmd> --profile feature --platform <p>")

    return 0


if __name__ == "__main__":
    sys.exit(main())
