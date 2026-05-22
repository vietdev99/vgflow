#!/usr/bin/env python3
"""verify-api-contract-filenames.py — B98 v4.69.1 (issue #204).

Purpose
-------
Block API-CONTRACTS/ filenames containing colon (:) or other Windows-reserved
chars. Windows git refuses checkout/pull of files containing `: < > " | ? *`
under `core.protectNTFS=true` (default since git 2.21).

Bug class
---------
vg-blueprint-contracts subagent writes per-endpoint markdown files like:
  get-api-vphase-{id}:id-pdf.md
  post-api-vphase-{id}:id-payments-:payment_id-reverse.md

`:` from path params (`:id`, `:payment_id`) leaks into filename. macOS/Linux
silently accept + push upstream. Windows clone fails with:

  error: invalid path '.vg/phases/.../get-api-vphase-{id}:id.md'

Spec in `agents/vg-blueprint-contracts/SKILL.md:76-77` says strip path params:
  `POST /api/v1/sites/:id` → `post-api-v1-sites-id`

But implementation can preserve the colon when path templates use `{id}` vs
`:id` mixed, or when slugification regex is wrong.

Fix
---
Block filenames containing reserved chars. Provide `--fix` flag to rename
each violator (colon → hyphen) in-place via `git mv` (preserves history) or
plain `os.rename` fallback.

Exit codes
----------
  0 - PASS (no offending filenames)
  1 - FAIL (offenders found, no --fix)
  0 - PASS with `--fix` after renames succeed
  2 - Internal error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


# Windows-reserved chars in NTFS (and git protectNTFS): `: < > " | ? *`
# Forward slash `/` is path separator so not a filename char by definition.
# Backslash `\` similarly path-sep on Windows. NULL also reserved but
# unlikely in markdown filenames so skipped.
RESERVED_RE = re.compile(r"[:<>\"|?*]")


def find_offenders(repo_root: Path) -> list[dict]:
    """Locate offending filenames under any `API-CONTRACTS/` directory.

    Returns list of {path, suggested_rename, reserved_chars} dicts.
    """
    offenders: list[dict] = []
    for d in repo_root.rglob("API-CONTRACTS"):
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if not f.is_file():
                continue
            reserved = sorted(set(RESERVED_RE.findall(f.name)))
            if not reserved:
                continue
            # Suggest rename: replace each reserved char with hyphen,
            # collapse double-hyphens, strip trailing hyphens before ext.
            stem = f.stem
            suffix = f.suffix
            new_stem = RESERVED_RE.sub("-", stem)
            new_stem = re.sub(r"-+", "-", new_stem).rstrip("-")
            new_name = new_stem + suffix
            offenders.append({
                "path": str(f.relative_to(repo_root)),
                "filename": f.name,
                "suggested_rename": new_name,
                "reserved_chars": reserved,
            })
    return offenders


def apply_renames(repo_root: Path, offenders: list[dict]) -> dict:
    """Rename each offender. Prefer `git mv` (preserves history) → fallback to os.rename."""
    use_git = shutil.which("git") is not None and (repo_root / ".git").exists()
    succeeded: list[dict] = []
    failed: list[dict] = []
    for entry in offenders:
        old_path = repo_root / entry["path"]
        new_path = old_path.parent / entry["suggested_rename"]
        if new_path.exists():
            failed.append({**entry, "reason": "target exists"})
            continue
        try:
            if use_git:
                # git mv handles history + index in one op
                subprocess.run(
                    ["git", "mv", str(old_path), str(new_path)],
                    check=True, capture_output=True, text=True,
                    cwd=str(repo_root),
                )
            else:
                os.rename(old_path, new_path)
            succeeded.append({**entry, "renamed_to": str(new_path.relative_to(repo_root))})
        except (subprocess.CalledProcessError, OSError) as exc:
            failed.append({**entry, "reason": str(exc)})
    return {"renamed": succeeded, "failed": failed}


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="verify-api-contract-filenames",
        description=(
            "B98 v4.69.1 (issue #204) — block API-CONTRACTS/ filenames with "
            "Windows-reserved chars (colon, etc.). Prevents Windows-side "
            "git clone failures under core.protectNTFS=true."
        ),
    )
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--fix", action="store_true",
                    help="Rename offenders in-place (git mv preferred, os.rename fallback).")
    ap.add_argument("--severity", choices=("warn", "block"), default="block",
                    help="block (default) = exit 1 on offenders; warn = exit 0")
    ap.add_argument("--json", dest="json_out", action="store_true", default=True)
    ap.add_argument("--no-json", dest="json_out", action="store_false")
    args = ap.parse_args()
    try:
        repo = Path(args.repo_root).resolve()
        offenders = find_offenders(repo)
        result: dict = {
            "scanned_dirs": sum(1 for _ in repo.rglob("API-CONTRACTS")),
            "offender_count": len(offenders),
            "offenders": offenders,
            "severity": args.severity,
            "status": "PASS" if not offenders else "FAIL",
        }
        if args.fix and offenders:
            result["fix_applied"] = apply_renames(repo, offenders)
            # Re-scan to confirm
            remaining = find_offenders(repo)
            result["remaining_offender_count"] = len(remaining)
            result["status"] = "PASS" if not remaining else "PARTIAL"
        if args.json_out:
            print(json.dumps(result, indent=2))
        else:
            print(f"verify-api-contract-filenames — {result['status']}")
            print(f"  offenders: {result['offender_count']}")
            for off in offenders[:10]:
                print(f"    - {off['path']} → {off['suggested_rename']}")
            if args.fix and "fix_applied" in result:
                print(f"  renamed: {len(result['fix_applied']['renamed'])}")
                print(f"  failed:  {len(result['fix_applied']['failed'])}")
        if result["status"] == "PASS":
            return 0
        if args.severity == "warn":
            return 0
        return 1
    except Exception as exc:
        print(f"verify-api-contract-filenames: internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
