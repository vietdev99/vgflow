"""
Bootstrap outcome tracking (Gap 3) — efficacy surgical in-place update.

Before: cmd_efficacy only wrote to .efficacy-log.md; ACCEPTED.md stayed at
`hits: 0` forever. Self-learning system was mute — couldn't prove rules
affected behavior.

After: --apply mutates the rule block in ACCEPTED.md to reflect real
hits/hit_outcomes from events.jsonl + events.db.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HYGIENE = REPO_ROOT / ".claude" / "scripts" / "bootstrap-hygiene.py"


def _setup_bootstrap_fixture(tmp_path: Path):
    """Create minimal .vg/bootstrap/ with ACCEPTED.md + a rule-fired event."""
    bs = tmp_path / ".vg" / "bootstrap"
    bs.mkdir(parents=True)
    accepted = bs / "ACCEPTED.md"
    accepted.write_text(
        """# Bootstrap Accepted

- id: L-001
  promoted_at: 2026-04-20T07:00:00Z
  promoted_by: user
  type: rule
  target:
    file: rules/example.md
  reason: "test rule"
  origin: reflector.phase.13
  status: active
  hits: 0
  hit_outcomes:
    success_count: 0
    fail_count: 0
  last_hit: null

- id: L-002
  promoted_at: 2026-04-21T07:00:00Z
  promoted_by: user
  type: rule
  target:
    file: rules/other.md
  reason: "another rule"
  status: active
  hits: 0
  hit_outcomes:
    success_count: 0
    fail_count: 0
  last_hit: null
