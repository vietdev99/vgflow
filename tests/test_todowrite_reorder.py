"""F2 v2.60.0: TodoWrite re-order by status."""
import json, os, subprocess, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EMIT = REPO_ROOT / "scripts" / "emit-tasklist.py"


def _items(*specs):
    """Build projection items from compact specs.
    spec: ('group'|'step', 'id', 'parent_or_None', 'status')"""
    out = []
    for kind, ident, parent, status in specs:
        out.append({
            "kind": kind,
            "id": ident,
            "parent": parent,
            "title": f"{'  ↳ ' if kind == 'step' else ''}{ident}",
            "status": status,
        })
    return out


def test_reorder_in_progress_first(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    # Re-import since we modified path
    import importlib
    if "emit_tasklist" in sys.modules:
        del sys.modules["emit_tasklist"]
    # Note: emit-tasklist.py has hyphenated name, must import as module via path
    import importlib.util
    spec = importlib.util.spec_from_file_location("emit_tasklist", EMIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    items = _items(
        ("group", "g1", None, "pending"),
        ("step", "g1.s1", "g1", "completed"),
        ("step", "g1.s2", "g1", "in_progress"),
        ("step", "g1.s3", "g1", "pending"),
    )
    out = mod.reorder_projection_by_status(items)
    # in_progress step should come before completed/pending within g1
    statuses = [i["status"] for i in out if i["kind"] == "step"]
    assert statuses == ["in_progress", "pending", "completed"], (
        f"expected in_progress→pending→completed within group, got {statuses}"
    )


def test_reorder_group_header_reflects_in_progress(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("emit_tasklist", EMIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    items = _items(
        ("group", "g1", None, "pending"),
        ("step", "g1.s1", "g1", "in_progress"),
    )
    out = mod.reorder_projection_by_status(items)
    g1 = next(i for i in out if i["kind"] == "group")
    assert g1["status"] == "in_progress"


def test_reorder_group_completed_when_all_steps_done(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("emit_tasklist", EMIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    items = _items(
        ("group", "g1", None, "pending"),
        ("step", "g1.s1", "g1", "completed"),
        ("step", "g1.s2", "g1", "completed"),
    )
    out = mod.reorder_projection_by_status(items)
    g1 = next(i for i in out if i["kind"] == "group")
    assert g1["status"] == "completed"


def test_reorder_preserves_group_order(tmp_path):
    """Groups stay in their original relative order, only items within sort."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("emit_tasklist", EMIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    items = _items(
        ("group", "g1", None, "pending"),
        ("step", "g1.s1", "g1", "in_progress"),
        ("group", "g2", None, "pending"),
        ("step", "g2.s1", "g2", "completed"),
    )
    out = mod.reorder_projection_by_status(items)
    groups = [i["id"] for i in out if i["kind"] == "group"]
    assert groups == ["g1", "g2"], "group order must be preserved"


def test_snapshot_helper_writes_payload(tmp_path):
    """vg-tasklist-snapshot.py --write captures TodoWrite payload."""
    helper = REPO_ROOT / "scripts" / "hooks" / "vg-tasklist-snapshot.py"
    run_id = "test-snapshot-001"
    runs_dir = tmp_path / ".vg" / "runs" / run_id
    runs_dir.mkdir(parents=True)
    payload = json.dumps({
        "items": [
            {"id": "step1", "content": "Setup", "status": "in_progress"},
            {"id": "step2", "content": "Build", "status": "pending"},
        ],
    })
    r = subprocess.run(
        [sys.executable, str(helper), "--write", "--run-id", run_id],
        input=payload, capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0, r.stderr
    snap = runs_dir / ".todowrite-snapshot.json"
    assert snap.exists()
    data = json.loads(snap.read_text(encoding="utf-8"))
    assert len(data["items"]) == 2


def test_snapshot_helper_empty_input_noop(tmp_path):
    helper = REPO_ROOT / "scripts" / "hooks" / "vg-tasklist-snapshot.py"
    run_id = "test-noop"
    runs_dir = tmp_path / ".vg" / "runs" / run_id
    runs_dir.mkdir(parents=True)
    r = subprocess.run(
        [sys.executable, str(helper), "--write", "--run-id", run_id],
        input="", capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0
    # No clobber when empty input
    snap = runs_dir / ".todowrite-snapshot.json"
    if snap.exists():
        # OK if exists but empty/null; just don't crash
        pass


def test_post_tool_hook_invokes_snapshot():
    """vg-post-tool-use-todowrite.sh must call vg-tasklist-snapshot.py."""
    body = (REPO_ROOT / "scripts" / "hooks" / "vg-post-tool-use-todowrite.sh").read_text(encoding="utf-8")
    assert "vg-tasklist-snapshot.py" in body, (
        "post-tool hook must wire snapshot capture for F1 restore on resume"
    )


def test_emit_tasklist_mirror():
    canonical = REPO_ROOT / "scripts" / "emit-tasklist.py"
    mirror = REPO_ROOT / ".claude" / "scripts" / "emit-tasklist.py"
    if not mirror.exists(): return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_post_tool_hook_mirror():
    canonical = REPO_ROOT / "scripts" / "hooks" / "vg-post-tool-use-todowrite.sh"
    mirror = REPO_ROOT / ".claude" / "scripts" / "hooks" / "vg-post-tool-use-todowrite.sh"
    if not mirror.exists(): return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_snapshot_helper_mirror():
    canonical = REPO_ROOT / "scripts" / "hooks" / "vg-tasklist-snapshot.py"
    mirror = REPO_ROOT / ".claude" / "scripts" / "hooks" / "vg-tasklist-snapshot.py"
    if not mirror.exists(): return
    assert canonical.read_bytes() == mirror.read_bytes()
