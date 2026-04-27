"""
Phase 16 Wave 5 — E2E acceptance smoke for Task Fidelity Lock.

Verifies every Phase 16 deliverable shipped across waves 0-4 is wired
correctly. 8 acceptance dimensions:

  1. Validators (3) — task-schema, crossai-output, task-fidelity
  2. Helpers       — task_hasher.py exports + canonical normalization
  3. Parser        — extract_task_section_v2 + extract_all_tasks
  4. Build wire    — build.md persists .meta.json + wires task-fidelity audit
  5. Schema gate   — verify-task-schema.py mode behavior across formats
  6. Body cap      — vg_completeness_check Check E (D-03)
  7. R4 caps       — pre-executor-check.py applied_caps (D-04)
  8. Fidelity 3-way — verify-task-fidelity.py PASS/WARN/BLOCK behavior (D-06)

Run: python -m pytest scripts/tests/root_verifiers/test_phase16_acceptance.py -v
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATORS = REPO_ROOT / "scripts" / "validators"
SCRIPTS = REPO_ROOT / "scripts"
COMMANDS = REPO_ROOT / "commands" / "vg"
SHARED = COMMANDS / "_shared"
FIXTURES = REPO_ROOT / "fixtures" / "phase16"
TASK_HASHER = SCRIPTS / "lib" / "task_hasher.py"


# ─── 1. Validators ────────────────────────────────────────────────────────

PHASE16_VALIDATOR_IDS = ["task-schema", "crossai-output", "task-fidelity"]


class TestPhase16Validators:
    @pytest.fixture(scope="class")
    def registry_text(self):
        return (VALIDATORS / "registry.yaml").read_text(encoding="utf-8")

    @pytest.mark.parametrize("vid", PHASE16_VALIDATOR_IDS)
    def test_registry_entry_present(self, vid, registry_text):
        assert re.search(
            rf"^\s*-\s*id:\s*['\"]?{re.escape(vid)}['\"]?\s*$",
            registry_text, re.MULTILINE,
        ), f"registry.yaml missing {vid}"

    @pytest.mark.parametrize("vid", PHASE16_VALIDATOR_IDS)
    def test_validator_script_present(self, vid):
        path = VALIDATORS / f"verify-{vid}.py"
        assert path.exists(), f"missing: {path}"

    @pytest.mark.parametrize("vid", PHASE16_VALIDATOR_IDS)
    def test_validator_help_runs(self, vid):
        proc = subprocess.run(
            [sys.executable, str(VALIDATORS / f"verify-{vid}.py"), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0, (
            f"verify-{vid}.py --help failed: {proc.stderr}"
        )


# ─── 2. task_hasher helper ───────────────────────────────────────────────

class TestPhase16Helper:
    def test_task_hasher_present(self):
        assert TASK_HASHER.exists(), f"missing: {TASK_HASHER}"

    def test_task_hasher_module_imports(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("th", TASK_HASHER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "task_block_sha256"), "missing task_block_sha256"
        assert hasattr(mod, "stable_meta"), "missing stable_meta"


# ─── 3. Parser exports ────────────────────────────────────────────────────

class TestPhase16Parser:
    def test_extract_task_section_v2_present(self):
        text = (SCRIPTS / "pre-executor-check.py").read_text(encoding="utf-8")
        assert "def extract_task_section_v2(" in text, (
            "pre-executor-check.py missing extract_task_section_v2"
        )

    def test_extract_all_tasks_present(self):
        text = (SCRIPTS / "pre-executor-check.py").read_text(encoding="utf-8")
        assert "def extract_all_tasks(" in text, (
            "pre-executor-check.py missing extract_all_tasks"
        )


# ─── 4. Build wire (D-01 + D-06) ─────────────────────────────────────────

class TestPhase16BuildWire:
    @pytest.fixture(scope="class")
    def build_md(self):
        return (COMMANDS / "build.md").read_text(encoding="utf-8")

    def test_meta_sidecar_persist_wired(self, build_md):
        assert "PROMPT_META_PERSIST" in build_md, (
            "build.md must persist .meta.json sidecar (D-01)"
        )
        assert ".meta.json" in build_md
        assert "task_meta" in build_md, (
            "build.md must reference CONTEXT_JSON.task_meta"
        )

    def test_task_fidelity_audit_wired(self, build_md):
        assert "verify-task-fidelity.py" in build_md, (
            "build.md step 8d must invoke verify-task-fidelity.py (D-06)"
        )
        assert "D-06 task fidelity audit" in build_md, (
            "build.md must surface verdict line for D-06 audit"
        )

    def test_r4_reads_applied_caps(self, build_md):
        # build.md should read ctx.get('applied_caps') for R4 budget
        assert "ctx.get('applied_caps')" in build_md, (
            "build.md R4 must read CONTEXT_JSON.applied_caps (D-04)"
        )


# ─── 5. Schema gate behavior (D-02) ──────────────────────────────────────

def _run_validator(script: Path, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=20, env=env,
        cwd=str(cwd),
    )


def _seed_phase(tmp_path: Path) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "16-fix"
    phase_dir.mkdir(parents=True)
    return phase_dir


def _verdict(stdout: str) -> str:
    try:
        return json.loads(stdout).get("verdict", "?")
    except json.JSONDecodeError:
        return "PARSE_ERROR"


class TestPhase16SchemaGate:
    @pytest.mark.parametrize("fmt,mode,expected_rc,expected_verdict", [
        ("heading-format", "legacy",     0, "PASS"),
        ("heading-format", "structured", 1, "BLOCK"),
        ("heading-format", "both",       0, "WARN"),
        ("xml-format",     "legacy",     0, "PASS"),
        ("xml-format",     "structured", 0, "PASS"),
        ("xml-format",     "both",       0, "PASS"),
    ])
    def test_mode_x_format_matrix(self, tmp_path, fmt, mode, expected_rc, expected_verdict):
        phase = _seed_phase(tmp_path)
        shutil.copy(FIXTURES / "plans" / f"{fmt}.PLAN.md", phase / "PLAN.md")
        r = _run_validator(VALIDATORS / "verify-task-schema.py",
                           ["--phase", "16", "--mode", mode], tmp_path)
        assert r.returncode == expected_rc, (
            f"{fmt}/{mode}: expected rc={expected_rc} got {r.returncode}; stdout={r.stdout[:300]}"
        )
        assert _verdict(r.stdout) == expected_verdict


# ─── 6. Body cap Check E (D-03) ──────────────────────────────────────────

class TestPhase16BodyCap:
    def _run_completeness(self, phase_dir: Path) -> dict:
        # vg_completeness_check.py uses --phase-dir not --phase
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "vg_completeness_check.py"),
             "--phase-dir", str(phase_dir), "--json"],
            capture_output=True, text=True, timeout=15,
        )
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def test_long_task_default_blocks(self, tmp_path):
        phase = _seed_phase(tmp_path)
        shutil.copy(FIXTURES / "plans" / "long-task.PLAN.md", phase / "PLAN.md")
        (phase / "CONTEXT.md").write_text("## P16.D-01: dummy\n", encoding="utf-8")
        (phase / "SPECS.md").write_text("## In Scope\n- Dummy\n", encoding="utf-8")
        out = self._run_completeness(phase)
        e = out.get("check_e", {})
        assert e.get("status") == "BLOCK", f"expected BLOCK; got {e}"
        assert e.get("violations_count", 0) >= 1

    def test_long_task_enriched_passes(self, tmp_path):
        phase = _seed_phase(tmp_path)
        shutil.copy(FIXTURES / "plans" / "long-task.PLAN.md", phase / "PLAN.md")
        (phase / "CONTEXT.md").write_text(
            "---\ncross_ai_enriched: true\n---\n## P16.D-01: dummy\n",
            encoding="utf-8",
        )
        (phase / "SPECS.md").write_text("## In Scope\n- Dummy\n", encoding="utf-8")
        out = self._run_completeness(phase)
        e = out.get("check_e", {})
        assert e.get("status") == "PASS", f"enriched should PASS; got {e}"


# ─── 7. R4 conditional caps (D-04) ───────────────────────────────────────

class TestPhase16R4Caps:
    def _run_pec(self, tmp_path: Path, ctx_text: str) -> dict:
        phase_dir = _seed_phase(tmp_path)
        shutil.copy(FIXTURES / "plans" / "heading-format.PLAN.md", phase_dir / "PLAN.md")
        (phase_dir / "CONTEXT.md").write_text(ctx_text, encoding="utf-8")
        (tmp_path / "vg.config.md").write_text("# minimal\n", encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "pre-executor-check.py"),
             "--phase-dir", str(phase_dir),
             "--task-num", "1",
             "--config", str(tmp_path / "vg.config.md"),
             "--repo-root", str(tmp_path)],
            capture_output=True, text=True, timeout=15,
        )
        return json.loads(r.stdout)

    def test_default_mode_caps(self, tmp_path):
        out = self._run_pec(tmp_path, "## P16.D-01: dummy\n")
        assert out.get("budget_mode") == "default"
        assert out["applied_caps"]["task_context"] == 300
        assert out["hard_total_max"] == 2500

    def test_enriched_mode_caps(self, tmp_path):
        out = self._run_pec(tmp_path, "---\ncross_ai_enriched: true\n---\n## P16.D-01: dummy\n")
        assert out.get("budget_mode") == "enriched"
        assert out["applied_caps"]["task_context"] == 600
        assert out["hard_total_max"] == 4000


# ─── 8. Task fidelity audit 3-way (D-06) ─────────────────────────────────

class TestPhase16TaskFidelity:
    def _seed_pair(self, tmp_path: Path, body_truncate_pct: float = 0.0):
        """Seed phase + run pre-executor-check + persist meta+prompt with
        the requested truncate ratio."""
        phase_dir = _seed_phase(tmp_path)
        shutil.copy(FIXTURES / "plans" / "heading-format.PLAN.md", phase_dir / "PLAN.md")
        (tmp_path / "vg.config.md").write_text("# minimal\n", encoding="utf-8")

        # Pre-executor-check to get task_meta
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "pre-executor-check.py"),
             "--phase-dir", str(phase_dir),
             "--task-num", "1",
             "--config", str(tmp_path / "vg.config.md"),
             "--repo-root", str(tmp_path)],
            capture_output=True, text=True, timeout=15,
        )
        ctx = json.loads(r.stdout)
        body = ctx["task_context"]
        meta = ctx["task_meta"]
        meta["wave"] = "wave-1"

        # Persist
        prompt_dir = phase_dir / ".build" / "wave-1" / "executor-prompts"
        prompt_dir.mkdir(parents=True)
        if body_truncate_pct > 0:
            lines = body.splitlines()
            keep = max(1, int(len(lines) * (1 - body_truncate_pct)))
            body = "\n".join(lines[:keep])
        (prompt_dir / "1.md").write_text(body, encoding="utf-8")
        (prompt_dir / "1.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return phase_dir, prompt_dir

    def test_verbatim_passes(self, tmp_path):
        _, pd = self._seed_pair(tmp_path, body_truncate_pct=0.0)
        r = _run_validator(VALIDATORS / "verify-task-fidelity.py",
                           ["--phase", "16", "--prompts-dir", str(pd)], tmp_path)
        assert r.returncode == 0
        assert _verdict(r.stdout) == "PASS"

    def test_severe_truncation_blocks(self, tmp_path):
        _, pd = self._seed_pair(tmp_path, body_truncate_pct=0.7)  # keep 30%
        r = _run_validator(VALIDATORS / "verify-task-fidelity.py",
                           ["--phase", "16", "--prompts-dir", str(pd)], tmp_path)
        assert r.returncode == 1
        assert _verdict(r.stdout) == "BLOCK"

    def test_minor_truncation_passes(self, tmp_path):
        _, pd = self._seed_pair(tmp_path, body_truncate_pct=0.05)  # 5% loss
        r = _run_validator(VALIDATORS / "verify-task-fidelity.py",
                           ["--phase", "16", "--prompts-dir", str(pd)], tmp_path)
        assert r.returncode == 0
        assert _verdict(r.stdout) == "PASS"
