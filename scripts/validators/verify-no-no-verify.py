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
    # This validator's own file
    re.compile(r"^\.claude/scripts/validators/verify-no-no-verify\.py$"),
    # Test fixtures
    re.compile(r"^\.claude/scripts/validators/test-"),
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

    Markers: 'NEVER', 'don't', 'do not', 'banned', 'forbidden', '🚫',
    'không bao giờ', 'KHÔNG', '⛔'.
    """
    markers = ("NEVER", "don't", "do not", "banned", "forbidden",
               "không bao giờ", "KHÔNG", "DO NOT", "Don't", "đừng",
               "ANTI-PATTERN", "anti-pattern", "anti pattern", "wrong:",
               "BAD:", "❌", "⛔", "🚫")
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

                # Severity routing:
                # - Source code (.py/.ts/.sh/.yaml etc.) → BLOCK always
                # - Markdown in code fence with no negative-example marker → WARN
                #   (might be example command, but not clearly forbidden)
                # - Markdown negative-example or prose → skip (doc legitimately
                #   discusses the rule)
                if is_md:
                    if negative_example:
                        continue  # legitimate doc mention
                    severity = "WARN" if in_fence else "WARN"
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
