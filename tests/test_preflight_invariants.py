"""Tests for scripts/runtime/preflight.py — RFC v9 PR-C N-consumer algorithm."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.preflight import (  # noqa: E402
    PreflightError,
    parse_env_contract,
    required_count,
    verify_invariants,
    fix_hint,
)


# ─── required_count algorithm (D5) ────────────────────────────────────


def test_per_consumer_one_destructive():
    inv = {
        "id": "i1",
        "consumers": [
            {"goal": "G-1", "recipe": "G-1", "consume_semantics": "destructive"},
        ],
    }
    assert required_count(inv) == 1


def test_per_consumer_three_destructive():
    inv = {
        "id": "i1",
        "consumers": [
            {"goal": f"G-{i}", "recipe": f"G-{i}", "consume_semantics": "destructive"}
            for i in range(1, 4)
        ],
    }
    assert required_count(inv) == 3


def test_per_consumer_destructive_plus_read_only_adds_one():
    """3 destructive + 2 read_only with isolation=per_consumer → 4 (3 destructive + 1 shared)."""
    inv = {
        "id": "i1",
        "consumers": [
            {"goal": "G-1", "recipe": "G-1", "consume_semantics": "destructive"},
            {"goal": "G-2", "recipe": "G-2", "consume_semantics": "destructive"},
            {"goal": "G-3", "recipe": "G-3", "consume_semantics": "destructive"},
            {"goal": "G-4", "recipe": "G-4", "consume_semantics": "read_only"},
            {"goal": "G-5", "recipe": "G-5", "consume_semantics": "read_only"},
        ],
    }
    assert required_count(inv) == 4


def test_shared_when_read_only_all_read_only():
    inv = {
        "id": "i1",
        "isolation": "shared_when_read_only",
        "consumers": [
            {"goal": "G-1", "recipe": "G-1", "consume_semantics": "read_only"},
            {"goal": "G-2", "recipe": "G-2", "consume_semantics": "read_only"},
        ],
    }
    assert required_count(inv) == 1


def test_shared_when_read_only_with_destructive_falls_back():
    """isolation=shared_when_read_only but a destructive consumer present →
    fall back to per_consumer count (destructive_n)."""
    inv = {
        "id": "i1",
        "isolation": "shared_when_read_only",
        "consumers": [
            {"goal": "G-1", "recipe": "G-1", "consume_semantics": "destructive"},
            {"goal": "G-2", "recipe": "G-2", "consume_semantics": "read_only"},
        ],
    }
    assert required_count(inv) == 1  # destructive_n=1; can't share with destructive


def test_no_consumers_raises():
    with pytest.raises(PreflightError, match="no consumers"):
        required_count({"id": "i1", "consumers": []})


def test_unknown_isolation_raises():
    inv = {
        "id": "i1",
        "isolation": "weird",
        "consumers": [
            {"goal": "G-1", "recipe": "G-1", "consume_semantics": "destructive"},
        ],
    }
    with pytest.raises(PreflightError, match="unknown isolation"):
        required_count(inv)


# ─── verify_invariants ───────────────────────────────────────────────


def _stub_count_fn(returns: dict[str, int]):
    """Returns a count_fn that maps resource → fixed count."""
    def count_fn(resource: str, where: dict) -> int:
        return returns.get(resource, 0)
    return count_fn


def test_verify_invariants_no_gap():
    invariants = [{
        "id": "tier2_topup",
        "resource": "topup",
        "where": {"tier": 2},
        "consumers": [
            {"goal": "G-1", "recipe": "G-1", "consume_semantics": "destructive"},
            {"goal": "G-2", "recipe": "G-2", "consume_semantics": "destructive"},
        ],
    }]
    gaps = verify_invariants(invariants, _stub_count_fn({"topup": 5}))
    assert gaps == []


def test_verify_invariants_gap_destructive_short():
    invariants = [{
        "id": "tier2_topup",
        "resource": "topup",
        "where": {"tier": 2},
        "consumers": [
            {"goal": "G-1", "recipe": "G-1", "consume_semantics": "destructive"},
            {"goal": "G-2", "recipe": "G-2", "consume_semantics": "destructive"},
            {"goal": "G-3", "recipe": "G-3", "consume_semantics": "destructive"},
        ],
    }]
    gaps = verify_invariants(invariants, _stub_count_fn({"topup": 1}))
    assert len(gaps) == 1
    g = gaps[0]
    assert g.required == 3
    assert g.actual == 1
    assert "G-1" in g.consumers and "G-3" in g.consumers


def test_verify_invariants_multiple_resources():
    invariants = [
        {
            "id": "i1",
            "resource": "topup",
            "where": {"tier": 2},
            "consumers": [{"goal": "G-1", "recipe": "G-1",
                           "consume_semantics": "destructive"}],
        },
        {
            "id": "i2",
            "resource": "withdraw",
            "where": {"status": "pending"},
            "consumers": [{"goal": "G-2", "recipe": "G-2",
                           "consume_semantics": "destructive"}],
        },
    ]
    # topup OK (1), withdraw short (0)
    gaps = verify_invariants(invariants, _stub_count_fn({"topup": 1, "withdraw": 0}))
    assert len(gaps) == 1
    assert gaps[0].invariant_id == "i2"
    assert gaps[0].resource == "withdraw"


def test_count_fn_receives_correct_where():
    captured: list = []

    def count_fn(resource: str, where: dict) -> int:
        captured.append((resource, where))
        return 99

    invariants = [{
        "id": "i1",
        "resource": "topup",
        "where": {"tier": 2, "status": "pending"},
        "consumers": [{"goal": "G-1", "recipe": "G-1",
                       "consume_semantics": "destructive"}],
    }]
    verify_invariants(invariants, count_fn)
    assert captured == [("topup", {"tier": 2, "status": "pending"})]


def test_invariant_missing_id_raises():
    with pytest.raises(PreflightError, match="missing id"):
        verify_invariants(
            [{"resource": "x", "consumers": [
                {"goal": "G-1", "recipe": "G-1", "consume_semantics": "destructive"},
            ]}],
            _stub_count_fn({}),
        )


# ─── fix_hint ─────────────────────────────────────────────────────────


def test_fix_hint_includes_actionable_data():
    from runtime.preflight import InvariantGap
    g = InvariantGap(
        invariant_id="tier2_topup",
        resource="topup",
        required=3,
        actual=1,
        consumers=["G-10", "G-11", "G-12"],
        where={"tier": 2, "status": "pending"},
    )
    hint = fix_hint(g)
    assert "create 2 more" in hint
    assert "G-10" in hint
    assert "tier2_topup" in hint
    assert "shared_when_read_only" in hint  # offer alternative


# ─── parse_env_contract ──────────────────────────────────────────────


def test_parses_yaml_block_in_markdown(tmp_path):
    md = """
# ENV-CONTRACT

Some prose…

```yaml
data_invariants:
  - id: tier2_topup
    resource: topup
    where:
      tier: 2
    consumers:
      - goal: G-10
        recipe: G-10
        consume_semantics: destructive
```

More prose.
""".lstrip()
    path = tmp_path / "ENV-CONTRACT.md"
    path.write_text(md, encoding="utf-8")
    pytest.importorskip("yaml")
    invs = parse_env_contract(path)
    assert len(invs) == 1
    assert invs[0]["id"] == "tier2_topup"


def test_parses_pure_yaml(tmp_path):
    pytest.importorskip("yaml")
    yaml_text = """
data_invariants:
  - id: x
    resource: r
    where: {a: 1}
    consumers:
      - {goal: G-1, recipe: G-1, consume_semantics: read_only}
""".lstrip()
    path = tmp_path / "ENV.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    invs = parse_env_contract(path)
    assert invs[0]["id"] == "x"


def test_returns_empty_when_no_block(tmp_path):
    path = tmp_path / "no.md"
    path.write_text("No invariants here.\n", encoding="utf-8")
    pytest.importorskip("yaml")
    assert parse_env_contract(path) == []
