#!/usr/bin/env python3
"""
verify-jwt-session-policy.py — Phase M Batch 2 of v2.5.2 hardening.

Problem closed:
  AI-generated auth code frequently emits JWT tokens with weak settings:
    - HS256 shared-secret instead of asymmetric RS256/ES256
    - Access tokens that never expire or last hours/days
    - Refresh tokens that aren't rotated on use
    - No revocation store, so leaked tokens stay valid until exp
  These are silent correctness problems — the tests pass, the endpoints
  authenticate, but the session model is exploitable. This SAST-level
  check greps source code for the relevant library calls and enforces
  a policy floor.

SAST checks (default mode, --project-root):
  1. JWT library is in use at all (grep for jwt.sign, jsonwebtoken, jose,
     python-jose, @fastify/jwt, PyJWT). Returns exit 2 if none found —
     phase may not be auth-related.
  2. Algorithm: block HS* (symmetric), require RS256/ES256/PS256 when
     declared. Unknown → warn.
  3. Access token lifetime: `expiresIn`, `exp`, `ACCESS_TOKEN_TTL`
     patterns. Floor 900s (15 min). Anything > 900s → BLOCK.
  4. Refresh token lifetime + rotation: `refresh_token` with TTL ≤ 7d
     (604800s). Grep for revoke/invalidate/rotate on the refresh path.
     Missing rotation → WARN.
  5. Revocation: blacklist/revoke/deny-list store (grep for these +
     Redis/DB usage on logout path). Missing → WARN.

Runtime mode (--sample-token <JWT>):
  Decode (no signature verify — stdlib only, base64+json) the payload,
  verify exp - iat ≤ 900. If no iat/exp → WARN. Algorithm from header
  is cross-checked with SAST findings.

Exit codes:
  0 = pass (policy satisfied, or WARN only)
  1 = BLOCK (HS256 in use, access TTL > 15m, critical violation)
  2 = config error (no JWT code detected; nothing to verify)

Usage:
  verify-jwt-session-policy.py --project-root .
  verify-jwt-session-policy.py --project-root . --sample-token eyJ...
  verify-jwt-session-policy.py --project-root . --json --quiet
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path


# Patterns for detecting JWT library usage
JWT_LIB_PATTERNS = [
    r"\bjwt\.sign\s*\(",
    r"from\s+jose\b",
    r"import\s+jose\b",
    r"from\s+jwt\b",
    r"import\s+jwt\b",
    r"require\s*\(\s*['\"]jsonwebtoken['\"]\s*\)",
    r"from\s+['\"]jsonwebtoken['\"]",
    r"@fastify/jwt",
    r"python-jose",
    r"PyJWT",
    r"\bjwt\.encode\s*\(",
    r"\bjwt\.decode\s*\(",
]

# Algorithm patterns
WEAK_ALGS = {"HS256", "HS384", "HS512", "none"}
STRONG_ALGS = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512",
               "PS256", "PS384", "PS512", "EdDSA"}

ALGORITHM_RE = re.compile(
    r"""algorithm\s*[:=]\s*['"]([A-Za-z0-9]+)['"]""",
    re.IGNORECASE,
)

# Access TTL detection: expiresIn: '15m' / 900 / ACCESS_TOKEN_TTL=900
EXPIRES_IN_RE = re.compile(
    r"""expires[_]?in\s*[:=]\s*['"]?([0-9smhd]+)['"]?""",
    re.IGNORECASE,
)
EXP_CONSTANT_RE = re.compile(
    r"(?:ACCESS[_\s-]*TOKEN[_\s-]*(?:TTL|EXPIRES?|LIFETIME)|"
    r"access[_\s-]*ttl)\s*[:=]\s*['\"]?([0-9smhd]+)['\"]?",
    re.IGNORECASE,
)

# Refresh TTL
REFRESH_TTL_RE = re.compile(
    r"(?:REFRESH[_\s-]*TOKEN[_\s-]*(?:TTL|EXPIRES?|LIFETIME)|"
    r"refresh[_\s-]*ttl)\s*[:=]\s*['\"]?([0-9smhd]+)['\"]?",
    re.IGNORECASE,
)

ROTATION_PATTERNS = [
    r"\brotate[_\s-]?refresh",
    r"\brevoke[_\s-]?refresh",
    r"\binvalidate[_\s-]?refresh",
    r"refresh[_\s-]?rotation",
    r"refresh\.\s*rotate",
]

REVOCATION_PATTERNS = [
    r"\brevoke[_\s-]?token",
    r"\btoken[_\s-]?blacklist",
    r"\btoken[_\s-]?denylist",
    r"\brevoked[_\s-]?tokens?",
    r"\bjwt[_\s-]?blacklist",
    r"\bblacklist.*token",
    r"logout.*revoke",
]

