#!/usr/bin/env python3
"""
verify-oauth-pkce-enforcement.py — Phase M Batch 2 of v2.5.2 hardening.

Problem closed:
  OAuth flows AI emits often omit PKCE (code_challenge/S256), state
  parameter verification, or nonce in OIDC. For public clients (SPA,
  mobile) PKCE is MANDATORY per RFC 7636. AI default templates often
  copy confidential-client flows into public-client contexts, leaving
  the authorization code interceptable.

SAST-only — detects OAuth flow implementations in source and checks:
  1. Any OAuth client code present at all? (grep passport-oauth2,
     openid-client, @fastify/oauth2, authlib, python-jose OIDC,
     oauthlib, simple-oauth2). Returns clean pass if none — nothing
     to verify.
  2. For each detected flow, verify:
     a. code_challenge + code_challenge_method=S256 appear in the
        authorization URL builder (PKCE)
     b. state parameter is set + verified on callback
     c. nonce is set + verified when id_token is consumed (OIDC)
  3. Client-type heuristic: public_client:true, pkceMethod:'S256', or
     SPA indicators (frontend-only OAuth). When public → PKCE is
     MANDATORY (BLOCK). Confidential server → recommended (WARN).

Exit codes:
  0 = PKCE + state + nonce all satisfied, or no OAuth code detected
  1 = BLOCK (missing PKCE on public client, missing state verification)
  2 = config error

Usage:
  verify-oauth-pkce-enforcement.py --project-root .
  verify-oauth-pkce-enforcement.py --project-root . --declared-flows FILE
  verify-oauth-pkce-enforcement.py --project-root . --json --quiet
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


OAUTH_LIB_PATTERNS = [
    r"passport-oauth2",
    r"openid-client",
    r"@fastify/oauth2",
    r"\bauthlib\b",
    r"oauthlib",
    r"simple-oauth2",
    r"python-jose",
    r"/oauth/callback",
    r"/oauth2?/authorize",
    r"\bcode_challenge\b",
    r"\bgrant_type\s*[:=]\s*['\"]authorization_code['\"]",
]

PKCE_CHALLENGE_RE = re.compile(r"\bcode_challenge\b")
PKCE_METHOD_S256_RE = re.compile(
    r"code_challenge_method\s*[:=]\s*['\"]S256['\"]",
    re.IGNORECASE,
)
PKCE_METHOD_ANY_RE = re.compile(
    r"code_challenge_method\s*[:=]\s*['\"]([A-Za-z0-9]+)['\"]",
    re.IGNORECASE,
)

STATE_SET_RE = re.compile(
    r"""state\s*[:=]\s*['"]?[\w\-${}]+""", re.IGNORECASE,
)
STATE_VERIFY_RE = re.compile(
    r"""(state\s*===?\s*|state_match|verifyState|"""
    r"""state\s*!==?\s*|check_state|stored_state)""",
    re.IGNORECASE,
)

NONCE_SET_RE = re.compile(r"\bnonce\b\s*[:=]", re.IGNORECASE)
NONCE_VERIFY_RE = re.compile(
    r"(id_token.*nonce|verify[_\s-]?nonce|nonce\s*===?\s*|nonce_match)",
    re.IGNORECASE,
)

PUBLIC_CLIENT_PATTERNS = [
    r"public_client\s*[:=]\s*true",
    r"is_public\s*[:=]\s*true",
    r"client_type\s*[:=]\s*['\"]public['\"]",
    r"pkce\s*[:=]\s*true",
    r"isPublicClient",
]

SPA_PATTERNS = [
    r"@angular/",
    r"react-dom",
    r"\bcreate-react-app\b",
    r"next\.config",
    r"apps/web",
]

CODE_EXTS = (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".py",
             ".go", ".java", ".rs", ".html")


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


