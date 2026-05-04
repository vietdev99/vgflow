"""
test_artifact_schema.py — v2.7 Phase E coverage for verify-artifact-schema.

Exercises the 6 core artifact schemas (specs/context/plan/test-goals/summary/
uat) with 4 cases each (24) plus 2 cross-cutting cases (grandfather skip,
--all mode). Total: 26 cases.

Per artifact, fixed protocol:
  test_<artifact>_valid_passes — minimal valid frontmatter + required body H2 → PASS
  test_<artifact>_missing_required_blocks — drop one required field → BLOCK rule=required
  test_<artifact>_wrong_type_blocks — wrong type on a typed field → BLOCK rule=type
  test_<artifact>_extra_field_blocks — extra unknown field → BLOCK rule=additionalProperties

Subprocess + tmp_path fake-repo pattern (mirrors
test_url_state_runtime_validator.py).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-artifact-schema.py"
SCHEMA_DIR_SRC = REPO_ROOT / ".claude" / "schemas"


# ---------------------------------------------------------------------------
# Fake-repo helpers
# ---------------------------------------------------------------------------


def _run(repo: Path, phase: str, *extra: str) -> tuple[int, dict]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--phase", phase, *extra],
        capture_output=True, text=True, cwd=repo, env=env, timeout=15,
    )
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        data = {
            "verdict": "ERROR", "raw_stdout": proc.stdout,
            "raw_stderr": proc.stderr,
        }
    return proc.returncode, data


def _setup_fake_repo(
    tmp_path: Path,
    *,
    phase: str,
    files: dict[str, str],
) -> Path:
    """Mirror validator + schemas + helpers; write phase artifact files."""
    scripts_dir = tmp_path / ".claude" / "scripts" / "validators"
    scripts_dir.mkdir(parents=True)
    shutil.copy(SCRIPT, scripts_dir / SCRIPT.name)
    for helper in ("_common.py", "_i18n.py", "_repo_root.py"):
        src = REPO_ROOT / ".claude" / "scripts" / "validators" / helper
        if src.exists():
            shutil.copy(src, scripts_dir / helper)
    schema_dst = tmp_path / ".claude" / "schemas"
    schema_dst.mkdir(parents=True)
    for schema_file in SCHEMA_DIR_SRC.glob("*.json"):
        shutil.copy(schema_file, schema_dst / schema_file.name)
    narr_src = (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
                / "narration-strings.yaml")
    if narr_src.exists():
        narr_dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
        narr_dst.mkdir(parents=True)
        shutil.copy(narr_src, narr_dst / "narration-strings.yaml")

    phase_dir = tmp_path / ".vg" / "phases" / phase
    phase_dir.mkdir(parents=True)
    for fname, content in files.items():
        (phase_dir / fname).write_text(content, encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def _cleanup_vg_repo_root_env():
    original_repo = os.environ.get("VG_REPO_ROOT")
    original_grand = os.environ.get("VG_SCHEMA_GRANDFATHER_BEFORE")
    yield
    if original_repo is None:
        os.environ.pop("VG_REPO_ROOT", None)
    else:
        os.environ["VG_REPO_ROOT"] = original_repo
    if original_grand is None:
        os.environ.pop("VG_SCHEMA_GRANDFATHER_BEFORE", None)
    else:
        os.environ["VG_SCHEMA_GRANDFATHER_BEFORE"] = original_grand


# ---------------------------------------------------------------------------
# Minimal valid frontmatter + body fixtures per artifact
# ---------------------------------------------------------------------------

SPECS_VALID = """\
---
phase: "14"
profile: feature
platform: web-fullstack
status: scope
created_at: 2026-04-26
---

## Goal

Lock the structural shape of 6 core VG artifacts.

## Scope

- Schema files
- Validator
- Tests

## Out of scope

- API-CONTRACTS schema (deferred to v2.9)

## Constraints

- pyyaml only — no external schema lib

## Success criteria

- 26/26 tests pass
"""

CONTEXT_VALID = """\
---
phase: "14"
discussed_in: 2026-04-26
participants:
  - user
  - ai
---

## Goals

### In-scope
- Lock the structural shape of 6 core VG artifacts.
- Provide a post-write validator.

### Out-of-scope (deferred / not this phase)
- API-CONTRACTS schema.

## Decisions

### D-01: Use draft-07 JSON Schema
**Decision:** Adopt draft-07.
**Rationale:** Stable, broadly supported.

