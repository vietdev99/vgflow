#!/usr/bin/env python3
"""
verify-bundle-size.py — Gate 10 for /vg:build mobile post-wave.

Locates built artifacts (*.ipa, *.apk, *.aab) under a search root and
compares size against budget from config.mobile.gates.bundle_size.

Over-budget bundles hurt install rates — especially in emerging markets
where cellular data + device storage are constrained. Catching this at
gate time forces a conscious trade-off, not silent drift.

USAGE
  python verify-bundle-size.py \
      --search-root . \
      [--ios-ipa-mb 100] [--android-apk-mb 50] [--android-aab-mb 80] \
      [--fail-action block|warn] [--lenient] [--json]

EXIT CODES
  0 ok
  1 fail — over budget AND fail-action=block AND not --lenient
  2 script error

PORTABILITY
  P1: all budgets from CLI; no hardcoded values.
  P2: pathlib globs; no shell-specific syntax.
  P3: no external tools.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_IPA_MB = 100
DEFAULT_APK_MB = 50
DEFAULT_AAB_MB = 80


def mb(bytes_: int) -> float:
    return round(bytes_ / (1024 * 1024), 2)


def find_artifacts(root: Path, extensions: list[str], ignore_dirs: set[str]) -> list[Path]:
    """Recursively find files with any of the given extensions, skipping
    noisy dirs like node_modules, Pods, build intermediate folders."""
    matches: list[Path] = []
    if not root.exists():
        return matches
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in extensions:
            continue
        # Skip if any parent matches ignore list
        parts_lower = {part.lower() for part in p.parts}
        if parts_lower & ignore_dirs:
            continue
        matches.append(p)
    return matches


def summarize(artifacts: list[Path]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for art in artifacts:
        try:
            size_b = art.stat().st_size
        except OSError:
            continue
        entries.append({
            "path": str(art),
            "extension": art.suffix.lower(),
            "size_bytes": size_b,
            "size_mb": mb(size_b),
        })
    # Largest first so report surfaces the worst offender
    entries.sort(key=lambda e: e["size_bytes"], reverse=True)
    return entries


BUDGET_BY_EXT = {
    ".ipa": "ios_ipa_mb",
    ".apk": "android_apk_mb",
    ".aab": "android_aab_mb",
}


def classify(entries: list[dict[str, Any]], budgets: dict[str, int]) -> list[dict[str, Any]]:
    out = []
    for e in entries:
        budget_key = BUDGET_BY_EXT.get(e["extension"])
        if not budget_key:
            e["verdict"] = "ok"
            e["reason"] = "no budget configured for this extension"
            out.append(e)
            continue
        budget_mb = budgets.get(budget_key)
        if budget_mb is None:
            e["verdict"] = "skipped"
            e["reason"] = f"budget '{budget_key}' disabled"
            out.append(e)
            continue
        e["budget_mb"] = budget_mb
        if e["size_mb"] > budget_mb:
            e["verdict"] = "over_budget"
            e["reason"] = f"{e['size_mb']} MB > {budget_mb} MB budget"
        else:
            e["verdict"] = "ok"
            e["reason"] = f"{e['size_mb']} MB ≤ {budget_mb} MB budget"
        out.append(e)
    return out


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
DEFAULT_IGNORE = {
    "node_modules", "pods", "build", "derived_data", "intermediates",
    ".gradle", ".dart_tool", "ios/pods", "android/build",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--search-root", default=".", help="Root directory to scan for built artifacts")
    ap.add_argument("--ios-ipa-mb", type=int, default=DEFAULT_IPA_MB, help="0 or negative disables iOS IPA check")
    ap.add_argument("--android-apk-mb", type=int, default=DEFAULT_APK_MB)
    ap.add_argument("--android-aab-mb", type=int, default=DEFAULT_AAB_MB)
    ap.add_argument("--fail-action", choices=("block", "warn"), default="block")
    ap.add_argument("--ignore-dir", action="append", default=[], help="Extra directory names to ignore (can repeat)")
    ap.add_argument("--lenient", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.search_root).resolve()
    if not root.exists():
        print(f"\033[38;5;208msearch-root does not exist: {root}\033[0m", file=sys.stderr)
        return 2

    ignore_dirs = {d.lower() for d in DEFAULT_IGNORE}
    ignore_dirs.update({d.lower() for d in args.ignore_dir})

    artifacts = find_artifacts(root, [".ipa", ".apk", ".aab"], ignore_dirs)
    entries = summarize(artifacts)

    budgets: dict[str, int] = {}
    if args.ios_ipa_mb > 0:
        budgets["ios_ipa_mb"] = args.ios_ipa_mb
    if args.android_apk_mb > 0:
        budgets["android_apk_mb"] = args.android_apk_mb
    if args.android_aab_mb > 0:
        budgets["android_aab_mb"] = args.android_aab_mb

    classified = classify(entries, budgets)

    over = [e for e in classified if e.get("verdict") == "over_budget"]

    report = {
        "search_root": str(root),
        "artifact_count": len(entries),
        "over_budget_count": len(over),
        "fail_action": args.fail_action,
        "budgets": budgets,
        "artifacts": classified,
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Bundle-size audit — root={root}")
        print(f"  Artifacts: {len(entries)}  Over-budget: {len(over)}")
        for e in classified[:10]:
            icon = {"ok": "✓", "over_budget": "✗", "skipped": "·"}.get(e.get("verdict"), "?")
            print(f"  {icon} {e['path']} ({e['size_mb']} MB)  {e['reason']}")

    if over and args.fail_action == "block" and not args.lenient:
        print("", file=sys.stderr)
        print(f"\033[38;5;208m{len(over)} bundle(s) exceed budget:\033[0m", file=sys.stderr)
        for e in over:
            print(f"   - {e['path']}: {e['size_mb']} MB > {e['budget_mb']} MB", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
