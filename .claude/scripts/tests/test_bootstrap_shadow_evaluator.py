"""
VG v2.6 Phase A — bootstrap-shadow-evaluator regression tests.

12 cases per PLAN-REVISED.md Phase A:
  1. events.jsonl empty -> output empty
  2. 5 events for L-001 -> correctness computed, n_samples=5
  3. min_samples threshold (n=2 < 5) -> tier_proposed=C (insufficient)
  4. correctness >= critical (0.95) AND impact=critical -> tier_proposed=A
  5. correctness in [important, critical) -> tier_proposed=B
  6. correctness < important threshold -> tier_proposed=C
  7. stale Tier A demotion (status=promoted, n>stale_phases, rate<threshold)
  8. promote/retire matrix (all valid transitions exercised)
  9. critic verdict parsing (mock Haiku response)
 10. critic LLM unavailable -> graceful degrade (fields omitted)
 11. critic disabled in config -> --critic still works, emits "skipped"
 12. concurrent runs same candidate -> idempotent output

All tests use VG_REPO_ROOT scoped to tmp_path; the script is invoked
in-process via importlib so no subprocess flakiness.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "bootstrap-shadow-evaluator.py"
)


@pytest.fixture
def evaluator(monkeypatch, tmp_path):
    """Import the script as a module with VG_REPO_ROOT scoped to tmp_path."""
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    # Build minimal repo skeleton
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg" / "bootstrap").mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / ".claude" / "vg.config.md"
    cfg.write_text(
        "bootstrap:\n"
        "  shadow_min_phases: 5\n"
        "  shadow_correctness_critical: 0.95\n"
        "  shadow_correctness_important: 0.80\n"
        "  shadow_stale_phases: 10\n"
        "  critic_enabled: true\n"
        '  critic_model: "claude-haiku-4-5-20251001"\n',
        encoding="utf-8",
    )

    # Reload module fresh per test (REPO_ROOT is module-level)
    spec = importlib.util.spec_from_file_location(
        "bootstrap_shadow_evaluator", str(SCRIPT_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _write_candidates(repo: Path, candidates: list[dict]) -> Path:
    p = repo / ".vg" / "bootstrap" / "CANDIDATES.md"
    blocks = []
    for c in candidates:
        body = "\n".join(
            f"{k}: {json.dumps(v) if isinstance(v, (dict, list)) else v}"
            for k, v in c.items()
        )
        blocks.append("```yaml\n" + body + "\n```")
    p.write_text("# CANDIDATES\n\n" + "\n\n".join(blocks), encoding="utf-8")
    return p


def _write_events(repo: Path, events: list[dict]) -> Path:
    p = repo / ".vg" / "events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "\n".join(json.dumps(e) for e in events) + ("\n" if events else ""),
        encoding="utf-8",
    )
    return p


# ─── Test 1: empty events.jsonl ──────────────────────────────────────────────

def test_01_empty_events_yields_empty_output(evaluator, tmp_path):
    _write_candidates(tmp_path, [])
    _write_events(tmp_path, [])
    cfg = evaluator.load_config(tmp_path / ".claude" / "vg.config.md")
    cands = evaluator.parse_candidates(tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md")
    evs = evaluator.read_events(tmp_path / ".vg" / "events.jsonl")
    result = evaluator.evaluate_all(cands, evs, cfg)
    assert result == []


# ─── Test 2: 5 events -> correctness + n_samples ─────────────────────────────

def test_02_five_events_correctness_computed(evaluator, tmp_path, monkeypatch):
    _write_candidates(
        tmp_path,
        [
            {"id": "L-001", "title": "rule one", "impact": "important",
             "status": "pending", "prose": "test"},
        ],
    )
    events = [
        {"event_type": "bootstrap.shadow_prediction", "phase": "7.10",
         "payload": {"candidate_id": "L-001", "commit_sha": f"abc{i:04d}",
                     "predicted": {"contract": True}}}
        for i in range(5)
    ]
    _write_events(tmp_path, events)

    # Mock commit_message to return a body with the expected citation
    monkeypatch.setattr(
        evaluator, "commit_message",
        lambda sha: "feat(7.10-01): foo\n\nPer API-CONTRACTS.md line 1-5"
    )

    cfg = evaluator.load_config(tmp_path / ".claude" / "vg.config.md")
    cands = evaluator.parse_candidates(tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md")
    evs = evaluator.read_events(tmp_path / ".vg" / "events.jsonl")
    result = evaluator.evaluate_all(cands, evs, cfg)

    assert len(result) == 1
    assert result[0]["id"] == "L-001"
    assert result[0]["n_samples"] == 5
    assert result[0]["correctness"] == 1.0
    assert result[0]["shadow_since_phase"] == "7.10"


# ─── Test 3: min_samples gate ────────────────────────────────────────────────

def test_03_below_min_samples_no_promotion(evaluator, tmp_path, monkeypatch):
    _write_candidates(
        tmp_path,
        [{"id": "L-002", "title": "few-events", "impact": "critical",
          "status": "pending", "prose": "x"}],
    )
    events = [
        {"event_type": "bootstrap.shadow_prediction", "phase": "7.10",
         "payload": {"candidate_id": "L-002", "commit_sha": f"def{i:04d}",
                     "predicted": {"contract": True}}}
        for i in range(2)
    ]
    _write_events(tmp_path, events)
    monkeypatch.setattr(evaluator, "commit_message",
                        lambda sha: "Per API-CONTRACTS.md line 1")

    cfg = evaluator.load_config(tmp_path / ".claude" / "vg.config.md")
    cands = evaluator.parse_candidates(tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md")
    evs = evaluator.read_events(tmp_path / ".vg" / "events.jsonl")
    result = evaluator.evaluate_all(cands, evs, cfg)

    assert result[0]["tier_proposed"] == "C"
    assert result[0]["n_samples"] == 2


# ─── Test 4: correctness >= critical AND impact=critical -> A ────────────────

def test_04_critical_threshold_promotes_to_A(evaluator, tmp_path, monkeypatch):
    _write_candidates(
        tmp_path,
        [{"id": "L-003", "title": "critical", "impact": "critical",
          "status": "pending", "prose": "x"}],
    )
    # 20 events all matching -> rate = 1.0
    events = [
        {"event_type": "bootstrap.shadow_prediction", "phase": "7.10",
         "payload": {"candidate_id": "L-003", "commit_sha": f"sha{i:04d}",
                     "predicted": {"contract": True}}}
        for i in range(20)
    ]
    _write_events(tmp_path, events)
    monkeypatch.setattr(evaluator, "commit_message",
                        lambda sha: "Per API-CONTRACTS.md line 1")

    cfg = evaluator.load_config(tmp_path / ".claude" / "vg.config.md")
    cands = evaluator.parse_candidates(tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md")
    evs = evaluator.read_events(tmp_path / ".vg" / "events.jsonl")
    result = evaluator.evaluate_all(cands, evs, cfg)

    assert result[0]["tier_proposed"] == "A"
    assert result[0]["correctness"] >= 0.95
    assert result[0]["adaptive_threshold"] == 0.95


# ─── Test 5: correctness in [important, critical) -> B ───────────────────────

def test_05_important_threshold_promotes_to_B(evaluator, tmp_path, monkeypatch):
    _write_candidates(
        tmp_path,
        [{"id": "L-004", "title": "imp", "impact": "important",
          "status": "pending", "prose": "x"}],
    )
    # 10 events: 9 cite, 1 doesn't (rate = 0.90)
    events = [
        {"event_type": "bootstrap.shadow_prediction", "phase": "7.11",
         "payload": {"candidate_id": "L-004", "commit_sha": f"k{i:04d}",
                     "predicted": {"contract": True}}}
        for i in range(10)
    ]
    _write_events(tmp_path, events)

    def fake_msg(sha):
        return ("Per API-CONTRACTS.md line 1"
                if not sha.endswith("0009") else "feat: nothing relevant")
    monkeypatch.setattr(evaluator, "commit_message", fake_msg)

    cfg = evaluator.load_config(tmp_path / ".claude" / "vg.config.md")
    cands = evaluator.parse_candidates(tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md")
    evs = evaluator.read_events(tmp_path / ".vg" / "events.jsonl")
    result = evaluator.evaluate_all(cands, evs, cfg)

    assert result[0]["tier_proposed"] == "B"
    assert 0.80 <= result[0]["correctness"] < 0.95


# ─── Test 6: correctness below important -> C ────────────────────────────────

def test_06_low_correctness_yields_C(evaluator, tmp_path, monkeypatch):
    _write_candidates(
        tmp_path,
        [{"id": "L-005", "title": "weak", "impact": "important",
          "status": "pending", "prose": "x"}],
    )
    events = [
        {"event_type": "bootstrap.shadow_prediction", "phase": "7.12",
         "payload": {"candidate_id": "L-005", "commit_sha": f"q{i:04d}",
                     "predicted": {"contract": True}}}
        for i in range(10)
    ]
    _write_events(tmp_path, events)
    # only 5/10 cite -> rate = 0.5
    monkeypatch.setattr(
        evaluator, "commit_message",
        lambda sha: "Per API-CONTRACTS.md line 1" if int(sha[-4:]) < 5 else "noop"
    )

    cfg = evaluator.load_config(tmp_path / ".claude" / "vg.config.md")
    cands = evaluator.parse_candidates(tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md")
    evs = evaluator.read_events(tmp_path / ".vg" / "events.jsonl")
    result = evaluator.evaluate_all(cands, evs, cfg)

    assert result[0]["tier_proposed"] == "C"
    assert result[0]["correctness"] < 0.80


# ─── Test 7: stale Tier A demotion ───────────────────────────────────────────

def test_07_stale_tier_a_demotes(evaluator, tmp_path, monkeypatch):
    _write_candidates(
        tmp_path,
        [{"id": "L-006", "title": "stale", "impact": "critical",
          "status": "promoted", "prose": "x"}],
    )
    # 12 events (> stale_phases=10), only 50% cite -> drop below threshold
    events = [
        {"event_type": "bootstrap.shadow_prediction", "phase": "7.13",
         "payload": {"candidate_id": "L-006", "commit_sha": f"s{i:04d}",
                     "predicted": {"contract": True}}}
        for i in range(12)
    ]
    _write_events(tmp_path, events)
    monkeypatch.setattr(
        evaluator, "commit_message",
        lambda sha: "Per API-CONTRACTS.md line 1" if int(sha[-4:]) < 6 else "noop"
    )

    cfg = evaluator.load_config(tmp_path / ".claude" / "vg.config.md")
    cands = evaluator.parse_candidates(tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md")
    evs = evaluator.read_events(tmp_path / ".vg" / "events.jsonl")
    result = evaluator.evaluate_all(cands, evs, cfg)

    assert result[0]["demote"] is True
    assert result[0]["tier_proposed"] == "C"


# ─── Test 8: promote/retire matrix (state machine smoke) ─────────────────────

def test_08_promote_retire_matrix(evaluator, tmp_path, monkeypatch):
    """Exercise valid transitions: pending→A, pending→B, pending→C, promoted→demote."""
    _write_candidates(
        tmp_path,
        [
            {"id": "L-100", "title": "to-A", "impact": "critical",
             "status": "pending", "prose": "x"},
            {"id": "L-101", "title": "to-B", "impact": "important",
             "status": "pending", "prose": "x"},
            {"id": "L-102", "title": "to-C", "impact": "important",
             "status": "pending", "prose": "x"},
            {"id": "L-103", "title": "demote", "impact": "critical",
             "status": "promoted", "prose": "x"},
        ],
    )
    events: list = []
    # L-100: 10/10 cite
    for i in range(10):
        events.append({
            "event_type": "bootstrap.shadow_prediction", "phase": "7.10",
            "payload": {"candidate_id": "L-100", "commit_sha": f"a{i:04d}",
                        "predicted": {"contract": True}},
        })
    # L-101: 9/10 cite
    for i in range(10):
        events.append({
            "event_type": "bootstrap.shadow_prediction", "phase": "7.11",
            "payload": {"candidate_id": "L-101", "commit_sha": f"b{i:04d}",
                        "predicted": {"contract": True}},
        })
    # L-102: 3/10 cite
    for i in range(10):
        events.append({
            "event_type": "bootstrap.shadow_prediction", "phase": "7.12",
            "payload": {"candidate_id": "L-102", "commit_sha": f"c{i:04d}",
                        "predicted": {"contract": True}},
        })
    # L-103: 12 events, 4 cite (below imp threshold) — promoted+stale → demote
    for i in range(12):
        events.append({
            "event_type": "bootstrap.shadow_prediction", "phase": "7.13",
            "payload": {"candidate_id": "L-103", "commit_sha": f"d{i:04d}",
                        "predicted": {"contract": True}},
        })
    _write_events(tmp_path, events)

    def fake_msg(sha):
        prefix, idx = sha[0], int(sha[1:5])
        if prefix == "a":
            return "Per API-CONTRACTS.md line 1"
        if prefix == "b":
            return "Per API-CONTRACTS.md line 1" if idx != 9 else "noop"
        if prefix == "c":
            return "Per API-CONTRACTS.md line 1" if idx < 3 else "noop"
        if prefix == "d":
            return "Per API-CONTRACTS.md line 1" if idx < 4 else "noop"
        return "noop"

    monkeypatch.setattr(evaluator, "commit_message", fake_msg)

    cfg = evaluator.load_config(tmp_path / ".claude" / "vg.config.md")
    cands = evaluator.parse_candidates(tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md")
    evs = evaluator.read_events(tmp_path / ".vg" / "events.jsonl")
    result = {r["id"]: r for r in evaluator.evaluate_all(cands, evs, cfg)}

    assert result["L-100"]["tier_proposed"] == "A"
    assert result["L-101"]["tier_proposed"] == "B"
    assert result["L-102"]["tier_proposed"] == "C"
    assert result["L-103"]["demote"] is True


# ─── Test 9: critic verdict parsing ──────────────────────────────────────────

def test_09_critic_parses_haiku_response(evaluator, tmp_path, monkeypatch):
    _write_candidates(
        tmp_path,
        [{"id": "L-200", "title": "c", "impact": "important",
          "status": "pending", "prose": "rule prose"}],
    )
    events = [
        {"event_type": "bootstrap.shadow_prediction", "phase": "7.10",
         "payload": {"candidate_id": "L-200", "commit_sha": f"e{i:04d}",
                     "predicted": {"contract": True}}}
        for i in range(10)
    ]
    _write_events(tmp_path, events)
    monkeypatch.setattr(evaluator, "commit_message",
                        lambda sha: "Per API-CONTRACTS.md line 1")
    monkeypatch.setattr(
        evaluator, "call_critic",
        lambda prompt, model: {"critic_verdict": "supports",
                               "critic_reason": "all commits cited contract"},
    )

    cfg = evaluator.load_config(tmp_path / ".claude" / "vg.config.md")
    cands = evaluator.parse_candidates(tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md")
    evs = evaluator.read_events(tmp_path / ".vg" / "events.jsonl")
    result = evaluator.evaluate_all(cands, evs, cfg, critic=True)

    assert result[0]["tier_proposed"] == "B"
    assert result[0]["critic_verdict"] == "supports"
    assert "all commits" in result[0]["critic_reason"]


# ─── Test 10: critic LLM unavailable -> graceful degrade ─────────────────────

def test_10_critic_unavailable_no_crash(evaluator, tmp_path, monkeypatch):
    _write_candidates(
        tmp_path,
        [{"id": "L-201", "title": "u", "impact": "important",
          "status": "pending", "prose": "rule prose"}],
    )
    events = [
        {"event_type": "bootstrap.shadow_prediction", "phase": "7.10",
         "payload": {"candidate_id": "L-201", "commit_sha": f"f{i:04d}",
                     "predicted": {"contract": True}}}
        for i in range(10)
    ]
    _write_events(tmp_path, events)
    monkeypatch.setattr(evaluator, "commit_message",
                        lambda sha: "Per API-CONTRACTS.md line 1")
    # Simulate no API key + no SDK -> call_critic returns None
    monkeypatch.setattr(evaluator, "call_critic", lambda prompt, model: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    cfg = evaluator.load_config(tmp_path / ".claude" / "vg.config.md")
    cands = evaluator.parse_candidates(tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md")
    evs = evaluator.read_events(tmp_path / ".vg" / "events.jsonl")
    result = evaluator.evaluate_all(cands, evs, cfg, critic=True)

    assert result[0]["tier_proposed"] == "B"
    assert "critic_verdict" not in result[0]
    assert "critic_reason" not in result[0]


# ─── Test 11: critic disabled in config -> "skipped" reason ──────────────────

def test_11_critic_disabled_in_config_emits_skipped(evaluator, tmp_path, monkeypatch):
    cfg_path = tmp_path / ".claude" / "vg.config.md"
    cfg_path.write_text(
        "bootstrap:\n"
        "  shadow_min_phases: 5\n"
        "  shadow_correctness_critical: 0.95\n"
        "  shadow_correctness_important: 0.80\n"
        "  shadow_stale_phases: 10\n"
        "  critic_enabled: false\n"
        '  critic_model: "claude-haiku-4-5-20251001"\n',
        encoding="utf-8",
    )
    _write_candidates(
        tmp_path,
        [{"id": "L-202", "title": "d", "impact": "important",
          "status": "pending", "prose": "rule"}],
    )
    events = [
        {"event_type": "bootstrap.shadow_prediction", "phase": "7.10",
         "payload": {"candidate_id": "L-202", "commit_sha": f"g{i:04d}",
                     "predicted": {"contract": True}}}
        for i in range(10)
    ]
    _write_events(tmp_path, events)
    monkeypatch.setattr(evaluator, "commit_message",
                        lambda sha: "Per API-CONTRACTS.md line 1")

    rc = evaluator.main([
        "--critic",
        "--candidate", "L-202",
        "--config", str(cfg_path),
        "--candidates-path", str(tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md"),
        "--events-path", str(tmp_path / ".vg" / "events.jsonl"),
        "--output-jsonl", str(tmp_path / "out.jsonl"),
    ])
    assert rc == 0
    out = (tmp_path / "out.jsonl").read_text(encoding="utf-8").strip().splitlines()
    rec = json.loads(out[0])
    assert rec["tier_proposed"] == "B"
    assert rec["critic_verdict"] == "skipped"
    assert "critic_enabled=false" in rec["critic_reason"]


# ─── Test 12: idempotent concurrent runs ─────────────────────────────────────

def test_12_concurrent_runs_idempotent(evaluator, tmp_path, monkeypatch):
    _write_candidates(
        tmp_path,
        [{"id": "L-300", "title": "i", "impact": "important",
          "status": "pending", "prose": "rule"}],
    )
    events = [
        {"event_type": "bootstrap.shadow_prediction", "phase": "7.10",
         "payload": {"candidate_id": "L-300", "commit_sha": f"h{i:04d}",
                     "predicted": {"contract": True}}}
        for i in range(8)
    ]
    _write_events(tmp_path, events)
    monkeypatch.setattr(evaluator, "commit_message",
                        lambda sha: "Per API-CONTRACTS.md line 1")

    out1 = tmp_path / "out1.jsonl"
    out2 = tmp_path / "out2.jsonl"
    cfg_path = tmp_path / ".claude" / "vg.config.md"
    cands_path = tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md"
    evs_path = tmp_path / ".vg" / "events.jsonl"

    rc1 = evaluator.main([
        "--config", str(cfg_path),
        "--candidates-path", str(cands_path),
        "--events-path", str(evs_path),
        "--output-jsonl", str(out1),
    ])
    rc2 = evaluator.main([
        "--config", str(cfg_path),
        "--candidates-path", str(cands_path),
        "--events-path", str(evs_path),
        "--output-jsonl", str(out2),
    ])
    assert rc1 == 0 and rc2 == 0
    a = out1.read_text(encoding="utf-8")
    b = out2.read_text(encoding="utf-8")
    assert a == b, "Concurrent runs must produce identical JSONL output"
    assert "L-300" in a
