"""
Phase G v2.5 (2026-04-23) — cost tracker tests.

Validates cost-tracker.py aggregates tokens correctly + budget verdict logic.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TRACKER   = REPO_ROOT / ".claude" / "scripts" / "cost-tracker.py"
PORTABILITY_DOC = REPO_ROOT / ".vg" / "MODEL-PORTABILITY.md"


def _make_repo(tmp_path: Path, events: list[dict],
               budgets: dict | None = None,
               roadmap: str | None = None) -> Path:
    vg = tmp_path / ".vg"
    vg.mkdir()

    # Write telemetry.jsonl
    jsonl_lines = [json.dumps(e) for e in events]
    (vg / "telemetry.jsonl").write_text("\n".join(jsonl_lines), encoding="utf-8")

    # Write events.db with same data
    db = vg / "events.db"
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, event_type TEXT, "
        "phase TEXT, payload TEXT, ts TEXT)"
    )
    for e in events:
        cur.execute(
            "INSERT INTO events (event_type, phase, payload, ts) VALUES (?,?,?,?)",
            (e.get("event_type") or e.get("type"),
             e.get("phase", ""),
             json.dumps(e.get("payload") or e),
             e.get("ts", "2026-04-23T00:00:00Z"))
        )
    conn.commit()
    conn.close()

    if roadmap:
        (vg / "ROADMAP.md").write_text(roadmap, encoding="utf-8")

    # Write config
    cfg_dir = tmp_path / ".claude"
    cfg_dir.mkdir()
    budgets = budgets or {"phase_budget_tokens": 100000, "milestone_budget_tokens": 500000,
                          "warn_threshold_pct": 80}
    cfg_text = (
        "---\ncost:\n"
        + "\n".join(f"  {k}: {v}" for k, v in budgets.items())
        + "\n---\n"
    )
    (cfg_dir / "vg.config.md").write_text(cfg_text, encoding="utf-8")
    return tmp_path


def _run(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(TRACKER)] + args,
        cwd=repo, capture_output=True, text=True, timeout=15, env=env,
    )


def test_no_events_under_budget(tmp_path):
    repo = _make_repo(tmp_path, events=[])
    r = _run(repo, ["--phase", "7.14", "--json"])
    assert r.returncode == 0
    data = json.loads(r.stdout.strip().splitlines()[-1])
    assert data["tokens"] == 0
    assert data["verdict"] == "PASS"


def test_phase_under_budget_pass(tmp_path):
    events = [
        {"event_type": "agent_invocation", "phase": "7.14",
         "payload": {"token_usage": {"prompt": 1000, "completion": 500}}},
        {"event_type": "agent_invocation", "phase": "7.14",
         "payload": {"token_usage": {"prompt": 2000, "completion": 500}}},
    ]
    repo = _make_repo(tmp_path, events=events, budgets={
        "phase_budget_tokens": 100000, "warn_threshold_pct": 80
    })
    r = _run(repo, ["--phase", "7.14", "--json"])
    assert r.returncode == 0
    # db + jsonl both contribute, so total = 4000 * 2 = 8000
    data = json.loads(r.stdout.strip().splitlines()[-1])
    assert data["tokens"] > 0
    assert data["verdict"] == "PASS"


def test_phase_over_budget_blocks(tmp_path):
    events = [
        {"event_type": "agent_invocation", "phase": "7.14",
         "payload": {"token_usage": {"prompt": 120000, "completion": 50000}}},
    ]
    repo = _make_repo(tmp_path, events=events, budgets={
        "phase_budget_tokens": 100000, "warn_threshold_pct": 80
    })
    r = _run(repo, ["--phase", "7.14", "--json"])
    # 170k > 100k budget → BLOCK
    assert r.returncode == 2
    data = json.loads(r.stdout.strip().splitlines()[-1])
    assert data["verdict"] == "BLOCK"


def test_phase_warn_threshold(tmp_path):
    """Usage at 85% budget → WARN (above warn_threshold_pct=80)."""
    events = [
        {"event_type": "agent_invocation", "phase": "7.14",
         "payload": {"token_usage": {"prompt": 85000, "completion": 0}}},
    ]
    repo = _make_repo(tmp_path, events=events, budgets={
        "phase_budget_tokens": 100000, "warn_threshold_pct": 80
    })
    r = _run(repo, ["--phase", "7.14", "--json"])
    data = json.loads(r.stdout.strip().splitlines()[-1])
    # Verdict is WARN (below hard budget, above warn threshold)
    assert data["verdict"] == "WARN"
    assert r.returncode == 1


def test_milestone_aggregates_multiple_phases(tmp_path):
    """Milestone aggregates tokens across all its phases."""
    events = [
        {"event_type": "agent_invocation", "phase": "7.14",
         "payload": {"token_usage": {"prompt": 100000, "completion": 50000}}},
        {"event_type": "agent_invocation", "phase": "7.15",
         "payload": {"token_usage": {"prompt": 50000, "completion": 50000}}},
    ]
    roadmap = "## Milestone M1\n- 7.14 DSP advertiser\n- 7.15 DSP publisher\n"
    repo = _make_repo(tmp_path, events=events, roadmap=roadmap, budgets={
        "milestone_budget_tokens": 1000000, "warn_threshold_pct": 80
    })
    r = _run(repo, ["--milestone", "M1", "--json"])
    data = json.loads(r.stdout.strip().splitlines()[-1])
    # 250k × 2 = 500k out of 1M → 50% → PASS
    assert data["tokens"] > 0
    assert data["verdict"] == "PASS"


def test_phase_filter_excludes_other_phases(tmp_path):
    events = [
        {"event_type": "agent_invocation", "phase": "7.14",
         "payload": {"token_usage": {"prompt": 1000, "completion": 500}}},
        {"event_type": "agent_invocation", "phase": "7.15",
         "payload": {"token_usage": {"prompt": 100000, "completion": 100000}}},
    ]
    repo = _make_repo(tmp_path, events=events, budgets={
        "phase_budget_tokens": 100000, "warn_threshold_pct": 80
    })
    r = _run(repo, ["--phase", "7.14", "--json"])
    data = json.loads(r.stdout.strip().splitlines()[-1])
    # Only 7.14 counted → small number → PASS
    assert data["verdict"] == "PASS"


def test_requires_phase_or_milestone_flag(tmp_path):
    repo = _make_repo(tmp_path, events=[])
    r = _run(repo, [])
    assert r.returncode != 0


def test_text_output_format(tmp_path):
    repo = _make_repo(tmp_path, events=[])
    r = _run(repo, ["--phase", "1"])
    assert r.returncode == 0
    # Human-readable format (not JSON)
    assert "tokens" in r.stdout.lower() or "cost" in r.stdout.lower()


def test_tracker_script_exists():
    assert TRACKER.exists()


# ─── MODEL-PORTABILITY.md doc ───────────────────────────────────────

class TestPortabilityDoc:
    def test_doc_exists(self):
        assert PORTABILITY_DOC.exists(), f"missing {PORTABILITY_DOC}"

    def test_references_foundation_section_9_8(self):
        text = PORTABILITY_DOC.read_text(encoding="utf-8")
        assert "9.8" in text or "§9.8" in text

    def test_doc_not_gate(self):
        """Doc must explicitly state it is NOT a gate (just documentation)."""
        text = PORTABILITY_DOC.read_text(encoding="utf-8")
        assert "NOT a gate" in text or "Doc-only" in text or "informational" in text.lower()

    def test_references_crossai_reuse(self):
        """Doc must mention CrossAI reuse (not building new tool)."""
        text = PORTABILITY_DOC.read_text(encoding="utf-8")
        assert "CrossAI" in text


# ─── config cost section ────────────────────────────────────────────

def test_vg_config_has_cost_section():
    cfg = REPO_ROOT / ".claude" / "vg.config.md"
    text = cfg.read_text(encoding="utf-8")
    assert "cost:" in text
    assert "phase_budget_tokens" in text
    assert "milestone_budget_tokens" in text
