#!/usr/bin/env python3
"""
Validator: verify-test-session-reuse.py — Phase 17 D-06

Detect generated specs still using the legacy `beforeEach(loginAs)` pattern
instead of Phase 17 `test.use(useAuth)` storage-state-based auth.

Logic:
  1. Find all generated spec files under --tests-glob (default scans
     apps/*/e2e/generated/*.spec.{ts,js} + e2e/generated/*.spec.{ts,js}).
  2. Per spec file:
     - Count `await loginAs(` occurrences in non-comment lines.
     - Count `test.use(useAuth(` occurrences.
     - Detect: file uses `test.beforeEach` AND contains `loginAs` →
       flag as "stale codegen pattern".
  3. Aggregate:
     - 0 stale specs → PASS
     - ≥1 stale + non-strict → WARN with per-file breakdown
     - ≥1 stale + --strict → BLOCK

Usage:  verify-test-session-reuse.py --phase 7.14.3
        verify-test-session-reuse.py --phase 7.14.3 --strict
        verify-test-session-reuse.py --phase 7.14.3 --tests-glob 'tests/e2e/**/*.spec.ts'

Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

DEFAULT_GLOBS = (
    "apps/*/e2e/generated/*.spec.ts",
    "apps/*/e2e/generated/*.spec.js",
    "e2e/generated/*.spec.ts",
    "e2e/generated/*.spec.js",
    "tests/e2e/generated/*.spec.ts",
)

# Match `await loginAs(...)` or `loginAs(...)` outside of // comments.
# We strip line comments first to avoid false positives in docstrings/notes.
LOGIN_AS_RE = re.compile(r"\bloginAs\s*\(")
USE_AUTH_RE = re.compile(r"\btest\.use\s*\(\s*useAuth\s*\(")
BEFORE_EACH_RE = re.compile(r"\btest\.beforeEach\s*\(")


def _strip_line_comments(text: str) -> str:
    """Remove // line comments so loginAs in doc-comments doesn't false-positive.
    Conservative: only strips comments that start at column 0 or after
    whitespace (avoids damaging URLs like http://...)."""
    out_lines = []
    for ln in text.splitlines():
        # Find // not preceded by ':' (URL guard) and not inside a string
        m = re.search(r"(?<![:'\"])//", ln)
        if m:
            ln = ln[:m.start()]
        out_lines.append(ln)
    return "\n".join(out_lines)


def _scan_spec(path: Path) -> dict | None:
    """Return None if spec is clean (PASS); dict with details if stale."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    code = _strip_line_comments(text)
    login_count = len(LOGIN_AS_RE.findall(code))
    if login_count == 0:
        return None
    has_before_each = bool(BEFORE_EACH_RE.search(code))
    use_auth_count = len(USE_AUTH_RE.findall(code))
    # Find first loginAs line for evidence
    first_line = 0
    for i, ln in enumerate(code.splitlines(), start=1):
        if LOGIN_AS_RE.search(ln):
            first_line = i
            break
    return {
        "loginas_count": login_count,
        "useauth_count": use_auth_count,
        "has_before_each": has_before_each,
        "first_line": first_line,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--tests-glob", action="append",
                    help="Glob pattern (relative to repo root); repeatable. "
                         "Default scans apps/*/e2e/generated + e2e/generated + tests/e2e/generated.")
    ap.add_argument("--strict", action="store_true",
                    help="Escalate WARN to BLOCK (use after 2 release cycles per D-06 plan).")
    args = ap.parse_args()

    out = Output(validator="test-session-reuse")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            out.warn(Evidence(
                type="info",
                message=f"Phase dir not found for {args.phase} — skipping (no generated specs to scan)",
            ))
            emit_and_exit(out)

        # Resolve repo root from VG_REPO_ROOT env or cwd
        import os
        repo_root = Path(os.environ.get("VG_REPO_ROOT") or Path.cwd()).resolve()

        globs = args.tests_glob or list(DEFAULT_GLOBS)
        spec_files: list[Path] = []
        for pattern in globs:
            spec_files.extend(p for p in repo_root.glob(pattern) if p.is_file())

        if not spec_files:
            out.evidence.append(Evidence(
                type="info",
                message=(f"No generated spec files found under {len(globs)} glob "
                         f"pattern(s) — nothing to verify."),
            ))
            emit_and_exit(out)

        stale: list[tuple[Path, dict]] = []
        for spec in spec_files:
            details = _scan_spec(spec)
            if details:
                stale.append((spec, details))

        if not stale:
            out.evidence.append(Evidence(
                type="info",
                message=(f"All {len(spec_files)} generated spec(s) use Phase 17 "
                         f"test.use(useAuth) pattern (no legacy loginAs)."),
            ))
            emit_and_exit(out)

        # Stale specs found — emit one evidence per file
        for spec, details in stale[:30]:  # cap for readability
            evid = Evidence(
                type="stale_codegen_pattern",
                message=(
                    f"Spec uses beforeEach(loginAs) [{details['loginas_count']} "
                    f"call(s)] — expected test.use(useAuth) per Phase 17 D-03."
                ),
                file=str(spec.relative_to(repo_root)),
                line=details["first_line"],
                expected=("test.use(useAuth(ROLE)) at describe scope; "
                          "beforeEach only navigates"),
                actual=(f"loginas_count={details['loginas_count']}, "
                        f"useauth_count={details['useauth_count']}, "
                        f"has_before_each={details['has_before_each']}"),
                fix_hint=(
                    "Re-run /vg:test {phase} --recodegen-interactive after "
                    "Phase 17 install. Helper template now exports useAuth."
                ),
            )
            if args.strict:
                out.add(evid)         # BLOCK
            else:
                out.warn(evid)        # WARN

        if len(stale) > 30:
            out.evidence.append(Evidence(
                type="info",
                message=f"... and {len(stale) - 30} more stale spec(s) (capped)",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
