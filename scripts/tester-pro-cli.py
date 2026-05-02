#!/usr/bin/env python3
"""CLI wrapper for tester_pro module (RFC v9 D17–D23 artifacts).

Exposes subcommands so skill .md files can call tester_pro with a single
bash line instead of inlining Python heredocs. Each subcommand is idempotent
and writes one artifact under the phase dir.

Subcommands:
  strategy generate --phase X            → TEST-STRATEGY.md (D17)
  validate-test-types --phase X          → D18 validator at blueprint
  defect new --phase X --title ... --severity ... --found-in review
                                         → append D-NNN to DEFECT-LOG.md (D21)
  defect close --phase X --id D-NNN --fix-ref <sha>
                                         → mark closed
  defect render --phase X                → re-render DEFECT-LOG.md from store
  summary render --phase X               → TEST-SUMMARY-REPORT.md (D22)
  rtm render --phase X                   → RTM.md (D23) + orphan check

Storage convention:
  {phase_dir}/.tester-pro/defects.json   (append-only Defect records)
  {phase_dir}/DEFECT-LOG.md              (rendered, idempotent overwrite)
  {phase_dir}/TEST-STRATEGY.md           (generated at scope)
  {phase_dir}/TEST-SUMMARY-REPORT.md     (rendered at test end)
  {phase_dir}/RTM.md                     (rendered at test end + accept)

Exit codes:
  0 — success
  1 — BLOCK (validation failure)
  2 — config / setup error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from runtime.tester_pro import (  # noqa: E402
    TEST_TYPES,
    Defect,
    TestSummary,
    TraceabilityRow,
    assert_required_coverage,
    coverage_by_test_type,
    detect_orphan_goals,
    detect_orphan_requirements,
    new_defect_id,
    parse_test_type_from_goal_body,
    render_defect_log,
    render_rtm,
    render_summary_report,
    reverse_index,
)


# ─── Phase resolution ──────────────────────────────────────────────


def _zero_pad(phase: str) -> str:
    if "." in phase and not phase.split(".")[0].startswith("0"):
        head, _, tail = phase.partition(".")
        return f"{head.zfill(2)}.{tail}"
    return phase


def find_phase_dir(phase: str) -> Path | None:
    repo = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    phases_dir = repo / ".vg" / "phases"
    if not phases_dir.exists():
        return None
    for prefix in (phase, _zero_pad(phase)):
        matches = sorted(phases_dir.glob(f"{prefix}-*"))
        if matches:
            return matches[0]
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─── Defect store (D21) ────────────────────────────────────────────


def _defect_store_path(phase_dir: Path) -> Path:
    d = phase_dir / ".tester-pro"
    d.mkdir(exist_ok=True)
    return d / "defects.json"


def load_defects(phase_dir: Path) -> list[Defect]:
    p = _defect_store_path(phase_dir)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [Defect(**d) for d in data]


def save_defects(phase_dir: Path, defects: list[Defect]) -> None:
    p = _defect_store_path(phase_dir)
    p.write_text(
        json.dumps([asdict(d) for d in defects], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_defect_log_md(phase_dir: Path, defects: list[Defect]) -> Path:
    path = phase_dir / "DEFECT-LOG.md"
    path.write_text(render_defect_log(defects) + "\n", encoding="utf-8")
    return path


# ─── TEST-STRATEGY (D17) ───────────────────────────────────────────


def _read_first_section(path: Path, heading_re: str) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"(?m)^{heading_re}.*?\n(.+?)(?=^#)", text, re.DOTALL)
    return (m.group(1).strip() if m else "")[:600]


def generate_test_strategy(phase_dir: Path, phase: str) -> str:
    """Compose TEST-STRATEGY.md from SPECS + CONTEXT.

    Heuristic: reads SPECS scope/risk hints, derives default test types
    in scope, sets coverage targets per priority. User edits the file
    after — it's a starting draft, not authoritative.
    """
    specs = phase_dir / "SPECS.md"
    context = phase_dir / "CONTEXT.md"

    in_scope = _read_first_section(specs, r"##\s+(?:In\s+scope|Scope)")
    risk = _read_first_section(specs, r"##\s+(?:Risk|Risks)")
    domain_keywords = re.findall(
        r"\b(payment|wallet|billing|auth|admin|security|order|invoice)\b",
        (specs.read_text(encoding="utf-8") if specs.exists() else "").lower(),
    )
    domain_set = ", ".join(sorted(set(domain_keywords))) or "general"

    test_types_in_scope = ["functional", "api_contract", "ui_ux", "data_integrity"]
    if any(k in domain_keywords for k in ("payment", "wallet", "auth", "admin")):
        test_types_in_scope.append("security")
    out_of_scope = ["performance (deferred to /vg:roam)", "exploratory (manual)"]

    body = f"""# Test Strategy — Phase {phase}

