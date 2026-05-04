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

import os
import re
import subprocess
import sys
import tempfile
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


# ---------------------------------------------------------------------------
# E2E coverage gap fix (R6 Task 2 follow-up)
# ---------------------------------------------------------------------------


def _extract_template_body() -> str:
    """Extract the SPECS.md template body from authoring.md.

    The template is wrapped in a ```markdown ... ``` code-fence inside the
    `<step name="write_specs">` block. We grab the first markdown fence in
    the file (scoped to that step in practice — there is only one such fence
    in authoring.md as of R6).
    """
    text = _template_text()
    m = re.search(r"```markdown\n(.*?)\n```", text, re.DOTALL)
    assert m, (
        "could not locate ```markdown ... ``` template fence in "
        f"{TEMPLATE_REF} — extraction regex needs update"
    )
    return m.group(1)


def _substitute_placeholders(template_body: str) -> str:
    """Render the template fence into a valid SPECS.md.

    Two transformations:

    1. Strip the inline `<LANGUAGE_POLICY>...</LANGUAGE_POLICY>` block. That
       block is an AI directive embedded inside the template fence (a known
       template artifact — see authoring.md lines 95-111), not literal output.
       At render time the AI applies the directive's behavior; the file the
       AI actually writes does NOT include the block. This test mirrors that.

    2. Substitute brace-wrapped placeholders in frontmatter with schema-valid
       enum values. Body placeholder hints (e.g. `{1-2 sentence phase
       objective}`) are left as literal text — validator only checks
       frontmatter shape + H2 anchors, NOT body content quality.
    """
    out = template_body

    # 1. Strip the LANGUAGE_POLICY directive block. Also collapse the blank
    #    line that immediately follows the opening `---` (template style).
    out = re.sub(
        r"<LANGUAGE_POLICY>.*?</LANGUAGE_POLICY>\n",
        "",
        out,
        flags=re.DOTALL,
    )
    # Collapse "---\n\n" (opening delimiter + intentional blank) → "---\n"
    out = re.sub(r"\A---\n\n+", "---\n", out)

    # 2. Substitute brace placeholders.
    # phase: schema pattern ^[0-9]+(\.[0-9]+)*(-[a-z0-9-]+)?$
    out = out.replace("{X}", "7.14.3")
    # profile: pick first enum value
    out = out.replace(
        "{feature|infra|hotfix|bugfix|migration|docs}",
        "feature",
    )
    # platform: schema enum value (web-fullstack is canonical).
    # Template enum string includes mobile-rn / mobile-flutter / mobile-native
    # / desktop-electron / desktop-tauri / server-setup / server-management
    # per authoring.md line 114.
    out = out.replace(
        "{web-fullstack|web-frontend-only|web-backend-only|mobile-rn|mobile-flutter|mobile-native|desktop-electron|desktop-tauri|cli-tool|library|server-setup|server-management}",
        "web-fullstack",
    )
    # created_at: ISO date YYYY-MM-DD
    out = out.replace("{YYYY-MM-DD}", "2026-05-04")
    # source: literal `ai-draft|user-guided` (no braces in template) → first enum.
    out = out.replace("source: ai-draft|user-guided", "source: ai-draft")
    return out


def test_specs_template_passes_schema_validator_e2e():
    """E2E: render template → write SPECS.md → run validator subprocess → assert PASS.

    This is the contract-level check the static template tests above lock
    DOWNSTREAM of. If any of:
      - schema `required` adds a field
      - validator regex tightens body anchor pattern
      - template placeholder enum drifts out of schema enum
    ...this test catches it where the static tests would pass blindly.
    """
    template_body = _extract_template_body()
    rendered = _substitute_placeholders(template_body)

    # Sanity: any leftover unresolved `{...}` placeholder in frontmatter would
    # fail schema validation later. Surface that here with a clearer message
    # than a downstream YAML parse error.
    fm_match = re.match(r"\A---\n(.*?)\n---", rendered, re.DOTALL)
    assert fm_match, (
        "rendered template missing YAML frontmatter delimiters — "
        f"first 200 chars:\n{rendered[:200]}"
    )
    leftover = re.findall(r"\{[^}\n]+\}", fm_match.group(1))
    assert not leftover, (
        f"rendered frontmatter still has unresolved placeholders: {leftover}. "
        f"Update _substitute_placeholders() to cover them."
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        phase_dir = tmp_root / ".vg" / "phases" / "7.14.3-r6-task2-followup"
        phase_dir.mkdir(parents=True)
        specs_path = phase_dir / "SPECS.md"
        specs_path.write_text(rendered, encoding="utf-8")

        # Validator resolves repo root via VG_REPO_ROOT env var (see
        # _common.find_phase_dir + verify-artifact-schema.py REPO_ROOT).
        # Schema dir is loaded relative to that root, so we must point it at
        # the real repo schemas while phase lookup walks tmp/.vg/phases.
        # The validator hard-codes SCHEMA_DIR = REPO_ROOT/.claude/schemas at
        # import time, so VG_REPO_ROOT MUST point somewhere that has BOTH
        # .claude/schemas/ AND .vg/phases/<phase-dir>. We achieve this by
        # symlinking the real schemas dir into tmp_root.
        (tmp_root / ".claude").mkdir()
        os.symlink(
            REPO_ROOT / ".claude" / "schemas",
            tmp_root / ".claude" / "schemas",
            target_is_directory=True,
        )

        env = {**os.environ, "VG_REPO_ROOT": str(tmp_root)}
        proc = subprocess.run(
            [
                sys.executable,
                str(VALIDATOR_PATH),
                "--phase", "7.14.3",
                "--artifact", "specs",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_root),
        )

        assert proc.returncode == 0, (
            f"verify-artifact-schema.py rejected the rendered template — "
            f"this means the template+schema+validator drifted apart.\n"
            f"  exit code: {proc.returncode}\n"
            f"  stdout: {proc.stdout}\n"
            f"  stderr: {proc.stderr}\n"
            f"  rendered SPECS.md frontmatter:\n"
            f"{fm_match.group(0) if fm_match else '<no frontmatter found>'}"
        )
