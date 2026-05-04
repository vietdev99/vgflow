"""Tier 2 D: Verify JSON Schema files for build executor return contracts.

Asserts:
- Both schema files exist + are valid JSON
- Each schema has draft-07 $schema marker + oneOf (success/error envelopes)
- Each schema validates a representative sample success return
- Agent SKILL.md docs reference the schema path
- Mirror at .claude/schemas/ matches source
"""
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_TASK = REPO_ROOT / "schemas" / "vg-build-task-executor-return.v1.json"
SCHEMA_POST = REPO_ROOT / "schemas" / "vg-build-post-executor-return.v1.json"
SCHEMA_TASK_MIRROR = REPO_ROOT / ".claude" / "schemas" / "vg-build-task-executor-return.v1.json"
SCHEMA_POST_MIRROR = REPO_ROOT / ".claude" / "schemas" / "vg-build-post-executor-return.v1.json"
SKILL_TASK = REPO_ROOT / "agents" / "vg-build-task-executor" / "SKILL.md"
SKILL_POST = REPO_ROOT / "agents" / "vg-build-post-executor" / "SKILL.md"


def test_task_schema_exists_and_valid_json():
    assert SCHEMA_TASK.exists(), f"Schema file missing: {SCHEMA_TASK}"
    data = json.loads(SCHEMA_TASK.read_text())
    assert data.get("$schema", "").startswith("http://json-schema.org/draft-07"), (
        "Schema must declare draft-07"
    )
    assert "oneOf" in data, "Schema must use oneOf for success/error envelopes"
    assert len(data["oneOf"]) == 2, "Schema oneOf must have exactly 2 branches (success + error)"


def test_post_schema_exists_and_valid_json():
    assert SCHEMA_POST.exists(), f"Schema file missing: {SCHEMA_POST}"
    data = json.loads(SCHEMA_POST.read_text())
    assert data.get("$schema", "").startswith("http://json-schema.org/draft-07"), (
        "Schema must declare draft-07"
    )
    assert "oneOf" in data, "Schema must use oneOf for success/error envelopes"
    assert len(data["oneOf"]) == 2, "Schema oneOf must have exactly 2 branches (success + error)"


def test_task_schema_required_fields():
    data = json.loads(SCHEMA_TASK.read_text())
    success = data["oneOf"][0]
    required = success.get("required", [])
    expected = {
        "task_id", "artifacts_written", "commit_sha", "bindings_satisfied",
        "fingerprint_path", "build_log_path",
    }
    assert expected.issubset(set(required)), (
        f"Task schema success branch missing required fields: "
        f"{expected - set(required)}"
    )


def test_post_schema_required_fields():
    data = json.loads(SCHEMA_POST.read_text())
    success = data["oneOf"][0]
    required = success.get("required", [])
    expected = {
        "gates_passed", "gates_failed", "summary_path",
        "summary_sha256", "build_log_path", "build_log_index_path",
        "build_log_sha256",
    }
    assert expected.issubset(set(required)), (
        f"Post-executor schema success branch missing required fields: "
        f"{expected - set(required)}"
    )


def test_task_skill_md_references_schema_path():
    body = SKILL_TASK.read_text()
    assert "vg-build-task-executor-return.v1.json" in body, (
        "agents/vg-build-task-executor/SKILL.md must reference the schema "
        "file path so future spawn-site updates know where to point "
        "--json-schema= arg"
    )
    assert "--json-schema" in body, (
        "SKILL.md must mention --json-schema flag for spawn-site adoption"
    )


def test_post_skill_md_references_schema_path():
    body = SKILL_POST.read_text()
    assert "vg-build-post-executor-return.v1.json" in body, (
        "agents/vg-build-post-executor/SKILL.md must reference the schema "
        "file path so future spawn-site updates know where to point "
        "--json-schema= arg"
    )
    assert "--json-schema" in body, (
        "SKILL.md must mention --json-schema flag for spawn-site adoption"
    )


def test_mirror_schemas_present_and_match_source():
    """install.sh ships schemas to .claude/schemas/ — mirror must match."""
    assert SCHEMA_TASK_MIRROR.exists(), f"Mirror missing: {SCHEMA_TASK_MIRROR}"
    assert SCHEMA_POST_MIRROR.exists(), f"Mirror missing: {SCHEMA_POST_MIRROR}"
    assert SCHEMA_TASK_MIRROR.read_text() == SCHEMA_TASK.read_text(), (
        "schemas/vg-build-task-executor-return.v1.json drifted from "
        ".claude/schemas/ mirror — re-run mirror copy"
    )
    assert SCHEMA_POST_MIRROR.read_text() == SCHEMA_POST.read_text(), (
        "schemas/vg-build-post-executor-return.v1.json drifted from "
        ".claude/schemas/ mirror — re-run mirror copy"
    )


def test_task_schema_validates_sample():
    """Sample success return JSON validates against the schema (if jsonschema available)."""
    sample = {
        "task_id": "task-04",
        "artifacts_written": ["src/foo.ts", "tests/foo.spec.ts"],
        "commit_sha": "abc123def4567890",
        "bindings_satisfied": ["binding-CONTEXT-D-02"],
        "fingerprint_path": "/tmp/.fingerprints/task-04.fingerprint.md",
        "read_evidence_path": None,
        "build_log_path": "/tmp/BUILD-LOG/task-04.md",
        "test_red_evidence_path": None,
        "test_green_evidence_path": None,
        "warnings": [],
    }
    schema = json.loads(SCHEMA_TASK.read_text())
    try:
        import jsonschema  # type: ignore
    except ImportError:
        pytest.skip("jsonschema lib not available; structural validation only")
    jsonschema.validate(sample, schema)


def test_post_schema_validates_sample():
    """Sample success return JSON validates against the schema (if jsonschema available)."""
    sample = {
        "gates_passed": ["L2", "L5", "truthcheck"],
        "gates_failed": [],
        "gaps_closed": [],
        "summary_path": "/tmp/SUMMARY.md",
        "summary_sha256": "a" * 64,
        "build_log_path": "/tmp/BUILD-LOG.md",
        "build_log_index_path": "/tmp/BUILD-LOG/index.md",
        "build_log_sha256": "b" * 64,
        "build_log_sub_files": ["/tmp/BUILD-LOG/task-01.md"],
    }
    schema = json.loads(SCHEMA_POST.read_text())
    try:
        import jsonschema  # type: ignore
    except ImportError:
        pytest.skip("jsonschema lib not available; structural validation only")
    jsonschema.validate(sample, schema)