> Generated by tester-pro-cli at {_now_iso()}. Edit to refine; re-run only
> overwrites if you delete the file. This is the D17 contract that
> /vg:blueprint validates against.

## Domain
{domain_set}

## Test types in scope
{chr(10).join(f"- {t}" for t in test_types_in_scope)}

### Out of scope
{chr(10).join(f"- {t}" for t in out_of_scope)}

## Risk assessment
{risk or "_TODO: capture domain-specific risks (data loss, compliance, security boundary)_"}

## Coverage targets (by priority)
- critical: 100% READY required (no PARTIAL/MANUAL accepted)
- important: ≥80% READY
- nice-to-have: ≥50% READY

## Coverage targets (by test_type)
- smoke: ≥1 per phase (auth + first happy path)
- happy: ≥1 per mutation goal
- edge: ≥1 per mutation goal (boundary values)
- negative: ≥1 per mutation goal (rejection path)
- security: ≥1 per role boundary (if domain includes auth/admin/payment)

## Exit criteria
- 0 BLOCKED + 0 UNREACHABLE (after triage)
- ≤3 DEFERRED (each with depends_on_phase declared)
- 100% goals have test_type assigned (D18 gate)
- All defects severity≥major closed or deferred with justification (D21)
- TEST-SUMMARY-REPORT.md generated (D22)
- RTM has 0 orphan goals + 0 orphan requirements (D23)

## Defect severity classification
- **critical**: production data loss, security breach, business logic violation (revenue/audit impact)
- **major**: feature broken with no workaround, api_contract drift, integration fail
- **minor**: cosmetic, ui_render bug with workaround, accessibility miss
- **trivial**: typo, polish, log noise

