"""R6 Task 10 — per-lens dispatch telemetry.

Asserts:
- scripts/spawn_recursive_probe.py emits review.lens.{lens}.dispatched event
- scripts/spawn_recursive_probe.py emits review.lens.{lens}.completed event
- scripts/spawn_recursive_probe.py emits review.lens.{lens}.crashed event
  (handles crash path: timeout + missing-binary)
- commands/vg/review.md must_emit_telemetry contract enumerates ≥3 per-lens
  event entries (representative critical lenses) so Stop hook can detect
  silent skip without hard-blocking.

Why: review.lens_plan_generated proves a plan was BUILT, but not that each
individual lens was DISPATCHED. Per-lens events close the silent-skip gap
("plan listed lens-idor but worker never spawned").
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPAWN_SCRIPT = REPO_ROOT / "scripts" / "spawn_recursive_probe.py"
REVIEW_MD = REPO_ROOT / "commands" / "vg" / "review.md"


def test_spawn_script_emits_lens_dispatched_event() -> None:
    """spawn_one_worker must emit review.lens.{lens}.dispatched BEFORE the
    subprocess.run call so silent skips (worker never reaches subprocess) are
    still detectable by Stop hook."""
    text = SPAWN_SCRIPT.read_text(encoding="utf-8")
    assert 'f"review.lens.{lens}.dispatched"' in text, (
        "spawn_recursive_probe.py must emit `review.lens.{lens}.dispatched` "
        "before each lens worker spawn (R6 Task 10). Without this event, "
        "Stop hook cannot distinguish 'lens dispatched but crashed silently' "
        "from 'lens never dispatched at all'."
    )


def test_spawn_script_emits_lens_completed_event() -> None:
    """spawn_one_worker must emit review.lens.{lens}.completed on the success
    path (subprocess.run returned)."""
    text = SPAWN_SCRIPT.read_text(encoding="utf-8")
    assert 'f"review.lens.{lens}.completed"' in text, (
        "spawn_recursive_probe.py must emit `review.lens.{lens}.completed` "
        "after subprocess.run returns (R6 Task 10). Pairs with .dispatched "
        "to prove the worker ran end-to-end."
    )


def test_spawn_script_emits_lens_crashed_event() -> None:
    """spawn_one_worker must emit review.lens.{lens}.crashed on timeout +
    missing-binary error paths so silent dies are observable."""
    text = SPAWN_SCRIPT.read_text(encoding="utf-8")
    crashed_count = text.count('f"review.lens.{lens}.crashed"')
    assert crashed_count >= 2, (
        f"spawn_recursive_probe.py must emit `review.lens.{{lens}}.crashed` "
        f"on BOTH timeout AND FileNotFoundError paths (R6 Task 10) — found "
        f"{crashed_count} occurrence(s), expected ≥2. Otherwise crashes leak "
        f"silently as plain return values without telemetry trail."
    )


def test_spawn_script_lens_events_use_phase_dir() -> None:
    """Per-lens events must include phase_dir so Stop hook can scope its
    silent-skip detection to the current phase."""
    text = SPAWN_SCRIPT.read_text(encoding="utf-8")
    # Look for the dispatched emit_event call body — phase_dir=phase_dir
    # should appear inside the same emit_event(...) invocation.
    idx = text.find('f"review.lens.{lens}.dispatched"')
    assert idx >= 0, "dispatched event not found (covered by earlier test)"
    # Capture the next ~400 chars and require phase_dir keyword in the call
    window = text[idx : idx + 600]
    assert "phase_dir=phase_dir" in window, (
        "review.lens.{lens}.dispatched emit_event call must pass "
        "phase_dir=phase_dir kwarg so the event is scoped to the phase. "
        "Without it the telemetry log loses the phase correlation needed "
        "by /vg:telemetry and the Stop hook silent-skip scan."
    )


def test_review_md_contract_documents_per_lens_telemetry() -> None:
    """commands/vg/review.md must_emit_telemetry must enumerate ≥3 per-lens
    event patterns so the contract surface (and grep-based audits) document
    that per-lens telemetry is part of the review contract.

    We don't enumerate all 19 lenses × 3 events — that's ~57 entries. Instead,
    pick 3 representative critical lenses (lens-idor for IDOR/BOLA,
    lens-business-coherence for state-mismatch, lens-form-lifecycle for CRUD
    coverage) — the rest follow the same pattern at runtime.
    """
    text = REVIEW_MD.read_text(encoding="utf-8")
    # Count distinct review.lens.<name>.<verb> entries declared in the
    # must_emit_telemetry array. Match lines like
    #   - event_type: "review.lens.lens-idor.dispatched"
    import re
    entries = re.findall(
        r'event_type:\s*"review\.lens\.lens-[a-z-]+\.(?:dispatched|completed|crashed)"',
        text,
    )
    assert len(entries) >= 3, (
        f"commands/vg/review.md must_emit_telemetry must enumerate ≥3 "
        f"per-lens event entries (review.lens.<lens>.<verb>) — found "
        f"{len(entries)}. R6 Task 10 requires the contract to document the "
        f"per-lens telemetry surface so silent skips of canonical lenses "
        f"are detected by the Stop hook."
    )


def test_review_md_contract_per_lens_severity_is_warn() -> None:
    """Per-lens telemetry entries should be severity:warn — silent skip is
    surfaced as a contract.telemetry_warn event without hard-blocking the
    run (lens may be legitimately filtered by env_policy or mutation budget)."""
    text = REVIEW_MD.read_text(encoding="utf-8")
    import re
    # Find each per-lens event_type line with the next ~200 chars of context
    # and check that severity: "warn" appears within that window before the
    # next event_type entry.
    blocks = re.split(r'(?=event_type:\s*"review\.lens\.lens-)', text)
    per_lens_blocks = [
        b for b in blocks
        if re.match(r'event_type:\s*"review\.lens\.lens-', b)
    ]
    assert per_lens_blocks, "no per-lens contract blocks found (covered by earlier test)"
    for block in per_lens_blocks:
        # Truncate at the next contract entry boundary
        head = re.split(r'\n\s*-\s+event_type:|\n\s*forbidden_without_override:|\n---\n',
                         block, maxsplit=1)[0]
        assert 'severity: "warn"' in head, (
            f"Per-lens contract entry missing severity: \"warn\":\n"
            f"  {head[:120]!r}\n"
            f"Use warn so silent skip surfaces a telemetry_warn event "
            f"without hard-blocking (env_policy + mutation budget can "
            f"legitimately filter individual lenses)."
        )
