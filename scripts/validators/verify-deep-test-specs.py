#!/usr/bin/env python3
"""Verify post-build deep test-spec artifacts exist before /vg:review."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402

REQUIRED_FILES = (
    ("DEEP-TEST-SPECS.md", 400),
    ("LIFECYCLE-SPECS.json", 80),
    ("TEST-FIXTURE-DAG.json", 80),
    ("TEST-EXECUTION-PLAN.json", 80),
    ("PLAYWRIGHT-SPEC-PLAN.md", 180),
    ("TEST-SPEC-GAPS.md", 40),
)

REQUIRED_LOCALIZER_FILES = (
    ("TEST-SPEC-LOCALIZER/REQUEST.json", 80),
    ("TEST-SPEC-LOCALIZER/PROMPT.md", 200),
    ("TEST-SPEC-LOCALIZER/OUTPUT.schema.json", 80),
    ("TEST-SPEC-LOCALIZER/OUTPUT.template.json", 20),
)

REQUIRED_STAGES = (
    "read_before",
    "create",
    "read_after_create",
    "update",
    "read_after_update",
    "delete",
    "read_after_delete",
)

# B65b (codex BLOCKER #3 fix): per-goal-class stage sets.
# Previous validator hard-required stages == REQUIRED_STAGES (RCRURDR 7).
# generate-lifecycle-specs.py:67-79 defines FEATURE_CHAIN_STAGES (11 stages)
# + READONLY_STAGES (9 stages, B36 R2). Both legitimate. Strict equality
# blocked valid feature_chain + readonly output.
#
# These sets MUST mirror scripts/generate-lifecycle-specs.py — keep in sync
# whenever stage tuples change there. Test ensures parity.
FEATURE_CHAIN_STAGES = (
    "read_before",
    "create",
    "read_after_create",
    "visibility_check",
    "interaction_chain",
    "update",
    "read_after_update",
    "cascade_check",
    "delete",
    "read_after_delete",
    "archive_visibility_check",
)

READONLY_STAGES = (
    "read_before",
    "render_initial",
    "interaction_filter",
    "interaction_sort",
    "interaction_paginate",
    "empty_state",
    "error_state_4xx",
    "loading_state",
    "accessibility",
)

CREATE_ONLY_STAGES = ("read_before", "create", "read_after_create")
UPDATE_ONLY_STAGES = ("read_before", "update", "read_after_update")
DELETE_ONLY_STAGES = ("read_before", "delete", "read_after_delete")

# Map goal_class / goal_type → expected stage set.
# Lookup order in _expected_stages_for_spec():
#   1. goal_class (B62-pre dispatch precedence)
#   2. goal_type
#   3. fallback REQUIRED_STAGES (legacy RCRURDR)
GOAL_CLASS_STAGE_SETS = {
    "feature_chain": FEATURE_CHAIN_STAGES,
    "post_create_cascade": FEATURE_CHAIN_STAGES,  # alias per B62-pre
    "readonly": READONLY_STAGES,
}

GOAL_TYPE_STAGE_SETS = {
    "read-only": READONLY_STAGES,
    "create-only": CREATE_ONLY_STAGES,
    "update-only": UPDATE_ONLY_STAGES,
    "delete-only": DELETE_ONLY_STAGES,
}


def _expected_stages_for_spec(spec: dict[str, Any]) -> tuple[tuple[str, ...], str]:
    """B65b: per-goal-class stage set lookup. Returns (stages, dispatch_key).

    Mirrors generate-lifecycle-specs.py _stages_for_goal precedence:
      1. goal_class (feature_chain etc.) — wins over goal_type
      2. goal_type (create-only, read-only etc.)
      3. fallback REQUIRED_STAGES (full RCRURDR)
    """
    gclass = (str(spec.get("goal_class") or "")).strip().lower()
    if gclass in GOAL_CLASS_STAGE_SETS:
        return GOAL_CLASS_STAGE_SETS[gclass], f"goal_class={gclass}"
    gtype = (str(spec.get("goal_type") or "")).strip().lower()
    if gtype in GOAL_TYPE_STAGE_SETS:
        return GOAL_TYPE_STAGE_SETS[gtype], f"goal_type={gtype}"
    return REQUIRED_STAGES, "default RCRURDR"

SUPPORTED_PROFILES = {
    "web-fullstack",
    "web-frontend-only",
    "web-backend-only",
    "backend-only",
    "backend-multi-actor",
    "mobile-rn",
    "mobile-flutter",
    "mobile-native-ios",
    "mobile-native-android",
    "mobile-hybrid",
    "cli-tool",
    "library",
    "mixed",
}


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None

def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []

def _goal_is_multi_actor(spec: dict[str, Any]) -> bool:
    return "multi" in str(spec.get("goal_type") or "").lower()

def add_error(out: Output, args: argparse.Namespace, *, type: str, message: str, file: Path, expected: str = "", fix_hint: str = "") -> None:
    out.add(
        Evidence(
            type=type,
            message=message,
            file=str(file),
            expected=expected,
            fix_hint=fix_hint or f"Regenerate with /vg:test-spec {args.phase}.",
        ),
        escalate=args.severity == "block",
    )

def validate_goal_contract(out: Output, args: argparse.Namespace, phase_dir: Path, goal_id: str, spec: dict[str, Any]) -> None:
    lifecycle_path = phase_dir / "LIFECYCLE-SPECS.json"
    actors = _list(spec.get("actors"))
    fixtures = _list(spec.get("fixture_dag"))
    cleanup = _list(spec.get("cleanup"))
    steps = _list(spec.get("steps"))
    execution_plan = spec.get("execution_plan") if isinstance(spec.get("execution_plan"), dict) else {}

    if not actors:
        add_error(out, args, type="lifecycle_actor_missing", message=f"{goal_id} has no actors", file=lifecycle_path, expected="actors[] non-empty")
    if _goal_is_multi_actor(spec) and len(actors) < 2:
        add_error(out, args, type="lifecycle_multi_actor_shallow", message=f"{goal_id} is multi-actor but has fewer than 2 actors", file=lifecycle_path, expected="at least 2 actors")
    if not fixtures:
        add_error(out, args, type="lifecycle_fixture_dag_missing", message=f"{goal_id} has no fixture_dag", file=lifecycle_path, expected="fixture_dag[] non-empty")
    if not cleanup:
        add_error(out, args, type="lifecycle_cleanup_missing", message=f"{goal_id} has no cleanup", file=lifecycle_path, expected="cleanup[] non-empty")
    if "artifact_capture" not in spec or not isinstance(spec.get("artifact_capture"), list):
        add_error(out, args, type="lifecycle_artifact_capture_invalid", message=f"{goal_id} artifact_capture must be a list", file=lifecycle_path, expected="artifact_capture[] present")

    stages = [
        str(step.get("stage"))
        for step in steps
        if isinstance(step, dict)
    ]
    # B65b (codex BLOCKER #3): per-goal-class stage set (was: hard-required
    # REQUIRED_STAGES for ALL goals, blocking valid feature_chain + readonly).
    expected_stages, dispatch_key = _expected_stages_for_spec(spec)
    if stages != list(expected_stages):
        missing = sorted(set(expected_stages) - set(stages))
        extra = sorted(set(stages) - set(expected_stages))
        details: list[str] = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if extra:
            details.append(f"unexpected: {', '.join(extra)}")
        detail = f" ({'; '.join(details)})" if details else ""
        add_error(
            out, args,
            type="lifecycle_stage_missing",
            message=f"{goal_id} lifecycle stages not in expected order for {dispatch_key}.{detail}",
            file=lifecycle_path,
            expected=f"ordered stages for {dispatch_key}: {list(expected_stages)}",
        )

    fixture_ids = {str(fixture.get("id")) for fixture in fixtures if isinstance(fixture, dict) and fixture.get("id")}
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            add_error(out, args, type="fixture_dag_schema_invalid", message=f"{goal_id} fixture item must be object", file=lifecycle_path)
            continue
        deps = fixture.get("depends_on") or []
        if not isinstance(deps, list):
            add_error(out, args, type="fixture_dag_dependency_invalid", message=f"{goal_id}:{fixture.get('id')} depends_on must be a list", file=lifecycle_path)
            continue
        missing = [str(dep) for dep in deps if str(dep) not in fixture_ids]
        if missing:
            add_error(out, args, type="fixture_dag_dependency_missing", message=f"{goal_id}:{fixture.get('id')} depends on unknown fixtures: {', '.join(missing)}", file=lifecycle_path, expected="depends_on refs existing fixture ids")

    if not execution_plan:
        add_error(out, args, type="execution_plan_missing", message=f"{goal_id} has no execution_plan", file=lifecycle_path, expected="execution_plan object")
    else:
        profile = str(execution_plan.get("profile") or "")
        if profile not in SUPPORTED_PROFILES:
            add_error(out, args, type="execution_plan_profile_invalid", message=f"{goal_id} execution_plan profile unsupported: {profile}", file=lifecycle_path, expected=f"one of {sorted(SUPPORTED_PROFILES)}")
        if not str(execution_plan.get("runner") or "").strip():
            add_error(out, args, type="execution_plan_runner_missing", message=f"{goal_id} execution_plan.runner missing", file=lifecycle_path, expected="runner string")
        for key in ("entrypoints", "assertions", "artifacts"):
            if not _list(execution_plan.get(key)):
                add_error(out, args, type=f"execution_plan_{key}_missing", message=f"{goal_id} execution_plan.{key} missing", file=lifecycle_path, expected=f"{key}[] non-empty")


def _check_goal_parity(phase_dir: Path) -> tuple[bool, list[str]]:
    """Returns (ok, omitted_goal_ids). Goals are 'automatable' unless skipped."""
    import re
    tg_path = phase_dir / "TEST-GOALS.md"
    ls_path = phase_dir / "LIFECYCLE-SPECS.json"
    if not tg_path.is_file() or not ls_path.is_file():
        return True, []  # nothing to check
    automatable_goals: set[str] = set()
    body = tg_path.read_text(encoding="utf-8")
    for m in re.finditer(r"^##\s+(G-\d+)\b", body, re.M):
        gid = m.group(1)
        # Find this goal's section
        sec_start = m.start()
        next_sec = re.search(r"\n##\s+G-\d+\b", body[sec_start + 1:])
        sec_end = sec_start + 1 + next_sec.start() if next_sec else len(body)
        sec = body[sec_start:sec_end]
        if re.search(r"automation:\s*(?:no|skip|deferred)", sec, re.I):
            continue
        automatable_goals.add(gid)
    try:
        ls = json.loads(ls_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, sorted(automatable_goals)
    emitted = set(ls.get("goals", {}).keys())
    skipped_with_reason: set[str] = set()
    for gid, gdata in ls.get("goals", {}).items():
        if isinstance(gdata, dict) and (gdata.get("skipped", False) or gdata.get("skip_reason")):
            skipped_with_reason.add(gid)
    omitted = automatable_goals - emitted - skipped_with_reason
    return len(omitted) == 0, sorted(omitted)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # --phase-dir takes precedence for direct path; --phase uses find_phase_dir
    parser.add_argument("--phase", default=None)
    parser.add_argument("--phase-dir", default=None, type=Path,
                        help="Direct path to phase directory (overrides --phase)")
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument("--check-goal-parity", action="store_true",
                        help="F3 Batch 22: fail if TEST-GOALS.md automatable goals "
                             "are missing from LIFECYCLE-SPECS.json")
    args = parser.parse_args()

    if args.phase_dir is None and args.phase is None:
        parser.error("--phase or --phase-dir is required")

    out = Output(validator="deep-test-specs")
    with timer(out):
        if args.phase_dir is not None:
            phase_dir = args.phase_dir
            if not phase_dir.is_dir():
                out.add(Evidence(type="phase_not_found", message=f"Phase dir not found: {phase_dir}"))
                emit_and_exit(out)
        else:
            phase_dir = find_phase_dir(args.phase)
            if phase_dir is None:
                out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
                emit_and_exit(out)

        # F3 Batch 22: goal parity check
        if args.check_goal_parity:
            ok, omitted = _check_goal_parity(phase_dir)
            if not ok:
                out.add(
                    Evidence(
                        type="goal_parity_fail",
                        message=f"F3 parity: automatable goals missing from LIFECYCLE-SPECS.json: {', '.join(omitted)}",
                        file=str(phase_dir / "LIFECYCLE-SPECS.json"),
                        expected="all TEST-GOALS.md automatable goals present in LIFECYCLE-SPECS.json",
                        fix_hint="Run /vg:test-spec to regenerate LIFECYCLE-SPECS.json with all goals.",
                    ),
                    escalate=True,
                )
                emit_and_exit(out)

        for filename, min_bytes in (*REQUIRED_FILES, *REQUIRED_LOCALIZER_FILES):
            path = phase_dir / filename
            if not path.exists():
                out.add(
                    Evidence(
                        type="deep_test_spec_missing",
                        message=f"{filename} missing",
                        file=str(path),
                        expected=f"post-build /vg:test-spec artifact {filename}",
                        fix_hint=f"Run /vg:test-spec {args.phase} before /vg:review.",
                    ),
                    escalate=args.severity == "block",
                )
                continue
            if path.stat().st_size < min_bytes:
                out.add(
                    Evidence(
                        type="deep_test_spec_shallow",
                        message=f"{filename} is too small ({path.stat().st_size} bytes)",
                        file=str(path),
                        expected=f">= {min_bytes} bytes",
                        fix_hint=f"Regenerate with /vg:test-spec {args.phase}.",
                    ),
                    escalate=args.severity == "block",
                )

        lifecycle = read_json(phase_dir / "LIFECYCLE-SPECS.json")
        if lifecycle is None:
            out.add(
                Evidence(
                    type="lifecycle_specs_invalid_json",
                    message="LIFECYCLE-SPECS.json is missing or invalid JSON",
                    file=str(phase_dir / "LIFECYCLE-SPECS.json"),
                    fix_hint=f"Run /vg:test-spec {args.phase}.",
                ),
                escalate=args.severity == "block",
            )
        else:
            profile = str(lifecycle.get("phase_profile") or "")
            if profile not in SUPPORTED_PROFILES:
                add_error(
                    out,
                    args,
                    type="lifecycle_phase_profile_invalid",
                    message=f"LIFECYCLE-SPECS.json phase_profile unsupported: {profile}",
                    file=phase_dir / "LIFECYCLE-SPECS.json",
                    expected=f"one of {sorted(SUPPORTED_PROFILES)}",
                )
            goals = lifecycle.get("goals") or {}
            if not isinstance(goals, dict):
                out.add(
                    Evidence(
                        type="lifecycle_goals_invalid",
                        message="LIFECYCLE-SPECS.json goals must be an object",
                        file=str(phase_dir / "LIFECYCLE-SPECS.json"),
                    ),
                    escalate=args.severity == "block",
                )
            for goal_id, spec in list(goals.items())[:200]:
                if not isinstance(spec, dict):
                    continue
                validate_goal_contract(out, args, phase_dir, str(goal_id), spec)

        dag = read_json(phase_dir / "TEST-FIXTURE-DAG.json")
        if dag is None:
            out.add(
                Evidence(
                    type="fixture_dag_invalid_json",
                    message="TEST-FIXTURE-DAG.json is missing or invalid JSON",
                    file=str(phase_dir / "TEST-FIXTURE-DAG.json"),
                ),
                escalate=args.severity == "block",
            )
        else:
            if "nodes" not in dag or "edges" not in dag:
                out.add(
                    Evidence(
                        type="fixture_dag_schema_invalid",
                        message="TEST-FIXTURE-DAG.json must contain nodes and edges",
                        file=str(phase_dir / "TEST-FIXTURE-DAG.json"),
                    ),
                    escalate=args.severity == "block",
                )

        execution = read_json(phase_dir / "TEST-EXECUTION-PLAN.json")
        if execution is None:
            add_error(
                out,
                args,
                type="execution_plan_artifact_invalid_json",
                message="TEST-EXECUTION-PLAN.json is missing or invalid JSON",
                file=phase_dir / "TEST-EXECUTION-PLAN.json",
            )
        else:
            if str(execution.get("phase_profile") or "") not in SUPPORTED_PROFILES:
                add_error(
                    out,
                    args,
                    type="execution_plan_artifact_profile_invalid",
                    message="TEST-EXECUTION-PLAN.json phase_profile invalid",
                    file=phase_dir / "TEST-EXECUTION-PLAN.json",
                    expected=f"one of {sorted(SUPPORTED_PROFILES)}",
                )
            goals = execution.get("goals")
            if not isinstance(goals, dict):
                add_error(
                    out,
                    args,
                    type="execution_plan_artifact_goals_invalid",
                    message="TEST-EXECUTION-PLAN.json goals must be an object",
                    file=phase_dir / "TEST-EXECUTION-PLAN.json",
                )
            else:
                for goal_id, plan in list(goals.items())[:200]:
                    if not isinstance(plan, dict):
                        add_error(out, args, type="execution_plan_goal_invalid", message=f"{goal_id} execution plan must be object", file=phase_dir / "TEST-EXECUTION-PLAN.json")
                        continue
                    if not str(plan.get("runner") or "").strip():
                        add_error(out, args, type="execution_plan_artifact_runner_missing", message=f"{goal_id} runner missing", file=phase_dir / "TEST-EXECUTION-PLAN.json")
                    for key in ("entrypoints", "assertions", "artifacts"):
                        if not _list(plan.get(key)):
                            add_error(out, args, type=f"execution_plan_artifact_{key}_missing", message=f"{goal_id} {key} missing", file=phase_dir / "TEST-EXECUTION-PLAN.json")

    emit_and_exit(out)


if __name__ == "__main__":
    main()
