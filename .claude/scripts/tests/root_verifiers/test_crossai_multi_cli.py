"""
Tests for verify-crossai-multi-cli.py — Phase L v2.5.2.

Closes CrossAI fast-fail-without-consensus loophole. Validates
result-*.xml files for valid verdict, reviewer diversity, and minimum
agreement count.

Covers:
  - No --glob and no --phase → PASS skip (CrossAI not run)
  - Empty glob (no files) + min_consensus 2 → fail
  - Single CLI result + require_all=2 → fail
  - 2 CLI agree (PASS+PASS) + 2 reviewers → PASS rc=0
  - 2 CLI disagree (PASS+BLOCK) → fail (no consensus)
  - Reviewer-diversity check: same reviewer twice → fail
  - Malformed XML → graceful, no crash
  - Verdict schema: top-level PASS|WARN per v2.6 dispatch shim
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-crossai-multi-cli.py"


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


def _make_result(path: Path, verdict: str, reviewer: str,
                 score: float = 8.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"<crossai_review>\n"
        f"  <verdict>{verdict}</verdict>\n"
        f"  <reviewer>{reviewer}</reviewer>\n"
        f"  <score>{score}</score>\n"
        f"</crossai_review>\n",
        encoding="utf-8",
    )


class TestCrossaiMultiCli:
    def test_no_args_passes_skip(self, tmp_path):
        # No --glob and no --phase → safe-skip (PASS) per v2.6
        r = _run(["--json"], tmp_path)
        assert r.returncode == 0
        v = _verdict(r.stdout)
        assert v == "PASS"

    def test_empty_glob_fails_min_consensus(self, tmp_path):
        crossai_dir = tmp_path / "crossai"
        crossai_dir.mkdir()
        glob = str(crossai_dir / "result-*.xml")
        r = _run(["--glob", glob, "--min-consensus", "2", "--json"], tmp_path)
        # No files → 0 agreement < 2 required → rc=1, verdict=WARN
        assert r.returncode == 1
        v = _verdict(r.stdout)
        assert v == "WARN"

    def test_require_all_not_met_fails(self, tmp_path):
        crossai_dir = tmp_path / "crossai"
        _make_result(crossai_dir / "result-codex.xml", "pass", "codex-cli")
        glob = str(crossai_dir / "result-*.xml")
        r = _run([
            "--glob", glob,
            "--require-all", "3",
            "--min-consensus", "1",
            "--json",
        ], tmp_path)
        assert r.returncode == 1, \
            f"require-all=3 with 1 file → rc=1, got {r.returncode}"

    def test_two_clis_agree_passes(self, tmp_path):
        crossai_dir = tmp_path / "crossai"
        _make_result(crossai_dir / "result-codex.xml", "pass", "codex-cli")
        _make_result(crossai_dir / "result-gemini.xml", "pass", "gemini-cli")
        glob = str(crossai_dir / "result-*.xml")
        r = _run(["--glob", glob, "--min-consensus", "2", "--json"], tmp_path)
        assert r.returncode == 0, \
            f"2-CLI consensus → rc=0, got {r.returncode}, stdout={r.stdout[:300]}"
        v = _verdict(r.stdout)
        assert v == "PASS"

    def test_clis_disagree_fails(self, tmp_path):
        crossai_dir = tmp_path / "crossai"
        _make_result(crossai_dir / "result-codex.xml", "pass", "codex-cli")
        _make_result(crossai_dir / "result-gemini.xml", "block", "gemini-cli")
        glob = str(crossai_dir / "result-*.xml")
        r = _run(["--glob", glob, "--min-consensus", "2", "--json"], tmp_path)
        # Max agreement = 1 (each verdict has 1 vote) < 2 required → fail
        assert r.returncode == 1
        v = _verdict(r.stdout)
        assert v == "WARN"

    def test_reviewer_diversity_check(self, tmp_path):
        crossai_dir = tmp_path / "crossai"
        # Same reviewer twice → diversity fail
        _make_result(crossai_dir / "result-1.xml", "pass", "same-cli")
        _make_result(crossai_dir / "result-2.xml", "pass", "same-cli")
        glob = str(crossai_dir / "result-*.xml")
        r = _run(["--glob", glob, "--min-consensus", "2", "--json"], tmp_path)
        # Consensus reached but diversity=1 < 2 → fail
        assert r.returncode == 1, \
            f"diversity check should fail, got {r.returncode}"
        data = json.loads(r.stdout)
        checks = {f["check"] for f in data.get("failures", [])}
        assert "reviewer_diversity" in checks

    def test_malformed_xml_no_crash(self, tmp_path):
        crossai_dir = tmp_path / "crossai"
        crossai_dir.mkdir()
        (crossai_dir / "result-bad.xml").write_text(
            "not really xml at all", encoding="utf-8")
        glob = str(crossai_dir / "result-*.xml")
        r = _run(["--glob", glob, "--json"], tmp_path)
        assert "Traceback" not in r.stderr, \
            f"crash on bad XML: {r.stderr[-300:]}"

    def test_verdict_schema_canonical(self, tmp_path):
        crossai_dir = tmp_path / "crossai"
        _make_result(crossai_dir / "result-codex.xml", "pass", "codex")
        _make_result(crossai_dir / "result-gemini.xml", "pass", "gemini")
        glob = str(crossai_dir / "result-*.xml")
        r = _run(["--glob", glob, "--json"], tmp_path)
        data = json.loads(r.stdout)
        assert data.get("validator") == "verify-crossai-multi-cli"
        assert data.get("verdict") in {"PASS", "BLOCK", "WARN"}
        assert data["verdict"] not in {"FAIL", "OK"}
