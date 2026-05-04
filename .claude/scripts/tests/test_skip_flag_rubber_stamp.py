"""Regression tests for check_skip_flag_rubber_stamp (v2.5.2.10).

Observed in phase 7.14 → 7.15 → 7.16: reason "UI-only no API change,
CrossAI marginal value" copy-pasted verbatim across 3 phases. Each entry
passed proof gate (cited prior commit SHA) but the pattern was unchecked
end-to-end. Guard added to vg-orchestrator cmd_override catches this.

Cases:
  - Same reason + different phases ≥ threshold → rubber_stamp True
  - Same reason but all on same phase → NOT rubber_stamp (single-phase debt is OK)
  - Different reasons across phases → NOT rubber_stamp
  - Different flag across phases → NOT rubber_stamp
  - Below threshold → NOT rubber_stamp
  - Empty event list → NOT rubber_stamp
  - Current phase excluded from match count (re-running same phase is fine)
"""
import sys
from pathlib import Path

# Make vg-orchestrator package importable regardless of cwd
_ORCH_DIR = Path(__file__).resolve().parents[1] / "vg-orchestrator"
if str(_ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCH_DIR))

import allow_flag_gate as gate  # type: ignore


def _mk_event(flag: str, reason: str, phase: str, event_type: str = "override.used"):
    return {
        "event_type": event_type,
        "phase": phase,
        "payload": {"flag": flag, "reason": reason},
    }


SKIP_FLAG = "--skip-crossai"
RUBBER_REASON = (
    "UI-only no API change, CrossAI marginal value. "
    "See commit abc1234 for precedent from phase 7.13."
)


class TestSkipFlagRubberStamp:
    def test_same_reason_different_phases_over_threshold_blocks(self):
        events = [
            _mk_event(SKIP_FLAG, RUBBER_REASON, "7.14"),
            _mk_event(SKIP_FLAG, RUBBER_REASON, "7.15"),
            _mk_event(SKIP_FLAG, RUBBER_REASON, "7.16"),
        ]
        hit, count, phases = gate.check_skip_flag_rubber_stamp(
            events, SKIP_FLAG, RUBBER_REASON, "7.17", threshold=2
        )
        assert hit is True
        assert count == 3
        assert set(phases) == {"7.14", "7.15", "7.16"}

    def test_exactly_at_threshold_blocks(self):
        events = [
            _mk_event(SKIP_FLAG, RUBBER_REASON, "7.14"),
            _mk_event(SKIP_FLAG, RUBBER_REASON, "7.15"),
        ]
        hit, count, phases = gate.check_skip_flag_rubber_stamp(
            events, SKIP_FLAG, RUBBER_REASON, "7.17", threshold=2
        )
        assert hit is True
        assert count == 2

    def test_below_threshold_passes(self):
        events = [_mk_event(SKIP_FLAG, RUBBER_REASON, "7.14")]
        hit, count, phases = gate.check_skip_flag_rubber_stamp(
            events, SKIP_FLAG, RUBBER_REASON, "7.17", threshold=2
        )
        assert hit is False
        assert count == 1

    def test_current_phase_excluded_from_count(self):
        # User re-running the same phase with same reason shouldn't trigger
        # rubber-stamp. Only cross-phase pattern matters.
        events = [
            _mk_event(SKIP_FLAG, RUBBER_REASON, "7.17"),
            _mk_event(SKIP_FLAG, RUBBER_REASON, "7.17"),
            _mk_event(SKIP_FLAG, RUBBER_REASON, "7.17"),
        ]
        hit, count, phases = gate.check_skip_flag_rubber_stamp(
            events, SKIP_FLAG, RUBBER_REASON, "7.17", threshold=2
        )
        assert hit is False
        assert count == 0
        assert phases == []

    def test_different_reasons_across_phases_pass(self):
        events = [
            _mk_event(SKIP_FLAG, "Phase 7.14: dev blocker, commit abc1234",
                      "7.14"),
            _mk_event(SKIP_FLAG, "Phase 7.15: different blocker, commit def5678",
                      "7.15"),
        ]
        hit, count, phases = gate.check_skip_flag_rubber_stamp(
            events, SKIP_FLAG,
            "Phase 7.17: yet another distinct reason, commit 9abcdef",
            "7.17", threshold=2,
        )
        assert hit is False
        assert count == 0

    def test_different_flag_not_matched(self):
        events = [
            _mk_event("--skip-design-check", RUBBER_REASON, "7.14"),
            _mk_event("--skip-design-check", RUBBER_REASON, "7.15"),
        ]
        hit, count, _ = gate.check_skip_flag_rubber_stamp(
            events, SKIP_FLAG, RUBBER_REASON, "7.17", threshold=2
        )
        assert hit is False
        assert count == 0

    def test_empty_events_pass(self):
        hit, count, phases = gate.check_skip_flag_rubber_stamp(
            [], SKIP_FLAG, RUBBER_REASON, "7.17", threshold=2
        )
        assert hit is False
        assert count == 0
        assert phases == []

    def test_wrong_event_type_ignored(self):
        events = [
            {"event_type": "allow_flag.used", "phase": "7.14",
             "payload": {"flag": SKIP_FLAG, "reason": RUBBER_REASON}},
            {"event_type": "allow_flag.used", "phase": "7.15",
             "payload": {"flag": SKIP_FLAG, "reason": RUBBER_REASON}},
        ]
        hit, count, _ = gate.check_skip_flag_rubber_stamp(
            events, SKIP_FLAG, RUBBER_REASON, "7.17", threshold=2
        )
        # Only override.used events count — allow_flag.used is different gate
        assert hit is False
        assert count == 0

    def test_whitespace_normalization_matches_same_fingerprint(self):
        # Reason with extra whitespace should match fingerprint of compact form
        events = [
            _mk_event(SKIP_FLAG, RUBBER_REASON, "7.14"),
            _mk_event(SKIP_FLAG, "  " + RUBBER_REASON.replace(" ", "  "),
                      "7.15"),
        ]
        hit, count, _ = gate.check_skip_flag_rubber_stamp(
            events, SKIP_FLAG, RUBBER_REASON, "7.17", threshold=2
        )
        # _reason_head() normalizes whitespace — both events should
        # produce the same fingerprint
        assert hit is True
        assert count == 2

    def test_json_string_payload_parsed(self):
        # Some SQL backends return payload as JSON string — function should
        # parse it
        import json as jsonlib
        events = [
            {"event_type": "override.used", "phase": "7.14",
             "payload": jsonlib.dumps(
                 {"flag": SKIP_FLAG, "reason": RUBBER_REASON})},
            {"event_type": "override.used", "phase": "7.15",
             "payload": jsonlib.dumps(
                 {"flag": SKIP_FLAG, "reason": RUBBER_REASON})},
        ]
        hit, count, _ = gate.check_skip_flag_rubber_stamp(
            events, SKIP_FLAG, RUBBER_REASON, "7.17", threshold=2
        )
        assert hit is True
        assert count == 2
