"""tests/test_issue_188_vg_uninstall_sibling.py — Issue #188 fix.

vg_uninstall.py crashed mid-cleanup with ValueError when a removal
candidate path lived OUTSIDE the project root (sibling-project leak
via symlink resolve(), e.g. PrintwayV3/.claude/scripts symlinked to
~/vgflow-bugfix/.claude/scripts).

Two-layer defense:
  1. _collect_paths filters paths outside root_resolved (collection-time)
  2. _backup_then_remove wraps relative_to() in try/except (per-path
     guard) — keeps update pipeline non-fatal if any path slips through.

Coverage:
  1. _backup_then_remove skips path outside root + writes warn to stderr
  2. _backup_then_remove still works on path inside root
  3. _collect_paths filters resolved paths outside root
  4. Mirror parity
"""
from __future__ import annotations
import importlib.util
import io
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
UNINSTALL = REPO / "scripts" / "vg_uninstall.py"
UNINSTALL_MIRROR = REPO / ".claude" / "scripts" / "vg_uninstall.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("vg_uninstall", UNINSTALL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_uninstall_test"] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def test_backup_then_remove_skips_path_outside_root(capsys):
    mod = _load_module()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "PrintwayV3"
        root.mkdir()
        sibling = Path(td) / "vgflow-bugfix"
        sibling.mkdir()
        target_outside = sibling / ".claude" / "scripts"
        target_outside.mkdir(parents=True)
        (target_outside / "marker").write_text("x")
        backup_root = Path(td) / "backup"
        backup_root.mkdir()

        # Should NOT raise ValueError
        mod._backup_then_remove(target_outside, root, backup_root)

        captured = capsys.readouterr()
        assert "skip path outside root" in captured.err
        # File still exists (not moved)
        assert (target_outside / "marker").exists()


def test_backup_then_remove_works_on_inside_path():
    mod = _load_module()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "project"
        root.mkdir()
        target = root / ".claude" / "scripts"
        target.mkdir(parents=True)
        (target / "marker").write_text("x")
        backup_root = Path(td) / "backup"
        backup_root.mkdir()

        mod._backup_then_remove(target, root, backup_root)

        # Moved
        assert not target.exists()
        assert (backup_root / ".claude" / "scripts" / "marker").exists()


def test_collect_paths_filters_outside_root(capsys):
    mod = _load_module()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "project"
        root.mkdir()
        # Create a path that resolves outside root via direct argument
        sibling = Path(td) / "sibling"
        sibling.mkdir()
        outside = sibling / ".claude"
        outside.mkdir()

        # Pass outside path explicitly via extra_paths
        paths = mod._collect_paths(root, purge_state=False, extra_paths=[outside])
        # outside MUST be filtered (not in result)
        resolved_outside = outside.resolve()
        assert resolved_outside not in paths


def test_mirror_in_sync():
    src = UNINSTALL.read_text(encoding="utf-8")
    mirror = UNINSTALL_MIRROR.read_text(encoding="utf-8")
    assert src == mirror, "vg_uninstall.py mirror drift"
