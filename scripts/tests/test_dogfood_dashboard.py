"""
VG v2.6 Phase E — dogfood-dashboard.py regression tests.

8 cases per PLAN-REVISED.md §Phase E work item #6:
  1. Empty events.jsonl → "no data" state, no crash
  2. Sample events → autonomy panel computed correctly
  3. Override events grouped by phase + reason
  4. Friction time aggregated per skill
  5. Shadow correctness pulled from bootstrap.shadow_prediction events
  6. Quarantine CLI --json subprocess returns parseable JSON (mocked)
  7. --lookback-phases N truncates older events
  8. HTML output is valid (DOCTYPE, no unclosed tags, placeholders gone)

All tests use VG_REPO_ROOT scoped to tmp_path; the script is imported in-process
via importlib so we get full Python coverage without subprocess flakiness.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "dogfood-dashboard.py"
)
TEMPLATE_SRC = (
    Path(__file__).resolve().parents[2]
    / "commands" / "vg" / "_shared" / "templates" / "dashboard-template.html"
)


@pytest.fixture
def dashboard(monkeypatch, tmp_path):
    """Import dogfood-dashboard.py with VG_REPO_ROOT scoped to tmp_path.

    Stages:
      - Build the .claude/commands/vg/_shared/templates skeleton
      - Copy real dashboard-template.html in (so renderer has placeholders)
      - Pre-create empty .vg/events.jsonl + .vg/ dir
      - Import the script as a module under sys.modules
    """
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    (tmp_path / ".vg").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg" / "events.jsonl").write_text("", encoding="utf-8")
    template_dst = (
        tmp_path / ".claude" / "commands" / "vg" / "_shared" / "templates"
    )
    template_dst.mkdir(parents=True, exist_ok=True)
    if TEMPLATE_SRC.exists():
        (template_dst / "dashboard-template.html").write_text(
            TEMPLATE_SRC.read_text(encoding="utf-8"), encoding="utf-8"
        )
    # Create stub orchestrator so subprocess fall back gracefully
    (tmp_path / ".claude" / "scripts").mkdir(parents=True, exist_ok=True)

    # Force re-import so module-level _repo_root() picks up new VG_REPO_ROOT
    sys.modules.pop("dogfood_dashboard", None)
    spec = importlib.util.spec_from_file_location(
        "dogfood_dashboard", str(SCRIPT_PATH)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules["dogfood_dashboard"] = module
    return module


def _write_events(tmp_path: Path, events: list[dict]) -> Path:
    p = tmp_path / ".vg" / "events.jsonl"
    p.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    return p


def _stub_quarantine_empty():
    """Replace fetch_quarantine_state with empty result so subprocess won't fire."""
    return patch(
        "dogfood_dashboard.fetch_quarantine_state",
        return_value={
            "schema": "quarantine.status.v1",
            "total": 0,
            "entries": [],
            "disabled_count": 0,
            "stale_unquarantinable": [],
        },
    )


# ────────────────────────── Case 1 ────────────────────────────────────────

def test_case1_empty_events_renders_no_data(dashboard, tmp_path):
    """Empty events.jsonl → renders with 'no data' state, no crash."""
    output = tmp_path / ".vg" / "dashboard.html"
    with _stub_quarantine_empty():
        summary = dashboard.build_dashboard([], lookback=10, output_path=output)

    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    # Empty-state messages MUST be visible
    assert "No events in lookback window" in content
    assert "No override.used events" in content
    assert summary["events_scanned"] == 0
    assert summary["phases_in_autonomy"] == 0


# ────────────────────────── Case 2 ────────────────────────────────────────

def test_case2_autonomy_pct_computed(dashboard, tmp_path):
    """4 events / 1 human → 75% autonomy for phase 7.6."""
    events = [
        {"phase": "7.6", "event_type": "step.started", "ts": "2026-04-25T10:00:00Z"},
        {"phase": "7.6", "event_type": "step.complete", "ts": "2026-04-25T10:01:00Z"},
        {"phase": "7.6", "event_type": "validator.passed", "ts": "2026-04-25T10:02:00Z"},
        {"phase": "7.6", "event_type": "override.used", "ts": "2026-04-25T10:03:00Z",
         "payload": {"reason": "manual-bypass"}},
    ]
    rows = dashboard.aggregate_autonomy(events)
    assert len(rows) == 1
    r = rows[0]
    assert r["phase"] == "7.6"
    assert r["total_events"] == 4
    assert r["human_events"] == 1
    assert r["autonomy_pct"] == pytest.approx(75.0)


