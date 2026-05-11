#!/usr/bin/env python3
"""redact-stream.py — line-oriented redactor for /vg:field-test.

Reads stdin line-by-line, applies a multi-form redaction regex, writes stdout.
Used in two places:
  1. tail-source.sh pipes API log lines through this BEFORE writing to disk
     (capture-time redaction — closes the v1 disk-exposure window).
  2. build-bundle.py runs each correlated window line through this for
     idempotent re-application during Stop-time bundle assembly.

Pattern modes:
  - "default" or empty → built-in multi-form template covering password|token|
    secret|api_key|email|phone + Authorization header + Bearer JWT.
  - Key alternation (e.g. `password|token|jwt`) → composed into multi-form
    template (kv=, kv:, JSON body forms applied).
  - Full regex (anything with metachars beyond | / word chars / [_-]?) → used
    as-is. v2.1 MUST-5: avoids double-wrapping user patterns that already
    encode their own match shape.
  - Mixed pattern: pipe-separated segments classified individually — plain key
    segments are composed into multi-form; full-regex segments are kept as-is.
    The two groups are OR-combined. Trailing \\S+ in a full-regex segment is
    promoted to \\S.* so it captures the full header value, not just one token.

Bad user regex → warn on stderr, fall back to default. Never crash.
"""
from __future__ import annotations

import argparse
import re
import sys


DEFAULT_KEYS = r"password|token|secret|api[_-]?key|email|phone"
SENTINEL = "[REDACTED]"

# A "simple key segment" consists of one or more word-char runs joined by the
# literal char-class [_-] optionally quantified with ?  (e.g. api[_-]?key).
# No other metacharacters are allowed.
_SIMPLE_KEY_RE = re.compile(r'^[\w]+(?:\[_\-\]\?[\w]+)*$')


def _compose_multiform(keys: str) -> str:
    """Build the multi-form template from a key-alternation string."""
    return (
        r"(?:" + keys + r")\s*[:=]\s*\"?[^\"\s,&}]+"
        r"|\"(?:" + keys + r")\"\s*:\s*\"[^\"]*\""
    )


def _bearer_auth_forms() -> str:
    return r"bearer\s+[A-Za-z0-9._\-]+|authorization:\s*\S.*"


def _enhance_full_seg(seg: str) -> str:
    """Extend a trailing \\S+ quantifier to \\S.* so the pattern captures
    the full header value (not just the first non-space token)."""
    if seg.endswith(r"\S+"):
        return seg[: -len(r"\S+")] + r"\S.*"
    return seg


def build_pattern(user: str | None) -> tuple[re.Pattern[str], bool]:
    """Return (compiled, used_default). Falls back to default on bad regex."""
    if not user or user == "default":
        inner = _compose_multiform(DEFAULT_KEYS) + "|" + _bearer_auth_forms()
        return re.compile(f"(?i)({inner})"), True
    try:
        # Classify each pipe-delimited segment individually.
        segments = user.split("|")
        simple_keys: list[str] = []
        full_segs: list[str] = []
        for seg in segments:
            if _SIMPLE_KEY_RE.match(seg):
                simple_keys.append(seg)
            else:
                # v2.1 MUST-5: keep as-is, only enhance trailing \S+
                full_segs.append(_enhance_full_seg(seg))

        parts: list[str] = []
        if simple_keys:
            parts.append(_compose_multiform("|".join(simple_keys)))
        if full_segs:
            parts.append("|".join(full_segs))
        if not parts:
            parts = [user]  # degenerate fallback

        if len(parts) > 1:
            inner = "|".join(f"(?:{p})" for p in parts)
        else:
            inner = parts[0]
        return re.compile(f"(?i)({inner})"), False

    except re.error as exc:
        print(
            f"redact-stream: warning: invalid user regex '{user}': {exc}; "
            f"falling back to default",
            file=sys.stderr,
        )
        inner = _compose_multiform(DEFAULT_KEYS) + "|" + _bearer_auth_forms()
        return re.compile(f"(?i)({inner})"), True


def redact(line: str, pat: re.Pattern[str]) -> str:
    return pat.sub(SENTINEL, line)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--pattern",
        default="default",
        help="Custom redaction regex (key alternation OR full pattern)",
    )
    args = ap.parse_args()
    pat, _ = build_pattern(args.pattern)
    try:
        for line in sys.stdin:
            sys.stdout.write(redact(line, pat))
            sys.stdout.flush()
    except BrokenPipeError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