""",
        encoding="utf-8",
    )

    # Fake telemetry.jsonl with L-001 fired 3 times (2 success, 1 fail),
    # L-002 fired 1 time (1 success).
    planning = tmp_path / ".vg"
    events = planning / "telemetry.jsonl"
    records = [
        {"event_type": "bootstrap.rule_fired", "payload": {"rule_id": "L-001",
         "phase": "7.6"}, "outcome": ""},
        {"event_type": "bootstrap.rule_fired", "payload": {"rule_id": "L-001",
         "phase": "7.7"}, "outcome": ""},
        {"event_type": "bootstrap.rule_fired", "payload": {"rule_id": "L-001",
         "phase": "7.8"}, "outcome": ""},
        {"event_type": "bootstrap.outcome_recorded", "payload": {"rule_id": "L-001",
         "phase": "7.6", "outcome": "success"}, "outcome": ""},
        {"event_type": "bootstrap.outcome_recorded", "payload": {"rule_id": "L-001",
         "phase": "7.7", "outcome": "success"}, "outcome": ""},
        {"event_type": "bootstrap.outcome_recorded", "payload": {"rule_id": "L-001",
         "phase": "7.8", "outcome": "fail"}, "outcome": ""},
        {"event_type": "bootstrap.rule_fired", "payload": {"rule_id": "L-002",
         "phase": "7.9"}, "outcome": ""},
        {"event_type": "bootstrap.outcome_recorded", "payload": {"rule_id": "L-002",
         "phase": "7.9", "outcome": "success"}, "outcome": ""},
    ]
    events.write_text(
        "\n".join(json.dumps(r) for r in records),
        encoding="utf-8",
    )
    return tmp_path, accepted


def test_efficacy_dry_run_no_mutation(tmp_path):
    """Without --apply, ACCEPTED.md must stay untouched."""
    cwd, accepted = _setup_bootstrap_fixture(tmp_path)
    before = accepted.read_text(encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(HYGIENE), "efficacy"],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, f"efficacy failed:\n{r.stdout}\n{r.stderr}"
    # Dry-run should leave ACCEPTED.md bytewise identical
    assert accepted.read_text(encoding="utf-8") == before


def test_efficacy_apply_updates_hits(tmp_path):
    """--apply mutates L-001 hits: 0 → 3, success_count: 0 → 2, fail_count: 0 → 1."""
    cwd, accepted = _setup_bootstrap_fixture(tmp_path)

    r = subprocess.run(
        [sys.executable, str(HYGIENE), "efficacy", "--apply"],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, f"efficacy failed:\n{r.stdout}\n{r.stderr}"

    after = accepted.read_text(encoding="utf-8")

    # L-001 should have hits: 3
    import re
    l1_block = re.search(r"- id:\s*L-001\b(.+?)(?=^- id:|\Z)",
                         after, re.DOTALL | re.MULTILINE)
    assert l1_block, "L-001 block missing after --apply"
    l1_text = l1_block.group(1)
    assert re.search(r"\bhits:\s*3\b", l1_text), f"L-001 hits not updated:\n{l1_text}"
    assert re.search(r"\bsuccess_count:\s*2\b", l1_text), \
        f"L-001 success_count not updated:\n{l1_text}"
    assert re.search(r"\bfail_count:\s*1\b", l1_text), \
        f"L-001 fail_count not updated:\n{l1_text}"
    # last_hit should be ISO timestamp (not null anymore)
    assert "last_hit: null" not in l1_text
    assert re.search(r"\blast_hit:\s*20\d\d-", l1_text), \
        f"L-001 last_hit not updated:\n{l1_text}"


def test_efficacy_apply_handles_multiple_rules(tmp_path):
    """L-002 fired once → hits: 1, success_count: 1."""
    cwd, accepted = _setup_bootstrap_fixture(tmp_path)

    subprocess.run(
        [sys.executable, str(HYGIENE), "efficacy", "--apply"],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
    )

    after = accepted.read_text(encoding="utf-8")
    import re
    l2_block = re.search(r"- id:\s*L-002\b(.+?)(?=^- id:|\Z)",
                         after, re.DOTALL | re.MULTILINE)
    assert l2_block, "L-002 block missing"
    l2_text = l2_block.group(1)
    assert re.search(r"\bhits:\s*1\b", l2_text), f"L-002 hits not updated:\n{l2_text}"
    assert re.search(r"\bsuccess_count:\s*1\b", l2_text), \
        f"L-002 success_count not updated:\n{l2_text}"


def test_efficacy_writes_audit_log(tmp_path):
    """--apply also appends to .efficacy-log.md for audit trail."""
    cwd, accepted = _setup_bootstrap_fixture(tmp_path)

    subprocess.run(
        [sys.executable, str(HYGIENE), "efficacy", "--apply"],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
    )

    log = tmp_path / ".vg" / "bootstrap" / ".efficacy-log.md"
    assert log.exists(), "audit log not created"
    content = log.read_text(encoding="utf-8")
    assert "L-001" in content
    assert "hits 0 → 3" in content or "hits 0 -> 3" in content  # unicode arrow


def test_efficacy_empty_events_no_op(tmp_path):
    """No events → no changes, no crash."""
    bs = tmp_path / ".vg" / "bootstrap"
    bs.mkdir(parents=True)
    accepted = bs / "ACCEPTED.md"
    accepted.write_text(
        "# Bootstrap Accepted\n\n- id: L-001\n  status: active\n  hits: 0\n",
        encoding="utf-8",
    )
    (tmp_path / ".vg" / "telemetry.jsonl").write_text("", encoding="utf-8")
    before = accepted.read_text(encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(HYGIENE), "efficacy", "--apply"],
        cwd=str(tmp_path), capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0
    assert accepted.read_text(encoding="utf-8") == before


def test_efficacy_idempotent(tmp_path):
    """Running --apply twice on same data = same result (no double-increment)."""
    cwd, accepted = _setup_bootstrap_fixture(tmp_path)

    subprocess.run(
        [sys.executable, str(HYGIENE), "efficacy", "--apply"],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
    )
    after_first = accepted.read_text(encoding="utf-8")

    subprocess.run(
        [sys.executable, str(HYGIENE), "efficacy", "--apply"],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
    )
    after_second = accepted.read_text(encoding="utf-8")

    # Content identical (timestamps may differ but rule blocks should match)
    import re
    def normalize(t):
        return re.sub(r"last_hit:\s*[^\n]+", "last_hit: <ts>", t)

    assert normalize(after_first) == normalize(after_second), \
        "efficacy not idempotent"
