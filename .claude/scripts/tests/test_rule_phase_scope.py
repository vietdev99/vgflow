"""
VG v2.6 Phase D — phase-scoped rules + verify-rule-phase-scope.

8 cases per PLAN-REVISED.md Phase D:
  1. Rule with `phase_pattern` matching current phase → injected
  2. Rule with `phase_pattern` NOT matching current phase → skipped
  3. Rule missing `phase_pattern` (grandfather) → injected with default `.*`
  4. Validator detects rule fired in 3+ phases without pattern → WARN
  5. Validator passes when rule has explicit pattern (regardless of phase count)
  6. Validator handles missing events.jsonl gracefully (PASS, no data)
  7. Validator schema canonical (verdict ∈ {BLOCK, PASS, WARN}, not FAIL/OK)
  8. Reflector suggests narrow pattern when all evidence in 7.x; suggests `.*` when mixed

All tests scope VG_REPO_ROOT to tmp_path; the validator script is invoked
via subprocess to verify real CLI behaviour.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import needs_bash

# Phase R (v2.7): rule_phase_scope tests invoke the inject-rule-cards.sh
# helper via `bash`. Same Windows-WSL caveat as block_resolver_l2.
# See PLATFORM-COMPAT.md.
pytestmark = needs_bash

REPO = Path(__file__).resolve().parents[3]
VALIDATOR = REPO / ".claude" / "scripts" / "validators" / "verify-rule-phase-scope.py"
INJECT_SH = REPO / ".claude" / "commands" / "vg" / "_shared" / "lib" / "inject-rule-cards.sh"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_cards(tmp_path: Path, skill: str, body: str) -> Path:
    """Create .codex/skills/{skill}/RULES-CARDS.md and return its path."""
    skill_dir = tmp_path / ".codex" / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    cards = skill_dir / "RULES-CARDS.md"
    cards.write_text(body, encoding="utf-8")
    return cards


def _run_inject(tmp_path: Path, skill: str, step: str, *extra_args: str) -> str:
    """Invoke inject-rule-cards.sh and return stdout."""
    env = os.environ.copy()
    env["REPO_ROOT"] = str(tmp_path)
    proc = subprocess.run(
        ["bash", str(INJECT_SH), skill, step, "quiet", *extra_args],
        env=env,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def _run_validator(tmp_path: Path, *extra_args: str) -> dict:
    """Invoke validator script with VG_REPO_ROOT scoped to tmp_path."""
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), *extra_args],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    # Last non-empty stdout line should be the JSON output
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    assert lines, f"validator emitted no JSON output. stderr={proc.stderr}"
    return json.loads(lines[-1])


def _write_events(tmp_path: Path, events: list[dict]) -> None:
    p = tmp_path / ".vg" / "events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")


def _write_accepted(tmp_path: Path, rules: list[dict]) -> None:
    p = tmp_path / ".vg" / "bootstrap" / "ACCEPTED.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for r in rules:
        block = f"- id: {r['id']}\n  title: \"{r.get('title', 'test')}\"\n"
        if "phase_pattern" in r:
            block += f"  phase_pattern: \"{r['phase_pattern']}\"\n"
        blocks.append(block)
    p.write_text("\n".join(blocks), encoding="utf-8")


# ---------------------------------------------------------------------------
# Inject-rule-cards.sh tests (cases 1-3)
# ---------------------------------------------------------------------------

def test_case_1_pattern_matches_current_phase(tmp_path):
    """Rule with phase_pattern matching current phase → injected."""
    body = """# RULES-CARDS — vg-test

## Top-level rules (apply to ALL steps)

- **R1 — Phase 7 only rule** [remind]
  body of phase 7 rule
  phase_pattern: "^7\\."

## Per-step rules

### Step: `parse_args`

- [remind] **TEST**: phase 7 step rule
  phase_pattern: "^7\\."
"""
    _write_cards(tmp_path, "vg-test", body)
    out = _run_inject(tmp_path, "vg-test", "parse_args", "--current-phase", "7.14.3")
    assert "Phase 7 only rule" in out
    assert "TEST" in out


def test_case_2_pattern_no_match_filters_rule(tmp_path):
    """Rule with phase_pattern not matching current phase → skipped."""
    body = """# RULES-CARDS — vg-test

## Top-level rules (apply to ALL steps)

- **R1 — Phase 12 only** [remind]
  body
  phase_pattern: "^12\\."

- **R2 — Always applies** [remind]
  always body
"""
    _write_cards(tmp_path, "vg-test", body)
    out = _run_inject(tmp_path, "vg-test", "parse_args", "--current-phase", "7.14")
    assert "Phase 12 only" not in out, "R1 should be filtered by phase_pattern mismatch"
    assert "Always applies" in out, "R2 default `.*` must always inject"


def test_case_3_missing_pattern_grandfather_injects(tmp_path):
    """Rule missing phase_pattern (grandfather) → injected regardless of phase."""
    body = """# RULES-CARDS — vg-test

## Top-level rules (apply to ALL steps)

- **R1 — No pattern declared** [remind]
  body of grandfather rule
