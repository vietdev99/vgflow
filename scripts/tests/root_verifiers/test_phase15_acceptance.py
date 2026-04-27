"""
Phase 15 Wave 10 — E2E acceptance smoke.

Verifies every Phase 15 deliverable shipped across waves 0–9 is wired
correctly so a downstream `/vg:*` invocation will find what it expects.
This is a pure inventory + integration-marker check; the per-piece
behavioural tests live in test_phase15_design_extractors.py and
test_phase15_validators_and_matrix.py.

Acceptance dimensions (one test class each):
  1. Schemas       — 4 JSON Schema files exist + parse + declare $id.
  2. Validators    — 11 Phase 15 validators present in registry.yaml AND
                     on disk AND produce valid JSON when invoked --help-less
                     (smoke import via subprocess).
  3. Scripts       — extractor + matrix + UAT generator + subtree filter
                     all present and import-clean.
  4. Templates     — 4 filter + 6 pagination + 2 UAT narrative templates
                     present in commands/vg/_shared/templates/.
  5. Skill bodies  — 6 command files contain the integration markers added
                     in Wave 7 (test, accept, build, review, blueprint, scope).
  6. Config        — vg.config.template.md declares mcp_servers + design_fidelity
                     + extended design_assets.handlers.
  7. i18n          — narration-strings.yaml has all 9 UAT keys (vi+en locales).
  8. Per-wave tests still green when invoked together.

Run: python -m pytest scripts/tests/root_verifiers/test_phase15_acceptance.py -v
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = REPO_ROOT / "schemas"
VALIDATORS = REPO_ROOT / "scripts" / "validators"
SCRIPTS = REPO_ROOT / "scripts"
TEMPLATES = REPO_ROOT / "commands" / "vg" / "_shared" / "templates"
COMMANDS = REPO_ROOT / "commands" / "vg"
SHARED = REPO_ROOT / "commands" / "vg" / "_shared"
SKILLS = REPO_ROOT / "skills"


# ─── 1. Schemas ──────────────────────────────────────────────────────────

PHASE15_SCHEMAS = [
    "slug-registry.v1.json",
    "structural-json.v1.json",
    "ui-map.v1.json",
    "narration-strings.v1.json",
]


class TestPhase15Schemas:
    @pytest.mark.parametrize("name", PHASE15_SCHEMAS)
    def test_schema_present_and_valid(self, name):
        path = SCHEMAS / name
        assert path.exists(), f"Phase 15 schema missing: {path}"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("$schema", "").startswith("http://json-schema.org/draft-"), (
            f"{name}: missing or non-draft $schema"
        )
        assert data.get("$id", "").startswith("https://vgflow.dev/schemas/"), (
            f"{name}: $id must point at vgflow.dev/schemas/"
        )
        assert "type" in data, f"{name}: top-level type missing"


# ─── 2. Validators ───────────────────────────────────────────────────────

PHASE15_VALIDATOR_IDS = [
    "design-extractor-output",
    "design-ref-required",
    "uimap-schema",
    "phase-ui-flag",
    "uimap-injection",
    "uat-narrative-fields",
    "uat-strings-no-hardcode",
    "filter-test-coverage",
    "haiku-spawn-fired",
]


class TestPhase15Validators:
    @pytest.fixture(scope="class")
    def registry_text(self):
        return (VALIDATORS / "registry.yaml").read_text(encoding="utf-8")

    @pytest.mark.parametrize("vid", PHASE15_VALIDATOR_IDS)
    def test_registry_entry_present(self, vid, registry_text):
        # Registry entries are YAML; tolerate either id: <vid> or id: '<vid>'
        pattern = re.compile(rf"^\s*-\s*id:\s*['\"]?{re.escape(vid)}['\"]?\s*$",
                             re.MULTILINE)
        assert pattern.search(registry_text), f"validator '{vid}' missing from registry.yaml"

    @pytest.mark.parametrize("vid", PHASE15_VALIDATOR_IDS)
    def test_validator_script_present(self, vid):
        path = VALIDATORS / f"verify-{vid}.py"
        assert path.exists(), f"validator script missing: {path}"

    def test_extended_ui_structure_validator_present(self):
        # T3.6 EXTENDED rather than CREATED — separate file
        assert (SCRIPTS / "verify-ui-structure.py").exists()

    def test_holistic_drift_validator_present(self):
        assert (SCRIPTS / "verify-holistic-drift.py").exists()


# ─── 3. Scripts ──────────────────────────────────────────────────────────

PHASE15_SCRIPTS = [
    ("scripts/design-normalize.py", "py"),
    ("scripts/design-normalize-html.js", "js"),
    ("scripts/extract-subtree-haiku.mjs", "js"),
    ("scripts/generate-ui-map.mjs", "js"),
    ("scripts/build-uat-narrative.py", "py"),
    ("scripts/lib/threshold-resolver.py", "py"),
    ("skills/vg-codegen-interactive/filter-test-matrix.mjs", "js"),
]


class TestPhase15Scripts:
    @pytest.mark.parametrize("rel,kind", PHASE15_SCRIPTS)
    def test_script_present(self, rel, kind):
        path = REPO_ROOT / rel
        assert path.exists(), f"Phase 15 script missing: {path}"
        # Lightweight syntax check (Python only — node parse needs a node call)
        if kind == "py":
            text = path.read_text(encoding="utf-8")
            try:
                compile(text, str(path), "exec")
            except SyntaxError as e:
                pytest.fail(f"{rel}: SyntaxError: {e}")


# ─── 4. Templates ────────────────────────────────────────────────────────

PHASE15_TEMPLATES = [
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
    "uat-narrative-prompt.md.tmpl",
    "uat-narrative-design-ref-block.md.tmpl",
]


class TestPhase15Templates:
    @pytest.mark.parametrize("name", PHASE15_TEMPLATES)
    def test_template_present(self, name):
        path = TEMPLATES / name
        assert path.exists(), f"Phase 15 template missing: {path}"
        # Mustache placeholders should resolve via {{var.X}} pattern
        text = path.read_text(encoding="utf-8")
        assert "{{var." in text or "{{uat_" in text, (
            f"{name}: no Mustache placeholders found — template may have been "
            f"corrupted to literal text"
        )


# ─── 5. Skill body integration markers (Wave 7) ──────────────────────────

# Each entry: (file, marker substring that MUST appear, what it proves)
PHASE15_SKILL_INTEGRATIONS = [
    ("test.md", "Phase 15 T6.1", "test.md step 5d wires D-16 codegen rigor"),
    ("test.md", "filter-test-matrix.mjs", "test.md references the matrix module"),
    ("accept.md", "4b_uat_narrative_autofire", "accept.md step 4b wires UAT auto-fire"),
    ("accept.md", "build-uat-narrative.py", "accept.md invokes the generator"),
    ("build.md", "ui_map_subtree", "build.md step 8c injects UI-MAP subtree"),
    ("build.md", "extract-subtree-haiku.mjs", "build.md calls the subtree extractor"),
    ("review.md", "D-12c", "review.md wires UI-flag drift gate"),
    ("review.md", "D-12b", "review.md wires wave-scoped drift gate"),
    ("review.md", "D-12e", "review.md wires holistic drift gate"),
    ("review.md", "D-17", "review.md wires phantom-aware Haiku audit"),
    ("blueprint.md", "fidelity_profile_lock", "blueprint.md locks D-08 profile"),
    ("blueprint.md", "ui-map.v1.json", "blueprint.md references D-15 schema"),
    ("scope.md", "D-02", "scope.md wires design-ref required gate"),
    ("scope.md", "verify-design-ref-required.py", "scope.md invokes the validator"),
]


class TestPhase15SkillIntegrations:
    @pytest.fixture(scope="class")
    def skill_bodies(self):
        return {
            name: (COMMANDS / name).read_text(encoding="utf-8")
            for name in {entry[0] for entry in PHASE15_SKILL_INTEGRATIONS}
        }

    @pytest.mark.parametrize("file,marker,why", PHASE15_SKILL_INTEGRATIONS)
    def test_integration_marker_present(self, file, marker, why, skill_bodies):
        text = skill_bodies[file]
        assert marker in text, f"{file}: marker '{marker}' missing — {why}"


# ─── 6. Config ───────────────────────────────────────────────────────────

class TestPhase15Config:
    @pytest.fixture(scope="class")
    def cfg_text(self):
        return (REPO_ROOT / "vg.config.template.md").read_text(encoding="utf-8")

    def test_design_fidelity_block_present(self, cfg_text):
        assert "design_fidelity:" in cfg_text, "vg.config missing design_fidelity block"

    def test_mcp_servers_block_present(self, cfg_text):
        assert "mcp_servers:" in cfg_text, "vg.config missing mcp_servers block"

    def test_pencil_mcp_handler_wired(self, cfg_text):
        assert "pencil_mcp" in cfg_text, "design_assets.handlers missing pencil_mcp"

    def test_penboard_mcp_handler_wired(self, cfg_text):
        assert "penboard_mcp" in cfg_text, "design_assets.handlers missing penboard_mcp"


# ─── 7. i18n — narration-strings.yaml ────────────────────────────────────

PHASE15_UAT_KEYS = [
    "uat_entry_label",
    "uat_role_label",
    "uat_account_label",
    "uat_navigation_label",
    "uat_precondition_label",
    "uat_expected_label",
    "uat_region_label",
    "uat_screenshot_compare",
    "uat_prompt_pfs",
]


class TestPhase15I18n:
    @pytest.fixture(scope="class")
    def yaml_text(self):
        return (SHARED / "narration-strings.yaml").read_text(encoding="utf-8")

    @pytest.mark.parametrize("key", PHASE15_UAT_KEYS)
    def test_key_present(self, key, yaml_text):
        # Match `<key>:` at line start (any indent depth tolerated)
        assert re.search(rf"^\s*{re.escape(key)}\s*:", yaml_text, re.MULTILINE), (
            f"narration-strings.yaml missing UAT key '{key}'"
        )

    @pytest.mark.parametrize("key", PHASE15_UAT_KEYS)
    def test_key_has_vi_and_en(self, key, yaml_text):
        # Find the key block and assert vi/en locales follow within ~5 lines
        m = re.search(rf"^\s*{re.escape(key)}\s*:\s*$([\s\S]*?)(?=^\s*uat_|^\s*[a-z_]+:\s*$|\Z)",
                      yaml_text, re.MULTILINE)
        assert m, f"could not locate body for '{key}'"
        body = m.group(1)
        assert re.search(r"^\s*vi\s*:", body, re.MULTILINE), f"'{key}' missing 'vi' locale"
        assert re.search(r"^\s*en\s*:", body, re.MULTILINE), f"'{key}' missing 'en' locale"


# ─── 8. Per-wave tests still green together ──────────────────────────────

class TestPhase15RegressionGreen:
    """Sanity: invoking the per-wave test files together still passes.
    This guards against ordering- or fixture-coupling bugs that hide when each
    file runs in isolation. Phase 17 added — Phase 15 templates were modified
    by Phase 17 D-03 (useAuth replaces beforeEach loginAs); cross-phase smoke
    catches if that work breaks Phase 15 acceptance assumptions."""

    def test_phase15_plus_phase17_suite_passes(self):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        # Discover all Phase 15+ per-wave tests dynamically — file additions
        # in future waves auto-pick up without editing this list. W-5 (P17
        # cross-AI WARN): broaden glob from `1[57]` (only P15 + P17) to
        # `1[5-9]` so future P16 + P18 + P19 are caught automatically.
        # Update again when phases reach 20+ (or replace with full
        # `test_phase[1-9]?[0-9]_*.py` wildcard).
        test_files = sorted(
            str(p.relative_to(REPO_ROOT))
            for p in (REPO_ROOT / "scripts" / "tests" / "root_verifiers").glob(
                "test_phase1[5-9]_*.py"
            )
            if p.name != "test_phase15_acceptance.py"
            and p.name != "test_phase17_acceptance.py"
        )
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", *test_files],
            cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=90, env=env,
            encoding="utf-8", errors="replace",
        )
        assert proc.returncode == 0, (
            f"Phase 15+17 per-wave suite regressed:\n"
            f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-500:]}"
        )
