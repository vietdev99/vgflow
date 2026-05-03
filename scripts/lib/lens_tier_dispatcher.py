"""lens_tier_dispatcher — pick the right model for each lens × goal dispatch.

Reads lens frontmatter (recommended_worker_tier + worker_complexity_score)
and project config (vg.config.md cost_caps). Returns spawn parameters.

Rules (sếp's M1 concern — Haiku capability bounded):
  1. complexity_score >= 4 → require sonnet+ floor (downgrade to sonnet only via
     explicit project override with override-debt entry)
  2. complexity_score == 5 → require opus floor (no downgrade without
     project-level cost_cap override + telemetry justification)
  3. fallback_on_inconclusive: if first spawn returns INCONCLUSIVE, re-spawn
     once at the declared fallback tier.

Cost cap (vg.config.md):
  review:
    cost_caps:
      max_haiku_per_phase: 60
      max_sonnet_per_phase: 20
      max_opus_per_phase: 5
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


_TIER_MODEL = {
    "haiku":  "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-7",
}


@dataclass(frozen=True)
class DispatchTier:
    tier: Literal["haiku", "sonnet", "opus", "crossai"]
    model: str
    fallback_tier: str | None
    override_required: bool


def select_tier(lens_frontmatter: dict, project_cost_caps: dict | None = None) -> DispatchTier:
    """Pick the worker tier for a lens dispatch.

    Capability floor (Codex round 5 + sếp's M1):
    - complexity_score >= 5 forces opus regardless of recommended tier.
    - complexity_score == 4 prevents Haiku — at minimum sonnet.

    Cost cap: when used count >= max_per_phase, override_required=True so the
    spawner can either bump cap or accept skip with override-debt entry.
    """
    project_cost_caps = project_cost_caps or {}
    recommended = lens_frontmatter.get("recommended_worker_tier", "haiku")
    complexity = int(lens_frontmatter.get("worker_complexity_score", 1))
    fallback = lens_frontmatter.get("fallback_on_inconclusive", "none")

    if complexity >= 5 and recommended != "opus":
        recommended = "opus"
    elif complexity >= 4 and recommended == "haiku":
        recommended = "sonnet"

    cap_used = project_cost_caps.get(f"used_{recommended}", 0)
    cap_max = project_cost_caps.get(f"max_{recommended}_per_phase", float("inf"))
    override_required = cap_used >= cap_max

    return DispatchTier(
        tier=recommended,
        model=_TIER_MODEL.get(recommended, _TIER_MODEL["haiku"]),
        fallback_tier=fallback if fallback != "none" else None,
        override_required=override_required,
    )
