"""
R7 Task 3 (G1) — Tests for RCRURD implementation audit validator.

Coverage:
  Validator (scripts/validators/verify-rcrurd-implementation.py):
    - test_validator_passes_no_invariants            — empty rcrurd_invariants_paths → PASS
    - test_validator_passes_when_handler_has_404_for_delete — DELETE invariant + handler grep finds 404 → PASS
    - test_validator_warns_when_delete_handler_lacks_404    — DELETE invariant + no 404 in handler → WARN, rc=0
    - test_validator_blocks_on_contradiction         — DELETE invariant + handler hardcodes 200 near endpoint → BLOCK, rc=1
    - test_validator_passes_when_create_handler_returns_id  — POST invariant + handler returns object with id → PASS
    - test_validator_handles_malformed_yaml_gracefully      — yaml parse fail → WARN with malformed_invariant evidence

  Wiring:
    - test_post_execution_validation_md_wires_validator    — waves-overview.md mentions verify-rcrurd-implementation.py at 8d.5c
    - test_build_md_frontmatter_has_override_flag          — build.md frontmatter lists --skip-rcrurd-implementation-audit
    - test_preflight_md_allowlists_override_flag           — preflight VALID_FLAGS_PATTERN includes the flag

Validator emit_and_exit semantics (per scripts/validators/_common.py):
  - rc 0 → PASS or WARN
  - rc 1 → BLOCK
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-rcrurd-implementation.py"
WAVES_OVERVIEW_MD = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "waves-overview.md"
)
POST_EXEC_VAL_MD = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "post-execution-validation.md"
)
BUILD_MD = REPO_ROOT / "commands" / "vg" / "build.md"
PREFLIGHT_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "preflight.md"


# ─── Helpers ──────────────────────────────────────────────────────────


def _stage_phase(
    tmp_path: Path,
    *,
    invariant_yaml: str | None,
    handler_files: dict[str, str] | None = None,
    task_id: str = "task-04",
    goal_id: str = "G-01",
) -> Path:
    """Stage a tmp phase dir with one capsule + optional invariant yaml + handler files.

    invariant_yaml=None → empty rcrurd_invariants_paths.
    handler_files: {repo_relative_path: file_contents}.
    """
    phase_dir = tmp_path / "07.99-test"
    phase_dir.mkdir(parents=True)

    capsule_dir = phase_dir / ".task-capsules"
    capsule_dir.mkdir()

    rcrurd_paths: list[str] = []
    artifacts: list[str] = []

    if invariant_yaml is not None:
        ext_dir = phase_dir / ".rcrurd-extracted"
        ext_dir.mkdir()
        yaml_file = ext_dir / f"{goal_id}.yaml"
        yaml_file.write_text(invariant_yaml, encoding="utf-8")
        rcrurd_paths.append(str(yaml_file))

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
        "rcrurd_invariants_paths": rcrurd_paths,
    }
    (capsule_dir / f"{task_id}.capsule.json").write_text(
        json.dumps(capsule), encoding="utf-8",
    )

    # Stage BUILD-LOG/task-NN.md so validator can read artifacts_written
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


# ─── Validator behavioral tests ───────────────────────────────────────


def test_validator_passes_no_invariants(tmp_path):
    """Capsule with empty rcrurd_invariants_paths → PASS rc=0."""
    phase_dir = _stage_phase(tmp_path, invariant_yaml=None)
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] in ("PASS", "WARN"), out


def test_validator_passes_when_handler_has_404_for_delete(tmp_path):
    """DELETE invariant + handler file contains 404 literal → PASS."""
    yaml_doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write:
            method: DELETE
            endpoint: /api/sites/{siteId}
          read:
            method: GET
            endpoint: /api/sites/{siteId}
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - path: $.error
              op: equals
              value_from: literal:not_found
    """).strip()
    handler = textwrap.dedent("""
        export async function DELETE(req, ctx) {
          const site = await db.sites.delete({ id: ctx.params.siteId });
          if (!site) return Response.json({ error: 'not_found' }, { status: 404 });
          return Response.json({ ok: true }, { status: 200 });
        }
    """).strip()
    phase_dir = _stage_phase(
        tmp_path,
        invariant_yaml=yaml_doc,
        handler_files={"apps/api/src/sites/route.ts": handler},
    )
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] in ("PASS", "WARN"), out


