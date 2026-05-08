import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

VALIDATOR = ".claude/scripts/validators/verify-rule-schema-v1-1.py"


def run_validator_with_body(rule_yaml: str, body: str = "# body\n"):
    """Write frontmatter+body to temp file, run validator, return CompletedProcess."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(f"---\n{rule_yaml}\n---\n{body}")
        path = f.name
    return subprocess.run([sys.executable, VALIDATOR, path], capture_output=True, text=True)


def run_validator(rule_yaml: str):
    return run_validator_with_body(rule_yaml, "# body\n")


def test_declarative_default_passes():
    result = run_validator(textwrap.dedent("""
        slug: test-rule
        title: "test"
        target_step: build
        priority: low
        tier: C
    """).strip())
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_procedural_without_sequence_fails():
    result = run_validator(textwrap.dedent("""
        slug: bad-procedural
        title: "missing sequence"
        type: procedural
        target_step: deploy
    """).strip())
    assert result.returncode != 0
    assert "sequence" in result.stderr.lower()


def test_procedural_without_success_signals_fails():
    result = run_validator(textwrap.dedent("""
        slug: bad-procedural-2
        title: "missing signals"
        type: procedural
        target_step: deploy
        sequence:
          - id: s1
            cmd: "echo hi"
    """).strip())
    assert result.returncode != 0
    assert "success_signals" in result.stderr.lower()


def test_procedural_without_attribution_required_fails():
    result = run_validator(textwrap.dedent("""
        slug: bad-procedural-3
        title: "missing attribution_required"
        type: procedural
        authority: advisory
        target_step: deploy
        sequence:
          - id: s1
            cmd: "echo hi"
            expected_signals: ["exit=0"]
        success_signals: ["pass"]
    """).strip())
    assert result.returncode != 0
    assert "attribution" in result.stderr.lower()


def test_target_step_invalid_value_fails():
    result = run_validator(textwrap.dedent("""
        slug: bad-step
        title: "bad target_step"
        target_step: foobar
    """).strip())
    assert result.returncode != 0
    assert "target_step" in result.stderr.lower()


def test_target_step_deploy_passes():
    result = run_validator(textwrap.dedent("""
        slug: deploy-ok
        title: "ok"
        type: procedural
        authority: advisory
        target_step: deploy
        sequence:
          - id: s1
            cmd: "flyctl deploy"
            expected_signals: ["exit=0"]
        success_signals: ["phase.deploy_completed.outcome == PASS"]
        attribution_required: true
    """).strip())
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_target_step_roam_passes():
    result = run_validator(textwrap.dedent("""
        slug: roam-decl
        title: "roam declarative ok"
        type: declarative
        target_step: roam
    """).strip())
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_target_step_amend_passes():
    result = run_validator(textwrap.dedent("""
        slug: amend-decl
        title: "amend declarative ok"
        type: declarative
        target_step: amend
    """).strip())
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_authority_executable_blocked():
    result = run_validator(textwrap.dedent("""
        slug: blocked
        title: "executable blocked"
        type: procedural
        authority: executable
        target_step: deploy
        sequence:
          - id: s1
            cmd: "echo"
            expected_signals: []
        success_signals: []
        attribution_required: true
    """).strip())
    assert result.returncode != 0
    assert "authority" in result.stderr.lower()


def test_authority_reference_passes():
    """Authority 'reference' is allowed alongside 'advisory' in v1."""
    result = run_validator(textwrap.dedent("""
        slug: reference-ok
        title: "reference ok"
        type: declarative
        authority: reference
        target_step: build
    """).strip())
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_declarative_with_sequence_fails():
    """Non-procedural rule must NOT have sequence."""
    result = run_validator(textwrap.dedent("""
        slug: bad-decl
        title: "declarative with sequence"
        type: declarative
        target_step: build
        sequence:
          - id: s1
            cmd: "echo"
            expected_signals: []
    """).strip())
    assert result.returncode != 0
    assert "sequence" in result.stderr.lower() or "declarative" in result.stderr.lower()


def test_relative_date_yesterday_in_body_fails():
    result = run_validator_with_body(
        textwrap.dedent("""
            slug: relative-date-1
            title: "test"
            target_step: build
        """).strip(),
        body="# body\nFixed yesterday's deploy bug.\n",
    )
    assert result.returncode != 0


def test_relative_date_last_week_in_body_fails():
    result = run_validator_with_body(
        textwrap.dedent("""
            slug: relative-date-2
            title: "test"
            target_step: build
        """).strip(),
        body="# body\nLast week we deployed v2.\n",
    )
    assert result.returncode != 0


def test_absolute_date_in_body_passes():
    """Absolute YYYY-MM-DD should pass."""
    result = run_validator_with_body(
        textwrap.dedent("""
            slug: absolute-date
            title: "test"
            target_step: build
        """).strip(),
        body="# body\nFixed on 2026-05-08.\n",
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_invalid_yaml_frontmatter_fails():
    """Malformed YAML in frontmatter should error out gracefully."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("---\nthis: is: bad: yaml:\n---\n# body\n")
        path = f.name
    result = subprocess.run([sys.executable, VALIDATOR, path], capture_output=True, text=True)
    assert result.returncode != 0


def test_missing_frontmatter_fails():
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("# Just body, no frontmatter\n")
        path = f.name
    result = subprocess.run([sys.executable, VALIDATOR, path], capture_output=True, text=True)
    assert result.returncode != 0
