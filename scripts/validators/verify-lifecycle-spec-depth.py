#!/usr/bin/env python3
"""Verify mutation goals have closed-loop lifecycle specs before /vg:test.

This gate closes a false-confidence class where a side-effecting TEST-GOAL has
flat "CRUD" wording but no executable fixture dependency graph. A real E2E
test needs prerequisites, actors, generated artifacts, state transitions, and
cleanup before codegen starts.

Required for each side-effecting goal:
  - LIFECYCLE-SPECS.json entry under goals.<G-ID>
  - actors[] with role/session context; multi-actor goals require >=2
  - fixture_dag[] with id, kind, cleanup
  - preconditions[]
  - steps[] containing full RCRURDR stages
  - artifact_capture[] when the goal emits/consumes email, token, websocket,
    realtime, notification, callback, invite, or magic-link artifacts
  - cleanup[] with target + action
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402

REQUIRED_STAGES = (
    "read_before",
    "create",
    "read_after_create",
    "update",
    "read_after_update",
    "delete",
    "read_after_delete",
)

SIDE_EFFECT_WORD_RE = re.compile(
    r"\b("
    r"create|created|update|updated|delete|deleted|patch|post|put|"
    r"submit|submitted|save|saved|edit|edited|remove|removed|add|added|"
    r"invite|invited|accept|accepted|register|login|logout|verify|verified|"
    r"refresh|revoke|revoked|pay|payment|refund|withdraw|transfer|sync|"
    r"upload|approve|approved|reject|rejected|enable|enabled|disable|"
    r"disabled|activate|deactivate|cancel|cancelled|archive|restore|"
    r"crud|rcrurd|rcrurdr|wizard|duplicate|mark|assign|unassign|"
    r"token|2fa|otp|webauthn"
    r")\b",
    re.IGNORECASE,
)

ARTIFACT_WORD_RE = re.compile(
    r"\b("
    r"email|mail|token|magic\s+link|websocket|ws|realtime|real-time|"
    r"notification|callback|webhook|invite|invitation|otp|2fa|webauthn"
    r")\b",
    re.IGNORECASE,
)

# B98: `admin` removed — it is a SINGLE role, the opposite of a multi-actor
# signal. Pre-B98 every admin-only goal ("admin opens page X") tripped this
# regex and was wrongly required to declare >=2 actors. Genuine multi-actor
# (admin impersonates merchant) still matches via `impersonat`/`owner`/etc.
MULTI_ACTOR_WORD_RE = re.compile(
    r"\b("
    r"multi[-\s]?actor|owner|invitee|inviter|approver|reviewer|"
    r"second\s+user|another\s+user|role\s+switch|impersonat|oauth"
    r")\b",
    re.IGNORECASE,
)

EMPTY_VALUES = {"", "none", "n/a", "na", "null", "-", "[]", "{}"}

# G13 Batch 3: semantic checks — stage verb ↔ endpoint method, assertion source, actor ↔ goal.actors
STAGE_VERB_MAP: dict[str, tuple[str, ...]] = {
    "create": ("POST",),
    "update": ("PUT", "PATCH"),
    "delete": ("DELETE",),
    "read_before": ("GET",),
    "read_after_create": ("GET",),
    "read_after_update": ("GET",),
    "read_after_delete": ("GET",),
}


def _semantic_checks(spec: dict) -> list[str]:
    """Return list of G13 semantic issues."""
    issues: list[str] = []
    for gid, goal in (spec.get("goals") or {}).items():
        if not isinstance(goal, dict):
            continue
        actor_ids = {a.get("id") for a in (goal.get("actors") or []) if isinstance(a, dict)}
        for step in (goal.get("steps") or []):
            if not isinstance(step, dict):
                continue
            stage = step.get("name") or step.get("stage")
            # Stage ↔ endpoint method match
            ep = step.get("endpoint")
            if ep and isinstance(ep, dict) and stage in STAGE_VERB_MAP:
                expected = STAGE_VERB_MAP[stage]
                if ep.get("method") not in expected:
                    issues.append(
                        f"G13: goal {gid} stage '{stage}' bound to "
                        f"{ep.get('method')} {ep.get('path')} — expected method in {expected}"
                    )
            # Assertion entries each need source
            for a in (step.get("assertions") or []):
                if not isinstance(a, dict) or not a.get("source"):
                    issues.append(
                        f"G13: goal {gid} stage '{stage}' has assertion without source: {a}"
                    )
            # Actor must exist in goal.actors
            actor = step.get("actor")
            if actor and actor_ids and actor not in actor_ids:
                issues.append(
                    f"G13: goal {gid} stage '{stage}' references unknown actor '{actor}'; "
                    f"goal.actors={sorted(actor_ids)}"
                )
    return issues


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _meaningful(value: Any) -> bool:
    if value is None:
        return False
    text = re.sub(r"\s+", " ", str(value).strip()).lower()
    return text not in EMPTY_VALUES and not text.startswith(("none", "n/a", "na"))


def _field(body: str, name: str) -> str:
    patterns = (
        rf"^\*\*{re.escape(name)}:\*\*\s*(.+?)(?=^\*\*|\n##|\n#\s+G-|\Z)",
        rf"^{re.escape(name)}:\s*(.+?)(?=^\w[\w -]*:|\n##|\n#\s+G-|\Z)",
    )
    for pattern in patterns:
        match = re.search(pattern, body, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _parse_goal_block(text: str, source: Path) -> dict[str, Any] | None:
    heading = re.search(r"^#\s+(G-[\w.-]+):?\s*(.+)$", text, re.MULTILINE)
    if not heading:
        heading = re.search(
            r"^##\s+(?:Goal\s+)?(G-[\w.-]+):?\s*(.+)$",
            text,
            re.MULTILINE,
        )
    if not heading:
        return None
    goal_id = heading.group(1).strip()
    title = heading.group(2).strip()
    return {
        "id": goal_id,
        "title": title,
        "body": text,
        "goal_type": _field(text, "goal_type").lower(),
        "goal_class": _field(text, "goal_class").lower(),
        "surface": _field(text, "Surface").lower(),
        "mutation_evidence": _field(text, "Mutation evidence"),
        "persistence_check": _field(text, "Persistence check"),
        "source": str(source),
    }


def _parse_goals(phase_dir: Path) -> list[dict[str, Any]]:
    split_dir = phase_dir / "TEST-GOALS"
    goals: list[dict[str, Any]] = []
    if split_dir.is_dir():
        for path in sorted(split_dir.glob("G-*.md")):
            goal = _parse_goal_block(_read(path), path)
            if goal:
                goals.append(goal)
    if goals:
        return goals

    text = _read(phase_dir / "TEST-GOALS.md")
    pattern = re.compile(
        r"^##\s+(?:Goal\s+)?(G-[\w.-]+):?\s*(.*?)$"
        r"(?P<body>(?:(?!^##\s+(?:Goal\s+)?G-[\w.-]+).)*)",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        body = f"## Goal {match.group(1)}: {match.group(2)}\n{match.group('body') or ''}"
        goal = _parse_goal_block(body, phase_dir / "TEST-GOALS.md")
        if goal:
            goals.append(goal)
    return goals


def _combined(goal: dict[str, Any]) -> str:
    return "\n".join(str(goal.get(k, "")) for k in (
        "title",
        "body",
        "goal_type",
        "goal_class",
        "surface",
        "mutation_evidence",
        "persistence_check",
    ))


# B97 v4.69.0 (issue #201): per-class required stage subset. Pre-B97
# validator enforced full RCRURDR for ANY goal whose evidence was
# meaningful OR SIDE_EFFECT_WORD_RE matched (catches "approve|reject|
# update|delete..." in titles like "Approve queue page renders" — which
# is read-only). Result: 3-stage create-only goals flagged as missing
# update/delete stages → BLOCK. Fix: when goal_class declares non-mutation
# subset, use its declared required-stage subset instead of full RCRURDR.
REQUIRED_STAGES_BY_CLASS: dict[str, tuple[str, ...]] = {
    "readonly":    ("read_before",),
    "read-only":   ("read_before",),
    "create-only": ("read_before", "create", "read_after_create"),
    "update-only": ("read_before", "update", "read_after_update"),
    "delete-only": ("read_before", "delete", "read_after_delete"),
    # B-dogfood (PrintwayV3 P9 2026-07-01): read-family min-required subsets.
    "read-hydrate": ("read_before", "render_initial"),
    "read-ssr-seo": ("read_before", "render_initial"),
    "infra-boot":   ("read_before", "boot_start"),
    "navigation":   ("read_before", "render_initial"),
    "auth-route":   ("read_before", "unauth_redirect"),
}


def _required_stages_for(goal: dict[str, Any], spec: dict[str, Any] | None = None) -> tuple[str, ...]:
    """B97 v4.69.0: explicit goal_class enum dictates required stage subset.

    Returns the stage tuple the validator should enforce for `goal`. Falls
    back to full RCRURDR when goal_class blank/unknown or declares a
    mutation-class value.
    """
    gc = str(goal.get("goal_class") or "").lower().strip()
    # B98: the lifecycle SPEC is the authoritative contract. When the
    # goal-side goal_class is blank (TEST-GOALS commonly omits it), fall back
    # to the spec's declared goal_class before defaulting to full RCRURDR.
    # Pre-B98 read goal-only -> readonly render specs wrongly required
    # create/update/delete stages.
    if gc not in REQUIRED_STAGES_BY_CLASS and spec is not None:
        spec_gc = str(spec.get("goal_class") or "").lower().strip()
        if spec_gc in REQUIRED_STAGES_BY_CLASS:
            gc = spec_gc
    if gc in REQUIRED_STAGES_BY_CLASS:
        return REQUIRED_STAGES_BY_CLASS[gc]
    return REQUIRED_STAGES


def _needs_lifecycle(goal: dict[str, Any]) -> bool:
    goal_type = str(goal.get("goal_type") or "").lower()
    goal_class = str(goal.get("goal_class") or "").lower()
    # B97 v4.69.0 (issue #201): respect explicit non-mutation goal_class.
    # When AI/author declares readonly/create-only/update-only/delete-only,
    # validator should NOT escalate to full RCRURDR check via word-match.
    # Goal still gets per-class required-stage enforcement via
    # _required_stages_for, just not the global REQUIRED_STAGES path.
    if goal_class in {"readonly", "read-only", "create-only", "update-only", "delete-only"}:
        return True  # still validated, but per-class subset (see _required_stages_for)
    if goal_type in {"mutation", "multi-actor", "workflow"}:
        return True
    if goal_class in {"mutation", "crud", "workflow", "multi-actor"}:
        return True
    if _meaningful(goal.get("mutation_evidence")) or _meaningful(goal.get("persistence_check")):
        return True
    return bool(SIDE_EFFECT_WORD_RE.search(_combined(goal)))


def _needs_artifact_capture(goal: dict[str, Any]) -> bool:
    return bool(ARTIFACT_WORD_RE.search(_combined(goal)))


def _is_multi_actor(goal: dict[str, Any]) -> bool:
    return bool(MULTI_ACTOR_WORD_RE.search(_combined(goal)))


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _stage_names(spec: dict[str, Any]) -> set[str]:
    return {
        str(step.get("stage") or step.get("phase") or "").strip()
        for step in _as_list(spec.get("steps"))
        if isinstance(step, dict)
    }


def _fixture_dag_ok(spec: dict[str, Any]) -> bool:
    fixtures = _as_list(spec.get("fixture_dag"))
    if not fixtures:
        return False
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            return False
        if not fixture.get("id") or not fixture.get("kind") or not fixture.get("cleanup"):
            return False
    return True


def _cleanup_ok(spec: dict[str, Any]) -> bool:
    cleanup = _as_list(spec.get("cleanup"))
    if not cleanup:
        return False
    for item in cleanup:
        if not isinstance(item, dict):
            return False
        if not item.get("target") or not item.get("action"):
            return False
    return True


def _add(out: Output, evidence: Evidence, severity: str) -> None:
    if severity == "warn":
        out.warn(evidence)
    else:
        out.add(evidence, escalate=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify lifecycle spec depth before /vg:test")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument("--lifecycle-path", default=None)
    parser.add_argument("--strict", action="store_true",
                        help="G13: escalate semantic issues to BLOCK (default: advisory)")
    args = parser.parse_args()

    out = Output(validator="lifecycle-spec-depth")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        lifecycle_goals = [goal for goal in _parse_goals(phase_dir) if _needs_lifecycle(goal)]
        if not lifecycle_goals:
            emit_and_exit(out)

        lifecycle_path = Path(args.lifecycle_path) if args.lifecycle_path else phase_dir / "LIFECYCLE-SPECS.json"
        if not lifecycle_path.exists():
            for goal in lifecycle_goals[:20]:
                _add(
                    out,
                    Evidence(
                        type="lifecycle_spec_missing",
                        message=f"{goal['id']}: side-effecting goal has no LIFECYCLE-SPECS.json entry",
                        file=goal.get("source"),
                        expected="LIFECYCLE-SPECS.json with goals.<id>.actors, fixture_dag, preconditions, steps, cleanup",
                        fix_hint="Generate lifecycle specs before /vg:test. Repair blueprint/test specs; then rerun /vg:test.",
                    ),
                    args.severity,
                )
            emit_and_exit(out)

        try:
            data = json.loads(_read(lifecycle_path))
        except json.JSONDecodeError as exc:
            _add(
                out,
                Evidence(
                    type="lifecycle_spec_json_invalid",
                    message=f"LIFECYCLE-SPECS.json parse failed: {exc}",
                    file=str(lifecycle_path),
                ),
                args.severity,
            )
            emit_and_exit(out)

        specs = data.get("goals") if isinstance(data, dict) else None
        if not isinstance(specs, dict):
            _add(
                out,
                Evidence(
                    type="lifecycle_spec_shape_invalid",
                    message="LIFECYCLE-SPECS.json must contain object field `goals`",
                    file=str(lifecycle_path),
                    expected='{"goals": {"G-01": {...}}}',
                ),
                args.severity,
            )
            emit_and_exit(out)

        for goal in lifecycle_goals:
            goal_id = goal["id"]
            spec = specs.get(goal_id)
            if not isinstance(spec, dict):
                _add(
                    out,
                    Evidence(
                        type="lifecycle_goal_missing",
                        message=f"{goal_id}: required lifecycle spec missing",
                        file=str(lifecycle_path),
                        expected=f"goals.{goal_id}",
                        fix_hint="Add actors, fixture_dag, preconditions, full RCRURDR steps, artifact_capture when applicable, and cleanup.",
                    ),
                    args.severity,
                )
                continue

            actors = _as_list(spec.get("actors"))
            if not actors:
                _add(
                    out,
                    Evidence(
                        type="actors_missing",
                        message=f"{goal_id}: actors[] missing",
                        file=str(lifecycle_path),
                        expected="actors[] with role/session/permission context",
                    ),
                    args.severity,
                )
            elif _is_multi_actor(goal) and len(actors) < 2:
                _add(
                    out,
                    Evidence(
                        type="multi_actor_matrix_missing",
                        message=f"{goal_id}: multi-actor goal requires at least two actors",
                        file=str(lifecycle_path),
                        expected="actors[] with at least two role/session contexts",
                    ),
                    args.severity,
                )

            if not _fixture_dag_ok(spec):
                _add(
                    out,
                    Evidence(
                        type="fixture_dag_missing",
                        message=f"{goal_id}: fixture_dag must list owned prerequisites and cleanup policy",
                        file=str(lifecycle_path),
                        expected="fixture_dag[] entries with id, kind, cleanup",
                    ),
                    args.severity,
                )

            if not _as_list(spec.get("preconditions")):
                _add(
                    out,
                    Evidence(
                        type="preconditions_missing",
                        message=f"{goal_id}: preconditions[] missing",
                        file=str(lifecycle_path),
                    ),
                    args.severity,
                )

            # B97 v4.69.0 (issue #201): use per-class required subset when
            # explicit goal_class declares non-mutation. Pre-B97 always used
            # full RCRURDR → false positive on 3-stage create-only goals.
            required = _required_stages_for(goal, spec)
            missing = [stage for stage in required if stage not in _stage_names(spec)]
            if missing:
                gc = str(goal.get("goal_class") or "").lower().strip()
                ev_type = "rcrurdr_stages_missing" if required == REQUIRED_STAGES else "class_stages_missing"
                _add(
                    out,
                    Evidence(
                        type=ev_type,
                        message=(
                            f"{goal_id}: lifecycle spec missing "
                            f"{'RCRURDR' if required == REQUIRED_STAGES else gc} "
                            f"stages: {', '.join(missing)}"
                        ),
                        file=str(lifecycle_path),
                        expected=", ".join(required),
                    ),
                    args.severity,
                )

            if _needs_artifact_capture(goal) and not _as_list(spec.get("artifact_capture")):
                _add(
                    out,
                    Evidence(
                        type="artifact_capture_missing",
                        message=f"{goal_id}: emitted/consumed artifact goal requires artifact_capture[]",
                        file=str(lifecycle_path),
                        expected="artifact_capture[] describing capture source, identifier, and consumer step",
                    ),
                    args.severity,
                )

            if not _cleanup_ok(spec):
                _add(
                    out,
                    Evidence(
                        type="cleanup_missing",
                        message=f"{goal_id}: cleanup[] must cover test-owned fixtures/resources",
                        file=str(lifecycle_path),
                        expected="cleanup[] entries with target and action",
                    ),
                    args.severity,
                )

        # G13 Batch 3: semantic checks — advisory mode prints issues; --strict escalates to BLOCK
        semantic_issues = _semantic_checks(data)
        if semantic_issues:
            print("WARN G13 semantic issues:")
            for issue in semantic_issues:
                print(f"  - {issue}")
            if getattr(args, "strict", False):
                for issue in semantic_issues:
                    out.add(Evidence(
                        type="lifecycle_semantic_issue",
                        message=issue,
                        file=str(lifecycle_path),
                    ), escalate=True)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
