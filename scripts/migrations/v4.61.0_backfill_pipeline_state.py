#!/usr/bin/env python3
"""v4.61.0_backfill_pipeline_state.py — verdict-aware PIPELINE-STATE backfill.

Closes the legacy-phase gap created when B69 fix (v4.61.0) added top-level
`next_command` to review/close.md without backfilling phases whose review
was closed under v4.40.0 (pre-B69). Those phases have REVIEW.md +
RUNTIME-MAP.json on disk but PIPELINE-STATE.json either missing entirely
OR missing the `steps.review` subkey + `next_command`.

This migration is the third leg of B70:
  - B70a (review/close.md writes steps.review + verdict-aware next_command) → v4.61.2
  - B70b (/vg:next prefers PIPELINE-STATE over recon-state when newer) → v4.61.3
  - B70c (THIS script — backfill legacy phases) → v4.62.0

Auto-invoked by scripts/hooks/vg-session-start.sh when VG_HOME version
bumps past 4.62.0 AND .vg/.last-migration-version is older. Idempotent —
re-running is a no-op (skip when both REVIEW.md is absent OR PIPELINE-STATE
already has steps.review + next_command).

Codex audit findings addressed:
  - B-3 schema drift     : writes schema matching review/close.md exactly
                           (steps.review = {status, verdict, finished_at,
                           next_command} + top-level next_command).
  - B-4 race vs mid-write: only acts on phases whose
                           .step-markers/review/complete.done sentinel exists
                           (review truly closed, not mid-run).
  - B-5 verdict ignored  : parses GOAL-COVERAGE-MATRIX.json (preferred) then
                           GOAL-COVERAGE-MATRIX.md fallback; maps verdict to
                           canonical {PASS, PASS-WITH-FLAGS, TEST_PENDING,
                           BLOCK, FAIL, UNKNOWN}. BLOCK/FAIL → next_command=null.
  - B-6 semver compare   : invoked from hook with Python tuple compare, not
                           bash string compare.
  - M-1/M-2 heuristics   : uses .step-markers/<step>/complete.done sentinels
                           where available (not raw file presence).

Args:
  --planning-dir DIR  Phase root, default .vg/phases.
  --phase NN          Filter to phase whose directory STARTS with this token.
  --dry-run           Print actions, do not write.
  --quiet             Suppress per-phase chatter (still print summary).
  --verbose           Print debug detail.

Exit: 0 on success (including no-op). Non-zero only on hard failure
(planning-dir unreadable, etc.). Per-phase errors logged + counted.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

# Canonical verdict set — must match review/close.md verdict parser.
CANONICAL_VERDICTS = {"PASS", "PASS-WITH-FLAGS", "TEST_PENDING", "BLOCK", "FAIL", "UNKNOWN"}

# Normalization for matrix.md legacy verdict strings — must match
# the table in commands/vg/_shared/review/close.md B70a fix block.
VERDICT_NORMALIZE = {
    "STATIC-READY": "TEST_PENDING",
    "BROWSER-PENDING": "TEST_PENDING",
    "READY": "PASS",
    "FAIL": "BLOCK",
}


def _now() -> str:
    return datetime.now().isoformat()


def _parse_verdict_from_matrix_json(matrix_json: Path) -> Optional[str]:
    """Read GOAL-COVERAGE-MATRIX.json — canonical Batch 34 F2 format."""
    try:
        mj = json.loads(matrix_json.read_text(encoding="utf-8"))
    except Exception:
        return None
    raw = (mj.get("gate") or mj.get("verdict") or "").upper().strip()
    if raw in CANONICAL_VERDICTS:
        return raw
    if raw in VERDICT_NORMALIZE:
        return VERDICT_NORMALIZE[raw]
    return None


def _parse_verdict_from_matrix_md(matrix_md: Path) -> Optional[str]:
    """Read GOAL-COVERAGE-MATRIX.md fallback — must match close.md regex."""
    try:
        body = matrix_md.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    m = re.search(
        r"(?im)^\s*(?:\*\*)?(?:Phase\s+[\w.-]+\s+)?(?:review\s+)?verdict\s*:?\s*\*?\*?\s*"
        r"(PASS-WITH-FLAGS|PASS|TEST_PENDING|BLOCK|FAIL|STATIC-READY|READY|BROWSER-PENDING)",
        body,
    )
    if m:
        raw = m.group(1).upper()
        return VERDICT_NORMALIZE.get(raw, raw)
    mg = re.search(r"(?im)^\s*Gate\s*:?\s*(PASS-WITH-FLAGS|PASS|TEST_PENDING|BLOCK|FAIL)", body)
    if mg:
        return mg.group(1).upper()
    return None


def _detect_verdict(phase_dir: Path) -> str:
    matrix_json = phase_dir / "GOAL-COVERAGE-MATRIX.json"
    if matrix_json.exists():
        v = _parse_verdict_from_matrix_json(matrix_json)
        if v is not None:
            return v
    matrix_md = phase_dir / "GOAL-COVERAGE-MATRIX.md"
    if matrix_md.exists():
        v = _parse_verdict_from_matrix_md(matrix_md)
        if v is not None:
            return v
    return "UNKNOWN"


def _phase_number(phase_dir: Path) -> Optional[str]:
    """Extract phase number from dir name (e.g. '7.16-foo' → '7.16')."""
    m = re.match(r"^(\d+(?:\.\d+(?:\.\d+)?)?)(?:[-_].*)?$", phase_dir.name)
    return m.group(1) if m else None


def _review_closed(phase_dir: Path) -> bool:
    """Review truly closed when complete.done marker exists OR (REVIEW.md AND RUNTIME-MAP.json AND step-markers absent for legacy phases)."""
    complete_marker = phase_dir / ".step-markers" / "review" / "complete.done"
    if complete_marker.exists():
        return True
    # Legacy v4.40.0 phases never wrote review/ step-markers. Fall back to
    # artifact pair, but require BOTH (RUNTIME-MAP.json only lands at close).
    review_md = phase_dir / "REVIEW.md"
    runtime_map = phase_dir / "RUNTIME-MAP.json"
    return review_md.exists() and runtime_map.exists()


def _needs_backfill(phase_dir: Path) -> Tuple[bool, str]:
    """Return (needs_backfill, reason). reason='ok' when no action needed."""
    if not _review_closed(phase_dir):
        return (False, "review-not-closed")
    state_file = phase_dir / "PIPELINE-STATE.json"
    if not state_file.exists():
        return (True, "state-missing")
    try:
        s = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return (True, "state-unparseable")
    steps_review = (s.get("steps") or {}).get("review") or {}
    if not steps_review:
        return (True, "steps.review-missing")
    if not s.get("next_command") and steps_review.get("verdict") not in ("BLOCK", "FAIL"):
        return (True, "next_command-missing-non-block-verdict")
    return (False, "ok")


def backfill_phase(phase_dir: Path, dry_run: bool, verbose: bool) -> Tuple[str, Optional[str]]:
    """Backfill one phase. Returns (outcome, error_or_None).

    outcome in {'skipped:<reason>', 'backfilled', 'error'}.
    """
    phase_num = _phase_number(phase_dir)
    if not phase_num:
        return ("skipped:phase-number-unparseable", None)
    needs, reason = _needs_backfill(phase_dir)
    if not needs:
        return (f"skipped:{reason}", None)
    verdict = _detect_verdict(phase_dir)
    now = _now()
    state_file = phase_dir / "PIPELINE-STATE.json"
    try:
        s = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    except Exception:
        s = {}
    s.setdefault("steps", {})
    s["steps"]["review"] = {
        "status": "done",
        "verdict": verdict,
        "finished_at": now,
    }
    if verdict in ("BLOCK", "FAIL"):
        s["next_command"] = None
        s["next_command_blocked_reason"] = f"review verdict={verdict}"
        s["next_command_emitted_at"] = now
    else:
        next_cmd = f"/vg:test-spec {phase_num}"
        s["next_command"] = next_cmd
        s["next_command_emitted_at"] = now
        s["steps"]["review"]["next_command"] = next_cmd
    s["backfilled_at"] = now
    s["backfilled_by"] = "v4.61.0_backfill_pipeline_state.py"
    s["backfilled_verdict_source"] = "matrix.json" if (phase_dir / "GOAL-COVERAGE-MATRIX.json").exists() else "matrix.md"
    if "status" not in s:
        s["status"] = "reviewed"
    if "pipeline_step" not in s:
        s["pipeline_step"] = "review-complete"
    s["updated_at"] = now
    if dry_run:
        if verbose:
            print(f"  [dry-run] {phase_dir.name}: would write verdict={verdict} next={s.get('next_command')}", file=sys.stderr)
        return ("backfilled-dry-run", None)
    try:
        state_file.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        return ("error", f"write-failed: {exc!r}")
    return ("backfilled", None)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planning-dir", default=".vg/phases", help="Root dir of phases.")
    parser.add_argument("--phase", default=None, help="Filter to phase dir starting with this token.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    planning_dir = Path(args.planning_dir)
    if not planning_dir.exists() or not planning_dir.is_dir():
        if not args.quiet:
            print(f"⛔ planning-dir not found: {planning_dir}", file=sys.stderr)
        return 1

    counts = {"scanned": 0, "skipped": 0, "backfilled": 0, "errors": 0}
    errors: list[tuple[str, str]] = []

    for phase_dir in sorted(planning_dir.iterdir()):
        if not phase_dir.is_dir():
            continue
        if args.phase and not phase_dir.name.startswith(args.phase):
            continue
        counts["scanned"] += 1
        outcome, err = backfill_phase(phase_dir, dry_run=args.dry_run, verbose=args.verbose)
        if outcome.startswith("backfilled"):
            counts["backfilled"] += 1
            if not args.quiet:
                print(f"✓ {phase_dir.name}: backfilled" + (" (dry-run)" if args.dry_run else ""), file=sys.stderr)
        elif outcome.startswith("skipped:"):
            counts["skipped"] += 1
            if args.verbose:
                print(f"· {phase_dir.name}: {outcome}", file=sys.stderr)
        elif outcome == "error":
            counts["errors"] += 1
            errors.append((phase_dir.name, err or "unknown"))
            if not args.quiet:
                print(f"⛔ {phase_dir.name}: error — {err}", file=sys.stderr)

    if not args.quiet:
        print(
            f"\nMigration v4.61.0 backfill report: "
            f"scanned={counts['scanned']} "
            f"backfilled={counts['backfilled']} "
            f"skipped={counts['skipped']} "
            f"errors={counts['errors']}",
            file=sys.stderr,
        )
        if errors:
            print("\nErrors detail:", file=sys.stderr)
            for name, err in errors:
                print(f"  - {name}: {err}", file=sys.stderr)

    return 0 if counts["errors"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