# ────────────────────────── Case 3 ────────────────────────────────────────

def test_case3_overrides_grouped_by_phase_and_reason(dashboard, tmp_path):
    """Override.used events bucket by phase, top-5 reason histogram."""
    events = [
        {"phase": "7.6", "event_type": "override.used",
         "payload": {"reason": "ci-broken"}},
        {"phase": "7.6", "event_type": "override.used",
         "payload": {"reason": "ci-broken"}},
        {"phase": "7.6", "event_type": "override.used",
         "payload": {"reason": "doc-only"}},
        {"phase": "8.0", "event_type": "override.used",
         "payload": {"reason": "infra-flake"}},
        {"phase": "7.6", "event_type": "step.complete"},  # ignored
    ]
    rows = dashboard.aggregate_override(events)
    by_phase = {r["phase"]: r for r in rows}
    assert by_phase["7.6"]["count"] == 3
    assert by_phase["8.0"]["count"] == 1
    # ci-broken should be most common in 7.6
    top_reason, top_count = by_phase["7.6"]["top_reasons"][0]
    assert top_reason == "ci-broken"
    assert top_count == 2


# ────────────────────────── Case 4 ────────────────────────────────────────

def test_case4_friction_per_skill(dashboard, tmp_path):
    """Friction = (complete_ts - started_ts) keyed by run_id+command+step."""
    events = [
        {"run_id": "r1", "command": "vg:build", "step": "s1",
         "event_type": "step.started", "ts": "2026-04-25T10:00:00Z"},
        {"run_id": "r1", "command": "vg:build", "step": "s1",
         "event_type": "step.complete", "ts": "2026-04-25T10:00:30Z"},
        {"run_id": "r2", "command": "vg:build", "step": "s2",
         "event_type": "step.started", "ts": "2026-04-25T11:00:00Z"},
        {"run_id": "r2", "command": "vg:build", "step": "s2",
         "event_type": "step.complete", "ts": "2026-04-25T11:00:10Z"},
        {"run_id": "r3", "command": "vg:test", "step": "t1",
         "event_type": "step.started", "ts": "2026-04-25T12:00:00Z"},
        {"run_id": "r3", "command": "vg:test", "step": "t1",
         "event_type": "step.complete", "ts": "2026-04-25T12:01:00Z"},
    ]
    rows = dashboard.aggregate_friction(events)
    by_skill = {r["skill"]: r for r in rows}
    # vg:build: avg of 30s and 10s = 20s
    assert by_skill["vg:build"]["n"] == 2
    assert by_skill["vg:build"]["avg_s"] == pytest.approx(20.0)
    # vg:test: single 60s sample
    assert by_skill["vg:test"]["n"] == 1
    assert by_skill["vg:test"]["avg_s"] == pytest.approx(60.0)


# ────────────────────────── Case 5 ────────────────────────────────────────

def test_case5_shadow_correctness_per_rule(dashboard, tmp_path):
    """bootstrap.shadow_prediction events: correctness = predicted == actual."""
    events = [
        {"event_type": "bootstrap.shadow_prediction",
         "payload": {"rule_id": "R-AUTH", "predicted_outcome": "BLOCK",
                     "actual_outcome": "BLOCK"}},
        {"event_type": "bootstrap.shadow_prediction",
         "payload": {"rule_id": "R-AUTH", "predicted_outcome": "BLOCK",
                     "actual_outcome": "BLOCK"}},
        {"event_type": "bootstrap.shadow_prediction",
         "payload": {"rule_id": "R-AUTH", "predicted_outcome": "PASS",
                     "actual_outcome": "BLOCK"}},  # wrong
        {"event_type": "bootstrap.shadow_prediction",
         "payload": {"rule_id": "R-CACHE", "predicted_outcome": "WARN",
                     "actual_outcome": "WARN"}},
    ]
    rows = dashboard.aggregate_shadow(events)
    by_rule = {r["rule_id"]: r for r in rows}
    # R-AUTH: 2/3 correct = 66.67%
    assert by_rule["R-AUTH"]["n"] == 3
    assert by_rule["R-AUTH"]["correct"] == 2
    assert by_rule["R-AUTH"]["correctness_pct"] == pytest.approx(66.6666, rel=1e-3)
    # R-CACHE: 1/1 = 100%
    assert by_rule["R-CACHE"]["correctness_pct"] == pytest.approx(100.0)


# ────────────────────────── Case 6 ────────────────────────────────────────

