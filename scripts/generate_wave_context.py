#!/usr/bin/env python3
"""Task 42 — generate wave-{N}-context.md with optional cross-WORKFLOW block.

Existing wave-context generator emitted file/field constraints by
listing waves' tasks. This module adds a Cross-WORKFLOW block per task
whose capsule references a workflow_id that has siblings in other waves.

Importable from orchestrator:
  from generate_wave_context import generate_wave_context
  text = generate_wave_context(phase_dir, wave_id, wave_task_nums, capsules_dir)

Or callable as a CLI:
  python3 scripts/generate-wave-context.py --phase-dir <p> --wave 3 \\
    --tasks 6,7 --capsules-dir <c> > wave-3-context.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

YAML_FENCE_RE = re.compile(r"```ya?ml\n(?P<body>.+?)\n```", re.DOTALL)


def _load_capsule(capsules_dir: Path, task_num: int) -> dict | None:
    f = capsules_dir / f"task-{task_num:02d}.capsule.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_workflow_spec(phase_dir: Path, workflow_id: str) -> dict | None:
    f = phase_dir / "WORKFLOW-SPECS" / f"{workflow_id}.md"
    if not f.exists():
        return None
    text = f.read_text(encoding="utf-8")
    m = YAML_FENCE_RE.search(text)
    if not m:
        return None
    try:
        return yaml.safe_load(m.group("body"))
    except yaml.YAMLError:
        return None


def _index_all_capsules(capsules_dir: Path) -> dict[str, list[dict]]:
    """Build workflow_id → list[capsule] index."""
    index: dict[str, list[dict]] = {}
    if not capsules_dir.is_dir():
        return index
    for f in sorted(capsules_dir.glob("task-*.capsule.json")):
        try:
            cap = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        wf = cap.get("workflow_id")
        if wf:
            index.setdefault(wf, []).append(cap)
    return index


def _state_after_for_step(spec: dict, step_id: int) -> str | None:
    for step in (spec.get("steps") or []):
        if step.get("step_id") == step_id:
            sa = step.get("state_after")
            if isinstance(sa, dict) and sa:
                return str(next(iter(sa.values())))
    return None


def _verb_for_step(spec: dict, step_id: int) -> str:
    """Return 'reads' or 'writes' based on whether step has state_after declared."""
    for step in (spec.get("steps") or []):
        if step.get("step_id") == step_id:
            return "writes" if isinstance(step.get("state_after"), dict) and step.get("state_after") else "reads"
    return "reads"


def _render_cross_workflow_block(
    current_capsule: dict,
    spec: dict,
    workflow_index: dict[str, list[dict]],
) -> list[str]:
    wf_id = current_capsule["workflow_id"]
    siblings = [c for c in workflow_index.get(wf_id, []) if c["task_num"] != current_capsule["task_num"]]
    if not siblings:
        return []

    lines = ["  Cross-WORKFLOW constraint:"]
    for sib in sorted(siblings, key=lambda c: (c.get("wave_id", 0), c["task_num"])):
        wave = sib.get("wave_id", "?")
        actor = (sib.get("actor_role") or "?").upper()
        step = sib.get("workflow_step", "?")
        verb = _verb_for_step(spec, step) if isinstance(step, int) else "interacts with"
        lines.append(
            f"    - Task {sib['task_num']} (wave {wave}, {actor}, step {step} of {wf_id}) "
            f"{verb} state established by your step"
        )

    own_step = current_capsule.get("workflow_step")
    if isinstance(own_step, int):
        sa = _state_after_for_step(spec, own_step)
        if sa:
            lines.append(
                f"    - Your `state_after` MUST be exactly `{sa}` "
                f"(per WORKFLOW-SPECS/{wf_id}.md state_machine.states)"
            )
    return lines


def generate_wave_context(
    phase_dir: Path,
    wave_id: int,
    wave_task_nums: list[int],
    capsules_dir: Path,
) -> str:
    """Render wave-{N}-context.md text. Cross-WORKFLOW block appended per task whose capsule has workflow_id."""
    workflow_index = _index_all_capsules(capsules_dir)

    out: list[str] = [f"# Wave {wave_id} Context — Phase {phase_dir.name}", ""]
    out.append(f"Tasks running in parallel this wave:")
    out.append("")

    cross_emitted = False
    for task_num in wave_task_nums:
        cap = _load_capsule(capsules_dir, task_num)
        if cap is None:
            out.append(f"## Task {task_num}")
            out.append("  (capsule not found — context degraded)")
            out.append("")
            continue
        title = cap.get("task_title") or f"Task {task_num}"
        out.append(f"## Task {task_num} — {title}")

        wf_id = cap.get("workflow_id")
        if wf_id:
            actor = (cap.get("actor_role") or "?").upper()
            step = cap.get("workflow_step", "?")
            out.append(f"  Workflow: {wf_id} step {step} ({actor})")
            spec = _load_workflow_spec(phase_dir, wf_id)
            if spec:
                cross = _render_cross_workflow_block(cap, spec, workflow_index)
                if cross:
                    out.extend(cross)
                    cross_emitted = True
        out.append("")

    if cross_emitted:
        # Telemetry hint for orchestrator (string sentinel parsed by caller).
        out.append("<!-- vg-telemetry: build.cross_wave_workflow_cited -->")
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--phase-dir", required=True)
    p.add_argument("--wave", required=True, type=int)
    p.add_argument("--tasks", required=True, help="Comma-separated task numbers")
    p.add_argument("--capsules-dir", required=True)
    args = p.parse_args()

    nums = [int(s) for s in args.tasks.split(",") if s.strip()]
    text = generate_wave_context(
        phase_dir=Path(args.phase_dir),
        wave_id=args.wave,
        wave_task_nums=nums,
        capsules_dir=Path(args.capsules_dir),
    )
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
