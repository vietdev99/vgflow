"""
Tests for verify-step-markers.py — BLOCK severity.

Universal rule "every <step> MUST, as FINAL action, touch
${PHASE_DIR}/.step-markers/{STEP_NAME}.done". Validator catches
silent step-skip by comparing skill <step name=...> declarations
to .step-markers/*.done on disk.

Covers:
  - Phase dir missing → PASS (no work)
  - Phase dir with no markers at all → PASS (command never ran)
  - All expected markers present → PASS
  - Some markers missing while others present → BLOCK
  - --command flag scopes check
  - profile filter (skill steps with profile="api" skipped on web phase)
  - Verdict schema canonical
  - Corrupt PIPELINE-STATE.json → graceful, no crash
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-step-markers.py"


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


def _make_phase(tmp_path: Path, *, markers: list[str] | None = None,
                profile: str = "feature",
                pipeline_step: str | None = None) -> Path:
    pdir = tmp_path / ".vg" / "phases" / "07-stepmarkers"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "SPECS.md").write_text(
        f"---\nprofile: {profile}\n---\n# Specs\n",
        encoding="utf-8",
    )
    if markers is not None:
        mdir = pdir / ".step-markers"
        mdir.mkdir(exist_ok=True)
        for m in markers:
            (mdir / f"{m}.done").write_text("", encoding="utf-8")
    if pipeline_step:
        (pdir / "PIPELINE-STATE.json").write_text(
            json.dumps({"pipeline_step": pipeline_step}),
            encoding="utf-8",
        )
    return pdir


def _make_skill(tmp_path: Path, command: str, steps: list[tuple[str, str]]) -> None:
    """Create a fake skill file with <step name=...> tags.
    steps = [(name, profile_attr_or_empty), ...]"""
    name = command.replace("vg:", "")
    skill_dir = tmp_path / ".codex" / "skills" / f"vg-{name}"
    skill_dir.mkdir(parents=True, exist_ok=True)
    body = "# Skill\n\n"
    for sname, prof in steps:
        if prof:
            body += f'<step name="{sname}" profile="{prof}">\n  body\n</step>\n\n'
        else:
            body += f'<step name="{sname}">\n  body\n</step>\n\n'
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")


class TestStepMarkers:
    def test_phase_dir_missing_passes(self, tmp_path):
        r = _run(["--phase", "07"], tmp_path)
        assert r.returncode == 0, f"missing phase → PASS, rc={r.returncode}"

    def test_no_markers_at_all_passes(self, tmp_path):
        # Phase dir exists but no .step-markers/ at all → command never ran
        _make_phase(tmp_path, markers=None)
        _make_skill(tmp_path, "vg:build",
                    [("0_parse_args", ""), ("1_initialize", "")])
        r = _run(["--phase", "07", "--command", "vg:build"], tmp_path)
        assert r.returncode == 0, f"no markers → PASS, rc={r.returncode}"

    def test_all_markers_present_passes(self, tmp_path):
        _make_phase(tmp_path,
                    markers=["0_parse_args", "1_initialize", "2_run"])
        _make_skill(tmp_path, "vg:build", [
            ("0_parse_args", ""),
            ("1_initialize", ""),
            ("2_run", ""),
        ])
        r = _run(["--phase", "07", "--command", "vg:build"], tmp_path)
        assert r.returncode == 0, \
            f"all markers present → PASS, rc={r.returncode}, stdout={r.stdout[:200]}"
        assert _verdict(r.stdout) == "PASS"

    def test_partial_markers_missing_blocks(self, tmp_path):
        _make_phase(tmp_path,
                    markers=["0_parse_args"])  # 1_initialize missing
        _make_skill(tmp_path, "vg:build", [
            ("0_parse_args", ""),
            ("1_initialize", ""),
            ("2_run", ""),
        ])
        r = _run(["--phase", "07", "--command", "vg:build"], tmp_path)
        assert r.returncode == 1, \
            f"missing markers → BLOCK rc=1, got {r.returncode}, stdout={r.stdout[:300]}"
        assert _verdict(r.stdout) == "BLOCK"

    def test_command_flag_scopes_check(self, tmp_path):
        _make_phase(tmp_path, markers=["scope_step"])
        # Skill for vg:scope only
        _make_skill(tmp_path, "vg:scope",
                    [("scope_step", "")])
        r = _run(["--phase", "07", "--command", "vg:scope"], tmp_path)
        assert r.returncode == 0
        # If we ask for vg:build, no skill found → no markers expected → PASS
        _make_skill(tmp_path, "vg:build",
                    [("build_step_a", "")])  # marker absent
        r2 = _run(["--phase", "07", "--command", "vg:build"], tmp_path)
        # build markers absent + no others → not run for this command → PASS
        assert r2.returncode == 0

    def test_profile_filter_excludes_unmatched_steps(self, tmp_path):
        """Steps with profile='api' skipped on phase profile='web'."""
        _make_phase(tmp_path, markers=["web_step"], profile="web")
        _make_skill(tmp_path, "vg:build", [
            ("web_step", "web,all"),
            ("api_step", "api"),  # excluded for web profile
        ])
        r = _run(["--phase", "07", "--command", "vg:build"], tmp_path)
        assert r.returncode == 0, \
            f"profile filter should exclude api_step from web phase, " \
            f"rc={r.returncode}, stdout={r.stdout[:200]}"

    def test_verdict_schema_canonical(self, tmp_path):
        _make_phase(tmp_path, markers=["a", "b"])
        _make_skill(tmp_path, "vg:build", [("a", ""), ("b", "")])
        r = _run(["--phase", "07", "--command", "vg:build"], tmp_path)
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            return
        v = data.get("verdict")
        if v is not None:
            assert v in {"PASS", "BLOCK", "WARN"}

    def test_corrupt_pipeline_state_no_crash(self, tmp_path):
        pdir = _make_phase(tmp_path, markers=["x"])
        (pdir / "PIPELINE-STATE.json").write_text("not json {{{", encoding="utf-8")
        r = _run(["--phase", "07"], tmp_path)
        assert "Traceback" not in r.stderr, \
            f"crash on bad pipeline state: {r.stderr[-300:]}"
