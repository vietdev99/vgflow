#!/usr/bin/env python3
"""
vg-auth.py — v2.5.2.1 hotfix for Phase O allow-flag gate.

Problem closed (CrossAI round 3 consensus):
  Phase O verified human via TTY check OR raw $VG_HUMAN_OPERATOR string.
  AI subprocess could self-set env var and forge approval. Signed token
  path raises the bar — AI needs key-file read access, not just env write.

CLI subcommands:
  approve --flag X [--ttl-days 30] [--any-flag]
    Mint an HMAC-signed approval token for flag X (or `*` with --any-flag).
    ONLY runs in TTY mode. Token printed to stdout; user exports into env:

        export VG_HUMAN_OPERATOR="$(python .claude/scripts/vg-auth.py \\
          approve --flag allow-security-baseline-unverified --ttl-days 7)"

    Then subsequent `/vg:<command> --allow-*` checks the env var with
    signature verification.

  verify --token T --flag X
    Verify a token explicitly (tests / debugging).

  init
    Force-create the signing key at ~/.vg/.approver-key (0600 POSIX).
    Idempotent — safe to re-run.

Exit codes:
  0 success
  1 verification fail / usage error
  2 config error / no TTY when required
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Import allow_flag_gate via importlib since vg-orchestrator has a dash in its
# directory name (not a valid Python identifier, blocks `from` imports).
import importlib.util as _ilu

_SCRIPT_DIR = Path(__file__).resolve().parent
_GATE_PATH = _SCRIPT_DIR / "vg-orchestrator" / "allow_flag_gate.py"
_spec = _ilu.spec_from_file_location("allow_flag_gate", _GATE_PATH)
_gate = _ilu.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_gate)


def cmd_approve(args) -> int:
    if not _gate._is_tty() and not args.force_no_tty:
        print("⛔ `vg-auth approve` requires a TTY (interactive shell).",
              file=sys.stderr)
        print("   AI subagents must not mint their own approvals. If you are "
              "running manually from a CI or headless env, use `--force-no-tty` "
              "and expect the token to be flagged as non-interactive in audit.",
              file=sys.stderr)
        return 2

    user = _gate._tty_user() or os.environ.get("VG_HUMAN_OPERATOR_HANDLE") \
           or "unknown"
    if args.handle:
        user = args.handle

    if args.any_flag:
        flag_scope = "*"
    elif args.flag:
        flag_scope = args.flag
    else:
        print("⛔ --flag <name> or --any-flag required", file=sys.stderr)
        return 1

    ttl_seconds = max(60, int(args.ttl_days) * 86400)
    token = _gate.sign_approval(user, flag_scope, ttl_seconds)

    if args.json:
        import json
        print(json.dumps({
            "token": token,
            "handle": user,
            "flag": flag_scope,
            "ttl_days": args.ttl_days,
            "expires_at_epoch": int(time.time()) + ttl_seconds,
        }, indent=2))
    else:
        # Print token only (stdout) so shell `$(...)` capture works
        print(token)
        if not args.quiet:
            print(f"# approver={user} flag={flag_scope} ttl={args.ttl_days}d",
                  file=sys.stderr)

    return 0


def cmd_verify(args) -> int:
    valid, handle, reason = _gate.verify_approval(args.token, args.flag)
    if args.json:
        import json
        print(json.dumps({
            "valid": valid,
            "handle": handle,
            "reason": reason,
        }, indent=2))
    else:
        status = "✓ VALID" if valid else "⛔ INVALID"
        print(f"{status} — handle={handle!r} reason={reason}")
    return 0 if valid else 1


def cmd_init(args) -> int:
    path = _gate._approver_key_path()
    # Force-create by calling _get_or_create_key
    _gate._get_or_create_key()
    try:
        mode = oct(path.stat().st_mode & 0o777)
    except OSError:
        mode = "?"
    print(f"✓ Signing key at {path} (mode={mode})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_app = sub.add_parser("approve",
                           help="mint an HMAC-signed approval token")
    p_app.add_argument("--flag", help="specific --allow-* flag name "
                                      "(e.g. 'allow-security-baseline-unverified')")
    p_app.add_argument("--any-flag", action="store_true",
                       help="token grants approval for any --allow-* flag "
                            "(defeats scoping — use only for short-lived session)")
    p_app.add_argument("--ttl-days", type=int, default=7,
                       help="token validity in days (default: 7, minimum: 1min)")
    p_app.add_argument("--handle",
                       help="override approver handle (default: $USER)")
    p_app.add_argument("--force-no-tty", action="store_true",
                       help="bypass TTY check (for CI; audit will flag)")
    p_app.add_argument("--json", action="store_true")
    p_app.add_argument("--quiet", action="store_true")

    p_ver = sub.add_parser("verify", help="verify a token explicitly")
    p_ver.add_argument("--token", required=True)
    p_ver.add_argument("--flag", required=True)
    p_ver.add_argument("--json", action="store_true")

    sub.add_parser("init",
                   help="force-create signing key (idempotent)")

    args = ap.parse_args()
    dispatch = {"approve": cmd_approve, "verify": cmd_verify, "init": cmd_init}
    return dispatch[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
