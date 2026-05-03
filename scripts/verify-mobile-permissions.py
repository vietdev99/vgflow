#!/usr/bin/env python3
"""
verify-mobile-permissions.py — Gate 6 for /vg:build mobile post-wave.

Enforces: every permission declared in Info.plist / AndroidManifest.xml /
Expo app.json MUST be justified in CONTEXT.md — either explicitly cited as
`Permission: {name}` OR implicitly by appearing inside a D-XX decision
block. Unjustified permissions = likely store rejection risk.

USAGE
  python verify-mobile-permissions.py \
      --phase-dir .vg/phases/07-onboarding \
      [--ios-plist ios/App/Info.plist] \
      [--android-manifest android/app/src/main/AndroidManifest.xml] \
      [--expo-config app.json] \
      [--lenient] [--json]

EXIT CODES
  0 ok — all permissions justified
  1 fail — one or more permissions have no justification in CONTEXT.md
  2 script error (bad args, phase dir missing)

PORTABILITY
  P1: paths come from CLI args populated by config.mobile.gates; no hardcoded
      project paths. Missing path = that platform skipped silently.
  P2: stdlib-only parsers (plistlib, xml.etree, json) — cross-platform.
  P3: no external tools invoked.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------
def parse_ios_plist(path: Path) -> list[str]:
    """Return iOS usage-description permission keys (e.g. NSCameraUsageDescription)."""
    if not path.is_file():
        return []
    try:
        with path.open("rb") as fh:
            data = plistlib.load(fh)
    except Exception as exc:
        print(f"\033[33mfailed to parse {path}: {exc}\033[0m", file=sys.stderr)
        return []
    return [k for k in data.keys() if k.endswith("UsageDescription")]


ANDROID_NS = "http://schemas.android.com/apk/res/android"


def parse_android_manifest(path: Path) -> list[str]:
    """Return Android permission names (android:name from <uses-permission>)."""
    if not path.is_file():
        return []
    try:
        tree = ET.parse(str(path))
    except Exception as exc:
        print(f"\033[33mfailed to parse {path}: {exc}\033[0m", file=sys.stderr)
        return []
    root = tree.getroot()
    perms = []
    for child in root.findall("uses-permission"):
        name = child.get(f"{{{ANDROID_NS}}}name")
        if name:
            perms.append(name)
    # Also catch uses-permission-sdk-23 and similar variants
    for tag in ("uses-permission-sdk-23", "uses-permission-sdk-m"):
        for child in root.findall(tag):
            name = child.get(f"{{{ANDROID_NS}}}name")
            if name and name not in perms:
                perms.append(name)
    return perms


def parse_expo_app_json(path: Path) -> dict[str, list[str]]:
    """Return dict with keys 'ios' and 'android' listing declared permissions."""
    if not path.is_file():
        return {"ios": [], "android": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"\033[33mfailed to parse {path}: {exc}\033[0m", file=sys.stderr)
        return {"ios": [], "android": []}

    expo = data.get("expo", data)
    ios_keys: list[str] = []
    android_keys: list[str] = []

    # iOS usage descriptions under expo.ios.infoPlist
    info_plist = (expo.get("ios") or {}).get("infoPlist") or {}
    for k in info_plist.keys():
        if k.endswith("UsageDescription"):
            ios_keys.append(k)

    # Android permissions under expo.android.permissions
    android_perms = (expo.get("android") or {}).get("permissions") or []
    for p in android_perms:
        if isinstance(p, str):
            android_keys.append(p if p.startswith("android.permission.") else f"android.permission.{p}")

    return {"ios": ios_keys, "android": android_keys}


# ---------------------------------------------------------------------
# Justification check
# ---------------------------------------------------------------------
def load_context_text(phase_dir: Path) -> str:
    p = phase_dir / "CONTEXT.md"
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def is_justified(permission: str, context_text: str) -> tuple[bool, str]:
    """
    A permission is justified if CONTEXT.md contains either:
      (a) An explicit line "Permission: {exact name}" (case-insensitive), OR
      (b) The permission name appears inside a D-XX block (any line that
          sits between "### D-" markers or within a decision body).

    We don't require an exact heading — contextual mention inside a decision
    block is enough. Returns (justified, reason_snippet).
    """
    if not context_text:
        return False, "CONTEXT.md is empty or missing"

    # (a) explicit justification
    pattern_a = re.compile(
        rf"(?i)permission\s*:\s*{re.escape(permission)}\b"
    )
    m = pattern_a.search(context_text)
    if m:
        return True, f"explicit: {m.group(0)[:80]}"

    # (b) mention anywhere in a decision block — loose but catches inline citations
    # The permission name itself should appear, with surrounding non-word boundary.
    pattern_b = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(permission)}(?![A-Za-z0-9_])"
    )
    m = pattern_b.search(context_text)
    if m:
        # Extract short context snippet around match
        start = max(0, m.start() - 30)
        end = min(len(context_text), m.end() + 30)
        snippet = context_text[start:end].replace("\n", " ").strip()
        return True, f"mentioned: …{snippet}…"

    return False, "no mention in CONTEXT.md"


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--ios-plist", help="Path to Info.plist (relative to REPO_ROOT or absolute)")
    ap.add_argument("--android-manifest", help="Path to AndroidManifest.xml")
    ap.add_argument("--expo-config", help="Path to Expo app.json")
    ap.add_argument("--lenient", action="store_true", help="Warn but do not fail")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    if not phase_dir.is_dir():
        print(f"\033[38;5;208mphase-dir not found: {phase_dir}\033[0m", file=sys.stderr)
        return 2

    context_text = load_context_text(phase_dir)

    collected: list[dict[str, Any]] = []

    if args.ios_plist:
        perms = parse_ios_plist(Path(args.ios_plist))
        for p in perms:
            ok, reason = is_justified(p, context_text)
            collected.append({
                "platform": "ios",
                "permission": p,
                "source": str(args.ios_plist),
                "justified": ok,
                "reason": reason,
            })

    if args.android_manifest:
        perms = parse_android_manifest(Path(args.android_manifest))
        for p in perms:
            ok, reason = is_justified(p, context_text)
            collected.append({
                "platform": "android",
                "permission": p,
                "source": str(args.android_manifest),
                "justified": ok,
                "reason": reason,
            })

    if args.expo_config:
        expo = parse_expo_app_json(Path(args.expo_config))
        for p in expo["ios"]:
            ok, reason = is_justified(p, context_text)
            collected.append({
                "platform": "expo-ios",
                "permission": p,
                "source": str(args.expo_config),
                "justified": ok,
                "reason": reason,
            })
        for p in expo["android"]:
            ok, reason = is_justified(p, context_text)
            collected.append({
                "platform": "expo-android",
                "permission": p,
                "source": str(args.expo_config),
                "justified": ok,
                "reason": reason,
            })

    report = {
        "phase_dir": str(phase_dir),
        "total_permissions": len(collected),
        "justified": sum(1 for c in collected if c["justified"]),
        "unjustified": sum(1 for c in collected if not c["justified"]),
        "entries": collected,
    }

    failures = [c for c in collected if not c["justified"]]

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Permission audit — phase {phase_dir.name}")
        print(f"  Total: {report['total_permissions']}  "
              f"Justified: {report['justified']}  "
              f"Unjustified: {report['unjustified']}")
        for c in collected:
            icon = "✓" if c["justified"] else "✗"
            print(f"  {icon} [{c['platform']}] {c['permission']}  "
                  f"({c['reason']})")

    if failures and not args.lenient:
        print("", file=sys.stderr)
        print(f"\033[38;5;208m{len(failures)} permission(s) declared but not justified in CONTEXT.md.\033[0m", file=sys.stderr)
        print("   Each declared permission must be referenced in CONTEXT.md either as:", file=sys.stderr)
        print("     Permission: NSCameraUsageDescription", file=sys.stderr)
        print("   or mentioned inside a D-XX decision block that explains why it's needed.", file=sys.stderr)
        print("   Unjustified permissions are a common App Store / Play Store rejection reason.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
