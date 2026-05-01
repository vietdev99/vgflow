#!/usr/bin/env python3
"""Validate backend mutation goals (surface=api|data|integration) carry
replay-style evidence (RFC v9 PR-Z).

Browser-only goals are covered by verify-mutation-actually-submitted.py +
verify-evidence-provenance.py. Backend goals don't go through the scanner;
they need a different evidence shape:

Required fields per goal_sequence step (when goal.surface ∈ {api, data,
integration}):
  - replay.method
  - replay.endpoint
  - replay.status (must match expected_status_range from TEST-GOALS)
  - replay.captured_at (ISO 8601)
  - evidence.source ∈ {scanner, executor, diagnostic_l2} (D10 alignment)
  - evidence.artifact_hash (sha256:...)

When goal.surface = data: also require replay.side_effect_resource (e.g.,
a `count_query` result confirming row insertion).

Severity: BLOCK (default) | warn (legacy migration grace).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402

BACKEND_SURFACES = {"api", "data", "integration"}
ALLOWED_SOURCES = {"scanner", "executor", "diagnostic_l2"}


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def parse_goals(text: str) -> list[dict]:
    goals = []
    # v2.46+: tolerate either ## Goal (legacy) OR ### Goal (newer phases
    # like 3.3 which use deeper heading nesting).
    for m in re.finditer(
        r"^#{2,4}\s+Goal\s+(G-[\w.-]+):?\s*(.*?)$"
        r"(?P<body>(?:(?!^#{2,4}\s+Goal\s+).)*)",
        text,
        re.MULTILINE | re.DOTALL,
    ):
        gid = m.group(1)
        body = m.group("body") or ""
        surface_m = re.search(r"\*\*Surface:\*\*\s*(\w+)", body)
        surface = surface_m.group(1).lower() if surface_m else "ui"
        me_m = re.search(
            r"\*\*Mutation evidence:\*\*\s*(.+?)(?=\*\*|\n##|\Z)",
            body,
            re.DOTALL,
        )
        mutation_evidence = me_m.group(1).strip() if me_m else ""
        goals.append({
            "id": gid,
            "surface": surface,
            "is_backend": surface in BACKEND_SURFACES,
            "needs_replay": surface in BACKEND_SURFACES and bool(mutation_evidence),
        })
    return goals


def validate_step(step: dict, gid: str, surface: str) -> list[dict]:
    errors: list[dict] = []
    replay = step.get("replay")
    evidence = step.get("evidence")

    if not isinstance(replay, dict):
        errors.append({
            "type": "replay_missing",
            "gid": gid,
            "issue": "backend mutation step missing `replay` block",
        })
        return errors

    method = str(replay.get("method") or "").upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        errors.append({
            "type": "replay_method_invalid",
            "gid": gid,
            "issue": f"replay.method='{method}' not a mutation verb",
        })

    endpoint = replay.get("endpoint") or ""
    if not endpoint.startswith("/"):
        errors.append({
            "type": "replay_endpoint_invalid",
            "gid": gid,
            "issue": f"replay.endpoint must start with '/', got '{endpoint}'",
        })

    status = replay.get("status")
    try:
        code = int(status)
        if not (200 <= code < 300):
            errors.append({
                "type": "replay_status_not_2xx",
                "gid": gid,
                "issue": f"replay.status={status} not in 200..299",
            })
    except (TypeError, ValueError):
        errors.append({
            "type": "replay_status_missing",
            "gid": gid,
            "issue": f"replay.status non-numeric: {status!r}",
        })

    if not replay.get("captured_at"):
        errors.append({
            "type": "replay_captured_at_missing",
            "gid": gid,
            "issue": "replay.captured_at required (ISO 8601)",
        })

    if surface == "data" and not replay.get("side_effect_resource"):
        errors.append({
            "type": "side_effect_resource_missing",
            "gid": gid,
            "issue": (
                "surface=data step requires replay.side_effect_resource "
                "(e.g., count query result proving row insertion)"
            ),
        })

    # Evidence (RFC v9 D10) — same gate as UI goals
    if not isinstance(evidence, dict):
        errors.append({
            "type": "evidence_missing",
            "gid": gid,
            "issue": "step missing structured evidence object",
        })
        return errors
    source = evidence.get("source")
    if source not in ALLOWED_SOURCES:
        errors.append({
            "type": "evidence_source_invalid_for_backend",
            "gid": gid,
            "issue": (
                f"backend evidence.source='{source}' not in "
                f"{sorted(ALLOWED_SOURCES)} (manual rejected for backend; "
                f"replay must come from automated runner)"
            ),
        })
    if not evidence.get("artifact_hash", "").startswith("sha256:"):
        errors.append({
            "type": "evidence_artifact_hash_invalid",
            "gid": gid,
            "issue": "evidence.artifact_hash missing or not sha256:...",
        })

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify backend mutation evidence (surface=api|data|integration)",
    )
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument(
        "--allow-legacy-surface-probe",
        action="store_true",
        help="Accept goals listed in .legacy-surface-probe.json (pre-RFC v9 "
             "phases that achieved READY/MANUAL via static handler-grep, "
             "before the replay-evidence requirement landed). Use after "
             "running scripts/migrate-backend-surface-probe.py --apply.",
    )
    args = parser.parse_args()

    out = Output(validator="backend-mutation-evidence")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"phase: {args.phase}"))
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        runtime_path = phase_dir / "RUNTIME-MAP.json"
        if not (goals_path.exists() and runtime_path.exists()):
            emit_and_exit(out)

        goals = parse_goals(_read(goals_path))
        try:
            runtime = json.loads(_read(runtime_path))
        except json.JSONDecodeError:
            out.add(Evidence(type="runtime_parse_error", message="parse failure"))
            emit_and_exit(out)
        sequences = runtime.get("goal_sequences") or {}

        # Codex-RFCv9 fix: load legacy-surface-probe manifest if present
        legacy_exempt: set[str] = set()
        manifest_path = phase_dir / ".legacy-surface-probe.json"
        if args.allow_legacy_surface_probe and manifest_path.exists():
            try:
                manifest = json.loads(_read(manifest_path))
                legacy_exempt = {
                    g.get("goal_id") for g in manifest.get("goals") or []
                    if isinstance(g, dict) and g.get("goal_id")
                }
            except json.JSONDecodeError:
                pass

        all_errors: list[dict] = []
        backend_count = 0
        legacy_skipped = 0
        for goal in goals:
            if not goal["needs_replay"]:
                continue
            backend_count += 1
            if goal["id"] in legacy_exempt:
                legacy_skipped += 1
                continue
            seq = sequences.get(goal["id"])
            if not isinstance(seq, dict):
                all_errors.append({
                    "type": "goal_sequence_missing",
                    "gid": goal["id"],
                    "issue": (
                        f"backend goal {goal['id']} has no goal_sequence entry — "
                        f"runner did not record evidence"
                    ),
                })
                continue
            steps = seq.get("steps") or []
            if not steps:
                all_errors.append({
                    "type": "steps_empty",
                    "gid": goal["id"],
                    "issue": "backend goal has empty steps[]",
                })
                continue
            # Validate every mutation-claim step (assume all steps that have
            # replay.method matter — usually 1 per backend goal).
            mutation_steps_seen = 0
            for step in steps:
                if not isinstance(step, dict):
                    continue
                if "replay" not in step and "evidence" not in step:
                    continue  # neutral step (e.g., setup GET)
                mutation_steps_seen += 1
                step_errors = validate_step(step, goal["id"], goal["surface"])
                all_errors.extend(step_errors)
            if mutation_steps_seen == 0:
                all_errors.append({
                    "type": "no_mutation_step",
                    "gid": goal["id"],
                    "issue": "no step carries replay/evidence — backend mutation never recorded",
                })

        out.add(
            Evidence(
                type="backend_summary",
                message=(
                    f"{backend_count} backend mutation goals "
                    f"({legacy_skipped} legacy-surface-probe exempt), "
                    f"{len(all_errors)} errors"
                ),
            ),
            escalate=False,
        )
        for err in all_errors:
            out.add(
                Evidence(
                    type=err["type"],
                    message=f"{err['gid']}: {err['issue']}",
                    file=str(runtime_path),
                    fix_hint=(
                        "Add `replay` + `evidence` to the goal_sequence step. "
                        "Use scripts/runtime/recipe_executor.py to record real "
                        "POST/PUT/PATCH/DELETE traffic, then attach evidence."
                    ),
                ),
                escalate=(args.severity == "block"),
            )

        if all_errors and args.severity == "warn":
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{len(all_errors)} backend mutation issues downgraded to WARN.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