"""
    _write_cards(tmp_path, "vg-test", body)
    out_p7 = _run_inject(tmp_path, "vg-test", "parse_args", "--current-phase", "7.0")
    out_p99 = _run_inject(tmp_path, "vg-test", "parse_args", "--current-phase", "99.0")
    assert "No pattern declared" in out_p7
    assert "No pattern declared" in out_p99
    # And without --current-phase at all
    out_none = _run_inject(tmp_path, "vg-test", "parse_args")
    assert "No pattern declared" in out_none


# ---------------------------------------------------------------------------
# verify-rule-phase-scope.py tests (cases 4-7)
# ---------------------------------------------------------------------------

def test_case_4_warn_when_rule_fires_in_3plus_phases_without_pattern(tmp_path):
    """Validator surfaces WARN for rule fired in 3+ distinct phases without explicit pattern."""
    _write_events(tmp_path, [
        {"type": "bootstrap.rule_promoted", "payload": {"id": "L-001", "phase": "7.1"}},
        {"type": "bootstrap.rule_promoted", "payload": {"id": "L-001", "phase": "8.2"}},
        {"type": "bootstrap.rule_promoted", "payload": {"id": "L-001", "phase": "12.3"}},
    ])
    _write_accepted(tmp_path, [{"id": "L-001", "title": "test rule"}])

    result = _run_validator(tmp_path)
    assert result["validator"] == "verify-rule-phase-scope"
    assert result["verdict"] == "WARN", f"expected WARN, got {result['verdict']}"
    assert any("L-001" in (e.get("actual") or "") for e in result["evidence"])


def test_case_5_pass_when_rule_has_explicit_pattern(tmp_path):
    """Validator PASS when rule has explicit phase_pattern, regardless of phase count."""
    _write_events(tmp_path, [
        {"type": "bootstrap.rule_promoted", "payload": {"id": "L-002", "phase": "7.1"}},
        {"type": "bootstrap.rule_promoted", "payload": {"id": "L-002", "phase": "8.2"}},
        {"type": "bootstrap.rule_promoted", "payload": {"id": "L-002", "phase": "12.3"}},
        {"type": "bootstrap.rule_promoted", "payload": {"id": "L-002", "phase": "14.0"}},
    ])
    _write_accepted(tmp_path, [
        {"id": "L-002", "title": "explicit universal", "phase_pattern": ".*"}
    ])

    result = _run_validator(tmp_path)
    assert result["verdict"] == "PASS", (
        f"explicit phase_pattern (even '.*') should silence WARN — got {result['verdict']}"
    )


def test_case_6_pass_when_events_jsonl_missing(tmp_path):
    """Missing events.jsonl → graceful PASS (no data to evaluate)."""
    # No events file written
    result = _run_validator(tmp_path)
    assert result["verdict"] == "PASS"
    assert result["evidence"] == []


def test_case_7_canonical_verdict_schema(tmp_path):
    """Verdict must use canonical {BLOCK, PASS, WARN} — not FAIL/OK."""
    # Trigger WARN path
    _write_events(tmp_path, [
        {"type": "bootstrap.rule_promoted", "payload": {"id": "L-003", "phase": "7.1"}},
        {"type": "bootstrap.rule_promoted", "payload": {"id": "L-003", "phase": "8.2"}},
        {"type": "bootstrap.rule_promoted", "payload": {"id": "L-003", "phase": "12.3"}},
    ])
    _write_accepted(tmp_path, [{"id": "L-003"}])  # no pattern → grandfather

    result = _run_validator(tmp_path)
    assert result["verdict"] in {"BLOCK", "PASS", "WARN"}, (
        f"verdict must be canonical, got {result['verdict']!r}"
    )
    # Specifically must NOT use legacy values
    assert result["verdict"] not in {"FAIL", "OK", "SKIP"}


# ---------------------------------------------------------------------------
# Reflector suggestion logic test (case 8)
# ---------------------------------------------------------------------------

def _suggest_pattern(commit_subjects: list[str]) -> str:
    """Pure-Python implementation of reflector's phase_pattern suggestion logic.

    Mirrors the prose pseudo-code in vg-reflector/SKILL.md (Phase D):
      - Parse each commit subject for `^[a-z]+\\(([0-9]+(?:\\.[0-9]+)*)-[0-9]+\\):`
      - Extract major component
      - 1 unique major  -> ^MAJOR\\.
      - 2 unique majors -> ^(M1|M2)\\.
      - 3+ majors / no commit-shaped evidence -> .*
    """
    import re as _re
    majors = []
    pat = _re.compile(r"^[a-z]+\(([0-9]+(?:\.[0-9]+)*)-[0-9]+\):")
    for s in commit_subjects:
        m = pat.match(s)
        if m:
            majors.append(m.group(1).split(".")[0])
    uniq = sorted(set(majors))
    if len(uniq) == 0:
        return ".*"
    if len(uniq) == 1:
        return f"^{uniq[0]}\\."
    if len(uniq) == 2:
        return f"^({uniq[0]}|{uniq[1]})\\."
    return ".*"


def test_case_8_reflector_suggests_narrow_or_wildcard():
    """Reflector suggests narrow pattern when evidence in single major; `.*` when mixed."""
    # All evidence in phase 7.x → suggest ^7\.
    subjects_7x = [
        "feat(7.1-04): add new endpoint",
        "fix(7.14.3-02): repair sidebar",
        "test(7.5-01): cover edge case",
    ]
    assert _suggest_pattern(subjects_7x) == "^7\\."

    # 3+ disjoint majors → suggest .*
    subjects_mixed = [
        "feat(7.1-04): one",
        "feat(8.2-01): two",
        "feat(12.3-01): three",
    ]
    assert _suggest_pattern(subjects_mixed) == ".*"

    # 2 adjacent majors → suggest ^(7|8)\.
    subjects_two = [
        "feat(7.1-01): a",
        "fix(8.2-02): b",
    ]
    assert _suggest_pattern(subjects_two) == "^(7|8)\\."

    # No commit-shaped evidence (e.g. user_message only) → .*
    subjects_none = [
        "user message: 'không thấy save'",
        "free-form text",
    ]
    assert _suggest_pattern(subjects_none) == ".*"
