"""v2.68.0 C4 — Discourse phase aggregator."""
import importlib.util
import sys
from pathlib import Path
import pytest


def _load():
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "crossai_normalize_results",
        repo_root / "scripts" / "crossai-normalize-results.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_discourse_function_exists():
    mod = _load()
    assert hasattr(mod, "compute_discourse_verdict"), \
        "compute_discourse_verdict function missing (v2.68.0 C4)"


def test_all_agree_yields_high_confidence_verdict():
    mod = _load()
    reviewers = [
        {"name": "Claude", "verdict": "pass", "findings": []},
        {"name": "Codex", "verdict": "pass", "findings": []},
        {"name": "Gemini", "verdict": "pass", "findings": []},
    ]
    result = mod.compute_discourse_verdict(reviewers)
    assert result["verdict"] == "pass"
    assert result["confidence"] == "high"
    assert any(m["move"] == "AGREE" for m in result["moves"])


def test_one_challenges_yields_partial_verdict():
    mod = _load()
    reviewers = [
        {"name": "Claude", "verdict": "pass", "findings": []},
        {"name": "Codex", "verdict": "pass", "findings": []},
        {"name": "Gemini", "verdict": "block", "findings": [{"id": "F-1", "title": "auth bypass"}]},
    ]
    result = mod.compute_discourse_verdict(reviewers)
    # 1 challenger = SURFACE the dissenting finding for human review
    assert result["verdict"] in ("flag", "partial")
    assert any(m["move"] == "CHALLENGE" for m in result["moves"])
    assert any(m["move"] == "SURFACE" for m in result["moves"])


def test_two_block_one_pass_yields_block_verdict():
    mod = _load()
    reviewers = [
        {"name": "Claude", "verdict": "block", "findings": [{"id": "F-1"}]},
        {"name": "Codex", "verdict": "block", "findings": [{"id": "F-2"}]},
        {"name": "Gemini", "verdict": "pass", "findings": []},
    ]
    result = mod.compute_discourse_verdict(reviewers)
    assert result["verdict"] == "block"
    # The pass-reviewer's perspective should be SURFACEd (might be missing context)
    assert any(m["move"] == "SURFACE" or m["move"] == "CONNECT" for m in result["moves"])


def test_overlapping_findings_yield_connect_move():
    """When 2 reviewers raise SAME finding (same id or normalized title), emit CONNECT move."""
    mod = _load()
    reviewers = [
        {"name": "Claude", "verdict": "block", "findings": [{"id": "F-AUTH", "title": "auth bypass on /admin"}]},
        {"name": "Codex", "verdict": "block", "findings": [{"id": "F-AUTH", "title": "auth bypass on /admin"}]},
        {"name": "Gemini", "verdict": "pass", "findings": []},
    ]
    result = mod.compute_discourse_verdict(reviewers)
    assert any(m["move"] == "CONNECT" for m in result["moves"]), \
        "overlapping findings must emit CONNECT move (corroboration)"
