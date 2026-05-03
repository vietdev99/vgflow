"""
Tests for verify-context-refs.py — Phase C v2.5.

Scoped-mode executor isolation check. When context_injection.mode=scoped,
every PLAN task MUST carry <context-refs>P{phase}.D-XX</context-refs>
listing decision IDs. Stale or missing refs → WARN (advisory).

Covers:
  - Full mode → PASS immediately (no enforcement)
  - Scoped mode but no phase dir → PASS
  - Scoped mode, phase dir, no PLAN files → PASS
  - All tasks have valid refs → PASS
  - Tasks missing <context-refs> → WARN (rc=0 but verdict=WARN)
  - Tasks have refs to unknown D-XX → WARN
  - Verdict schema canonical
  - Subprocess resilience: malformed CONTEXT.md
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-context-refs.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _verdict(stdout: str) -> str | None:
    try:
        return json.loads(stdout).get("verdict")
    except (json.JSONDecodeError, AttributeError):
        return None


def _set_mode(tmp_path: Path, mode: str) -> None:
    cfg = tmp_path / ".claude" / "vg.config.md"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        f"# vg.config\nmode: '{mode}'\nphase_cutover: 14\n",
        encoding="utf-8",
    )


def _make_phase(tmp_path: Path, plan_text: str,
                context_text: str = "",
                slug: str = "07.5-ctx") -> Path:
    pdir = tmp_path / ".vg" / "phases" / slug
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "PLAN.md").write_text(plan_text, encoding="utf-8")
    if context_text:
        (pdir / "CONTEXT.md").write_text(context_text, encoding="utf-8")
    return pdir


class TestContextRefs:
    def test_full_mode_passes(self, tmp_path):
        _set_mode(tmp_path, "full")
        _make_phase(tmp_path, "## Task 1\nSome task.\n")
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 0
        assert _verdict(r.stdout) == "PASS"

    def test_scoped_mode_no_phase_passes(self, tmp_path):
        _set_mode(tmp_path, "scoped")
        # No phase dir created
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 0

    def test_scoped_no_plans_passes(self, tmp_path):
        _set_mode(tmp_path, "scoped")
        # Phase dir but no PLAN.md
        pdir = tmp_path / ".vg" / "phases" / "07.5-ctx"
        pdir.mkdir(parents=True)
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 0

    def test_scoped_all_refs_present_passes(self, tmp_path):
        _set_mode(tmp_path, "scoped")
        _make_phase(
            tmp_path,
            "## Task 1\n<context-refs>D-01, D-02</context-refs>\nDo X.\n"
            "## Task 2\n<context-refs>D-03</context-refs>\nDo Y.\n",
            context_text="# Context\n- D-01: foo\n- D-02: bar\n- D-03: baz\n",
        )
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 0, \
            f"all refs present → PASS, rc={r.returncode}, stdout={r.stdout[:300]}"
        assert _verdict(r.stdout) == "PASS"

    def test_scoped_missing_refs_warns(self, tmp_path):
        _set_mode(tmp_path, "scoped")
        _make_phase(
            tmp_path,
            "## Task 1\nNo refs declared.\n## Task 2\nAlso no refs.\n",
        )
        r = _run(["--phase", "07.5"], tmp_path)
        # WARN → rc=0 (advisory)
        assert r.returncode == 0
        v = _verdict(r.stdout)
        assert v == "WARN", f"expected WARN, got {v}, stdout={r.stdout[:300]}"

    def test_scoped_stale_refs_warns(self, tmp_path):
        _set_mode(tmp_path, "scoped")
        _make_phase(
            tmp_path,
            "## Task 1\n<context-refs>D-99, D-100</context-refs>\nBogus refs.\n",
            context_text="# Context\n- D-01: foo\n",
        )
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 0
        v = _verdict(r.stdout)
        assert v == "WARN", f"stale refs → WARN, got {v}"
        data = json.loads(r.stdout)
        types = {ev.get("type") for ev in data.get("evidence", [])}
        assert "context_refs_stale" in types

    def test_verdict_schema_canonical(self, tmp_path):
        _set_mode(tmp_path, "scoped")
        _make_phase(tmp_path, "## Task 1\nbody.\n")
        r = _run(["--phase", "07.5"], tmp_path)
        data = json.loads(r.stdout)
        v = data.get("verdict")
        if v is not None:
            assert v in {"PASS", "BLOCK", "WARN"}
        assert data["verdict"] not in {"FAIL", "OK"}

    def test_corrupt_context_no_crash(self, tmp_path):
        _set_mode(tmp_path, "scoped")
        _make_phase(
            tmp_path,
            "## Task 1\n<context-refs>D-01</context-refs>\n",
            context_text="\xff\xfe\x00garbage\x00",
        )
        r = _run(["--phase", "07.5"], tmp_path)
        assert "Traceback" not in r.stderr, \
            f"crash on bad CONTEXT: {r.stderr[-300:]}"