### D-02: Hand-rolled walker
**Decision:** No external schema lib.
**Rationale:** Keep VG infra dep-light.

## Open questions

None.

## Risks

- Schema bumps could break consumers — mitigated by `/v1` versioning.
"""

PLAN_VALID = """\
---
phase: "14"
profile: feature
goal_summary: Lock 6 artifact frontmatter shapes via JSON Schema + post-write validator.
total_waves: 2
total_tasks: 4
generated_at: 2026-04-26
---

## Wave 1

### Task 14-01: Author schemas
- **Files:** .claude/schemas/*.json
- **Goal coverage:** G-01
- **Acceptance:** all 6 schemas present.

### Task 14-02: Author README
- **Files:** .claude/schemas/README.md
- **Goal coverage:** G-02
- **Acceptance:** versioning policy documented.

## Wave 2

### Task 14-03: Validator + tests
- **Files:** verify-artifact-schema.py + test_artifact_schema.py
- **Goal coverage:** G-03
- **Acceptance:** 26/26 pass.

### Task 14-04: Wire skill bodies
- **Files:** specs.md, scope.md, blueprint.md, build.md, accept.md
- **Goal coverage:** G-04
- **Acceptance:** validator fires post-write at every producer step.

## Verification

- pytest .claude/scripts/tests/test_artifact_schema.py
- full regression delta = +26

## Risks

- Existing legacy phases may fail — grandfather env supported.
"""

TEST_GOALS_VALID = """\
---
phase: "14"
profile: feature
goal_count: 2
generated_at: 2026-04-26
---

## G-01: Validator runs post-write
Body for goal 1.

## G-02: Schema bumps version cleanly
Body for goal 2.
"""

SUMMARY_VALID = """\
---
phase: "14"
status: completed
total_tasks: 4
tasks_completed: 4
total_waves: 2
generated_at: 2026-04-26
final_commit: abc1234
---

## Tasks shipped

- Task 14-01
- Task 14-02
- Task 14-03
- Task 14-04

## Files touched

- .claude/schemas/*.json
- .claude/scripts/validators/verify-artifact-schema.py

## Goal coverage

- G-01 PASS
- G-02 PASS

## Deviations

None.

## Next steps

Run /vg:review 14.
"""

UAT_VALID = """\
---
phase: "14"
verdict: ACCEPTED
performed_by: user
performed_at: 2026-04-26
total_goals_verified: 2
goals_passed: 2
goals_failed: 0
---

## Login + setup

Logged in at http://localhost:5173/login as admin@example.com.

## Per-goal verification

### G-01 — PASS
Evidence: validator fires post-write, asserted via subprocess test.

### G-02 — PASS
Evidence: README documents versioning + bump path.

## Deviations from acceptance criteria

None.

## Sign-off

User accepted on 2026-04-26.
"""


VALID_FIXTURES = {
    "specs": ("SPECS.md", SPECS_VALID),
    "context": ("CONTEXT.md", CONTEXT_VALID),
    "plan": ("PLAN.md", PLAN_VALID),
    "test-goals": ("TEST-GOALS.md", TEST_GOALS_VALID),
    "summary": ("SUMMARY.md", SUMMARY_VALID),
    "uat": ("UAT.md", UAT_VALID),
}


def _mutate_frontmatter(text: str, mutator) -> str:
    """Apply mutator to the YAML frontmatter block; return updated text."""
    import yaml
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise ValueError("missing frontmatter")
    fm = yaml.safe_load(parts[1]) or {}
    fm = mutator(fm) or fm
    new_fm = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False)
    return "---\n" + new_fm + "---\n" + parts[2]


# ---------------------------------------------------------------------------
# Generic per-artifact case helpers
# ---------------------------------------------------------------------------


def _expect_pass(repo: Path, artifact: str):
    rc, data = _run(repo, "14", "--artifact", artifact)
    assert rc == 0, data
    assert data["verdict"] in ("PASS", "WARN"), data
    return data


def _expect_block_with_rule(
    repo: Path, artifact: str, rule_substring: str,
):
    rc, data = _run(repo, "14", "--artifact", artifact)
    assert rc == 1, data
    assert data["verdict"] == "BLOCK", data
    types = [e["type"] for e in data["evidence"]]
    assert any(rule_substring in t for t in types), (rule_substring, types)
    return data


# ---------------------------------------------------------------------------
# SPECS
# ---------------------------------------------------------------------------


def test_specs_valid_passes(tmp_path):
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"SPECS.md": SPECS_VALID},
    )
    _expect_pass(repo, "specs")


def test_specs_missing_required_blocks(tmp_path):
    mutated = _mutate_frontmatter(
        SPECS_VALID, lambda fm: fm.pop("created_at") and fm,
    )
    # ^ fm.pop returns the popped value, then `and fm` returns fm.
    # If created_at is the date string (truthy), result = fm.
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"SPECS.md": mutated},
    )
    _expect_block_with_rule(repo, "specs", "required")


def test_specs_wrong_type_blocks(tmp_path):
    def mut(fm):
        fm["estimated_effort_days"] = "three"
        return fm
    mutated = _mutate_frontmatter(SPECS_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"SPECS.md": mutated},
    )
    _expect_block_with_rule(repo, "specs", "type")


def test_specs_extra_field_blocks(tmp_path):
    def mut(fm):
        fm["unexpected_field"] = "boom"
        return fm
    mutated = _mutate_frontmatter(SPECS_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"SPECS.md": mutated},
    )
    _expect_block_with_rule(repo, "specs", "additionalProperties")


# ---------------------------------------------------------------------------
# CONTEXT
# ---------------------------------------------------------------------------


def test_context_valid_passes(tmp_path):
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"CONTEXT.md": CONTEXT_VALID},
    )
    _expect_pass(repo, "context")


def test_context_missing_required_blocks(tmp_path):
    def mut(fm):
        fm.pop("participants", None)
        return fm
    mutated = _mutate_frontmatter(CONTEXT_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"CONTEXT.md": mutated},
    )
    _expect_block_with_rule(repo, "context", "required")


def test_context_wrong_type_blocks(tmp_path):
    def mut(fm):
        fm["participants"] = "user-and-ai"  # should be list
        return fm
    mutated = _mutate_frontmatter(CONTEXT_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"CONTEXT.md": mutated},
    )
    _expect_block_with_rule(repo, "context", "type")


def test_context_extra_field_blocks(tmp_path):
    def mut(fm):
        fm["random"] = "value"
        return fm
    mutated = _mutate_frontmatter(CONTEXT_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"CONTEXT.md": mutated},
    )
    _expect_block_with_rule(repo, "context", "additionalProperties")


# ---------------------------------------------------------------------------
# PLAN
# ---------------------------------------------------------------------------


def test_plan_valid_passes(tmp_path):
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"PLAN.md": PLAN_VALID},
    )
    _expect_pass(repo, "plan")


def test_plan_missing_required_blocks(tmp_path):
    def mut(fm):
        fm.pop("total_waves", None)
        return fm
    mutated = _mutate_frontmatter(PLAN_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"PLAN.md": mutated},
    )
    _expect_block_with_rule(repo, "plan", "required")


def test_plan_wrong_type_blocks(tmp_path):
    def mut(fm):
        fm["total_tasks"] = "four"
        return fm
    mutated = _mutate_frontmatter(PLAN_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"PLAN.md": mutated},
    )
    _expect_block_with_rule(repo, "plan", "type")


def test_plan_extra_field_blocks(tmp_path):
    def mut(fm):
        fm["weird_key"] = 1
        return fm
    mutated = _mutate_frontmatter(PLAN_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"PLAN.md": mutated},
    )
    _expect_block_with_rule(repo, "plan", "additionalProperties")


# ---------------------------------------------------------------------------
# TEST-GOALS
# ---------------------------------------------------------------------------


def test_test_goals_valid_passes(tmp_path):
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"TEST-GOALS.md": TEST_GOALS_VALID},
    )
    _expect_pass(repo, "test-goals")


def test_test_goals_missing_required_blocks(tmp_path):
    def mut(fm):
        fm.pop("goal_count", None)
        return fm
    mutated = _mutate_frontmatter(TEST_GOALS_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"TEST-GOALS.md": mutated},
    )
    _expect_block_with_rule(repo, "test-goals", "required")


def test_test_goals_wrong_type_blocks(tmp_path):
    def mut(fm):
        fm["goal_count"] = "two"
        return fm
    mutated = _mutate_frontmatter(TEST_GOALS_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"TEST-GOALS.md": mutated},
    )
    _expect_block_with_rule(repo, "test-goals", "type")


def test_test_goals_extra_field_blocks(tmp_path):
    def mut(fm):
        fm["mystery"] = True
        return fm
    mutated = _mutate_frontmatter(TEST_GOALS_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"TEST-GOALS.md": mutated},
    )
    _expect_block_with_rule(repo, "test-goals", "additionalProperties")


# ---------------------------------------------------------------------------
# SUMMARY
# ---------------------------------------------------------------------------


def test_summary_valid_passes(tmp_path):
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"SUMMARY.md": SUMMARY_VALID},
    )
    _expect_pass(repo, "summary")


def test_summary_missing_required_blocks(tmp_path):
    def mut(fm):
        fm.pop("final_commit", None)
        return fm
    mutated = _mutate_frontmatter(SUMMARY_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"SUMMARY.md": mutated},
    )
    _expect_block_with_rule(repo, "summary", "required")


def test_summary_wrong_type_blocks(tmp_path):
    def mut(fm):
        fm["status"] = 1  # should be string from enum
        return fm
    mutated = _mutate_frontmatter(SUMMARY_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"SUMMARY.md": mutated},
    )
    _expect_block_with_rule(repo, "summary", "type")


def test_summary_extra_field_blocks(tmp_path):
    def mut(fm):
        fm["bogus"] = "x"
        return fm
    mutated = _mutate_frontmatter(SUMMARY_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"SUMMARY.md": mutated},
    )
    _expect_block_with_rule(repo, "summary", "additionalProperties")


# ---------------------------------------------------------------------------
# UAT
# ---------------------------------------------------------------------------


def test_uat_valid_passes(tmp_path):
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"UAT.md": UAT_VALID},
    )
    _expect_pass(repo, "uat")


def test_uat_missing_required_blocks(tmp_path):
    def mut(fm):
        fm.pop("verdict", None)
        return fm
    mutated = _mutate_frontmatter(UAT_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"UAT.md": mutated},
    )
    _expect_block_with_rule(repo, "uat", "required")


def test_uat_wrong_type_blocks(tmp_path):
    def mut(fm):
        fm["goals_passed"] = "two"
        return fm
    mutated = _mutate_frontmatter(UAT_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"UAT.md": mutated},
    )
    _expect_block_with_rule(repo, "uat", "type")


def test_uat_extra_field_blocks(tmp_path):
    def mut(fm):
        fm["spurious"] = "y"
        return fm
    mutated = _mutate_frontmatter(UAT_VALID, mut)
    repo = _setup_fake_repo(
        tmp_path, phase="14", files={"UAT.md": mutated},
    )
    _expect_block_with_rule(repo, "uat", "additionalProperties")


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


def test_grandfather_skip_when_cutoff_set(tmp_path):
    """Phase major < cutoff → PASS regardless of malformed content."""
    bogus = "---\nthis is: not_valid\n---\n\nbody\n"
    repo = _setup_fake_repo(
        tmp_path, phase="5", files={"SPECS.md": bogus},
    )
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    env["VG_SCHEMA_GRANDFATHER_BEFORE"] = "14"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--phase", "5", "--artifact", "specs"],
        capture_output=True, text=True, cwd=repo, env=env, timeout=15,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert data["verdict"] == "PASS", data
    assert data["evidence"] == [], data


def test_all_mode_runs_every_artifact(tmp_path):
    """--all invokes all 6 artifact validations sequentially."""
    files = {fname: content for (fname, content) in VALID_FIXTURES.values()}
    repo = _setup_fake_repo(tmp_path, phase="14", files=files)
    rc, data = _run(repo, "14", "--all")
    assert rc == 0, data
    assert data["verdict"] in ("PASS", "WARN"), data
    # Re-run with one artifact intentionally broken — confirm --all surfaces it.
    files["SUMMARY.md"] = _mutate_frontmatter(
        SUMMARY_VALID, lambda fm: (fm.update({"status": "weird"}) or fm),
    )
    repo2 = _setup_fake_repo(tmp_path / "sub", phase="14", files=files)
    rc2, data2 = _run(repo2, "14", "--all")
    assert rc2 == 1, data2
    assert data2["verdict"] == "BLOCK", data2
    assert any(
        "summary.md" in (e.get("file") or "").lower()
        or "SUMMARY.md" in e.get("message", "")
        for e in data2["evidence"]
    ), data2
