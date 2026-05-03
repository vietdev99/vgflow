#!/usr/bin/env python3
"""
verify-cert-expiry.py — Gate 7 for /vg:build mobile post-wave.

Checks signing certificate / keystore expiry for iOS (.p12) and Android
(.jks / .keystore). Warns when expiry is within warn_days; blocks when
expiry is within block_days. Each backend is gated on tool availability
(openssl, keytool) — missing tool → skip + WARN, not a hard failure.

USAGE
  python verify-cert-expiry.py \
      [--ios-p12 path/to/cert.p12] [--ios-p12-password "..."] \
      [--android-keystore path/to/release.jks] \
      [--android-keystore-password "..."] \
      [--android-alias "release"] \
      [--warn-days 30] [--block-days 0] \
      [--json] [--lenient]

EXIT CODES
  0 ok — no certs within block window
  1 fail — at least one cert within block_days (default 0 = already expired)
  2 script error (bad args)

PORTABILITY
  P1: all paths + passwords + aliases come from CLI args (populated by
      env vars the user declared in config.mobile.deploy.signing).
  P2: subprocess calls always check shutil.which; missing tool returns
      structured skip (not a fatal error).
  P3: openssl and keytool are widely available cross-platform (bundled
      with OpenSSL and JDK respectively).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_WARN_DAYS = 30
DEFAULT_BLOCK_DAYS = 0


# ---------------------------------------------------------------------
# Tool detection
# ---------------------------------------------------------------------
def has_tool(name: str) -> bool:
    return shutil.which(name) is not None


# ---------------------------------------------------------------------
# iOS .p12 via openssl
# ---------------------------------------------------------------------
# openssl pkcs12 outputs cert in PEM; openssl x509 -noout -enddate -in <pem>
# gives "notAfter=Jan  1 00:00:00 2027 GMT"
_NOT_AFTER_RE = re.compile(r"notAfter\s*=\s*(.+?)\s*$", re.MULTILINE)


def _parse_openssl_date(raw: str) -> _dt.datetime | None:
    """Parse 'Jan  1 00:00:00 2027 GMT' → aware UTC datetime."""
    raw = raw.strip()
    # Collapse multiple spaces (openssl adds extra space for 1-digit days)
    raw = re.sub(r"\s+", " ", raw)
    # e.g. "Jan 1 00:00:00 2027 GMT"
    fmt = "%b %d %H:%M:%S %Y %Z"
    try:
        dt = _dt.datetime.strptime(raw, fmt)
        return dt.replace(tzinfo=_dt.timezone.utc)
    except Exception:
        return None


def check_ios_p12(path: Path, password: str | None = None, legacy: bool = True) -> dict[str, Any]:
    """Return {status, expires_at, days_remaining, reason}."""
    if not path.is_file():
        return {"status": "not_found", "reason": f"p12 not found: {path}"}
    if not has_tool("openssl"):
        return {"status": "tool_missing", "reason": "openssl not on PATH — install via OpenSSL project or brew/apt"}

    env = os.environ.copy()
    pw_args = []
    if password:
        # Use env var to avoid password ending up in ps listing
        env["VG_P12_PW"] = password
        pw_args = ["-passin", "env:VG_P12_PW"]
    else:
        pw_args = ["-passin", "pass:"]

    # Extract certs only as PEM
    extract_cmd = ["openssl", "pkcs12", "-in", str(path), "-nokeys", *pw_args]
    if legacy:
        extract_cmd.append("-legacy")

    try:
        extract = subprocess.run(extract_cmd, capture_output=True, text=True, check=False, timeout=15, env=env)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "openssl pkcs12 timed out"}

    if extract.returncode != 0 and "-legacy" not in extract.stderr.lower():
        # Try without -legacy for older openssl versions
        if legacy:
            return check_ios_p12(path, password, legacy=False)
        return {
            "status": "failed",
            "reason": f"openssl pkcs12 failed: {extract.stderr.strip()[:200]}",
        }

    pem = extract.stdout
    if "BEGIN CERTIFICATE" not in pem:
        return {"status": "failed", "reason": "no certificate found in p12"}

    # Parse end date
    try:
        end_proc = subprocess.run(
            ["openssl", "x509", "-noout", "-enddate"],
            input=pem,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "openssl x509 timed out"}

    m = _NOT_AFTER_RE.search(end_proc.stdout)
    if not m:
        return {"status": "failed", "reason": f"could not parse notAfter from: {end_proc.stdout.strip()[:200]}"}

    expires = _parse_openssl_date(m.group(1))
    if expires is None:
        return {"status": "failed", "reason": f"could not normalize date: {m.group(1)}"}

    now = _dt.datetime.now(_dt.timezone.utc)
    days_remaining = (expires - now).days

    return {
        "status": "ok",
        "expires_at": expires.isoformat(),
        "days_remaining": days_remaining,
    }


# ---------------------------------------------------------------------
# Android keystore via keytool
# ---------------------------------------------------------------------
_VALID_UNTIL_RE = re.compile(r"(?:Valid\s+until|Valid\s+from\s*:.+?until):\s*(.+)", re.IGNORECASE)
_VALID_FROM_UNTIL_RE = re.compile(r"Valid from:.*?until:\s*(.+?)(?:\n|$)", re.IGNORECASE)


def _parse_keytool_date(raw: str) -> _dt.datetime | None:
    """
    keytool output varies by JDK locale. Common formats:
      'Tuesday, January 31, 2040'
      'Sun Jan 01 00:00:00 UTC 2040'
      'Fri Jan 01 00:00:00 GMT+00:00 2040'
    Try several formats.
    """
    raw = raw.strip()
    for fmt in (
        "%a %b %d %H:%M:%S %Z %Y",
        "%A, %B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
    ):
        try:
            return _dt.datetime.strptime(raw, fmt).replace(tzinfo=_dt.timezone.utc)
        except Exception:
            continue
    return None


def check_android_keystore(
    path: Path,
    password: str | None = None,
    alias: str | None = None,
) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "not_found", "reason": f"keystore not found: {path}"}
    if not has_tool("keytool"):
        return {"status": "tool_missing", "reason": "keytool not on PATH — install JDK (bundled)"}

    cmd = ["keytool", "-list", "-v", "-keystore", str(path)]
    if password is not None:
        cmd += ["-storepass", password]
    if alias:
        cmd += ["-alias", alias]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=20)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "keytool timed out"}

    if res.returncode != 0:
        return {
            "status": "failed",
            "reason": f"keytool failed: {res.stderr.strip()[:300]}",
        }

    # Try "Valid from: X until: Y" pattern first
    m = _VALID_FROM_UNTIL_RE.search(res.stdout)
    if not m:
        m = _VALID_UNTIL_RE.search(res.stdout)
    if not m:
        return {
            "status": "failed",
            "reason": f"could not locate validity in keytool output",
        }

    expires = _parse_keytool_date(m.group(1))
    if expires is None:
        return {
            "status": "failed",
            "reason": f"could not parse validity date: {m.group(1)!r}",
        }

    now = _dt.datetime.now(_dt.timezone.utc)
    days_remaining = (expires - now).days

    return {
        "status": "ok",
        "expires_at": expires.isoformat(),
        "days_remaining": days_remaining,
    }


# ---------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------
def classify(entry: dict[str, Any], warn_days: int, block_days: int) -> str:
    """
    Return 'block' | 'warn' | 'ok' | 'skipped'.
    skipped applies when status != ok (tool missing, file missing, parse fail).
    """
    if entry.get("status") != "ok":
        return "skipped"
    dr = entry.get("days_remaining", 99999)
    if dr <= block_days:
        return "block"
    if dr <= warn_days:
        return "warn"
    return "ok"


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ios-p12", help="Path to iOS distribution .p12")
    ap.add_argument("--ios-p12-password", default=None, help="Password for the .p12 (or empty for blank)")
    ap.add_argument("--android-keystore", help="Path to Android release.jks / .keystore")
    ap.add_argument("--android-keystore-password", default=None)
    ap.add_argument("--android-alias", default=None)
    ap.add_argument("--warn-days", type=int, default=DEFAULT_WARN_DAYS)
    ap.add_argument("--block-days", type=int, default=DEFAULT_BLOCK_DAYS)
    ap.add_argument("--lenient", action="store_true", help="Warn but do not fail")
    ap.add_argument("--json", action="store_true", help="Emit JSON")
    args = ap.parse_args()

    checks: list[dict[str, Any]] = []

    if args.ios_p12:
        ios = check_ios_p12(Path(args.ios_p12), args.ios_p12_password)
        ios["platform"] = "ios"
        ios["path"] = args.ios_p12
        ios["verdict"] = classify(ios, args.warn_days, args.block_days)
        checks.append(ios)

    if args.android_keystore:
        android = check_android_keystore(
            Path(args.android_keystore),
            args.android_keystore_password,
            args.android_alias,
        )
        android["platform"] = "android"
        android["path"] = args.android_keystore
        android["verdict"] = classify(android, args.warn_days, args.block_days)
        checks.append(android)

    report = {
        "warn_days": args.warn_days,
        "block_days": args.block_days,
        "checks": checks,
    }

    failures = [c for c in checks if c.get("verdict") == "block"]
    warnings = [c for c in checks if c.get("verdict") == "warn"]
    skipped = [c for c in checks if c.get("verdict") == "skipped"]

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for c in checks:
            icon = {"ok": "✓", "warn": "", "block": "✗", "skipped": "·"}.get(c["verdict"], "?")
            if c.get("status") == "ok":
                print(f"  {icon} [{c['platform']}] expires {c['expires_at']}  "
                      f"({c['days_remaining']} days left)")
            else:
                print(f"  {icon} [{c['platform']}] {c.get('status')}: {c.get('reason', '')}")

    if failures and not args.lenient:
        print("", file=sys.stderr)
        print(f"\033[38;5;208m{len(failures)} signing cert(s) expired or within block window ({args.block_days} days).\033[0m", file=sys.stderr)
        print("   Renew cert / keystore before next build. A silent failure here", file=sys.stderr)
        print("   breaks CI mid-deploy — we catch it at gate time instead.", file=sys.stderr)
        return 1

    if warnings:
        # Warnings are informational — always print but never fail
        for w in warnings:
            print(f"⚠ [{w['platform']}] cert expires in {w['days_remaining']} days — renew soon.", file=sys.stderr)

    if skipped and not checks:
        # Nothing actually checked
        print("ℹ no signing assets checked (paths empty or tools missing).", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
