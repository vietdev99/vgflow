"""
R7 Task 7 (G3) — Tests for edge-case coverage audit validator.

Coverage:
  Validator (scripts/validators/verify-edge-case-coverage.py):
    - test_validator_passes_no_edge_cases       — capsule.edge_cases_for_goals empty → PASS
    - test_validator_passes_when_critical_variants_marked — all critical markers present → PASS
    - test_validator_blocks_when_critical_missing — critical variant has no marker → BLOCK rc=1
    - test_validator_warns_on_high_priority_missing — only high-priority short → WARN rc=0

  Wiring:
    - test_post_execution_wires_validator       — waves-overview.md 8d.5e block exists
    - test_build_md_frontmatter_has_override_flag — build.md forbids --skip-edge-case-coverage-audit
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-edge-case-coverage.py"
WAVES_OVERVIEW_MD = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "waves-overview.md"
)
BUILD_MD = REPO_ROOT / "commands" / "vg" / "build.md"


# ─── Helpers ──────────────────────────────────────────────────────────


def _stage_phase(
    tmp_path: Path,
    *,
    edge_cases_for_goals: list[str] | None,
    edge_case_files: dict[str, str] | None = None,
    handler_files: dict[str, str] | None = None,
    task_id: str = "task-04",
) -> Path:
    """Stage tmp phase dir.

    edge_cases_for_goals: list written into capsule (None → empty []).
    edge_case_files: {goal_id: markdown_body} — written under EDGE-CASES/.
    handler_files: {repo_relative_path: file_contents} — written into
                   tmp_path so the validator's repo_root grep finds them.
    """
    phase_dir = tmp_path / "07.99-test"
    phase_dir.mkdir(parents=True)

    capsule_dir = phase_dir / ".task-capsules"
    capsule_dir.mkdir()

    artifacts: list[str] = []

    if edge_case_files:
        edge_dir = phase_dir / "EDGE-CASES"
        edge_dir.mkdir()
        for goal_id, body in edge_case_files.items():
            (edge_dir / f"{goal_id}.md").write_text(body, encoding="utf-8")

    if handler_files:
        for rel, contents in handler_files.items():
            full = tmp_path / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(contents, encoding="utf-8")
            artifacts.append(rel)

    capsule = {
        "task_id": task_id,
        "task_context": {},
        "contract_context": {},
        "goals_context": {},
        "sibling_context": {},
        "downstream_callers": [],
        "build_config": {},
        "tdd_required": False,
        "edge_cases_for_goals": edge_cases_for_goals or [],
    }
    (capsule_dir / f"{task_id}.capsule.json").write_text(
        json.dumps(capsule), encoding="utf-8",
    )

    if artifacts:
        bl_dir = phase_dir / "BUILD-LOG"
        bl_dir.mkdir()
        artifact_lines = "\n".join(f"- {p} (lines added: 5, removed: 0)" for p in artifacts)
        (bl_dir / f"{task_id}.md").write_text(
            f"# Task {task_id} — test stub\n\n"
            f"**Files modified**:\n{artifact_lines}\n",
            encoding="utf-8",
        )

    return phase_dir


def _run_validator(phase_dir: Path, repo_root: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if repo_root is not None:
        env["VG_REPO_ROOT"] = str(repo_root)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase-dir", str(phase_dir)],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace",
    )


def _parse_output(proc: subprocess.CompletedProcess) -> dict:
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    return json.loads(line)


# Edge-case file template — 1 critical, 1 high, 1 medium variant for G-04.
def _edge_case_md_g04() -> str:
    return textwrap.dedent("""
        # Edge Cases — G-04: User creates site with custom domain

        **Goal source**: TEST-GOALS/G-04.md
        **Profile**: web-fullstack
        **Skipped categories**: []

        ## Boundary inputs
        | variant_id | input | expected_outcome | priority |
        |---|---|---|---|
        | G-04-b1 | domain="" (empty) | 400 with field-level error "domain required" | critical |
        | G-04-b2 | domain="a"*256 | 400 "domain ≤ 253 chars" | high |
        | G-04-b3 | domain="invalid space" | 400 "invalid hostname format" | medium |
    """).strip()


# ─── Validator behavioral tests ───────────────────────────────────────


def test_validator_passes_no_edge_cases(tmp_path):
    """Capsule with empty edge_cases_for_goals → PASS rc=0."""
    phase_dir = _stage_phase(tmp_path, edge_cases_for_goals=None)
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] in ("PASS", "WARN"), out


def test_validator_passes_when_critical_variants_marked(tmp_path):
    """All critical variants have `// vg-edge-case:` markers → PASS rc=0."""
    handler = textwrap.dedent("""
        export async function POST(req) {
          const body = await req.json();
          // vg-edge-case: G-04-b1 (empty domain → 400)
          if (!body.domain) return Response.json({ error: 'domain required' }, { status: 400 });
          // vg-edge-case: G-04-b2 (domain too long → 400)
          if (body.domain.length > 253) return Response.json({ error: 'domain too long' }, { status: 400 });
          // vg-edge-case: G-04-b3 (invalid hostname → 400)
          if (/\\s/.test(body.domain)) return Response.json({ error: 'invalid hostname' }, { status: 400 });
          return Response.json({ id: 'site-1' }, { status: 201 });
        }
    """).strip()
    phase_dir = _stage_phase(
        tmp_path,
        edge_cases_for_goals=["G-04"],
        edge_case_files={"G-04": _edge_case_md_g04()},
        handler_files={"apps/api/src/sites/route.ts": handler},
    )
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] in ("PASS", "WARN"), out
    # No critical-missing evidence should be emitted.
    types = {e.get("type") for e in out.get("evidence", [])}
    assert "edge_case_critical_missing" not in types, types


def test_validator_blocks_when_critical_missing(tmp_path):
    """Critical variant has NO marker in any modified file → BLOCK rc=1."""
    # Handler covers high/medium but NOT the critical b1 variant.
    handler = textwrap.dedent("""
        export async function POST(req) {
          const body = await req.json();
          // vg-edge-case: G-04-b2 (domain too long → 400)
          if (body.domain && body.domain.length > 253) {
            return Response.json({ error: 'domain too long' }, { status: 400 });
          }
          // vg-edge-case: G-04-b3 (invalid hostname → 400)
          if (body.domain && /\\s/.test(body.domain)) {
            return Response.json({ error: 'invalid hostname' }, { status: 400 });
          }
          return Response.json({ id: 'site-1' }, { status: 201 });
        }
    """).strip()
    phase_dir = _stage_phase(
        tmp_path,
        edge_cases_for_goals=["G-04"],
        edge_case_files={"G-04": _edge_case_md_g04()},
        handler_files={"apps/api/src/sites/route.ts": handler},
    )
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 1, (
        f"Expected BLOCK rc=1 (critical missing), got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK"
    types = {e.get("type") for e in out["evidence"]}
    assert "edge_case_critical_missing" in types, types
    # Confirm the missing variant is the critical b1.
    msgs = " ".join(e.get("message", "") for e in out["evidence"])
    assert "G-04-b1" in msgs, msgs


def test_validator_warns_on_high_priority_missing(tmp_path):
    """Critical variants covered, but high-priority short of 80% → WARN rc=0.

    Edge-case fixture has 4 high-priority variants — covering only 1 (25%)
    drops below the 80% floor.
    """
    edge_case_md = textwrap.dedent("""
        # Edge Cases — G-05: Update site

        | variant_id | input | expected_outcome | priority |
        |---|---|---|---|
        | G-05-b1 | empty body | 400 | critical |
        | G-05-h1 | 1 simultaneous PATCH | 200 | high |
        | G-05-h2 | 2 simultaneous PATCHs same row | first 200 second 409 | high |
        | G-05-h3 | stale If-Match | 412 | high |
        | G-05-h4 | invalid version header | 400 | high |
    """).strip()
    handler = textwrap.dedent("""
        export async function PATCH(req) {
          // vg-edge-case: G-05-b1 (empty body → 400)
          const body = await req.json();
          if (!body || Object.keys(body).length === 0) {
            return Response.json({ error: 'empty' }, { status: 400 });
          }
          // vg-edge-case: G-05-h1 (single update → 200)
          return Response.json({ ok: true }, { status: 200 });
        }
    """).strip()
    phase_dir = _stage_phase(
        tmp_path,
        edge_cases_for_goals=["G-05"],
        edge_case_files={"G-05": edge_case_md},
        handler_files={"apps/api/src/sites/route.ts": handler},
    )
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 0, (
        f"Expected WARN rc=0 (high-priority undercovered), got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "WARN", out
    types = {e.get("type") for e in out["evidence"]}
    assert "edge_case_high_priority_undercovered" in types, types
    # No critical evidence (b1 is marked).
    assert "edge_case_critical_missing" not in types, types


# ─── Wiring tests ─────────────────────────────────────────────────────


def test_post_execution_wires_validator():
    """waves-overview.md MUST invoke verify-edge-case-coverage.py at 8d.5e."""
    text = WAVES_OVERVIEW_MD.read_text(encoding="utf-8")
    assert "verify-edge-case-coverage.py" in text, (
        "waves-overview.md does not invoke verify-edge-case-coverage.py — "
        "gate not wired."
    )
    assert "8d.5e" in text, (
        "Section header `8d.5e` not found — edge-case coverage audit must be "
        "labeled as sibling of 8d.5c RCRURD audit + 8d.5d workflow audit."
    )


def test_build_md_frontmatter_has_override_flag():
    """build.md `forbidden_without_override` must list --skip-edge-case-coverage-audit."""
    text = BUILD_MD.read_text(encoding="utf-8")
    assert "--skip-edge-case-coverage-audit" in text, (
        "build.md frontmatter missing `--skip-edge-case-coverage-audit` "
        "in forbidden_without_override list."
    )
    m = re.search(
        r"forbidden_without_override:\s*\n((?:\s+(?:-\s+.+|#.+)\n)+)",
        text,
    )
    assert m is not None, "forbidden_without_override block not found in build.md"
    assert "--skip-edge-case-coverage-audit" in m.group(1), (
        "Override flag not under `forbidden_without_override:` block."
    )
