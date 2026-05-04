#!/usr/bin/env python3
"""
Validator: verify-security-baseline.py

Phase B.3 v2.5 (2026-04-23): project-wide security baseline verification.

Reads FOUNDATION.md §9 (optional) + vg.config.md security_baseline block,
then greps the codebase and deploy configs to verify implementation meets
baseline. Project-wide — not per-phase.

Severity matrix:
- TLS < 1.2 explicitly enabled → HARD BLOCK
- Wildcard CORS (origin '*') + credentials: true → HARD BLOCK
- Real secret (32+ char base64 / UUID v4 / JWT) in .env.example → HARD BLOCK
- Missing security headers middleware (Helmet etc.) → WARN
- Missing HSTS header (when require_hsts=true) → WARN
- Missing cookie flags (Secure/HttpOnly/SameSite) → WARN
- Missing dependency lockfile → WARN
- CORS preflight maxAge > 86400 → WARN

Scope modes:
- repo   — grep source code only
- deploy — check deploy scripts only
- all    — both (default)

Usage:
  verify-security-baseline.py [--phase <N>] [--scope repo|deploy|all]

Exit codes:
  0 PASS or WARN
  1 BLOCK
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# ─────────────────────────────────────────────────────────────────────────
# Config parsing
# ─────────────────────────────────────────────────────────────────────────


def _read_config() -> dict:
    """Read security_baseline block from vg.config.md."""
    defaults = {
        "enabled": True,
        "tls_config_globs": [
            "infra/**/nginx*.conf",
            "infra/**/Caddyfile",
            "infra/**/caddyfile",
            "infra/ansible/**/*.yml",
            "infra/ansible/**/*.yaml",
            "nginx.conf",
            "Caddyfile",
        ],
        "api_routes_globs": [
            "apps/api/src/**/*.ts",
            "apps/api/src/**/*.js",
            "apps/*/src/**/*.ts",
            "apps/*/src/**/*.js",
            "src/**/*.ts",
            "src/**/*.js",
            "server/**/*.ts",
            "server/**/*.js",
            "routes/**/*.ts",
            "routes/**/*.js",
        ],
        "require_hsts": True,
        "allow_cors_wildcard_no_credentials": True,
    }

    cfg = REPO_ROOT / ".claude" / "vg.config.md"
    if not cfg.exists():
        return defaults

    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return defaults

    # Extract security_baseline: block (2-space indented keys)
    m = re.search(
        r"^security_baseline:\s*\n((?:\s{2,}.*\n?)+)",
        text, re.MULTILINE,
    )
    if not m:
        return defaults
    block = m.group(1)

    bool_match = re.search(
        r"^\s+enabled:\s*(true|false)", block, re.MULTILINE | re.IGNORECASE,
    )
    if bool_match:
        defaults["enabled"] = bool_match.group(1).lower() == "true"

    hsts_match = re.search(
        r"^\s+require_hsts:\s*(true|false)", block,
        re.MULTILINE | re.IGNORECASE,
    )
    if hsts_match:
        defaults["require_hsts"] = hsts_match.group(1).lower() == "true"

    cors_allow = re.search(
        r"^\s+allow_cors_wildcard_no_credentials:\s*(true|false)",
        block, re.MULTILINE | re.IGNORECASE,
    )
    if cors_allow:
        defaults["allow_cors_wildcard_no_credentials"] = (
            cors_allow.group(1).lower() == "true"
        )

    # tls_config_globs: [ ... ]
    globs_match = re.search(
        r"^\s+tls_config_globs:\s*\[([^\]]+)\]", block, re.MULTILINE,
    )
    if globs_match:
        items = [
            x.strip().strip("'\"") for x in globs_match.group(1).split(",")
        ]
        items = [x for x in items if x]
        if items:
            defaults["tls_config_globs"] = items

    return defaults


# ─────────────────────────────────────────────────────────────────────────
# File collection helpers
# ─────────────────────────────────────────────────────────────────────────


def _resolve_globs(patterns: list[str]) -> list[Path]:
    """Resolve list of glob patterns against REPO_ROOT."""
    seen: set[Path] = set()
    result: list[Path] = []
    for pat in patterns:
        for p in REPO_ROOT.glob(pat):
            if p.is_file() and p not in seen:
                seen.add(p)
                result.append(p)
    return result


def _strip_comments(text: str, comment_char: str = "#") -> str:
    """Remove lines starting with comment_char (leading whitespace allowed)."""
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(comment_char):
            continue
        out.append(line)
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────
# Check 1: TLS baseline
# ─────────────────────────────────────────────────────────────────────────

TLS_OUTDATED_RE = re.compile(
    r"(?:ssl_protocols[^;#\n]*|tls_min_version\s*[:=]\s*['\"]?|protocols\s+)"
    r".*?(TLSv1\.0|TLSv1\.1|SSLv3|SSLv2)",
    re.IGNORECASE,
)
# Caddy/nginx/go also: tls_min_version "1.0" | "1.1"
TLS_MIN_LOW_RE = re.compile(
    r"tls_min_version\s*[:=]?\s*['\"]?1\.[01]\b",
    re.IGNORECASE,
)
TLS_GOOD_RE = re.compile(
    r"(?:ssl_protocols\s+[^;#\n]*TLSv1\.[23]"
    r"|tls_min_version\s*[:=]?\s*['\"]?1\.[23]"
    r"|min_version\s*[:=]\s*(?:tls|VersionTLS)1[23])",
    re.IGNORECASE,
)


def _check_tls(cfg: dict, out: Output) -> None:
    files = _resolve_globs(cfg["tls_config_globs"])
    if not files:
        out.warn(Evidence(
            type="tls_config_not_found",
            message=t("sec_baseline.tls_config_not_found.message"),
            fix_hint=t("sec_baseline.tls_config_not_found.fix_hint"),
        ))
        return

    outdated_hits: list[tuple[Path, int, str]] = []
    has_good = False

    for fp in files:
        try:
            raw = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Comment char varies: # for nginx/yaml/caddy; // for JSON5-ish — stick with #
        cleaned = _strip_comments(raw, "#")
        for m in TLS_OUTDATED_RE.finditer(cleaned):
            line_num = cleaned[:m.start()].count("\n") + 1
            outdated_hits.append((fp, line_num, m.group(0)[:80]))
        for m in TLS_MIN_LOW_RE.finditer(cleaned):
            line_num = cleaned[:m.start()].count("\n") + 1
            outdated_hits.append((fp, line_num, m.group(0)[:80]))
        if TLS_GOOD_RE.search(cleaned):
            has_good = True

    if outdated_hits:
        sample = "; ".join(
            f"{fp.relative_to(REPO_ROOT).as_posix()}:{ln} [{text.strip()}]"
            for fp, ln, text in outdated_hits[:5]
        )
        out.add(Evidence(
            type="tls_outdated",
            message=t(
                "sec_baseline.tls_outdated.message",
                count=len(outdated_hits),
            ),
            actual=sample,
            fix_hint=t("sec_baseline.tls_outdated.fix_hint"),
        ))
        return

    if not has_good:
        # No explicit good TLS found and no outdated — advisory
        out.warn(Evidence(
            type="tls_config_not_found",
            message=t("sec_baseline.tls_config_not_found.message"),
            fix_hint=t("sec_baseline.tls_config_not_found.fix_hint"),
        ))


# ─────────────────────────────────────────────────────────────────────────
# Check 2: Security headers middleware
# ─────────────────────────────────────────────────────────────────────────

HELMET_RE = re.compile(
    r"(?:require\s*\(\s*['\"](?:@fastify/helmet|helmet|koa-helmet|"
    r"fastify-helmet)['\"]\s*\)"
    r"|import\s+[^;]*?from\s+['\"](?:@fastify/helmet|helmet|koa-helmet|"
    r"fastify-helmet)['\"]"
    r"|\bsecurityHeaders\b"
    r"|\bhelmet\s*\([^)]*\))",
    re.IGNORECASE,
)
HELMET_REGISTER_RE = re.compile(
    r"\.(?:register|use)\s*\(\s*(?:helmet|securityHeaders|"
    r"require\s*\(\s*['\"][^'\"]*helmet[^'\"]*['\"]\s*\))",
    re.IGNORECASE,
)
HSTS_RE = re.compile(
    r"(?:Strict-Transport-Security|\bstrictTransportSecurity\b|"
    r"\bhsts\s*:\s*\{|\bhsts\s*\(|\bhsts\s*:\s*true)",
    re.IGNORECASE,
)
# Explicit-disable pattern: `hsts: false` tells us HSTS was considered and
# OFF, so we must NOT mark has_hsts = True based on the word appearing.
HSTS_DISABLED_RE = re.compile(r"\bhsts\s*:\s*false\b", re.IGNORECASE)


def _check_headers(cfg: dict, out: Output) -> None:
    files = _resolve_globs(cfg["api_routes_globs"])
    if not files:
        return  # nothing to grep — silent

    has_helmet = False
    has_hsts = False

    for fp in files:
        try:
            raw = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if HELMET_RE.search(raw) or HELMET_REGISTER_RE.search(raw):
            has_helmet = True
        # HSTS present only if matched AND not explicitly disabled
        if HSTS_RE.search(raw) and not HSTS_DISABLED_RE.search(raw):
            has_hsts = True
        if has_helmet and has_hsts:
            break

    if not has_helmet:
        out.warn(Evidence(
            type="headers_missing",
            message=t("sec_baseline.headers_missing.message"),
            fix_hint=t("sec_baseline.headers_missing.fix_hint"),
        ))

    if cfg["require_hsts"] and not has_hsts:
        out.warn(Evidence(
            type="hsts_missing",
            message=t("sec_baseline.hsts_missing.message"),
            fix_hint=t("sec_baseline.hsts_missing.fix_hint"),
        ))


# ─────────────────────────────────────────────────────────────────────────
# Check 3: Secret in .env.example
# ─────────────────────────────────────────────────────────────────────────

# High-confidence real-secret patterns (subset of secrets-scan.py).
# We intentionally SKIP generic_api_key_assignment because .env.example
# examples are expected to have KEY=value shape — we only flag when the
# VALUE looks like a real secret.
SECRET_VALUE_PATTERNS = [
    # base64-ish 32+ chars
    re.compile(r"=\s*([A-Za-z0-9+/]{32,}={0,2})\s*$", re.MULTILINE),
    # hex 32+
    re.compile(r"=\s*([0-9a-fA-F]{32,})\s*$", re.MULTILINE),
    # UUID v4
    re.compile(
        r"=\s*([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12})\s*$",
        re.MULTILINE | re.IGNORECASE,
    ),
    # JWT
    re.compile(
        r"=\s*(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})",
        re.MULTILINE,
    ),
    # AWS access key
    re.compile(r"=\s*((?:AKIA|ASIA)[0-9A-Z]{16})\b"),
    # stripe
    re.compile(r"=\s*(sk_(?:live|test)_[0-9a-zA-Z]{24,})\b"),
    # google api
    re.compile(r"=\s*(AIza[0-9A-Za-z_\-]{35})\b"),
]

PLACEHOLDER_RE = re.compile(
    r"(?i)(?:"
    r"your[_-]?(?:api[_-]?)?key|"
    r"replace[_-]?(?:me|with)|"
    r"<(?:your|api|secret)[^>]*>|"
    r"example[_-]?(?:key|secret|token)|"
    r"dummy|foobar|placeholder|changeme|todo|fixme|"
    r"xxx+|\.\.\.|"
    r"here\s*$|"
    r"change[_-]?this"
    r")"
)


def _check_env_example(out: Output) -> None:
    candidates = [
        REPO_ROOT / ".env.example",
        REPO_ROOT / ".env.sample",
        REPO_ROOT / ".env.template",
    ]
    env_files = [p for p in candidates if p.is_file()]
    if not env_files:
        return

    hits: list[tuple[Path, int, str]] = []
    for fp in env_files:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Check each pattern
            for pat in SECRET_VALUE_PATTERNS:
                m = pat.search(line)
                if not m:
                    continue
                value = m.group(1)
                # Skip if placeholder
                if PLACEHOLDER_RE.search(line):
                    continue
                # Hex: skip obvious placeholders like 000...000 or all same char
                if len(set(value)) <= 2:
                    continue
                hits.append((fp, line_no, value[:40]))
                break  # one hit per line enough

    if hits:
        sample = "; ".join(
            f"{fp.relative_to(REPO_ROOT).as_posix()}:{ln} "
            f"[{v[:10]}…{v[-4:] if len(v) > 14 else ''}]"
            for fp, ln, v in hits[:5]
        )
        out.add(Evidence(
            type="secret_in_example",
            message=t(
                "sec_baseline.secret_in_example.message",
                count=len(hits),
            ),
            actual=sample,
            fix_hint=t("sec_baseline.secret_in_example.fix_hint"),
        ))


# ─────────────────────────────────────────────────────────────────────────
# Check 4: Cookie flags
# ─────────────────────────────────────────────────────────────────────────

COOKIE_CONTEXT_RE = re.compile(
    r"(?:setCookie|cookie\s*:|session\s*\(|res\.cookie|reply\.setCookie|"
    r"@fastify/cookie|@fastify/session|express-session|cookie-session)",
    re.IGNORECASE,
)


def _check_cookie_flags(cfg: dict, out: Output) -> None:
    files = _resolve_globs(cfg["api_routes_globs"])
    if not files:
        return

    # Look for cookie setup locations; in ±10 lines check flags.
    missing_flags_files: dict[str, set[str]] = {}  # file → {missing flag names}
    found_cookie = False

    for fp in files:
        try:
            raw = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = raw.splitlines()
        for i, line in enumerate(lines):
            if not COOKIE_CONTEXT_RE.search(line):
                continue
            found_cookie = True
            # window ±10 lines
            start = max(0, i - 10)
            end = min(len(lines), i + 11)
            window = "\n".join(lines[start:end])
            missing: set[str] = set()
            if not re.search(r"\bSecure\b", window):
                missing.add("Secure")
            if not re.search(r"\bHttpOnly\b|\bhttpOnly\b", window):
                missing.add("HttpOnly")
            if not re.search(r"\bSameSite\b|\bsameSite\b", window):
                missing.add("SameSite")
            if missing:
                rel = fp.relative_to(REPO_ROOT).as_posix()
                missing_flags_files.setdefault(rel, set()).update(missing)

    if found_cookie and missing_flags_files:
        sample_parts = []
        for rel, flags in list(missing_flags_files.items())[:5]:
            sample_parts.append(f"{rel}: missing {', '.join(sorted(flags))}")
        out.warn(Evidence(
            type="cookie_flags_missing",
            message=t(
                "sec_baseline.cookie_flags_missing.message",
                count=len(missing_flags_files),
            ),
            actual="; ".join(sample_parts),
            fix_hint=t("sec_baseline.cookie_flags_missing.fix_hint"),
        ))


# ─────────────────────────────────────────────────────────────────────────
# Check 5: CORS
# ─────────────────────────────────────────────────────────────────────────

CORS_BLOCK_RE = re.compile(
    r"(?:cors\s*\(|@fastify/cors|registerCors|app\.use\s*\(\s*cors)",
    re.IGNORECASE,
)
CORS_WILDCARD_ORIGIN_RE = re.compile(
    r"origin\s*:\s*['\"]\*['\"]|origin\s*:\s*true",
)
CORS_CREDENTIALS_TRUE_RE = re.compile(
    r"credentials\s*:\s*true",
    re.IGNORECASE,
)
CORS_MAXAGE_RE = re.compile(
    r"(?:maxAge|max_age|Access-Control-Max-Age)\s*[:=]\s*['\"]?(\d+)",
    re.IGNORECASE,
)


def _check_cors(cfg: dict, out: Output) -> None:
    files = _resolve_globs(cfg["api_routes_globs"])
    if not files:
        return

    wildcard_cred_hits: list[tuple[str, int]] = []
    high_maxage_hits: list[tuple[str, int, int]] = []

    for fp in files:
        try:
            raw = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = fp.relative_to(REPO_ROOT).as_posix()
        lines = raw.splitlines()

        # Scan by CORS block anchor then check ±10 lines
        for i, line in enumerate(lines):
            if not CORS_BLOCK_RE.search(line):
                continue
            start = max(0, i - 2)
            end = min(len(lines), i + 20)
            window = "\n".join(lines[start:end])
            has_wildcard = bool(CORS_WILDCARD_ORIGIN_RE.search(window))
            has_creds = bool(CORS_CREDENTIALS_TRUE_RE.search(window))
            if has_wildcard and has_creds:
                wildcard_cred_hits.append((rel, i + 1))
            for m in CORS_MAXAGE_RE.finditer(window):
                try:
                    val = int(m.group(1))
                except ValueError:
                    continue
                if val > 86400:
                    high_maxage_hits.append((rel, i + 1, val))

    if wildcard_cred_hits:
        sample = "; ".join(
            f"{rel}:{ln}" for rel, ln in wildcard_cred_hits[:5]
        )
        out.add(Evidence(
            type="cors_wildcard_credentials",
            message=t(
                "sec_baseline.cors_wildcard_credentials.message",
                count=len(wildcard_cred_hits),
            ),
            actual=sample,
            fix_hint=t("sec_baseline.cors_wildcard_credentials.fix_hint"),
        ))

    if high_maxage_hits:
        sample = "; ".join(
            f"{rel}:{ln} (maxAge={v})" for rel, ln, v in high_maxage_hits[:5]
        )
        out.warn(Evidence(
            type="cors_maxage_high",
            message=t(
                "sec_baseline.cors_maxage_high.message",
                count=len(high_maxage_hits),
            ),
            actual=sample,
            fix_hint=t("sec_baseline.cors_maxage_high.fix_hint"),
        ))


# ─────────────────────────────────────────────────────────────────────────
# Check 6: Dependency lockfile
# ─────────────────────────────────────────────────────────────────────────

LOCKFILES = ["package-lock.json", "pnpm-lock.yaml", "yarn.lock"]


def _check_lockfile(out: Output) -> None:
    # First try git ls-files (authoritative: committed?)
    tracked: set[str] = set()
    try:
        r = subprocess.run(
            ["git", "ls-files"] + LOCKFILES,
            capture_output=True, text=True, timeout=10, cwd=REPO_ROOT,
        )
        if r.returncode == 0 and r.stdout.strip():
            tracked = {
                line.strip() for line in r.stdout.splitlines()
                if line.strip()
            }
    except Exception:
        pass

    if tracked:
        return  # at least one lockfile committed

    # Fallback: disk presence (tmp_path / no-git repos)
    for name in LOCKFILES:
        if (REPO_ROOT / name).is_file():
            return

    out.warn(Evidence(
        type="lockfile_missing",
        message=t("sec_baseline.lockfile_missing.message"),
        fix_hint=t("sec_baseline.lockfile_missing.fix_hint"),
    ))


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=False, default=None)
    ap.add_argument("--scope", choices=["repo", "deploy", "all"],
                    default="all")
    args = ap.parse_args()

    out = Output(validator="verify-security-baseline")
    with timer(out):
        cfg = _read_config()
        if not cfg.get("enabled", True):
            emit_and_exit(out)

        if args.scope in ("deploy", "all"):
            _check_tls(cfg, out)

        if args.scope in ("repo", "all"):
            _check_headers(cfg, out)
            _check_env_example(out)
            _check_cookie_flags(cfg, out)
            _check_cors(cfg, out)
            _check_lockfile(out)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
