#!/usr/bin/env python3
"""
generate-milestone-summary.py — v2.33.0 milestone closeout aggregator.

Produces `.vg/milestones/{M}/MILESTONE-SUMMARY.md` aggregating data from
every phase that belongs to milestone {M}:

  - Phase status (built / reviewed / tested / accepted) from artifact presence
  - Goal coverage (critical/important/nice-to-have totals + achieved)
  - Decisions inventory (D-XX namespace per phase + foundation F-XX)
  - Security register (open threats by severity at close time)
  - Override-debt entries (carried forward into next milestone)
  - Cross-phase blockers / lessons (if `lessons.md` per phase exists)
  - Timeline (first phase started_at → last phase accepted_at)

Phase membership is resolved from ROADMAP.md `## Milestone {M}` section
listing `Phase N` entries, with fallback to all phases if no milestone
section found (single-milestone projects).

Usage:
  generate-milestone-summary.py --milestone M1
  generate-milestone-summary.py --milestone M1 --json
  generate-milestone-summary.py --phases 1-7 --milestone-id M1   # explicit

Exit codes:
  0 — summary written (or no phases → "Empty milestone" stanza emitted)
  1 — config / arg error
  2 — write error
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
GOAL_BLOCK_RE = re.compile(r"^---\s*$", re.MULTILINE)
DECISION_RE = re.compile(r"\bD-(\d+)\b")
FOUNDATION_DECISION_RE = re.compile(r"\bF-(\d+)\b")
SEVERITY_RE = re.compile(r"\bseverity\s*[:=]\s*[\"']?(critical|high|medium|low|info)\b", re.I)
STATUS_OPEN_RE = re.compile(r"\bstatus\s*[:=]\s*[\"']?(open|in_progress|in-progress|new)\b", re.I)


def discover_phases_for_milestone(milestone: str, phase_range: str | None) -> list[Path]:
    phases_root = PLANNING_DIR / "phases"
    if not phases_root.is_dir():
        return []

    all_phases = sorted(
        (p for p in phases_root.iterdir() if p.is_dir() and PHASE_DIR_RE.match(p.name)),
        key=lambda p: int(PHASE_DIR_RE.match(p.name).group(1)),
    )
    if not all_phases:
        return []

    if phase_range:
        if "-" in phase_range:
            lo, hi = phase_range.split("-", 1)
            lo_i, hi_i = int(lo), int(hi)
        else:
            lo_i = hi_i = int(phase_range)
        return [
            p for p in all_phases
            if lo_i <= int(PHASE_DIR_RE.match(p.name).group(1)) <= hi_i
        ]

    roadmap = PLANNING_DIR / "ROADMAP.md"
    if roadmap.is_file():
        txt = roadmap.read_text(encoding="utf-8", errors="replace")
        m_id = milestone
        m_num = milestone.lstrip("Mm")
        patterns = [
            rf"##\s*{re.escape(m_id)}\b(.+?)(?=\n##\s|\Z)",
            rf"##\s*Milestone\s*{re.escape(m_id)}\b(.+?)(?=\n##\s|\Z)",
            rf"##\s*Milestone\s*{re.escape(m_num)}\b(.+?)(?=\n##\s|\Z)",
        ]
        section = None
        for pat in patterns:
            section = re.search(pat, txt, re.S)
            if section:
                break
        if section:
            phase_nums = set(re.findall(r"Phase\s*(\d+)", section.group(1)))
            return [
                p for p in all_phases
                if PHASE_DIR_RE.match(p.name).group(1) in phase_nums
            ]

    return all_phases


def phase_status(phase_dir: Path) -> dict:
    """Inspect phase artifacts to infer pipeline stage reached."""
    has = lambda name: (phase_dir / name).is_file()
    summaries = list(phase_dir.glob("SUMMARY*.md"))
    return {
        "specs": has("SPECS.md"),
        "scope": has("CONTEXT.md"),
        "blueprint": has("PLAN.md") and has("TEST-GOALS.md"),
        "build": has("SUMMARY.md") or len(summaries) > 0,
        "review": has("RUNTIME-MAP.json") or has("REVIEW.md"),
        "test": has("SANDBOX-TEST.md") or has("TEST-RESULTS.md"),
        "accepted": has("UAT.md"),
    }


def parse_test_goals(phase_dir: Path) -> dict:
    """Return {priority: {total, achieved}} from TEST-GOALS.md."""
    tg = phase_dir / "TEST-GOALS.md"
    if not tg.is_file():
        return {}
    text = tg.read_text(encoding="utf-8", errors="replace")
    counts: dict[str, dict[str, int]] = {}
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None  # type: ignore

    if yaml is not None:
        blocks: list[str] = []
        cur: list[str] = []
        in_block = False
        for line in text.splitlines():
            if line.strip() == "---":
                if in_block:
                    blocks.append("\n".join(cur))
                    cur = []
                    in_block = False
                else:
                    in_block = True
                continue
            if in_block:
                cur.append(line)
        for blob in blocks:
            try:
                data = yaml.safe_load(blob) or {}
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            gid = str(data.get("id", ""))
            if not gid.startswith("G-"):
                continue
            priority = str(data.get("priority", "important")).lower()
            status = str(data.get("status", "")).lower()
            counts.setdefault(priority, {"total": 0, "achieved": 0})
            counts[priority]["total"] += 1
            if status in {"achieved", "passed", "verified"}:
                counts[priority]["achieved"] += 1
    return counts


def count_decisions(phase_dir: Path) -> int:
    ctx = phase_dir / "CONTEXT.md"
    if not ctx.is_file():
        return 0
    text = ctx.read_text(encoding="utf-8", errors="replace")
    nums = {m.group(1) for m in DECISION_RE.finditer(text)}
    return len(nums)


def parse_security_register() -> dict:
    """Return {severity: count_open} from project SECURITY-REGISTER.md."""
    out = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    candidates = [
        PLANNING_DIR / "SECURITY-REGISTER.md",
        REPO_ROOT / ".planning" / "SECURITY-REGISTER.md",
    ]
    reg = next((c for c in candidates if c.is_file()), None)
    if reg is None:
        return out
    text = reg.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n###\s+", text)
    for blk in blocks:
        if not STATUS_OPEN_RE.search(blk):
            continue
        sev_match = SEVERITY_RE.search(blk)
        if sev_match:
            sev = sev_match.group(1).lower()
            if sev in out:
                out[sev] += 1
    return out


def count_override_debt() -> int:
    candidates = [
        PLANNING_DIR / "OVERRIDE-DEBT.md",
        REPO_ROOT / ".planning" / "OVERRIDE-DEBT.md",
    ]
    od = next((c for c in candidates if c.is_file()), None)
    if od is None:
        return 0
    text = od.read_text(encoding="utf-8", errors="replace")
    return len(re.findall(r"^- \[ \]", text, re.M))


def phase_first_commit_date(phase_num: str) -> str | None:
    """git log -1 --format=%aI -- pattern. Best effort."""
    try:
        import subprocess
        r = subprocess.run(
            ["git", "log", "--reverse", "--pretty=format:%aI",
             "--", f".vg/phases/{phase_num}*", f".planning/phases/{phase_num}*"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout.splitlines()[0]
    except Exception:
        pass
    return None


def phase_last_commit_date(phase_num: str) -> str | None:
    try:
        import subprocess
        r = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%aI",
             "--", f".vg/phases/{phase_num}*", f".planning/phases/{phase_num}*"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def aggregate(phases: list[Path]) -> dict:
    rows: list[dict] = []
    coverage: dict[str, dict[str, int]] = {}
    decisions_total = 0
    first_date = None
    last_date = None
    accepted_count = 0

    for phase_dir in phases:
        m = PHASE_DIR_RE.match(phase_dir.name)
        if not m:
            continue
        phase_num = m.group(1)

        status = phase_status(phase_dir)
        goals = parse_test_goals(phase_dir)
        decisions = count_decisions(phase_dir)
        decisions_total += decisions

        for priority, c in goals.items():
            bucket = coverage.setdefault(priority, {"total": 0, "achieved": 0})
            bucket["total"] += c["total"]
            bucket["achieved"] += c["achieved"]

        first = phase_first_commit_date(phase_num)
        last = phase_last_commit_date(phase_num)
        if first and (first_date is None or first < first_date):
            first_date = first
        if last and (last_date is None or last > last_date):
            last_date = last

        title = ""
        specs = phase_dir / "SPECS.md"
        if specs.is_file():
            txt = specs.read_text(encoding="utf-8", errors="replace")
            tm = re.search(r"^#\s+(.+)$", txt, re.M)
            if tm:
                title = tm.group(1).strip()

        if status["accepted"]:
            accepted_count += 1

        rows.append({
            "phase": phase_dir.name,
            "phase_num": phase_num,
            "title": title or "(no title)",
            "status": status,
            "goals_total": sum(c["total"] for c in goals.values()),
            "goals_achieved": sum(c["achieved"] for c in goals.values()),
            "decisions": decisions,
            "first_commit": first or "—",
            "last_commit": last or "—",
        })

    rows.sort(key=lambda r: int(r["phase_num"]))

    return {
        "phases": rows,
        "coverage": coverage,
        "decisions_total": decisions_total,
        "accepted_count": accepted_count,
        "first_date": first_date,
        "last_date": last_date,
        "security_open": parse_security_register(),
        "override_debt_open": count_override_debt(),
    }


def render_summary(milestone_id: str, agg: dict, summary_path: Path) -> str:
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = agg["phases"]
    total = len(rows)
    accepted = agg["accepted_count"]

    lines: list[str] = []
    lines.append(f"# Milestone {milestone_id} Summary")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append("")

    if not rows:
        lines.append("> **Empty milestone.** No phases resolved for this milestone via ROADMAP.md or `--phases` arg.")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Overview")
    lines.append("")
    lines.append(f"- **Phases:** {total} ({accepted} accepted, {total - accepted} not accepted)")
    if agg["first_date"]:
        lines.append(f"- **Started:** {agg['first_date']}")
    if agg["last_date"]:
        lines.append(f"- **Last commit:** {agg['last_date']}")
    lines.append(f"- **Decisions (D-XX namespace):** {agg['decisions_total']} total across phases")
    lines.append("")

    lines.append("## Phases")
    lines.append("")
    lines.append("| # | Title | Specs | Plan | Build | Review | Test | UAT | Goals | Decisions |")
    lines.append("|---|---|:-:|:-:|:-:|:-:|:-:|:-:|---|---|")
    for r in rows:
        s = r["status"]
        marks = lambda b: "✓" if b else "·"
        lines.append(
            f"| {r['phase_num']} | {r['title']} | {marks(s['specs'])} | "
            f"{marks(s['blueprint'])} | {marks(s['build'])} | {marks(s['review'])} | "
            f"{marks(s['test'])} | {marks(s['accepted'])} | "
            f"{r['goals_achieved']}/{r['goals_total']} | {r['decisions']} |"
        )
    lines.append("")

    lines.append("## Goal coverage (across milestone)")
    lines.append("")
    cov = agg["coverage"]
    if cov:
        lines.append("| Priority | Achieved | Total | % |")
        lines.append("|---|---|---|---|")
        for prio in ("critical", "important", "nice-to-have", "nice_to_have"):
            if prio in cov:
                c = cov[prio]
                pct = (100.0 * c["achieved"] / c["total"]) if c["total"] else 0
                lines.append(f"| {prio} | {c['achieved']} | {c['total']} | {pct:.0f}% |")
        for prio, c in cov.items():
            if prio in {"critical", "important", "nice-to-have", "nice_to_have"}:
                continue
            pct = (100.0 * c["achieved"] / c["total"]) if c["total"] else 0
            lines.append(f"| {prio} | {c['achieved']} | {c['total']} | {pct:.0f}% |")
    else:
        lines.append("_No TEST-GOALS.md files found across phases._")
    lines.append("")

    lines.append("## Security posture (at close time)")
    lines.append("")
    sec = agg["security_open"]
    if any(sec.values()):
        lines.append("| Severity | Open |")
        lines.append("|---|---|")
        for sev in ("critical", "high", "medium", "low", "info"):
            lines.append(f"| {sev} | {sec.get(sev, 0)} |")
        if sec.get("critical", 0) > 0:
            lines.append("")
            lines.append("> ⚠ **Critical threats OPEN at close.** `/vg:complete-milestone` will BLOCK unless `--allow-open-critical` flag with reason is passed.")
    else:
        lines.append("_No open threats in SECURITY-REGISTER.md._")
    lines.append("")

    lines.append("## Override debt (carried forward)")
    lines.append("")
    od = agg["override_debt_open"]
    if od > 0:
        lines.append(f"- **{od}** open OVERRIDE-DEBT entries carry into next milestone.")
        lines.append("- Resolve via `/vg:override-resolve <id>` before next milestone close.")
    else:
        lines.append("_No open OVERRIDE-DEBT entries._")
    lines.append("")

    lines.append("## Companion artifacts")
    lines.append("")
    milestone_dir = summary_path.parent
    companions = [
        ("Security audit", "security-audit-*.md"),
        ("Pen-test checklist (human)", "SECURITY-PENTEST-CHECKLIST.md"),
        ("Strix scan advisory (AI)", "STRIX-ADVISORY.md"),
        ("Strix scope payload", "strix-scope.json"),
    ]
    found = False
    for label, pattern in companions:
        for p in sorted(milestone_dir.glob(pattern)):
            lines.append(f"- **{label}**: `{p.relative_to(REPO_ROOT).as_posix()}`")
            found = True
    if not found:
        lines.append("_No companion artifacts present yet._ Run `/vg:security-audit-milestone --milestone={}` to generate.".format(milestone_id))
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"_Generated by `/vg:milestone-summary {milestone_id}`. Re-run to refresh after artifacts change._")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--milestone", required=True, help="Milestone ID (e.g. M1)")
    ap.add_argument("--phases", help="Explicit phase range (e.g. 3-7) — overrides ROADMAP resolution")
    ap.add_argument("--out", help="Output path (default: .vg/milestones/{M}/MILESTONE-SUMMARY.md)")
    ap.add_argument("--json", action="store_true", help="Print summary payload to stdout")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phases = discover_phases_for_milestone(args.milestone, args.phases)
    agg = aggregate(phases)

    milestone_dir = PLANNING_DIR / "milestones" / args.milestone
    summary_path = Path(args.out) if args.out else (milestone_dir / "MILESTONE-SUMMARY.md")
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    body = render_summary(args.milestone, agg, summary_path.resolve())
    summary_path.write_text(body, encoding="utf-8")

    if args.json:
        print(json.dumps({
            "summary_path": str(summary_path.resolve().relative_to(REPO_ROOT).as_posix()),
            "milestone": args.milestone,
            "phase_count": len(agg["phases"]),
            "accepted_count": agg["accepted_count"],
            "decisions_total": agg["decisions_total"],
            "security_open": agg["security_open"],
            "override_debt_open": agg["override_debt_open"],
        }, indent=2))
    elif not args.quiet:
        print(f"✓ Milestone summary written: {summary_path.resolve().relative_to(REPO_ROOT).as_posix()}")
        print(f"  Phases: {len(agg['phases'])} ({agg['accepted_count']} accepted)")
        print(f"  Decisions: {agg['decisions_total']}")
        if agg["security_open"].get("critical", 0) > 0:
            print(f"  ⚠ {agg['security_open']['critical']} critical threats OPEN")

    return 0


if __name__ == "__main__":
    sys.exit(main())
