#!/usr/bin/env python3
"""
Validator: verify-milestone-foundation-coverage.py — R8-G

Cross-phase milestone integrity check. Per-phase traceability already exists
(SPECS, RUNTIME-MAP, UAT) and milestone summary aggregates phase status. But
nothing currently maps FOUNDATION milestone goals → phases citing the goal →
deployed runtime evidence → "satisfied". VG verifies "did we build it RIGHT?"
per phase, but not "did we build the RIGHT THING?" at milestone close.

This validator closes the Q-loop:

  For each F-XX milestone goal listed in FOUNDATION.md under the target
  milestone heading:
    1. Find phases that CITE F-XX in their SPECS.md (regex F-\\d+)
    2. For each citing phase, check whether UAT verdict = ACCEPTED
       (recognises both ``${PHASE}-UAT.md`` (modern) and ``UAT.md`` (legacy)
       per R8-H glob fix)
    3. For each accepted phase, check for runtime evidence linking back to
       the goal — RUNTIME-MAP.json (preferred) or RUNTIME-MAP.md (legacy)

Per-goal verdict:
  SATISFIED   — ≥1 phase cites F-XX AND has UAT ACCEPTED AND has runtime evidence
  PARTIAL     — phase cites + UAT accepted but NO runtime evidence
  UNSATISFIED — no phase cites F-XX OR none accepted

Aggregate verdict:
  PASS        — all milestone goals SATISFIED
  WARN        — some PARTIAL (informational; operator decides)
  BLOCK       — any UNSATISFIED (rc=1, override via
                --allow-unsatisfied-foundation-goals at the command layer)

Side-effect: writes ``.vg/milestones/{M}/FOUNDATION-COVERAGE-MATRIX.md`` with
the goal × phase × evidence join — this is the durable artifact for milestone
hand-off review.

Usage:
  verify-milestone-foundation-coverage.py --milestone M1
  verify-milestone-foundation-coverage.py --milestone M1 --no-write-matrix
  verify-milestone-foundation-coverage.py            # auto-detect from STATE.md

Exit codes (per _common.emit_and_exit):
  0  PASS or WARN
  1  BLOCK
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PLANNING_DIR = Path(os.environ.get("VG_PLANNING_DIR") or REPO_ROOT / ".vg")

# F-XX goal id (allow F-1, F-01, F-100). Used for both extraction from
# FOUNDATION.md and citation scan in SPECS.md.
GOAL_ID_RE = re.compile(r"\bF-(\d{1,3})\b")
PHASE_DIR_RE = re.compile(r"^(\d+(?:\.\d+)?)(?:-.*)?$")


# ─── FOUNDATION extraction (inline; no R8-F dep) ──────────────────────────


def _find_foundation() -> Path | None:
    """Locate FOUNDATION.md — .vg/ canonical first, .planning/ legacy fallback."""
    candidates = [
        PLANNING_DIR / "FOUNDATION.md",
        REPO_ROOT / ".vg" / "FOUNDATION.md",
        REPO_ROOT / "FOUNDATION.md",
        REPO_ROOT / ".planning" / "FOUNDATION.md",
    ]
    seen: set[Path] = set()
    for p in candidates:
        rp = p.resolve() if p.exists() else p
        if rp in seen:
            continue
        seen.add(rp)
        if p.exists():
            return p
    return None


def _extract_milestone_goals(foundation_text: str, milestone: str) -> list[tuple[str, str]]:
    """Extract goal IDs + their inline description for the target milestone.

    Looks for markdown headers matching one of:
      ## M1 ...
      ## Milestone M1 ...
      ## Milestone 1 ...
      ### M1 ...
    Then scans the section body for ``F-XX`` IDs (with optional inline
    description following the ID on the same line, e.g.
    ``- F-01: User authentication``).

    Returns list of ``(goal_id, description)`` in order of first appearance.
    Description may be empty string if not parseable from the line.

    Args:
      foundation_text: full FOUNDATION.md text
      milestone:       e.g. "M1", "1", "m1"

    Returns:
      [] when milestone section not found OR no F-XX IDs in the section.
    """
    m_id = milestone.strip()
    m_num = m_id.lstrip("Mm")

    patterns = [
        rf"^#{{2,3}}\s+{re.escape(m_id)}\b(.+?)(?=^#{{1,3}}\s|\Z)",
        rf"^#{{2,3}}\s+Milestone\s+{re.escape(m_id)}\b(.+?)(?=^#{{1,3}}\s|\Z)",
        rf"^#{{2,3}}\s+Milestone\s+{re.escape(m_num)}\b(.+?)(?=^#{{1,3}}\s|\Z)",
        # Goals header: "## M1 Goals" or "## Milestone 1 Goals"
        rf"^#{{2,3}}\s+{re.escape(m_id)}\s+Goals?\b(.+?)(?=^#{{1,3}}\s|\Z)",
    ]

    section: str | None = None
    for pat in patterns:
        m = re.search(pat, foundation_text, re.MULTILINE | re.DOTALL)
        if m:
            section = m.group(1)
            break

    if section is None:
        return []

    seen: dict[str, str] = {}
    order: list[str] = []
    for line in section.splitlines():
        for match in GOAL_ID_RE.finditer(line):
            num = match.group(1)
            gid = f"F-{num}"
            if gid in seen:
                continue
            # Best-effort description: take whatever follows the goal id on
            # the same line, after any ":" / "—" / "-".
            tail = line[match.end():].strip()
            tail = re.sub(r"^[\s:—\-–|]+", "", tail)
            # Trim long tails / trailing punctuation
            tail = tail.split(" — ", 1)[0].strip().rstrip(".")
            seen[gid] = tail[:80]
            order.append(gid)
    return [(gid, seen[gid]) for gid in order]


# ─── Phase resolution (mirrors complete-milestone.discover_phases) ────────


def _discover_phases_for_milestone(milestone: str) -> list[Path]:
    phases_root = PLANNING_DIR / "phases"
    if not phases_root.is_dir():
        # Also check archived path
        archived = PLANNING_DIR / "milestones" / milestone / "phases"
        if archived.is_dir():
            phases_root = archived
        else:
            return []

    def _phase_key(p: Path) -> tuple[float, str]:
        m = PHASE_DIR_RE.match(p.name)
        if not m:
            return (1e9, p.name)
        try:
            return (float(m.group(1)), p.name)
        except ValueError:
            return (1e9, p.name)

    all_phases = sorted(
        (p for p in phases_root.iterdir() if p.is_dir() and PHASE_DIR_RE.match(p.name)),
        key=_phase_key,
    )

    # Also include phases archived under .vg/milestones/{M}/phases/ if
    # archive ran first
    archived_root = PLANNING_DIR / "milestones" / milestone / "phases"
    if archived_root.is_dir() and archived_root != phases_root:
        archived = sorted(
            (p for p in archived_root.iterdir() if p.is_dir() and PHASE_DIR_RE.match(p.name)),
            key=_phase_key,
        )
        # de-dup by name
        seen_names = {p.name for p in all_phases}
        for p in archived:
            if p.name not in seen_names:
                all_phases.append(p)

    roadmap = PLANNING_DIR / "ROADMAP.md"
    if roadmap.is_file():
        txt = roadmap.read_text(encoding="utf-8", errors="replace")
        m_id = milestone
        m_num = milestone.lstrip("Mm")
        for pat in (
            rf"##\s*{re.escape(m_id)}\b(.+?)(?=\n##\s|\Z)",
            rf"##\s*Milestone\s*{re.escape(m_id)}\b(.+?)(?=\n##\s|\Z)",
            rf"##\s*Milestone\s*{re.escape(m_num)}\b(.+?)(?=\n##\s|\Z)",
        ):
            section = re.search(pat, txt, re.S)
            if section:
                phase_nums = set(re.findall(r"Phase\s*(\d+(?:\.\d+)?)", section.group(1)))
                if phase_nums:
                    return [
                        p for p in all_phases
                        if PHASE_DIR_RE.match(p.name).group(1) in phase_nums
                    ]
    return all_phases


# ─── Per-phase artifact checks ────────────────────────────────────────────


def _phase_specs_text(phase_dir: Path) -> str:
    """Concatenate SPECS.md content (search common shapes)."""
    candidates = [
        phase_dir / "SPECS.md",
        phase_dir / "specs.md",
    ]
    for c in candidates:
        if c.is_file():
            try:
                return c.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return ""


def _phase_cites(phase_dir: Path, goal_id: str) -> bool:
    text = _phase_specs_text(phase_dir)
    if not text:
        return False
    # Match exact goal id; tolerate F-1 vs F-01 by normalizing both sides.
    target_num = goal_id.split("-", 1)[1].lstrip("0") or "0"
    for match in GOAL_ID_RE.finditer(text):
        cited_num = match.group(1).lstrip("0") or "0"
        if cited_num == target_num:
            return True
    return False


def _phase_uat_verdict(phase_dir: Path) -> str:
    """Return 'ACCEPTED' / 'REJECTED' / 'PENDING' / 'NONE'.

    Reads ``${PHASE}-UAT.md`` (modern, R8-H) first then plain ``UAT.md``
    (legacy). Verdict is parsed from a line like ``Verdict: ACCEPTED``
    (case-insensitive). Files lacking explicit Verdict but present count
    as PENDING.
    """
    candidates: list[Path] = []
    candidates.extend(sorted(phase_dir.glob("*-UAT.md")))
    legacy = phase_dir / "UAT.md"
    if legacy.is_file():
        candidates.append(legacy)

    if not candidates:
        return "NONE"

    for uat in candidates:
        try:
            text = uat.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # First Verdict line wins
        m = re.search(r"^\s*\**\s*Verdict\s*[:=]\s*([A-Za-z_-]+)", text, re.MULTILINE)
        if m:
            v = m.group(1).strip().upper()
            if v in ("ACCEPTED", "ACCEPT", "PASS", "PASSED"):
                return "ACCEPTED"
            if v in ("REJECTED", "REJECT", "FAIL", "FAILED", "BLOCKED"):
                return "REJECTED"
            return v
    return "PENDING"


def _phase_runtime_evidence(phase_dir: Path, goal_id: str) -> bool:
    """Check whether RUNTIME-MAP links the goal back to deployed code.

    Looks for both .json (preferred) and .md shapes. For .json, treat any
    occurrence of the goal id in the text as evidence. For .md, same — we
    only need to confirm the goal is namedropped in the runtime map (the
    map shape itself is verified by other validators).
    """
    candidates = [
        phase_dir / "RUNTIME-MAP.json",
        phase_dir / "runtime-map.json",
        phase_dir / "RUNTIME-MAP.md",
        phase_dir / "runtime-map.md",
    ]
    target_num = goal_id.split("-", 1)[1].lstrip("0") or "0"
    for c in candidates:
        if not c.is_file():
            continue
        try:
            text = c.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in GOAL_ID_RE.finditer(text):
            n = match.group(1).lstrip("0") or "0"
            if n == target_num:
                return True
    return False


# ─── Coverage compute ─────────────────────────────────────────────────────


def _compute_coverage(
    goals: list[tuple[str, str]],
    phases: list[Path],
) -> list[dict]:
    """Build per-goal coverage rows."""
    rows: list[dict] = []
    for goal_id, desc in goals:
        citing: list[Path] = [p for p in phases if _phase_cites(p, goal_id)]
        verdicts: list[tuple[Path, str]] = [(p, _phase_uat_verdict(p)) for p in citing]
        accepted: list[Path] = [p for p, v in verdicts if v == "ACCEPTED"]
        with_runtime: list[Path] = [
            p for p in accepted if _phase_runtime_evidence(p, goal_id)
        ]

        if not citing:
            status = "UNSATISFIED"
            reason = "no phase cites"
        elif not accepted:
            status = "UNSATISFIED"
            reason = "no citing phase has UAT ACCEPTED"
        elif not with_runtime:
            status = "PARTIAL"
            reason = "accepted phase(s) lack runtime evidence"
        else:
            status = "SATISFIED"
            reason = ""

        rows.append({
            "goal_id": goal_id,
            "description": desc,
            "citing_phases": [p.name for p in citing],
            "verdicts": [{"phase": p.name, "verdict": v} for p, v in verdicts],
            "accepted_phases": [p.name for p in accepted],
            "phases_with_runtime_evidence": [p.name for p in with_runtime],
            "status": status,
            "reason": reason,
        })
    return rows


# ─── Matrix artifact write ────────────────────────────────────────────────


def _status_glyph(status: str) -> str:
    return {
        "SATISFIED":   "[ok] SATISFIED",
        "PARTIAL":     "[warn] PARTIAL",
        "UNSATISFIED": "[block] UNSATISFIED",
    }.get(status, status)


def _write_matrix(milestone: str, rows: list[dict], aggregate: str) -> Path:
    """Write FOUNDATION-COVERAGE-MATRIX.md and return its path."""
    out_dir = PLANNING_DIR / "milestones" / milestone
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "FOUNDATION-COVERAGE-MATRIX.md"

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        f"# Foundation Coverage Matrix — Milestone {milestone}",
        "",
        f"Generated: {now}",
        f"Aggregate verdict: **{aggregate}**",
        "",
        "| Goal | Description | Phases citing | UAT verdicts | Runtime evidence | Status |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        citing = ", ".join(row["citing_phases"]) or "—"
        verdicts = ", ".join(f"{v['phase']}:{v['verdict']}" for v in row["verdicts"]) or "—"
        runtime = ", ".join(row["phases_with_runtime_evidence"]) or "—"
        desc = row["description"] or "—"
        # escape pipes in desc
        desc = desc.replace("|", "\\|")
        lines.append(
            f"| {row['goal_id']} | {desc} | {citing} | {verdicts} | {runtime} "
            f"| {_status_glyph(row['status'])} |"
        )

    lines.extend([
        "",
        "## Verdict Legend",
        "",
        "- **SATISFIED** — ≥1 phase cites the goal in SPECS.md, has UAT ACCEPTED, "
        "and runtime evidence (RUNTIME-MAP) references the goal id.",
        "- **PARTIAL** — phase cites the goal and UAT is ACCEPTED, but RUNTIME-MAP "
        "does not reference the goal id back to deployed code.",
        "- **UNSATISFIED** — no phase cites the goal, OR no citing phase has been "
        "UAT-accepted yet.",
        "",
        "Override: `/vg:complete-milestone <M> --allow-unsatisfied-foundation-goals "
        "--override-reason=\"…\"` logs an OVERRIDE-DEBT entry and proceeds.",
        "",
    ])

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# ─── Main ─────────────────────────────────────────────────────────────────


def _resolve_milestone(arg: str | None) -> str | None:
    if arg:
        return arg
    state = PLANNING_DIR / "STATE.md"
    if not state.is_file():
        return None
    try:
        text = state.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"^current_milestone\s*:\s*(\S+)", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None


def main() -> None:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--milestone", help="Milestone id (e.g. 'M1'). Auto-detect from STATE.md if omitted.")
    ap.add_argument("--no-write-matrix", action="store_true",
                    help="Skip writing FOUNDATION-COVERAGE-MATRIX.md (read-only check)")
    ap.add_argument("--json", action="store_true",
                    help="Emit verbose JSON payload alongside vg.validator-output (debugging)")
    args = ap.parse_args()

    out = Output(validator="milestone-foundation-coverage")

    with timer(out):
        milestone = _resolve_milestone(args.milestone)
        if not milestone:
            out.warn(Evidence(
                type="milestone_unresolved",
                message=(
                    "Cannot resolve milestone — pass --milestone <id> or set "
                    "current_milestone in .vg/STATE.md."
                ),
                fix_hint="Re-run with --milestone M1 (or your current milestone id).",
            ))
            emit_and_exit(out)
            return

        # ── Step 1: locate FOUNDATION.md ──────────────────────────────────
        foundation_path = _find_foundation()
        if foundation_path is None:
            out.warn(Evidence(
                type="foundation_missing",
                message=(
                    f"FOUNDATION.md not found — milestone {milestone} foundation "
                    f"coverage cannot be computed. Common for early projects "
                    f"that haven't run /vg:project."
                ),
                fix_hint=(
                    "Run /vg:project to create FOUNDATION.md, then re-run "
                    "/vg:complete-milestone."
                ),
            ))
            emit_and_exit(out)
            return

        try:
            foundation_text = foundation_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            out.warn(Evidence(
                type="foundation_read_error",
                message=f"Cannot read FOUNDATION.md: {exc}",
                file=str(foundation_path),
            ))
            emit_and_exit(out)
            return

        goals = _extract_milestone_goals(foundation_text, milestone)
        if not goals:
            out.warn(Evidence(
                type="milestone_goals_not_extracted",
                message=(
                    f"No F-XX goal ids found under milestone {milestone} in "
                    f"FOUNDATION.md. Expected a section like '## Milestone "
                    f"{milestone}' or '## {milestone} Goals' with bullet "
                    f"items containing 'F-XX' identifiers."
                ),
                file=str(foundation_path),
                fix_hint=(
                    "Add a milestone goals section to FOUNDATION.md, or pass "
                    "--milestone with the correct id. Without milestone goals, "
                    "this validator falls back to advisory mode."
                ),
            ))
            emit_and_exit(out)
            return

        # ── Step 2: resolve phases for milestone ──────────────────────────
        phases = _discover_phases_for_milestone(milestone)
        # Even with no phases we can still write a matrix showing all
        # goals UNSATISFIED — this is the desired BLOCK signal.

        # ── Step 3: compute coverage ──────────────────────────────────────
        rows = _compute_coverage(goals, phases)

        unsatisfied = [r for r in rows if r["status"] == "UNSATISFIED"]
        partial = [r for r in rows if r["status"] == "PARTIAL"]

        # Aggregate verdict
        if unsatisfied:
            aggregate = "BLOCK"
        elif partial:
            aggregate = "WARN"
        else:
            aggregate = "PASS"

        # ── Step 4: write matrix artifact ─────────────────────────────────
        if not args.no_write_matrix:
            try:
                matrix_path = _write_matrix(milestone, rows, aggregate)
            except OSError as exc:
                out.warn(Evidence(
                    type="matrix_write_failed",
                    message=f"Could not write FOUNDATION-COVERAGE-MATRIX.md: {exc}",
                ))
                matrix_path = None
        else:
            matrix_path = None

        # ── Step 5: emit evidence ─────────────────────────────────────────
        if unsatisfied:
            for row in unsatisfied:
                desc_part = f" ({row['description']})" if row["description"] else ""
                out.add(Evidence(
                    type="foundation_goal_unsatisfied",
                    message=(
                        f"Milestone {milestone} goal {row['goal_id']}{desc_part}: "
                        f"{row['reason']}. citing_phases="
                        f"{row['citing_phases'] or 'none'}"
                    ),
                    file=str(foundation_path),
                    expected="≥1 phase cites goal AND has UAT ACCEPTED AND runtime evidence",
                    actual=(
                        f"citing={row['citing_phases'] or 'none'}, "
                        f"accepted={row['accepted_phases'] or 'none'}, "
                        f"runtime={row['phases_with_runtime_evidence'] or 'none'}"
                    ),
                    fix_hint=(
                        f"Either add a phase that delivers {row['goal_id']} (and "
                        f"cite it in SPECS.md), accept the existing citing "
                        f"phase via /vg:accept, or override at milestone close "
                        f"with --allow-unsatisfied-foundation-goals + "
                        f"--override-reason."
                    ),
                ))

        for row in partial:
            desc_part = f" ({row['description']})" if row["description"] else ""
            out.warn(Evidence(
                type="foundation_goal_partial",
                message=(
                    f"Milestone {milestone} goal {row['goal_id']}{desc_part}: "
                    f"phase(s) cite + UAT accepted but RUNTIME-MAP does not "
                    f"reference the goal back to deployed code. "
                    f"accepted_phases={row['accepted_phases']}"
                ),
                file=str(foundation_path),
                expected="RUNTIME-MAP.json/.md to mention the goal id",
                actual=f"accepted phases={row['accepted_phases']} but no runtime link",
                fix_hint=(
                    "Add the goal id to the phase RUNTIME-MAP entries, or "
                    "accept this PARTIAL outcome (it does not block close)."
                ),
            ))

        if not unsatisfied and not partial:
            summary = (
                f"Milestone {milestone}: all {len(goals)} foundation goal(s) "
                f"SATISFIED across {len(phases)} resolved phase(s)."
            )
            if matrix_path:
                summary += f" Matrix written to {matrix_path.relative_to(REPO_ROOT)}."
            out.evidence.append(Evidence(
                type="info",
                message=summary,
            ))

        if args.json:
            print(json.dumps({
                "milestone": milestone,
                "aggregate": aggregate,
                "rows": rows,
                "matrix_path": str(matrix_path) if matrix_path else None,
            }, indent=2), file=sys.stderr)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
