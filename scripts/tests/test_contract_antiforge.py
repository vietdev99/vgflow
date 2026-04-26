"""
Anti-forge contract tests (2026-04-23).

Fixes the gap where AI could touch marker files without doing the actual work:
- Blueprint run phase 7.14 had marker 2d_crossai_review.done present but
  crossai/ dir empty and zero crossai.verdict events in telemetry.
- Contract must require BOTH the marker AND artifact evidence (must_write
  glob) AND telemetry event to close the forge surface.

Tests here validate:
  1. normalize_must_write accepts glob_min_count + required_unless_flag
  2. normalize_telemetry accepts required_unless_flag
  3. Blueprint skill contract declares crossai artifact + verdict event requirements
  4. Schema JSON accepts the new fields
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts"))

# Import orchestrator's contracts module (treats dir as package)
orch_dir = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
# Phase R (v2.7): contracts.py does `from _repo_root import find_repo_root`
# which only resolves when orch_dir itself (not its parent) is on sys.path.
# Without this insert, collection fails with ModuleNotFoundError on every
# platform — pre-existing bug surfaced by `python -m pytest` invocation.
sys.path.insert(0, str(orch_dir))
sys.path.insert(0, str(orch_dir.parent))
from importlib.machinery import SourceFileLoader

contracts_mod = SourceFileLoader(
    "vg_orch_contracts", str(orch_dir / "contracts.py")
).load_module()

SCHEMA = REPO_ROOT / ".claude" / "schemas" / "runtime-contract.json"
BLUEPRINT_MD = REPO_ROOT / ".claude" / "commands" / "vg" / "blueprint.md"


# ─── Normalizer tests ─────────────────────────────────────────────────

class TestMustWriteNormalizer:
    def test_string_form_default(self):
        out = contracts_mod.normalize_must_write(["${PHASE_DIR}/PLAN.md"])
        # Phase R (v2.7): normalizer is allowed to add new defaulted keys
        # over time (must_be_created_in_run, check_provenance, etc.) without
        # breaking this test. Assert the contract on the 5 invariants the
        # forge defense actually depends on; ignore additive surface.
        assert len(out) == 1
        entry = out[0]
        expected_subset = {
            "path": "${PHASE_DIR}/PLAN.md",
            "content_min_bytes": 1,
            "content_required_sections": [],
            "glob_min_count": None,
            "required_unless_flag": None,
        }
        for k, v in expected_subset.items():
            assert entry[k] == v, f"normalizer drift on {k}: {entry[k]!r} != {v!r}"

    def test_dict_with_glob_min_count(self):
        out = contracts_mod.normalize_must_write([
            {"path": "${PHASE_DIR}/crossai/result-*.xml",
             "glob_min_count": 2}
        ])
        assert out[0]["glob_min_count"] == 2
        assert out[0]["required_unless_flag"] is None

    def test_dict_with_required_unless_flag(self):
        out = contracts_mod.normalize_must_write([
            {"path": "${PHASE_DIR}/crossai/result-*.xml",
             "glob_min_count": 1,
             "required_unless_flag": "--skip-crossai"}
        ])
        assert out[0]["required_unless_flag"] == "--skip-crossai"
        assert out[0]["glob_min_count"] == 1

    def test_backward_compat_existing_dict(self):
        """Legacy dicts with only `path` + `content_min_bytes` still normalize."""
        out = contracts_mod.normalize_must_write([
            {"path": "${PHASE_DIR}/SPECS.md", "content_min_bytes": 100}
        ])
        assert out[0]["path"] == "${PHASE_DIR}/SPECS.md"
        assert out[0]["content_min_bytes"] == 100
        assert out[0]["glob_min_count"] is None
        assert out[0]["required_unless_flag"] is None


class TestTelemetryNormalizer:
    def test_string_form_default(self):
        out = contracts_mod.normalize_telemetry(["blueprint.plan_written"])
        assert out[0]["event_type"] == "blueprint.plan_written"
        assert out[0]["required_unless_flag"] is None

    def test_dict_with_required_unless_flag(self):
        out = contracts_mod.normalize_telemetry([
            {"event_type": "crossai.verdict",
             "phase": "${PHASE_NUMBER}",
             "required_unless_flag": "--skip-crossai"}
        ])
        assert out[0]["event_type"] == "crossai.verdict"
        assert out[0]["required_unless_flag"] == "--skip-crossai"

    def test_backward_compat_existing_dict(self):
        out = contracts_mod.normalize_telemetry([
            {"event_type": "build.completed", "phase": "7.14", "min_count": 2}
        ])
        assert out[0]["min_count"] == 2
        assert out[0]["required_unless_flag"] is None


# ─── Schema JSON tests ────────────────────────────────────────────────

class TestSchemaSupport:
    def test_schema_must_write_has_new_fields(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        mw_item = schema["properties"]["must_write"]["items"]["oneOf"][1]
        props = mw_item["properties"]
        assert "glob_min_count" in props
        assert "required_unless_flag" in props
        assert props["glob_min_count"]["type"] == "integer"

    def test_schema_must_emit_telemetry_has_new_field(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        tel_item = schema["properties"]["must_emit_telemetry"]["items"]["oneOf"][1]
        props = tel_item["properties"]
        assert "required_unless_flag" in props


# ─── Blueprint skill contract tests ─────────────────────────────────

class TestBlueprintContract:
    @pytest.fixture
    def frontmatter_body(self):
        text = BLUEPRINT_MD.read_text(encoding="utf-8")
        # YAML frontmatter between first two `---`
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        assert m, "blueprint.md missing frontmatter"
        return m.group(1)

    def test_must_write_includes_crossai_xml_glob(self, frontmatter_body):
        """Blueprint contract must require crossai/result-*.xml files."""
        assert "crossai/result-*.xml" in frontmatter_body
        assert "glob_min_count" in frontmatter_body

    def test_crossai_artifact_waived_by_skip_flag(self, frontmatter_body):
        """--skip-crossai flag must waive the crossai artifact check."""
        # Find the crossai glob requirement block
        idx = frontmatter_body.find("crossai/result-*.xml")
        assert idx != -1
        # Check nearby lines (~300 chars) have required_unless_flag
        nearby = frontmatter_body[idx:idx + 400]
        assert "required_unless_flag" in nearby
        assert "--skip-crossai" in nearby

    def test_must_emit_includes_crossai_verdict(self, frontmatter_body):
        """Blueprint contract must require crossai.verdict telemetry event."""
        assert "crossai.verdict" in frontmatter_body

    def test_verdict_event_waived_by_skip_flag(self, frontmatter_body):
        # Find the event_type: "crossai.verdict" line (the actual spec, not
        # the comment that mentions the same string).
        idx = frontmatter_body.find('event_type: "crossai.verdict"')
        assert idx != -1
        nearby = frontmatter_body[idx:idx + 300]
        assert "required_unless_flag" in nearby
        assert "--skip-crossai" in nearby
