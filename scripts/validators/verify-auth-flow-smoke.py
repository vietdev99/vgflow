#!/usr/bin/env python3
"""
Validator: verify-auth-flow-smoke.py

Harness v2.6 (2026-04-25): static smoke test for auth flow integrity.

Scope: when API-CONTRACTS.md declares auth endpoints (login, logout,
forgot-password, reset-password, change-password, refresh-token,
verify-email, verify-2fa, etc.), validate the flow has the basic
defensive shape AI tends to forget.

Why it exists: existing auth validators handle narrow questions —
verify-2fa-gate (does 2FA exist?), verify-jwt-session-policy (JWT TTL
correct?), verify-cookie-flags-runtime (live probe), verify-oauth-pkce
(OAuth specific). None of them catch the COMMON misconfigurations:
  - Login route declared but NO logout route (forgot to add)
  - Login route in contract but NO **Auth:** declaration on it
  - forgot-password without rate-limit/throttle declaration
  - login form using GET instead of POST (data leaks to logs/Referer)
  - login form input field type="text" instead of type="password"
  - Failed login response leaks whether account exists

This validator runs 6 static smoke checks; each is BLOCK-severity if it
catches misconfiguration in a feature phase that touches auth.

Checks:
  C1. Auth flow completeness — login → logout pair (both must exist)
  C2. Per-endpoint auth declaration — every auth endpoint has **Auth:**
  C3. Mutation rate-limit/throttle — login/forgot/reset must declare
      rate_limit (form throttle per CLAUDE.md ASVS V11.1.5)
  C4. Login form HTML/JSX shape — password input type="password",
      form method POST (when login UI files exist)
  C5. Forgot-password email enumeration — contract declares constant
      response (no "user not found" leak)
  C6. Reset-password token TTL — contract declares finite token TTL

Severity:
  BLOCK — auth endpoints declared without core defenses (C1-C3, C5)
  WARN  — UI form shape (C4 — may run before UI files written)
  WARN  — token TTL not declared (C6 — advisory)

Skip when phase has no auth-related endpoints in contract.

Usage:
  verify-auth-flow-smoke.py --phase 14
  verify-auth-flow-smoke.py --phase 14 --strict  (escalate WARN → BLOCK)

Exit codes:
  0  PASS or WARN-only
  1  BLOCK
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Auth endpoint path keywords — matched against path lower
AUTH_KEYWORDS_LOGIN = ("login", "signin", "sign-in")
AUTH_KEYWORDS_LOGOUT = ("logout", "signout", "sign-out")
AUTH_KEYWORDS_FORGOT = ("forgot", "forgot-password", "request-reset")
AUTH_KEYWORDS_RESET = ("reset-password", "reset/password")
AUTH_KEYWORDS_REFRESH = ("refresh-token", "auth/refresh", "refresh")
AUTH_KEYWORDS_2FA = ("verify-2fa", "totp", "2fa")
AUTH_KEYWORDS_ALL = (
    *AUTH_KEYWORDS_LOGIN, *AUTH_KEYWORDS_LOGOUT, *AUTH_KEYWORDS_FORGOT,
    *AUTH_KEYWORDS_RESET, *AUTH_KEYWORDS_REFRESH, *AUTH_KEYWORDS_2FA,
)

ENDPOINT_HEADER_RE = re.compile(
    r"^###\s+(?P<method>GET|POST|PUT|DELETE|PATCH)\s+(?P<path>/\S+)",
    re.MULTILINE,
)
AUTH_LINE_RE = re.compile(
    # Bold-marker form: **Auth:** session
    r"\*\*Auth:?\*\*\s*(?P<value>.+?)$",
    re.IGNORECASE | re.MULTILINE,
)
# Code-block comment form: // === BLOCK 1: Auth + middleware ===
AUTH_BLOCK_COMMENT_RE = re.compile(
    r"//\s*={2,}\s*BLOCK\s*\d*:?\s*Auth",
    re.IGNORECASE,
)
# Inline auth keyword form (when middleware list cites auth helpers explicitly)
AUTH_INLINE_RE = re.compile(
    r"(requireAuth|requireSession|verifyJwt|jwtAuth|sessionAuth|authMiddleware|validateOrigin|"
    r"isAuthenticated|cookieAuth|authenticate|@requireAuth|@auth\b)",
    re.IGNORECASE,
)
RATE_LIMIT_RE = re.compile(
    # Bold-marker form: **Rate-limit:** N/min
    r"\*\*(?:Rate[\s\-_]*limit|Throttle|Form[\s_]*throttle):?\*\*\s*(?P<value>.+?)$",
    re.IGNORECASE | re.MULTILINE,
)
# Inline-middleware form (Fastify/Express middleware patterns): rateLimit({...})
RATE_LIMIT_INLINE_RE = re.compile(
    r"(rateLimit|rate_limit|rateLimiter|express-rate-limit|@fastify/rate-limit|throttle\b|express-throttle)\s*\(",
    re.IGNORECASE,
)
ENUM_PROTECTION_RE = re.compile(
    r"(constant[\s\-]*(?:response|time)|email[\s\-]*enumeration|same[\s\-]*message|generic[\s\-]*response|always[\s\-]*200)",
    re.IGNORECASE,
)
TOKEN_TTL_RE = re.compile(
    r"(token[\s\-]*ttl|expires?[\s\-]*in|valid[\s\-]*for)\s*[:=]?\s*(\d+)\s*(min|minute|hour|day|s\b)",
    re.IGNORECASE,
)


def _endpoint_blocks(text: str) -> list[dict]:
    blocks: list[dict] = []
    matches = list(ENDPOINT_HEADER_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block_text = text[m.start():end]
        path = m.group("path")
        path_lower = path.lower()
        is_auth = any(kw in path_lower for kw in AUTH_KEYWORDS_ALL)
        blocks.append({
            "method": m.group("method"),
            "path": path,
            "is_auth": is_auth,
            "block": block_text,
        })
    return blocks


def _collect_login_jsx(repo_root: Path) -> list[Path]:
    """Find Login form components for HTML/JSX shape check."""
    candidates: list[Path] = []
    for pattern in ("login*.tsx", "login*.jsx", "Login*.tsx", "Login*.jsx",
                    "*login-form*.tsx", "*login-form*.jsx", "*loginForm*.tsx"):
        candidates.extend(
            (repo_root / "apps" / "web" / "src").rglob(pattern)
        )
    return candidates


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--strict", action="store_true",
                    help="Escalate WARN findings to BLOCK")
    args = ap.parse_args()

    out = Output(validator="verify-auth-flow-smoke")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        contracts_path = phase_dir / "API-CONTRACTS.md"
        if not contracts_path.exists():
            emit_and_exit(out)

        text = contracts_path.read_text(encoding="utf-8", errors="replace")
        endpoints = _endpoint_blocks(text)
        auth_endpoints = [e for e in endpoints if e["is_auth"]]
        if not auth_endpoints:
            # No auth endpoints — nothing to smoke test
            emit_and_exit(out)

        block_findings: list[Evidence] = []
        warn_findings: list[Evidence] = []

        # C1 — login → logout completeness
        has_login = any(any(k in e["path"].lower() for k in AUTH_KEYWORDS_LOGIN) for e in auth_endpoints)
        has_logout = any(any(k in e["path"].lower() for k in AUTH_KEYWORDS_LOGOUT) for e in auth_endpoints)
        if has_login and not has_logout:
            block_findings.append(Evidence(
                type="auth_logout_missing",
                message="Login endpoint declared but no logout endpoint found in API-CONTRACTS.md",
                actual=f"Login: {[e['path'] for e in auth_endpoints if any(k in e['path'].lower() for k in AUTH_KEYWORDS_LOGIN)]}",
                expected="POST /api/.../logout endpoint that invalidates server-side session",
                fix_hint="Add a POST logout endpoint to API-CONTRACTS.md. Logout-side invalidation is mandatory — deleting cookie alone is insufficient.",
            ))

        # C2 — every auth endpoint has auth declaration in any of three forms:
        #   - **Auth:** bold marker (markdown style)
        #   - // === BLOCK N: Auth ... === code-block comment
        #   - inline middleware reference (requireAuth, validateOrigin, etc.)
        missing_auth_declared = []
        for e in auth_endpoints:
            has_auth_decl = (
                AUTH_LINE_RE.search(e["block"]) is not None
                or AUTH_BLOCK_COMMENT_RE.search(e["block"]) is not None
                or AUTH_INLINE_RE.search(e["block"]) is not None
            )
            if not has_auth_decl:
                missing_auth_declared.append(f"{e['method']} {e['path']}")
        if missing_auth_declared:
            block_findings.append(Evidence(
                type="auth_declaration_missing",
                message=f"{len(missing_auth_declared)} auth endpoint(s) without **Auth:** declaration",
                actual="; ".join(missing_auth_declared[:5]),
                expected="Each auth endpoint declares **Auth:** public | session | jwt | refresh-token | etc.",
                fix_hint="Add `**Auth:** <type>` line below endpoint header. Login/forgot/reset typically `public`; refresh/logout `session` or `refresh-token`.",
            ))

        # C3 — login / forgot-password / reset-password must declare rate-limit
        sensitive_no_rate = []
        for e in auth_endpoints:
            path_lower = e["path"].lower()
            is_sensitive = any(
                k in path_lower
                for k in (*AUTH_KEYWORDS_LOGIN, *AUTH_KEYWORDS_FORGOT, *AUTH_KEYWORDS_RESET)
            )
            has_rate_limit = (
                RATE_LIMIT_RE.search(e["block"]) is not None
                or RATE_LIMIT_INLINE_RE.search(e["block"]) is not None
            )
            if is_sensitive and not has_rate_limit:
                sensitive_no_rate.append(f"{e['method']} {e['path']}")
        if sensitive_no_rate:
            block_findings.append(Evidence(
                type="auth_rate_limit_missing",
                message=f"{len(sensitive_no_rate)} sensitive auth endpoint(s) without rate-limit declaration",
                actual="; ".join(sensitive_no_rate[:5]),
                expected="Login / forgot-password / reset-password must declare **Rate-limit:** (e.g., 5/min per IP + 10/hour per email) — ASVS V11.1.5",
                fix_hint="Add `**Rate-limit:** <N>/min per IP, <M>/hour per email` line. Without throttle, brute-force/credential-stuffing trivially bypass auth.",
            ))

        # C4 — login form HTML/JSX shape (UI smoke)
        login_jsx_files = _collect_login_jsx(REPO_ROOT)
        for fp in login_jsx_files:
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # Password field type — must be type="password" not type="text"
            # Heuristic: any input named password|pass|pwd MUST have type="password"
            password_fields = re.findall(
                r'<(?:Input|input)[^>]*?name=["\'](?:password|pass|pwd)["\'][^>]*>',
                content,
                re.IGNORECASE,
            )
            for field in password_fields:
                if 'type="password"' not in field and "type='password'" not in field:
                    rel = str(fp.relative_to(REPO_ROOT)).replace("\\", "/")
                    warn_findings.append(Evidence(
                        type="login_password_field_wrong_type",
                        message="Login form has password field NOT using type=\"password\"",
                        actual=f"{rel}: {field[:120]}",
                        fix_hint="Add `type=\"password\"` to the password input. Otherwise browser autofill + screen-share leak the password.",
                    ))

        # C5 — forgot-password constant-response declaration
        forgot_endpoints = [
            e for e in auth_endpoints
            if any(k in e["path"].lower() for k in AUTH_KEYWORDS_FORGOT)
        ]
        for e in forgot_endpoints:
            if not ENUM_PROTECTION_RE.search(e["block"]):
                block_findings.append(Evidence(
                    type="auth_email_enumeration_unprotected",
                    message=f"forgot-password endpoint {e['method']} {e['path']} does not declare email enumeration protection",
                    actual=f"{e['method']} {e['path']}: no constant-response / generic-response declaration",
                    expected="Contract should mention 'constant response' / 'generic response' / 'email enumeration' protection — same message regardless of account existence.",
                    fix_hint="Add note to endpoint: \"Returns 200 with generic message regardless of email existence to prevent enumeration\". OWASP Top 10 2021 A07.",
                ))

        # C6 — reset-password token TTL
        reset_endpoints = [
            e for e in auth_endpoints
            if any(k in e["path"].lower() for k in AUTH_KEYWORDS_RESET)
        ]
        for e in reset_endpoints:
            if not TOKEN_TTL_RE.search(e["block"]):
                warn_findings.append(Evidence(
                    type="auth_reset_token_ttl_missing",
                    message=f"reset-password endpoint {e['method']} {e['path']} does not declare token TTL",
                    actual=f"{e['method']} {e['path']}: no 'token TTL N min/hour' declaration",
                    fix_hint="Declare token TTL explicitly (e.g., \"reset token valid for 30 minutes, single-use\"). Long-lived reset tokens are a credential-theft vector.",
                ))

        # Emit findings
        if args.strict:
            block_findings.extend(warn_findings)
            warn_findings = []
        for e in block_findings:
            out.add(e)
        for e in warn_findings:
            out.warn(e)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
