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

Exit code: always 0 (we communicate decisions via JSON). Failures fall
through to "allow" silently — never break user's workflow on hook bug.
"""
from __future__ import annotations

import json
import os
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


def allow() -> int:
    # Empty stdout = neutral pass-through (Claude Code proceeds normally).
    return 0


def deny(reason: str) -> int:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(payload))
    return 0


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

    # Only enforce for gsd-* subagent types; everything else is none of
    # our business.
    if not subagent_type.startswith("gsd-"):
        return allow()

    # gsd-debugger is the legitimate exception VG uses in build.md step 12.
    if subagent_type in ALLOWED_GSD_SUBAGENTS:
        return allow()

    # Only block when an active VG run is in progress. Outside VG context
    # (e.g., user running /gsd-execute-phase directly), let the spawn
    # proceed — VG isn't authoritative there.
    is_active, vg_command = in_active_vg_run(hook_session=hook_session)
    if not is_active:
        return allow()

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


if __name__ == "__main__":
    sys.exit(main())
