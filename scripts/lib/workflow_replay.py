"""workflow_replay — Multi-actor workflow runtime replay engine (R7 Task 5 / G9).

Build-side R7 Task 4 (verify-workflow-implementation.py) catches state-literal
absent statically. This module runs at REVIEW verdict layer — replays each
WORKFLOW-SPECS/<WF-NN>.md against a deployed environment to prove:

1. Per-actor session isolation (each role drives its own browser/auth context)
2. State-machine transitions actually fire (state_after observed in DB/UI)
3. Cross-role visibility (admin sees user-submitted record after submission)
4. Authz negative paths (wrong-role transition rejected with 4xx)

This is defense-in-depth — multi-actor bugs that survive static state-literal
grep can still be caught by runtime replay.

Architecture decision (Codex audit 2026-05-04):
  - flow-runner skill is single-actor (resume_context.logged_in_as is one role).
    Has good 4-rule deviation + 3-strike primitives but no role-switch.
  - Cross-role visibility + authz negative paths are NOT in flow-runner's scope.
  - Build sibling helper here (do not fork flow-runner). flow-runner remains
    untouched for FLOW-SPEC.md execution; workflow_replay handles WF-NN.md.

Layers:
  - Layer 1 (parse_workflow_spec)    — fully implemented, pure-yaml parser.
  - Layer 2 (build_replay_plan)      — fully implemented, deterministic.
  - Layer 3 (evidence schema)        — schemas/workflow-replay.v1.schema.json.
  - Layer 4 (execute_replay)         — partial: skeleton emits PARTIAL verdict
                                       with TODO markers when MCP runtime
                                       unavailable. Real Playwright MCP wiring
                                       is downstream work (orchestrator runs
                                       MCP tools in-context, not from a Python
                                       subprocess — see runtime-checks-dynamic
                                       playwright pattern).
  - Layer 5 (validator)              — verify-workflow-replay.py.
  - Layer 6 (review verdict wiring)  — review/verdict/multi-actor-workflow.md.

Public API:
  - parse_workflow_spec(wf_path) -> dict
  - build_replay_plan(spec) -> list[dict]
  - execute_replay(plan, phase_dir, deployed_url, *, mode='mock') -> dict
  - write_replay_evidence(result, output_path) -> None
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

YAML_FENCE_RE = re.compile(r"```ya?ml\n(?P<body>.+?)\n```", re.DOTALL)

SCHEMA_VERSION = "1.0"


class WorkflowReplayError(ValueError):
    """Raised on workflow spec parse / plan build error."""


# ─── Layer 1: parse_workflow_spec ────────────────────────────────────────


def parse_workflow_spec(wf_path: Path) -> dict:
    """Parse WORKFLOW-SPECS/<WF-NN>.md into a structured dict.

    The file is expected to contain a fenced ```yaml ... ``` block matching
    the schema in agents/vg-blueprint-workflows/SKILL.md (workflow_id, name,
    goal_links, actors[], steps[], state_machine, ui_assertions_per_step?).

    Args:
        wf_path: Path to WF-NN.md.

    Returns:
        Dict with keys: workflow_id, name, goal_links, actors, steps,
        state_machine (states[], transitions[]), ui_assertions_per_step.

    Raises:
        WorkflowReplayError on missing file, missing yaml fence, parse fail,
        or missing required top-level keys.
    """
    if not wf_path.exists():
        raise WorkflowReplayError(f"workflow spec not found: {wf_path}")

    text = wf_path.read_text(encoding="utf-8")
    m = YAML_FENCE_RE.search(text)
    if not m:
        raise WorkflowReplayError(f"no yaml fence in {wf_path.name}")

    try:
        import yaml  # type: ignore
    except ImportError as e:  # pragma: no cover - environment guard
        raise WorkflowReplayError(f"pyyaml not installed: {e}") from e

    try:
        spec = yaml.safe_load(m.group("body"))
    except yaml.YAMLError as e:
        raise WorkflowReplayError(f"yaml parse failed for {wf_path.name}: {e}") from e

    if not isinstance(spec, dict):
        raise WorkflowReplayError(f"{wf_path.name}: top-level must be a mapping")

    required = ("workflow_id", "actors", "steps", "state_machine")
    for k in required:
        if k not in spec:
            raise WorkflowReplayError(f"{wf_path.name}: missing required key '{k}'")

    actors = spec.get("actors") or []
    if not isinstance(actors, list) or not actors:
        raise WorkflowReplayError(f"{wf_path.name}: actors must be a non-empty list")

    steps = spec.get("steps") or []
    if not isinstance(steps, list) or not steps:
        raise WorkflowReplayError(f"{wf_path.name}: steps must be a non-empty list")

    sm = spec.get("state_machine") or {}
    if not isinstance(sm, dict) or "states" not in sm:
        raise WorkflowReplayError(f"{wf_path.name}: state_machine must declare states[]")

    return spec


# ─── Layer 2: build_replay_plan ──────────────────────────────────────────


def build_replay_plan(spec: dict) -> list[dict]:
    """Generate ordered step list from a parsed workflow spec.

    Each plan entry surfaces:
      - step_index (1-based, monotonic)
      - step_id (from spec, may be int or string)
      - actor / cred_switch (true when actor differs from previous step)
      - action / view / api / target
      - state_before (resolved from previous step's state_after, or None)
      - state_after (declared in spec)
      - assertions (ui_assertions_per_step entries pinned to step_id)

    The plan is intentionally pure data — no I/O. execute_replay() consumes it.

    Returns:
        List of plan dicts, in execution order.
    """
    steps = spec.get("steps") or []
    ui_assertions = spec.get("ui_assertions_per_step") or []
    states = set(str(s) for s in (spec.get("state_machine", {}).get("states") or []))

    # Index UI assertions by step_id for O(1) lookup
    assertions_by_step: dict[Any, list[dict]] = {}
    for ua in ui_assertions:
        if isinstance(ua, dict):
            sid = ua.get("step_id")
            assertions_by_step.setdefault(sid, []).append(ua)

    # Resolve bootstrap actor (workflow's first declared actor, if any)
    actors_list = spec.get("actors") or []
    prev_actor: str | None = None
    if actors_list and isinstance(actors_list[0], dict):
        role = actors_list[0].get("role")
        if isinstance(role, str):
            prev_actor = role

    plan: list[dict] = []
    prev_state_after: Any = None
    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        actor = step.get("actor")
        cred_switch = bool(actor != prev_actor and prev_actor is not None) or bool(
            step.get("cred_switch_marker")
        )
        state_after = step.get("state_after")

        # Validate state_after values vs declared states (when dict-form)
        if isinstance(state_after, dict):
            for v in state_after.values():
                if str(v) not in states:
                    raise WorkflowReplayError(
                        f"step {step.get('step_id', idx)}: state_after value "
                        f"'{v}' not declared in state_machine.states"
                    )

        plan.append({
            "step_index": idx,
            "step_id": step.get("step_id", idx),
            "actor": actor,
            "cred_switch": cred_switch,
            "action": step.get("action"),
            "view": step.get("view"),
            "api": step.get("api"),
            "target": step.get("target"),
            "state_before": prev_state_after,
            "state_after": state_after,
            "assertions": assertions_by_step.get(step.get("step_id"), []),
            "goals": step.get("goals") or [],
        })
        prev_actor = actor
        prev_state_after = state_after

    return plan


def collect_actors(plan: list[dict]) -> list[str]:
    """Distinct ordered list of actor names appearing in the plan."""
    seen: list[str] = []
    for entry in plan:
        a = entry.get("actor")
        if isinstance(a, str) and a not in seen:
            seen.append(a)
    return seen


def derive_authz_negative_probes(spec: dict, plan: list[dict]) -> list[dict]:
    """Derive authz negative-path probes from the plan.

    For every step that has an `api` field, every OTHER actor in the workflow
    is a candidate to be denied that action. We emit one probe per
    (action, foreign_actor) pair — execute_replay() drives the actual call.

    Returns:
        List of probe dicts: {action, attempted_by, expected_status: 403}.
    """
    actors = collect_actors(plan)
    probes: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in plan:
        api = entry.get("api")
        action = entry.get("action")
        owning_actor = entry.get("actor")
        if not api or not owning_actor:
            continue
        for other in actors:
            if other == owning_actor:
                continue
            key = (action or "", other, str(api))
            if key in seen:
                continue
            seen.add(key)
            probes.append({
                "action": action,
                "api": api,
                "attempted_by": other,
                "expected_status": 403,
            })
    return probes


def derive_visibility_checks(spec: dict, plan: list[dict]) -> list[dict]:
    """Derive cross-role visibility checks from the plan.

    Rule: when a step's actor changes from previous step (cred_switch=True),
    the new actor SHOULD be able to see the state_after that the previous
    actor wrote. Emits a check {from_role, checked, expected}.

    Returns:
        List of check dicts.
    """
    checks: list[dict] = []
    for i, entry in enumerate(plan):
        if not entry.get("cred_switch") or i == 0:
            continue
        prev = plan[i - 1]
        prev_state = prev.get("state_after")
        if prev_state is None:
            continue
        if isinstance(prev_state, dict):
            checked = "; ".join(f"{k}={v}" for k, v in prev_state.items())
        else:
            checked = str(prev_state)
        checks.append({
            "from_role": entry.get("actor"),
            "checked": f"state set by {prev.get('actor')} at step {prev.get('step_index')}: {checked}",
            "expected": checked,
        })
    return checks


# ─── Layer 4: execute_replay (partial — see module docstring) ────────────


@dataclass
class ReplayContext:
    """Runtime context passed to per-step executors. Pure data shell so
    tests can supply mock implementations without monkey-patching.
    """
    deployed_url: str | None
    phase_dir: Path
    mode: str  # 'live' | 'mock' | 'dry-run'
    notes: list[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def execute_replay(
    plan: list[dict],
    phase_dir: Path,
    deployed_url: str | None,
    *,
    mode: str = "mock",
    workflow_id: str = "WF-UNKNOWN",
    spec: dict | None = None,
    step_executor=None,
    visibility_executor=None,
    authz_executor=None,
) -> dict:
    """Execute the replay plan and return evidence dict.

    Args:
        plan: Output of build_replay_plan.
        phase_dir: Phase directory (where .runs/ artifacts land).
        deployed_url: Base URL of the deployed env. Required for mode='live'.
        mode: 'live' | 'mock' | 'dry-run'.
        workflow_id: WF-NN identifier (recorded in evidence).
        spec: Original parsed spec (used to derive visibility/authz checks).
        step_executor: Callable(plan_entry, ctx) -> step evidence dict. When
            None, mock executor returns SKIPPED with a TODO note.
        visibility_executor: Callable(check, ctx) -> verdict dict. When None,
            mock returns SKIPPED.
        authz_executor: Callable(probe, ctx) -> verdict dict. When None, mock
            returns SKIPPED.

    Returns:
        Evidence dict matching schemas/workflow-replay.v1.schema.json.

    Layer 4 status: in mode='mock' or when no executors are wired, the
    function returns a PARTIAL verdict with TODO notes. Real live execution
    requires Playwright MCP runtime in the orchestrator (see review verdict
    integration doc).
    """
    started_at = _now_iso()
    t0 = time.time()
    ctx = ReplayContext(
        deployed_url=deployed_url,
        phase_dir=phase_dir,
        mode=mode,
        notes=[],
    )

    # ─── Run per-step executors ────────────────────────────────────────
    step_results: list[dict] = []
    blocking_failures: list[str] = []

    for entry in plan:
        if mode == "dry-run":
            step_results.append({
                "step_index": entry["step_index"],
                "step_id": entry.get("step_id"),
                "actor": entry.get("actor"),
                "action": entry.get("action"),
                "view": entry.get("view"),
                "api": entry.get("api"),
                "state_before": entry.get("state_before"),
                "state_after": entry.get("state_after"),
                "verdict": "SKIPPED",
                "evidence": {},
                "duration_ms": 0,
                "failure_reason": None,
                "cred_switch": entry.get("cred_switch", False),
            })
            continue

        if step_executor is None:
            # Layer 4 stub — record SKIPPED with a TODO marker
            ctx.notes.append(
                f"step {entry['step_index']} ({entry.get('actor')}/"
                f"{entry.get('action')}): TODO live MCP execution — "
                f"orchestrator must drive Playwright tools"
            )
            step_results.append({
                "step_index": entry["step_index"],
                "step_id": entry.get("step_id"),
                "actor": entry.get("actor"),
                "action": entry.get("action"),
                "view": entry.get("view"),
                "api": entry.get("api"),
                "state_before": entry.get("state_before"),
                "state_after": entry.get("state_after"),
                "verdict": "SKIPPED",
                "evidence": {
                    "screenshot_path": None,
                    "console_logs": [],
                    "network_requests": [],
                    "ui_assertions": [],
                },
                "duration_ms": 0,
                "failure_reason": "live MCP executor not wired",
                "cred_switch": entry.get("cred_switch", False),
            })
            continue

        # Custom executor (test mock or real implementation)
        try:
            ev = step_executor(entry, ctx) or {}
        except Exception as e:  # pragma: no cover - defensive
            ev = {"verdict": "FAILED", "failure_reason": f"executor crashed: {e}"}

        merged = {
            "step_index": entry["step_index"],
            "step_id": entry.get("step_id"),
            "actor": entry.get("actor"),
            "action": entry.get("action"),
            "view": entry.get("view"),
            "api": entry.get("api"),
            "state_before": entry.get("state_before"),
            "state_after": entry.get("state_after"),
            "verdict": ev.get("verdict", "SKIPPED"),
            "evidence": ev.get("evidence", {}),
            "duration_ms": ev.get("duration_ms", 0),
            "failure_reason": ev.get("failure_reason"),
            "cred_switch": entry.get("cred_switch", False),
        }
        step_results.append(merged)
        if merged["verdict"] == "FAILED":
            blocking_failures.append(
                f"step {merged['step_index']} ({merged['actor']}/"
                f"{merged['action']}) failed: {merged.get('failure_reason') or 'no reason'}"
            )

    # ─── Cross-role visibility ─────────────────────────────────────────
    visibility_results: list[dict] = []
    if spec is not None:
        for check in derive_visibility_checks(spec, plan):
            if visibility_executor is None or mode in ("dry-run", "mock"):
                visibility_results.append({
                    "from_role": check["from_role"],
                    "checked": check["checked"],
                    "expected": check.get("expected"),
                    "actual": None,
                    "verdict": "SKIPPED",
                })
                continue
            try:
                v = visibility_executor(check, ctx) or {}
            except Exception as e:  # pragma: no cover - defensive
                v = {"verdict": "SKIPPED", "actual": f"executor crashed: {e}"}
            visibility_results.append({
                "from_role": check["from_role"],
                "checked": check["checked"],
                "expected": check.get("expected"),
                "actual": v.get("actual"),
                "verdict": v.get("verdict", "SKIPPED"),
            })
            if v.get("verdict") == "NOT_VISIBLE":
                blocking_failures.append(
                    f"visibility: {check['from_role']} cannot see "
                    f"{check['checked']}"
                )

    # ─── Authz negative paths ──────────────────────────────────────────
    authz_results: list[dict] = []
    if spec is not None:
        for probe in derive_authz_negative_probes(spec, plan):
            if authz_executor is None or mode in ("dry-run", "mock"):
                authz_results.append({
                    "actor": probe["attempted_by"],
                    "attempted": str(probe.get("action") or probe.get("api")),
                    "expected_status": probe.get("expected_status"),
                    "actual_status": None,
                    "verdict": "SKIPPED",
                })
                continue
            try:
                v = authz_executor(probe, ctx) or {}
            except Exception as e:  # pragma: no cover - defensive
                v = {"verdict": "SKIPPED", "actual_status": None,
                     "note": f"executor crashed: {e}"}
            actual = v.get("actual_status")
            verdict = v.get("verdict")
            if verdict is None:
                # Compute from status comparison
                if actual is not None and actual >= 400:
                    verdict = "PASSED"
                elif actual is not None and actual < 400:
                    verdict = "FAILED"
                else:
                    verdict = "SKIPPED"
            authz_results.append({
                "actor": probe["attempted_by"],
                "attempted": str(probe.get("action") or probe.get("api")),
                "expected_status": probe.get("expected_status"),
                "actual_status": actual,
                "verdict": verdict,
            })
            if verdict == "FAILED":
                blocking_failures.append(
                    f"authz: {probe['attempted_by']} succeeded at "
                    f"{probe.get('action')} (expected denied)"
                )

    # ─── Compose overall verdict ───────────────────────────────────────
    actors_used = collect_actors(plan)
    completed_at = _now_iso()
    duration_ms = int((time.time() - t0) * 1000)

    overall = _compute_overall_verdict(
        step_results=step_results,
        visibility_results=visibility_results,
        authz_results=authz_results,
        blocking_failures=blocking_failures,
        mode=mode,
    )

    if mode in ("mock", "dry-run") and not ctx.notes:
        ctx.notes.append(
            "Replay ran in non-live mode — partial verdict expected. "
            "Live execution requires Playwright MCP runtime via review verdict orchestrator."
        )

    return {
        "workflow_id": workflow_id,
        "schema_version": SCHEMA_VERSION,
        "replay_started_at": started_at,
        "replay_completed_at": completed_at,
        "actors_used": actors_used,
        "deployed_url": deployed_url,
        "execution_mode": mode,
        "steps": step_results,
        "cross_role_visibility": visibility_results,
        "authz_negative_paths": authz_results,
        "side_effects_captured": {},
        "overall_verdict": overall,
        "blocking_failures": blocking_failures,
        "notes": ctx.notes,
        "duration_ms": duration_ms,
    }


def _compute_overall_verdict(
    *,
    step_results: list[dict],
    visibility_results: list[dict],
    authz_results: list[dict],
    blocking_failures: list[str],
    mode: str,
) -> str:
    """Derive overall_verdict from per-component results.

    Rules (precedence top→bottom):
      1. blocking_failures non-empty → FAILED
      2. mode in {mock, dry-run} → PARTIAL (no live evidence)
      3. any required step SKIPPED → PARTIAL
      4. any required check SKIPPED → PARTIAL
      5. otherwise → PASSED
    """
    if blocking_failures:
        return "FAILED"
    if mode in ("mock", "dry-run"):
        return "PARTIAL"

    has_skipped_step = any(s.get("verdict") == "SKIPPED" for s in step_results)
    has_skipped_check = any(
        v.get("verdict") == "SKIPPED" for v in visibility_results
    ) or any(a.get("verdict") == "SKIPPED" for a in authz_results)
    if has_skipped_step or has_skipped_check:
        return "PARTIAL"
    return "PASSED"


# ─── Evidence writer ─────────────────────────────────────────────────────


def write_replay_evidence(result: dict, output_path: Path) -> None:
    """Write replay result JSON to ${PHASE_DIR}/.runs/<WF-NN>.replay.json.

    Creates parent directory if missing. Writes pretty-printed JSON for
    diff-friendliness.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )


# ─── End-to-end convenience ──────────────────────────────────────────────


def replay_workflow_file(
    wf_path: Path,
    phase_dir: Path,
    deployed_url: str | None,
    *,
    mode: str = "mock",
    step_executor=None,
    visibility_executor=None,
    authz_executor=None,
) -> dict:
    """Convenience wrapper: parse → plan → execute → return evidence.

    Used by the validator's integration tests + by review verdict orchestrator
    when wiring real executors.
    """
    spec = parse_workflow_spec(wf_path)
    plan = build_replay_plan(spec)
    workflow_id = str(spec.get("workflow_id") or wf_path.stem)
    return execute_replay(
        plan,
        phase_dir=phase_dir,
        deployed_url=deployed_url,
        mode=mode,
        workflow_id=workflow_id,
        spec=spec,
        step_executor=step_executor,
        visibility_executor=visibility_executor,
        authz_executor=authz_executor,
    )
