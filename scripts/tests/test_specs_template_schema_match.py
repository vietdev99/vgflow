"""R6 Task 2 — assert specs template emits artifact passing schema validator.

The template lives in commands/vg/_shared/specs/authoring.md as a markdown
heredoc/code-fence. Pre-fix audit found two field/heading deltas vs schema
+ validator (which are source-of-truth, NOT touched by this task):

  1. Schema (.claude/schemas/specs.v1.json) requires:
       phase, profile, platform, status, created_at
     Template was emitting:
       phase, status, created (no _at), source — missing profile + platform
  2. Validator (verify-artifact-schema.py BODY_H2_REQUIRED["specs"]) requires
     H2 anchors: Goal, Scope, Out of [Ss]cope, Constraints, Success criteria.
     Template was emitting `### Out of Scope` (H3) and `## Success Criteria`
     (capitalized C — validator regex uses lowercase "criteria").

This test locks the alignment so future refactors can't silently regress.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_REF = REPO_ROOT / "commands" / "vg" / "_shared" / "specs" / "authoring.md"
SCHEMA_PATH = REPO_ROOT / ".claude" / "schemas" / "specs.v1.json"
VALIDATOR_PATH = REPO_ROOT / "scripts" / "validators" / "verify-artifact-schema.py"


def _template_text() -> str:
    assert TEMPLATE_REF.exists(), f"template missing at {TEMPLATE_REF}"
    return TEMPLATE_REF.read_text(encoding="utf-8")


def test_schema_and_validator_present():
    """Pre-condition: schema + validator must exist (source-of-truth).

    If either is missing, R6 Task 2 cannot align — escalate BLOCKED.
    """
    assert SCHEMA_PATH.exists(), (
        f"schema missing at {SCHEMA_PATH} — cannot verify template alignment"
    )
    assert VALIDATOR_PATH.exists(), (
        f"validator missing at {VALIDATOR_PATH} — cannot verify template alignment"
    )


def test_specs_template_emits_required_frontmatter_fields():
    """Template MUST include all required frontmatter keys per schema.

    Schema .claude/schemas/specs.v1.json `required`:
      ["phase", "profile", "platform", "status", "created_at"]
    """
    text = _template_text()
    required_fields = ["phase:", "profile:", "platform:", "status:", "created_at:"]
    for field in required_fields:
        assert field in text, (
            f"specs template missing required frontmatter field '{field}' "
            f"per .claude/schemas/specs.v1.json"
        )


def test_specs_template_emits_required_h2_sections():
    """Template MUST use H2 (## ...) for sections per validator regex.

    verify-artifact-schema.py BODY_H2_REQUIRED["specs"] requires:
      ## Goal, ## Scope, ## Out of [Ss]cope, ## Constraints, ## Success criteria
    """
    text = _template_text()
    required_h2 = [
        "## Goal",
        "## Scope",
        "## Out of Scope",
        "## Constraints",
        "## Success criteria",
    ]
    for section in required_h2:
        # Match exact H2 at line start (not H3, not embedded in prose).
        # Use re.MULTILINE so ^ anchors per line.
        pattern = rf"^{re.escape(section)}\b"
        assert re.search(pattern, text, re.MULTILINE), (
            f"specs template missing required H2 section '{section}' "
            f"(might be H3 or capitalization mismatch — check exact case "
            f"per validator regex)"
        )


def test_specs_template_does_not_emit_legacy_created_field():
    """Template MUST NOT emit `created: {YYYY-MM-DD}` placeholder.

    Schema accepts `created` as legacy alias but `created_at` is required.
    Emitting both would either be redundant or violate
    additionalProperties:false depending on key shape. Template should emit
    only the canonical `created_at:`.
    """
    text = _template_text()
    assert "created: {YYYY-MM-DD}" not in text, (
        "specs template still emits legacy `created:` placeholder "
        "(schema requires `created_at:`)"
    )


def test_specs_template_does_not_emit_h3_out_of_scope():
    """Template MUST promote `### Out of Scope` to `## Out of Scope`.

    Validator regex `^##\\s+Out of [Ss]cope\\b` rejects H3.
    """
    text = _template_text()
    assert "### Out of Scope" not in text, (
        "specs template still emits H3 `### Out of Scope` — validator "
        "requires H2 `## Out of Scope`"
    )


def test_specs_template_does_not_emit_capitalized_success_criteria():
    """Template MUST emit `## Success criteria` (lowercase c), not `## Success Criteria`.

    Validator regex `^##\\s+Success criteria\\b` is case-sensitive on `criteria`.
    """
    text = _template_text()
    # Exact match for the wrong-case heading on its own line
    assert not re.search(r"^##\s+Success Criteria\b", text, re.MULTILINE), (
        "specs template still emits `## Success Criteria` (capitalized C) — "
        "validator regex requires lowercase `## Success criteria`"
    )
