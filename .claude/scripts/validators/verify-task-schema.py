#!/usr/bin/env python3
"""
Validator: verify-task-schema.py — Phase 16 D-02

Classify PLAN tasks as xml/heading/mixed format and gate per
vg.config.task_schema mode:

  legacy (default):    PASS heading; PASS xml; WARN mixed
  structured:          BLOCK heading; PASS xml only
  both:                WARN heading; PASS xml

XML-format tasks REQUIRE frontmatter `acceptance:` array with ≥1 entry
(structured task contract per Phase 16 D-02). Missing → BLOCK regardless
of mode.

Migration enforcement: WARN-now / BLOCK-after-2-cycles cycle to give
consumer projects time to migrate their PLAN format.

Usage:  verify-task-schema.py --phase 7.14.3
        verify-task-schema.py --phase 7.14.3 --mode structured
        verify-task-schema.py --phase 7.14.3 --strict
Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402


def _load_pec():
    """Load extract_all_tasks from pre-executor-check.py without polluting
    the global module namespace (the script's hyphenated name prevents
    direct import)."""
    pec_path = Path(__file__).resolve().parents[1] / "pre-executor-check.py"
    spec = importlib.util.spec_from_file_location("pre_executor_check", pec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _resolve_mode(phase_dir: Path, cli_mode: str | None) -> str:
    """Resolve task_schema mode in priority order: --mode CLI flag,
    vg.config.task_schema in phase or repo, fallback "legacy"."""
    if cli_mode:
        return cli_mode
    # Look for vg.config.md alongside the phase tree (.vg/phases/<x>/.. is the
    # repo root, two levels up).
    for parent_levels in range(2, 5):
        candidate = phase_dir
        for _ in range(parent_levels):
            candidate = candidate.parent
        cfg = candidate / "vg.config.md"
        if cfg.exists():
            text = cfg.read_text(encoding="utf-8", errors="ignore")
            import re
            m = re.search(r"^task_schema\s*:\s*([a-z]+)", text, re.MULTILINE)
            if m:
                return m.group(1).strip()
            break
    return "legacy"


def main() -> None:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--mode",
                    choices=("legacy", "structured", "both"),
                    default=None,
                    help="Override vg.config.task_schema. Default reads config.")
    ap.add_argument("--strict", action="store_true",
                    help="Escalate WARN to BLOCK (planned escalation per D-02 plan).")
    args = ap.parse_args()

    out = Output(validator="task-schema")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            out.add(Evidence(type="missing_file",
                             message=f"Phase dir not found for {args.phase}"))
            emit_and_exit(out)

        mode = _resolve_mode(phase_dir, args.mode)
        plan_files = sorted(phase_dir.glob("PLAN*.md"))
        if not plan_files:
            out.warn(Evidence(
                type="info",
                message=f"No PLAN*.md in {phase_dir} — nothing to classify",
            ))
            emit_and_exit(out)

        try:
            pec = _load_pec()
        except Exception as e:
            out.add(Evidence(type="config-error",
                             message=f"failed to load pre-executor-check.py: {e}"))
            emit_and_exit(out)

        all_tasks = []
        per_file_format: dict[Path, set[str]] = {}
        for pf in plan_files:
            tasks = pec.extract_all_tasks(pf)
            all_tasks.extend(tasks)
            per_file_format[pf] = {t["format"] for t in tasks}

        if not all_tasks:
            out.warn(Evidence(
                type="info",
                message=f"No tasks parsed from {len(plan_files)} PLAN file(s)",
            ))
            emit_and_exit(out)

        formats = {t["format"] for t in all_tasks}
        is_mixed = len(formats) > 1

        # XML tasks MUST have frontmatter acceptance ≥1 entry
        for task in all_tasks:
            if task["format"] != "xml":
                continue
            fm = task.get("frontmatter") or {}
            acceptance = fm.get("acceptance")
            if not acceptance or not isinstance(acceptance, list) or len(acceptance) == 0:
                out.add(Evidence(
                    type="schema_violation",
                    message=(
                        f"Task {task['id']} is XML format but frontmatter "
                        f"`acceptance:` array is missing or empty (Phase 16 D-02 "
                        f"requires ≥1 acceptance criterion per task)"
                    ),
                    file=str(plan_files[0]),
                    expected="acceptance: [<criterion 1>, ...]",
                    actual=fm,
                    fix_hint=(
                        "Add to task frontmatter:\n"
                        "  ---\n"
                        "  acceptance:\n"
                        "    - \"<measurable success criterion>\"\n"
                        "  ---"
                    ),
                ))

        # Mode-specific gates
        for task in all_tasks:
            if task["format"] != "heading":
                continue
            evidence = Evidence(
                type="legacy_format",
                message=(
                    f"Task {task['id']} uses legacy heading format — "
                    f"Phase 16 D-02 prefers `<task id=\"N\">...</task>` "
                    f"with YAML frontmatter for structured acceptance/edge_cases"
                ),
                file=str(plan_files[0]),
                fix_hint=(
                    "Migrate task block to:\n"
                    "  <task id=\"N\">\n"
                    "  ---\n"
                    "  acceptance: [\"...\"]\n"
                    "  edge_cases: [\"...\"]\n"
                    "  decision_refs: [\"P{phase}.D-XX\"]\n"
                    "  ---\n"
                    "  Body markdown\n"
                    "  </task>"
                ),
            )
            if mode == "structured":
                out.add(evidence)         # BLOCK
            elif mode == "both":
                out.warn(evidence)
            else:  # legacy — PASS, but emit info if --strict
                if args.strict:
                    out.warn(evidence)

        if is_mixed and mode != "structured":
            out.warn(Evidence(
                type="schema_drift",
                message=(
                    f"PLAN files contain MIXED formats ({sorted(formats)}) — "
                    f"unify on one format to reduce reviewer cognitive load"
                ),
                file=str(plan_files[0]),
                actual=sorted(formats),
            ))

        if not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message=(
                    f"Task schema PASS — mode={mode}, "
                    f"{len(all_tasks)} task(s), formats={sorted(formats)}"
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
