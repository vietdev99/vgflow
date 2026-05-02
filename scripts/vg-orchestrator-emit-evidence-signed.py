#!/usr/bin/env python3
"""HMAC-signed evidence emitter — only path that writes protected paths.

Usage:
    vg-orchestrator-emit-evidence-signed.py --out <path> --payload <json>

Reads HMAC key from $VG_EVIDENCE_KEY_PATH (default .vg/.evidence-key, mode 0600).
Writes JSON: {"payload": <input>, "hmac_sha256": "<hex>", "signed_at": "<iso8601>"}
"""
import argparse, hashlib, hmac, json, os, sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_KEY_PATH = ".vg/.evidence-key"


def load_key() -> bytes:
    key_path = Path(os.environ.get("VG_EVIDENCE_KEY_PATH", DEFAULT_KEY_PATH))
    if not key_path.exists():
        sys.stderr.write(
            f"ERROR: evidence key missing at {key_path}\n"
            f"Run: openssl rand -base64 32 > {key_path} && chmod 600 {key_path}\n"
        )
        sys.exit(2)
    if (key_path.stat().st_mode & 0o077) != 0:
        sys.stderr.write(f"ERROR: evidence key {key_path} must be mode 0600\n")
        sys.exit(2)
    return key_path.read_bytes().strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--payload", required=True, help="JSON string")
    args = ap.parse_args()

    payload = json.loads(args.payload)
    key = load_key()
    canonical = json.dumps(payload, sort_keys=True).encode()
    sig = hmac.new(key, canonical, hashlib.sha256).hexdigest()

    record = {
        "payload": payload,
        "hmac_sha256": sig,
        "signed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
