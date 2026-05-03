#!/usr/bin/env python3
"""
distribution-check.py — VG distribution integrity check.

OHOK v2 Day 6 finish — addresses Codex audit missed gap #4 (distribution
integrity). Prior state: scripts + validators exist in `.claude/scripts/`,
`vgflow-repo/scripts/`, and deployed `~/.codex/skills/`. No guard detects
drift — users could edit their local `.claude/scripts/validators/commit-
attribution.py` and silently weaken enforcement.

Strategy:
1. Build manifest — scan canonical script/validator/hook paths, record
   sha256 of each file. Optionally diff against shipped manifest.
2. Verify — compare current on-disk hashes vs `.claude/.distribution-
   manifest.json` (committed baseline). Drift → WARN or BLOCK.
3. `--generate` rebuilds manifest (intended for maintainers post-sync;
   CI enforces no drift by running `--verify` on PR).

Exit codes:
  0 — manifest matches OR generating mode
  1 — drift detected in verify mode
  2 — script error / missing manifest

Usage:
  python distribution-check.py --verify        # compare vs baseline
  python distribution-check.py --generate      # rewrite baseline (maintainer)
  python distribution-check.py --verify --strict   # drift = BLOCK (CI mode)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
MANIFEST_PATH = REPO_ROOT / ".claude" / ".distribution-manifest.json"

# Paths tracked in manifest — core enforcement files whose drift would
# weaken the VG trust boundary. Hooks scripts + validators + orchestrator
# core. Commands/.md are LLM-facing prose (reviewer-critical but not
# trust-boundary); skip from manifest to reduce noise — users will and
# SHOULD edit .md as workflow evolves.
TRACKED_PATHS = [
    ".claude/scripts/vg-orchestrator/__main__.py",
    ".claude/scripts/vg-orchestrator/db.py",
    ".claude/scripts/vg-orchestrator/contracts.py",
    ".claude/scripts/vg-orchestrator/state.py",
    ".claude/scripts/vg-orchestrator/evidence.py",
    ".claude/scripts/vg-verify-claim.py",
    ".claude/scripts/vg-entry-hook.py",
    ".claude/scripts/vg-wired-check.py",
    ".claude/scripts/vg-ohok-metrics.py",
    ".claude/scripts/vg-build-crossai-loop.py",
    ".claude/scripts/rationalization-guard.sh",
    ".claude/scripts/bootstrap-loader.py",
    ".claude/scripts/bootstrap-test-runner.py",
    ".claude/scripts/override-revalidate.py",
    ".claude/scripts/validators/_common.py",
]
# Plus every *.py under validators/ — dynamic
VALIDATORS_GLOB = ".claude/scripts/validators/*.py"


def sha256_file(path: Path) -> str:
    """Return hex sha256 of file content. Raises FileNotFoundError if missing."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_current_manifest() -> dict[str, str]:
    """Scan tracked paths + validator glob, return {rel_path: sha256}."""
    manifest: dict[str, str] = {}
    for rel in TRACKED_PATHS:
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        manifest[rel] = sha256_file(p)

    # Auto-include every validator .py
    for p in sorted(REPO_ROOT.glob(VALIDATORS_GLOB)):
        if p.name == "_common.py":
            continue  # already tracked above
        rel = p.relative_to(REPO_ROOT).as_posix()
        manifest[rel] = sha256_file(p)

    return manifest


def load_baseline() -> dict[str, str] | None:
    """Load .distribution-manifest.json, return None if missing."""
    if not MANIFEST_PATH.exists():
        return None
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return data.get("files", {}) if isinstance(data, dict) else None
    except Exception:
        return None


def cmd_generate() -> int:
    """Rewrite baseline manifest. Run after sync + before commit."""
    current = build_current_manifest()
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat() + "Z",
        "file_count": len(current),
        "files": dict(sorted(current.items())),
    }
    MANIFEST_PATH.write_text(
        json.dumps(data, indent=2, sort_keys=False), encoding="utf-8",
    )
    print(f"✓ Generated manifest with {len(current)} entries → {MANIFEST_PATH}")
    return 0


def cmd_verify(strict: bool) -> int:
    """Compare current vs baseline. Drift detection.

    Categories:
      ADDED   — file in current, not in baseline
      REMOVED — file in baseline, not on disk
      CHANGED — both exist, hash differs
    """
    baseline = load_baseline()
    if baseline is None:
        print(f"\033[38;5;208mBaseline manifest missing at {MANIFEST_PATH}.\033[0m")
        print("   Run: python distribution-check.py --generate")
        return 2

    current = build_current_manifest()

    added = sorted(set(current) - set(baseline))
    removed = sorted(set(baseline) - set(current))
    changed = sorted(
        rel for rel in set(current) & set(baseline)
        if current[rel] != baseline[rel]
    )

    total_drift = len(added) + len(removed) + len(changed)
    if total_drift == 0:
        print(f"✓ Distribution integrity OK — {len(current)} files match baseline.")
        return 0

    print(f"\033[33mDistribution drift detected: {total_drift} item(s).\033[0m")
    for rel in added:
        print(f"  + ADDED    {rel}")
    for rel in removed:
        print(f"  - REMOVED  {rel}")
    for rel in changed:
        base_h = baseline[rel][:12]
        cur_h = current[rel][:12]
        print(f"  ~ CHANGED  {rel}  {base_h}… → {cur_h}…")

    print()
    print("Next steps:")
    print("  - If edits are intentional: python distribution-check.py --generate")
    print("    + commit the updated .distribution-manifest.json")
    print("  - If unexpected: audit the diff before proceeding (potential tampering)")

    return 1 if strict else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify", action="store_true",
                      help="compare vs baseline manifest")
    mode.add_argument("--generate", action="store_true",
                      help="rewrite baseline manifest")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any drift (CI mode)")
    args = ap.parse_args()

    if args.generate:
        return cmd_generate()
    return cmd_verify(strict=args.strict)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\033[38;5;208mdistribution-check crashed: {e}\033[0m", file=sys.stderr)
        sys.exit(2)
