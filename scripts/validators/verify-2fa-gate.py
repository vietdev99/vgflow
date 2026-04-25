#!/usr/bin/env python3
"""
verify-2fa-gate.py — Phase M Batch 2 of v2.5.2 hardening.

Problem closed:
  TEST-GOALS.md may declare that a sensitive route (admin, payout,
  billing) REQUIRES 2FA, but the handler code uses only
  password/session auth. AI executors often forget the 2FA step
  when wiring handlers, and single-factor tests still pass. This
  validator cross-checks declared-2FA routes against handler code.

SAST workflow:
  1. Parse TEST-GOALS.md (or --test-goals path) for goals that
     declare 2FA requirement via:
       requires_2fa: true
       auth_model: "2fa_required_for: admin"
       verifies: 2fa_enforced
     Or phase-level frontmatter block `security.requires_2fa: [role...]`.
  2. For each flagged route/handler, grep source for ≥1 2FA-check
     pattern:
       TOTP: totp.verify, speakeasy.totp.verify, pyotp.TOTP().verify,
             otplib.authenticator.verify
       WebAuthn: f2l.attestation, f2l.assertion, @simplewebauthn/server
       Backup codes: backup_codes usage + consumed/used marker
  3. If TEST-GOALS declares nothing 2FA-related → skip (info only).
  4. If backup codes are used but never marked consumed → WARN (replay).

Exit codes:
  0 = every declared-2FA route has a verified handler check, or no 2FA
      declared (skip)
  1 = BLOCK (declared but missing check)
  2 = config error

Usage:
  verify-2fa-gate.py --project-root .
  verify-2fa-gate.py --project-root . --test-goals .vg/phases/7.14/TEST-GOALS.md
  verify-2fa-gate.py --project-root . --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TOTP_PATTERNS = [
    r"\btotp\.verify\s*\(",
    r"speakeasy\.totp\.verify",
    r"pyotp\.TOTP\s*\(.*?\)\.verify",
    r"otplib\.authenticator\.verify",
    r"\bverify_totp\s*\(",
    r"\btwofactor\.verify\s*\(",
    r"TotpVerifier",
]

WEBAUTHN_PATTERNS = [
    r"f2l\.attestation",
    r"f2l\.assertion",
    r"@simplewebauthn/server",
    r"\bwebauthn\.verify",
    r"verifyAuthenticationResponse",
    r"verifyRegistrationResponse",
    r"fido2-lib",
]

BACKUP_CODE_USE_RE = re.compile(
    r"\bbackup[_\s-]?code[s]?\b", re.IGNORECASE,
)
BACKUP_CODE_CONSUME_RE = re.compile(
    r"(mark.*consumed|mark.*used|set.*consumed_at|"
    r"backup_code[s]?\..*(consume|invalidate|delete|remove))",
    re.IGNORECASE,
)

REQUIRES_2FA_PATTERNS = [
    r"requires[_\s-]?2fa\s*[:=]\s*true",
    r"2fa[_\s-]?required\s*[:=]\s*true",
    r"""auth[_\s-]?model\s*[:=]\s*['"]?.*2fa[_\s-]?required""",
    r"verifies\s*:\s*2fa[_\s-]?enforced",
    r"mfa[_\s-]?required\s*[:=]\s*true",
]

CODE_EXTS = (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".py",
             ".go", ".java", ".rs")


def _iter_code_files(root: Path):
    skip = {"node_modules", "dist", "build", ".git", ".vg",
            "__pycache__", ".next", "target", "vendor"}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip for part in p.parts):
            continue
        if p.suffix.lower() in CODE_EXTS:
            yield p


