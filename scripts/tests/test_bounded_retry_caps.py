"""R6 Task 7 — bounded retry caps in 3 paths.

Three workflows had unbounded adversarial retry loops where any AI hitting
a stubborn gate could burn 200K+ tokens:

  1. scope deep_probe — heuristic "≥5 probes after R5 AND no gray areas"
  2. blueprint crossai remediation — loop until PASS/FLAG
  3. build crossai global — user "continue 6-10" with no upper bound

Each path now has a hard cap from `.claude/vg.config.md`:
  - scope.deep_probe_max=10
  - blueprint.crossai_remediation_max=3
  - build.crossai_global_max=10

On cap exhausted: emit `<workflow>.<path>_max_iter_reached` event +
log_override_debt + refuse loop continuation.

This regression test asserts each of the 3 ref files contains the 3
invariants (event emit, override debt log, config key reference).
Also asserts mirror parity between commands/ and .claude/commands/.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# Ref path, config key, event suffix, debt slug
PATHS = [
    (
        "commands/vg/_shared/scope/discussion-deep-probe.md",
        "scope.deep_probe_max",
        "scope.deep_probe_max_iter_reached",
        "scope-deep-probe-max-iter",
    ),
    (
        "commands/vg/_shared/blueprint/verify.md",
        "blueprint.crossai_remediation_max",
        "blueprint.crossai_remediation_max_iter_reached",
        "blueprint-crossai-remediation-max-iter",
    ),
    (
        "commands/vg/_shared/build/crossai-loop.md",
        "build.crossai_global_max",
        "build.crossai_global_max_iter_reached",
        "build-crossai-global-max-iter",
    ),
]


@pytest.mark.parametrize("ref_rel,config_key,event_name,debt_slug", PATHS)
def test_ref_emits_max_iter_event(ref_rel, config_key, event_name, debt_slug):
    """Each ref must emit `<workflow>.<path>_max_iter_reached` event on cap exhausted."""
    ref = REPO_ROOT / ref_rel
    assert ref.exists(), f"Ref missing: {ref_rel}"
    text = ref.read_text(encoding="utf-8")
    assert event_name in text, (
        f"{ref_rel}: must emit `{event_name}` event when hard cap is reached "
        f"(R6 Task 7 — bounded retry telemetry)"
    )
    # Verify it goes through the canonical orchestrator emit-event path
    assert "emit-event" in text, (
        f"{ref_rel}: cap-exhausted branch must emit via "
        f"`vg-orchestrator emit-event` (canonical telemetry path)"
    )


@pytest.mark.parametrize("ref_rel,config_key,event_name,debt_slug", PATHS)
def test_ref_logs_override_debt(ref_rel, config_key, event_name, debt_slug):
    """Each ref must call log_override_debt with the appropriate slug.

    The debt entry blocks /vg:accept until resolved — this is the audit
    trail for any AI that hit a hard cap (forces ops review, no silent
    burn).
    """
    ref = REPO_ROOT / ref_rel
    text = ref.read_text(encoding="utf-8")
    assert "log_override_debt" in text, (
        f"{ref_rel}: must call `log_override_debt` to log retry-cap debt "
        f"(blocks /vg:accept on unresolved entry)"
    )
    assert debt_slug in text, (
        f"{ref_rel}: log_override_debt must use slug `{debt_slug}` "
        f"(matches override-debt register canonical naming)"
    )


@pytest.mark.parametrize("ref_rel,config_key,event_name,debt_slug", PATHS)
def test_ref_references_config_key(ref_rel, config_key, event_name, debt_slug):
    """Each ref must read the cap from config (not hardcoded).

    Caps are tunable via `.claude/vg.config.md` so projects can adjust
    based on their own AI cost ceiling. Pattern: `vg_config_get <key> <default>`.
    """
    ref = REPO_ROOT / ref_rel
    text = ref.read_text(encoding="utf-8")
    assert config_key in text, (
        f"{ref_rel}: must reference config key `{config_key}` so cap is "
        f"tunable via .claude/vg.config.md (not hardcoded)"
    )
    # The vg_config_get helper is the canonical accessor
    assert "vg_config_get" in text, (
        f"{ref_rel}: must read cap via `vg_config_get` helper (config-loader.md)"
    )


@pytest.mark.parametrize("ref_rel,config_key,event_name,debt_slug", PATHS)
def test_mirror_parity(ref_rel, config_key, event_name, debt_slug):
    """Source ref and .claude/ mirror must be byte-identical.

    Sync invariant: every change to commands/vg/_shared/* must also land
    in .claude/commands/vg/_shared/* — the harness reads from the latter.
    """
    src = REPO_ROOT / ref_rel
    mirror = REPO_ROOT / ".claude" / ref_rel
    assert mirror.exists(), f"Mirror missing: .claude/{ref_rel}"
    assert src.read_bytes() == mirror.read_bytes(), (
        f"Mirror drift: {ref_rel} != .claude/{ref_rel} — re-run mirror sync"
    )


def test_config_template_documents_caps():
    """vg.config.template.md must document all 3 cap keys with defaults.

    Without template documentation, /vg:init projects miss the caps and
    fall back to hardcoded defaults (still safe, but no per-project tuning).
    """
    template = REPO_ROOT / "vg.config.template.md"
    assert template.exists(), "vg.config.template.md missing"
    text = template.read_text(encoding="utf-8")
    assert "deep_probe_max:" in text, "template must document scope.deep_probe_max"
    assert "crossai_remediation_max:" in text, (
        "template must document blueprint.crossai_remediation_max"
    )
    assert "crossai_global_max:" in text, (
        "template must document build.crossai_global_max"
    )
