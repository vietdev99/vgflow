"""
R6 Task 12 — CONTEXT template explicit `## Goals` section.

Schema-check downstream (blueprint/build) expects a structured `## Goals`
section with `### In-scope` + `### Out-of-scope` subsections in
CONTEXT.md. This test pins:

  1. The artifact-write.md template contains `## Goals`, `### In-scope`,
     `### Out-of-scope` headings — so the AI scaffolds the section every
     run.
  2. `### In-scope` and `### Out-of-scope` are nested under `## Goals`
     (positional check — In-scope appears AFTER `## Goals` and BEFORE
     the next `## ` H2).
  3. The verify-artifact-schema.py validator lists `## Goals` as a
     required H2 anchor for `context` artifacts (regression guard
     against drift).
  4. A CONTEXT.md missing `## Goals` blocks in the validator
     (subprocess test, mirror parity).
  5. A CONTEXT.md WITH `## Goals` passes the validator.

Mirror parity: both `commands/vg/_shared/scope/artifact-write.md` and
`.claude/commands/vg/_shared/scope/artifact-write.md` carry the same
template body.
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

# Resolve repo root: this file lives at either
#   <repo>/scripts/tests/test_context_goals_section.py     (canonical)  → parents[2]
#   <repo>/.claude/scripts/tests/test_context_goals_section.py (mirror) → parents[3]
# Walk up until we find both `commands/vg` (canonical) and `.claude/commands/vg`.
def _resolve_repo_root() -> Path:
    here = Path(__file__).resolve()
    for ancestor in [here, *here.parents]:
        if (ancestor / "commands" / "vg").is_dir() and (
            ancestor / ".claude" / "commands" / "vg"
        ).is_dir():
            return ancestor
    # Fallback to parents[3] (matches existing test pattern in mirror).
    return here.parents[3]


REPO_ROOT = _resolve_repo_root()
TEMPLATE = REPO_ROOT / "commands" / "vg" / "_shared" / "scope" / "artifact-write.md"
TEMPLATE_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "scope" / "artifact-write.md"
# Prefer the canonical validator copy; fall back to the .claude mirror.
_CANONICAL_VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-artifact-schema.py"
_MIRROR_VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-artifact-schema.py"
VALIDATOR = _CANONICAL_VALIDATOR if _CANONICAL_VALIDATOR.exists() else _MIRROR_VALIDATOR
_CANONICAL_SCHEMAS = REPO_ROOT / "schemas"
_MIRROR_SCHEMAS = REPO_ROOT / ".claude" / "schemas"
SCHEMA_DIR_SRC = _CANONICAL_SCHEMAS if _CANONICAL_SCHEMAS.is_dir() else _MIRROR_SCHEMAS


# ─── Template structure assertions ───────────────────────────────────────


def test_template_has_goals_section():
    """Template must contain `## Goals`, `### In-scope`, `### Out-of-scope`."""
    body = TEMPLATE.read_text(encoding="utf-8")
    assert re.search(r"^##\s+Goals\b", body, re.MULTILINE), (
        "artifact-write.md template missing `## Goals` H2"
    )
    assert re.search(r"^###\s+In-scope\b", body, re.MULTILINE), (
        "artifact-write.md template missing `### In-scope` H3"
    )
    assert re.search(r"^###\s+Out-of-scope\b", body, re.MULTILINE), (
        "artifact-write.md template missing `### Out-of-scope` H3"
    )


def test_in_scope_nested_under_goals():
    """`### In-scope` must appear AFTER `## Goals` and BEFORE next `## ` H2."""
    body = TEMPLATE.read_text(encoding="utf-8")
    goals_match = re.search(r"^##\s+Goals\b", body, re.MULTILINE)
    in_scope_match = re.search(r"^###\s+In-scope\b", body, re.MULTILINE)
    out_scope_match = re.search(r"^###\s+Out-of-scope\b", body, re.MULTILINE)
    assert goals_match and in_scope_match and out_scope_match

    # Find next `## ` H2 after Goals (excluding the Goals heading itself)
    after_goals = body[goals_match.end():]
    next_h2_match = re.search(r"^##\s+\S", after_goals, re.MULTILINE)
    next_h2_offset = (
        goals_match.end() + next_h2_match.start() if next_h2_match else len(body)
    )

    assert goals_match.start() < in_scope_match.start() < next_h2_offset, (
        "`### In-scope` must be nested directly under `## Goals` "
        f"(goals@{goals_match.start()}, in_scope@{in_scope_match.start()}, "
        f"next_h2@{next_h2_offset})"
    )
    assert goals_match.start() < out_scope_match.start() < next_h2_offset, (
        "`### Out-of-scope` must be nested directly under `## Goals`"
    )


def test_template_mirror_parity():
    """Canonical template + .claude mirror must be byte-identical."""
    canonical = TEMPLATE.read_text(encoding="utf-8")
    mirror = TEMPLATE_MIRROR.read_text(encoding="utf-8")
    assert canonical == mirror, (
        "artifact-write.md drift: commands/vg/_shared/scope/artifact-write.md "
        "differs from .claude/commands/vg/_shared/scope/artifact-write.md — "
        "re-run sync."
    )


# ─── Validator wiring assertion ──────────────────────────────────────────


def test_validator_requires_goals_h2_for_context():
    """verify-artifact-schema.py BODY_H2_REQUIRED['context'] includes Goals."""
    src = VALIDATOR.read_text(encoding="utf-8")
    # Locate the BODY_H2_REQUIRED dict + the "context" key block.
    m = re.search(
        r'"context":\s*\[(.*?)\]',
        src, re.DOTALL,
    )
    assert m, "BODY_H2_REQUIRED['context'] block not found in validator"
    block = m.group(1)
    assert r"^##\s+Goals\b" in block, (
        f"BODY_H2_REQUIRED['context'] missing `## Goals` anchor; got: {block}"
    )


# ─── Subprocess validator behavior assertions ────────────────────────────


def _setup_fake_repo(tmp_path: Path, *, phase: str, context_md: str) -> Path:
    scripts_dir = tmp_path / ".claude" / "scripts" / "validators"
    scripts_dir.mkdir(parents=True)
    shutil.copy(VALIDATOR, scripts_dir / VALIDATOR.name)
    for helper in ("_common.py", "_i18n.py", "_repo_root.py"):
        for candidate in (
            REPO_ROOT / "scripts" / "validators" / helper,
            REPO_ROOT / ".claude" / "scripts" / "validators" / helper,
        ):
            if candidate.exists():
                shutil.copy(candidate, scripts_dir / helper)
                break
    schema_dst = tmp_path / ".claude" / "schemas"
    schema_dst.mkdir(parents=True)
    for schema_file in SCHEMA_DIR_SRC.glob("*.json"):
        shutil.copy(schema_file, schema_dst / schema_file.name)
    narr_src = (
        REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
        / "narration-strings.yaml"
    )
    if narr_src.exists():
        narr_dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
        narr_dst.mkdir(parents=True)
        shutil.copy(narr_src, narr_dst / "narration-strings.yaml")

    phase_dir = tmp_path / ".vg" / "phases" / phase
    phase_dir.mkdir(parents=True)
    (phase_dir / "CONTEXT.md").write_text(context_md, encoding="utf-8")
    return tmp_path


def _run_validator(repo: Path, phase: str) -> tuple[int, dict]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", phase, "--artifact", "context"],
        capture_output=True, text=True, cwd=repo, env=env, timeout=15,
    )
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        data = {"verdict": "ERROR", "raw_stdout": proc.stdout, "raw_stderr": proc.stderr}
    return proc.returncode, data


CONTEXT_WITH_GOALS = """\
---
phase: "14"
discussed_in: 2026-04-26
participants:
  - user
  - ai
