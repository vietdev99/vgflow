#!/usr/bin/env python3
"""
vg-agent-spawn-guard.py — PreToolUse hook for Agent (Task) tool calls.

Programmatic enforcement of the v2.26.0 "no gsd-* subagent types in VG
workflow" rule. Until v2.26.0 the rule was prose only; AI dispatchers
sometimes still picked `gsd-executor` because it ships globally at
~/.claude/agents/gsd-executor.md and Claude Code's agent picker scored
it higher than `general-purpose` for plan-execution prompts.

This hook closes the gap by inspecting Agent tool calls BEFORE they
fire and blocking the spawn when:

  1. An active VG run is registered in .vg/current-run.json
     (so we don't break GSD users who spawn gsd-* legitimately
     outside any VG context), AND
  2. tool_input.subagent_type starts with "gsd-" but is NOT
     "gsd-debugger" (which VG legitimately uses in build.md step 12
     for debugging dispatch — already documented allow-listed).

When both conditions match, return PreToolUse JSON with
`permissionDecision: deny` + a clear reason that tells Claude how to
re-spawn correctly. The AI receives the reason in the next turn and
typically adapts (Anthropic API guarantees the reason field is
delivered to the model on `deny`).

Hook contract (Claude Code PreToolUse):
  Stdin JSON:
    {
      "tool_name": "Agent",
      "tool_input": {
        "subagent_type": "...",
        "description": "...",
        "prompt": "..."
      },
      "session_id": "...",
      ...
    }
  Stdout JSON for deny:
    {
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "<message Claude sees>"
      }
    }
  Stdout JSON for allow (or empty / exit 0): proceeds normally.

Exit code:
  - 0 on allow (or unparseable input — fall-through to allow on hook bug,
    never block user's workflow on guard error).
  - 2 on deny — also writes JSON to stdout AND mirrors reason to stderr
    so both Claude Code's permissionDecision channel AND bash-style hook
    pipelines (which inspect stderr/exit-code) see the block. Belt and
    suspenders for cross-version compatibility.

R2 build pilot (v2.41+): adds wave-spawn-plan enforcement for
`vg-build-task-executor` subagent — denies when task_id missing or not
in the current wave's remaining[] list. Reads/writes
.vg/runs/<run_id>/.wave-spawn-plan.json + .spawn-count.json.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR")
                 or os.environ.get("VG_REPO_ROOT")
                 or os.getcwd()).resolve()
CURRENT_RUN = REPO_ROOT / ".vg" / "current-run.json"
ACTIVE_RUNS_DIR = REPO_ROOT / ".vg" / "active-runs"  # v2.28.0 per-session

# Allow-list: gsd-* subagents legitimately used by VG. Currently only
# gsd-debugger (referenced in commands/vg/build.md step 12). Extend if
# more legitimate uses appear; defaults strict.
ALLOWED_GSD_SUBAGENTS = {"gsd-debugger"}

# R2 build pilot — only this subagent type is subject to wave-plan
# spawn-count enforcement. Others fall through unchanged.
BUILD_TASK_EXECUTOR = "vg-build-task-executor"


def allow() -> int:
    # Empty stdout = neutral pass-through (Claude Code proceeds normally).
    return 0


def deny(reason: str) -> int:
    # Dual-channel deny:
    #   - JSON on stdout for Claude Code's PreToolUse contract (v2.27.0+
    #     consumers expect permissionDecision=deny + reason here).
    #   - Mirror to stderr + rc=2 so harness tests and bash-style hook
    #     pipelines (which inspect stderr/exit-code) see the same block.
    # Both channels carry the same reason — no double-blocking, just
    # belt-and-suspenders compatibility across Claude Code versions.
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(payload))
    sys.stderr.write(reason + "\n")
    return 2


def _spawn_count_paths(run_id: str) -> tuple[Path, Path]:
    base = REPO_ROOT / ".vg" / "runs" / run_id
    return base / ".wave-spawn-plan.json", base / ".spawn-count.json"


def _extract_task_id(prompt: str) -> str | None:
    """Parse 'task_id=task-NN' or 'task_id: task-NN' from subagent prompt.

    Accepts case-insensitive key, optional whitespace around the
    delimiter, and dash/word characters in the suffix. When the prompt
    contains multiple `task_id=...` lines, the LAST occurrence wins —
    matches "explicit override after default" semantics that callers
    tend to use (and matches the harness test fixture).
    """
    matches = re.findall(r"task_id\s*[=:]\s*(task-[\w\d-]+)", prompt, re.IGNORECASE)
    return matches[-1] if matches else None


def _enforce_spawn_count(hook_input: dict, run_id: str) -> int | None:
    """R2 build pilot — assert spawned task_id matches wave-spawn-plan.

    Returns:
      int  — deny rc if spawn shortfall / overshoot / unknown task_id.
      None — fall-through (caller proceeds with normal allow()).

    Pass-through cases (return None):
      - subagent_type is not vg-build-task-executor (only this agent
        runs against the wave plan).
      - No .wave-spawn-plan.json (R5 hasn't produced one yet).
      - Wave plan unparseable / missing 'expected' list.

    Persists .spawn-count.json on every successful spawn so the next
    Pre-tool fire can see remaining[] shrink. Stop hook (R6) reads the
    same file to assert spawned == expected at wave end.
    """
    tool_input = hook_input.get("tool_input") or {}
    subagent = tool_input.get("subagent_type", "")
    if subagent != BUILD_TASK_EXECUTOR:
        return None

    plan_path, count_path = _spawn_count_paths(run_id)
    if not plan_path.exists():
        return None  # no wave plan → R5 not run yet, no enforcement

    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected = plan.get("expected") or []
    if not isinstance(expected, list):
        return None
    plan_wave_id = plan.get("wave_id")

    prompt = tool_input.get("prompt", "") or ""
    task_id = _extract_task_id(prompt)
    if not task_id:
        return deny(
            "\033[38;5;208mvg-build-task-executor spawn missing task_id in prompt; \033[0m"
            "spawn-guard cannot verify against wave plan.\n"
            "Add 'task_id=task-NN' to the subagent prompt so the guard "
            "can match it against .wave-spawn-plan.json."
        )

    # Load existing count or initialize from plan.
    # R2 round-2 (E1 critical-1) — when waves-overview overwrites
    # `.wave-spawn-plan.json` for a NEW wave but the prior wave's
    # `.spawn-count.json` is still on disk with `remaining=[]`, the next
    # spawn would be denied against a stale empty queue. Detect wave_id
    # mismatch (or shape mismatch on `expected`) and rebuild the count
    # state from the new plan instead of silently inheriting the previous
    # wave's exhausted queue.
    fresh_count = {
        "wave_id": plan_wave_id,
        "expected": expected,
        "spawned": [],
        "remaining": list(expected),
    }
    if count_path.exists():
        try:
            count = json.loads(count_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            count = fresh_count
        else:
            # Wave rolled forward — drop stale spawned[]/remaining[].
            if (count.get("wave_id") != plan_wave_id
                    or count.get("expected") != expected):
                count = fresh_count
    else:
        count = fresh_count

    remaining = count.get("remaining") or []
    spawned = count.get("spawned") or []
    if task_id not in remaining:
        already = task_id in spawned
        msg = (
            f"⛔ vg-agent-spawn-guard: task_id='{task_id}' "
            f"{'already spawned this wave' if already else 'not in remaining'}.\n"
            f"Wave {count.get('wave_id')} expected: {count.get('expected')}\n"
            f"Already spawned: {spawned}\n"
            f"Remaining: {remaining}\n\n"
            f"Either correct the task_id, or update wave-spawn-plan.json "
            f"with override-reason."
        )
        return deny(msg)

    # Move task_id from remaining → spawned, persist atomically-ish.
    remaining.remove(task_id)
    spawned.append(task_id)
    count["remaining"] = remaining
    count["spawned"] = spawned
    try:
        count_path.parent.mkdir(parents=True, exist_ok=True)
        count_path.write_text(json.dumps(count, indent=2), encoding="utf-8")
    except OSError:
        # Persistence failure shouldn't block the spawn — log to stderr
        # so users notice, but allow the spawn to proceed.
        sys.stderr.write(
            f"\033[33mvg-agent-spawn-guard: failed to persist spawn-count for \033[0m"
            f"run {run_id}; continuing (non-fatal).\n"
        )
    return None  # allow


def _safe_session_filename(sid: str) -> str:
    if not sid:
        return "unknown"
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")
    return safe or "unknown"


def in_active_vg_run(hook_session: str | None = None) -> tuple[bool, str | None]:
    """Returns (active, command) where `active` means THIS session has a
    running VG run.

    v2.28.0: scope by per-session active-run file. Two windows on same
    project, only one running /vg:*: only THAT session's Agent spawns
    are guarded. Other session's general-purpose / mcp Agent calls are
    unaffected. Falls back to legacy .vg/current-run.json snapshot for
    pre-v2.28.0 installs (or when session_id missing).
    """
    # v2.28.0 per-session preferred
    if hook_session:
        per_session = ACTIVE_RUNS_DIR / f"{_safe_session_filename(hook_session)}.json"
        if per_session.exists():
            try:
                data = json.loads(per_session.read_text(encoding="utf-8"))
                cmd = data.get("command", "")
                return bool(cmd and cmd.startswith("vg:")), cmd or None
            except (OSError, json.JSONDecodeError):
                pass

    if not CURRENT_RUN.exists():
        return False, None
    try:
        data = json.loads(CURRENT_RUN.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, None
    # Only honor legacy snapshot if it belongs to THIS session (or has no
    # session_id field — pre-v2.24 install).
    legacy_sid = data.get("session_id")
    if hook_session and legacy_sid and legacy_sid != hook_session:
        return False, None
    cmd = data.get("command", "")
    return bool(cmd and cmd.startswith("vg:")), cmd or None


def _resolve_run_id(hook_session: str | None) -> str | None:
    """Return the active run_id for this session, or None if none."""
    if hook_session:
        per_session = ACTIVE_RUNS_DIR / f"{_safe_session_filename(hook_session)}.json"
        if per_session.exists():
            try:
                data = json.loads(per_session.read_text(encoding="utf-8"))
                rid = data.get("run_id")
                if isinstance(rid, str) and rid:
                    return rid
            except (OSError, json.JSONDecodeError):
                pass
    if CURRENT_RUN.exists():
        try:
            data = json.loads(CURRENT_RUN.read_text(encoding="utf-8"))
            rid = data.get("run_id")
            if isinstance(rid, str) and rid:
                return rid
        except (OSError, json.JSONDecodeError):
            pass
    return None


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return allow()
        hook_input = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return allow()

    if hook_input.get("tool_name") != "Agent":
        return allow()

    hook_session = hook_input.get("session_id") or None
    subagent_type = (hook_input.get("tool_input") or {}).get("subagent_type", "")
    if not isinstance(subagent_type, str):
        return allow()

    # ── Existing gsd-* allow-list enforcement (preserved) ───────────────
    # Only enforce for gsd-* subagent types in this branch; others fall
    # through to the spawn-count check below.
    if subagent_type.startswith("gsd-") and subagent_type not in ALLOWED_GSD_SUBAGENTS:
        # Only block when an active VG run is in progress. Outside VG
        # context (e.g., user running /gsd-execute-phase directly), let
        # the spawn proceed — VG isn't authoritative there.
        is_active, vg_command = in_active_vg_run(hook_session=hook_session)
        if is_active:
            reason = (
                f"⛔ VG workflow guard: subagent_type='{subagent_type}' is "
                f"forbidden during active VG run ({vg_command}).\n\n"
                f"VG explicitly forbids GSD executors during /vg:* commands "
                f"because their rule sets diverge:\n"
                f"  - VG forbids --no-verify; GSD allows it in parallel mode\n"
                f"  - VG requires `Per CONTEXT.md D-XX` body citation; GSD doesn't\n"
                f"  - VG L1-L6 design fidelity gates require evidence; GSD has none\n"
                f"  - VG task context capsule with vision-decomposition; GSD doesn't load it\n\n"
                f"Re-spawn with subagent_type='general-purpose'. The "
                f"<vg_executor_rules> block is already in your prompt and is "
                f"authoritative — load it via general-purpose instead.\n\n"
                f"(Rule sourced from commands/vg/build.md step 7 + hardened "
                f"programmatically in vg-agent-spawn-guard.py since v2.27.0.)"
            )
            return deny(reason)

    # ── R2 build pilot — wave-plan spawn-count enforcement ──────────────
    # Only fires for vg-build-task-executor when an active VG run has a
    # .wave-spawn-plan.json. All other paths fall through to allow().
    is_active, _ = in_active_vg_run(hook_session=hook_session)
    if is_active:
        run_id = _resolve_run_id(hook_session)
        if run_id:
            rc = _enforce_spawn_count(hook_input, run_id)
            if rc is not None:
                return rc

    return allow()


if __name__ == "__main__":
    sys.exit(main())
