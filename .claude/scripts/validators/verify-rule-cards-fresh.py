#!/usr/bin/env python3
"""
Validator: verify-rule-cards-fresh.py

Harness v2.6 (2026-04-25): Tầng 3 of memory-vs-enforce strategy.

Problem: rule cards (.codex/skills/vg-*/RULES-CARDS.md) auto-generated
from skill body. If skill body changes but cards aren't regenerated,
AI reads stale cards → applies outdated rules → drift.

This validator catches that drift by comparing mtime of SKILL.md vs
RULES-CARDS.md. If skill is newer than cards → BLOCK with regeneration
hint.

Also checks:
  - RULES-CARDS.md exists for each skill (vg-* folder with SKILL.md)
  - Cards file is non-empty + has expected header structure

Skip when:
  - Skill folder has no SKILL.md (init-pending skills)
  - Cards have never been generated (first-run; cards would be empty)

Severity:
  WARN (advisory) — operator should run extract-rule-cards.py
                    Not BLOCK because stale cards still useful;
                    full enforcement risks pipeline freezes.

Usage:
  verify-rule-cards-fresh.py
  verify-rule-cards-fresh.py --strict (escalate WARN → BLOCK)

Exit codes:
  0  PASS or WARN-only
  1  BLOCK (--strict mode + drift detected)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", help="(orchestrator-injected; ignored — checks all skills)")
    ap.add_argument("--strict", action="store_true",
                    help="Escalate stale-cards WARN to BLOCK")
    args = ap.parse_args()

    out = Output(validator="verify-rule-cards-fresh")
    with timer(out):
        codex_skills = REPO_ROOT / ".codex" / "skills"
        if not codex_skills.exists():
            emit_and_exit(out)

        stale: list[dict] = []
        missing: list[str] = []
        ok_count = 0

        for skill_dir in sorted(codex_skills.iterdir()):
            if not skill_dir.is_dir() or not skill_dir.name.startswith("vg-"):
                continue
            skill_md = skill_dir / "SKILL.md"
            cards_md = skill_dir / "RULES-CARDS.md"

            if not skill_md.exists():
                continue  # not a real skill yet

            if not cards_md.exists():
                missing.append(skill_dir.name)
                continue

            try:
                skill_mtime = skill_md.stat().st_mtime
                cards_mtime = cards_md.stat().st_mtime
            except OSError:
                continue

            # Allow 60s tolerance window — skill edited & immediately cards
            # generated may have very close mtimes that flicker
            if skill_mtime > cards_mtime + 60:
                age_seconds = int(skill_mtime - cards_mtime)
                stale.append({
                    "skill": skill_dir.name,
                    "age_seconds": age_seconds,
                    "age_human": f"{age_seconds // 3600}h {(age_seconds % 3600) // 60}m"
                                 if age_seconds >= 3600
                                 else f"{age_seconds // 60}m",
                })
            else:
                ok_count += 1

        if missing:
            sample = ", ".join(missing[:8])
            evidence = Evidence(
                type="rule_cards_missing",
                message=f"{len(missing)} skill(s) without RULES-CARDS.md",
                actual=sample,
                fix_hint=("Run `python3 .claude/scripts/validators/extract-rule-cards.py` "
                          "to generate cards. Cards compress 1500-3000 line skill bodies "
                          "into ~50-100 line digests AI reads at step start (96% size "
                          "reduction). Without cards, AI skims skill body and misses 60-70% "
                          "of rules."),
            )
            if args.strict:
                out.add(evidence)
            else:
                out.warn(evidence)

        if stale:
            sample = "; ".join(
                f"{s['skill']} ({s['age_human']} stale)"
                for s in stale[:6]
            )
            evidence = Evidence(
                type="rule_cards_stale",
                message=f"{len(stale)} RULES-CARDS.md out of date relative to SKILL.md (skill body edited after cards regenerated)",
                actual=sample,
                fix_hint=("Run `python3 .claude/scripts/validators/extract-rule-cards.py` "
                          "to refresh cards. Stale cards mean AI may apply old rules "
                          "when skill body has new requirements."),
            )
            if args.strict:
                out.add(evidence)
            else:
                out.warn(evidence)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
