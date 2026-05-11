"""tests/test_field_test_config_schema.py — schema + config block contracts."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = REPO_ROOT / "schemas" / "field-test-session.v1.json"
CONFIG_TEMPLATE = REPO_ROOT / "vg.config.template.md"


def test_schema_exists_and_parses():
    assert SCHEMA.is_file()
    data = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    required = set(data["required"])
    expected = {"version", "sid", "phase", "base_url", "ts_started", "sources", "redaction"}
    assert expected <= required


def test_schema_rejects_invalid_session():
    """Schema must actually reject malformed session.json — not just declare required fields."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    # Missing `sid`
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"version": "1", "base_url": "http://x", "ts_started": "2026-05-11T00:00:00Z",
             "sources": [], "redaction": "password"},
            schema,
            format_checker=jsonschema.FormatChecker(),
        )
    # Bad sources type
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"version": "1", "sid": "ft-2026", "phase": None, "base_url": "http://x",
             "ts_started": "2026-05-11T00:00:00Z", "sources": "not-a-list", "redaction": "password"},
            schema,
            format_checker=jsonschema.FormatChecker(),
        )


def test_schema_accepts_real_session():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    valid = {
        "version": "1", "sid": "ft-2026-05-11T10-00-00Z", "phase": None,
        "base_url": "http://localhost:3000", "ts_started": "2026-05-11T10:00:00Z",
        "sources": [{"type": "file", "target": "/var/log/api.log", "label": "api"}],
        "redaction": "password|token|secret",
    }
    jsonschema.validate(valid, schema, format_checker=jsonschema.FormatChecker())


def test_schema_phase_goal_accepts_domain_ids():
    """v2.1: phase_goal field permits domain IDs (G-AUTH-00, G-FE-ADMIN-DLQ-01) per PR #177 generic ID rewrite."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for goal_id in ["G-01", "G-19b", "G-AUTH-00", "G-FE-ADMIN-DLQ-01", "G-PHASE-04"]:
        session = {
            "version": "1", "sid": "ft-2026-05-11T10-00-00Z", "phase": None,
            "base_url": "http://x", "ts_started": "2026-05-11T10:00:00Z",
            "sources": [], "redaction": "password", "phase_goal": goal_id,
        }
        jsonschema.validate(session, schema, format_checker=jsonschema.FormatChecker())  # must not raise


def _date_time_format_checker():
    """Build a FormatChecker with a guaranteed date-time validator.

    The stock ``jsonschema.FormatChecker`` only registers ``date-time`` when an
    optional dependency (``rfc3339-validator`` / ``strict-rfc3339``) is installed.
    We register a local RFC3339 validator so the contract is enforced
    regardless of the environment.
    """
    jsonschema = pytest.importorskip("jsonschema")
    fc = jsonschema.FormatChecker()
    # Always (re)register a strict ISO 8601 / RFC 3339 date-time checker so the
    # test does not depend on optional packages being installed.
    rfc3339_re = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
    )

    @fc.checks("date-time", raises=(ValueError,))
    def _check_date_time(value):  # pragma: no cover - trivial
        if not isinstance(value, str) or not rfc3339_re.match(value):
            raise ValueError(f"not a valid RFC3339 date-time: {value!r}")
        return True

    return fc


def test_schema_rejects_bad_date_time_format():
    """format: date-time must actually validate, not just annotate."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    bad = {
        "version": "1", "sid": "ft-2026-05-11T10-00-00Z", "phase": None,
        "base_url": "http://x", "ts_started": "this is not a date",
        "sources": [], "redaction": "password",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema, format_checker=_date_time_format_checker())


def test_schema_phase_goal_rejects_trailing_separators():
    """v2.1: phase_goal must not end in -, _, or . — those signal incomplete ID."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for bad_id in ["G-X-", "G-X_", "G-X.", "G-AUTH-"]:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"version": "1", "sid": "ft-2026-05-11T10-00-00Z", "phase": None,
                 "base_url": "http://x", "ts_started": "2026-05-11T10:00:00Z",
                 "sources": [], "redaction": "password", "phase_goal": bad_id},
                schema,
            )


@pytest.mark.parametrize("payload,reason", [
    ({"version": "2", "sid": "ft-2026", "phase": None, "base_url": "http://x",
      "ts_started": "2026-05-11T10:00:00Z", "sources": [], "redaction": "p"},
     "version must be const '1'"),
    ({"version": "1", "sid": "ft-2026", "phase": None, "base_url": "http://x",
      "ts_started": "2026-05-11T10:00:00Z",
      "sources": [{"type": "process", "target": "x", "label": "y"}],
      "redaction": "p"},
     "sources.items.type must be 'file' or 'command'"),
    ({"version": "1", "sid": "ft-2026", "phase": None, "base_url": "http://x",
      "ts_started": "2026-05-11T10:00:00Z",
      "sources": [{"type": "file", "target": "/x"}],
      "redaction": "p"},
     "sources.items missing required 'label'"),
    ({"version": "1", "sid": "ft-2026", "phase": None, "base_url": "http://x",
      "ts_started": "2026-05-11T10:00:00Z", "sources": [], "redaction": "p",
      "mark_count": -1},
     "mark_count must be >= 0"),
    ({"version": "1", "sid": "ft-2026", "phase": None, "base_url": "http://x",
      "ts_started": "2026-05-11T10:00:00Z", "sources": [], "redaction": "p",
      "phase_goal": "g-01"},
     "phase_goal must start with capital G-"),
    ({"version": "1", "sid": "ft-2026", "phase": None, "base_url": "http://x",
      "ts_started": "2026-05-11T10:00:00Z", "sources": [], "redaction": "p",
      "phase_goal": "AUTH-00"},
     "phase_goal must have G- prefix"),
])
def test_schema_rejects_specific_field_violations(payload, reason):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_config_template_advertises_field_test_block_no_preset():
    body = CONFIG_TEMPLATE.read_text(encoding="utf-8")
    assert re.search(r"^#?\s*field_test\s*:", body, re.MULTILINE)
    for key in [
        "api_log_sources", "default_redaction", "default_base_url",
        "mark_window_sec", "session_max_size_mb", "max_session_hours",
    ]:
        assert key in body, f"missing config key: {key}"
    # v1: preset must NOT appear (deferred to v2)
    assert "default_preset" not in body, (
        "v1 ships only the standard capture profile — no preset enum in config"
    )
