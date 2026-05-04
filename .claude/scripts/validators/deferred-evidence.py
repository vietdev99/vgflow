#!/usr/bin/env python3
"""
Validator: deferred-evidence.py

Purpose: Every Playwright test tagged `@deferred-*` MUST have an inline reason
comment linking to a tracked issue/ticket/runbook. Without this, `@deferred`
becomes a silent skip mechanism that never gets resolved.

Example phase 14 dogfood pattern (2026-04-22):
  test('logout on admin domain @deferred-4port', async ...) { ... }

The `@deferred-4port` tag says "requires 4-port dev stack" — but no ticket
tracks when the 4-port harness ships, so the test is effectively abandoned.
Gate: require a nearby comment matching:

  // @deferred-reason: <ticket-url-or-id>
  /* @deferred-reason: ISSUE-123 — sandbox CI needs 4-port harness (ETA P15) */

Prior state: `@deferred-*` tags proliferated across phase 14 + earlier with
no tracking. Validator enforces discipline — override via --allow-untracked-deferred
(logged as HARD debt).

Skip (PASS):
- Phase has no Playwright spec files → not our gate
- No @deferred-* tags in spec files → nothing to validate

Checks (BLOCK):
- @deferred-* tag found in .spec.ts without matching @deferred-reason comment
  within ±5 lines

Usage: deferred-evidence.py --phase <N>
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
PHASES_DIR = REPO_ROOT / ".vg" / "phases"

# @deferred-<tag> pattern in test files
DEFERRED_TAG_RE = re.compile(r"@deferred-([a-z0-9-_]+)", re.IGNORECASE)
# Matching reason comment within ±5 lines
REASON_COMMENT_RE = re.compile(
    r"@deferred-reason\s*:\s*(.{10,})",
    re.IGNORECASE,
)

# Phase-scope: scan files whose path mentions phase number OR all e2e specs
# (conservative — err on including-more to catch deferred tags even if not
# in phase-specific file).
E2E_GLOBS = [
    "apps/*/e2e/**/*.spec.ts",
    "apps/*/e2e/**/*.spec.tsx",
    "apps/*/tests/**/*.spec.ts",
    "e2e/**/*.spec.ts",
]


def find_spec_files(phase: str) -> list[Path]:
    """Find test spec files to scan.
    Priority 1: files with phase number in path or filename.
    Priority 2: all E2E specs (validator covers the whole repo, not just phase).
    """
    results: list[Path] = []
    seen: set[Path] = set()
    # Priority 1 — phase-specific
    for pattern in E2E_GLOBS:
        for p in REPO_ROOT.glob(pattern):
            if p in seen:
                continue
            if phase in p.name or phase in p.parent.name:
                results.append(p)
                seen.add(p)
    # Priority 2 — add rest (for cross-phase @deferred discovery)
    for pattern in E2E_GLOBS:
        for p in REPO_ROOT.glob(pattern):
            if p in seen:
                continue
            results.append(p)
            seen.add(p)
    return results


def scan_file(path: Path) -> list[dict]:
    """Return list of untracked @deferred tags in file."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    violations: list[dict] = []
    for lineno, line in enumerate(lines, start=1):
        for m in DEFERRED_TAG_RE.finditer(line):
            tag = m.group(1)
            # Look ±5 lines around tag for @deferred-reason
            window_start = max(0, lineno - 6)
            window_end = min(len(lines), lineno + 5)
            window_text = "\n".join(lines[window_start:window_end])
            if not REASON_COMMENT_RE.search(window_text):
                violations.append({
                    "file": str(path.relative_to(REPO_ROOT)),
                    "line": lineno,
                    "tag": f"@deferred-{tag}",
                    "snippet": line.strip()[:100],
                })
    return violations


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="deferred-evidence")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        phase_dirs = [phase_dir] if phase_dir else []
        if not phase_dirs:
            emit_and_exit(out)

        specs = find_spec_files(args.phase)
        if not specs:
            # No E2E specs → not applicable (backend-only phase)
            emit_and_exit(out)

        all_violations: list[dict] = []
        for spec in specs:
            all_violations.extend(scan_file(spec))

        if not all_violations:
            emit_and_exit(out)

        # Cap to first 8 concrete evidence entries
        sample = all_violations[:8]
        evidence_summary = "; ".join(
            f"{v['file']}:{v['line']} {v['tag']}" for v in sample
        )

        out.add(Evidence(
            type="untracked_deferred",
            message=(
                f"{len(all_violations)} @deferred-* tag(s) lack @deferred-reason "
                f"comment with ticket/issue link. Deferred tests without tracking "
                f"become silent skips."
            ),
            expected="every @deferred-* tag has @deferred-reason: <ticket-url> within ±5 lines",
            actual=evidence_summary + (
                f" (+{len(all_violations) - 8} more)"
                if len(all_violations) > 8 else ""
            ),
            fix_hint=(
                "Add comment near the test: "
                "`// @deferred-reason: <ISSUE-URL or text with ETA>`. Example: "
                "`// @deferred-reason: GitHub #123 — sandbox 4-port harness lands P15`. "
                "Override via --allow-untracked-deferred (logs HARD override-debt)."
            ),
        ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
