#!/usr/bin/env python3
"""
validator-registry.py — Phase S of v2.5.2 hardening.

CLI for managing .claude/scripts/validators/registry.yaml.

Commands:
  list                 — print catalog (all or filter by --domain / --severity)
  describe <id>        — show full entry for one validator
  missing              — find validators on disk not in registry
  orphans              — find registry entries with no matching file
  disable <id>         --reason TXT [--until YYYY-MM-DD]  — mark disabled
  enable <id>          — clear disabled flag
  validate             — schema check on registry YAML itself

All commands support --json for machine output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import os as _os


def _repo_root() -> Path:
    env = _os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env).resolve()
    # Marker-walk so this resolves correctly whether the script is invoked
    # from canonical (`scripts/validator-registry.py`, depth 2) or install
    # target (`.claude/scripts/validator-registry.py`, depth 3). Previous
    # implementation used `parents[2]` which was correct only for the
    # install-target depth and walked one level too far when called from
    # canonical — `validate` would silently see 0 entries because the
    # registry path resolved outside the repo.
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "VERSION").exists() and (parent / ".git").exists():
            return parent
    return here.parents[2]  # fallback to historical behavior


def _registry_path() -> Path:
    return _repo_root() / ".claude" / "scripts" / "validators" / "registry.yaml"


def _load_registry() -> dict:
    path = _registry_path()
    if not path.exists():
        return {"validators": []}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml
        return yaml.safe_load(text) or {"validators": []}
    except ImportError:
        return _yaml_minimal(text)


def _yaml_minimal(text: str) -> dict:
    """Minimal parser — handles registry.yaml structure specifically."""
    entries: list[dict] = []
    current: dict = {}
    in_list = False

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)

        if stripped == "validators:" and indent == 0:
            in_list = True
            continue
        if not in_list:
            continue

        if stripped.startswith("- "):
            if current:
                entries.append(current)
            current = {}
            rest = stripped[2:]
            if ":" in rest:
                k, _, v = rest.partition(":")
                current[k.strip()] = _parse_value(v.strip())
            continue

        if ":" in stripped and current is not None:
            k, _, v = stripped.partition(":")
            current[k.strip()] = _parse_value(v.strip())

    if current:
        entries.append(current)
    return {"validators": entries}


def _parse_value(v: str) -> object:
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(x.strip()) for x in inner.split(",")]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    if v.isdigit():
        return int(v)
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    return v


def _strip_quotes(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def _save_registry(data: dict) -> None:
    try:
        import yaml
        _registry_path().write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    except ImportError:
        print("\033[38;5;208mPyYAML required to save registry. Install: pip install PyYAML\033[0m",
              file=sys.stderr)
        sys.exit(2)


def _find_on_disk() -> set[str]:
    """IDs derived from filenames in scripts/validators/."""
    validators_dir = _repo_root() / ".claude" / "scripts" / "validators"
    if not validators_dir.exists():
        return set()

    ids = set()
    for p in validators_dir.glob("*.py"):
        name = p.stem
        # Strip common action prefixes to match registry id convention
        for prefix in ("verify-", "validate-", "evaluate-"):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        if name.startswith("_"):
            continue  # skip _common.py, _i18n.py etc.
        ids.add(name)
    return ids


def cmd_list(args, reg: dict) -> int:
    entries = reg.get("validators", [])
    if args.domain:
        entries = [e for e in entries if e.get("domain") == args.domain]
    if args.severity:
        entries = [e for e in entries if e.get("severity") == args.severity]

    if args.json:
        print(json.dumps({"count": len(entries), "validators": entries}, indent=2))
    else:
        print(f"{len(entries)} validator(s)\n")
        for e in entries:
            marker = " [DISABLED]" if e.get("disabled") else ""
            print(f"  [{e.get('severity','?'):<8}] {e.get('id','?'):<30} "
                  f"{e.get('domain','?'):<12} — {e.get('description','')[:60]}{marker}")
    return 0


def cmd_describe(args, reg: dict) -> int:
    entry = next((e for e in reg["validators"] if e.get("id") == args.id), None)
    if not entry:
        print(f"\033[38;5;208mvalidator id not in registry: {args.id}\033[0m", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(entry, indent=2))
    else:
        for k, v in entry.items():
            print(f"  {k}: {v}")
    return 0


def cmd_missing(args, reg: dict) -> int:
    registered = {e.get("id") for e in reg["validators"]}
    on_disk = _find_on_disk()
    missing = sorted(on_disk - registered)

    if args.json:
        print(json.dumps({"missing_from_registry": missing}, indent=2))
    else:
        if missing:
            print(f"\033[33m{len(missing)} validator(s) on disk but not in registry:\033[0m\n")
            for m in missing:
                print(f"  - {m}")
        else:
            print("✓ All validators on disk are in registry")
    return 0 if not missing else 1


def cmd_orphans(args, reg: dict) -> int:
    registered = {e.get("id") for e in reg["validators"]}
    on_disk = _find_on_disk()
    orphans = sorted(registered - on_disk)

    if args.json:
        print(json.dumps({"orphan_registry_entries": orphans}, indent=2))
    else:
        if orphans:
            print(f"\033[33m{len(orphans)} registry entry(ies) with no file on disk:\033[0m\n")
            for o in orphans:
                print(f"  - {o}")
        else:
            print("✓ All registry entries have matching files")
    return 0 if not orphans else 1


def cmd_disable(args, reg: dict) -> int:
    entry = next((e for e in reg["validators"] if e.get("id") == args.id), None)
    if not entry:
        print(f"\033[38;5;208mvalidator id not in registry: {args.id}\033[0m", file=sys.stderr)
        return 1
    entry["disabled"] = True
    entry["disabled_reason"] = args.reason
    if args.until:
        entry["disabled_until"] = args.until
    _save_registry(reg)
    print(f"✓ Disabled {args.id} — reason: {args.reason}")
    return 0


def cmd_enable(args, reg: dict) -> int:
    entry = next((e for e in reg["validators"] if e.get("id") == args.id), None)
    if not entry:
        print(f"\033[38;5;208mvalidator id not in registry: {args.id}\033[0m", file=sys.stderr)
        return 1
    for k in ("disabled", "disabled_reason", "disabled_until"):
        entry.pop(k, None)
    _save_registry(reg)
    print(f"✓ Enabled {args.id}")
    return 0


REQUIRED_FIELDS = {"id", "path", "severity", "domain", "description", "added_in"}
VALID_SEVERITIES = {"block", "warn", "advisory"}


def cmd_validate(args, reg: dict) -> int:
    errors = []
    ids_seen = set()

    for i, e in enumerate(reg.get("validators", [])):
        prefix = f"entry[{i}] (id={e.get('id','?')})"
        missing = REQUIRED_FIELDS - set(e.keys())
        if missing:
            errors.append(f"{prefix}: missing fields {sorted(missing)}")
        sev = e.get("severity")
        if sev and sev not in VALID_SEVERITIES:
            errors.append(f"{prefix}: invalid severity {sev!r}, must be {sorted(VALID_SEVERITIES)}")
        rid = e.get("id")
        if rid in ids_seen:
            errors.append(f"{prefix}: duplicate id")
        ids_seen.add(rid)

    if args.json:
        print(json.dumps({"errors": errors, "valid": not errors}, indent=2))
    else:
        if errors:
            print(f"\033[38;5;208mRegistry schema {len(errors)} error(s):\033[0m")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"✓ Registry schema valid — {len(reg['validators'])} entries")
    return 0 if not errors else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="machine output")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--domain")
    p_list.add_argument("--severity")

    p_desc = sub.add_parser("describe")
    p_desc.add_argument("id")

    sub.add_parser("missing")
    sub.add_parser("orphans")

    p_dis = sub.add_parser("disable")
    p_dis.add_argument("id")
    p_dis.add_argument("--reason", required=True)
    p_dis.add_argument("--until")

    p_en = sub.add_parser("enable")
    p_en.add_argument("id")

    sub.add_parser("validate")

    args = ap.parse_args()
    reg = _load_registry()

    dispatch = {
        "list": cmd_list, "describe": cmd_describe,
        "missing": cmd_missing, "orphans": cmd_orphans,
        "disable": cmd_disable, "enable": cmd_enable,
        "validate": cmd_validate,
    }
    return dispatch[args.cmd](args, reg)


if __name__ == "__main__":
    sys.exit(main())
