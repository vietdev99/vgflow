"""End-to-end: golden fixture phase produces expected L4a-i + L4a-ii results."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "build-fix-loop-golden" / "phase"


def test_l4a_i_detects_fe_be_gap(tmp_path: Path) -> None:
    out = tmp_path / "ev.json"
    result = subprocess.run([
        "python3", str(REPO / "scripts" / "validators" / "verify-fe-be-call-graph.py"),
        "--fe-root", str(FIXTURE / "fe"),
        "--be-root", str(FIXTURE / "be"),
        "--phase", "golden-test",
        "--evidence-out", str(out),
    ], capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert ev["category"] == "fe_be_call_graph"
    assert "GET" in ev["summary"]


def test_classifier_marks_gap_in_scope(tmp_path: Path) -> None:
    """Run L4a-i, then feed evidence into classifier — expect IN_SCOPE."""
    ev_path = tmp_path / "ev.json"
    subprocess.run([
        "python3", str(REPO / "scripts" / "validators" / "verify-fe-be-call-graph.py"),
        "--fe-root", str(FIXTURE / "fe"),
        "--be-root", str(FIXTURE / "be"),
        "--phase", "golden-test",
        "--evidence-out", str(ev_path),
    ], capture_output=True, text=True)

    cls = subprocess.run([
        "python3", str(REPO / "scripts" / "classify-build-warning.py"),
        "--phase-dir", str(FIXTURE),
        "--warning", str(ev_path),
    ], capture_output=True, text=True, check=False)
    assert cls.returncode == 0, cls.stderr
    out = json.loads(cls.stdout)
    # Fixture: FE file path appears in PLAN/task-39.md → R3 hit → IN_SCOPE
    assert out["classification"] == "IN_SCOPE"


def test_phase_ownership_excludes_outside_files() -> None:
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from phase_ownership import is_owned  # type: ignore

    assert is_owned("tests/fixtures/build-fix-loop-golden/phase/be/router.ts", FIXTURE)
    assert not is_owned("apps/api/src/middleware/error.ts", FIXTURE)
    sys.path.remove(str(REPO / "scripts" / "lib"))
