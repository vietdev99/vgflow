#!/usr/bin/env python3
"""Verify that build executor prompts received per-task context capsules."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402


def _task_num_from_meta(meta_path: Path) -> int | None:
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    raw = meta.get("task_id") or meta.get("task_num")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _load_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, "root is not an object"
    return data, None


def _prompt_has_capsule(prompt_text: str, task_num: int) -> bool:
    if "<task_context_capsule" not in prompt_text:
        return False
    if "</task_context_capsule>" not in prompt_text:
        return False
    if '"capsule_version"' not in prompt_text:
        return False
    return bool(re.search(rf'"task_num"\s*:\s*{task_num}\b', prompt_text))


def _check_capsule_shape(capsule: dict, task_num: int) -> list[str]:
    errors: list[str] = []
    if capsule.get("capsule_version") not in {"1", "2"}:
        errors.append("capsule_version must be '1' or '2'")
    if capsule.get("task_num") != task_num:
        errors.append(f"task_num mismatch: expected {task_num}, got {capsule.get('task_num')!r}")
    for key in ("source_artifacts", "required_context", "execution_contract"):
        if not isinstance(capsule.get(key), dict):
            errors.append(f"{key} must be an object")
    for key in ("goals", "endpoints", "file_paths", "anti_lazy_read_rules"):
        if not isinstance(capsule.get(key), list):
            errors.append(f"{key} must be a list")

    required = capsule.get("required_context") if isinstance(capsule.get("required_context"), dict) else {}
    if required.get("task_context") != "present":
        errors.append("task_context must be present")

    contract = capsule.get("execution_contract")
    if isinstance(contract, dict):
        if contract.get("must_follow_api_contract") and required.get("contract_context") != "present":
            errors.append("API contract is required but contract_context is not present")
        if contract.get("requires_persistence_check") and required.get("goals_context") != "present":
            errors.append("mutation task requires goals_context for persistence checks")
        if contract.get("must_follow_crud_surface") and required.get("crud_surface_context") != "present":
            errors.append("CRUD surface is required but crud_surface_context is not present")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--phase-dir", help="Override phase directory")
    args = parser.parse_args()

    out = Output(validator="task-context-capsule")
    with timer(out):
        phase_dir = Path(args.phase_dir) if args.phase_dir else find_phase_dir(args.phase)
        if not phase_dir:
            out.warn(Evidence(type="info", message=f"Phase dir not found for {args.phase}; skipping"))
            emit_and_exit(out)

        meta_files = sorted(phase_dir.glob(".build/wave-*/executor-prompts/*.meta.json"))
        if not meta_files:
            out.warn(Evidence(
                type="info",
                message=(
                    "No executor prompt meta sidecars found; build has not spawned "
                    "tasks yet or used an older workflow."
                ),
            ))
            emit_and_exit(out)

        for meta_path in meta_files:
            task_num = _task_num_from_meta(meta_path)
            if task_num is None:
                out.add(Evidence(
                    type="malformed_meta",
                    message="meta.json missing numeric task_id/task_num",
                    file=str(meta_path),
                ))
                continue

            prompt_path = meta_path.parent / meta_path.name.replace(".meta.json", ".prompt.md")
            if not prompt_path.exists():
                out.add(Evidence(
                    type="missing_prompt",
                    message="executor full prompt missing; cannot verify capsule injection",
                    file=str(prompt_path),
                ))
                continue

            capsule_path = phase_dir / ".task-context-capsules" / f"task-{task_num}.json"
            if not capsule_path.exists():
                out.add(Evidence(
                    type="capsule_missing",
                    message=f"task {task_num} has executor prompt but no context capsule",
                    file=str(capsule_path),
                    fix_hint="Run build with pre-executor-check.py --capsule-out before spawning.",
                ))
                continue

            capsule, error = _load_json(capsule_path)
            if error or capsule is None:
                out.add(Evidence(
                    type="capsule_malformed",
                    message=f"task {task_num} capsule JSON invalid: {error}",
                    file=str(capsule_path),
                ))
                continue

            for err in _check_capsule_shape(capsule, task_num):
                out.add(Evidence(
                    type="capsule_contract_violation",
                    message=f"task {task_num}: {err}",
                    file=str(capsule_path),
                ))

            prompt_text = prompt_path.read_text(encoding="utf-8", errors="replace")
            if not _prompt_has_capsule(prompt_text, task_num):
                out.add(Evidence(
                    type="capsule_not_in_prompt",
                    message=(
                        f"task {task_num} prompt does not contain the literal "
                        "task_context_capsule block"
                    ),
                    file=str(prompt_path),
                    fix_hint="Inject <task_context_capsule> before vg_executor_rules.",
                ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