def test_case6_quarantine_json_subprocess_parsed(dashboard, tmp_path):
    """Mock subprocess.run; verify fetch_quarantine_state parses --json output."""
    fake_payload = {
        "schema": "quarantine.status.v1",
        "total": 2,
        "disabled_count": 1,
        "stale_unquarantinable": [],
        "entries": [
            {"validator": "v1", "disabled": True, "consecutive_fails": 3,
             "last_fail_at": "2026-04-25T10:00:00Z", "unquarantinable": False,
             "re_enabled_at": None, "re_enabled_reason": None},
            {"validator": "v2", "disabled": False, "consecutive_fails": 0,
             "last_fail_at": None, "unquarantinable": True,
             "re_enabled_at": None, "re_enabled_reason": None},
        ],
    }
    fake_stdout = json.dumps(fake_payload)

    class FakeResult:
        returncode = 0
        stdout = fake_stdout
        stderr = ""

    with patch("dogfood_dashboard.subprocess.run", return_value=FakeResult()):
        state = dashboard.fetch_quarantine_state()

    assert state["total"] == 2
    assert state["disabled_count"] == 1
    assert len(state["entries"]) == 2
    assert state["entries"][0]["validator"] == "v1"
    assert state["entries"][1]["unquarantinable"] is True


# ────────────────────────── Case 7 ────────────────────────────────────────

def test_case7_lookback_truncates_older_phases(dashboard, tmp_path):
    """--lookback-phases 2 keeps only the last 2 distinct phases."""
    events = [
        {"phase": "1.0", "event_type": "step.complete"},
        {"phase": "1.0", "event_type": "step.complete"},
        {"phase": "2.0", "event_type": "step.complete"},
        {"phase": "3.0", "event_type": "step.complete"},
        {"phase": "3.0", "event_type": "step.complete"},
        {"phase": "4.0", "event_type": "step.complete"},
    ]
    filtered = dashboard.filter_by_lookback(events, lookback_phases=2)
    phases = {(e.get("phase") or "").strip() for e in filtered}
    assert phases == {"3.0", "4.0"}
    assert len(filtered) == 3  # 2× phase 3.0 + 1× phase 4.0


# ────────────────────────── Case 8 ────────────────────────────────────────

def test_case8_html_output_is_valid(dashboard, tmp_path):
    """End-to-end: render dashboard, validate HTML structure."""
    events = [
        {"phase": "7.6", "event_type": "step.started",
         "ts": "2026-04-25T10:00:00Z", "run_id": "r1", "command": "vg:build"},
        {"phase": "7.6", "event_type": "step.complete",
         "ts": "2026-04-25T10:00:30Z", "run_id": "r1", "command": "vg:build"},
        {"phase": "7.6", "event_type": "override.used",
         "payload": {"reason": "test-bypass"}},
        {"phase": "7.6", "event_type": "bootstrap.shadow_prediction",
         "payload": {"rule_id": "R-X", "predicted_outcome": "PASS",
                     "actual_outcome": "PASS"}},
    ]
    output = tmp_path / ".vg" / "dashboard.html"
    with _stub_quarantine_empty():
        summary = dashboard.build_dashboard(events, lookback=10,
                                            output_path=output)

    assert output.exists()
    content = output.read_text(encoding="utf-8")

    # Structural sanity
    assert content.startswith("<!DOCTYPE html>")
    assert "</html>" in content
    # Open/close tag counts must match for primary structural elements
    for tag in ("html", "head", "body", "main", "table"):
        opens = content.count(f"<{tag}")
        closes = content.count(f"</{tag}>")
        assert opens >= closes, (
            f"unclosed <{tag}>: opens={opens}, closes={closes}"
        )
    # Placeholder slots must all be substituted (no leaks)
    for placeholder in ("AUTONOMY_TABLE", "OVERRIDE_TABLE", "FRICTION_TABLE",
                        "SHADOW_TABLE", "CONFLICT_TABLE", "QUARANTINE_TABLE",
                        "META_GENERATED", "FOOTER"):
        assert f"<!-- {placeholder} -->" not in content, (
            f"placeholder {placeholder} not replaced"
        )
    # Sanity: phase + skill made it into rendered tables
    assert "7.6" in content
    assert "vg:build" in content
    assert "test-bypass" in content
    assert "R-X" in content
    assert summary["phases_in_autonomy"] == 1
    assert summary["skills_in_friction"] == 1
    assert summary["rules_in_shadow"] == 1
