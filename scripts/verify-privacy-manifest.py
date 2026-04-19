#!/usr/bin/env python3
"""
verify-privacy-manifest.py — Gate 8 for /vg:build mobile post-wave.

Checks consistency between declared permissions and privacy disclosures:

  iOS:     Info.plist usage-descriptions  ↔  PrivacyInfo.xcprivacy
           declared privacy-accessed APIs + tracking domains
  Android: AndroidManifest uses-permission ↔  data-safety YAML
           declared collected data types

Compliance impact: iOS 17+ requires PrivacyInfo.xcprivacy for specific
API domains (user_defaults, file_timestamp, disk_space, system_boot,
active_keyboards). Google Play requires the data-safety form to match
the permissions actually requested. Mismatches = store rejection.

USAGE
  python verify-privacy-manifest.py \
      [--ios-plist Info.plist] \
      [--ios-privacy-info PrivacyInfo.xcprivacy] \
      [--android-manifest AndroidManifest.xml] \
      [--android-data-safety .vg/android-data-safety.yaml] \
      [--lenient] [--json]

EXIT CODES
  0 ok — consistent
  1 fail — inconsistency detected
  2 script error

PORTABILITY
  P1: all paths from CLI args populated by config.mobile.gates.privacy_manifest.
  P2: stdlib plistlib + xml.etree + (yaml if available, else naive parser).
  P3: no external tools.
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
# iOS: Info.plist usage keys + PrivacyInfo.xcprivacy
# ---------------------------------------------------------------------
# Mapping from Info.plist usage keys to required PrivacyInfo categories.
# Not exhaustive — covers the most common App Store rejection triggers.
# Key: usage-description key in Info.plist.
# Value: tuple of (PrivacyInfo.xcprivacy key, human-readable reason).
USAGE_TO_PRIVACY = {
    "NSCameraUsageDescription": ("NSPrivacyAccessedAPIType", "camera data collection"),
    "NSMicrophoneUsageDescription": ("NSPrivacyAccessedAPIType", "microphone data collection"),
    "NSLocationWhenInUseUsageDescription": ("NSPrivacyCollectedDataType", "precise/coarse location"),
    "NSLocationAlwaysUsageDescription": ("NSPrivacyCollectedDataType", "precise/coarse location"),
    "NSLocationAlwaysAndWhenInUseUsageDescription": ("NSPrivacyCollectedDataType", "precise/coarse location"),
    "NSContactsUsageDescription": ("NSPrivacyCollectedDataType", "contacts"),
    "NSCalendarsUsageDescription": ("NSPrivacyCollectedDataType", "calendar"),
    "NSPhotoLibraryUsageDescription": ("NSPrivacyCollectedDataType", "photo library"),
    "NSHealthShareUsageDescription": ("NSPrivacyCollectedDataType", "health data"),
    "NSBluetoothAlwaysUsageDescription": ("NSPrivacyAccessedAPIType", "bluetooth"),
    "NSUserTrackingUsageDescription": ("NSPrivacyTracking", "user tracking"),
}


def parse_ios_plist_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        with path.open("rb") as fh:
            data = plistlib.load(fh)
    except Exception:
        return set()
    return {k for k in data.keys() if k in USAGE_TO_PRIVACY}


def parse_ios_privacy_info(path: Path) -> dict[str, Any]:
    """
    Returns the top-level keys present in PrivacyInfo.xcprivacy. Keys we
    care about:
        NSPrivacyTracking (bool)
        NSPrivacyTrackingDomains (array)
        NSPrivacyCollectedDataTypes (array of dicts)
        NSPrivacyAccessedAPITypes (array of dicts)
    Returns empty dict if file missing/unparseable.
    """
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            return plistlib.load(fh)
    except Exception:
        return {}


def check_ios_consistency(plist: Path | None, privacy: Path | None) -> list[dict[str, Any]]:
    """Return list of issues (empty = consistent)."""
    issues: list[dict[str, Any]] = []
    if not plist or not privacy:
        return issues

    usage_keys = parse_ios_plist_keys(plist)
    privacy_doc = parse_ios_privacy_info(privacy)

    # Distinguish "privacy file missing on disk" (hard failure, short-circuit)
    # vs "privacy file exists but empty" (continue with per-key checks that
    # will flag specific missing categories).
    if not privacy.is_file() and plist.is_file() and usage_keys:
        issues.append({
            "type": "missing_privacy_info",
            "detail": f"Info.plist declares {len(usage_keys)} usage descriptions but PrivacyInfo.xcprivacy missing at {privacy}",
            "severity": "major",
        })
        return issues

    has_collected = "NSPrivacyCollectedDataTypes" in privacy_doc
    has_accessed = "NSPrivacyAccessedAPITypes" in privacy_doc
    has_tracking = privacy_doc.get("NSPrivacyTracking")

    for key in usage_keys:
        category, reason = USAGE_TO_PRIVACY[key]
        if category == "NSPrivacyCollectedDataType" and not has_collected:
            issues.append({
                "type": "missing_collected_data_type",
                "usage_key": key,
                "expected_category": "NSPrivacyCollectedDataTypes",
                "detail": f"{key} implies {reason} is collected, but NSPrivacyCollectedDataTypes is empty in PrivacyInfo.xcprivacy",
                "severity": "major",
            })
        elif category == "NSPrivacyAccessedAPIType" and not has_accessed:
            issues.append({
                "type": "missing_accessed_api_type",
                "usage_key": key,
                "expected_category": "NSPrivacyAccessedAPITypes",
                "detail": f"{key} requires declaring the API in NSPrivacyAccessedAPITypes",
                "severity": "major",
            })
        elif category == "NSPrivacyTracking" and not has_tracking:
            issues.append({
                "type": "tracking_not_disclosed",
                "usage_key": key,
                "detail": f"{key} implies tracking but NSPrivacyTracking=false/missing in PrivacyInfo.xcprivacy",
                "severity": "major",
            })

    return issues


# ---------------------------------------------------------------------
# Android: AndroidManifest ↔ data-safety YAML
# ---------------------------------------------------------------------
ANDROID_NS = "http://schemas.android.com/apk/res/android"


def parse_android_manifest_perms(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        tree = ET.parse(str(path))
    except Exception:
        return set()
    root = tree.getroot()
    perms = set()
    for tag in ("uses-permission", "uses-permission-sdk-23"):
        for c in root.findall(tag):
            n = c.get(f"{{{ANDROID_NS}}}name")
            if n:
                perms.add(n)
    return perms


# Permission → Google Play data-safety category.
# Kept as a curated table — extend as needed. Unknown permissions are
# treated as "requires disclosure" with category='unknown' (soft warning).
ANDROID_PERM_TO_CATEGORY = {
    "android.permission.CAMERA": "photos_and_videos",
    "android.permission.RECORD_AUDIO": "audio_files",
    "android.permission.ACCESS_FINE_LOCATION": "location",
    "android.permission.ACCESS_COARSE_LOCATION": "location",
    "android.permission.ACCESS_BACKGROUND_LOCATION": "location",
    "android.permission.READ_CONTACTS": "contacts",
    "android.permission.WRITE_CONTACTS": "contacts",
    "android.permission.READ_CALENDAR": "calendar_events",
    "android.permission.WRITE_CALENDAR": "calendar_events",
    "android.permission.READ_SMS": "messages",
    "android.permission.SEND_SMS": "messages",
    "android.permission.READ_EXTERNAL_STORAGE": "files_and_docs",
    "android.permission.WRITE_EXTERNAL_STORAGE": "files_and_docs",
    "android.permission.READ_MEDIA_IMAGES": "photos_and_videos",
    "android.permission.READ_MEDIA_VIDEO": "photos_and_videos",
    "android.permission.READ_MEDIA_AUDIO": "audio_files",
}


def _load_yaml(text: str) -> dict:
    """YAML loader — prefer PyYAML, fall back to a naive line parser for
    the subset we actually use (top-level `data_collected:` list)."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except Exception:
        pass
    # Naive fallback: look for `- category: X` under `data_collected:`
    out: dict[str, Any] = {"data_collected": []}
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("data_collected:"):
            in_section = True
            continue
        if in_section and stripped.startswith("-"):
            # Expected: - category: location
            m = re.search(r"category\s*:\s*([^\s#,}]+)", stripped)
            if m:
                out["data_collected"].append({"category": m.group(1)})
        elif in_section and stripped and not stripped.startswith("-") and not stripped.startswith("#"):
            # Section ended (non-list line at same or lower indent)
            if not stripped.startswith(" "):
                in_section = False
    return out