def _scan(root: Path) -> dict:
    findings = {
        "oauth_detected": False,
        "oauth_files": [],       # files with OAuth activity
        "pkce_challenge": False,
        "pkce_method": None,     # "S256" | "plain" | None
        "state_set": False,
        "state_verified": False,
        "nonce_set": False,
        "nonce_verified": False,
        "public_client_hints": [],
        "spa_hints": [],
        "files_scanned": 0,
    }
    oauth_re = re.compile("|".join(OAUTH_LIB_PATTERNS), re.IGNORECASE)
    public_re = re.compile("|".join(PUBLIC_CLIENT_PATTERNS), re.IGNORECASE)
    spa_re = re.compile("|".join(SPA_PATTERNS), re.IGNORECASE)

    for f in _iter_code_files(root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings["files_scanned"] += 1

        hit_oauth = False
        if oauth_re.search(text):
            findings["oauth_detected"] = True
            findings["oauth_files"].append(str(f))
            hit_oauth = True

        if hit_oauth or "oauth" in text.lower()[:2000]:
            if PKCE_CHALLENGE_RE.search(text):
                findings["pkce_challenge"] = True
            m = PKCE_METHOD_ANY_RE.search(text)
            if m:
                findings["pkce_method"] = m.group(1).upper()

            if STATE_SET_RE.search(text):
                findings["state_set"] = True
            if STATE_VERIFY_RE.search(text):
                findings["state_verified"] = True

            if NONCE_SET_RE.search(text):
                findings["nonce_set"] = True
            if NONCE_VERIFY_RE.search(text):
                findings["nonce_verified"] = True

        if public_re.search(text):
            findings["public_client_hints"].append(str(f))
        if spa_re.search(text):
            findings["spa_hints"].append(str(f))

    return findings


def _evaluate(sast: dict) -> tuple[str, list[str], list[str]]:
    """Returns (verdict, blocks, warns)."""
    blocks: list[str] = []
    warns: list[str] = []

    if not sast["oauth_detected"]:
        return "NO_OAUTH", [], []

    is_public = bool(sast["public_client_hints"]) or bool(sast["spa_hints"])

    # PKCE challenge presence
    if not sast["pkce_challenge"]:
        if is_public:
            blocks.append(
                "PKCE code_challenge not found — MANDATORY for public "
                "client (SPA/mobile). Authorization code is interceptable."
            )
        else:
            warns.append(
                "PKCE code_challenge not found — recommended even for "
                "confidential clients (defense in depth)"
            )
    else:
        # Present but wrong method
        method = sast["pkce_method"]
        if method and method != "S256":
            blocks.append(
                f"PKCE code_challenge_method={method!r} — must be 'S256'. "
                f"'plain' is deprecated and insecure."
            )
        elif method is None:
            warns.append(
                "code_challenge present but method not declared — "
                "must explicitly set code_challenge_method='S256'"
            )

    # State verification
    if not sast["state_set"]:
        blocks.append(
            "OAuth state parameter not set — required CSRF protection"
        )
    elif not sast["state_verified"]:
        blocks.append(
            "OAuth state set but no verification pattern detected on "
            "callback — state must be compared against stored value"
        )

    # Nonce (OIDC) — WARN only, not all flows are OIDC
    if sast["nonce_set"] and not sast["nonce_verified"]:
        warns.append(
            "nonce set but no verification — replayable id_token risk"
        )

    verdict = "FAIL" if blocks else ("WARN" if warns else "OK")
    return verdict, blocks, warns


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--declared-flows",
                    help="optional SECURITY-TEST-PLAN.md path for cross-check")
    ap.add_argument("--allow-warn", action="store_true")
    # Orchestrator dispatch passes --phase to every validator. SAST
    # scans whole project regardless of phase; accept the arg to avoid
    # argparse crash.
    ap.add_argument("--phase", help="(orchestrator-injected; ignored by SAST scan)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = Path(args.project_root).resolve()
    if not root.exists():
        print(f"\033[38;5;208mproject-root does not exist: {root}\033[0m", file=sys.stderr)
        return 2

    sast = _scan(root)
    verdict, blocks, warns = _evaluate(sast)

    # v2.6.1 (2026-04-26): canonicalize verdict for orchestrator schema.
    _canonical = {"FAIL": "BLOCK", "OK": "PASS", "WARN": "WARN"}.get(verdict, verdict)

    output = {
        "validator": "verify-oauth-pkce-enforcement",
        "verdict": _canonical,
        "oauth_detected": sast["oauth_detected"],
        "is_public_client_hint": (
            bool(sast["public_client_hints"]) or bool(sast["spa_hints"])
        ),
        "blocks": blocks,
        "warns": warns,
        "sast_summary": {
            "pkce_challenge": sast["pkce_challenge"],
            "pkce_method": sast["pkce_method"],
            "state_set": sast["state_set"],
            "state_verified": sast["state_verified"],
            "nonce_set": sast["nonce_set"],
            "nonce_verified": sast["nonce_verified"],
            "files_scanned": sast["files_scanned"],
        },
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        if verdict == "NO_OAUTH":
            if not args.quiet:
                print("✓ No OAuth code detected — nothing to verify.")
        elif verdict == "FAIL":
            print(f"\033[38;5;208mOAuth PKCE: {len(blocks)} block(s), {len(warns)} warn(s)\033[0m")
            for b in blocks:
                print(f"  [BLOCK] {b}")
            for w in warns:
                print(f"  [WARN]  {w}")
        elif verdict == "WARN":
            if not args.quiet:
                print(f"\033[33mOAuth PKCE: {len(warns)} warn(s)\033[0m")
                for w in warns:
                    print(f"  [WARN]  {w}")
        elif not args.quiet:
            print("✓ OAuth PKCE + state + nonce OK")

    if verdict == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