---

## Goals

### In-scope
- Ship feature X.

### Out-of-scope (deferred / not this phase)
- Feature Y deferred.

## Decisions

### D-01: Adopt approach A
**Decision:** Use approach A.
**Rationale:** Simpler.

## Open questions

None.

## Risks

- None identified.
"""


CONTEXT_WITHOUT_GOALS = """\
---
phase: "14"
discussed_in: 2026-04-26
participants:
  - user
  - ai
---

## Decisions

### D-01: Adopt approach A
**Decision:** Use approach A.
**Rationale:** Simpler.

## Open questions

None.

## Risks

- None identified.
"""


def test_validator_passes_with_goals(tmp_path):
    repo = _setup_fake_repo(tmp_path, phase="14", context_md=CONTEXT_WITH_GOALS)
    rc, data = _run_validator(repo, "14")
    assert rc == 0, data
    assert data.get("verdict") in ("PASS", "WARN"), data


def test_validator_blocks_without_goals(tmp_path):
    repo = _setup_fake_repo(tmp_path, phase="14", context_md=CONTEXT_WITHOUT_GOALS)
    rc, data = _run_validator(repo, "14")
    assert rc == 1, data
    assert data.get("verdict") == "BLOCK", data
    types = [e["type"] for e in data.get("evidence", [])]
    messages = [e.get("message", "") for e in data.get("evidence", [])]
    assert any(t == "missing_required_section" for t in types), (
        f"expected missing_required_section evidence type, got types={types}"
    )
    assert any("Goals" in msg for msg in messages), (
        f"expected Goals-related missing_required_section message, got: {messages}"
    )