## In-scope reference (from SPECS)
{in_scope or "_(SPECS.md has no Scope section — populate before /vg:blueprint)_"}
"""
    path = phase_dir / "TEST-STRATEGY.md"
    path.write_text(body, encoding="utf-8")
    return str(path)


# ─── TEST-GOALS parsing (shared) ───────────────────────────────────


def parse_goals_from_test_goals(phase_dir: Path) -> list[dict]:
    p = phase_dir / "TEST-GOALS.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    goals: list[dict] = []
    parts = re.split(
        r"(?m)^(#{2,4}\s+(?:Goal\s+)?(G-[\w.-]+).*?)$",
        text,
    )
    for i in range(1, len(parts), 3):
        heading = parts[i]
        gid = parts[i + 1]
        body = parts[i + 2] if i + 2 < len(parts) else ""
        priority_m = re.search(r"\*\*Priority:\*\*\s*(\w+)", body)
        surface_m = re.search(r"\*\*Surface:\*\*\s*(\w+)", body)
        title_m = re.match(
            r"#{2,4}\s+(?:Goal\s+)?G-[\w.-]+(?:[:\s—–-]+)\s*(.+)$",
            heading,
        )
        goals.append({
            "id": gid,
            "title": (title_m.group(1).strip() if title_m else "").strip(),
            "priority": (priority_m.group(1).lower() if priority_m else "important"),
            "surface": (surface_m.group(1).lower() if surface_m else "ui"),
            "test_type": parse_test_type_from_goal_body(body),
            "body": body,
        })
    return goals


# ─── Subcommand handlers ───────────────────────────────────────────


def cmd_strategy_generate(args) -> int:
    phase_dir = find_phase_dir(args.phase)
    if not phase_dir:
        print(json.dumps({"error": f"phase {args.phase} not found"}), file=sys.stderr)
        return 2
    target = phase_dir / "TEST-STRATEGY.md"
    if target.exists() and not args.force:
        print(json.dumps({
            "verdict": "SKIP",
            "reason": "TEST-STRATEGY.md exists; pass --force to overwrite",
            "path": str(target),
        }))
        return 0
    path = generate_test_strategy(phase_dir, args.phase)
    print(json.dumps({"verdict": "WROTE", "path": path}))
    return 0


def cmd_validate_test_types(args) -> int:
    """D18 — every mutation goal must declare **Test type:** field.

    Severity:
      block — default for new phases (post-2026-05-01)
      warn  — pre-2026-05-01 phases (grandfathered)
    """
    phase_dir = find_phase_dir(args.phase)
    if not phase_dir:
        print(json.dumps({"error": f"phase {args.phase} not found"}), file=sys.stderr)
        return 2

    goals = parse_goals_from_test_goals(phase_dir)
    if not goals:
        print(json.dumps({
            "verdict": "PASS", "evidence": "no TEST-GOALS.md or no goals",
        }))
        return 0

    # Mutation goals = surface ∈ backend OR body has Mutation evidence.
    mutation_goals = [
        g for g in goals
        if g["surface"] in ("api", "data", "integration", "time-driven")
        or "**Mutation evidence:**" in g["body"]
    ]
    missing = [g["id"] for g in mutation_goals if not g["test_type"]]

    counts = coverage_by_test_type([
        {**g, "test_type": g["test_type"]} for g in goals
    ])
    coverage_msgs = assert_required_coverage(
        counts,
        requirements={"smoke": 1, "happy": 1, "edge": 1},
    )

    blocking = bool(missing) or bool(coverage_msgs)
    severity = (args.severity or "block").lower()
    verdict = ("BLOCK" if blocking and severity == "block"
               else "WARN" if blocking else "PASS")

    out = {
        "verdict": verdict,
        "missing_test_type": missing,
        "coverage_by_type": counts,
        "coverage_gaps": coverage_msgs,
        "mutation_goal_count": len(mutation_goals),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if verdict == "BLOCK" else 0


def cmd_defect_new(args) -> int:
    phase_dir = find_phase_dir(args.phase)
    if not phase_dir:
        print(json.dumps({"error": f"phase {args.phase} not found"}), file=sys.stderr)
        return 2
    defects = load_defects(phase_dir)
    new_id = new_defect_id(defects)
    severity = args.severity.lower()
    if severity not in ("critical", "major", "minor", "trivial"):
        print(json.dumps({"error": f"invalid severity '{args.severity}'"}),
              file=sys.stderr)
        return 2
    d = Defect(
        id=new_id,
        title=args.title,
        severity=severity,
        discovered_at=_now_iso(),
        discovered_in=args.found_in,
        repro_steps=(args.repro or []),
        related_goals=(args.goals or []),
        notes=(args.notes or ""),
        root_cause=args.root_cause,
    )
    defects.append(d)
    save_defects(phase_dir, defects)
    write_defect_log_md(phase_dir, defects)
    print(json.dumps({"verdict": "OPENED", "id": new_id, "severity": severity}))
    return 0


def cmd_defect_close(args) -> int:
    phase_dir = find_phase_dir(args.phase)
    if not phase_dir:
        print(json.dumps({"error": f"phase {args.phase} not found"}), file=sys.stderr)
        return 2
    defects = load_defects(phase_dir)
    target = next((d for d in defects if d.id == args.id), None)
    if not target:
        print(json.dumps({"error": f"defect {args.id} not found"}), file=sys.stderr)
        return 2
    target.fix_ref = args.fix_ref
    target.closed_at = _now_iso()
    if args.root_cause:
        target.root_cause = args.root_cause
    save_defects(phase_dir, defects)
    write_defect_log_md(phase_dir, defects)
    print(json.dumps({"verdict": "CLOSED", "id": args.id, "fix_ref": args.fix_ref}))
    return 0


def cmd_defect_render(args) -> int:
    phase_dir = find_phase_dir(args.phase)
    if not phase_dir:
        print(json.dumps({"error": f"phase {args.phase} not found"}), file=sys.stderr)
        return 2
    defects = load_defects(phase_dir)
    path = write_defect_log_md(phase_dir, defects)
    print(json.dumps({
        "verdict": "WROTE", "path": str(path),
        "total": len(defects),
        "open": sum(1 for d in defects if not d.closed_at),
    }))
    return 0


def cmd_summary_render(args) -> int:
    """D22 — render TEST-SUMMARY-REPORT.md aggregating goals + defects."""
    phase_dir = find_phase_dir(args.phase)
    if not phase_dir:
        print(json.dumps({"error": f"phase {args.phase} not found"}), file=sys.stderr)
        return 2

    goals = parse_goals_from_test_goals(phase_dir)
    defects = load_defects(phase_dir)

    # Read GOAL-COVERAGE-MATRIX for pass/fail/block counts (best-effort)
    matrix = phase_dir / "GOAL-COVERAGE-MATRIX.md"
    passed = failed = blocked = 0
    if matrix.exists():
        text = matrix.read_text(encoding="utf-8")
        passed = len(re.findall(r"\bREADY\b", text))
        failed = len(re.findall(r"\bBLOCKED\b", text))
        blocked = len(re.findall(r"\bUNREACHABLE\b", text))

    counts = coverage_by_test_type(goals)
    summary = TestSummary(
        phase=args.phase,
        generated_at=_now_iso(),
        goals_total=len(goals),
        goals_passed=passed,
        goals_failed=failed,
        goals_blocked=blocked,
        coverage_by_type=counts,
        defects_opened=len(defects),
        defects_closed=sum(1 for d in defects if d.closed_at),
        defects_open=sum(1 for d in defects if not d.closed_at),
    )
    path = phase_dir / "TEST-SUMMARY-REPORT.md"
    path.write_text(render_summary_report(summary) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": "WROTE", "path": str(path),
                      "goals_total": summary.goals_total,
                      "defects_open": summary.defects_open}))
    return 0


def cmd_rtm_render(args) -> int:
    """D23 — render RTM.md and detect orphan goals/requirements."""
    phase_dir = find_phase_dir(args.phase)
    if not phase_dir:
        print(json.dumps({"error": f"phase {args.phase} not found"}), file=sys.stderr)
        return 2

    # Build TraceabilityRow per requirement (decision-id) by scanning SPECS
    # + CONTEXT for D-NN/P{N}.D-NN, mapping to goals via TEST-GOALS body.
    goals = parse_goals_from_test_goals(phase_dir)
    defects = load_defects(phase_dir)

    rows: dict[str, TraceabilityRow] = {}

    # 1. Goals → requirements via decision refs in goal body
    for g in goals:
        decision_refs = re.findall(
            r"\b(?:P\d+(?:\.\d+)?\.)?D-\d+\b", g["body"],
        )
        for req in decision_refs:
            row = rows.setdefault(req, TraceabilityRow(requirement_id=req))
            if g["id"] not in row.goal_ids:
                row.goal_ids.append(g["id"])

    # 2. Defects → requirements via related_goals → decisions
    for d in defects:
        for gid in d.related_goals:
            g = next((x for x in goals if x["id"] == gid), None)
            if not g:
                continue
            for req in re.findall(r"\b(?:P\d+(?:\.\d+)?\.)?D-\d+\b", g["body"]):
                row = rows.setdefault(req, TraceabilityRow(requirement_id=req))
                if d.id not in row.defect_ids:
                    row.defect_ids.append(d.id)
                if d.fix_ref and d.fix_ref not in row.fix_commits:
                    row.fix_commits.append(d.fix_ref)

    declared_goals = {g["id"] for g in goals}
    declared_requirements: set[str] = set()
    for f in (phase_dir / "SPECS.md", phase_dir / "CONTEXT.md"):
        if f.exists():
            declared_requirements.update(
                re.findall(r"\b(?:P\d+(?:\.\d+)?\.)?D-\d+\b", f.read_text(encoding="utf-8")),
            )

    rows_list = list(rows.values())
    orphan_goals = detect_orphan_goals(rows_list, declared_goals=declared_goals)
    orphan_reqs = detect_orphan_requirements(
        rows_list, declared_requirements=declared_requirements,
    )

    out_md = render_rtm(rows_list)
    if orphan_goals:
        out_md += "\n## Orphan goals (not traced to any requirement)\n\n"
        out_md += "\n".join(f"- {g}" for g in sorted(orphan_goals))
        out_md += "\n"
    if orphan_reqs:
        out_md += "\n## Orphan requirements (declared but no covering goal)\n\n"
        out_md += "\n".join(f"- {r}" for r in sorted(orphan_reqs))
        out_md += "\n"

    path = phase_dir / "RTM.md"
    path.write_text(out_md + "\n", encoding="utf-8")

    blocking = bool(orphan_goals) or bool(orphan_reqs)
    severity = (args.severity or "block").lower()
    verdict = "BLOCK" if blocking and severity == "block" else (
        "WARN" if blocking else "PASS"
    )
    print(json.dumps({
        "verdict": verdict,
        "path": str(path),
        "rows": len(rows_list),
        "orphan_goals": sorted(orphan_goals),
        "orphan_requirements": sorted(orphan_reqs),
    }, ensure_ascii=False, indent=2))
    return 1 if verdict == "BLOCK" else 0


# ─── Argparse plumbing ─────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="tester-pro-cli",
        description="RFC v9 D17–D23 artifacts CLI (tester pro discipline).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # strategy generate
    p_strat = sub.add_parser("strategy")
    s_strat = p_strat.add_subparsers(dest="action", required=True)
    p_sg = s_strat.add_parser("generate")
    p_sg.add_argument("--phase", required=True)
    p_sg.add_argument("--force", action="store_true")
    p_sg.set_defaults(func=cmd_strategy_generate)

    # validate-test-types
    p_vt = sub.add_parser("validate-test-types")
    p_vt.add_argument("--phase", required=True)
    p_vt.add_argument("--severity", choices=["block", "warn"], default="block")
    p_vt.set_defaults(func=cmd_validate_test_types)

    # defect new/close/render
    p_def = sub.add_parser("defect")
    s_def = p_def.add_subparsers(dest="action", required=True)
    p_dn = s_def.add_parser("new")
    p_dn.add_argument("--phase", required=True)
    p_dn.add_argument("--title", required=True)
    p_dn.add_argument("--severity", required=True,
                      choices=["critical", "major", "minor", "trivial"])
    p_dn.add_argument("--found-in", required=True,
                      choices=["build", "review", "test", "accept", "roam"])
    p_dn.add_argument("--goals", nargs="+",
                      help="Related goal ids, e.g. G-11 G-12")
    p_dn.add_argument("--repro", nargs="+", help="Repro steps")
    p_dn.add_argument("--root-cause")
    p_dn.add_argument("--notes", default="")
    p_dn.set_defaults(func=cmd_defect_new)

    p_dc = s_def.add_parser("close")
    p_dc.add_argument("--phase", required=True)
    p_dc.add_argument("--id", required=True)
    p_dc.add_argument("--fix-ref", required=True,
                      help="Commit hash, PR number, or 'wontfix'")
    p_dc.add_argument("--root-cause")
    p_dc.set_defaults(func=cmd_defect_close)

    p_dr = s_def.add_parser("render")
    p_dr.add_argument("--phase", required=True)
    p_dr.set_defaults(func=cmd_defect_render)

    # summary render
    p_sum = sub.add_parser("summary")
    s_sum = p_sum.add_subparsers(dest="action", required=True)
    p_sr = s_sum.add_parser("render")
    p_sr.add_argument("--phase", required=True)
    p_sr.set_defaults(func=cmd_summary_render)

    # rtm render
    p_rtm = sub.add_parser("rtm")
    s_rtm = p_rtm.add_subparsers(dest="action", required=True)
    p_rr = s_rtm.add_parser("render")
    p_rr.add_argument("--phase", required=True)
    p_rr.add_argument("--severity", choices=["block", "warn"], default="block")
    p_rr.set_defaults(func=cmd_rtm_render)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
