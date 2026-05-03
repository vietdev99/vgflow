"""Tester-pro artifacts (RFC v9 D17–D23).

Five artifacts the workflow now produces / consumes for tester-grade
discipline:

D17 — TEST-STRATEGY.md (per phase) — declares scope, surface taxonomy,
  test types, exit criteria. Produced at /vg:scope, validated at review.

D18 — test_type classification per goal — {smoke|happy|edge|negative|
  security|perf|integration}. Validators check coverage across types.

D21 — DEFECT-LOG.md — every BLOCK / unexpected behavior recorded with
  severity, repro steps, root cause, fix ref. Cumulative across runs.

D22 — TEST-SUMMARY-REPORT.md — final report combining stats:
  - tests run / passed / failed / blocked
  - coverage by goal / surface / test_type
  - defects opened / closed / open
  - effort estimate vs actual

D23 — RTM (Requirements Traceability Matrix) bi-directional:
  - Forward: requirement → goals → test cases → defects → fix commits
  - Reverse: any test/defect/commit → owning requirement
  Closes the feedback loop the AI most often misses.

This module owns the data structures + serialization + parsing. Skill
markdown invokes via thin Python wrappers. Validators check that each
artifact exists when the phase profile demands it.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Test-type taxonomy (D18) — keep small + non-overlapping.
TEST_TYPES = ("smoke", "happy", "edge", "negative", "security", "perf", "integration")


# ─── D18 test_type ─────────────────────────────────────────────────


def parse_test_type_from_goal_body(body: str) -> str | None:
    """Extract `**Test type:** <one>` directive from TEST-GOALS.md goal body.

    Defaults to None (validator surfaces missing as warn).
    """
    m = re.search(r"\*\*Test\s*type:\*\*\s*([A-Za-z]+)", body, re.IGNORECASE)
    if not m:
        return None
    t = m.group(1).strip().lower()
    return t if t in TEST_TYPES else None


def coverage_by_test_type(
    goals: list[dict],
    *,
    required_types: Iterable[str] = ("smoke", "happy", "edge"),
) -> dict[str, int]:
    """Aggregate goal counts per test_type. Caller asserts required floors."""
    counts: dict[str, int] = {t: 0 for t in TEST_TYPES}
    for g in goals:
        t = g.get("test_type")
        if t in TEST_TYPES:
            counts[t] += 1
    return counts


def assert_required_coverage(
    counts: dict[str, int],
    *,
    requirements: dict[str, int],
) -> list[str]:
    """Returns list of missing-coverage messages."""
    missing: list[str] = []
    for t, floor in requirements.items():
        if counts.get(t, 0) < floor:
            missing.append(f"test_type='{t}' has {counts.get(t, 0)} goals, requires ≥{floor}")
    return missing


# ─── D21 DEFECT-LOG ────────────────────────────────────────────────


@dataclass
class Defect:
    id: str
    title: str
    severity: str  # critical | high | medium | low
    discovered_at: str
    discovered_in: str  # which step (review/test/accept) found it
    repro_steps: list[str] = field(default_factory=list)
    root_cause: str | None = None
    fix_ref: str | None = None  # commit hash | PR number | "wontfix"
    closed_at: str | None = None
    related_goals: list[str] = field(default_factory=list)
    notes: str = ""


def new_defect_id(existing: list[Defect]) -> str:
    """D-NNN sequential per phase."""
    used = []
    for d in existing:
        m = re.match(r"D-(\d+)$", d.id)
        if m:
            used.append(int(m.group(1)))
    n = (max(used) + 1) if used else 1
    return f"D-{n:03d}"


def render_defect_log(defects: list[Defect]) -> str:
    lines = ["# DEFECT LOG", "",
             "| ID | Severity | Title | Discovered in | Closed | Goals |",
             "|----|----------|-------|----------------|--------|-------|"]
    for d in defects:
        closed = d.closed_at or "open"
        goals = ", ".join(d.related_goals) or "—"
        lines.append(
            f"| {d.id} | {d.severity} | {d.title} | {d.discovered_in} | "
            f"{closed} | {goals} |"
        )
    lines.append("")
    for d in defects:
        lines.append(f"## {d.id} — {d.title}")
        lines.append(f"- Severity: {d.severity}")
        lines.append(f"- Discovered: {d.discovered_at} (in {d.discovered_in})")
        if d.repro_steps:
            lines.append("- Repro:")
            for step in d.repro_steps:
                lines.append(f"  1. {step}")
        if d.root_cause:
            lines.append(f"- Root cause: {d.root_cause}")
        if d.fix_ref:
            lines.append(f"- Fix: {d.fix_ref}")
        if d.related_goals:
            lines.append(f"- Goals: {', '.join(d.related_goals)}")
        if d.notes:
            lines.append(f"- Notes: {d.notes}")
        lines.append("")
    return "\n".join(lines)


# ─── D22 TEST-SUMMARY-REPORT ───────────────────────────────────────


@dataclass
class TestSummary:
    __test__ = False  # not a pytest test class
    phase: str
    generated_at: str
    goals_total: int = 0
    goals_passed: int = 0
    goals_failed: int = 0
    goals_blocked: int = 0
    coverage_by_type: dict[str, int] = field(default_factory=dict)
    defects_opened: int = 0
    defects_closed: int = 0
    defects_open: int = 0
    notes: str = ""


def render_summary_report(summary: TestSummary) -> str:
    lines = [
        f"# TEST SUMMARY REPORT — phase {summary.phase}",
        f"Generated: {summary.generated_at}",
        "",
        "## Goals",
        f"- Total: {summary.goals_total}",
        f"- Passed: {summary.goals_passed}",
        f"- Failed: {summary.goals_failed}",
        f"- Blocked: {summary.goals_blocked}",
        "",
        "## Coverage by test_type",
    ]
    for t, n in sorted(summary.coverage_by_type.items()):
        lines.append(f"- {t}: {n}")
    lines += [
        "",
        "## Defects",
        f"- Opened (this run): {summary.defects_opened}",
        f"- Closed (this run): {summary.defects_closed}",
        f"- Still open: {summary.defects_open}",
    ]
    if summary.notes:
        lines += ["", "## Notes", summary.notes]
    return "\n".join(lines)


# ─── D23 RTM (bi-directional) ─────────────────────────────────────


@dataclass
class TraceabilityRow:
    requirement_id: str
    goal_ids: list[str] = field(default_factory=list)
    test_case_ids: list[str] = field(default_factory=list)
    defect_ids: list[str] = field(default_factory=list)
    fix_commits: list[str] = field(default_factory=list)


def reverse_index(rows: list[TraceabilityRow]) -> dict[str, list[str]]:
    """Build reverse map: any leaf id → list of requirements covering it.

    Lets caller answer "what requirements does commit XYZ touch?" in O(1).
    """
    rev: dict[str, list[str]] = {}
    for r in rows:
        for leaf in r.goal_ids + r.test_case_ids + r.defect_ids + r.fix_commits:
            rev.setdefault(leaf, []).append(r.requirement_id)
    return rev


def detect_orphan_goals(
    rows: list[TraceabilityRow],
    *,
    declared_goals: set[str],
) -> list[str]:
    """Return goal IDs in `declared_goals` not covered by any RTM row."""
    covered: set[str] = set()
    for r in rows:
        covered.update(r.goal_ids)
    return sorted(declared_goals - covered)


def detect_orphan_requirements(
    rows: list[TraceabilityRow],
    *,
    declared_requirements: set[str],
) -> list[str]:
    """Return requirement IDs declared but absent from RTM rows."""
    rtm_reqs = {r.requirement_id for r in rows}
    return sorted(declared_requirements - rtm_reqs)


def render_rtm(rows: list[TraceabilityRow]) -> str:
    lines = ["# RTM (Requirements Traceability Matrix)", "",
             "## Forward",
             "| Requirement | Goals | Test cases | Defects | Fix commits |",
             "|-------------|-------|------------|---------|-------------|"]
    for r in rows:
        lines.append(
            f"| {r.requirement_id} | "
            f"{', '.join(r.goal_ids) or '—'} | "
            f"{', '.join(r.test_case_ids) or '—'} | "
            f"{', '.join(r.defect_ids) or '—'} | "
            f"{', '.join(r.fix_commits) or '—'} |"
        )
    return "\n".join(lines)
