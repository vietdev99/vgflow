import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_dedupe_collapses_same_behavior_class(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    # 3 worker partials all same canonical key
    for i in range(3):
        (runs_dir / f"goals-worker-{i}.partial.yaml").write_text(yaml.safe_dump([{
            "view": "/x", "element_class": "row_action", "selector_hash": "abc12345",
            "lens": "lens-idor", "resource": "users", "assertion_type": "status_403",
            "priority": "critical", "action_semantic": "delete",
        }]))
    output = tmp_path / "TEST-GOALS-DISCOVERED.md"
    overflow = tmp_path / "recursive-goals-overflow.json"
    r = subprocess.run([
        sys.executable, "scripts/aggregate_recursive_goals.py",
        "--phase-dir", str(tmp_path), "--mode", "light",
        "--output", str(output), "--overflow", str(overflow),
    ], capture_output=True, text=True, cwd=REPO_ROOT)
    assert r.returncode == 0, f"stderr: {r.stderr}"
    text = output.read_text()
    assert text.count("G-RECURSE-") == 1, "Should dedupe to 1 entry"


def test_overflow_when_cap_exceeded(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    # 60 distinct behavior classes in light mode (cap=50)
    partials = []
    for i in range(60):
        partials.append({
            "view": f"/v{i}", "element_class": "row_action",
            "selector_hash": f"hash{i:04d}", "lens": "lens-idor",
            "resource": f"r{i}", "assertion_type": "x", "priority": "high",
            "action_semantic": "delete",
        })
    (runs_dir / "goals-worker-0.partial.yaml").write_text(yaml.safe_dump(partials))
    output = tmp_path / "TEST-GOALS-DISCOVERED.md"
    overflow = tmp_path / "overflow.json"
    subprocess.run([
        sys.executable, "scripts/aggregate_recursive_goals.py",
        "--phase-dir", str(tmp_path), "--mode", "light",
        "--output", str(output), "--overflow", str(overflow),
    ], check=True, cwd=REPO_ROOT)
    main_count = output.read_text().count("G-RECURSE-")
    overflow_count = len(json.loads(overflow.read_text())["goals"])
    assert main_count == 50
    assert overflow_count == 10
