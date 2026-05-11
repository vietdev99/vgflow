"""Task 5.6 — /vg:learn --consolidate skill mode tests.

Verifies that the canonical /vg:learn skill documents the --consolidate
mode wired to bootstrap-consolidate.py orchestrator, and that the
.claude mirror stays byte-identical.
"""
from pathlib import Path


def test_learn_md_documents_consolidate_mode():
    f = Path("commands/vg/learn.md").read_text(encoding="utf-8")
    assert "--consolidate" in f, "learn.md must document --consolidate flag"
    assert "bootstrap-consolidate" in f, "learn.md must invoke bootstrap-consolidate.py"


def test_learn_md_documents_dry_run_default():
    f = Path("commands/vg/learn.md").read_text(encoding="utf-8")
    # Either explicit "dry-run" or "--apply" flag mentioned
    assert "dry-run" in f.lower() or "--apply" in f


def test_learn_md_invokes_4_phases():
    f = Path("commands/vg/learn.md").read_text(encoding="utf-8")
    # Either lists all 4 phases or invokes --consolidate-all
    has_all_phases = all(
        p in f.lower() for p in ["orient", "gather", "consolidate", "prune"]
    )
    has_orchestrator = "--consolidate-all" in f
    assert has_all_phases or has_orchestrator


def test_learn_md_gate_check_documented():
    f = Path("commands/vg/learn.md").read_text(encoding="utf-8")
    assert "--check-gate" in f or "24h" in f or "session" in f.lower()


def test_mirror_byte_identical():
    canonical = Path("commands/vg/learn.md").read_bytes()
    mirror = Path(".claude/commands/vg/learn.md").read_bytes()
    assert canonical == mirror


def test_project_codex_skill_mirror_absent_global_only():
    assert Path("codex-skills/vg-learn/SKILL.md").is_file()
    assert not Path(".codex/skills/vg-learn/SKILL.md").exists()


def test_codex_skill_documents_consolidate_mode():
    f = Path("codex-skills/vg-learn/SKILL.md").read_text(encoding="utf-8")
    assert "--consolidate" in f, "Codex SKILL.md must document --consolidate flag"
    assert "bootstrap-consolidate" in f, "Codex SKILL.md must reference bootstrap-consolidate.py"


def test_bootstrap_consolidate_has_consolidate_all_subcommand():
    f = Path("scripts/bootstrap-consolidate.py").read_text(encoding="utf-8")
    assert "--consolidate-all" in f, "orchestrator subcommand must be defined"


def test_bootstrap_consolidate_mirror_byte_identical():
    canonical = Path("scripts/bootstrap-consolidate.py").read_bytes()
    mirror = Path(".claude/scripts/bootstrap-consolidate.py").read_bytes()
    assert canonical == mirror


def test_consolidate_all_lock_always_released_on_exception(tmp_path, monkeypatch):
    """Lock file MUST be released even if a phase raises mid-run.

    This is the hard invariant called out by the orchestrator design:
    `try/finally` around the 4 phases so a crash never strands the lock.
    """
    import os
    import sys
    import importlib.util

    # Force VG_DREAMS_GATE_HOURS=0 + VG_DREAMS_GATE_SESSIONS=0 so the gate
    # opens against our fresh tmp state dir.
    monkeypatch.setenv("VG_BOOTSTRAP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("VG_DREAMS_GATE_HOURS", "0")
    monkeypatch.setenv("VG_DREAMS_GATE_SESSIONS", "-1")

    spec = importlib.util.spec_from_file_location(
        "bootstrap_consolidate_t56",
        Path("scripts/bootstrap-consolidate.py").resolve(),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Monkey-patch orient to raise — verifies finally: release_lock runs.
    def boom(_state_dir):
        raise RuntimeError("simulated phase crash")

    monkeypatch.setattr(mod, "orient", boom)

    rc = mod.main(["bootstrap-consolidate.py", "--consolidate-all", "--json"])

    lock_file = tmp_path / ".consolidation.lock"
    assert not lock_file.exists(), \
        "lock must be released even when a phase raises"
    # rc must be non-zero on crash
    assert rc != 0


def test_consolidate_all_gate_closed_returns_zero(tmp_path, monkeypatch):
    """Gate-closed exit must be rc=0 (not an error — just no work to do)."""
    import importlib.util
    import json
    import time

    monkeypatch.setenv("VG_BOOTSTRAP_STATE_DIR", str(tmp_path))
    # Force gate closed with a recent state.json
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "state.json").write_text(
        json.dumps({"last_run_ts": time.time(), "sessions_since_last": 0}),
        encoding="utf-8",
    )

    spec = importlib.util.spec_from_file_location(
        "bootstrap_consolidate_t56_gate",
        Path("scripts/bootstrap-consolidate.py").resolve(),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    rc = mod.main(["bootstrap-consolidate.py", "--consolidate-all", "--json"])
    assert rc == 0, "gate-closed must exit 0 (no-op, not an error)"


def test_consolidate_all_dry_run_does_not_modify_overlay(tmp_path, monkeypatch):
    """Default mode (no --apply) must not write to overlay.yml."""
    import importlib.util

    monkeypatch.setenv("VG_BOOTSTRAP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("VG_DREAMS_GATE_HOURS", "0")
    monkeypatch.setenv("VG_DREAMS_GATE_SESSIONS", "-1")

    overlay = tmp_path / "overlay.yml"
    tmp_path.mkdir(parents=True, exist_ok=True)
    overlay.write_text("# pristine\n", encoding="utf-8")
    pristine = overlay.read_bytes()

    spec = importlib.util.spec_from_file_location(
        "bootstrap_consolidate_t56_dryrun",
        Path("scripts/bootstrap-consolidate.py").resolve(),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    rc = mod.main(["bootstrap-consolidate.py", "--consolidate-all", "--json"])
    # Whether gate opens or not, overlay should remain untouched in dry-run.
    assert overlay.read_bytes() == pristine, \
        "dry-run mode must NEVER modify overlay.yml"
    assert rc == 0
