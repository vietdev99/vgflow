#!/usr/bin/env python3
"""
Validator: verify-task-fidelity.py — Phase 16 D-06

Post-spawn 3-way audit of executor prompt fidelity. Closes the
PARAPHRASE leg of the "AI lazy-read blueprint" failure mode (Q1
follow-up). For each (wave × task) tuple under
${PHASE_DIR}/.build/wave-*/executor-prompts/:

  Compare 3 sources:
    1. PLAN.md task block re-extracted now (current source of truth)
    2. .meta.json sidecar (snapshot at spawn time, P16 D-01)
    3. .md prompt body (what executor actually received)

  Detect:
    A. PLAN drift — PLAN modified between spawn + audit (rare; should
       not happen mid-build but graceful WARN if it does)
    B. Body shortfall — prompt body line_count < meta.line_count × 0.9
       → 0-10% PASS, 10-30% WARN, >30% BLOCK (orchestrator paraphrase /
       truncate detection)

Usage:  verify-task-fidelity.py --phase 7.14.3
        verify-task-fidelity.py --phase 7.14.3 --prompts-dir <override>
Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

SHORTFALL_WARN_THRESHOLD = 0.10  # 10%
SHORTFALL_BLOCK_THRESHOLD = 0.30  # 30%


def _load_hasher():
    repo_root = Path(__file__).resolve().parents[2]
    hasher_path = repo_root / "scripts" / "lib" / "task_hasher.py"
    spec = importlib.util.spec_from_file_location("task_hasher", hasher_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_pec():
    pec_path = Path(__file__).resolve().parents[1] / "pre-executor-check.py"
    spec = importlib.util.spec_from_file_location("pec_for_fidelity", pec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _audit_pair(meta_path: Path, prompt_path: Path, phase_dir: Path,
                hasher, pec) -> dict:
    """Return dict with 3-way comparison facts for one (wave, task) pair."""
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"meta.json unreadable: {e}", "task_id": meta_path.stem.split(".")[0]}

    try:
        prompt_text = prompt_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"error": f"prompt.md unreadable: {e}", "task_id": meta.get("task_id_str")}

    task_id = meta.get("task_id")
    if task_id is None:
        return {"error": "meta.json missing task_id", "task_id": "?"}

    # Re-extract task block from PLAN.md NOW
    try:
        plan_v2 = pec.extract_task_section_v2(phase_dir, task_id)
        plan_body = plan_v2["body"]
    except Exception as e:
        plan_body = ""
        plan_extract_error = str(e)
    else:
        plan_extract_error = None

    plan_sha, plan_lines, _ = hasher.task_block_sha256(plan_body) if plan_body else ("", 0, 0)

    expected_sha = meta.get("source_block_sha256", "")
    expected_lines = int(meta.get("source_block_line_count", 0))

    # Body line count from persisted prompt (raw, no normalize — caller wants
    # to see what executor SAW, not what was canonical)
    prompt_lines = prompt_text.count("\n") + (1 if prompt_text and not prompt_text.endswith("\n") else 0)

    # Drift: PLAN now differs from what was hashed at spawn
    plan_drift = bool(expected_sha) and bool(plan_sha) and plan_sha != expected_sha

    # Shortfall: prompt body shorter than expected (paraphrase or truncate)
    shortfall_pct = 0.0
    if expected_lines > 0:
        shortfall = max(0, expected_lines - prompt_lines)
        shortfall_pct = shortfall / expected_lines

    return {
        "task_id_str": meta.get("task_id_str"),
        "task_id": task_id,
        "wave": meta.get("wave"),
        "expected_sha": expected_sha,
        "expected_lines": expected_lines,
        "plan_now_sha": plan_sha,
        "plan_now_lines": plan_lines,
        "prompt_lines": prompt_lines,
        "shortfall_pct": shortfall_pct,
        "plan_drift": plan_drift,
        "plan_extract_error": plan_extract_error,
        "meta_path": str(meta_path),
        "prompt_path": str(prompt_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--prompts-dir",
                    help="Override default scan path (.build/wave-*/executor-prompts)")
    args = ap.parse_args()

    out = Output(validator="task-fidelity")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            out.warn(Evidence(type="info",
                              message=f"Phase dir not found for {args.phase} — skipping"))
            emit_and_exit(out)

        # Discover meta.json files
        if args.prompts_dir:
            base = Path(args.prompts_dir)
            if not base.is_absolute():
                base = phase_dir / base
            meta_files = sorted(base.glob("*.meta.json"))
        else:
            meta_files = sorted(phase_dir.glob(".build/wave-*/executor-prompts/*.meta.json"))

        if not meta_files:
            # Soft-warn rather than BLOCK (older builds don't write sidecar)
            out.warn(Evidence(
                type="info",
                message=(
                    f"No .meta.json sidecars under {phase_dir}/.build/wave-*/"
                    f"executor-prompts/. Either build hasn't run yet, or older "
                    f"build.md without P16 D-01 (T-1.2) sidecar persist."
                ),
                fix_hint=(
                    "Re-run /vg:build {phase} after Phase 16 ship to populate "
                    "sidecars. Or set --skip-task-fidelity-audit override."
                ),
            ))
            emit_and_exit(out)

        try:
            hasher = _load_hasher()
            pec = _load_pec()
        except Exception as e:
            out.add(Evidence(type="config-error",
                             message=f"failed to load helpers: {e}"))
            emit_and_exit(out)

        for meta_path in meta_files:
            # Phase 16 hot-fix (v2.11.1): build.md step 8c now writes the
            # task body to *.body.md (separate from the *.uimap.md UI-MAP
            # wrapper). Read body.md as the canonical "what the executor
            # received" artifact. Backward compat: legacy *.md fallback for
            # older builds before the split-persist refactor.
            prompt_path = meta_path.parent / meta_path.name.replace(".meta.json", ".body.md")
            if not prompt_path.exists():
                legacy_path = meta_path.parent / meta_path.name.replace(".meta.json", ".md")
                if legacy_path.exists():
                    prompt_path = legacy_path
                else:
                    out.add(Evidence(
                        type="missing_file",
                        message=f"meta.json present but prompt body missing: {prompt_path.name}",
                        file=str(meta_path),
                    ))
                    continue

            audit = _audit_pair(meta_path, prompt_path, phase_dir, hasher, pec)
            if "error" in audit:
                out.add(Evidence(type="malformed_content",
                                 message=audit["error"], file=str(meta_path)))
                continue

            tid = audit["task_id_str"] or audit["task_id"]
            wave = audit.get("wave", "?")

            # PLAN drift → WARN (PLAN should not change between spawn + audit
            # but if user manually edited it, surface so they know)
            if audit["plan_drift"]:
                out.warn(Evidence(
                    type="content_drift",
                    message=(
                        f"Task {tid} ({wave}): PLAN.md task block changed since "
                        f"spawn (expected sha {audit['expected_sha'][:16]}…, "
                        f"now {audit['plan_now_sha'][:16]}…)."
                    ),
                    file=audit["prompt_path"],
                    fix_hint=(
                        "Either accept the drift (PLAN edit was intentional and "
                        "newer is correct) or revert PLAN.md to match the "
                        "spawn-time snapshot. Re-running build will re-snapshot."
                    ),
                ))

            # Shortfall classification
            sp = audit["shortfall_pct"]
            if sp > SHORTFALL_BLOCK_THRESHOLD:
                out.add(Evidence(
                    type="content_shortfall",
                    message=(
                        f"Task {tid} ({wave}): prompt body {audit['prompt_lines']} "
                        f"lines vs expected {audit['expected_lines']} "
                        f"({sp:.0%} shortfall > {SHORTFALL_BLOCK_THRESHOLD:.0%} "
                        f"threshold). Orchestrator likely paraphrased / truncated."
                    ),
                    file=audit["prompt_path"],
                    expected=audit["expected_lines"],
                    actual=audit["prompt_lines"],
                    fix_hint=(
                        "Inspect prompt body vs PLAN task block. If paraphrase: "
                        "fix prompt template to pass body verbatim. Override: "
                        "--skip-task-fidelity-audit (logs override-debt)."
                    ),
                ))
            elif sp > SHORTFALL_WARN_THRESHOLD:
                out.warn(Evidence(
                    type="content_shortfall",
                    message=(
                        f"Task {tid} ({wave}): prompt body {audit['prompt_lines']} "
                        f"lines vs expected {audit['expected_lines']} "
                        f"({sp:.0%} shortfall, between WARN/BLOCK threshold)."
                    ),
                    file=audit["prompt_path"],
                ))

        if not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message=f"Task fidelity PASS — {len(meta_files)} (wave, task) pair(s) audited",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