def parse_android_data_safety(path: Path) -> set[str]:
    """Return set of data-safety categories declared."""
    if not path.is_file():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return set()
    doc = _load_yaml(text)
    categories: set[str] = set()
    for entry in doc.get("data_collected", []) or []:
        if isinstance(entry, dict):
            cat = entry.get("category")
            if cat:
                categories.add(str(cat))
        elif isinstance(entry, str):
            categories.add(entry)
    return categories


def check_android_consistency(manifest: Path | None, data_safety: Path | None) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not manifest or not data_safety:
        return issues

    perms = parse_android_manifest_perms(manifest)
    declared = parse_android_data_safety(data_safety)

    if perms and not data_safety.is_file():
        issues.append({
            "type": "missing_data_safety",
            "detail": f"AndroidManifest declares {len(perms)} permission(s) but data-safety YAML missing at {data_safety}",
            "severity": "major",
        })
        return issues

    for perm in perms:
        expected = ANDROID_PERM_TO_CATEGORY.get(perm)
        if expected is None:
            # Permission not in our curated map — surface as informational so user can
            # confirm disclosure manually. Not a hard failure.
            issues.append({
                "type": "unmapped_permission",
                "permission": perm,
                "detail": f"{perm} not in privacy-manifest map; verify data-safety disclosure manually",
                "severity": "minor",
            })
            continue
        if expected not in declared:
            issues.append({
                "type": "missing_data_safety_category",
                "permission": perm,
                "expected_category": expected,
                "detail": f"{perm} implies data-safety category '{expected}' but not declared in {data_safety.name}",
                "severity": "major",
            })

    return issues


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ios-plist")
    ap.add_argument("--ios-privacy-info")
    ap.add_argument("--android-manifest")
    ap.add_argument("--android-data-safety")
    ap.add_argument("--lenient", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    all_issues: list[dict[str, Any]] = []

    ios_issues = check_ios_consistency(
        Path(args.ios_plist) if args.ios_plist else None,
        Path(args.ios_privacy_info) if args.ios_privacy_info else None,
    )
    for i in ios_issues:
        i["platform"] = "ios"
    all_issues.extend(ios_issues)

    android_issues = check_android_consistency(
        Path(args.android_manifest) if args.android_manifest else None,
        Path(args.android_data_safety) if args.android_data_safety else None,
    )
    for i in android_issues:
        i["platform"] = "android"
    all_issues.extend(android_issues)

    major = [i for i in all_issues if i.get("severity") == "major"]
    minor = [i for i in all_issues if i.get("severity") == "minor"]

    report = {
        "total_issues": len(all_issues),
        "major": len(major),
        "minor": len(minor),
        "issues": all_issues,
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Privacy manifest audit — issues: {len(all_issues)} "
              f"(major={len(major)}, minor={len(minor)})")
        for i in all_issues:
            icon = "✗" if i.get("severity") == "major" else "⚠"
            print(f"  {icon} [{i.get('platform')}] {i.get('type')}: {i.get('detail')}")

    if major and not args.lenient:
        print("", file=sys.stderr)
        print(f"⛔ {len(major)} major privacy-manifest inconsistency(ies).", file=sys.stderr)
        print("   Store rejection risk — resolve BEFORE submission.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