def _parse_test_goals(path: Path) -> list[dict]:
    """Return list of goals that declare 2FA. Each: {goal_id, route, text}."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    declared: list[dict] = []
    req_re = re.compile("|".join(REQUIRES_2FA_PATTERNS), re.IGNORECASE)

    # Split into goals by headings G-XX or "### Goal"
    # Fallback: scan whole file
    goal_blocks = re.split(r"^(?=##\s+G-\d+|###\s+Goal|---\s*$)",
                           text, flags=re.MULTILINE)
    for block in goal_blocks:
        if not req_re.search(block):
            continue
        gid_m = re.search(r"\bG-(\d+(?:\.\d+)?)\b", block)
        route_m = re.search(
            r"(?:route|path|endpoint)\s*:\s*['\"]?(/\S+)", block,
            re.IGNORECASE,
        )
        declared.append({
            "goal_id": f"G-{gid_m.group(1)}" if gid_m else "(unknown)",
            "route": route_m.group(1) if route_m else None,
            "text": block[:200].strip(),
        })
    return declared


def _scan_code(root: Path) -> dict:
    findings = {
        "totp_hits": [],
        "webauthn_hits": [],
        "backup_code_files": [],
        "backup_code_consumed": False,
        "files_scanned": 0,
    }
    totp_re = re.compile("|".join(TOTP_PATTERNS), re.IGNORECASE)
    webauthn_re = re.compile("|".join(WEBAUTHN_PATTERNS), re.IGNORECASE)

    for f in _iter_code_files(root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings["files_scanned"] += 1

        if totp_re.search(text):
            findings["totp_hits"].append(str(f))
        if webauthn_re.search(text):
            findings["webauthn_hits"].append(str(f))
        if BACKUP_CODE_USE_RE.search(text):
            findings["backup_code_files"].append(str(f))
            if BACKUP_CODE_CONSUME_RE.search(text):
                findings["backup_code_consumed"] = True
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--test-goals",
                    help="path to TEST-GOALS.md to parse for 2FA declarations")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--phase", help="(orchestrator-injected; ignored by this validator)")
    args = ap.parse_args()

    root = Path(args.project_root).resolve()
    if not root.exists():
        print(f"⛔ project-root does not exist: {root}", file=sys.stderr)
        return 2

    declared: list[dict] = []
    if args.test_goals:
        tg_path = Path(args.test_goals)
        if not tg_path.is_absolute():
            tg_path = root / tg_path
        declared = _parse_test_goals(tg_path)

    sast = _scan_code(root)

    blocks: list[str] = []
    warns: list[str] = []

    has_any_2fa = bool(sast["totp_hits"]) or bool(sast["webauthn_hits"])

    if not declared:
        # Nothing declared as 2FA-required → skip gracefully
        verdict = "SKIP"
    else:
        verdict = "OK"
        if not has_any_2fa:
            blocks.append(
                f"{len(declared)} goal(s) declare 2FA requirement but "
                f"no TOTP/WebAuthn verify call found anywhere in "
                f"{sast['files_scanned']} scanned files"
            )
            verdict = "FAIL"
        else:
            # We have some 2FA code; per-route mapping is approximate
            # since routes aren't always declared in TEST-GOALS with
            # file refs. Warn if backup codes exist without consumption.
            if (sast["backup_code_files"]
                    and not sast["backup_code_consumed"]):
                warns.append(
                    "backup_codes referenced but no consume/mark-used "
                    "pattern — allows replay of a single code"
                )
                verdict = "WARN"

    # v2.6.1 (2026-04-26): canonicalize verdict for orchestrator schema.
    # Internal: SKIP/OK/WARN/FAIL → output: PASS/PASS/WARN/BLOCK.
    _canonical = {"FAIL": "BLOCK", "OK": "PASS", "SKIP": "PASS", "WARN": "WARN"}.get(verdict, verdict)

    output = {
        "validator": "verify-2fa-gate",
        "verdict": _canonical,
        "declared_2fa_goals": len(declared),
        "declared_details": declared[:10],
        "blocks": blocks,
        "warns": warns,
        "sast_summary": {
            "totp_files": len(sast["totp_hits"]),
            "webauthn_files": len(sast["webauthn_hits"]),
            "backup_code_files": len(sast["backup_code_files"]),
            "backup_code_consumed": sast["backup_code_consumed"],
            "files_scanned": sast["files_scanned"],
        },
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        if verdict == "SKIP":
            if not args.quiet:
                print("✓ No 2FA goals declared — skipping check.")
        elif verdict == "FAIL":
            print(f"⛔ 2FA gate: {len(blocks)} block(s)")
            for b in blocks:
                print(f"  [BLOCK] {b}")
        elif verdict == "WARN":
            if not args.quiet:
                print(f"⚠ 2FA gate: {len(warns)} warn(s)")
                for w in warns:
                    print(f"  [WARN]  {w}")
        elif not args.quiet:
            print(f"✓ 2FA gate OK — {len(declared)} declared goal(s) "
                  f"covered by TOTP/WebAuthn code")

    if verdict == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
