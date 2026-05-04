#!/usr/bin/env python3
"""
Validator: verify-foundation-to-specs.py — R8-F (Codex closed-loop audit
2026-05-05).

Audits the FOUNDATION→SPECS goal traceability link.

Background — silent gap fix: `/vg:specs` ignores FOUNDATION.md directly.
The existing SPECS preflight only checks ROADMAP phase membership
(commands/vg/_shared/specs/preflight.md:50-63), and roadmap drift is
warning/pause (commands/vg/_shared/roadmap.md:179-201). Result: phase
SPECS.md may declare goals that don't trace back to ANY FOUNDATION/PROJECT
milestone goal — cross-phase milestone integrity broken.

This validator closes the loop: it reads FOUNDATION.md, extracts
`F-XX` milestone-goal IDs, and asserts that the phase SPECS.md cites at
least one of them via:

  1. Explicit `F-XX` reference (e.g. "Per F-02", "Implements F-05")
  2. `Per FOUNDATION.md § <section>` citation (textual link)
  3. `Milestone goal: ...` quoted bullet from FOUNDATION

FOUNDATION.md schema (per commands/vg/project.md:1488 onward):
- `## 4. Decisions` section with per-decision blocks `### F-01: ...`
- IDs are `F-XX` (project-scope, stable across milestones)
- Distinct from `D-XX` (per-phase context decisions, namespaced as
  `P{phase}.D-XX`).

Verdicts:
  - PASS  — ≥1 valid citation found in SPECS body
  - WARN  — FOUNDATION.md absent (legacy / early bootstrap project)
  - BLOCK — FOUNDATION.md exists with goal IDs BUT SPECS has 0 citations

FOUNDATION.md lookup (multi-location, in order):
  1. ${VG_REPO_ROOT}/.vg/FOUNDATION.md          (canonical, current convention)
  2. ${VG_REPO_ROOT}/.planning/FOUNDATION.md    (legacy GSD path)
  3. ${VG_REPO_ROOT}/FOUNDATION.md              (repo root, very early bootstrap)

Args:
  --phase N             Phase id (e.g. "7.14") — uses find_phase_dir
  --phase-dir PATH      Direct phase dir override (preferred when caller has it)

Override (in callers):
  --skip-foundation-trace  + --override-reason=<≥50ch>
  Logs HARD debt via override-debt register; emits
  `specs.foundation_trace_skipped` event for telemetry.

Output: vg.validator-output JSON on stdout
        rc=0 PASS/WARN, rc=1 BLOCK
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

# F-XX id pattern (1+ digits, anchored on word boundary so we don't match
# F-01-style suffixes inside larger tokens like "AF-01").
F_ID_RE = re.compile(r"\bF-\d+\b")

# "Per FOUNDATION.md ..." or "FOUNDATION.md §..." style citation
FOUNDATION_TEXT_CITE_RE = re.compile(r"FOUNDATION\.md", re.IGNORECASE)

# "Milestone goal: ..." line (loose — case-insensitive, allows :, –, —)
MILESTONE_GOAL_RE = re.compile(r"\bMilestone\s+goal\b", re.IGNORECASE)


def _foundation_locations(repo_root: Path) -> list[Path]:
    """Ordered candidate locations where FOUNDATION.md may live."""
    return [
        repo_root / ".vg" / "FOUNDATION.md",
        repo_root / ".planning" / "FOUNDATION.md",
        repo_root / "FOUNDATION.md",
    ]


def _find_foundation(repo_root: Path) -> Path | None:
    """Return the first existing FOUNDATION.md candidate, or None."""
    for cand in _foundation_locations(repo_root):
        if cand.is_file():
            return cand
    return None


def _extract_foundation_goal_ids(foundation_text: str) -> set[str]:
    """Pull F-XX ids out of FOUNDATION.md body.

    Conservative: we capture every `\\bF-\\d+\\b` token. False positives are
    extremely unlikely in FOUNDATION.md — the schema reserves this prefix
    for project-scope decisions per the project.md namespace rule.
    """
    return set(F_ID_RE.findall(foundation_text))


def _specs_citations(specs_text: str, foundation_ids: set[str]) -> dict:
    """Inspect specs body for FOUNDATION links.

    Returns {
      "f_id_hits": [<id>, ...],          # F-XX ids actually cited
      "textual_cite": bool,              # "FOUNDATION.md" mentioned
      "milestone_goal_cite": bool,       # "Milestone goal" line present
    }
    """
    found_ids = set(F_ID_RE.findall(specs_text))
    # Only count IDs that actually exist in FOUNDATION (anti-hallucination
    # guard — if SPECS cites F-99 but FOUNDATION lists only F-01..F-08,
    # that's not a real trace; treat as missing for hit-set computation).
    real_hits = sorted(found_ids & foundation_ids) if foundation_ids else sorted(found_ids)
    return {
        "f_id_hits": real_hits,
        "textual_cite": bool(FOUNDATION_TEXT_CITE_RE.search(specs_text)),
        "milestone_goal_cite": bool(MILESTONE_GOAL_RE.search(specs_text)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--phase", help="Phase id (e.g. '7.14')")
    ap.add_argument("--phase-dir", help="Absolute path to phase dir (overrides --phase)")
    args = ap.parse_args()

    out = Output(validator="foundation-to-specs")
    with timer(out):
        repo_root = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

        # Resolve phase dir
        if args.phase_dir:
            phase_dir = Path(args.phase_dir)
            if not phase_dir.is_absolute():
                phase_dir = Path.cwd() / phase_dir
            if not phase_dir.exists():
                out.warn(Evidence(
                    type="info",
                    message=f"--phase-dir does not exist: {phase_dir}",
                ))
                emit_and_exit(out)
        elif args.phase:
            phase_dir = find_phase_dir(args.phase)
            if not phase_dir:
                out.warn(Evidence(
                    type="info",
                    message=f"Phase dir not found for {args.phase} — skipping",
                ))
                emit_and_exit(out)
        else:
            ap.error("either --phase or --phase-dir is required")

        specs_path = phase_dir / "SPECS.md"
        if not specs_path.exists():
            # SPECS hasn't been written yet — this validator is a preflight,
            # so an absent SPECS just means /vg:specs is about to write it.
            # Emit info + PASS; the runtime_contract.must_write check will
            # gate post-write.
            out.evidence.append(Evidence(
                type="info",
                message=(
                    f"No SPECS.md at {specs_path}. Validator runs as preflight "
                    f"— skip until SPECS is authored."
                ),
            ))
            emit_and_exit(out)

        foundation_path = _find_foundation(repo_root)

        if foundation_path is None:
            # Legacy / early bootstrap projects — no FOUNDATION yet. Warn,
            # don't block. The /vg:project skill is the canonical fix.
            tried = [str(p) for p in _foundation_locations(repo_root)]
            out.warn(Evidence(
                type="foundation_absent",
                message=(
                    "FOUNDATION.md not found in any canonical location — cannot "
                    "audit FOUNDATION→SPECS trace. Treating as legacy/bootstrap "
                    "project."
                ),
                expected="FOUNDATION.md present at .vg/, .planning/, or repo root",
                actual=f"checked: {tried}",
                fix_hint=(
                    "Run /vg:project to derive FOUNDATION.md from project "
                    "discussion. Then re-run /vg:specs to enforce trace."
                ),
            ))
            emit_and_exit(out)

        try:
            foundation_text = foundation_path.read_text(encoding="utf-8")
        except OSError as exc:
            out.add(Evidence(
                type="foundation_unreadable",
                message=f"FOUNDATION.md exists but cannot be read: {exc}",
                file=str(foundation_path),
                fix_hint="Inspect file permissions / encoding.",
            ))
            emit_and_exit(out)

        foundation_ids = _extract_foundation_goal_ids(foundation_text)

        if not foundation_ids:
            # FOUNDATION exists but has no F-XX goals. Warn — could be an
            # early stub waiting for /vg:project to fill it. SPECS can't
            # cite what doesn't exist yet.
            out.warn(Evidence(
                type="foundation_no_goals",
                message=(
                    f"FOUNDATION.md found at {foundation_path.relative_to(repo_root)} "
                    f"but contains no F-XX milestone goal ids. Trace check is "
                    f"vacuous — nothing to cite."
                ),
                file=str(foundation_path),
                expected="FOUNDATION.md with `### F-XX:` decision blocks",
                fix_hint=(
                    "Run /vg:project to populate FOUNDATION.md with derived "
                    "F-XX decisions (Round 4 'Decisions' section)."
                ),
            ))
            emit_and_exit(out)

        try:
            specs_text = specs_path.read_text(encoding="utf-8")
        except OSError as exc:
            out.add(Evidence(
                type="specs_unreadable",
                message=f"SPECS.md exists but cannot be read: {exc}",
                file=str(specs_path),
                fix_hint="Inspect file permissions / encoding.",
            ))
            emit_and_exit(out)

        cites = _specs_citations(specs_text, foundation_ids)
        has_trace = (
            bool(cites["f_id_hits"])
            or cites["textual_cite"]
            or cites["milestone_goal_cite"]
        )

        if has_trace:
            kinds: list[str] = []
            if cites["f_id_hits"]:
                kinds.append(f"F-id hits: {', '.join(cites['f_id_hits'])}")
            if cites["textual_cite"]:
                kinds.append("FOUNDATION.md textual citation")
            if cites["milestone_goal_cite"]:
                kinds.append("Milestone goal quotation")
            out.evidence.append(Evidence(
                type="info",
                message=(
                    f"FOUNDATION→SPECS trace OK for "
                    f"{phase_dir.name} — {' + '.join(kinds)}. "
                    f"FOUNDATION goal pool: {len(foundation_ids)} id(s)."
                ),
                file=str(specs_path),
            ))
            emit_and_exit(out)

        # No citations of any kind — BLOCK
        sample_ids = ", ".join(sorted(foundation_ids)[:5])
        if len(foundation_ids) > 5:
            sample_ids += f", … (+{len(foundation_ids) - 5} more)"
        out.add(Evidence(
            type="foundation_trace_missing",
            message=(
                f"SPECS.md at {specs_path.relative_to(repo_root)} does NOT cite "
                f"any FOUNDATION milestone goal. FOUNDATION.md has "
                f"{len(foundation_ids)} F-XX goal(s) ({sample_ids}); SPECS body "
                f"has 0 trace markers. Cross-phase milestone integrity broken — "
                f"this phase's goals don't link back to project foundation."
            ),
            file=str(specs_path),
            expected=(
                "SPECS body cites ≥1 of: explicit F-XX reference, "
                "'Per FOUNDATION.md § ...' citation, OR 'Milestone goal: ...' "
                "quoted bullet from FOUNDATION."
            ),
            actual="0 F-XX hits, 0 textual citations, 0 milestone-goal quotes",
            fix_hint=(
                "Add a `## Foundation trace` (or inline) section to SPECS.md "
                "naming the FOUNDATION goal(s) this phase advances, e.g. "
                "'Implements F-04 (Backend topology) by adding the order-events "
                "queue.' Or override at preflight via `--skip-foundation-trace "
                "--override-reason=<≥50 char justification>` for genuinely "
                "infra-only phases."
            ),
        ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
