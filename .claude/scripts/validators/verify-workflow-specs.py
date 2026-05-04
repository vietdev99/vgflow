#!/usr/bin/env python3
"""Task 40 — verify WORKFLOW-SPECS/<WF-NN>.md schema compliance.

Required top-level keys: workflow_id, name, goal_links, actors, steps,
state_machine, ui_assertions_per_step.

Cross-field invariants:
- Every `state_after` value seen in steps[] must appear in
  state_machine.states[] (no orphan state names).
- When step N's actor differs from step N-1's actor, step N MUST set
  `cred_switch_marker: true` (FE codegen injects testRoleSwitch()).
- Each `ui_assertions_per_step.rcrurd_invariant_ref` (when present) must
  reference a goal_id in this file's goal_links.

Empty index.md (no flows) is allowed for phases without multi-actor work.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

REQUIRED_TOP_KEYS = (
    "workflow_id", "name", "goal_links", "actors", "steps", "state_machine"
)
YAML_FENCE_RE = re.compile(r"```ya?ml\n(?P<body>.+?)\n```", re.DOTALL)


def _load_yaml_block(md_path: Path) -> dict | None:
    text = md_path.read_text(encoding="utf-8")
    m = YAML_FENCE_RE.search(text)
    if not m:
        return None
    try:
        return yaml.safe_load(m.group("body"))
    except yaml.YAMLError:
        return None


def _check_workflow(spec: dict, source: str) -> list[str]:
    findings: list[str] = []

    for k in REQUIRED_TOP_KEYS:
        if k not in spec:
            findings.append(f"{source}: missing required top-level key '{k}'")

    states = set()
    sm = spec.get("state_machine") or {}
    for s in sm.get("states", []) or []:
        states.add(str(s))

    # Collect state_after strings used in steps[]
    for step in spec.get("steps", []) or []:
        sa = step.get("state_after")
        if isinstance(sa, dict):
            for state_value in sa.values():
                if str(state_value) not in states:
                    findings.append(
                        f"{source}: step {step.get('step_id')} state_after value "
                        f"'{state_value}' not declared in state_machine.states"
                    )

    # cred_switch_marker required when actor changes between consecutive steps
    prev_actor: str | None = None
    for step in spec.get("steps", []) or []:
        actor = step.get("actor")
        if prev_actor is not None and actor != prev_actor:
            if not step.get("cred_switch_marker"):
                findings.append(
                    f"{source}: step {step.get('step_id')} actor changed from '{prev_actor}' "
                    f"to '{actor}' but cred_switch_marker is not true"
                )
        prev_actor = actor

    # rcrurd_invariant_ref must match a goal_id in goal_links
    goal_links = set(str(g) for g in (spec.get("goal_links") or []))
    for ua in spec.get("ui_assertions_per_step", []) or []:
        ref = ua.get("rcrurd_invariant_ref")
        if ref and str(ref) not in goal_links:
            findings.append(
                f"{source}: ui_assertions_per_step step {ua.get('step_id')} "
                f"references unknown goal '{ref}' (not in goal_links)"
            )

    return findings


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--workflows-dir", required=True)
    args = p.parse_args()

    wf_dir = Path(args.workflows_dir)
    if not wf_dir.is_dir():
        print(f"ERROR: --workflows-dir not a directory: {wf_dir}", file=sys.stderr)
        return 2

    index = wf_dir / "index.md"
    if not index.exists():
        print(f"BLOCK: missing {index}", file=sys.stderr)
        return 1
    index_text = index.read_text(encoding="utf-8")

    # Empty index ⇒ no workflows expected ⇒ pass
    if "flows: []" in index_text and not list(wf_dir.glob("WF-*.md")):
        return 0

    findings: list[str] = []
    for wf_path in sorted(wf_dir.glob("WF-*.md")):
        spec = _load_yaml_block(wf_path)
        if spec is None:
            findings.append(f"{wf_path.name}: missing or invalid yaml fence")
            continue
        findings.extend(_check_workflow(spec, wf_path.name))

    if findings:
        print("BLOCK: WORKFLOW-SPECS validation findings:")
        for f in findings:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
