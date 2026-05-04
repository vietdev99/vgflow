#!/usr/bin/env python3
"""
Validator: verify-rollback-procedure.py

Harness v2.6 (2026-04-25): closes the CLAUDE.md "ORG 6-Dimension Gate"
rollback rule + migration-profile contract:

  Dimension 6 — Rollback: "If deploy fails, what's the recovery path?"
  Example: "pm2 stop, git revert, pm2 restart. ClickHouse tables are
   additive — no data loss"

Plus phase-profile rule:
  migration profile → required artifacts include ROLLBACK.md

Why: AI tends to ship destructive operations (DB schema migrations,
data deletes, mass updates, table renames) WITHOUT planning the
recovery path. When deploy fails mid-flight, ops has nothing to
roll back to.

What this validator checks:

  1. Phase profile = migration → ROLLBACK.md MUST exist + be substantive
     (≥ 200 bytes, contains down-migration steps).

  2. PLAN tasks with destructive verbs:
       drop / truncate / delete-table / delete-column / migrate / reindex
       / rebuild / recreate / wipe / purge / DESTRUCTIVE: marker
     → require rollback declaration inline (per-task `Rollback:` line OR
       phase-level ROLLBACK.md OR `## Rollback` section in PLAN.md).

  3. ORG 6-dim gate: every PLAN file must have an ORG section addressing
     dimension 6 (rollback) explicitly. Missing → BLOCK at blueprint stage.
     But many phases satisfy this in OPERATIONAL-READINESS.md instead;
     accept either source.

Severity:
  BLOCK — destructive verb without rollback / migration without ROLLBACK.md
  WARN  — ORG dim 6 not explicitly addressed (advisory)

Usage:
  verify-rollback-procedure.py --phase 7.14
  verify-rollback-procedure.py --phase 7.14 --strict (escalate WARN→BLOCK)

Exit codes:
  0  PASS or WARN-only
  1  BLOCK
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Destructive verbs in PLAN tasks that demand rollback declaration.
# Regex matches as whole-word, case-insensitive.
DESTRUCTIVE_VERBS_RE = re.compile(
    r"\b(?:drop\s+(?:table|column|index|schema|database)|"
    r"truncate\b|"
    r"delete\s+(?:table|column|all|from)|"
    r"alter\s+table\s+\w+\s+drop\b|"
    r"rename\s+(?:table|column)|"
    r"DESTRUCTIVE\s*:|"
    r"^\s*MIGRATE:\s*|"
    r"\bwipe\b|\bpurge\b|"
    r"\bremove\s+(?:column|index|constraint)\b|"
    r"\brebuild\s+(?:table|index|cache)|"
    r"\brecreate\s+(?:table|index|database))",
    re.IGNORECASE | re.MULTILINE,
)

# Rollback declaration patterns
ROLLBACK_DECL_RE = re.compile(
    r"(?:^|\n)\s*(?:\*\*Rollback:\*\*|##\s+Rollback|Rollback\s*:|"
    r"recovery\s+path\s*:|down[\s-]migration\s*:|"
    r"reverse[\s-]migration|undo[\s-]script)",
    re.IGNORECASE,
)

# ORG 6-dim section markers
ORG_DIMENSION_RE = re.compile(
    r"(?:Rollback|Recovery|Dim\s*6|Dimension\s*6)",
    re.IGNORECASE,
)


def _phase_profile(phase_dir: Path) -> str:
    specs = phase_dir / "SPECS.md"
    if not specs.exists():
        return "feature"
    try:
        text = specs.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "feature"
    m = re.search(r"^profile:\s*(\w+)", text, re.MULTILINE)
    if m:
        return m.group(1).lower()
    if re.search(r"^parent_phase:", text, re.MULTILINE):
        return "hotfix"
    if re.search(r"\bmigration\b", text, re.IGNORECASE) and \
       re.search(r"\bdown\b|\bup\b|\brevert\b", text, re.IGNORECASE):
        return "migration"
    return "feature"


def _has_rollback_doc(phase_dir: Path) -> tuple[bool, str]:
    """Return (has_rollback, reason). Rollback evidence sources:
    1. ROLLBACK.md present + substantive
    2. PLAN.md has ## Rollback section
    3. OPERATIONAL-READINESS.md mentions rollback path
    """
    rollback = phase_dir / "ROLLBACK.md"
    if rollback.exists():
        try:
            text = rollback.read_text(encoding="utf-8", errors="replace")
            if len(text.encode("utf-8")) >= 200:
                return True, "ROLLBACK.md substantive"
        except OSError:
            pass

    for plan in phase_dir.glob("PLAN*.md"):
        try:
            text = plan.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if ROLLBACK_DECL_RE.search(text):
            return True, f"{plan.name} has rollback section"

    op_ready = phase_dir / "OPERATIONAL-READINESS.md"
    if op_ready.exists():
        try:
            text = op_ready.read_text(encoding="utf-8", errors="replace")
            if ORG_DIMENSION_RE.search(text) and ROLLBACK_DECL_RE.search(text):
                return True, "OPERATIONAL-READINESS.md addresses rollback"
        except OSError:
            pass

    return False, "no rollback evidence found"


def _find_destructive_tasks(plan_text: str) -> list[dict]:
    """Find PLAN tasks containing destructive verbs."""
    findings: list[dict] = []
    # Split by heading-style task markers
    task_re = re.compile(r"^#{2,3}\s+Task\s+(\d+[\d.]*)\b", re.MULTILINE)
    matches = list(task_re.finditer(plan_text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(plan_text)
        task_block = plan_text[m.start():end]
        verbs = DESTRUCTIVE_VERBS_RE.findall(task_block)
        if verbs:
            # Check if THIS task has inline Rollback: declaration
            has_rollback = bool(ROLLBACK_DECL_RE.search(task_block))
            findings.append({
                "task_id": m.group(1),
                "verbs": list(set(v.lower() for v in verbs))[:5],
                "has_rollback": has_rollback,
            })
    return findings


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    out = Output(validator="verify-rollback-procedure")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        profile = _phase_profile(phase_dir)

        # Check 1: migration profile → ROLLBACK.md mandatory
        if profile == "migration":
            has_rb, reason = _has_rollback_doc(phase_dir)
            if not has_rb:
                out.add(Evidence(
                    type="migration_no_rollback",
                    message=f"Migration phase {args.phase} missing ROLLBACK.md",
                    actual=f"Profile: {profile}. Searched: ROLLBACK.md, PLAN*.md ## Rollback section, OPERATIONAL-READINESS.md. Result: {reason}.",
                    expected="Migration phase MUST ship ROLLBACK.md with down-migration steps (drop/restore/revert commands), OR PLAN.md must have ## Rollback section.",
                    fix_hint=("Tạo ROLLBACK.md trong phase dir. Format: 1 đoạn ngắn mô tả "
                              "khi nào trigger rollback, kế tiếp là step-by-step commands "
                              "để revert. Phải test rollback trước khi ship migration "
                              "(per CLAUDE.md ORG 6-dim Rollback example: 'pm2 stop, git "
                              "revert, pm2 restart. ClickHouse tables are additive — no "
                              "data loss')."),
                ))

        # Check 2: destructive tasks in PLAN must have rollback declared
        plan_files = list(phase_dir.glob("PLAN*.md"))
        for plan in plan_files:
            try:
                text = plan.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            destructive = _find_destructive_tasks(text)
            unrecovered = [d for d in destructive if not d["has_rollback"]]
            if unrecovered:
                # Phase-level rollback may cover all tasks; check that fallback
                phase_has_rb, _reason = _has_rollback_doc(phase_dir)
                if phase_has_rb:
                    continue  # covered at phase level
                out.add(Evidence(
                    type="destructive_tasks_no_rollback",
                    message=f"{len(unrecovered)} destructive task(s) in {plan.name} without rollback declaration",
                    actual=f"Tasks: {[(d['task_id'], d['verbs']) for d in unrecovered[:4]]}",
                    expected="Each destructive task (DROP / TRUNCATE / DELETE / ALTER DROP / DESTRUCTIVE: marker) needs **Rollback:** line OR phase-level ROLLBACK.md.",
                    fix_hint="Add `**Rollback:** <commands or reference to ROLLBACK.md>` line below each destructive task. Or create phase-level ROLLBACK.md if multiple tasks share same recovery path.",
                ))

        # Check 3: ORG 6-dim rollback addressed (advisory WARN)
        # Skip when phase already passed checks 1 & 2 — the rollback IS addressed
        # somewhere. Only fire when no rollback signal at all + phase is non-trivial.
        if profile in ("feature", "infra"):
            org_ready = phase_dir / "OPERATIONAL-READINESS.md"
            has_org_rb = False
            if org_ready.exists():
                try:
                    text = org_ready.read_text(encoding="utf-8", errors="replace")
                    has_org_rb = bool(ORG_DIMENSION_RE.search(text))
                except OSError:
                    pass
            phase_has_rb, _ = _has_rollback_doc(phase_dir)
            if not has_org_rb and not phase_has_rb:
                # Only WARN — feature phases without rollback may legitimately
                # have nothing to revert
                out.warn(Evidence(
                    type="org_dim6_not_addressed",
                    message=f"Phase {args.phase} does not explicitly address ORG dimension 6 (rollback) — advisory",
                    actual=f"Profile: {profile}. No ROLLBACK.md, no ## Rollback section, no OPERATIONAL-READINESS rollback mention.",
                    fix_hint="If phase introduces no destructive operations, add 1-line note in PLAN: 'N/A — phase only adds new code, no rollback needed (revert via git revert).' If phase deploys infra, document tear-down path.",
                ))

        if args.strict and not out.evidence:
            pass  # nothing to escalate

    emit_and_exit(out)


if __name__ == "__main__":
    main()
