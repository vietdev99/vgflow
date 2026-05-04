#!/usr/bin/env python3
"""
Validator: verify-uat-checklist-sections.py — R6 Task 6

Asserts the UAT checklist subagent (`vg-accept-uat-builder`) returned ALL six
canonical ISTQB CT-AcT sections (A/B/C/D/E/F). The legacy inline check in
`commands/vg/_shared/accept/uat/checklist-build/overview.md` only enforced
`sections[] length >= 5` — that accepted payloads missing Section C (Ripple
HIGH callers) and Section F (Mobile gates), which is weaker than the
acceptance-test standard the checklist is built against.

Canonical 6 sections:
  A — Decisions          (CONTEXT.md decisions)
  B — Goals              (TEST-GOALS Layer-1)
  C — Ripple HIGH        (RIPPLE-ANALYSIS.md HIGH-rated callers)
  D — Design refs        (PLAN.md design-ref blocks)
  E — Deliverables       (PLAN.md task summaries)
  F — Mobile gates       (mobile-security/report.md, may be N/A on web profile)

Optional sub-sections allowed alongside the canonical 6:
  A.1 — Foundation cites  (FOUNDATION.md cites)
  B.1 — CRUD surfaces     (CRUD-SURFACES.md rows)

N/A handling:
  Section F is N/A on non-mobile profiles. The SECTION KEY must still exist —
  we accept any of:
    - `items: []` (empty but present)
    - `status: "N/A"` (explicit N/A flag)
    - `note` containing "N/A" or "skipped"
  but BLOCK if the section key itself is absent.

Usage:
  verify-uat-checklist-sections.py --stdin
    Read JSON payload from stdin (used by overview.md after subagent return).
  verify-uat-checklist-sections.py --file path/to/checklist.json
    Read JSON from a file.

Exit:
  0 — PASS or WARN (all canonical sections present)
  1 — BLOCK (missing canonical section)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, timer  # noqa: E402

VALIDATOR_NAME = "verify-uat-checklist-sections"

# ISTQB CT-AcT canonical 6-section enum.
CANONICAL_SECTIONS: tuple[str, ...] = ("A", "B", "C", "D", "E", "F")

# Sub-sections we tolerate alongside the canonical 6 (informational, not required).
ALLOWED_SUBSECTIONS: frozenset[str] = frozenset({"A.1", "B.1"})


def _section_name(section: dict) -> str:
    """Extract a normalized section name from a payload entry."""
    raw = section.get("name") or section.get("id") or ""
    return str(raw).strip()


def _is_na(section: dict) -> bool:
    """Return True if the section is explicitly N/A (still satisfies key-exists)."""
    status = str(section.get("status", "")).strip().lower()
    if status in ("n/a", "na", "skipped", "omitted"):
        return True
    note = str(section.get("note", "")).strip().lower()
    if "n/a" in note or "skipped" in note:
        return True
    return False


def _validate(payload: dict, output: Output) -> None:
    sections_raw = payload.get("sections")
    if not isinstance(sections_raw, list):
        output.add(Evidence(
            type="schema",
            message="payload missing `sections` array",
            expected="list",
            actual=type(sections_raw).__name__,
            fix_hint="vg-accept-uat-builder must return JSON with `sections: [...]`",
        ))
        return

    present_names: set[str] = set()
    for section in sections_raw:
        if not isinstance(section, dict):
            output.add(Evidence(
                type="schema",
                message="section entry is not an object",
                actual=repr(section)[:80],
            ))
            continue
        name = _section_name(section)
        if name:
            present_names.add(name)

    # 1. Every canonical section MUST be present (even if N/A).
    missing = [s for s in CANONICAL_SECTIONS if s not in present_names]
    if missing:
        output.add(Evidence(
            type="canonical_sections",
            message=(
                f"missing canonical UAT section(s): {', '.join(missing)} — "
                "ISTQB CT-AcT requires all 6 (A/B/C/D/E/F)"
            ),
            expected=list(CANONICAL_SECTIONS),
            actual=sorted(present_names),
            fix_hint=(
                "vg-accept-uat-builder must emit a section entry for every "
                "canonical letter. Use `status: \"N/A\"` for non-applicable "
                "sections (e.g. F on web-* profiles) — don't omit the key."
            ),
        ))

    # 2. Unexpected names get a WARN (not BLOCK) — extending checklist is OK
    #    but we want visibility.
    unexpected = sorted(
        n for n in present_names
        if n not in CANONICAL_SECTIONS and n not in ALLOWED_SUBSECTIONS
    )
    if unexpected:
        output.warn(Evidence(
            type="unexpected_sections",
            message=f"unexpected section name(s): {', '.join(unexpected)}",
            expected=list(CANONICAL_SECTIONS) + sorted(ALLOWED_SUBSECTIONS),
            actual=unexpected,
            fix_hint=(
                "Allowed: A, A.1, B, B.1, C, D, E, F. If you need to extend, "
                "update CANONICAL_SECTIONS / ALLOWED_SUBSECTIONS in this validator."
            ),
        ))

    # 3. Surface N/A sections in evidence (PASS, but informational).
    na_sections = [
        _section_name(s) for s in sections_raw
        if isinstance(s, dict) and _is_na(s) and _section_name(s) in CANONICAL_SECTIONS
    ]
    if na_sections and output.verdict == "PASS":
        # Don't escalate — purely informational.
        output.evidence.append(Evidence(
            type="info",
            message=f"sections marked N/A (allowed): {', '.join(na_sections)}",
        ))


def _read_payload(args: argparse.Namespace) -> dict:
    if args.stdin:
        raw = sys.stdin.read()
    elif args.file:
        raw = Path(args.file).read_text(encoding="utf-8")
    else:
        raise SystemExit("must pass --stdin or --file <path>")
    if not raw.strip():
        raise SystemExit("empty payload")
    return json.loads(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdin", action="store_true", help="read JSON from stdin")
    parser.add_argument("--file", help="read JSON from file path")
    args = parser.parse_args()

    output = Output(validator=VALIDATOR_NAME)
    with timer(output):
        try:
            payload = _read_payload(args)
        except (json.JSONDecodeError, OSError) as exc:
            output.add(Evidence(
                type="payload",
                message=f"failed to read payload: {exc}",
                fix_hint="ensure subagent returned valid JSON",
            ))
            emit_and_exit(output)
            return
        _validate(payload, output)

    emit_and_exit(output)


if __name__ == "__main__":
    main()
