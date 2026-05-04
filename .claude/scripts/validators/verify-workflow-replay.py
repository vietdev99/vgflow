#!/usr/bin/env python3
"""
Validator: verify-workflow-replay.py — R7 Task 5 (G9)

Review-side gate. For every WORKFLOW-SPECS/<WF-NN>.md in the phase, check
that ${PHASE_DIR}/.runs/<WF-NN>.replay.json exists with overall_verdict in
{PASSED, PARTIAL}. Pairs with R7 Task 4 (verify-workflow-implementation.py)
which catches static state-literal absent at build time. This validator is
defense-in-depth at review verdict layer:

Severity matrix:
  - PASS:  every WORKFLOW-SPECS/<WF-NN>.md has a .runs/<WF-NN>.replay.json
           with overall_verdict == "PASSED".
  - WARN:  replay file present but overall_verdict == "PARTIAL" (live MCP
           skipped, mock mode, etc.) — flagged so reviewer notices, but
           does not block when the build-side gate already passed.
  - BLOCK: replay file MISSING for a workflow, OR overall_verdict ==
           "FAILED" (a workflow step failed in live execution OR cross-role
           visibility/authz negative path failed).

Override flag (consumed in review verdict integration md):
  --skip-multi-actor-replay --override-reason "<text>"

Usage:
  verify-workflow-replay.py --phase 7.14
  verify-workflow-replay.py --phase-dir /abs/path/to/phase

Output: vg.validator-output JSON on stdout. rc 0 = PASS or WARN; rc 1 = BLOCK.

Pattern: modeled after verify-tdd-evidence.py + verify-rcrurd-implementation.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

WF_FILE_RE = re.compile(r"^WF-[0-9]{2,4}$")


def _list_workflow_specs(phase_dir: Path) -> list[Path]:
    """Return sorted list of WORKFLOW-SPECS/<WF-NN>.md files (excludes index.md)."""
    wf_dir = phase_dir / "WORKFLOW-SPECS"
    if not wf_dir.is_dir():
        return []
    return sorted(p for p in wf_dir.glob("WF-*.md") if WF_FILE_RE.match(p.stem))


def _index_says_no_workflows(phase_dir: Path) -> bool:
    """Empty index.md (`flows: []`) signals no multi-actor workflows."""
    idx = phase_dir / "WORKFLOW-SPECS" / "index.md"
    if not idx.exists():
        return False
    try:
        return "flows: []" in idx.read_text(encoding="utf-8")
    except OSError:
        return False


def _load_replay(phase_dir: Path, workflow_id: str) -> tuple[dict | None, str | None]:
    """Returns (replay_dict, error_message)."""
    runs_dir = phase_dir / ".runs"
    fp = runs_dir / f"{workflow_id}.replay.json"
    if not fp.exists():
        return None, f"missing {fp.relative_to(phase_dir)}"
    try:
        return json.loads(fp.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as e:
        return None, f"replay json malformed: {e}"
    except OSError as e:  # pragma: no cover - defensive
        return None, f"replay file unreadable: {e}"


def _audit_workflow(out: Output, *, phase_dir: Path, wf_path: Path) -> None:
    workflow_id = wf_path.stem
    replay, err = _load_replay(phase_dir, workflow_id)

    if replay is None:
        out.add(Evidence(
            type="missing_file",
            message=(
                f"Workflow {workflow_id}: review verdict requires runtime "
                f"replay evidence at .runs/{workflow_id}.replay.json — "
                f"{err}. Multi-actor workflow bugs that survive build-side "
                f"static state-literal grep can still ship without this gate."
            ),
            file=str(wf_path),
            expected=f".runs/{workflow_id}.replay.json with overall_verdict",
            actual="file not found",
            fix_hint=(
                "Drive the workflow replay during review verdict (see "
                "commands/vg/_shared/review/verdict/multi-actor-workflow.md). "
                "Override: --skip-multi-actor-replay --override-reason "
                "\"<replay-impossible-in-this-env>\"."
            ),
        ))
        return

    verdict = replay.get("overall_verdict")
    schema_version = replay.get("schema_version")
    if schema_version != "1.0":
        out.warn(Evidence(
            type="schema_violation",
            message=(
                f"Workflow {workflow_id}: replay schema_version "
                f"{schema_version!r} does not match expected '1.0'. "
                f"Audit may miss new fields."
            ),
            file=f".runs/{workflow_id}.replay.json",
        ))

    blocking = replay.get("blocking_failures") or []

    if verdict == "PASSED":
        return  # green path — no evidence appended

    if verdict == "PARTIAL":
        out.warn(Evidence(
            type="info",
            message=(
                f"Workflow {workflow_id}: replay overall_verdict=PARTIAL "
                f"(execution_mode={replay.get('execution_mode')!r}). "
                f"Build-side gate (R7 Task 4) caught the static class; "
                f"live multi-actor verification was skipped or partial. "
                f"{len(replay.get('notes') or [])} note(s) recorded."
            ),
            file=f".runs/{workflow_id}.replay.json",
            fix_hint=(
                "Run review verdict in an env where Playwright MCP can drive "
                "the deployed URL with per-actor credentials, OR explicitly "
                "override with --skip-multi-actor-replay --override-reason."
            ),
        ))
        return

    if verdict == "FAILED":
        details = "; ".join(blocking[:5]) if blocking else "no blocking_failures recorded"
        out.add(Evidence(
            type="semantic_check_failed",
            message=(
                f"Workflow {workflow_id}: replay FAILED — "
                f"multi-actor runtime verification surfaced blocking issues. "
                f"Details: {details}"
            ),
            file=f".runs/{workflow_id}.replay.json",
            expected="overall_verdict=PASSED",
            actual="overall_verdict=FAILED",
            fix_hint=(
                "Inspect the replay JSON: steps[].failure_reason, "
                "cross_role_visibility[].verdict=NOT_VISIBLE, and "
                "authz_negative_paths[].verdict=FAILED entries identify the "
                "exact step + actor combination. Fix the implementation, "
                "redeploy, re-run review."
            ),
        ))
        return

    if verdict == "SKIPPED":
        # Skipped overall (entire workflow opted out for this run) — WARN.
        out.warn(Evidence(
            type="info",
            message=(
                f"Workflow {workflow_id}: replay overall_verdict=SKIPPED. "
                f"Verify override-debt entry exists for this exclusion."
            ),
            file=f".runs/{workflow_id}.replay.json",
        ))
        return

    # Unknown verdict
    out.add(Evidence(
        type="malformed_content",
        message=(
            f"Workflow {workflow_id}: unknown overall_verdict={verdict!r}. "
            f"Expected one of PASSED/FAILED/PARTIAL/SKIPPED."
        ),
        file=f".runs/{workflow_id}.replay.json",
        fix_hint="Regenerate replay evidence with workflow_replay.py.",
    ))


def main() -> None:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--phase", help="Phase id (e.g. '7.14')")
    ap.add_argument("--phase-dir", help="Absolute path to phase dir")
    args = ap.parse_args()

    out = Output(validator="workflow-replay")
    with timer(out):
        if args.phase_dir:
            phase_dir = Path(args.phase_dir)
            if not phase_dir.is_absolute():
                phase_dir = Path.cwd() / phase_dir
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

        if not phase_dir.exists():
            out.warn(Evidence(
                type="info",
                message=f"Phase dir does not exist: {phase_dir} — skipping",
            ))
            emit_and_exit(out)

        wf_specs = _list_workflow_specs(phase_dir)
        if not wf_specs:
            if _index_says_no_workflows(phase_dir):
                out.evidence.append(Evidence(
                    type="info",
                    message=(
                        "WORKFLOW-SPECS/index.md declares flows: [] — "
                        "no multi-actor workflows to replay."
                    ),
                ))
            else:
                out.evidence.append(Evidence(
                    type="info",
                    message=(
                        f"No WORKFLOW-SPECS/WF-*.md files found under "
                        f"{phase_dir} — workflow replay gate skipped."
                    ),
                ))
            emit_and_exit(out)

        for wf_path in wf_specs:
            _audit_workflow(out, phase_dir=phase_dir, wf_path=wf_path)

        if not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message=(
                    f"Workflow replay gate PASS — {len(wf_specs)} workflow(s) "
                    f"verified against .runs/<WF-NN>.replay.json."
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
