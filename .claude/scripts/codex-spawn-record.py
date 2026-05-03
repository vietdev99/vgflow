#!/usr/bin/env python3
"""Preflight and record VGFlow Codex child-process spawn evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BUILD_TASK_EXECUTOR = "vg-build-task-executor"


def _safe(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in name)
    return cleaned.strip("-") or "unknown"


def _sha256(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _json_load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _safe_session_filename(sid: str) -> str:
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")
    return safe or "unknown"


def _active_run(root: Path) -> dict[str, Any] | None:
    session_id = os.environ.get("CLAUDE_HOOK_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
    candidates: list[Path] = []
    if session_id:
        candidates.append(root / ".vg" / "active-runs" / f"{_safe_session_filename(session_id)}.json")
    candidates.append(root / ".vg" / "current-run.json")
    for candidate in candidates:
        data = _json_load(candidate)
        if data and data.get("run_id"):
            return data
    return None


def _run_id(root: Path) -> str | None:
    run = _active_run(root)
    rid = run.get("run_id") if run else None
    return rid if isinstance(rid, str) and rid else None


def _read_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _extract_task_id(prompt: str, fallback: str | None = None) -> str | None:
    if fallback:
        return fallback
    matches = re.findall(r"task_id\s*[=:]\s*(task-[\w\d-]+)", prompt, re.IGNORECASE)
    return matches[-1] if matches else None


def _extract_capsule_path(prompt: str) -> str | None:
    match = re.search(r'task_context_capsule\s+path\s*=\s*"([^"]+)"', prompt, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"capsule_path\s*[=:]\s*([^\s\"'<>]+)", prompt, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _resolve_path(root: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else root / raw


def _spawn_paths(root: Path, run_id: str) -> tuple[Path, Path]:
    base = root / ".vg" / "runs" / run_id
    return base / ".wave-spawn-plan.json", base / ".spawn-count.json"


def _load_wave_plan(root: Path, run_id: str) -> tuple[dict[str, Any] | None, str | None]:
    plan_path, _ = _spawn_paths(root, run_id)
    if not plan_path.is_file():
        return None, f"missing wave plan: {plan_path}"
    plan = _json_load(plan_path)
    if plan is None:
        return None, f"unparseable wave plan: {plan_path}"
    expected = plan.get("expected")
    if not isinstance(expected, list):
        return None, "wave plan missing expected[]"
    return plan, None


def _fresh_count(plan: dict[str, Any]) -> dict[str, Any]:
    expected = list(plan.get("expected") or [])
    return {
        "wave_id": plan.get("wave_id"),
        "expected": expected,
        "spawned": [],
        "remaining": expected,
    }


def _load_or_init_count(count_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    fresh = _fresh_count(plan)
    existing = _json_load(count_path)
    if not existing:
        return fresh
    if existing.get("wave_id") != plan.get("wave_id") or existing.get("expected") != plan.get("expected"):
        return fresh
    return existing


def _preflight_build_task(root: Path, run_id: str, prompt_file: Path, task_id_arg: str | None) -> int:
    prompt = _read_prompt(prompt_file)
    task_id = _extract_task_id(prompt, task_id_arg)
    if not task_id:
        print("codex-spawn preflight blocked: missing task_id for vg-build-task-executor", file=sys.stderr)
        return 2

    plan, error = _load_wave_plan(root, run_id)
    if error or plan is None:
        print(f"codex-spawn preflight blocked: {error}", file=sys.stderr)
        return 2

    capsule_raw = _extract_capsule_path(prompt)
    if not capsule_raw:
        print(f"codex-spawn preflight blocked: missing capsule_path for {task_id}", file=sys.stderr)
        return 2
    capsule = _resolve_path(root, capsule_raw)
    if not capsule.is_file() or capsule.stat().st_size == 0:
        print(f"codex-spawn preflight blocked: capsule missing for {task_id}: {capsule}", file=sys.stderr)
        return 2

    expected = plan.get("expected") or []
    if task_id not in expected:
        print(f"codex-spawn preflight blocked: {task_id} not in expected[] {expected}", file=sys.stderr)
        return 2

    _, count_path = _spawn_paths(root, run_id)
    count = _load_or_init_count(count_path, plan)
    if task_id in count.get("spawned", []):
        print(f"codex-spawn preflight blocked: {task_id} already spawned this wave", file=sys.stderr)
        return 2
    if task_id not in count.get("remaining", []):
        print(
            f"codex-spawn preflight blocked: {task_id} not in remaining[] {count.get('remaining')}",
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    run_id = args.run_id or _run_id(root)
    if not run_id:
        print("codex-spawn preflight blocked: active VG run_id not found", file=sys.stderr)
        return 2
    if args.role == BUILD_TASK_EXECUTOR:
        return _preflight_build_task(root, run_id, Path(args.prompt_file), args.task_id)
    return 0


def _record_build_task_success(
    root: Path,
    run_id: str,
    prompt_file: Path,
    task_id_arg: str | None,
) -> int:
    prompt = _read_prompt(prompt_file)
    task_id = _extract_task_id(prompt, task_id_arg)
    if not task_id:
        print("codex-spawn record blocked: missing task_id for vg-build-task-executor", file=sys.stderr)
        return 2
    plan, error = _load_wave_plan(root, run_id)
    if error or plan is None:
        print(f"codex-spawn record blocked: {error}", file=sys.stderr)
        return 2
    _, count_path = _spawn_paths(root, run_id)
    count = _load_or_init_count(count_path, plan)
    remaining = list(count.get("remaining") or [])
    spawned = list(count.get("spawned") or [])
    if task_id in remaining:
        remaining.remove(task_id)
    if task_id not in spawned:
        spawned.append(task_id)
    count["remaining"] = remaining
    count["spawned"] = spawned
    count_path.parent.mkdir(parents=True, exist_ok=True)
    count_path.write_text(json.dumps(count, indent=2), encoding="utf-8")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    run_id = args.run_id or _run_id(root)
    if not run_id:
        print("codex-spawn record blocked: active VG run_id not found", file=sys.stderr)
        return 2

    prompt_file = Path(args.prompt_file).resolve()
    out_file = Path(args.out_file).resolve()
    spawn_id = args.spawn_id or args.task_id or args.role
    if args.role == BUILD_TASK_EXECUTOR:
        task_rc = _record_build_task_success(root, run_id, prompt_file, args.task_id)
        if task_rc != 0:
            return task_rc
        prompt_text = _read_prompt(prompt_file)
        spawn_id = _extract_task_id(prompt_text, args.task_id) or spawn_id

    record = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": run_id,
        "role": args.role,
        "spawn_id": spawn_id,
        "tier": args.tier,
        "model": args.model or "",
        "sandbox": args.sandbox,
        "wave_id": args.wave_id,
        "task_id": args.task_id,
        "prompt_file": str(prompt_file),
        "prompt_sha256": _sha256(prompt_file),
        "out_file": str(out_file),
        "out_sha256": _sha256(out_file),
        "stdout_log": str(Path(args.stdout_log).resolve()) if args.stdout_log else "",
        "stderr_log": str(Path(args.stderr_log).resolve()) if args.stderr_log else "",
        "exit_code": int(args.exit_code),
    }

    base = root / ".vg" / "runs" / run_id
    spawn_dir = base / "codex-spawns"
    spawn_dir.mkdir(parents=True, exist_ok=True)
    record_path = spawn_dir / f"{_safe(str(record['role']))}--{_safe(str(record['spawn_id']))}.json"
    record["record_path"] = str(record_path)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    with (base / ".codex-spawn-manifest.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--spawn-id")
    parser.add_argument("--task-id")
    parser.add_argument("--wave-id")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    preflight = sub.add_parser("preflight")
    _add_common(preflight)
    preflight.set_defaults(func=cmd_preflight)

    record = sub.add_parser("record")
    _add_common(record)
    record.add_argument("--out-file", required=True)
    record.add_argument("--stdout-log", required=True)
    record.add_argument("--stderr-log", required=True)
    record.add_argument("--exit-code", required=True)
    record.add_argument("--tier", required=True)
    record.add_argument("--model", default="")
    record.add_argument("--sandbox", required=True)
    record.set_defaults(func=cmd_record)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
