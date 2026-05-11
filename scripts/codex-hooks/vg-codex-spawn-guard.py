#!/usr/bin/env python3
"""Codex Bash guard for VGFlow required spawn evidence."""
from __future__ import annotations

import json
import re
import sys
import hashlib
from pathlib import Path
from typing import Any

from vg_codex_hook_lib import repo_root, safe_session_filename

REQUIRED_STEP_ROLES = {
    ("build", "9_post_execution"): ("vg-build-post-executor",),
    ("test", "5c_goal_verification"): ("vg-test-goal-verifier",),
    ("test", "5d_codegen"): ("vg-test-codegen",),
    ("accept", "4_build_uat_checklist"): ("vg-accept-uat-builder",),
    ("accept", "7_post_accept_actions"): ("vg-accept-cleanup",),
}

PROTECTED_SPAWN_PATH_RE = re.compile(
    r"\.vg/runs/[^/\s]+/(?:\.codex-spawn-manifest\.jsonl|\.spawn-count\.json|codex-spawns/[^\s]+)"
)
PROTECTED_SPAWN_PATH_PATTERN = (
    r"\.vg/runs/[^/\s]+/(?:\.codex-spawn-manifest\.jsonl|\.spawn-count\.json|codex-spawns/[^\s]+)"
)
WRITE_TO_PROTECTED_SPAWN_PATH_RE = re.compile(
    rf"""
    (?:
      (?:>|>>|>\|)\s*['"]?{PROTECTED_SPAWN_PATH_PATTERN}
      |
      \btee\b(?:\s+-a)?\s+['"]?{PROTECTED_SPAWN_PATH_PATTERN}
      |
      \b(?:touch|rm|mv|cp|install|truncate)\b[^\n;&|]*{PROTECTED_SPAWN_PATH_PATTERN}
      |
      \bsed\s+-i\b[^\n;&|]*{PROTECTED_SPAWN_PATH_PATTERN}
      |
      \bperl\s+-pi\b[^\n;&|]*{PROTECTED_SPAWN_PATH_PATTERN}
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
SCRIPT_WRITE_TO_PROTECTED_SPAWN_PATH_RE = re.compile(
    r"""
    \b(?:python3?|node|ruby|perl)\b
    .*
    (?:write_text|write_bytes|json\.dump|pickle\.dump|open\s*\([^)]*,\s*['"][wax+])
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def _read_input() -> dict[str, Any]:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def _tool_command(hook_input: dict[str, Any]) -> str:
    tool_input = hook_input.get("tool_input")
    if isinstance(tool_input, dict):
        return str(tool_input.get("command") or "")
    return ""


def _looks_like_spawn_evidence_write(command: str) -> bool:
    if not PROTECTED_SPAWN_PATH_RE.search(command):
        return False
    if "codex-spawn-record.py" in command or "codex-spawn.sh" in command:
        return False
    if WRITE_TO_PROTECTED_SPAWN_PATH_RE.search(command):
        return True
    if SCRIPT_WRITE_TO_PROTECTED_SPAWN_PATH_RE.search(command):
        return True
    return False


def _active_run(root: Path, session_id: str | None) -> dict[str, Any] | None:
    candidates: list[Path] = []
    if session_id:
        candidates.append(root / ".vg" / "active-runs" / f"{safe_session_filename(session_id)}.json")
    candidates.append(root / ".vg" / "current-run.json")
    for candidate in candidates:
        try:
            if candidate.is_file():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if data.get("run_id"):
                    return data
        except Exception:
            continue
    return None


def _block(root: Path, run_id: str, gate_id: str, reason: str) -> int:
    block_dir = root / ".vg" / "blocks" / (run_id or "unknown")
    block_dir.mkdir(parents=True, exist_ok=True)
    block_file = block_dir / f"{gate_id}.md"
    block_file.write_text(
        f"""# Block diagnostic - {gate_id}

## Cause
{reason}

## Required fix
Run the required Codex child process via `.claude/commands/vg/_shared/lib/codex-spawn.sh`
with the correct `--spawn-role`, then retry the blocked marker/wave command.

Codex hooks cannot intercept native subagent calls directly; VGFlow enforces
spawn parity through codex-spawn evidence under `.vg/runs/<run_id>/codex-spawns/`.
""",
        encoding="utf-8",
    )
    sys.stderr.write(f"{gate_id}: {reason}\n-> Read {block_file.relative_to(root)} for fix\n")
    return 2


def _manifest_records(root: Path, run_id: str) -> list[dict[str, Any]]:
    manifest = root / ".vg" / "runs" / run_id / ".codex-spawn-manifest.jsonl"
    records: list[dict[str, Any]] = []
    try:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if isinstance(record, dict):
                records.append(record)
    except Exception:
        return []
    return records


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _has_role(root: Path, run_id: str, role: str) -> bool:
    for record in _manifest_records(root, run_id):
        if record.get("role") != role or int(record.get("exit_code") or 0) != 0:
            continue
        out_file = record.get("out_file")
        out_sha = record.get("out_sha256")
        if out_file and out_sha and Path(str(out_file)).is_file():
            if _sha256(Path(str(out_file))) != out_sha:
                continue
            return True
    return False


def _extract_mark_step(command: str) -> tuple[str, str] | None:
    match = re.search(r"vg-orchestrator(?:/__main__\.py)?\s+mark-step\s+([A-Za-z0-9_-]+)\s+([A-Za-z0-9_-]+)", command)
    if match:
        return match.group(1), match.group(2)
    match = re.search(r"mark_step\s+(?:[\"']?[^\"'\s]+[\"']?\s+)?[\"']?([A-Za-z0-9_-]+)[\"']?", command)
    if match:
        return "", match.group(1)
    match = re.search(r"\.step-markers/(?:[A-Za-z0-9_-]+/)?([A-Za-z0-9_-]+)\.done", command)
    if match:
        return "", match.group(1)
    return None


def _extract_wave_complete(command: str) -> str | None:
    match = re.search(r"vg-orchestrator(?:/__main__\.py)?\s+wave-complete\s+([0-9]+)", command)
    return match.group(1) if match else None


def _validate_wave_spawn_count(root: Path, run_id: str, wave: str) -> tuple[bool, str]:
    base = root / ".vg" / "runs" / run_id
    plan_path = base / ".wave-spawn-plan.json"
    count_path = base / ".spawn-count.json"
    if not plan_path.is_file():
        return True, "no wave plan; nothing to enforce"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"wave plan unparseable before wave-complete: {exc}"
    expected = plan.get("expected") or []
    if not expected:
        return True, "empty expected[]; nothing to enforce"
    if not count_path.is_file():
        return False, f"Codex spawn-count missing before wave-complete {wave}; expected {expected}"
    try:
        count = json.loads(count_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"Codex spawn-count unparseable before wave-complete: {exc}"
    if str(count.get("wave_id")) != str(plan.get("wave_id")):
        return False, f"Codex spawn-count wave_id={count.get('wave_id')} does not match plan wave_id={plan.get('wave_id')}"
    remaining = count.get("remaining") or []
    spawned = count.get("spawned") or []
    if remaining:
        return False, f"Codex spawn shortfall before wave-complete {wave}; spawned={spawned}, remaining={remaining}"
    return True, "ok"


def main() -> int:
    hook_input = _read_input()
    if hook_input.get("tool_name") != "Bash":
        return 0
    command = _tool_command(hook_input)
    if not command:
        return 0

    if _looks_like_spawn_evidence_write(command):
        root = repo_root(hook_input)
        active = _active_run(root, str(hook_input.get("session_id") or ""))
        run_id = str((active or {}).get("run_id") or "unknown")
        return _block(
            root,
            run_id,
            "PreToolUse-Codex-spawn-forgery",
            "direct Bash write to Codex spawn evidence path is forbidden",
        )

    root = repo_root(hook_input)
    active = _active_run(root, str(hook_input.get("session_id") or ""))
    if not active:
        return 0
    run_id = str(active.get("run_id") or "unknown")
    active_command = str(active.get("command") or "")
    active_name = active_command.split(":", 1)[1] if active_command.startswith("vg:") else ""

    wave = _extract_wave_complete(command)
    if wave and active_name == "build":
        ok, reason = _validate_wave_spawn_count(root, run_id, wave)
        if not ok:
            return _block(root, run_id, "PreToolUse-Codex-spawn-wave-shortfall", reason)
        return 0

    mark = _extract_mark_step(command)
    if not mark:
        return 0
    namespace, step = mark
    namespace = namespace or active_name
    roles = REQUIRED_STEP_ROLES.get((namespace, step))
    if not roles:
        return 0
    missing = [role for role in roles if not _has_role(root, run_id, role)]
    if missing:
        return _block(
            root,
            run_id,
            "PreToolUse-Codex-spawn-required",
            f"missing Codex spawn evidence for {namespace}.{step}: {', '.join(missing)}",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
