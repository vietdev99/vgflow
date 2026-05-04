#!/usr/bin/env python3
"""
Validator: verify-workflow-implementation.py — R7 Task 4 (G2)

Post-spawn workflow implementation audit. For every task capsule under
${PHASE_DIR}/.task-capsules/task-*.capsule.json with a non-null
`workflow_id` AND `workflow_step`, this validator HEURISTICALLY checks
that the modified handler files actually transition state to the value
declared by ${PHASE_DIR}/WORKFLOW-SPECS/<workflow_id>.md state_machine
for that step (e.g. `pending_admin_review`).

Why heuristic + grep:
  Static analysis cannot prove a workflow state machine without full
  control-flow + dataflow analysis. A grep miss is a strong signal the
  task implemented the wrong state literal (codex audit failure mode:
  task implements `approved` while WF declares `pending_admin_review`).
  Build typecheck/tests pass either way; this gate raises the issue
  early instead of letting review's runtime probe catch it late.

Severity matrix:
  - PASS: state literal found in modified handler/route/state files,
          OR no workflow_id declared in any capsule of the wave.
  - WARN: state literal found ONLY in *.spec.ts / *.test.ts contexts,
          OR malformed WORKFLOW-SPECS yaml (graceful degradation —
          stale phase, do not crash the build).
  - BLOCK: workflow_id + workflow_step declared, expected state literal
          resolved from WORKFLOW-SPECS, but NOT found anywhere in
          modified files. Strong signal the implementation diverges
          from the workflow spec.

Pairs with R7 Task 5 (G9 — review replay of workflow runtime probe).

Usage:
  verify-workflow-implementation.py --phase 7.14
  verify-workflow-implementation.py --phase-dir /abs/path/to/phase

Output: vg.validator-output JSON on stdout (rc 0 PASS/WARN, rc 1 BLOCK).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

YAML_FENCE_RE = re.compile(r"```ya?ml\n(?P<body>.+?)\n```", re.DOTALL)


def _load_capsule(capsule_path: Path) -> dict | None:
    try:
        return json.loads(capsule_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_workflow_spec(phase_dir: Path, workflow_id: str) -> tuple[dict | None, str | None]:
    """Returns (parsed_spec_or_None, error_message_or_None).

    Graceful degradation: missing pyyaml, file not found, or parse
    errors return (None, msg) so the caller can WARN rather than crash.
    """
    spec_path = phase_dir / "WORKFLOW-SPECS" / f"{workflow_id}.md"
    if not spec_path.exists():
        return None, f"WORKFLOW-SPECS/{workflow_id}.md not found"
    try:
        text = spec_path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"unreadable spec file: {e}"
    m = YAML_FENCE_RE.search(text)
    if not m:
        return None, "no yaml fence found in spec"
    try:
        import yaml  # type: ignore
    except ImportError:
        return None, "pyyaml not installed; cannot parse WORKFLOW-SPECS"
    try:
        data = yaml.safe_load(m.group("body"))
        if not isinstance(data, dict):
            return None, "yaml root is not a mapping"
        return data, None
    except Exception as e:
        return None, f"yaml parse error: {type(e).__name__}: {e}"


def _state_after_for_step(spec: dict, step_id) -> str | None:
    """Pull the `state_after` value for a given step_id from spec.steps[].

    state_after is a dict (e.g. `{db: pending_admin_review}`). We return
    the FIRST value because heuristic state-literal grep only needs one.
    Returns None when step missing or state_after absent.
    """
    try:
        step_target = int(step_id) if not isinstance(step_id, int) else step_id
    except (TypeError, ValueError):
        return None
    for step in (spec.get("steps") or []):
        if not isinstance(step, dict):
            continue
        sid = step.get("step_id")
        try:
            sid_int = int(sid) if not isinstance(sid, int) else sid
        except (TypeError, ValueError):
            continue
        if sid_int == step_target:
            sa = step.get("state_after")
            if isinstance(sa, dict) and sa:
                # Return first non-empty value as the canonical state literal.
                for v in sa.values():
                    if v is not None and str(v).strip():
                        return str(v).strip()
            elif isinstance(sa, str) and sa.strip():
                return sa.strip()
            return None
    return None


def _parse_artifacts_from_build_log(phase_dir: Path, task_id: str) -> list[str]:
    """Read BUILD-LOG/task-NN.md and extract `Files modified` paths.

    Mirrors verify-rcrurd-implementation.py parser. See that file for
    format reference (per agents/vg-build-task-executor/SKILL.md step 15).
    """
    bl = phase_dir / "BUILD-LOG" / f"{task_id}.md"
    if not bl.exists():
        return []
    try:
        body = bl.read_text(encoding="utf-8")
    except OSError:
        return []

    paths: list[str] = []
    in_section = False
    for line in body.splitlines():
        stripped = line.strip()
        if "Files modified" in stripped:
            in_section = True
            continue
        if in_section:
            if stripped.startswith("- "):
                rest = stripped[2:]
                m = re.match(r"([^\s(]+)", rest)
                if m:
                    paths.append(m.group(1))
            elif stripped == "" or stripped.startswith("##") or stripped.startswith("```"):
                if paths:
                    break
    return paths


def _looks_like_handler_or_state(path: str) -> bool:
    """Filter: handler/route/controller/state/store/reducer file.

    Workflows can transition state in route handlers (server) OR in
    client state stores (Redux/Zustand/Pinia/Context reducers). Cast a
    wider net than RCRURD validator's _looks_like_handler since
    workflow state literals appear in both surfaces.
    """
    p = path.lower()
    if "/route." in p or p.endswith("/route.ts") or p.endswith("/route.js"):
        return True
    if "controller" in p or "handler" in p:
        return True
    if "/api/" in p and (p.endswith(".ts") or p.endswith(".js") or p.endswith(".py")):
        return True
    # State / store / reducer / machine
    if any(seg in p for seg in ("/store/", "/stores/", "reducer", "/state/", "machine")):
        if p.endswith((".ts", ".tsx", ".js", ".jsx", ".py")):
            return True
    # Service / use-case files often hold workflow transitions
    if "service" in p or "use-case" in p or "usecase" in p:
        if p.endswith((".ts", ".tsx", ".js", ".py")):
            return True
    return False


def _is_test_only_path(path: str) -> bool:
    """True for *.spec.ts / *.test.ts / __tests__/ files."""
    p = path.lower()
    if ".spec." in p or ".test." in p:
        return True
    if "/__tests__/" in p or "/tests/" in p or "/test/" in p:
        return True
    return False


def _read_text(repo_root: Path, rel: str) -> str | None:
    full = repo_root / rel
    if not full.exists() or not full.is_file():
        return None
    try:
        return full.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _find_state_literal(text: str, state_literal: str) -> bool:
    """Return True if state_literal appears as a string token in text.

    Match patterns:
      - 'pending_admin_review' or "pending_admin_review" (string literal)
      - PendingAdminReview / PENDING_ADMIN_REVIEW (enum-style — case
        insensitive identifier match)
      - bare token boundary match (defensive — covers free-form usage)
    """
    if not state_literal:
        return False
    # Quoted literal — strongest signal.
    if f"'{state_literal}'" in text or f'"{state_literal}"' in text or f"`{state_literal}`" in text:
        return True
    # Token-boundary match (covers enum reference, e.g. State.pending_admin_review)
    if re.search(rf"\b{re.escape(state_literal)}\b", text):
        return True
    return False


def _audit_task(
    out: Output,
    *,
    repo_root: Path,
    phase_dir: Path,
    capsule_path: Path,
) -> bool:
    """Return True if this capsule had a workflow_id (i.e. participated)."""
    capsule = _load_capsule(capsule_path)
    if capsule is None:
        out.warn(Evidence(
            type="workflow_malformed_capsule",
            message=f"Capsule unreadable: {capsule_path.name}",
            file=str(capsule_path),
        ))
        return False

    wf_id = capsule.get("workflow_id")
    wf_step = capsule.get("workflow_step")
    if not wf_id or wf_step is None:
        return False  # No workflow declared → nothing to audit.

    task_id = (
        capsule.get("task_id")
        or capsule.get("task_id_str")
        or capsule_path.stem.replace(".capsule", "")
    )
    task_id_str = str(task_id)

    # Parse WORKFLOW-SPECS for expected state_after literal.
    spec, err = _load_workflow_spec(phase_dir, str(wf_id))
    if err or spec is None:
        out.warn(Evidence(
            type="workflow_malformed_spec",
            message=(
                f"Task {task_id_str}: cannot parse WORKFLOW-SPECS/{wf_id}.md "
                f"— {err or 'unknown'}. Skipping workflow implementation "
                f"audit for this task."
            ),
            file=f"WORKFLOW-SPECS/{wf_id}.md",
            fix_hint=(
                "Fix the yaml fence in WORKFLOW-SPECS/<wf>.md or re-run "
                "/vg:blueprint to regenerate. Stale phases may need cleanup."
            ),
        ))
        return True

    expected_state = _state_after_for_step(spec, wf_step)
    if not expected_state:
        # Step has no state_after declared — read-only step, nothing to verify.
        return True

    # Resolve modified files from BUILD-LOG/task-NN.md.
    artifacts = _parse_artifacts_from_build_log(phase_dir, task_id_str)
    if not artifacts:
        out.warn(Evidence(
            type="workflow_no_modified_files",
            message=(
                f"Task {task_id_str} (workflow {wf_id} step {wf_step}, "
                f"expects state `{expected_state}`): BUILD-LOG/{task_id_str}.md "
                f"missing or contains no `Files modified` section. Cannot "
                f"verify state-literal implementation."
            ),
            file=f"BUILD-LOG/{task_id_str}.md",
            fix_hint=(
                "Confirm vg-build-task-executor wrote a BUILD-LOG entry with "
                "the `Files modified` section (per SKILL.md step 15)."
            ),
        ))
        return True

    handler_paths = [p for p in artifacts if _looks_like_handler_or_state(p)]
    test_only_paths = [p for p in artifacts if _is_test_only_path(p)]

    # Search prod handler/state files first.
    prod_hit_files: list[str] = []
    for rel in handler_paths:
        if _is_test_only_path(rel):
            continue
        text = _read_text(repo_root, rel)
        if text and _find_state_literal(text, expected_state):
            prod_hit_files.append(rel)

    if prod_hit_files:
        # PASS — heuristic match in prod code.
        return True

    # No prod hit. Check test-only files for the state literal.
    test_hit_files: list[str] = []
    for rel in test_only_paths:
        text = _read_text(repo_root, rel)
        if text and _find_state_literal(text, expected_state):
            test_hit_files.append(rel)

    # Also scan ALL artifacts (including non-handler) in case state lives
    # in an unconventional file (e.g. constants.ts, schema.prisma).
    other_prod_hit_files: list[str] = []
    for rel in artifacts:
        if rel in handler_paths or rel in test_only_paths:
            continue
        text = _read_text(repo_root, rel)
        if text and _find_state_literal(text, expected_state):
            other_prod_hit_files.append(rel)

    if other_prod_hit_files:
        # Found in a prod file we didn't classify as handler/state — PASS.
        return True

    if test_hit_files and not prod_hit_files:
        out.warn(Evidence(
            type="workflow_state_only_in_tests",
            message=(
                f"Task {task_id_str} (workflow {wf_id} step {wf_step}): "
                f"expected state literal `{expected_state}` (from "
                f"WORKFLOW-SPECS/{wf_id}.md state_machine) appears ONLY in "
                f"test files {test_hit_files}, not in any handler/state "
                f"production file. Implementation may be missing the "
                f"actual state transition."
            ),
            file=test_hit_files[0],
            expected=f"state literal `{expected_state}` in handler/state code",
            actual=f"only present in {test_hit_files}",
            fix_hint=(
                "Verify the handler/store/reducer actually writes "
                f"`{expected_state}` (not just the test asserting it). "
                "If the literal is centralized in a constants module, "
                "include that file's path in BUILD-LOG `Files modified`."
            ),
        ))
        return True

    # No hits anywhere → BLOCK.
    out.add(Evidence(
        type="workflow_state_literal_missing",
        message=(
            f"Task {task_id_str} (workflow {wf_id} step {wf_step}): "
            f"expected state literal `{expected_state}` (from "
            f"WORKFLOW-SPECS/{wf_id}.md state_machine) NOT FOUND in any "
            f"modified file. Implementation likely diverges from "
            f"workflow spec — tasks may be writing the wrong state value "
            f"(e.g. `approved` instead of `pending_admin_review`)."
        ),
        file=f"WORKFLOW-SPECS/{wf_id}.md",
        expected=f"state literal `{expected_state}` in modified handler/state files",
        actual=f"not found in {artifacts}",
        fix_hint=(
            f"Check the handler / state store / reducer for task "
            f"{task_id_str} writes `{expected_state}` exactly as declared. "
            f"Re-run /vg:build, or override via "
            f"--skip-workflow-implementation-audit --override-reason=<ticket> "
            f"if the state lives in a file not captured in BUILD-LOG."
        ),
    ))
    return True


def main() -> None:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--phase", help="Phase id (e.g. '7.14')")
    ap.add_argument("--phase-dir", help="Absolute path to phase dir")
    ap.add_argument("--wave-id", help="(Optional) wave number — informational")
    args = ap.parse_args()

    out = Output(validator="workflow-implementation")
    with timer(out):
        if args.phase_dir:
            phase_dir = Path(args.phase_dir)
            if not phase_dir.is_absolute():
                phase_dir = Path.cwd() / phase_dir
            if not phase_dir.exists():
                out.warn(Evidence(
                    type="info",
                    message=f"--phase-dir does not exist: {phase_dir}",
                ))
                emit_and_exit(out)
        elif args.phase:
            phase_dir = find_phase_dir(args.phase)
            if not phase_dir:
                out.warn(Evidence(
                    type="info",
                    message=f"Phase dir not found for {args.phase} — skipping",
                ))
                emit_and_exit(out)
        else:
            ap.error("either --phase or --phase-dir is required")

        # Repo root for resolving artifact paths. Default to env override,
        # else walk parents looking for .git / .vg marker.
        import os as _os
        repo_root_env = _os.environ.get("VG_REPO_ROOT")
        if repo_root_env:
            repo_root = Path(repo_root_env).resolve()
        else:
            repo_root = phase_dir
            for parent in [phase_dir, *phase_dir.parents]:
                if (parent / ".git").exists() or (parent / ".vg").exists():
                    repo_root = parent
                    break

        capsule_dir = phase_dir / ".task-capsules"
        if not capsule_dir.exists():
            out.warn(Evidence(
                type="info",
                message=(
                    f"No .task-capsules dir under {phase_dir}. "
                    f"Either build hasn't run yet, or this phase has no tasks."
                ),
            ))
            emit_and_exit(out)

        capsules = sorted(capsule_dir.glob("task-*.capsule.json"))
        if not capsules:
            out.warn(Evidence(
                type="info",
                message=f"No task capsules found under {capsule_dir}.",
            ))
            emit_and_exit(out)

        workflow_count = 0
        for capsule_path in capsules:
            if _audit_task(
                out,
                repo_root=repo_root,
                phase_dir=phase_dir,
                capsule_path=capsule_path,
            ):
                workflow_count += 1

        if not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message=(
                    f"Workflow implementation audit PASS — {len(capsules)} "
                    f"capsule(s) scanned, {workflow_count} with workflow_id "
                    f"verified against WORKFLOW-SPECS state_machine."
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
