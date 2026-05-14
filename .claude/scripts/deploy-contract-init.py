#!/usr/bin/env python3
"""deploy-contract-init.py — Batch 20

Bootstrap .vg/DEPLOY-CONTRACT.json on first deploy.

Modes:
  - Explicit args: --method ansible --build "..." --restart "..." --health "..."
  - From vg.config.md: auto-infer from deploy_profile + environments[env].deploy
  - Interactive: prompts user (when called from /vg:test or /vg:deploy with no flags)

Idempotent: refuses overwrite unless --force.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


VALID_METHODS = ["ansible", "pm2", "docker", "systemd", "kubectl",
                 "helm", "terraform", "capistrano", "fabric", "custom"]

# Heuristic patterns for auto-detecting method from command
METHOD_PATTERNS = {
    "ansible": r"^ansible(-playbook)?\b",
    "pm2": r"^pm2\b",
    "docker": r"^docker(\s+compose)?\b",
    "systemd": r"^sudo\s+systemctl\b|^systemctl\b",
    "kubectl": r"^kubectl\b",
    "helm": r"^helm\b",
    "terraform": r"^terraform\b",
    "capistrano": r"^cap\b|^bundle exec cap\b",
    "fabric": r"^fab\b",
}


def _infer_method(cmd: str) -> str:
    for method, pat in METHOD_PATTERNS.items():
        if re.search(pat, cmd):
            return method
    return "custom"


def _fingerprint_pattern(method: str) -> str:
    return METHOD_PATTERNS.get(method, r".*")


def _compute_lock_sha(commands: dict) -> str:
    canonical = json.dumps(commands, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vg-dir", type=Path, default=Path(".vg"))
    ap.add_argument("--method", choices=VALID_METHODS)
    ap.add_argument("--pre", default="")
    ap.add_argument("--build")
    ap.add_argument("--restart")
    ap.add_argument("--health")
    ap.add_argument("--rollback", default="")
    ap.add_argument("--phase", default="")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing contract (logs override-debt)")
    args = ap.parse_args()

    contract_path = args.vg_dir / "DEPLOY-CONTRACT.json"
    if contract_path.exists() and not args.force:
        existing = json.loads(contract_path.read_text(encoding="utf-8"))
        print(f"DEPLOY-CONTRACT.json already exists (method={existing.get('method')}).", file=sys.stderr)
        print(f"   Use --force to overwrite OR /vg:override-resolve --deploy-method to change", file=sys.stderr)
        return 1

    if not (args.build and args.restart and args.health):
        print("ERROR: --build, --restart, --health all required (or use interactive mode via /vg:deploy)", file=sys.stderr)
        return 2

    method = args.method or _infer_method(args.build)
    commands = {
        "pre": args.pre,
        "build": args.build,
        "restart": args.restart,
        "health": args.health,
        "rollback": args.rollback,
    }
    contract = {
        "method": method,
        "commands": commands,
        "fingerprint_pattern": _fingerprint_pattern(method),
        "lock_sha256": _compute_lock_sha(commands),
        "established_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "established_by_phase": args.phase,
        "established_by_run_id": args.run_id,
    }

    args.vg_dir.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    print(f"DEPLOY-CONTRACT.json written: method={method}")
    print(f"  fingerprint_pattern={contract['fingerprint_pattern']}")
    print(f"  lock_sha256={contract['lock_sha256'][:12]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
