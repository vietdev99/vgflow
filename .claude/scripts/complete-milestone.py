#!/usr/bin/env python3
"""
complete-milestone.py — v2.33.0 milestone closeout orchestrator backbone.

Pure verification + state-mutation engine called by /vg:complete-milestone.
The slash command handles UI prompts + telemetry; this script runs the
checks and writes state atomically.

Order of operations (matches /vg:complete-milestone Step 1-6):
  1. Resolve phases for milestone (ROADMAP.md or --phases override)
  2. Verify all resolved phases are accepted (UAT.md present)
  3. Check security register for blocking-critical OPEN threats
  4. Check OVERRIDE-DEBT for unresolved critical entries
  5. Emit STATE.md update (mark milestone completed, advance current_milestone)
  6. Emit MILESTONE-COMPLETE marker file (.vg/milestones/{M}/.completed)

This script does NOT:
  - Run /vg:security-audit-milestone (slash command handles the spawn)
  - Run /vg:milestone-summary (slash command handles the spawn)
  - Archive phase dirs (slash command handles via git mv for traceability)
  - Commit (slash command commits the atomic group)

Usage:
  complete-milestone.py --milestone M1 --check        # dry-run, exits non-zero on gate fail
  complete-milestone.py --milestone M1 --finalize     # writes STATE.md update + marker
  complete-milestone.py --milestone M1 --finalize \\
    --allow-open-critical="reason for waiver"          # bypass critical gate

Exit codes:
  0 — all gates pass (or --finalize succeeded)
  1 — gate failed (phases not accepted, critical threats open, etc.)
  2 — config / arg error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PLANNING_DIR = Path(os.environ.get("VG_PLANNING_DIR") or REPO_ROOT / ".vg")

PHASE_DIR_RE = re.compile(r"^(\d+)(?:-.*)?$")


def discover_phases(milestone: str, phase_range: str | None) -> list[Path]:
    phases_root = PLANNING_DIR / "phases"
    if not phases_root.is_dir():
        return []
    all_phases = sorted(
        (p for p in phases_root.iterdir() if p.is_dir() and PHASE_DIR_RE.match(p.name)),
        key=lambda p: int(PHASE_DIR_RE.match(p.name).group(1)),
    )
    if phase_range:
        if "-" in phase_range:
            lo, hi = map(int, phase_range.split("-", 1))
        else:
            lo = hi = int(phase_range)
        return [p for p in all_phases if lo <= int(PHASE_DIR_RE.match(p.name).group(1)) <= hi]

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
                phase_nums = set(re.findall(r"Phase\s*(\d+)", section.group(1)))
                return [
                    p for p in all_phases
                    if PHASE_DIR_RE.match(p.name).group(1) in phase_nums
                ]
    return all_phases


def check_phase_acceptance(phases: list[Path]) -> tuple[list[str], list[str]]:
    accepted, missing = [], []
    for p in phases:
        if (p / "UAT.md").is_file():
            accepted.append(p.name)
        else:
            missing.append(p.name)
    return accepted, missing


def check_security_critical_open() -> int:
    candidates = [
        PLANNING_DIR / "SECURITY-REGISTER.md",
        REPO_ROOT / ".planning" / "SECURITY-REGISTER.md",
    ]
    reg = next((c for c in candidates if c.is_file()), None)
    if reg is None:
        return 0
    text = reg.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n###\s+", text)
    count = 0
    for blk in blocks:
        is_critical = re.search(r"\bseverity\s*[:=]\s*[\"']?critical\b", blk, re.I)
        is_open = re.search(r"\bstatus\s*[:=]\s*[\"']?(open|in_progress|in-progress|new)\b", blk, re.I)
        if is_critical and is_open:
            count += 1
    return count


def check_override_debt_critical() -> int:
    candidates = [
        PLANNING_DIR / "OVERRIDE-DEBT.md",
        REPO_ROOT / ".planning" / "OVERRIDE-DEBT.md",
    ]
    od = next((c for c in candidates if c.is_file()), None)
    if od is None:
        return 0
    text = od.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n###\s+", text)
    count = 0
    for blk in blocks:
        is_critical = re.search(r"\bseverity\s*[:=]\s*[\"']?critical\b", blk, re.I)
        is_open = re.search(r"^- \[ \]", blk, re.M)
        if is_critical and is_open:
            count += 1
    return count


def update_state_md(milestone: str, completed_phases: list[str]) -> Path:
    """Append/update STATE.md with milestone completion. Atomic write
    via temp file + rename.
    """
    state_path = PLANNING_DIR / "STATE.md"
    PLANNING_DIR.mkdir(parents=True, exist_ok=True)

    if state_path.is_file():
        text = state_path.read_text(encoding="utf-8", errors="replace")
    else:
        text = ""

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    next_id = _next_milestone_id(milestone)

    cm_re = re.compile(r"^current_milestone\s*:\s*\S+\s*$", re.M)
    if cm_re.search(text):
        text = cm_re.sub(f"current_milestone: {next_id}", text)
    else:
        text = (text.rstrip() + f"\ncurrent_milestone: {next_id}\n").lstrip()

    block_re = re.compile(r"^milestones_completed:\s*$.*?(?=^\S|\Z)", re.M | re.S)
    completed_block_match = block_re.search(text)
    new_entry = (
        f"  - id: {milestone}\n"
        f"    completed_at: {now}\n"
        f"    phases: [{', '.join(completed_phases)}]\n"
    )
    if completed_block_match:
        existing = completed_block_match.group(0)
        if f"id: {milestone}" not in existing:
            updated = existing.rstrip() + "\n" + new_entry
            text = text[: completed_block_match.start()] + updated + text[completed_block_match.end():]
    else:
        text = text.rstrip() + "\n\nmilestones_completed:\n" + new_entry

    tmp_path = state_path.with_suffix(".md.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(state_path)
    return state_path


def _next_milestone_id(current: str) -> str:
    m = re.match(r"^([Mm]?)(\d+)$", current.strip())
    if m:
        prefix = m.group(1) or "M"
        return f"{prefix}{int(m.group(2)) + 1}"
    return current + ".next"


def write_completion_marker(milestone: str, phase_count: int) -> Path:
    milestone_dir = PLANNING_DIR / "milestones" / milestone
    milestone_dir.mkdir(parents=True, exist_ok=True)
    marker = milestone_dir / ".completed"
    payload = {
        "milestone": milestone,
        "completed_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "phase_count": phase_count,
        "vgflow_version": _read_version(),
    }
    marker.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return marker


def _read_version() -> str:
    for c in (REPO_ROOT / "VGFLOW-VERSION", REPO_ROOT / ".claude" / "VGFLOW-VERSION"):
        if c.is_file():
            return c.read_text(encoding="utf-8").strip()
    return "unknown"


def run_checks(milestone: str, phases: list[Path],
               allow_open_critical: str | None,
               allow_open_override_debt: str | None) -> tuple[bool, list[str], dict]:
    """Returns (gate_pass, blocker_messages, payload)."""
    accepted, missing = check_phase_acceptance(phases)
    sec_critical = check_security_critical_open()
    debt_critical = check_override_debt_critical()

    blockers: list[str] = []

    if missing:
        blockers.append(
            f"⛔ {len(missing)} phase(s) NOT accepted (UAT.md missing): {', '.join(missing)}\n"
            "   Run /vg:accept on each before completing milestone."
        )
    if sec_critical > 0 and not allow_open_critical:
        blockers.append(
            f"\033[38;5;208m{sec_critical} CRITICAL threat(s) OPEN in SECURITY-REGISTER.md.\033[0m\n"
            "   Either resolve them, or pass --allow-open-critical=\"<reason>\" "
            "to log an OVERRIDE-DEBT entry and proceed."
        )
    if debt_critical > 0 and not allow_open_override_debt:
        blockers.append(
            f"\033[38;5;208m{debt_critical} CRITICAL OVERRIDE-DEBT entries unresolved.\033[0m\n"
            "   Run /vg:override-resolve <id> on each, or pass "
            "--allow-open-override-debt=\"<reason>\" to defer to next milestone."
        )

    payload = {
        "milestone": milestone,
        "phases_resolved": [p.name for p in phases],
        "phases_accepted": accepted,
        "phases_missing_uat": missing,
        "security_critical_open": sec_critical,
        "override_debt_critical_open": debt_critical,
        "gate_pass": len(blockers) == 0,
        "checked_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return len(blockers) == 0, blockers, payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--milestone", required=True)
    ap.add_argument("--phases", help="Explicit phase range (overrides ROADMAP)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Dry-run gate checks only")
    mode.add_argument("--finalize", action="store_true", help="Write STATE.md + marker")
    ap.add_argument("--allow-open-critical", default=None,
                    help="Reason for proceeding with critical OPEN threats")
    ap.add_argument("--allow-open-override-debt", default=None,
                    help="Reason for deferring critical OVERRIDE-DEBT to next milestone")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phases = discover_phases(args.milestone, args.phases)
    if not phases:
        msg = f"No phases resolved for milestone={args.milestone!r} (phase_range={args.phases!r})"
        if args.json:
            print(json.dumps({"error": msg, "gate_pass": False}, indent=2))
        else:
            print(f"\033[38;5;208m{msg}\033[0m", file=sys.stderr)
        return 2

    gate_pass, blockers, payload = run_checks(
        args.milestone, phases,
        args.allow_open_critical, args.allow_open_override_debt,
    )

    if args.check:
        if args.json:
            print(json.dumps(payload, indent=2))
        elif not args.quiet:
            print(f"━━━ Milestone {args.milestone} gate check ━━━")
            print(f"Phases resolved: {len(phases)}")
            print(f"  Accepted: {len(payload['phases_accepted'])}")
            print(f"  Missing UAT: {len(payload['phases_missing_uat'])}")
            print(f"Security CRITICAL open: {payload['security_critical_open']}")
            print(f"OVERRIDE-DEBT CRITICAL open: {payload['override_debt_critical_open']}")
            print()
            if gate_pass:
                print("✓ All gates pass — safe to /vg:complete-milestone --finalize")
            else:
                for b in blockers:
                    print(b)
        return 0 if gate_pass else 1

    if not gate_pass:
        if args.json:
            print(json.dumps({**payload, "blockers": blockers}, indent=2))
        else:
            for b in blockers:
                print(b, file=sys.stderr)
        return 1

    state_path = update_state_md(args.milestone, [p.name for p in phases])
    marker_path = write_completion_marker(args.milestone, len(phases))

    payload["state_path"] = str(state_path.resolve().relative_to(REPO_ROOT).as_posix())
    payload["marker_path"] = str(marker_path.resolve().relative_to(REPO_ROOT).as_posix())
    payload["allow_open_critical_reason"] = args.allow_open_critical
    payload["allow_open_override_debt_reason"] = args.allow_open_override_debt

    if args.json:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        print(f"✓ Milestone {args.milestone} marked completed.")
        print(f"  STATE.md updated: {payload['state_path']}")
        print(f"  Completion marker: {payload['marker_path']}")
        print(f"  Next milestone: current_milestone -> {_next_milestone_id(args.milestone)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
