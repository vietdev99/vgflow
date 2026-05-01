#!/usr/bin/env python3
"""Verify code implements business rule constants matching CONTEXT decisions.

Closes Phase 3.2 dogfood gap: D-46 says "5 topups in 24h" but code may
implement THRESHOLD=3 (drift). All downstream tests/scans align with code,
not with decision → bug ships.

Mechanism: parse `expected_assertion` per goal, extract numeric/string
constants (e.g., "5", "24h", "$100"), grep code under apps/ + packages/ +
infra/ for matching constants near rule-related identifiers (e.g.,
SUSPICIOUS_COUNT_THRESHOLD).

Severity: BLOCK at /vg:build end-of-wave.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402
from _traceability import parse_goals_with_frontmatter  # noqa: E402


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def extract_constants(assertion: str) -> list[str]:
    """Extract numeric/duration/currency constants from assertion text.

    Examples:
      "5 topups in 24h"       → ["5", "24"]
      "amount sum >= $100"    → ["100"]
      "threshold of 5 topups" → ["5"]
    """
    constants: list[str] = []
    # Numbers (integer or decimal)
    constants.extend(re.findall(r"\b(\d+(?:\.\d+)?)\b", assertion))
    # Currency ($X / X USD)
    constants.extend(re.findall(r"\$(\d+(?:\.\d+)?)", assertion))
    # Time durations (24h, 7d, 5m)
    constants.extend(re.findall(r"\b(\d+)\s*(?:h|hrs|hour|d|day|m|min|s|sec|w|week|month)\b", assertion, re.IGNORECASE))
    return list(dict.fromkeys(constants))  # dedupe preserving order


def grep_code_for_constants(constants: list[str], repo_root: Path) -> dict[str, list[str]]:
    """Use `git grep` to find files containing each constant.

    Restricts to source files (apps/, packages/, infra/) and excludes
    test fixtures + node_modules.
    """
    found: dict[str, list[str]] = {}
    if not constants:
        return found
    src_dirs = ["apps", "packages", "infra"]
    src_dirs_present = [d for d in src_dirs if (repo_root / d).is_dir()]
    if not src_dirs_present:
        return found

    for c in constants:
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "grep",
                    "-l",
                    "--no-color",
                    rf"\b{re.escape(c)}\b",
                    "--",
                ]
                + [f"{d}/" for d in src_dirs_present]
                + [
                    f":!{d}/**/test*"
                    for d in src_dirs_present
                ]
                + [f":!{d}/**/__tests__/**" for d in src_dirs_present],
                capture_output=True,
                text=True,
                timeout=15,
            )
            files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
            if files:
                found[c] = files[:5]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify business rule constants in code")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument("--allow-rule-not-implemented", action="store_true")
    args = parser.parse_args()

    out = Output(validator="business-rule-implemented")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        if not goals_path.exists():
            emit_and_exit(out)

        goals = parse_goals_with_frontmatter(_read(goals_path))
        repo_root = Path.cwd()
        violations = 0

        for goal in goals:
            assertion = goal.get("expected_assertion", "").strip()
            if not assertion or len(assertion) < 20:
                continue
            constants = extract_constants(assertion)
            if not constants:
                continue
            found = grep_code_for_constants(constants, repo_root)
            missing = [c for c in constants if c not in found]
            if missing:
                violations += 1
                out.add(
                    Evidence(
                        type="rule_constants_not_in_code",
                        message=(
                            f"{goal['id']}: expected_assertion has constants {constants} "
                            f"but {len(missing)} not found in apps/packages/infra source: {missing}"
                        ),
                        file=str(goals_path),
                        expected=f"Source code constants matching {constants}",
                        actual=f"Found: {list(found.keys())}, missing: {missing}",
                        fix_hint=(
                            "Verify code implements business rule with these specific values. "
                            "Drift between expected_assertion and code → bug ships."
                        ),
                    ),
                    escalate=(args.severity == "block" and not args.allow_rule_not_implemented),
                )

        if violations and (args.severity == "warn" or args.allow_rule_not_implemented):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{violations} rule(s) not in code, downgraded to WARN.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
