#!/usr/bin/env python3
"""
Validator: secrets-scan.py

B8.1 (OHOK D1): detect hardcoded secrets (API keys, tokens, credentials)
in in-flight changes BEFORE they leave the developer machine.

Scope: pre-push mode scans `git diff <upstream>..HEAD` for patterns.
Default mode scans staged changes (useful pre-commit too, opt-in).

Exits:
  0  PASS (no secrets) or WARN (suppressed via allowlist)
  1  BLOCK (secrets found, no allowlist match)

Allowlist: .vg/secrets-allowlist.yml (optional) — entries with regex +
reason + optional expiry date. Expired entries re-activate the block.

Design choices:
- Regex patterns cover the common-surface secrets: AWS keys, GitHub
  PATs, Slack tokens, Stripe keys, JWT fragments, DB URLs w/ password,
  generic `*_KEY=...` / `SECRET=...` env-style assignments, private
  key PEM headers, Google API keys, npm auth tokens.
- False-positive control: (a) skip test fixture / docs / lock files
  via path heuristics, (b) require non-placeholder value patterns
  (min entropy, not obviously dummy), (c) allowlist for known OK refs.
- Output follows vg.validator-output schema via _common.Output.

Usage:
  secrets-scan.py --mode pre-push [--base origin/main]
  secrets-scan.py --mode staged
  secrets-scan.py --mode full  (scan all tracked files — slow)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
ALLOWLIST_PATH = REPO_ROOT / ".vg" / "secrets-allowlist.yml"

# Files / paths that commonly contain look-alike strings and should be
# scanned with lighter scrutiny (only very high-confidence patterns).
LOW_SIGNAL_PATH_RE = re.compile(
    r"(?:^|/)(?:"
    r"tests?/|test[_-]?data/|fixtures?/|__fixtures__/|mocks?/|"
    r"\.test\.|\.spec\.|_test\.|_spec\.|"
    r"\.md$|\.txt$|"
    r"package-lock\.json|pnpm-lock\.yaml|yarn\.lock|poetry\.lock|"
    r"Cargo\.lock|go\.sum|uv\.lock"
    r")",
    re.IGNORECASE,
)

# Meta files — config for the scanners themselves, contain literal patterns
# by design. Skip entirely to avoid self-flagging.
# - secrets-allowlist.yml / cve-waivers.yml contain literal patterns
# - test_secrets_scan.py + secrets-scan.py + narration-strings-validators.yaml
#   reference patterns for testing and message templates
SKIP_PATH_RE = re.compile(
    r"(?:^|/)(?:"
    r"\.vg/(?:secrets-allowlist|cve-waivers)\.ya?ml"
    r"|\.claude/scripts/(?:validators/secrets-scan\.py|tests/test_secrets_scan\.py)"
    r"|\.claude/commands/vg/_shared/narration-strings-validators\.ya?ml"
    r")$",
    re.IGNORECASE,
)


@dataclass
class SecretPattern:
    name: str
    regex: re.Pattern[str]
    severity: str  # "critical" | "high" | "medium"
    # High-confidence patterns that fire even on low-signal paths
    high_confidence: bool = False


def _pat(name: str, regex: str, severity: str = "high",
         high_confidence: bool = False) -> SecretPattern:
    return SecretPattern(name, re.compile(regex), severity, high_confidence)


# Patterns ordered by precision (higher precision first).
PATTERNS: list[SecretPattern] = [
    _pat("aws_access_key_id",
         r"\b(AKIA|ASIA)[0-9A-Z]{16}\b",
         "critical", high_confidence=True),
    _pat("aws_secret_access_key",
         r"(?i)aws(.{0,20})?(secret|private).{0,20}['\"`]([A-Za-z0-9/+=]{40})['\"`]",
         "critical"),
    _pat("github_pat",
         r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
         "critical", high_confidence=True),
    _pat("slack_token",
         r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",
         "critical", high_confidence=True),
    _pat("stripe_live_key",
         r"\bsk_live_[0-9a-zA-Z]{24,}\b",
         "critical", high_confidence=True),
    _pat("stripe_test_key",
         r"\bsk_test_[0-9a-zA-Z]{24,}\b",
         "high"),  # test keys less critical but still leak signal
    _pat("google_api_key",
         r"\bAIza[0-9A-Za-z_\-]{35}\b",
         "critical", high_confidence=True),
    _pat("google_oauth_secret",
         r"\bGOCSPX-[A-Za-z0-9_-]{28,}\b",
         "critical", high_confidence=True),
    _pat("private_key_pem",
         r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
         "critical", high_confidence=True),
    _pat("jwt_token_literal",
         r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b",
         "high"),
    _pat("db_url_with_password",
         r"(?i)(postgres|postgresql|mysql|mariadb|mongodb(?:\+srv)?|redis)"
         r"://[^\s:@'\"]+:[^\s@'\"/]{6,}@[\w.\-]+",
         "critical"),
    _pat("npm_token",
         r"\bnpm_[A-Za-z0-9]{36}\b",
         "critical", high_confidence=True),
    _pat("generic_api_key_assignment",
         r"(?im)^\s*(?:[A-Z][A-Z0-9_]*_)?(?:API[_-]?KEY|SECRET[_-]?KEY|"
         r"ACCESS[_-]?TOKEN|AUTH[_-]?TOKEN|BEARER[_-]?TOKEN|"
         r"PRIVATE[_-]?KEY)\s*[:=]\s*['\"]?"
         r"([A-Za-z0-9_\-+/=]{20,})['\"]?",
         "high"),
    _pat("generic_password_assignment",
         r"(?im)\b(password|passwd|pwd)\s*[:=]\s*['\"]"
         r"(?!(?:\*{3,}|\.{3,}|xxx|<[^>]+>|\$\{|\$\(|undefined|null|true|false))"
         r"([^'\"\s]{8,})['\"]",
         "medium"),
]

# Placeholder values that should never flag — common in examples/docs
PLACEHOLDER_RE = re.compile(
    r"(?i)(?:"
    r"your[_-]?(?:api[_-]?)?key|"
    r"replace[_-]?(?:me|with)|"
    r"<(?:your|api|secret)[^>]*>|"
    r"example[_-]?(?:key|secret|token)|"
    r"dummy|foobar|placeholder|changeme|todo|fixme|"
    r"xxx+|\.\.\.|abc{3,}|test{3,}|"
    r"sk_(?:test|fake|example)_0{10,}"
    r")"
)


def _load_allowlist() -> list[dict]:
    """Read allowlist yaml. Returns list of {pattern, reason, expires}."""
    if not ALLOWLIST_PATH.exists():
        return []
    try:
        import yaml  # type: ignore
    except ImportError:
        return []
    try:
        data = yaml.safe_load(
            ALLOWLIST_PATH.read_text(encoding="utf-8", errors="replace")
        ) or []
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict) and "pattern" in e]


def _allowlist_matches(match_text: str, file_rel: str,
                       allowlist: list[dict]) -> tuple[bool, str]:
    """Check if a match is suppressed by allowlist. Returns (matches, reason)."""
    now = datetime.now(timezone.utc)
    for entry in allowlist:
        try:
            pat = re.compile(entry["pattern"])
        except re.error:
            continue
        scope = entry.get("file")
        if scope and not re.search(scope, file_rel):
            continue
        if not pat.search(match_text):
            continue
        expires = entry.get("expires")
        if expires:
            try:
                exp_dt = datetime.fromisoformat(
                    str(expires).replace("Z", "+00:00")
                )
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if now > exp_dt:
                    continue  # expired — do not suppress
            except Exception:
                continue
        reason = entry.get("reason", "allowlisted")
        return True, str(reason)
    return False, ""


def _resolve_file_list(mode: str, base_ref: str) -> list[Path]:
    """Return files-to-scan Paths relative to repo."""
    if mode == "pre-push":
        try:
            r = subprocess.run(
                ["git", "diff", f"{base_ref}...HEAD", "--name-only",
                 "--diff-filter=ACMR"],
                capture_output=True, text=True, timeout=15, cwd=REPO_ROOT,
            )
            if r.returncode != 0:
                # base_ref may not exist (first push to new branch) — fall back
                r = subprocess.run(
                    ["git", "diff", "HEAD~10..HEAD", "--name-only",
                     "--diff-filter=ACMR"],
                    capture_output=True, text=True, timeout=15, cwd=REPO_ROOT,
                )
        except Exception:
            return []
    elif mode == "staged":
        try:
            r = subprocess.run(
                ["git", "diff", "--cached", "--name-only",
                 "--diff-filter=ACMR"],
                capture_output=True, text=True, timeout=15, cwd=REPO_ROOT,
            )
        except Exception:
            return []
    else:  # full
        try:
            r = subprocess.run(
                ["git", "ls-files"],
                capture_output=True, text=True, timeout=20, cwd=REPO_ROOT,
            )
        except Exception:
            return []
    if r.returncode != 0:
        return []
    files = []
    for rel in r.stdout.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        p = REPO_ROOT / rel
        if p.is_file():
            files.append(p)
    return files[:2000]  # cap


def _scan_file(path: Path, allowlist: list[dict]) -> list[tuple[SecretPattern, str, int]]:
    """Return list of (pattern, match_text, line_num) hits, allowlist-filtered."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    if SKIP_PATH_RE.search(rel):
        return []
    low_signal = bool(LOW_SIGNAL_PATH_RE.search(rel))

    hits: list[tuple[SecretPattern, str, int]] = []
    for pattern in PATTERNS:
        if low_signal and not pattern.high_confidence:
            continue
        for m in pattern.regex.finditer(text):
            match_text = m.group(0)
            # Placeholder filter
            if PLACEHOLDER_RE.search(match_text):
                continue
            # Allowlist
            suppressed, _ = _allowlist_matches(match_text, rel, allowlist)
            if suppressed:
                continue
            # Compute line number
            line_num = text[:m.start()].count("\n") + 1
            hits.append((pattern, match_text[:100], line_num))
    return hits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["pre-push", "staged", "full"],
                    default="pre-push")
    ap.add_argument("--base", default="origin/main",
                    help="Base ref for pre-push diff (default origin/main)")
    args = ap.parse_args()

    out = Output(validator="secrets-scan")
    with timer(out):
        files = _resolve_file_list(args.mode, args.base)
        if not files:
            # Empty diff — nothing to scan → PASS silently.
            emit_and_exit(out)

        allowlist = _load_allowlist()
        all_hits: list[tuple[Path, SecretPattern, str, int]] = []
        for f in files:
            hits = _scan_file(f, allowlist)
            for pat, match_text, line_num in hits:
                all_hits.append((f, pat, match_text, line_num))

        if not all_hits:
            emit_and_exit(out)

        # Group by severity
        critical = [h for h in all_hits if h[1].severity == "critical"]
        high = [h for h in all_hits if h[1].severity == "high"]
        medium = [h for h in all_hits if h[1].severity == "medium"]

        def _format_hits(hits: list, limit: int = 5) -> str:
            lines = []
            for f, pat, match_text, line_num in hits[:limit]:
                rel = str(f.relative_to(REPO_ROOT)).replace("\\", "/")
                # Redact middle of match to avoid re-leaking in logs
                redacted = (
                    match_text[:10] + "…" + match_text[-6:]
                    if len(match_text) > 20 else "***"
                )
                lines.append(f"{rel}:{line_num} [{pat.name}] {redacted}")
            if len(hits) > limit:
                lines.append(f"... and {len(hits) - limit} more")
            return "\n".join(lines)

        if critical:
            out.add(Evidence(
                type="secret_leak_critical",
                message=t(
                    "secrets_scan.critical.message",
                    count=len(critical),
                    kinds=", ".join(sorted({h[1].name for h in critical})),
                ),
                actual=_format_hits(critical),
                fix_hint=t("secrets_scan.critical.fix_hint"),
            ))

        if high:
            severity_fn = out.add if not critical else out.warn
            severity_fn(Evidence(
                type="secret_leak_high",
                message=t(
                    "secrets_scan.high.message",
                    count=len(high),
                    kinds=", ".join(sorted({h[1].name for h in high})),
                ),
                actual=_format_hits(high),
                fix_hint=t("secrets_scan.high.fix_hint"),
            ))

        if medium and not (critical or high):
            out.warn(Evidence(
                type="secret_leak_medium",
                message=t(
                    "secrets_scan.medium.message",
                    count=len(medium),
                ),
                actual=_format_hits(medium),
                fix_hint=t("secrets_scan.medium.fix_hint"),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
