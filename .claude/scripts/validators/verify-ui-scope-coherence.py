#!/usr/bin/env python3
"""Validator: verify-ui-scope-coherence — UI scope vs PLAN coherence gate.

Cross-checks `.ui-scope.json` (authoritative AI semantic detection from
preflight/detect-ui-scope.py) against PLAN.md FE-task count to catch the
class of bugs where:

  A) SPECS says "phase has UI" but planner ships zero FE tasks
     → silent UI gap, build produces backend only, UAT fails (L-002)

  B) SPECS says "phase is backend-only" but planner spawns FE tasks anyway
     → scope violation, FE leaks into wrong phase, design refs missing

Mismatch → BLOCK with explicit fix hints.
PASS = scope decision matches PLAN reality.

Usage:  verify-ui-scope-coherence.py --phase 4.3
        verify-ui-scope-coherence.py --phase 6 --strict
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402


FE_PATH_RE = re.compile(
    r"<file-path>\s*("
    r"apps/(admin|merchant|vendor|web)/[^<\s]+|"
    r"packages/ui/[^<\s]+|"
    r"[^<\s]+\.(tsx|jsx|vue|svelte)"
    r")\s*</file-path>",
    re.IGNORECASE,
)

# Tasks that touch FE patterns even if file path uses generic naming
FE_DESC_HINT_RE = re.compile(
    r"\b(React component|JSX|TSX|page component|Tailwind|Shadcn|Zustand|TanStack|"
    r"sidebar|topbar|navbar|modal|drawer|wizard|stepper|form component|UI component|"
    r"frontend route|FE route|client-side router)\b",
    re.IGNORECASE,
)


def count_fe_tasks(plan_text: str) -> tuple[int, list[str]]:
    """Return (count, examples). Splits PLAN by `### Task N` and checks each."""
    task_blocks = re.split(r"(?m)^### Task \d+", plan_text)
    fe_tasks = []
    for i, block in enumerate(task_blocks[1:], 1):
        if FE_PATH_RE.search(block):
            # Extract file-path for evidence
            m = FE_PATH_RE.search(block)
            fe_tasks.append(f"Task {i}: {m.group(1)[:80]}")
    return len(fe_tasks), fe_tasks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--strict", action="store_true",
                        help="treat low-confidence (<0.5) ui-scope as BLOCK")
    parser.add_argument("--allow-mismatch", action="store_true",
                        help="downgrade BLOCK to WARN (logs override-debt elsewhere)")
    args = parser.parse_args()

    out = Output(validator="ui-scope-coherence")

    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(
                type="phase_dir_not_found",
                message=f"Phase {args.phase} directory not found",
                fix_hint="Verify phase number; run /vg:scope <phase> first.",
            ))
            return emit_and_exit(out) or 1

        ui_scope_path = phase_dir / ".ui-scope.json"
        plan_path = phase_dir / "PLAN.md"

        if not plan_path.exists():
            out.warn(Evidence(
                type="plan_not_found",
                message=f"PLAN.md not found at {plan_path}",
                fix_hint="Run /vg:blueprint <phase> step 2a first.",
            ))
            return emit_and_exit(out) or 0

        if not ui_scope_path.exists():
            out.add(Evidence(
                type="ui_scope_missing",
                message=f".ui-scope.json not found at {ui_scope_path}",
                fix_hint=(
                    "Run preflight/detect-ui-scope.py --phase-dir <phase_dir> to "
                    "generate authoritative UI scope decision before validation."
                ),
            ))
            return emit_and_exit(out) or 1

        try:
            scope = json.loads(ui_scope_path.read_text(encoding="utf-8"))
        except Exception as e:
            out.add(Evidence(
                type="ui_scope_parse_error",
                message=f".ui-scope.json invalid JSON: {e}",
                file=str(ui_scope_path),
                fix_hint="Re-run preflight/detect-ui-scope.py --force to regenerate.",
            ))
            return emit_and_exit(out) or 1

        has_ui_declared: bool = bool(scope.get("has_ui", False))
        confidence: float = float(scope.get("confidence", 0.0))
        evidence_quote: str = scope.get("evidence", "")[:200]
        deferred_to: str | None = scope.get("deferred_to")
        method: str = scope.get("method", "unknown")
        ui_kinds: list[str] = scope.get("ui_kinds") or []

        # Strict-mode confidence floor
        if args.strict and confidence < 0.5:
            out.add(Evidence(
                type="low_confidence_strict",
                message=f"ui-scope confidence={confidence:.2f} below 0.5 threshold (--strict)",
                expected="confidence >= 0.5",
                actual=str(confidence),
                fix_hint=(
                    "Re-run detect-ui-scope.py with --force, or run an "
                    "AskUserQuestion fallback to confirm 'has_ui' manually."
                ),
            ))

        # Count FE tasks in PLAN
        plan_text = plan_path.read_text(encoding="utf-8")
        fe_count, fe_examples = count_fe_tasks(plan_text)

        # Decision matrix
        if has_ui_declared and fe_count == 0:
            # Case A: silent UI gap
            out.add(Evidence(
                type="ui_declared_no_fe_tasks",
                message=(
                    f"ui-scope declares has_ui=true (confidence={confidence:.2f}, "
                    f"method={method}, kinds={ui_kinds}) but PLAN.md has ZERO FE "
                    f"tasks (file paths matching apps/admin|merchant|vendor|web/, "
                    f"packages/ui/, or .tsx/.jsx/.vue/.svelte)."
                ),
                file=str(plan_path),
                expected=f"FE tasks > 0 (UI scope: {ui_kinds})",
                actual="0 FE tasks",
                fix_hint=(
                    "Either (a) re-run /vg:blueprint to add FE tasks covering the "
                    "declared UI surface; or (b) if UI is actually deferred, edit "
                    "SPECS.md to clarify and re-run preflight/detect-ui-scope.py "
                    "--force; or (c) run with --allow-mismatch (logs override-debt) "
                    "if scope is intentionally split (FE in a sibling phase)."
                ),
            ))
        elif not has_ui_declared and fe_count > 0:
            # Case B: scope violation — FE leaked into BE-only phase
            out.add(Evidence(
                type="be_only_with_fe_leak",
                message=(
                    f"ui-scope declares has_ui=false (confidence={confidence:.2f}, "
                    f"deferred_to={deferred_to or 'N/A'}) but PLAN.md has {fe_count} "
                    f"FE task(s) — FE leaked into a backend-only phase."
                ),
                file=str(plan_path),
                expected="0 FE tasks (phase is backend-only)",
                actual=f"{fe_count} FE tasks: {fe_examples[:3]}",
                fix_hint=(
                    "Either (a) re-plan and remove FE tasks (move to the phase "
                    "named in deferred_to); or (b) edit SPECS to include UI "
                    "scope and re-run preflight/detect-ui-scope.py --force; "
                    "or (c) --allow-mismatch (log override-debt) if FE files "
                    "are intentional (e.g., shared component used by future phase)."
                ),
            ))
        else:
            # Coherent: both true (UI phase with FE tasks) or both false (BE phase, no FE)
            pass

        # Downgrade BLOCK → WARN under --allow-mismatch
        if args.allow_mismatch and out.verdict == "BLOCK":
            # Convert all evidence to WARN-level
            out.verdict = "WARN"

        # If no findings at all, emit positive evidence so the operator sees the gate ran
        if not out.evidence:
            out.evidence.append(Evidence(
                type="coherent",
                message=(
                    f"PASS: ui-scope (has_ui={has_ui_declared}, "
                    f"confidence={confidence:.2f}, method={method}) "
                    f"matches PLAN ({fe_count} FE tasks). "
                    f"Evidence: {evidence_quote}"
                ),
            ))

    return emit_and_exit(out) or 0


if __name__ == "__main__":
    sys.exit(main() or 0)
