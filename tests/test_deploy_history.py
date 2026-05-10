"""v2.82.0 Stage 6.3 — `.vg/deploy/history.jsonl` append-only event log."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts"))


@pytest.fixture
def hist_mod():
    from deploy import history  # type: ignore[import-not-found]

    return history


def test_append_creates_file(tmp_path, hist_mod):
    path = hist_mod.append_event(
        tmp_path,
        {"event": "deploy.started", "env": "prod", "sha": "aaa"},
    )
    assert path.exists()
    assert path == tmp_path / ".vg" / "deploy" / "history.jsonl"


def test_append_adds_ts_when_missing(tmp_path, hist_mod):
    hist_mod.append_event(tmp_path, {"event": "deploy.started", "env": "prod"})
    line = (tmp_path / ".vg" / "deploy" / "history.jsonl").read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert "ts" in record
    assert record["ts"].startswith("20")  # ISO 8601


def test_append_preserves_explicit_ts(tmp_path, hist_mod):
    hist_mod.append_event(
        tmp_path,
        {"event": "deploy.completed", "env": "prod", "ts": "2026-05-10T10:00:00Z"},
    )
    record = json.loads(
        (tmp_path / ".vg" / "deploy" / "history.jsonl").read_text(encoding="utf-8").strip()
    )
    assert record["ts"] == "2026-05-10T10:00:00Z"


def test_multiple_events_each_on_own_line(tmp_path, hist_mod):
    for i in range(3):
        hist_mod.append_event(tmp_path, {"event": "deploy.started", "i": i})
    lines = (
        (tmp_path / ".vg" / "deploy" / "history.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert len(lines) == 3
    for line in lines:
        json.loads(line)  # valid JSON each


def test_append_rejects_non_dict(tmp_path, hist_mod):
    with pytest.raises(TypeError):
        hist_mod.append_event(tmp_path, "not a dict")  # type: ignore[arg-type]


def test_rotate_when_exceeds_threshold(tmp_path, hist_mod):
    # Pre-populate with > rotate_bytes worth of data
    deploy_dir = tmp_path / ".vg" / "deploy"
    deploy_dir.mkdir(parents=True)
    big_path = deploy_dir / "history.jsonl"
    big_path.write_text("x" * 100, encoding="utf-8")
    hist_mod.append_event(
        tmp_path,
        {"event": "deploy.completed", "env": "prod"},
        rotate_bytes=50,  # tiny threshold for test
    )
    rotated = list(deploy_dir.glob("history-*.jsonl"))
    assert len(rotated) == 1, f"expected 1 rotated; got {rotated}"
    # Fresh history should contain only the new line
    lines = big_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_read_events_returns_all(tmp_path, hist_mod):
    for i in range(5):
        hist_mod.append_event(tmp_path, {"event": "deploy.started", "i": i})
    events = hist_mod.read_events(tmp_path)
    assert len(events) == 5


def test_read_events_filter_env(tmp_path, hist_mod):
    hist_mod.append_event(tmp_path, {"event": "deploy.completed", "env": "prod"})
    hist_mod.append_event(tmp_path, {"event": "deploy.completed", "env": "staging"})
    prod = hist_mod.read_events(tmp_path, env="prod")
    assert len(prod) == 1 and prod[0]["env"] == "prod"


def test_read_events_filter_event(tmp_path, hist_mod):
    hist_mod.append_event(tmp_path, {"event": "deploy.started", "env": "prod"})
    hist_mod.append_event(tmp_path, {"event": "deploy.completed", "env": "prod"})
    completed = hist_mod.read_events(tmp_path, event="deploy.completed")
    assert len(completed) == 1
    assert completed[0]["event"] == "deploy.completed"


def test_read_events_skips_corrupt_lines(tmp_path, hist_mod):
    hist_mod.append_event(tmp_path, {"event": "deploy.started", "env": "prod"})
    # Append corrupt line manually
    path = tmp_path / ".vg" / "deploy" / "history.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write("not json\n")
    hist_mod.append_event(tmp_path, {"event": "deploy.completed", "env": "prod"})
    events = hist_mod.read_events(tmp_path)
    assert len(events) == 2  # corrupt line skipped


def test_latest_successful_sha(tmp_path, hist_mod):
    hist_mod.append_event(
        tmp_path,
        {"event": "deploy.completed", "env": "prod", "sha": "aaa"},
    )
    hist_mod.append_event(
        tmp_path,
        {"event": "deploy.completed", "env": "prod", "sha": "bbb"},
    )
    assert hist_mod.latest_successful_sha(tmp_path, "prod") == "bbb"


def test_latest_successful_sha_no_events_returns_none(tmp_path, hist_mod):
    assert hist_mod.latest_successful_sha(tmp_path, "prod") is None


def test_latest_successful_sha_before_filter(tmp_path, hist_mod):
    hist_mod.append_event(
        tmp_path,
        {
            "event": "deploy.completed",
            "env": "prod",
            "sha": "aaa",
            "ts": "2026-05-10T10:00:00Z",
        },
    )
    hist_mod.append_event(
        tmp_path,
        {
            "event": "deploy.completed",
            "env": "prod",
            "sha": "bbb",
            "ts": "2026-05-10T11:00:00Z",
        },
    )
    # Asking for latest before bbb's ts → returns aaa
    sha = hist_mod.latest_successful_sha(
        tmp_path, "prod", before="2026-05-10T10:30:00Z"
    )
    assert sha == "aaa"