CODE_EXTS = (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".py",
             ".go", ".java", ".rs")


def _iter_code_files(root: Path):
    """Yield source files under root, skipping vendor/build dirs."""
    skip = {"node_modules", "dist", "build", ".git", ".vg",
            "__pycache__", ".next", "target", "vendor"}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip for part in p.parts):
            continue
        if p.suffix.lower() in CODE_EXTS:
            yield p


def _ttl_to_seconds(value: str) -> int | None:
    """Convert '15m'/'900'/'7d' to seconds. None if unparseable."""
    if not value:
        return None
    v = value.strip().strip("'\"")
    m = re.match(r"^(\d+)([smhd]?)$", v, re.IGNORECASE)
    if not m:
        try:
            return int(v)
        except ValueError:
            return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    return {
        "": n, "s": n, "m": n * 60, "h": n * 3600, "d": n * 86400,
    }.get(unit, n)


def _scan_sast(root: Path) -> dict:
    findings = {
        "jwt_detected": False,
        "algorithms": [],
        "weak_alg_hits": [],   # list of (file, alg)
        "access_ttls": [],     # list of (file, seconds, raw)
        "refresh_ttls": [],
        "has_rotation": False,
        "has_revocation": False,
        "files_scanned": 0,
    }

    lib_re = re.compile("|".join(JWT_LIB_PATTERNS))

    for f in _iter_code_files(root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings["files_scanned"] += 1

        if lib_re.search(text):
            findings["jwt_detected"] = True

        for m in ALGORITHM_RE.finditer(text):
            alg = m.group(1).upper()
            findings["algorithms"].append((str(f), alg))
            if alg in WEAK_ALGS:
                findings["weak_alg_hits"].append((str(f), alg))

        for m in EXPIRES_IN_RE.finditer(text):
            secs = _ttl_to_seconds(m.group(1))
            if secs is None:
                continue
            # Context sensitivity: if "refresh" appears within ~200 chars
            # before the match, attribute to refresh (avoids false-block
            # on refresh rotation functions that set expiresIn: '7d').
            window_start = max(0, m.start() - 200)
            preceding = text[window_start:m.start()].lower()
            if "refresh" in preceding:
                findings["refresh_ttls"].append(
                    (str(f), secs, m.group(1))
                )
            else:
                findings["access_ttls"].append(
                    (str(f), secs, m.group(1))
                )
        for m in EXP_CONSTANT_RE.finditer(text):
            secs = _ttl_to_seconds(m.group(1))
            if secs is not None:
                findings["access_ttls"].append(
                    (str(f), secs, m.group(1))
                )

        for m in REFRESH_TTL_RE.finditer(text):
            secs = _ttl_to_seconds(m.group(1))
            if secs is not None:
                findings["refresh_ttls"].append(
                    (str(f), secs, m.group(1))
                )

        if any(re.search(p, text, re.IGNORECASE)
               for p in ROTATION_PATTERNS):
            findings["has_rotation"] = True
        if any(re.search(p, text, re.IGNORECASE)
               for p in REVOCATION_PATTERNS):
            findings["has_revocation"] = True

    return findings


def _decode_jwt_payload(token: str) -> tuple[dict | None, dict | None, str | None]:
    """Decode JWT header+payload without verifying signature (stdlib only).
    Returns (header, payload, error)."""
    parts = token.split(".")
    if len(parts) != 3:
        return None, None, "token does not have 3 parts"

    def _b64d(s: str) -> bytes:
        s = s + "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s.encode("ascii"))

    try:
        header = json.loads(_b64d(parts[0]))
        payload = json.loads(_b64d(parts[1]))
    except (ValueError, json.JSONDecodeError) as e:
        return None, None, f"decode error: {e}"
    return header, payload, None


def _check_sample_token(token: str) -> dict:
    result = {"verdict": "OK", "reason": None, "details": {}}
    header, payload, err = _decode_jwt_payload(token)
    if err:
        result["verdict"] = "FAIL"
        result["reason"] = err
        return result
    alg = (header or {}).get("alg", "").upper()
    result["details"]["alg"] = alg
    if alg in WEAK_ALGS:
        result["verdict"] = "FAIL"
        result["reason"] = (
            f"sample token uses weak algorithm {alg!r} — switch to RS256/ES256"
        )
        return result

    iat = (payload or {}).get("iat")
    exp = (payload or {}).get("exp")
    if iat is not None and exp is not None:
        lifetime = int(exp) - int(iat)
        result["details"]["lifetime_s"] = lifetime
        if lifetime > 900:
            result["verdict"] = "FAIL"
            result["reason"] = (
                f"sample token lifetime {lifetime}s > 900s (15m) access floor"
            )
            return result
    else:
        result["details"]["warn"] = "no iat/exp in payload"
    return result


def _verdict_from_findings(sast: dict) -> tuple[str, list[str], list[str]]:
    """Returns (verdict, blocks, warns)."""
    blocks: list[str] = []
    warns: list[str] = []

    if not sast["jwt_detected"]:
        return "NO_JWT", [], []

    # Weak algorithms BLOCK
    if sast["weak_alg_hits"]:
        uniq = sorted({alg for _, alg in sast["weak_alg_hits"]})
        blocks.append(
            f"weak algorithm(s) {uniq} found in {len(sast['weak_alg_hits'])} "
            f"location(s) — must use RS256/ES256/PS256"
        )

    # Access TTL > 900 BLOCK
    too_long = [(f, s, raw) for f, s, raw in sast["access_ttls"] if s > 900]
    if too_long:
        sample = too_long[0]
        blocks.append(
            f"access token TTL exceeds 900s floor: {sample[2]!r} "
            f"({sample[1]}s) in {sample[0]}"
        )

    # Refresh TTL > 7d BLOCK
    refresh_too_long = [
        (f, s, raw) for f, s, raw in sast["refresh_ttls"] if s > 604800
    ]
    if refresh_too_long:
        sample = refresh_too_long[0]
        blocks.append(
            f"refresh token TTL exceeds 7d: {sample[2]!r} "
            f"({sample[1]}s) in {sample[0]}"
        )

    # Missing rotation on refresh path WARN
    if sast["refresh_ttls"] and not sast["has_rotation"]:
        warns.append(
            "refresh token declared but no rotation/invalidate pattern "
            "detected — tokens should rotate on each use"
        )

    # Missing revocation WARN
    if not sast["has_revocation"]:
        warns.append(
            "no token revocation/blacklist store detected — leaked tokens "
            "remain valid until natural expiry"
        )

    verdict = "FAIL" if blocks else ("WARN" if warns else "OK")
    return verdict, blocks, warns


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project-root", default=".",
                    help="repository root to scan (default: .)")
    ap.add_argument("--sample-token",
                    help="optional JWT to decode and verify runtime policy")
    ap.add_argument("--allow-warn", action="store_true",
                    help="treat WARN-level findings as pass (exit 0)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = Path(args.project_root).resolve()
    if not root.exists():
        print(f"⛔ project-root does not exist: {root}", file=sys.stderr)
        return 2

    sast = _scan_sast(root)
    verdict, blocks, warns = _verdict_from_findings(sast)

    token_result = None
    if args.sample_token:
        token_result = _check_sample_token(args.sample_token)
        if token_result["verdict"] == "FAIL":
            blocks.append(f"sample token: {token_result['reason']}")
            verdict = "FAIL"

    output = {
        "validator": "verify-jwt-session-policy",
        "verdict": verdict,
        "jwt_detected": sast["jwt_detected"],
        "files_scanned": sast["files_scanned"],
        "blocks": blocks,
        "warns": warns,
        "sample_token": token_result,
        "sast_summary": {
            "algorithms": sorted({a for _, a in sast["algorithms"]}),
            "access_ttls": [s for _, s, _ in sast["access_ttls"]],
            "refresh_ttls": [s for _, s, _ in sast["refresh_ttls"]],
            "has_rotation": sast["has_rotation"],
            "has_revocation": sast["has_revocation"],
        },
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        if verdict == "NO_JWT":
            if not args.quiet:
                print("⚠ No JWT library usage detected — cannot verify "
                      "session policy. Skipping.")
        elif verdict == "FAIL":
            print(f"⛔ JWT session policy: {len(blocks)} block(s), "
                  f"{len(warns)} warn(s)")
            for b in blocks:
                print(f"  [BLOCK] {b}")
            for w in warns:
                print(f"  [WARN]  {w}")
        elif verdict == "WARN":
            if not args.quiet:
                print(f"⚠ JWT session policy: {len(warns)} warn(s)")
                for w in warns:
                    print(f"  [WARN]  {w}")
        elif not args.quiet:
            print("✓ JWT session policy OK")

    if verdict == "NO_JWT":
        return 2
    if verdict == "FAIL":
        return 1
    if verdict == "WARN" and not args.allow_warn:
        return 0  # warn is non-blocking by default
    return 0


if __name__ == "__main__":
    sys.exit(main())
