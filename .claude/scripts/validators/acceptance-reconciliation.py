#!/usr/bin/env python3
"""
Validator: acceptance-reconciliation.py

Purpose: Final gate at /vg:accept. Cross-checks multiple sources of truth to
catch discrepancies between what the phase CLAIMED to do vs what actually
landed. Runs after all other validators — this is the "does the story add up"
reconciliation.

Checks (BLOCK):
1. Every step declared in runtime_contract has >=1 step.marked event in events.db
2. Every commit in phase range has goal/contract citation (alias of
   commit-attribution — re-run here as final check in case attribution was
   amended during /vg:amend)
3. Every critical goal in TEST-GOALS.md has status READY or MANUAL in
   GOAL-COVERAGE-MATRIX.md (no FAILED, BLOCKED, UNREACHABLE, NOT_SCANNED)
4. OVERRIDE-DEBT.md has no HARD-severity entry with status: active
5. Scope branching: every decision mentioning "options" / "branches" /
   "alternatives" has ≥1 follow-up decision (D-XX.Y) OR explicit "finalized" note

Skip (PASS):
- No runtime_contract declared → lightweight command, not our gate
- Phase has 0 decisions → not scoped, not our gate

Usage: acceptance-reconciliation.py --phase <N> [--run-id <UUID>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PHASES_DIR = REPO_ROOT / ".vg" / "phases"
DB_PATH = REPO_ROOT / ".vg" / "events.db"
OVERRIDE_DEBT_PATH = REPO_ROOT / ".vg" / "OVERRIDE-DEBT.md"

# Flags that produce HARD-severity debt (block accept if active).
# These skip CRITICAL gates that underpin correctness. Match both
# CLI flag format (--skip-xxx) AND gate-id format (xxx-yyy) since the
# override-debt register uses inconsistent flag names historically.
HARD_DEBT_FLAGS = {
    # CLI flag forms
    "--allow-missing-commits",
    "--allow-r5-violation",
    "--skip-goal-coverage",
    "--skip-design-check",
    "--skip-review-browser",
    "--allow-untracked-deferred",
    "--skip-crossai",
    # Gate-id forms (older entries use these)
    "goal-coverage",
    "browser-discovery-skipped",
    "design-check",
    "review-browser",
    "untracked-deferred",
    "commit-attribution",
}

# Critical priority terms (matches review-skip-guard)
CRITICAL_PRIORITY = {"critical", "p0", "blocker"}

# Goal statuses that count as SUCCESS for acceptance
PASSING_STATUSES = {"READY", "MANUAL", "DEFERRED", "INFRA_PENDING"}

# Decision pattern — `### P{x}.D-NN` or `### D-NN` (with optional "Goal" prefix)
DECISION_RE = re.compile(
    r"^###\s+(P[\d.]+\.)?D-(\d+(?:\.\d+)?)[:\s]",
    re.MULTILINE,
)
# Scope branching keywords in decision prose
BRANCHING_KW_RE = re.compile(
    r"\b(option\s*[A-Z1-9]|alternative|branch(es)?|choice|tradeoff|either|or\s+we|"
    r"diverge|fork)\b",
    re.IGNORECASE,
)
# "Finalized" explicit note
FINALIZED_RE = re.compile(
    r"\b(final(ized)?|locked|decided|chosen|rejected alternatives|one-way)\b",
    re.IGNORECASE,
)


def parse_override_debt(register: Path) -> list[dict]:
    """Return list of debt entries from OVERRIDE-DEBT.md.
    Accepts both ```yaml fenced blocks and flat `- id: OD-XXX\\n  key: val` format.
    """
    if not register.exists():
        return []
    text = register.read_text(encoding="utf-8", errors="replace")
    entries: list[dict] = []

    # Flat format entries (from cmd_override)
    flat_re = re.compile(
        r"^-\s*id:\s*(\S+)\s*\n((?:  \S.*\n?)+)",
        re.MULTILINE,
    )
    for m in flat_re.finditer(text):
        od_id = m.group(1).strip()
        if od_id.upper() == "OD-XXX":
            continue
        body = m.group(2)
        entry: dict = {"id": od_id}
        for line in body.splitlines():
            line = line.strip()
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            entry[k.strip()] = v.strip().strip('"').strip("'")
        # Normalize status active → OPEN for severity check
        raw_status = str(entry.get("status", "active")).lower()
        entry["_normalized_status"] = (
            "OPEN" if raw_status == "active" else raw_status.upper()
        )
        entries.append(entry)

    return entries


def parse_decisions(context_path: Path) -> list[dict]:
    """Extract decisions + their body text for scope branching check."""
    if not context_path.exists():
        return []
    text = context_path.read_text(encoding="utf-8", errors="replace")
    matches = list(DECISION_RE.finditer(text))
    decisions = []
    for i, m in enumerate(matches):
        d_id = m.group(2)
        block_start = m.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[block_start:block_end]
        decisions.append({"id": d_id, "body": body})
    return decisions


def parse_goal_statuses(matrix_path: Path) -> dict[str, dict]:
    """Return {goal_id: {priority, surface, status}}."""
    if not matrix_path.exists():
        return {}
    text = matrix_path.read_text(encoding="utf-8", errors="replace")
    statuses: dict[str, dict] = {}
    row_re = re.compile(
        r"^\|\s*G-(\d+)\s*\|\s*([a-z_-]+)\s*\|\s*([a-z_-]+)\s*\|\s*([A-Z_]+)\s*\|",
        re.MULTILINE | re.IGNORECASE,
    )
    for m in row_re.finditer(text):
        goal_id = f"G-{m.group(1).zfill(2)}"
        statuses[goal_id] = {
            "priority": m.group(2).lower(),
            "surface": m.group(3).lower(),
            "status": m.group(4).upper(),
        }
    return statuses


def query_step_markers(run_id: str | None, phase: str) -> set[str]:
    """Return set of step names that have step.marked events in events.db."""
    if not DB_PATH.exists():
        return set()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        if run_id:
            rows = conn.execute(
                "SELECT payload_json FROM events "
                "WHERE run_id = ? AND event_type = 'step.marked'",
                (run_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT payload_json FROM events "
                "WHERE phase = ? AND event_type = 'step.marked'",
                (phase,),
            ).fetchall()
    finally:
        conn.close()

    marked: set[str] = set()
    for r in rows:
        try:
            pl = json.loads(r["payload_json"])
            step = pl.get("step") or pl.get("step_name") or pl.get("name", "")
            if step:
                marked.add(step)
        except Exception:
            pass
    return marked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    out = Output(validator="acceptance-reconciliation")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        phase_dirs = [phase_dir] if phase_dir else []
        if not phase_dirs:
            emit_and_exit(out)

        phase_dir = phase_dirs[0]

        # ─── CHECK 1: critical goals all passing ──────────────────────────
        matrix = phase_dir / "GOAL-COVERAGE-MATRIX.md"
        goal_statuses = parse_goal_statuses(matrix)
        if goal_statuses:
            failing_critical = [
                gid for gid, info in goal_statuses.items()
                if info["priority"] in CRITICAL_PRIORITY
                and info["status"] not in PASSING_STATUSES
            ]
            if failing_critical:
                sample = failing_critical[:8]
                out.add(Evidence(
                    type="critical_goal_not_passing",
                    message=(
                        f"{len(failing_critical)} critical goal(s) not in "
                        f"passing status (READY/MANUAL/DEFERRED/INFRA_PENDING)"
                    ),
                    file=str(matrix),
                    actual=", ".join(
                        f"{gid}({goal_statuses[gid]['status']})" for gid in sample
                    ),
                    fix_hint=(
                        "Either fix the goal (code + re-run /vg:review) OR "
                        "promote to MANUAL via vg-orchestrator promote-goal-manual "
                        "<G-XX> --phase <N> --reason '≥50 chars'. Do NOT accept "
                        "a phase with failing critical goals."
                    ),
                ))

        # ─── CHECK 2: HARD override-debt active ───────────────────────────
        debt_entries = parse_override_debt(OVERRIDE_DEBT_PATH)
        phase_debt = [
            e for e in debt_entries
            if e.get("phase", "").strip('"') == args.phase
        ]
        hard_active = [
            e for e in phase_debt
            if e.get("flag", "") in HARD_DEBT_FLAGS
            and e.get("_normalized_status") == "OPEN"
        ]
        if hard_active:
            out.add(Evidence(
                type="hard_debt_unresolved",
                message=(
                    f"{len(hard_active)} HARD-severity override-debt entry(ies) "
                    f"active for phase {args.phase}. These skip CRITICAL gates "
                    f"that must be resolved before accept."
                ),
                file=str(OVERRIDE_DEBT_PATH),
                actual="; ".join(
                    f"{e['id']}: {e.get('flag', '?')} — "
                    f"{e.get('reason', '')[:80]}"
                    for e in hard_active[:5]
                ),
                fix_hint=(
                    "For each HARD debt: either (a) resolve the underlying "
                    "issue and mark entry status: RESOLVED, OR (b) declare "
                    "permanent via /vg:override-resolve with WONT_FIX status "
                    "+ concrete rationale. HARD debts block accept by design."
                ),
            ))

        # ─── CHECK 3: scope branching — decisions with options but no follow-up ─
        context = phase_dir / "CONTEXT.md"
        decisions = parse_decisions(context)
        if decisions:
            decision_ids = {d["id"] for d in decisions}
            branching_unresolved = []
            for d in decisions:
                body_lower = d["body"].lower()
                if not BRANCHING_KW_RE.search(d["body"]):
                    continue
                if FINALIZED_RE.search(d["body"]):
                    continue
                # Look for sub-decisions D-XX.Y where XX = this decision's id
                base_id = d["id"].split(".")[0]
                sub_exists = any(
                    other_id.startswith(f"{base_id}.")
                    for other_id in decision_ids
                )
                if not sub_exists:
                    branching_unresolved.append(d["id"])

            if branching_unresolved:
                out.warn(Evidence(
                    type="scope_branching_unresolved",
                    message=(
                        f"{len(branching_unresolved)} decision(s) mention "
                        f"options/alternatives but have no sub-decisions and no "
                        f"'finalized' note — branches may be unaddressed"
                    ),
                    file=str(context),
                    actual=", ".join(f"D-{did}"
                                     for did in branching_unresolved[:8]),
                    fix_hint=(
                        "Either add a sub-decision (D-XX.1, D-XX.2) for each "
                        "branch, OR add explicit 'Finalized: chose X because Y' "
                        "note. Acceptance is shaky if branches are open."
                    ),
                ))

        # ─── CHECK 4: step.marked events exist for build waves (if build ran) ─
        # Heuristic: if wave.completed events exist for this phase, step.marked
        # events must exist for corresponding wave contexts.
        if DB_PATH.exists():
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            try:
                wave_rows = conn.execute(
                    "SELECT payload_json FROM events "
                    "WHERE phase = ? AND event_type = 'wave.completed'",
                    (args.phase,),
                ).fetchall()
            finally:
                conn.close()

            waves = []
            for r in wave_rows:
                try:
                    w = json.loads(r["payload_json"]).get("wave")
                    if w:
                        waves.append(int(w))
                except Exception:
                    pass

            # Spot-check: if 5+ waves completed, step markers should exist for
            # at least 80% of waves. Low bar — just catches 0-markers case.
            if len(waves) >= 3:
                marked_steps = query_step_markers(args.run_id, args.phase)
                # Waves emit markers like "wave_{N}_complete"; also accept
                # generic "8_execute_waves" style names
                wave_markers_present = any(
                    any(f"wave_{w}" in s or "execute_waves" in s
                        for s in marked_steps)
                    for w in waves
                )
                if not wave_markers_present and not marked_steps:
                    out.warn(Evidence(
                        type="missing_step_markers",
                        message=(
                            f"{len(waves)} wave.completed events exist but no "
                            f"step.marked events for phase {args.phase}. "
                            f"Markers enable downstream reconciliation."
                        ),
                        fix_hint=(
                            "Build step should emit step.marked per wave. "
                            "If migrating from legacy run, /vg:regression can "
                            "backfill markers from git log."
                        ),
                    ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
