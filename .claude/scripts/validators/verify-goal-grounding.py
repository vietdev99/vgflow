#!/usr/bin/env python3
"""Verify TEST-GOALS declare goal_grounding ∈ {api, flow, presentation}.

RFC v9 PR-F (2026-05-02). Closes the verification-strategy ambiguity:
without an explicit grounding declaration, /vg:test cannot pick the right
proof shape:

  - api          → recipe_executor + openapi.json + lifecycle.post_state
  - flow         → flow-runner walks FLOW-SPEC checkpoints
  - presentation → screenshot diff + display-computation check

The 3-class split was driven by user observation that "API = nghiệp vụ,
UI = thin client" is true for B2B billing (PrintwayV3 majority) but
NOT for onboarding wizards (flow IS business) or dashboards (UI computes
display from API raw data — extra fields are real, not phantom).

Severity:
  block — default for new phases (post-2026-05-01)
  warn  — pre-2026-05-01 phases (grandfathered; backfill via inference)

Inference fallback (when goal_grounding missing):
  surface=api|data|integration → api
  surface=ui + flow_ref present → flow
  surface=ui + title contains preview|dashboard|chart|report → presentation
  else → api (conservative default — most goals are API-grounded)

In WARN mode the validator emits inferred values + a backfill suggestion
but doesn't block.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402


GROUNDING_VALUES = ("api", "flow", "presentation")
PRESENTATION_KEYWORDS = (
    "preview", "dashboard", "chart", "report", "graph", "summary view",
    "analytics", "metric", "widget",
)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_goals(text: str) -> list[dict]:
    out: list[dict] = []
    parts = re.split(
        r"(?m)^(#{2,4}\s+(?:Goal\s+)?(G-[\w.-]+).*?)$",
        text,
    )
    for i in range(1, len(parts), 3):
        heading = parts[i]
        gid = parts[i + 1]
        body = parts[i + 2] if i + 2 < len(parts) else ""
        title_m = re.match(
            r"#{2,4}\s+(?:Goal\s+)?G-[\w.-]+(?:[:\s—–-]+)\s*(.+)$",
            heading,
        )
        surface_m = re.search(r"\*\*Surface:\*\*\s*([\w-]+)", body)
        # goal_grounding may appear as `**Goal grounding:** api` (markdown)
        # OR `goal_grounding: api` (yaml frontmatter)
        grounding_m = re.search(
            r"(?:\*\*Goal\s+grounding:\*\*|^\s*goal_grounding\s*:)\s*"
            r"([\w]+)",
            body, re.IGNORECASE | re.MULTILINE,
        )
        flow_ref_m = re.search(
            r"(?:\*\*Flow\s+ref:\*\*|^\s*flow_ref\s*:)\s*([\S]+)",
            body, re.IGNORECASE | re.MULTILINE,
        )
        out.append({
            "id": gid,
            "title": (title_m.group(1).strip() if title_m else "").strip(),
            "surface": (surface_m.group(1).lower() if surface_m else ""),
            "goal_grounding": (
                grounding_m.group(1).lower() if grounding_m else None
            ),
            "flow_ref": (flow_ref_m.group(1) if flow_ref_m else None),
        })
    return out


def infer_grounding(goal: dict) -> str:
    surface = goal.get("surface") or ""
    title = (goal.get("title") or "").lower()
    if surface in ("api", "data", "integration", "time-driven"):
        return "api"
    if goal.get("flow_ref"):
        return "flow"
    if any(k in title for k in PRESENTATION_KEYWORDS):
        return "presentation"
    return "api"  # conservative default


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify TEST-GOALS declare goal_grounding (RFC v9 PR-F)",
    )
    parser.add_argument("--phase", required=True)
    parser.add_argument(
        "--severity", choices=["block", "warn"], default="block",
    )
    parser.add_argument(
        "--allow-grounding-gaps", action="store_true",
        help="Override: allow missing/inferred values without WARN",
    )
    args = parser.parse_args()

    out = Output(validator="goal-grounding")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found",
                             message=f"phase: {args.phase}"))
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        if not goals_path.exists():
            emit_and_exit(out)

        goals = parse_goals(_read(goals_path))
        if not goals:
            emit_and_exit(out)

        missing: list[dict] = []
        invalid: list[dict] = []
        by_grounding = {"api": 0, "flow": 0, "presentation": 0}

        for g in goals:
            declared = g.get("goal_grounding")
            if declared is None:
                inferred = infer_grounding(g)
                missing.append({**g, "inferred": inferred})
                by_grounding[inferred] += 1
            elif declared not in GROUNDING_VALUES:
                invalid.append(g)
            else:
                by_grounding[declared] += 1

        out.add(
            Evidence(
                type="grounding_summary",
                message=(
                    f"goal_grounding distribution across {len(goals)} goals: "
                    f"api={by_grounding['api']}, flow={by_grounding['flow']}, "
                    f"presentation={by_grounding['presentation']} "
                    f"({len(missing)} inferred, {len(invalid)} invalid)"
                ),
            ),
            escalate=False,
        )

        for g in missing:
            out.add(
                Evidence(
                    type="goal_grounding_missing",
                    message=(
                        f"{g['id']}: missing goal_grounding declaration "
                        f"(inferred '{g['inferred']}' from "
                        f"surface='{g.get('surface') or '?'}', "
                        f"title='{g.get('title','')[:40]}')"
                    ),
                    file=str(goals_path),
                    fix_hint=(
                        f"Add `**Goal grounding:** {g['inferred']}` to "
                        f"goal {g['id']} body (or `goal_grounding: "
                        f"{g['inferred']}` in YAML frontmatter)."
                    ),
                ),
                escalate=(args.severity == "block" and not args.allow_grounding_gaps),
            )

        for g in invalid:
            out.add(
                Evidence(
                    type="goal_grounding_invalid",
                    message=(
                        f"{g['id']}: goal_grounding="
                        f"'{g.get('goal_grounding')}' "
                        f"not in {{api, flow, presentation}}"
                    ),
                    file=str(goals_path),
                    fix_hint=(
                        f"Use one of: api (B2B billing/orders/payments), "
                        f"flow (multi-step wizards), presentation "
                        f"(dashboards/charts/previews)."
                    ),
                ),
                escalate=(args.severity == "block" and not args.allow_grounding_gaps),
            )

        # WARN downgrade — emit summary fix path
        if (missing or invalid) and (
            args.severity == "warn" or args.allow_grounding_gaps
        ):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=(
                        f"Pre-2026-05-01 grandfather: {len(missing)} missing + "
                        f"{len(invalid)} invalid downgraded to WARN. Backfill "
                        f"via fix-hints above before next /vg:blueprint."
                    ),
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
