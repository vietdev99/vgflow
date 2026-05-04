#!/usr/bin/env python3
"""
Validator: verify-build-crossai-carryover.py — R7-A Task 1 (G5 from codex audit 2026-05-05)

Review preflight gate that ingests the build CrossAI loop terminal state.

Background — silent leak fix: the build CrossAI loop
(`commands/vg/_shared/build/crossai-loop.md`) lets the user pick
`(b) defer` after iteration 5 exhaustion. That path emits:
  - `build.crossai_loop_exhausted` event with payload reason="user_deferred"
  - `${PHASE_DIR}/crossai-build-verify/findings-iter5.json` carrying remaining BLOCK findings

Pre-this-validator, /vg:review preflight ignored both. Result: deferred
findings vanish, accept passes clean, ship bug.

Verdicts (5 cases):
  1. terminal=clean (`build.crossai_loop_complete`)                    → PASS
  2. terminal=exhausted + findings-iter5.json exists                   → BLOCK
     (override: --allow-build-crossai-deferred + --override-reason)
  3. terminal=user_override + findings-iter5.json exists               → WARN
     (already user-acknowledged at build time; informational here)
  4. no terminal event AND findings-iter5.json exists                  → BLOCK
     (build state corrupted — terminal missing, findings present)
  5. no terminal AND no findings                                       → PASS
     (cross-AI build never ran, or it ran and completed clean — covered
     by build-crossai-required.py if /vg:build itself is incomplete)

Args:
  --phase N             Phase id (e.g. "7.14") — uses find_phase_dir
  --phase-dir PATH      Direct phase dir override (preferred when caller has it)

Output: vg.validator-output JSON on stdout
        rc=0 PASS/WARN, rc=1 BLOCK
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
DB_PATH = REPO_ROOT / ".vg" / "events.db"

# Terminal event types emitted by build CrossAI loop
TERMINAL_CLEAN = "build.crossai_loop_complete"
TERMINAL_EXHAUSTED = "build.crossai_loop_exhausted"
TERMINAL_USER_OVERRIDE = "build.crossai_loop_user_override"

ALL_TERMINAL = {TERMINAL_CLEAN, TERMINAL_EXHAUSTED, TERMINAL_USER_OVERRIDE}


def _phase_id_from_dir(phase_dir: Path) -> str:
    """Derive phase id from phase dir name.

    Phase dirs follow `${MAJOR}.${MINOR}-slug` (e.g. `7.14-rfc-foo`) or bare
    `${MAJOR}` legacy. We strip the trailing `-slug` to match how
    `vg-orchestrator run-start` records `phase` on the events row.
    """
    name = phase_dir.name
    # Strip "-suffix" if present (`7.14-rfc-foo` → `7.14`)
    if "-" in name:
        return name.split("-", 1)[0]
    return name


def _latest_terminal_event(phase_id: str) -> dict | None:
    """Read the most recent build-crossai terminal event for this phase.

    Returns None if no terminal event recorded for this phase.
    Scoped by phase (NOT run_id) because /vg:review runs in a different
    run_id than /vg:build — the terminal lives in the build run's history.
    """
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=2.0)
    except sqlite3.OperationalError:
        return None
    try:
        placeholders = ",".join("?" for _ in ALL_TERMINAL)
        row = conn.execute(
            f"SELECT event_type, payload_json, ts "
            f"FROM events "
            f"WHERE phase = ? AND event_type IN ({placeholders}) "
            f"ORDER BY id DESC LIMIT 1",
            [phase_id, *ALL_TERMINAL],
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    if not row:
        return None
    try:
        payload = json.loads(row[1] or "{}")
    except Exception:
        payload = {}
    return {"event_type": row[0], "payload": payload, "ts": row[2]}


def _findings_path(phase_dir: Path) -> Path:
    return phase_dir / "crossai-build-verify" / "findings-iter5.json"


def _load_findings(findings_path: Path) -> list[dict]:
    """Best-effort load of findings array. Returns [] on parse failure."""
    if not findings_path.exists():
        return []
    try:
        data = json.loads(findings_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Common shapes: {"findings": [...]} or {"blocks": [...]}
        for key in ("findings", "blocks", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _summarize_findings(findings: list[dict]) -> str:
    """Compact human summary: count + first few IDs."""
    n = len(findings)
    ids: list[str] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        fid = f.get("id") or f.get("finding_id") or f.get("title")
        if fid:
            ids.append(str(fid))
        if len(ids) >= 5:
            break
    suffix = f": {', '.join(ids)}" + (f" + {n - len(ids)} more" if n > len(ids) else "")
    return f"{n} BLOCK finding(s){suffix if ids else ''}"


def main() -> None:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--phase", help="Phase id (e.g. '7.14')")
    ap.add_argument("--phase-dir", help="Absolute path to phase dir (overrides --phase)")
    args = ap.parse_args()

    out = Output(validator="build-crossai-carryover")
    with timer(out):
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

        phase_id = args.phase or _phase_id_from_dir(phase_dir)
        findings_path = _findings_path(phase_dir)
        findings_exists = findings_path.exists()
        findings = _load_findings(findings_path) if findings_exists else []

        terminal = _latest_terminal_event(phase_id)
        term_type = terminal["event_type"] if terminal else None

        # Case 1: terminal=clean → PASS silently
        if term_type == TERMINAL_CLEAN:
            out.evidence.append(Evidence(
                type="info",
                message=(
                    f"Build CrossAI terminal=clean for phase {phase_id}. "
                    f"No carryover findings."
                ),
            ))
            emit_and_exit(out)

        # Case 2: terminal=exhausted + findings present → BLOCK
        if term_type == TERMINAL_EXHAUSTED and findings_exists:
            summary = _summarize_findings(findings)
            reason = terminal["payload"].get("reason", "unspecified")
            out.add(Evidence(
                type="build_crossai_deferred_findings",
                message=(
                    f"Build CrossAI loop exhausted (5/5 iterations) and user "
                    f"deferred remaining BLOCK findings to /vg:review. "
                    f"Carryover: {summary}. Reason: {reason}. "
                    f"Review must ingest these into its backlog before passing."
                ),
                file=str(findings_path),
                expected="terminal=clean OR --allow-build-crossai-deferred override",
                actual=f"terminal=exhausted + {len(findings)} carryover finding(s)",
                fix_hint=(
                    "Either (a) re-run /vg:build to drive CrossAI loop to clean, "
                    "or (b) acknowledge carryover with: "
                    "/vg:review {phase} --allow-build-crossai-deferred "
                    "--override-reason='<ticket URL or commit SHA, ≥50ch>'. "
                    "The override appends findings to review's backlog and "
                    "logs HARD debt."
                ),
            ))
            emit_and_exit(out)

        # Case 3: terminal=user_override + findings → WARN (already acknowledged)
        if term_type == TERMINAL_USER_OVERRIDE:
            summary = _summarize_findings(findings) if findings_exists else "no findings file"
            reason = terminal["payload"].get("reason", "unspecified")
            out.warn(Evidence(
                type="build_crossai_user_override_acknowledged",
                message=(
                    f"Build CrossAI loop terminated via user_override for phase "
                    f"{phase_id} (reason: {reason}). HARD debt was logged at "
                    f"build time. Carryover: {summary}. Review records as "
                    f"informational — debt resolution is via override-debt "
                    f"register, not this gate."
                ),
                file=str(findings_path) if findings_exists else None,
                fix_hint=(
                    "No action required — override.used was logged at build "
                    "time. The override-debt register tracks resolution."
                ),
            ))
            emit_and_exit(out)

        # Case 4: no terminal event + findings present → BLOCK (corrupted state)
        if term_type is None and findings_exists:
            out.add(Evidence(
                type="build_crossai_state_corrupted",
                message=(
                    f"Build CrossAI carryover findings present at "
                    f"{findings_path.name} but NO terminal event recorded for "
                    f"phase {phase_id}. State corrupted — terminal missing, "
                    f"findings stranded. Build may have crashed mid-loop or "
                    f"someone hand-edited findings without emitting a terminal."
                ),
                file=str(findings_path),
                expected=(
                    "Either: terminal event emitted (clean/exhausted/user_override) "
                    "OR no findings-iter5.json present"
                ),
                actual=f"no terminal event + findings file with {len(findings)} entry(s)",
                fix_hint=(
                    "Investigate: re-run /vg:build for this phase to drive "
                    "loop to a proper terminal state, OR delete "
                    f"{findings_path} if it's a stale artifact."
                ),
            ))
            emit_and_exit(out)

        # Case 5: no terminal + no findings → PASS (CrossAI never ran or
        # ran clean before this validator was wired). Note: build-crossai-
        # required.py is the gate that catches "build run-complete without
        # terminal" — this validator only audits the review side.
        out.evidence.append(Evidence(
            type="info",
            message=(
                f"Build CrossAI: no terminal event + no findings-iter5.json "
                f"for phase {phase_id}. Either CrossAI never ran or it "
                f"completed without leaving carryover state."
            ),
        ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
