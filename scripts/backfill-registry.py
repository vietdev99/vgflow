#!/usr/bin/env python3
"""
backfill-registry.py — v2.5.2.1 Fix 2.

Closes CrossAI round 3 consensus finding (Codex + Claude major):
  Phase S registry catalogs only 24 of ~60 validators. `verify-validator-drift`
  can only surface drift on cataloged entries — ~36 legacy validators stay
  silently unobservable.

This script auto-discovers every `.claude/scripts/validators/*.py` (excluding
`_common.py`, `_i18n.py`, and the registry script itself), reads each
docstring first line, and appends a `registry.yaml` entry.

Behavior:
  - Idempotent: existing entries preserved; only NEW validators appended
  - Placeholder fields for uncatalogued: `added_in: pre-v2.5.2`,
    `severity: warn` (safe default), `domain: uncategorized` (force reviewer
    to classify), `runtime_target_ms: 5000` (generous), `phases_active: [all]`
  - Description from docstring first line (max 120 chars)
  - --dry-run prints what would be added without writing
  - --apply actually commits changes

Exit codes:
  0 = all validators catalogued (after apply) OR dry-run clean
  1 = drift detected + --dry-run (caller should re-run with --apply)
  2 = config / file error
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATORS_DIR = REPO_ROOT / ".claude" / "scripts" / "validators"
REGISTRY_PATH = VALIDATORS_DIR / "registry.yaml"

# Files to skip when scanning validators dir
SKIP_NAMES = {"_common.py", "_i18n.py", "registry.yaml", "backfill-registry.py"}


def _extract_docstring_first_line(py_path: Path) -> str | None:
    """Return the first non-empty line of the module docstring, or None."""
    try:
        text = py_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    # Find the first triple-quoted string
    m = re.search(r'^\s*"""(.*?)"""', text, re.DOTALL | re.MULTILINE)
    if not m:
        m = re.search(r"^\s*'''(.*?)'''", text, re.DOTALL | re.MULTILINE)
    if not m:
        return None

    body = m.group(1).strip()
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return None


def _file_to_id(py_path: Path) -> str:
    """Map file name → registry id by stripping common action prefixes."""
    stem = py_path.stem
    for prefix in ("verify-", "validate-", "evaluate-"):
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return stem


def _load_registry_ids() -> set[str]:
    """Read registry.yaml and return the set of cataloged ids."""
    if not REGISTRY_PATH.exists():
        return set()
    text = REGISTRY_PATH.read_text(encoding="utf-8")
    ids = set()
    for line in text.splitlines():
        m = re.match(r"\s*-\s*id:\s*(\S+)", line)
        if m:
            ids.add(m.group(1).strip().strip("'\""))
    return ids


def _discover_on_disk() -> list[Path]:
    return sorted(
        p for p in VALIDATORS_DIR.glob("*.py")
        if p.name not in SKIP_NAMES and not p.name.startswith("_")
    )


def _format_entry(rid: str, file_path: Path, description: str) -> str:
    """Build a YAML entry block for a validator."""
    rel = file_path.relative_to(REPO_ROOT).as_posix()
    # Escape single quotes in description to keep YAML safe
    desc_safe = description.replace("'", "''").strip()
    if not desc_safe:
        desc_safe = "TODO — legacy validator, docstring missing. Fill in."
    return (
        f"\n  - id: {rid}\n"
        f"    path: {rel}\n"
        f"    severity: warn\n"
        f"    phases_active: [all]\n"
        f"    domain: uncategorized\n"
        f"    runtime_target_ms: 5000\n"
        f"    added_in: pre-v2.5.2\n"
        f"    description: '{desc_safe}'\n"
    )


def _append_entries(new_blocks: list[str]) -> None:
    if not new_blocks:
        return
    existing = REGISTRY_PATH.read_text(encoding="utf-8")
    # Drop trailing pre-v2.5.2 comment block if present so new entries land
    # above it cleanly
    marker = "  # ──── Pre-v2.5.2 validators"
    if marker in existing:
        existing, tail = existing.split(marker, 1)
        existing = existing.rstrip() + "\n"
        # We replace the old comment block entirely — new entries
        # make the placeholder comment obsolete
    else:
        existing = existing.rstrip() + "\n"

    header = (
        "\n  # ──── Backfilled v2.5.2.1 (pre-v2.5.2 legacy validators) ────\n"
        "  # Entries below were auto-discovered + need per-entry review\n"
        "  # (domain, severity, phases_active may need tightening).\n"
    )
    payload = header + "".join(new_blocks)
    REGISTRY_PATH.write_text(existing + payload, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="write changes to registry.yaml (default: dry-run)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not REGISTRY_PATH.exists():
        print(f"⛔ registry.yaml not found at {REGISTRY_PATH}",
              file=sys.stderr)
        return 2

    registered = _load_registry_ids()
    on_disk = _discover_on_disk()

    missing_entries = []
    for path in on_disk:
        rid = _file_to_id(path)
        if rid in registered:
            continue
        desc = _extract_docstring_first_line(path) or ""
        missing_entries.append((rid, path, desc))

    if not missing_entries:
        if not args.quiet:
            print(f"✓ All {len(on_disk)} validators cataloged in registry.yaml "
                  f"({len(registered)} existing entries)")
        return 0

    if args.apply:
        blocks = [_format_entry(rid, p, d) for rid, p, d in missing_entries]
        _append_entries(blocks)
        print(f"✓ Appended {len(missing_entries)} validator entries to "
              f"{REGISTRY_PATH.relative_to(REPO_ROOT)}")
        for rid, _p, d in missing_entries:
            print(f"  + {rid}: {d[:80]}")
        return 0

    # Dry-run
    print(f"⚠ Registry drift: {len(missing_entries)} validator(s) on disk "
          f"but not cataloged.\n")
    for rid, p, d in missing_entries:
        print(f"  - {rid}")
        print(f"      path: {p.relative_to(REPO_ROOT).as_posix()}")
        print(f"      description: {d[:80] if d else '(no docstring)'}")
    print(f"\nRun with --apply to append placeholder entries.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
