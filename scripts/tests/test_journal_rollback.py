"""
Tests for vg-orchestrator/journal.py — Phase O of v2.5.2.

Covers:
  - journal_entry appends JSONL with monotonic ids
  - query_journal filters by run_id + action_prefix
  - file_write rollback restores prior content
  - file_write on newly-created file → rollback deletes
  - file_delete rollback restores captured content
  - config_change rollback reverts a JSON key
  - config_change rollback removes key that didn't exist before
  - state_transition + manifest_append marked as skipped
  - dry_run mode returns plan without touching files
  - cross-run isolation — rollback of run A does not affect run B
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT_REAL = Path(__file__).resolve().parents[3]
ORCH_DIR = REPO_ROOT_REAL / ".claude" / "scripts" / "vg-orchestrator"


@pytest.fixture
def journal_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    sys.path.insert(0, str(ORCH_DIR))
    if "journal" in sys.modules:
        del sys.modules["journal"]
    import journal as journal_mod
    journal_mod.REPO_ROOT = tmp_path
    yield tmp_path, journal_mod


class TestJournalAppend:
    def test_entry_creates_file_with_monotonic_ids(self, journal_mod):
        root, journal = journal_mod
        run_id = "run-1"
        id1 = journal.journal_entry(
            run_id, "file_write", "foo.txt",
            before_hash=None, after_hash="h1",
        )
        id2 = journal.journal_entry(
            run_id, "file_write", "bar.txt",
            before_hash=None, after_hash="h2",
        )
        assert id1 == 1
        assert id2 == 2
        path = root / ".vg" / "runs" / run_id / "journal.jsonl"
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_invalid_action_rejected(self, journal_mod):
        _, journal = journal_mod
        with pytest.raises(ValueError):
            journal.journal_entry("run-x", "bogus", "a", None, "h")

    def test_query_filter_by_action_prefix(self, journal_mod):
        _, journal = journal_mod
        run_id = "run-q"
        journal.journal_entry(run_id, "file_write", "a", None, "h1")
        journal.journal_entry(run_id, "config_change", "conf.json", "h0", "h2",
                              meta={"key": "x", "before_value": 1})
        journal.journal_entry(run_id, "file_delete", "b", "h3", "h4",
                              meta={"before_content_b64":
                                    base64.b64encode(b"x").decode()})
        got = journal.query_journal(run_id, action_prefix="file_")
        assert len(got) == 2
        assert {e["action"] for e in got} == {"file_write", "file_delete"}


class TestRollback:
    def test_rollback_file_write_restores_prior_content(self, journal_mod):
        root, journal = journal_mod
        run_id = "rb-1"
        target = root / "doc.md"
        # Pre-existing file
        target.write_text("ORIGINAL\n", encoding="utf-8")
        # Log journal with before content captured
        journal.journal_entry(
            run_id, "file_write", "doc.md",
            before_hash=None, after_hash="after",
        )
        # Simulate mutation
        target.write_text("MUTATED\n", encoding="utf-8")
        res = journal.rollback_run(run_id)
        assert res["rolled_back"] == 1
        assert target.read_text(encoding="utf-8") == "ORIGINAL\n"

    def test_rollback_file_write_deletes_newly_created(self, journal_mod):
        root, journal = journal_mod
        run_id = "rb-2"
        # No pre-existing file — capture hash None
        journal.journal_entry(
            run_id, "file_write", "new.md",
            before_hash=None, after_hash="after",
        )
        target = root / "new.md"
        target.write_text("created during run\n", encoding="utf-8")
        res = journal.rollback_run(run_id)
        assert res["rolled_back"] == 1
        assert not target.exists()

    def test_rollback_file_delete_restores(self, journal_mod):
        root, journal = journal_mod
        run_id = "rb-3"
        target = root / "kept.md"
        target.write_text("KEEP ME\n", encoding="utf-8")
        journal.journal_entry(
            run_id, "file_delete", "kept.md",
            before_hash=None, after_hash="deleted",
        )
        target.unlink()
        assert not target.exists()
        res = journal.rollback_run(run_id)
        assert res["rolled_back"] == 1
        assert target.read_text(encoding="utf-8") == "KEEP ME\n"

    def test_rollback_config_change_reverts_key(self, journal_mod):
        root, journal = journal_mod
        run_id = "rb-conf"
        conf = root / "app.json"
        conf.write_text(json.dumps({"foo": {"bar": "NEW"}}), encoding="utf-8")
        journal.journal_entry(
            run_id, "config_change", "app.json",
            before_hash=None, after_hash="h",
            meta={"key": "foo.bar", "before_value": "OLD"},
        )
        res = journal.rollback_run(run_id)
        assert res["rolled_back"] == 1
        data = json.loads(conf.read_text(encoding="utf-8"))
        assert data["foo"]["bar"] == "OLD"

    def test_rollback_config_change_removes_new_key(self, journal_mod):
        root, journal = journal_mod
        run_id = "rb-conf2"
        conf = root / "app.json"
        conf.write_text(json.dumps({"existing": 1, "new_key": 2}),
                        encoding="utf-8")
        journal.journal_entry(
            run_id, "config_change", "app.json",
            before_hash=None, after_hash="h",
            meta={"key": "new_key", "before_value": None},
        )
        res = journal.rollback_run(run_id)
        assert res["rolled_back"] == 1
        data = json.loads(conf.read_text(encoding="utf-8"))
        assert "new_key" not in data

    def test_skipped_actions_counted(self, journal_mod):
        _, journal = journal_mod
        run_id = "rb-skip"
        journal.journal_entry(run_id, "state_transition", "x", None, "h")
        journal.journal_entry(run_id, "manifest_append", "y", None, "h")
        res = journal.rollback_run(run_id)
        assert res["skipped"] == 2
        assert res["rolled_back"] == 0

    def test_dry_run_does_not_mutate(self, journal_mod):
        root, journal = journal_mod
        run_id = "rb-dry"
        target = root / "dry.md"
        target.write_text("ORIG\n", encoding="utf-8")
        journal.journal_entry(
            run_id, "file_write", "dry.md",
            before_hash=None, after_hash="after",
        )
        target.write_text("MUTATED\n", encoding="utf-8")
        res = journal.rollback_run(run_id, dry_run=True)
        assert res["rolled_back"] == 1
        assert res["dry_run"] is True
        # File is untouched in dry_run
        assert target.read_text(encoding="utf-8") == "MUTATED\n"

    def test_cross_run_isolation(self, journal_mod):
        root, journal = journal_mod
        run_a, run_b = "rb-A", "rb-B"
        a_file = root / "a.md"
        b_file = root / "b.md"
        a_file.write_text("A-ORIG\n", encoding="utf-8")
        b_file.write_text("B-ORIG\n", encoding="utf-8")
        journal.journal_entry(run_a, "file_write", "a.md", None, "h1")
        journal.journal_entry(run_b, "file_write", "b.md", None, "h2")
        a_file.write_text("A-NEW\n", encoding="utf-8")
        b_file.write_text("B-NEW\n", encoding="utf-8")
        res_a = journal.rollback_run(run_a)
        assert res_a["rolled_back"] == 1
        assert a_file.read_text(encoding="utf-8") == "A-ORIG\n"
        # B untouched
        assert b_file.read_text(encoding="utf-8") == "B-NEW\n"
        res_b = journal.rollback_run(run_b)
        assert res_b["rolled_back"] == 1
        assert b_file.read_text(encoding="utf-8") == "B-ORIG\n"

    def test_rollback_failure_reported_not_raised(self, journal_mod):
        root, journal = journal_mod
        run_id = "rb-fail"
        # Manually write a broken entry that lacks before_content_b64
        # even though before_hash is set → must fail gracefully
        path = root / ".vg" / "runs" / run_id / "journal.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "journal_id": 1, "ts": "2026-04-24T00:00:00Z",
            "run_id": run_id, "action": "file_write",
            "target_path": "missing.md",
            "before_hash": "deadbeef",
            "after_hash": "cafebabe",
            "meta": {},  # no before_content_b64
        }) + "\n", encoding="utf-8")
        res = journal.rollback_run(run_id)
        assert res["rolled_back"] == 0
        assert len(res["failed"]) == 1
        assert res["failed"][0]["action"] == "file_write"
