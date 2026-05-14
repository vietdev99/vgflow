#!/usr/bin/env python3
"""deploy-contract-load.py — Batch 20

Load .vg/DEPLOY-CONTRACT.json and print shell `export` statements for sourcing.

Usage in deploy step:
  eval "$(python scripts/deploy-contract-load.py --vg-dir .vg --env sandbox)"
  run_on_target "$DEPLOY_BUILD"

BLOCKs (exit 1) if contract missing — forces operator to run init first.
"""
from __future__ import annotations
import argparse
import json
import shlex
import sys
from pathlib import Path


def _substitute(cmd: str, env: str) -> str:
    return cmd.replace("{env}", env)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vg-dir", type=Path, default=Path(".vg"))
    ap.add_argument("--env", required=True)
    args = ap.parse_args()

    contract_path = args.vg_dir / "DEPLOY-CONTRACT.json"
    if not contract_path.is_file():
        print(f"DEPLOY-CONTRACT.json missing at {contract_path}", file=sys.stderr)
        print("   Bootstrap with one of:", file=sys.stderr)
        print("     /vg:deploy --init                                    # interactive", file=sys.stderr)
        print("     python scripts/deploy-contract-init.py \\", file=sys.stderr)
        print("       --method ansible --build '...' --restart '...' --health '...'", file=sys.stderr)
        return 1

    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"DEPLOY-CONTRACT.json malformed: {e}", file=sys.stderr)
        return 1

    method = contract.get("method", "")
    cmds = contract.get("commands", {})
    fp = contract.get("fingerprint_pattern", "")
    lock = contract.get("lock_sha256", "")

    exports = {
        "DEPLOY_METHOD": method,
        "DEPLOY_PRE": _substitute(cmds.get("pre", ""), args.env),
        "DEPLOY_BUILD": _substitute(cmds.get("build", ""), args.env),
        "DEPLOY_RESTART": _substitute(cmds.get("restart", ""), args.env),
        "DEPLOY_HEALTH": _substitute(cmds.get("health", ""), args.env),
        "DEPLOY_ROLLBACK": _substitute(cmds.get("rollback", ""), args.env),
        "DEPLOY_FINGERPRINT_PATTERN": fp,
        "DEPLOY_CONTRACT_LOCK_SHA256": lock,
    }
    for key, val in exports.items():
        if val:
            print(f"export {key}={shlex.quote(val)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
