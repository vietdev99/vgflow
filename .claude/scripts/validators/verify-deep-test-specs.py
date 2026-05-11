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
    if stages != list(REQUIRED_STAGES):
        missing = sorted(set(REQUIRED_STAGES) - set(stages))
        detail = f" missing: {', '.join(missing)}" if missing else ""
        add_error(out, args, type="lifecycle_stage_missing", message=f"{goal_id} lifecycle stages not in required order.{detail}", file=lifecycle_path, expected="full ordered RCRURDR stages")

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    args = parser.parse_args()

    out = Output(validator="deep-test-specs")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
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
