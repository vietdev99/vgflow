"""scripts/review_batch.py — multi-phase orchestrator (Task 26d).

Args under test:
  --phases <p1,p2,...>     explicit list
  --milestone <M>          read .vg/phases/* aligned with milestone (via ROADMAP.md)
  --since <git-sha>        diff sha → derive list of touched phases
  --recursion              forwarded
  --probe-mode             forwarded
  --target-env             forwarded
  --non-interactive        forwarded

Per-phase failures must NOT abort the batch — log to BATCH-FINDINGS-*.json
and continue.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "review_batch.py"


def _seed_phases(tmp_path: Path, names: list[str]) -> Path:
    """Create .vg/phases/<name>/ each with a minimal .phase-profile."""
    root = tmp_path / "repo"
    (root / ".vg" / "phases").mkdir(parents=True)
    for n in names:
        p = root / ".vg" / "phases" / n
        p.mkdir()
        (p / ".phase-profile").write_text(
            "phase_profile: feature\nsurface: ui\n", encoding="utf-8")
    return root


def _run(repo: Path, *args: str, fake_review: Path | None = None,
         env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    if fake_review is not None:
        # review_batch.py honors VG_REVIEW_CMD as the per-phase entry point.
        env["VG_REVIEW_CMD"] = str(fake_review)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, env=env, cwd=str(repo),
    )


def _make_fake_review(tmp_path: Path, *, exit_codes: dict[str, int]) -> Path:
    """Create a fake review.py shim — exits per-phase per the supplied map."""
    fake = tmp_path / "fake_review.py"
    fake.write_text(
        "import sys, json\n"
        "ec_map = " + json.dumps(exit_codes) + "\n"
        "phase = None\n"
        "i = 0\n"
        "while i < len(sys.argv):\n"
        "    a = sys.argv[i]\n"
        "    if a == '--phase':\n"
        "        phase = sys.argv[i+1]\n"
        "    elif a.startswith('--phase='):\n"
        "        phase = a.split('=', 1)[1]\n"
        "    i += 1\n"
        "exit_code = ec_map.get(str(phase), 0)\n"
        "print(json.dumps({'phase': phase, 'argv': sys.argv[1:]}))\n"
        "sys.exit(exit_code)\n",
        encoding="utf-8",
    )
    return fake


def test_sequential_runs_each_phase(tmp_path: Path) -> None:
    repo = _seed_phases(tmp_path, ["1", "2", "3"])
    fake = _make_fake_review(tmp_path, exit_codes={"1": 0, "2": 0, "3": 0})
    r = _run(repo, "--phases", "1,2,3", fake_review=fake)
    assert r.returncode == 0, r.stderr + r.stdout
    findings_files = list(repo.glob("BATCH-FINDINGS-*.json"))
    assert findings_files, "no BATCH-FINDINGS-*.json written"
    payload = json.loads(findings_files[0].read_text(encoding="utf-8"))
    assert {p["phase"] for p in payload["phases"]} == {"1", "2", "3"}
    assert all(p["exit_code"] == 0 for p in payload["phases"])


def test_failure_continues_batch(tmp_path: Path) -> None:
    repo = _seed_phases(tmp_path, ["1", "2", "3"])
    fake = _make_fake_review(tmp_path, exit_codes={"1": 0, "2": 7, "3": 0})
    r = _run(repo, "--phases", "1,2,3", fake_review=fake)
    # Per spec: per-phase fail logs + continues, batch exit non-zero overall
    # but every phase still ran.
    payload = json.loads(next(repo.glob("BATCH-FINDINGS-*.json"))
                          .read_text(encoding="utf-8"))
    phases = {p["phase"]: p["exit_code"] for p in payload["phases"]}
    assert phases == {"1": 0, "2": 7, "3": 0}, phases
    # Aggregated exit != 0 because one phase failed.
    assert r.returncode != 0


def test_aggregate_findings_path(tmp_path: Path) -> None:
    repo = _seed_phases(tmp_path, ["1"])
    fake = _make_fake_review(tmp_path, exit_codes={"1": 0})
    r = _run(repo, "--phases", "1", fake_review=fake,
             env_extra={"VG_NON_INTERACTIVE": "1"})
    findings = next(repo.glob("BATCH-FINDINGS-*.json"))
    payload = json.loads(findings.read_text(encoding="utf-8"))
    assert "started_at" in payload and "finished_at" in payload
    assert payload["phases"][0]["phase"] == "1"


def test_review_cmd_uses_env_var_first(tmp_path: Path, monkeypatch) -> None:
    """VG_REVIEW_CMD env var wins outright — even when claude CLI is on PATH."""
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("review_batch_mod", SCRIPT)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)

    fake_script = tmp_path / "fake_review.py"
    fake_script.write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("VG_REVIEW_CMD", str(fake_script))
    # Even if claude is "available", env var should win.
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/claude")
    cmd = mod.resolve_review_cmd()
    assert cmd == [sys.executable, str(fake_script)]


def test_review_cmd_falls_back_to_claude_cli(tmp_path: Path, monkeypatch) -> None:
    """No env var → look for `claude` on PATH → emit ['claude', '-p', '/vg:review']."""
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("review_batch_mod", SCRIPT)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.delenv("VG_REVIEW_CMD", raising=False)
    monkeypatch.setattr(mod.shutil, "which",
                        lambda name: "/usr/bin/claude" if name == "claude" else None)
    cmd = mod.resolve_review_cmd()
    assert cmd == ["claude", "-p", "/vg:review"]


def test_review_cmd_hard_fails_when_nothing_resolved(monkeypatch) -> None:
    """No env var, no claude CLI, no vg.review module → SystemExit with helpful msg."""
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("review_batch_mod", SCRIPT)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.delenv("VG_REVIEW_CMD", raising=False)
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    # Force the vg.review import probe to fail.
    import importlib.util as _real_ilu
    monkeypatch.setattr(_real_ilu, "find_spec", lambda name: None)

    with pytest.raises(SystemExit) as excinfo:
        mod.resolve_review_cmd()
    msg = str(excinfo.value)
    assert "Cannot resolve" in msg
    assert "VG_REVIEW_CMD" in msg
    assert "claude" in msg


def test_review_cmd_env_var_with_args(tmp_path: Path, monkeypatch) -> None:
    """Env var with multi-token value (e.g. wrapper + flags) is shlex-split verbatim."""
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("review_batch_mod", SCRIPT)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.setenv("VG_REVIEW_CMD", "node my-shim.js --quiet")
    cmd = mod.resolve_review_cmd()
    assert cmd == ["node", "my-shim.js", "--quiet"]


def test_milestone_resolution(tmp_path: Path) -> None:
    """--milestone reads ROADMAP.md to enumerate phases."""
    repo = _seed_phases(tmp_path, ["7", "8", "9"])
    (repo / "ROADMAP.md").write_text(
        "# Roadmap\n## Milestone M2\n- Phase 7 — Foo\n- Phase 8 — Bar\n"
        "## Milestone M3\n- Phase 9 — Baz\n",
        encoding="utf-8",
    )
    fake = _make_fake_review(tmp_path, exit_codes={"7": 0, "8": 0, "9": 0})
    r = _run(repo, "--milestone", "M2", fake_review=fake)
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(next(repo.glob("BATCH-FINDINGS-*.json"))
                          .read_text(encoding="utf-8"))
    phases = sorted(p["phase"] for p in payload["phases"])
    assert phases == ["7", "8"], phases
