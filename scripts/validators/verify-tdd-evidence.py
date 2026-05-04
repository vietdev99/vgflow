#!/usr/bin/env python3
"""
Validator: verify-tdd-evidence.py — R6 Task 9

Post-spawn TDD discipline audit. For every task capsule under
${PHASE_DIR}/.task-capsules/task-*.capsule.json with
`tdd_required: true`, asserts that the executor produced both:

  ${PHASE_DIR}/.test-evidence/task-${task_id}.red.json
  ${PHASE_DIR}/.test-evidence/task-${task_id}.green.json

with:
  - red.exit_code  != 0    (test failed BEFORE the src change)
  - green.exit_code == 0   (test passed AFTER the src change)
  - red.captured_at < green.captured_at  (correct temporal order)

Tasks with `tdd_required` false/missing are skipped (back-compat).

Pairs with the executor procedure steps 7a (red capture) + 7c (green
capture) defined in agents/vg-build-task-executor/SKILL.md and
commands/vg/_shared/build/waves-delegation.md. Both evidence files
are bundled into the SAME single commit per the "ONE commit per task"
hard constraint — this validator only checks evidence shape, not
commit-membership (R5 spawn-budget validator covers commit count).

Usage:  verify-tdd-evidence.py --phase 7.14
        verify-tdd-evidence.py --phase 7.14 --wave-id 3
        verify-tdd-evidence.py --phase-dir /abs/path/to/phase
Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402


def _load_capsule(capsule_path: Path) -> dict | None:
    try:
        return json.loads(capsule_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_evidence(evidence_path: Path) -> dict | None:
    try:
        return json.loads(evidence_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_iso_utc(s) -> datetime | None:
    """Parse ISO 8601 string to UTC datetime. Returns None on parse failure.

    Handles `Z` suffix, fractional seconds, and timezone offsets.
    Naive datetimes are treated as UTC (matches the captured_at contract,
    which executor procedure 7a/7c always emits as UTC).
    Normalizes to UTC for safe comparison — fixes review finding I2:
      Bug A (false-PASS): '2026-05-05T12:00:00.000Z' < '2026-05-05T12:00:00Z'
        lexically (because '.' < 'Z'), but they are the SAME instant.
      Bug B (false-BLOCK): '2026-05-05T12:05:00+07:00' (= 05:05Z) is genuinely
        BEFORE '2026-05-05T05:10:00Z', but lex compare says '+' > '0' → red>green.
    """
    if not isinstance(s, str):
        return None
    try:
        # Python 3.11+ handles trailing 'Z' natively; for 3.10 compat replace it.
        normalized = s.replace("Z", "+00:00") if s.endswith("Z") else s
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _audit_task(out: Output, phase_dir: Path, capsule_path: Path) -> None:
    """Audit one task capsule. Mutates `out` with Evidence on failure."""
    capsule = _load_capsule(capsule_path)
    if capsule is None:
        out.add(Evidence(
            type="malformed_capsule",
            message=f"Capsule unreadable: {capsule_path.name}",
            file=str(capsule_path),
            fix_hint="Re-run pre-executor-check.py to re-materialize the capsule.",
        ))
        return

    # Skip path: tdd_required absent or false → back-compat, no evidence required
    if not capsule.get("tdd_required", False):
        return

    # Resolve task_id from capsule (preferred) or filename
    task_id = (
        capsule.get("task_id")
        or capsule.get("task_id_str")
        or capsule_path.stem.replace(".capsule", "")
    )
    # Strip "task-" prefix variations to derive a consistent stem for evidence files.
    # Capsule files are named .task-capsules/task-04.capsule.json so stem is "task-04";
    # evidence files use the same "task-04" stem.
    evidence_stem = task_id if str(task_id).startswith("task-") else f"task-{task_id}"

    evidence_dir = phase_dir / ".test-evidence"
    red_path = evidence_dir / f"{evidence_stem}.red.json"
    green_path = evidence_dir / f"{evidence_stem}.green.json"

    # Check both files exist
    red_exists = red_path.exists()
    green_exists = green_path.exists()

    if not red_exists:
        out.add(Evidence(
            type="tdd_evidence_missing",
            message=(
                f"Task {task_id}: tdd_required=true but red evidence missing — "
                f"{red_path.name} not found in .test-evidence/"
            ),
            file=str(red_path),
            expected="red.json with exit_code != 0 from pre-fix test run (step 7a)",
            actual="file does not exist",
            fix_hint=(
                "Executor MUST capture red evidence BEFORE applying src changes. "
                "Re-run /vg:build for this wave or override via "
                "--skip-tdd-evidence --override-reason=<ticket>."
            ),
        ))
    if not green_exists:
        out.add(Evidence(
            type="tdd_evidence_missing",
            message=(
                f"Task {task_id}: tdd_required=true but green evidence missing — "
                f"{green_path.name} not found in .test-evidence/"
            ),
            file=str(green_path),
            expected="green.json with exit_code == 0 from post-fix test run (step 7c)",
            actual="file does not exist",
            fix_hint=(
                "Executor MUST capture green evidence AFTER applying src changes. "
                "Re-run /vg:build for this wave or override via "
                "--skip-tdd-evidence --override-reason=<ticket>."
            ),
        ))

    if not (red_exists and green_exists):
        return  # cannot validate further without both files

    red = _load_evidence(red_path)
    green = _load_evidence(green_path)

    if red is None:
        out.add(Evidence(
            type="tdd_evidence_malformed",
            message=f"Task {task_id}: red evidence unreadable JSON",
            file=str(red_path),
            fix_hint="Re-run executor or repair file format.",
        ))
        return
    if green is None:
        out.add(Evidence(
            type="tdd_evidence_malformed",
            message=f"Task {task_id}: green evidence unreadable JSON",
            file=str(green_path),
            fix_hint="Re-run executor or repair file format.",
        ))
        return

    # Check exit codes
    red_rc = red.get("exit_code")
    green_rc = green.get("exit_code")

    if red_rc is None or not isinstance(red_rc, int):
        out.add(Evidence(
            type="tdd_evidence_malformed",
            message=f"Task {task_id}: red evidence missing/invalid exit_code field",
            file=str(red_path),
            expected="exit_code: <int>",
            actual=f"exit_code: {red_rc!r}",
        ))
    elif red_rc == 0:
        out.add(Evidence(
            type="tdd_red_passing",
            message=(
                f"Task {task_id}: red evidence reports exit_code=0 — test "
                f"trivially passed BEFORE src change. TDD discipline broken: "
                f"a passing test cannot drive a fix."
            ),
            file=str(red_path),
            expected="exit_code != 0 (FAIL_BEFORE_FIX)",
            actual=f"exit_code = {red_rc}",
            fix_hint=(
                "The test must FAIL before the src change. Either the test is "
                "asserting the wrong invariant, or the bug doesn't manifest in "
                "this test path. Investigate, then re-run /vg:build."
            ),
        ))

    if green_rc is None or not isinstance(green_rc, int):
        out.add(Evidence(
            type="tdd_evidence_malformed",
            message=f"Task {task_id}: green evidence missing/invalid exit_code field",
            file=str(green_path),
            expected="exit_code: 0",
            actual=f"exit_code: {green_rc!r}",
        ))
    elif green_rc != 0:
        out.add(Evidence(
            type="tdd_green_failing",
            message=(
                f"Task {task_id}: green evidence reports exit_code={green_rc} — "
                f"test still failed AFTER src change. The fix did not satisfy "
                f"the failing case."
            ),
            file=str(green_path),
            expected="exit_code = 0 (PASS_AFTER_FIX)",
            actual=f"exit_code = {green_rc}",
            fix_hint=(
                "The src change did not make the test pass. Re-examine the "
                "implementation against the test assertions, then re-run /vg:build."
            ),
        ))

    # Check temporal order — red MUST come before green.
    # I2 fix: parse ISO-8601 → UTC-normalized datetime instead of lexicographic
    # string compare. String compare false-PASSes mixed precision (12:00:00.000Z
    # vs 12:00:00Z lex'd as red < green even though same instant) and
    # false-BLOCKs cross-timezone evidence (red +07:00 vs green Z compared
    # lexically rather than after UTC normalization).
    red_at = red.get("captured_at")
    green_at = green.get("captured_at")

    if not red_at or not green_at:
        out.add(Evidence(
            type="tdd_evidence_malformed",
            message=(
                f"Task {task_id}: missing captured_at field "
                f"(red={red_at!r}, green={green_at!r})"
            ),
            file=str(capsule_path),
            expected="captured_at: ISO-8601 UTC timestamp on both red + green",
        ))
    else:
        red_dt = _parse_iso_utc(red_at)
        green_dt = _parse_iso_utc(green_at)
        if red_dt is None or green_dt is None:
            out.add(Evidence(
                type="tdd_evidence_bad_timestamp_format",
                message=(
                    f"Task {task_id}: captured_at not parseable as ISO-8601 "
                    f"(red={red_at!r}, green={green_at!r})"
                ),
                file=str(capsule_path),
                expected="ISO-8601 UTC timestamp like '2026-05-05T12:34:56Z' "
                         "(fractional seconds + tz offsets accepted)",
                actual=f"red={red_at!r}, green={green_at!r}",
                fix_hint=(
                    "Evidence files MUST emit captured_at in ISO-8601 format. "
                    "Re-run executor procedure step 7a → src change → 7c so "
                    "both red.json and green.json carry valid timestamps."
                ),
            ))
        elif not (red_dt < green_dt):
            out.add(Evidence(
                type="tdd_evidence_wrong_order",
                message=(
                    f"Task {task_id}: green.captured_at ({green_at}) is not "
                    f"strictly after red.captured_at ({red_at}) when normalized "
                    f"to UTC (red={red_dt.isoformat()}, "
                    f"green={green_dt.isoformat()}). TDD discipline requires "
                    f"red capture BEFORE src change BEFORE green capture."
                ),
                file=str(capsule_path),
                expected="red.captured_at < green.captured_at (UTC-normalized)",
                actual=(
                    f"red={red_at} (UTC {red_dt.isoformat()}), "
                    f"green={green_at} (UTC {green_dt.isoformat()})"
                ),
                fix_hint=(
                    "Re-run executor — the green run must be temporally after "
                    "the red run. Possible cause: file timestamps swapped or "
                    "evidence files written out of order."
                ),
            ))


def main() -> None:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--phase", help="Phase id (e.g. '7.14')")
    ap.add_argument("--phase-dir", help="Absolute path to phase dir (overrides --phase)")
    ap.add_argument("--wave-id", help="(Optional) wave number — informational only, "
                                       "validator audits all capsules in phase regardless")
    args = ap.parse_args()

    out = Output(validator="tdd-evidence")
    with timer(out):
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

        capsule_dir = phase_dir / ".task-capsules"
        if not capsule_dir.exists():
            out.warn(Evidence(
                type="info",
                message=(
                    f"No .task-capsules dir under {phase_dir}. "
                    f"Either build hasn't run yet, or this phase has no tasks."
                ),
            ))
            emit_and_exit(out)

        capsules = sorted(capsule_dir.glob("task-*.capsule.json"))
        if not capsules:
            out.warn(Evidence(
                type="info",
                message=f"No task capsules found under {capsule_dir}.",
            ))
            emit_and_exit(out)

        tdd_count = 0
        for capsule_path in capsules:
            cap = _load_capsule(capsule_path)
            if cap and cap.get("tdd_required", False):
                tdd_count += 1
            _audit_task(out, phase_dir, capsule_path)

        if not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message=(
                    f"TDD evidence audit PASS — {len(capsules)} capsule(s) "
                    f"scanned, {tdd_count} with tdd_required=true validated."
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
