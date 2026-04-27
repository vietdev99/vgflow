"""
Phase 17 Wave 5 — E2E acceptance smoke.

Verifies every Phase 17 deliverable shipped across waves 0–4 is wired
correctly. Pure inventory + integration-marker check; per-piece
behavioural tests live in test_phase17_helpers.py.

Acceptance dimensions (one test class each):
  1. Validator    — verify-test-session-reuse.py present + registry entry
  2. Helpers      — interactive-helpers.template.ts has loginOnce + useAuth
                    + LoginOnceOptions (covered in test_phase17_helpers.py;
                    we sanity-check here)
  3. Templates    — global-setup + config-partial + 10 D-16 specs all use
                    Phase 17 pattern (no loginAs in beforeEach)
  4. Config       — vg.config.template.md has test: block with 5 keys
  5. Skill wires  — test.md step 5d-pre runs the Phase 17 auto-setup
                    (E2E_DIR detection + storage path export + .gitignore append +
                    VG_ROLES discovery)
  6. Validator-vs-fixture — validator WARNs on legacy fixture, PASSes on modern
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
TEMPLATES = REPO_ROOT / "commands" / "vg" / "_shared" / "templates"
COMMANDS = REPO_ROOT / "commands" / "vg"
SHARED = COMMANDS / "_shared"
FIXTURES = REPO_ROOT / "fixtures" / "phase17"
HELPER = TEMPLATES / "interactive-helpers.template.ts"


# ─── 1. Validator ─────────────────────────────────────────────────────────

class TestPhase17Validator:
    def test_script_present(self):
        path = VALIDATORS / "verify-test-session-reuse.py"
        assert path.exists(), f"validator missing: {path}"

    def test_registry_entry_present(self):
        text = (VALIDATORS / "registry.yaml").read_text(encoding="utf-8")
        assert re.search(r"^\s*-\s*id:\s*['\"]?test-session-reuse['\"]?\s*$",
                         text, flags=re.MULTILINE), (
            "registry.yaml missing test-session-reuse entry"
        )

    def test_validator_help_runs(self):
        # Smoke: validator --help should not crash
        proc = subprocess.run(
            [sys.executable, str(VALIDATORS / "verify-test-session-reuse.py"), "--help"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        assert proc.returncode == 0, f"validator --help failed: {proc.stderr}"
        assert "test-session-reuse" in proc.stdout or "phase" in proc.stdout.lower()


# ─── 2. Helper exports ────────────────────────────────────────────────────

class TestPhase17Helpers:
    @pytest.fixture(scope="class")
    def helper_text(self):
        return HELPER.read_text(encoding="utf-8")

    @pytest.mark.parametrize("name,kind", [
        ("loginOnce", "async function"),
        ("useAuth", "function"),
        ("LoginOnceOptions", "interface"),
    ])
    def test_export_present(self, helper_text, name, kind):
        if kind == "interface":
            assert f"export interface {name}" in helper_text, f"missing export {name}"
        else:
            pat = rf"export (?:async )?function {re.escape(name)}\b"
            assert re.search(pat, helper_text), f"missing export {name} ({kind})"


# ─── 3. Templates ─────────────────────────────────────────────────────────

class TestPhase17Templates:
    def test_global_setup_template_present(self):
        path = TEMPLATES / "playwright-global-setup.template.ts"
        assert path.exists(), f"missing: {path}"
        text = path.read_text(encoding="utf-8")
        assert "import { loginOnce }" in text, "global-setup must import loginOnce"
        assert "VG_ROLES" in text, "global-setup must consume VG_ROLES env"
        assert "export default globalSetup" in text, "default export missing"

    def test_config_partial_template_present(self):
        path = TEMPLATES / "playwright-config.partial.ts"
        assert path.exists(), f"missing: {path}"
        text = path.read_text(encoding="utf-8")
        assert "globalSetup:" in text, "merge fragment must show globalSetup line"
        assert ".gitignore" in text, "merge fragment must mention .gitignore step"

    @pytest.mark.parametrize("tmpl_name", [
        "filter-coverage.test.tmpl",
        "filter-stress.test.tmpl",
        "filter-state-integrity.test.tmpl",
        "filter-edge.test.tmpl",
        "pagination-navigation.test.tmpl",
        "pagination-url-sync.test.tmpl",
        "pagination-envelope.test.tmpl",
        "pagination-display.test.tmpl",
        "pagination-stress.test.tmpl",
        "pagination-edge.test.tmpl",
    ])
    def test_p15_template_uses_useauth_no_loginas(self, tmpl_name):
        text = (TEMPLATES / tmpl_name).read_text(encoding="utf-8")
        assert "test.use(useAuth(ROLE))" in text, (
            f"{tmpl_name}: missing test.use(useAuth(ROLE)) — Phase 17 D-03 not applied"
        )
        assert "loginAs(" not in text, (
            f"{tmpl_name}: legacy loginAs( still present — D-03 incomplete"
        )
        assert "useAuth" in text, f"{tmpl_name}: useAuth not imported"


# ─── 4. vg.config test: block ─────────────────────────────────────────────

class TestPhase17Config:
    @pytest.fixture(scope="class")
    def cfg_text(self):
        return (REPO_ROOT / "vg.config.template.md").read_text(encoding="utf-8")

    @pytest.mark.parametrize("key", [
        "storage_state_path:",
        "storage_state_ttl_hours:",
        "workers:",
        "fully_parallel:",
        "reuse_existing_server:",
        "login_strategy:",
    ])
    def test_test_block_key_present(self, cfg_text, key):
        # All 6 keys must exist somewhere under the test: block
        assert key in cfg_text, f"vg.config.template.md missing key: {key}"

    def test_test_block_introduced(self, cfg_text):
        assert "test:" in cfg_text and "Phase 17 D-05" in cfg_text, (
            "vg.config.template.md should declare test: block with Phase 17 D-05 marker"
        )


# ─── 5. Skill body (test.md) wiring ───────────────────────────────────────

class TestPhase17SkillIntegrations:
    @pytest.fixture(scope="class")
    def test_md(self):
        return (COMMANDS / "test.md").read_text(encoding="utf-8")

    @pytest.mark.parametrize("marker,why", [
        ("Phase 17 D-04/D-05", "test.md step 5d-pre headline"),
        ("playwright-global-setup.template.ts", "global-setup copy step"),
        ("VG_STORAGE_STATE_PATH", "env var export"),
        ("VG_LOGIN_STRATEGY", "env var export"),
        ("VG_ROLES=", "roles discovery export"),
        (".auth/", ".gitignore append target"),
    ])
    def test_marker_present(self, test_md, marker, why):
        assert marker in test_md, f"test.md missing marker '{marker}' — {why}"


# ─── 6. Validator vs fixtures (regression for D-06) ───────────────────────

class TestPhase17ValidatorBehavior:
    """Wire the T-0.2 fixtures through verify-test-session-reuse.py and
    assert WARN on legacy / no-flag on modern. Catches future drift in
    detection logic."""

    def _run_validator(self, tmp_path: Path, fixture_files: dict[str, str], strict: bool = False):
        """Set up fake VG_REPO_ROOT with .vg/phases/15-test + generated specs."""
        (tmp_path / ".vg" / "phases" / "15-test").mkdir(parents=True)
        gen = tmp_path / "apps" / "web" / "e2e" / "generated"
        gen.mkdir(parents=True)
        for name, src_path in fixture_files.items():
            shutil.copy(src_path, gen / name)
        env = os.environ.copy()
        env["VG_REPO_ROOT"] = str(tmp_path)
        env["PYTHONIOENCODING"] = "utf-8"
        args = [sys.executable, str(VALIDATORS / "verify-test-session-reuse.py"),
                "--phase", "15"]
        if strict:
            args.append("--strict")
        return subprocess.run(
            args, capture_output=True, text=True, env=env,
            cwd=str(tmp_path), timeout=10,
            encoding="utf-8", errors="replace",
        )

    def test_legacy_fixture_warns(self, tmp_path):
        legacy = FIXTURES / "specs" / "legacy-loginas.spec.ts.fixture"
        r = self._run_validator(tmp_path, {"g-legacy.spec.ts": legacy})
        assert r.returncode == 0, f"WARN should exit 0 — got {r.returncode}"
        out = json.loads(r.stdout)
        assert out["verdict"] == "WARN", f"expected WARN, got {out['verdict']}"
        assert any(e["type"] == "stale_codegen_pattern" for e in out["evidence"])

    def test_legacy_fixture_strict_blocks(self, tmp_path):
        legacy = FIXTURES / "specs" / "legacy-loginas.spec.ts.fixture"
        r = self._run_validator(tmp_path, {"g-legacy.spec.ts": legacy}, strict=True)
        assert r.returncode == 1, f"--strict should BLOCK (rc=1), got {r.returncode}"
        out = json.loads(r.stdout)
        assert out["verdict"] == "BLOCK"

    def test_modern_fixture_passes(self, tmp_path):
        modern = FIXTURES / "specs" / "modern-useauth.spec.ts.fixture"
        r = self._run_validator(tmp_path, {"g-modern.spec.ts": modern})
        assert r.returncode == 0, f"modern should PASS — got {r.returncode}"
        out = json.loads(r.stdout)
        assert out["verdict"] == "PASS", f"expected PASS, got {out['verdict']}"

    def test_mixed_fixtures_warns_only_for_legacy(self, tmp_path):
        legacy = FIXTURES / "specs" / "legacy-loginas.spec.ts.fixture"
        modern = FIXTURES / "specs" / "modern-useauth.spec.ts.fixture"
        r = self._run_validator(tmp_path, {
            "g-legacy.spec.ts": legacy,
            "g-modern.spec.ts": modern,
        })
        assert r.returncode == 0
        out = json.loads(r.stdout)
        assert out["verdict"] == "WARN"
        flagged_files = [e.get("file", "") for e in out["evidence"]
                         if e.get("type") == "stale_codegen_pattern"]
        assert len(flagged_files) == 1, f"expected 1 flagged file; got {flagged_files}"
        assert "g-legacy" in flagged_files[0]


# ─── 7. Orphan validator wire (P17 polish — Phase 7.14.3 retrospective) ──

class TestPhase17OrphanValidators:
    """Phase 17 polish wired 2 historically-orphaned validators into
    blueprint.md step 2d-3b. These tests ensure they stay registered +
    wired so future drift can't re-orphan them."""

    @pytest.mark.parametrize("vid", [
        "blueprint-completeness",
        "test-goals-platform-essentials",
    ])
    def test_registry_entry_present(self, vid):
        text = (VALIDATORS / "registry.yaml").read_text(encoding="utf-8")
        assert re.search(rf"^\s*-\s*id:\s*['\"]?{re.escape(vid)}['\"]?\s*$",
                         text, flags=re.MULTILINE), (
            f"registry.yaml missing {vid} entry — was it accidentally removed?"
        )

    @pytest.mark.parametrize("vid", [
        "blueprint-completeness",
        "test-goals-platform-essentials",
    ])
    def test_validator_script_present(self, vid):
        path = VALIDATORS / f"verify-{vid}.py"
        assert path.exists(), f"validator script missing: {path}"

    @pytest.mark.parametrize("script_name,marker", [
        ("verify-blueprint-completeness.py", "blueprint-completeness:"),
        ("verify-test-goals-platform-essentials.py", "test-goals-platform-essentials:"),
    ])
    def test_blueprint_md_wires_validator(self, script_name, marker):
        bp = (COMMANDS / "blueprint.md").read_text(encoding="utf-8")
        assert script_name in bp, (
            f"blueprint.md must invoke {script_name} (P17 polish wire)"
        )
        # Verify the bash case statement handles BLOCK verdict
        assert marker in bp, (
            f"blueprint.md must surface verdict line containing '{marker}'"
        )

    def test_blueprint_md_step_2d_3b_section_present(self):
        bp = (COMMANDS / "blueprint.md").read_text(encoding="utf-8")
        assert "### 2d-3b" in bp, "blueprint.md missing step 2d-3b section header"
        assert "Phase 7.14.3 retrospective" in bp, (
            "blueprint.md must document why the orphan validators are wired now"
        )