def test_validator_warns_when_delete_handler_lacks_404(tmp_path):
    """DELETE invariant but handler has no 404/NotFoundError → WARN rc=0."""
    yaml_doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write:
            method: DELETE
            endpoint: /api/sites/{siteId}
          read:
            method: GET
            endpoint: /api/sites/{siteId}
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - path: $.error
              op: equals
              value_from: literal:not_found
    """).strip()
    handler = textwrap.dedent("""
        export async function DELETE(req, ctx) {
          await db.sites.delete({ id: ctx.params.siteId });
          return Response.json({ ok: true }, { status: 200 });
        }
    """).strip()
    phase_dir = _stage_phase(
        tmp_path,
        invariant_yaml=yaml_doc,
        handler_files={"apps/api/src/sites/route.ts": handler},
    )
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 0, (
        f"Expected WARN rc=0 (heuristic miss), got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "WARN", out
    types = {e.get("type") for e in out["evidence"]}
    assert "rcrurd_delete_missing_404" in types, types


def test_validator_blocks_on_contradiction(tmp_path):
    """DELETE invariant says 404 but handler explicitly hardcodes 200
    on the not-found branch near the endpoint → BLOCK rc=1.

    Heuristic: handler grep finds a `not_found` literal/comment AND
    the response status code adjacent to it is 200, not 404.
    """
    yaml_doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write:
            method: DELETE
            endpoint: /api/sites/{siteId}
          read:
            method: GET
            endpoint: /api/sites/{siteId}
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - path: $.error
              op: equals
              value_from: literal:not_found
    """).strip()
    # Handler explicitly returns 200 on not-found path — clear contradiction
    handler = textwrap.dedent("""
        export async function DELETE(req, ctx) {
          const site = await db.sites.delete({ id: ctx.params.siteId });
          if (!site) {
            // not_found path — HARDCODED 200 (BUG)
            return Response.json({ error: 'not_found' }, { status: 200 });
          }
          return Response.json({ ok: true }, { status: 200 });
        }
    """).strip()
    phase_dir = _stage_phase(
        tmp_path,
        invariant_yaml=yaml_doc,
        handler_files={"apps/api/src/sites/route.ts": handler},
    )
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 1, (
        f"Expected BLOCK rc=1 (contradiction), got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK"
    types = {e.get("type") for e in out["evidence"]}
    assert "rcrurd_delete_contradiction" in types, types


def test_validator_passes_when_create_handler_returns_id(tmp_path):
    """POST invariant + handler returns object with id field → PASS."""
    yaml_doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write:
            method: POST
            endpoint: /api/sites
          read:
            method: GET
            endpoint: /api/sites/{siteId}
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - path: $.id
              op: equals
              value_from: action.id
    """).strip()
    handler = textwrap.dedent("""
        export async function POST(req) {
          const body = await req.json();
          const site = await db.sites.create({ data: body });
          return Response.json({ id: site.id, name: site.name }, { status: 201 });
        }
    """).strip()
    phase_dir = _stage_phase(
        tmp_path,
        invariant_yaml=yaml_doc,
        handler_files={"apps/api/src/sites/route.ts": handler},
    )
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] in ("PASS", "WARN"), out


def test_validator_handles_malformed_yaml_gracefully(tmp_path):
    """Malformed yaml → WARN with malformed_invariant evidence (not crash)."""
    bad_yaml = "this is: : : not yaml ::: [garbage"
    phase_dir = _stage_phase(
        tmp_path,
        invariant_yaml=bad_yaml,
        handler_files={"apps/api/src/sites/route.ts": "export async function DELETE() {}"},
    )
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 0, (
        f"Expected WARN rc=0 (graceful degradation), got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "WARN", out
    types = {e.get("type") for e in out["evidence"]}
    assert "rcrurd_malformed_invariant" in types, types


# ─── Wiring tests ─────────────────────────────────────────────────────


def test_post_execution_validation_md_wires_validator():
    """Either waves-overview.md (sibling 8d.5b) OR post-execution-validation.md
    must invoke verify-rcrurd-implementation.py at 8d.5c."""
    waves_text = WAVES_OVERVIEW_MD.read_text(encoding="utf-8")
    post_text = POST_EXEC_VAL_MD.read_text(encoding="utf-8")
    combined = waves_text + post_text
    assert "verify-rcrurd-implementation.py" in combined, (
        "Neither waves-overview.md nor post-execution-validation.md "
        "invokes verify-rcrurd-implementation.py — gate not wired."
    )
    assert "8d.5c" in combined, (
        "Section header `8d.5c` not found — RCRURD audit must be "
        "labeled as sibling of 8d.5b TDD evidence audit."
    )


def test_build_md_frontmatter_has_override_flag():
    """build.md `forbidden_without_override` must list --skip-rcrurd-implementation-audit."""
    text = BUILD_MD.read_text(encoding="utf-8")
    assert '"--skip-rcrurd-implementation-audit"' in text or \
           "'--skip-rcrurd-implementation-audit'" in text or \
           "--skip-rcrurd-implementation-audit" in text, (
        "build.md frontmatter missing `--skip-rcrurd-implementation-audit` "
        "in forbidden_without_override list."
    )
    # Must appear inside forbidden_without_override block. Tolerate
    # comment lines (`# ...`) interleaved with `- "..."` entries.
    m = re.search(
        r"forbidden_without_override:\s*\n((?:\s+(?:-\s+.+|#.+)\n)+)",
        text,
    )
    assert m is not None, "forbidden_without_override block not found in build.md"
    assert "--skip-rcrurd-implementation-audit" in m.group(1), (
        "Override flag not under `forbidden_without_override:` block."
    )


def test_preflight_md_allowlists_override_flag():
    """preflight.md VALID_FLAGS_PATTERN must include skip-rcrurd-implementation-audit."""
    text = PREFLIGHT_MD.read_text(encoding="utf-8")
    assert "skip-rcrurd-implementation-audit" in text, (
        "preflight.md VALID_FLAGS_PATTERN does not allow "
        "--skip-rcrurd-implementation-audit — flag would be rejected."
    )
