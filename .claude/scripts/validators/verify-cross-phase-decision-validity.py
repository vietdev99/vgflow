#!/usr/bin/env python3
"""Verify cross-phase D-XX references are still active (not revoked by amend).

Closes Phase 3.2 dogfood gap: Phase X goal cites D-AA from Phase Y. A later
amend in Phase Z revokes D-AA. Phase X stale but no validator catches.

Mechanism: parse goals with cross-phase decision refs (e.g., "P3.D-46").
For each, walk to source phase CONTEXT.md + AMEND-LOG.md to confirm decision
still active.

Severity: BLOCK at /vg:review (and /vg:amend for cascade).
"""
from __future__ import annotations

import argparse
import re
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


def parse_cross_phase_ref(decision_ref: str) -> tuple[str, str] | None:
    """Parse "P3.D-46" → ("3", "D-46"); "D-46" → None (same-phase)."""
    m = re.match(r"^P?(\d+(?:\.\d+)?)\.(D-\d+)$", decision_ref)
    if m:
        return (m.group(1), m.group(2))
    return None


def find_phase_dir_by_number(phase_num: str, phases_root: Path) -> Path | None:
    """Resolve phase number to dir under phases_root."""
    candidates = sorted(phases_root.glob(f"{phase_num}-*"))
    if candidates:
        return candidates[0]
    # Try zero-padded
    if "." in phase_num:
        major, minor = phase_num.split(".")
        padded = f"{int(major):02d}.{minor}"
        candidates = sorted(phases_root.glob(f"{padded}-*"))
    else:
        padded = f"{int(phase_num):02d}"
        candidates = sorted(phases_root.glob(f"{padded}-*"))
    return candidates[0] if candidates else None


def is_decision_revoked(phase_dir: Path, decision_id: str) -> tuple[bool, str]:
    """Check if D-XX has been revoked by amendment.

    Convention: AMEND-LOG.md or CONTEXT.md may have:
      "## Revoked: D-46" or "**Status:** revoked" or "REVOKED in P5"
    """
    for fname in ("AMEND-LOG.md", "CONTEXT.md"):
        path = phase_dir / fname
        if not path.exists():
            continue
        text = _read(path)
        # Look for explicit revocation markers near D-XX
        patterns = [
            rf"#{2,4}\s*Revoked:?\s*{re.escape(decision_id)}\b",
            rf"\*\*Status:\*\*\s*revoked.*\b{re.escape(decision_id)}\b",
            rf"\b{re.escape(decision_id)}\b.*\*\*Status:\*\*\s*revoked",
            rf"\bREVOKED\b.*\b{re.escape(decision_id)}\b",
        ]
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE | re.DOTALL):
                return (True, f"{fname} marks {decision_id} revoked")
    return (False, "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify cross-phase D-XX still active")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument("--allow-stale-decisions", action="store_true")
    args = parser.parse_args()

    out = Output(validator="cross-phase-decision-validity")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        if not goals_path.exists():
            emit_and_exit(out)

        goals = parse_goals_with_frontmatter(_read(goals_path))
        phases_root = phase_dir.parent
        violations = 0

        for goal in goals:
            for d_ref in goal["decisions"]:
                parsed = parse_cross_phase_ref(d_ref)
                if not parsed:
                    continue  # Same-phase reference — separate validator handles
                src_phase_num, decision_id = parsed
                src_dir = find_phase_dir_by_number(src_phase_num, phases_root)
                if src_dir is None:
                    violations += 1
                    out.add(
                        Evidence(
                            type="cross_phase_dir_not_found",
                            message=f"{goal['id']}: cites {d_ref} but source phase '{src_phase_num}' dir not found",
                            file=str(goals_path),
                        ),
                        escalate=(args.severity == "block" and not args.allow_stale_decisions),
                    )
                    continue

                # Verify D-XX still active in source phase
                src_context = src_dir / "CONTEXT.md"
                if not src_context.exists():
                    continue
                src_text = _read(src_context)
                if not re.search(rf"^#{{2,4}}\s*{re.escape(decision_id)}\b", src_text, re.MULTILINE):
                    violations += 1
                    out.add(
                        Evidence(
                            type="cross_phase_decision_missing",
                            message=(
                                f"{goal['id']}: cites {d_ref} but {decision_id} not found in "
                                f"{src_dir.name}/CONTEXT.md"
                            ),
                            file=str(goals_path),
                        ),
                        escalate=(args.severity == "block" and not args.allow_stale_decisions),
                    )
                    continue

                revoked, reason = is_decision_revoked(src_dir, decision_id)
                if revoked:
                    violations += 1
                    out.add(
                        Evidence(
                            type="cross_phase_decision_revoked",
                            message=f"{goal['id']}: cites {d_ref} but it was revoked — {reason}",
                            file=str(goals_path),
                            fix_hint=(
                                "Amend goal to cite replacement decision OR remove if no longer relevant. "
                                "Run /vg:amend on this phase to update CONTEXT."
                            ),
                        ),
                        escalate=(args.severity == "block" and not args.allow_stale_decisions),
                    )

        if violations and (args.severity == "warn" or args.allow_stale_decisions):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{violations} stale cross-phase decision(s) downgraded to WARN.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
