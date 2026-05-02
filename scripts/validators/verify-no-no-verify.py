#!/usr/bin/env python3
"""
Validator: verify-no-no-verify.py

Harness v2.6 (2026-04-25): closes the CLAUDE.md / VG executor rule:

  "NEVER use `--no-verify` on any file under apps/**/src/**, packages/**/
   src/**. GSD generic execute-plan.md instructs --no-verify in parallel
   mode — VG OVERRIDES."
  + git safety: "Never skip hooks (--no-verify) or bypass signing
   (--no-gpg-sign, -c commit.gpgsign=false) unless the user has
   explicitly asked for it."

Why it matters: pre-commit hooks (husky + commit-msg gate) enforce
typecheck + commit-attribution + secrets-scan. Bypassing them with
--no-verify lets broken / unattributed / secret-leaking commits land
in main. AI sometimes uses --no-verify when hook fails to "make commit
go through" — this validator catches that anti-pattern.

What it scans:
  Source/skill/command/script files for git invocations carrying
  --no-verify or --no-gpg-sign or -c commit.gpgsign=false flags.

Allowlist (places that MAY discuss the flag in documentation):
  - .claude/scripts/validators/verify-no-no-verify.py (this file)
  - .claude/scripts/validators/test-* (test fixtures)
  - .planning/**, .vg/** (workspace artifacts)
  - **/*.md (documentation/skill prose)
  - .git/, node_modules/, dist/

Severity:
  BLOCK in source code (apps/**, packages/**, infra/, .claude/scripts/)
  WARN  in skill/command markdown when not in code-fence (docs may
        legitimately quote the flag in negative examples)

Usage:
  verify-no-no-verify.py
  verify-no-no-verify.py --phase 7.14 (for symmetry — ignored, scans repo)

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
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Patterns that indicate hook-bypass intent on a git command
NO_VERIFY_PATTERNS = [
    re.compile(r"\bgit\s+commit\b[^\n]*--no-verify\b"),
    re.compile(r"\bgit\s+push\b[^\n]*--no-verify\b"),
    re.compile(r"\bgit\s+rebase\b[^\n]*--no-verify\b"),
    re.compile(r"\bgit\s+(?:commit|rebase)\b[^\n]*--no-gpg-sign\b"),
    re.compile(r"-c\s+commit\.gpgsign\s*=\s*false"),
    re.compile(r"HUSKY\s*=\s*0"),  # bash env disabling husky pre-commit
    re.compile(r"export\s+HUSKY=0"),
]

# Allowlist — paths where mentions are intentional documentation
ALLOWLIST_RE = [
    re.compile(r"^\.git/"),
    re.compile(r"^node_modules/"),
    re.compile(r"^dist/"),
    re.compile(r"^build/"),
    re.compile(r"^\.next/"),
    re.compile(r"^target/"),
    re.compile(r"^vendor/"),
    re.compile(r"^\.planning/"),
    re.compile(r"^\.vg/"),
    re.compile(r"^docs/"),
    re.compile(r"\.example$"),
    # v2.47.2 (Issue #87) — allowlist patterns must work from BOTH vgflow-repo
    # source layout (`scripts/validators/...`) and user installs
    # (`.claude/scripts/validators/...`). Pre-fix the `^\.claude/` anchor only
    # matched user installs, so running the validator from vgflow-repo source
    # self-flagged its own file + its own test fixture + gate-manifest.json
    # (which contains the literal --no-verify string in its frozen gate hash
    # data). 80 violations on a clean v2.47.1 install blocked every
    # /vg:* run-complete.
    # This validator's own file (any layout)
    re.compile(r"(^|/)scripts/validators/verify-no-no-verify\.py$"),
    # Test fixtures (any layout) — both `tests/` (vgflow-repo) and
    # `.claude/scripts/tests/` (user install) carry test_no_no_verify.py
    # with intentional --no-verify literals as repro fixtures.
    re.compile(r"(^|/)scripts/validators/test-"),
    re.compile(r"(^|/)tests/test_no_no_verify\.py$"),
    re.compile(r"(^|/)scripts/tests/test_no_no_verify\.py$"),
    # Generated gate manifest — contains the literal flag inside hashed
    # gate body, NOT as an executable command.
    re.compile(r"(^|/)gate-manifest\.json$"),
    # Storybook static assets
    re.compile(r"^apps/web/storybook-static/"),
]


def is_allowlisted(rel_path: str) -> bool:
    rel_norm = rel_path.replace("\\", "/")
    for rx in ALLOWLIST_RE:
        if rx.search(rel_norm):
            return True
    return False


def is_in_code_fence(text: str, start_offset: int) -> bool:
    """Check if `start_offset` is inside a fenced code block (```)."""
    preceding = text[:start_offset]
    fences = preceding.count("```")
    return (fences % 2) == 1


def is_in_negative_example(line: str) -> bool:
    """Heuristic: line shows the flag as a forbidden example.

    v2.47.2 (Issue #87) — added 'MUST NOT', 'must not', 'Bypass', 'anti --no-verify'
    so docstrings/comments educating about the rule (e.g. orchestrator
    `__main__.py:2764` comment "Source code MUST NOT contain --no-verify",
    or `verify-rule-cards-fresh-hook.py:29` docstring "Bypass: git commit
    --no-verify (already banned)") are recognized as legitimate prose
    instead of self-flagging the validator.
    """
    markers = ("NEVER", "don't", "do not", "banned", "forbidden",
               "không bao giờ", "KHÔNG", "DO NOT", "Don't", "đừng",
               "ANTI-PATTERN", "anti-pattern", "anti pattern", "wrong:",
               "BAD:", "❌", "⛔", "🚫",
               # v2.47.2 additions for source-code prose
               "MUST NOT", "must not", "Must not", "Bypass:", "bypass:",
               "anti --no-verify", "no-no-verify", "non-negotiable",
               "(already banned)", "already banned")
    return any(m in line for m in markers)


def scan_file(file_path: Path) -> list[dict]:
    findings: list[dict] = []
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return findings

    is_md = file_path.suffix.lower() == ".md"

    for line_no, line in enumerate(text.splitlines(), 1):
        for rx in NO_VERIFY_PATTERNS:
            for m in rx.finditer(line):
                # Compute global offset for code-fence check
                offset = sum(len(x) + 1 for x in text.splitlines()[:line_no - 1]) + m.start()
                in_fence = is_in_code_fence(text, offset) if is_md else False
                negative_example = is_in_negative_example(line)

                # v2.47.2 (Issue #87) — severity routing:
                # - Source code line that is a COMMENT or in DOCSTRING and
                #   carries a negative-example marker → skip (educational
                #   prose, not actual bypass intent).
                # - Source code line containing `git commit`/`git push`/
                #   `git rebase` AS A COMMAND (not just discussed) → BLOCK.
                #   Pre-fix: any --no-verify mention in .py/.sh was BLOCK,
                #   self-flagging orchestrator's own anti-bypass docstring.
                # - Markdown in code fence without negative-example marker → WARN.
                # - Markdown negative-example or prose → skip.
                stripped = line.lstrip()
                is_comment_line = (
                    stripped.startswith("#") or  # py/sh/yaml comment
                    stripped.startswith("//") or  # ts/js/go comment
                    stripped.startswith("*") or   # /* ... */ continuation
                    stripped.startswith("///")    # rust/c# doc comment
                )
                if is_md:
                    if negative_example:
                        continue  # legitimate doc mention
                    severity = "WARN" if in_fence else "WARN"
                else:
                    # v2.47.2 (Issue #87) — negative-example marker (NEVER /
                    # MUST NOT / Bypass: / already banned / etc.) on the same
                    # line as --no-verify is sufficient to recognize the
                    # mention as educational prose, regardless of whether
                    # the line is a `#` comment, `//` comment, inside a
                    # `"""..."""` docstring, or plain text in a multi-line
                    # rules block. Same intent as the markdown branch above.
                    if negative_example:
                        continue
                    if is_comment_line:
                        # Comment without explicit anti-pattern marker —
                        # downgrade to WARN (could be example, not clearly
                        # forbidden; reviewer can confirm).
                        severity = "WARN"
                    else:
                        severity = "BLOCK"

                findings.append({
                    "line": line_no,
                    "snippet": line.strip()[:140],
                    "severity": severity,
                })
    return findings


def collect_files(root: Path) -> list[Path]:
    extensions = {".sh", ".bash", ".js", ".jsx", ".ts", ".tsx", ".py",
                  ".rs", ".go", ".yaml", ".yml", ".json", ".md", ".mjs",
                  ".cjs"}
    skip_dirs = {"node_modules", ".git", "dist", "build", ".next",
                 "target", "vendor", ".planning", ".vg",
                 "storybook-static"}
    files: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        # Fast skip — avoid descending into huge dirs
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.suffix.lower() not in extensions:
            continue
        files.append(p)
    return files


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", help="(orchestrator-injected; ignored — scans repo)")
    ap.add_argument("--strict", action="store_true",
                    help="Treat WARN findings as BLOCK")
    args = ap.parse_args()

    out = Output(validator="verify-no-no-verify")
    with timer(out):
        candidates = collect_files(REPO_ROOT)

        block_findings: list[dict] = []
        warn_findings: list[dict] = []

        for fp in candidates:
            try:
                rel = str(fp.relative_to(REPO_ROOT)).replace("\\", "/")
            except ValueError:
                continue
            if is_allowlisted(rel):
                continue
            for f in scan_file(fp):
                row = {**f, "file": rel}
                if f["severity"] == "BLOCK":
                    block_findings.append(row)
                else:
                    warn_findings.append(row)

        if args.strict:
            block_findings.extend(warn_findings)
            warn_findings = []

        if block_findings:
            sample = "; ".join(
                f"{f['file']}:{f['line']}"
                for f in block_findings[:5]
            )
            out.add(Evidence(
                type="no_verify_in_source",
                message=f"Found {len(block_findings)} --no-verify / hook-bypass usage(s) in source files",
                actual=sample,
                expected="Pre-commit hooks (typecheck + commit-attribution + secrets-scan) MUST run on every commit. Bypassing them lets broken/unattributed/secret-leaking commits land in main.",
                fix_hint="Remove --no-verify / --no-gpg-sign / -c commit.gpgsign=false / HUSKY=0 from the command. If hook fails: read error → fix root cause → retry. Per VG executor rule R3 + CLAUDE.md git safety.",
            ))

        if warn_findings:
            sample = "; ".join(
                f"{f['file']}:{f['line']}"
                for f in warn_findings[:5]
            )
            out.warn(Evidence(
                type="no_verify_in_doc",
                message=f"Found {len(warn_findings)} --no-verify mention(s) in docs/skills (advisory)",
                actual=sample,
                fix_hint="Verify mention is in negative-example context (NEVER / don't / banned). If genuine command, mark with explicit anti-pattern marker.",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
