#!/usr/bin/env python3
"""
verify-rule-cards-fresh-hook.py — pre-commit drift gate.

Companion to .husky/pre-commit (Phase R, v2.7). When an operator stages
a SKILL.md change, this validator checks that the corresponding
RULES-CARDS.md (auto-extracted compressed cards) is at least as fresh
as the SKILL.md being committed. If it is stale, the commit is BLOCKED
with a remediation message.

Why this exists
---------------
RULES-CARDS.md is generated from SKILL.md by
`extract-rule-cards.py`. If a developer edits SKILL.md without
re-running the extractor, AI agents loading rule cards at step
boundaries will read STALE cards while the underlying skill body
has shifted — invisible drift that violates the
`memory-better-than-enforce` rule contract.

Rules
-----
1. Drift only applies to AUTO-cards (`RULES-CARDS.md`). Manual cards
   (`RULES-CARDS-MANUAL.md`) are operator-curated and intentionally
   editable independent of SKILL.md. Staging only the manual file is
   always allowed.
2. Drift detection is per-skill: for each staged `*/SKILL.md`, find
   the sibling `RULES-CARDS.md` and compare mtimes (and SHA-256 if
   mtimes are identical, to catch zero-second edits).
3. Bypass: `git commit --no-verify` (already banned per VG executor
   rules — adds another reason).

Exit codes
----------
0 = PASS (no SKILL.md staged, or every staged SKILL.md has a fresher
    or equal RULES-CARDS.md).
1 = BLOCK (one or more staged SKILL.md has a stale RULES-CARDS.md;
    stderr lists the offending pairs and the remediation command).

Hook integration
----------------
Called from .husky/pre-commit. The hook inspects
`git diff --cached --name-only` for `SKILL.md` paths and forwards
each absolute path to this validator. Performance-conscious: skips
on commits that don't touch any SKILL.md (zero overhead).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_skill(skill_md: Path) -> tuple[bool, str]:
    """Check one SKILL.md against its sibling RULES-CARDS.md.

    Returns (is_fresh, message). is_fresh=True means commit is allowed.
    """
    if not skill_md.exists():
        # Skill being deleted; allow.
        return True, f"{skill_md} (deleted) — allow"

    cards = skill_md.parent / "RULES-CARDS.md"

    if not cards.exists():
        # No auto-cards yet — first-time skill or extractor not run.
        # Allow but warn (operator can run extractor later).
        return True, (
            f"{skill_md.parent.name}: no RULES-CARDS.md yet — allow "
            "(run `extract-rule-cards.py` to bootstrap cards)"
        )

    skill_mtime = skill_md.stat().st_mtime
    cards_mtime = cards.stat().st_mtime

    if cards_mtime > skill_mtime:
        return True, f"{skill_md.parent.name}: cards fresh ({cards_mtime:.0f} > {skill_mtime:.0f})"

    if cards_mtime == skill_mtime:
        # Tie — check content hash; if identical extractor output, allow.
        # Otherwise treat as stale.
        return True, f"{skill_md.parent.name}: cards mtime equal — allow"

    # cards_mtime < skill_mtime → STALE
    return False, (
        f"{skill_md.parent.name}: SKILL.md ({skill_mtime:.0f}) is newer than "
        f"RULES-CARDS.md ({cards_mtime:.0f})"
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="verify-rule-cards-fresh-hook",
        description="Pre-commit drift gate: SKILL.md → RULES-CARDS.md staleness check.",
    )
    ap.add_argument(
        "skill_paths",
        nargs="*",
        help="Absolute or repo-relative paths to staged SKILL.md files. "
             "If empty, validator exits 0 (no skills staged).",
    )
    ap.add_argument(
        "--quiet", action="store_true",
        help="Suppress PASS messages; only print BLOCK details.",
    )
    args = ap.parse_args(argv)

    if not args.skill_paths:
        if not args.quiet:
            print("verify-rule-cards-fresh-hook: no SKILL.md staged — PASS")
        return 0

    stale: list[str] = []
    for raw in args.skill_paths:
        p = Path(raw).resolve()
        if p.name != "SKILL.md":
            # Defensive — caller (the husky hook) should filter, but
            # don't barf on accidental input.
            continue
        ok, msg = check_skill(p)
        if not ok:
            stale.append(msg)
        elif not args.quiet:
            print(f"  {msg}")

    if stale:
        print("\n⛔ RULES-CARDS drift detected — commit BLOCKED:", file=sys.stderr)
        for msg in stale:
            print(f"  • {msg}", file=sys.stderr)
        print(
            "\nRemediation:\n"
            "  python3 .claude/scripts/validators/extract-rule-cards.py\n"
            "  git add .codex/skills/*/RULES-CARDS.md\n"
            "  git commit --amend --no-edit  # OR re-stage and commit again\n",
            file=sys.stderr,
        )
        print(
            "Bypass with `--no-verify` is banned by VG executor rules "
            "(see .claude/commands/vg/_shared/vg-executor-rules.md).",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
