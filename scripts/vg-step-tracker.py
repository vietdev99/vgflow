#!/usr/bin/env python3
"""
PostToolUse hook (Bash matcher) — Layer 2 of v2.7 Phase F marker tracking.

Detects when AI runs `touch <path>/.step-markers/<step>.{start,done}` (or
`mark_step <ns> <step>`) inside a /vg:* run, and updates
.vg/.session-context.json:current_step + appends to step_history.

Companion telemetry: emits `hook.step_active` event (best-effort, dedup'd
per (run_id, step, transition)) so /vg:gate-stats can report drift
patterns. Reactive companion to v2.8.3 hybrid Stop-hook.

Why Layer 2 separate from Layer 1 (vg-entry-hook):
- Layer 1 fires once per UserPromptSubmit (user types /vg:cmd).
- Layer 2 fires once per Bash tool call (potentially many per turn).
- Different cadence + payload schema = clean separation.

Hook input (stdin JSON, Claude Code PostToolUse contract):
  {
    "session_id": "...",
    "tool_name": "Bash",
    "tool_input": { "command": "...", ... },
    "tool_response": { ... },
    "cwd": "..."
  }

Hook output: always exits 0 (never blocks). Optionally emits
hookSpecificOutput.additionalContext on dedup-violation detection.

Failure modes:
- session-context.json missing → no-op (no active /vg:* run).
- bash command unparseable → no-op.
- orchestrator emit-event fails → log + continue.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
SESSION_CONTEXT = REPO_ROOT / ".vg" / ".session-context.json"
ORCHESTRATOR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
LOG = REPO_ROOT / ".vg" / "hook-step-tracker.log"

# Patterns the AI uses to mark step transitions:
# (a) Direct touch:         touch ${PHASE_DIR}/.step-markers/8_execute_waves.done
#                           touch "/foo/.step-markers/blueprint/2a_plan.start"
# (b) mark_step helper:     mark_step "${PHASE_NUMBER}" "8_execute_waves" "${PHASE_DIR}"
#                           mark_step shared 5d_codegen
# (c) orchestrator mark-step: vg-orchestrator mark-step build 8_execute_waves
TOUCH_MARKER_RE = re.compile(
    r"""touch\s+
        (?:["']?)              # optional opening quote
        [^\s"']*\.step-markers/(?:[^/\s"']+/)?
        (?P<step>[A-Za-z0-9_][A-Za-z0-9_-]*)
        \.(?P<transition>start|done)
        (?:["']?)              # optional closing quote
    """,
    re.VERBOSE,
)
MARK_STEP_HELPER_RE = re.compile(
    r"""mark_step\s+
        (?:["'][^"']*["']\s+|[^\s]+\s+)?  # optional phase number arg
        ["']?(?P<step>[A-Za-z0-9_][A-Za-z0-9_-]*)["']?
    """,
    re.VERBOSE,
)
MARK_STEP_CMD_RE = re.compile(
    r"""vg-orchestrator(?:/__main__\.py)?\s+
        mark-step\s+
        (?:[A-Za-z_][A-Za-z0-9_-]*\s+)   # namespace
        (?P<step>[A-Za-z0-9_][A-Za-z0-9_-]*)
    """,
    re.VERBOSE,
)


def log(msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            f.write(f"[{ts}] {msg.rstrip()}\n")
    except Exception:
        pass


def _detect_step_transition(command: str) -> tuple[str, str] | None:
    """Parse bash command for step marker writes. Returns (step, transition)
    or None when no match. transition ∈ {"start", "done", "mark"}.
    """
    if not command:
        return None
    m = TOUCH_MARKER_RE.search(command)
    if m:
        return (m.group("step"), m.group("transition"))
    m = MARK_STEP_HELPER_RE.search(command)
    if m:
        return (m.group("step"), "mark")
    m = MARK_STEP_CMD_RE.search(command)
    if m:
        return (m.group("step"), "mark")
    return None


def _read_session_context() -> dict | None:
    if not SESSION_CONTEXT.exists():
        return None
    try:
        return json.loads(SESSION_CONTEXT.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"session-context parse error: {e}")
        return None


def _write_session_context(ctx: dict) -> None:
    try:
        SESSION_CONTEXT.write_text(
            json.dumps(ctx, indent=2), encoding="utf-8"
        )
    except Exception as e:
        log(f"session-context write error: {e}")


def _emit_telemetry(event_type: str, payload: dict) -> None:
    """Best-effort `hook.*` telemetry via vg-orchestrator emit-event.
    `hook.*` prefix is reserved-safe (not in RESERVED_EVENT_PREFIXES).
    """
    try:
        subprocess.run(
            [sys.executable, str(ORCHESTRATOR), "emit-event",
             event_type,
             "--actor", "hook",
             "--outcome", "INFO",
             "--payload", json.dumps(payload)],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:
        log(f"emit-event failed for {event_type}: {e}")


def main() -> int:
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Bash":
        return 0

    tool_input = hook_input.get("tool_input") or {}
    command = tool_input.get("command", "")
    if not command:
        return 0

    transition = _detect_step_transition(command)
    if not transition:
        return 0

    step_name, kind = transition

    # Skip if no active /vg:* run — session-context only exists during
    # an active run (Layer 1 vg-entry-hook seeds it).
    ctx = _read_session_context()
    if not ctx:
        return 0

    # Update state
    previous_step = ctx.get("current_step")
    if kind in ("done", "mark"):
        ctx["current_step"] = step_name
        history = ctx.get("step_history") or []
        if not history or history[-1].get("step") != step_name:
            history.append({
                "step": step_name,
                "transition": kind,
                "ts": datetime.datetime.now(datetime.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            })
            ctx["step_history"] = history
        _write_session_context(ctx)
        log(f"step transition: {previous_step} → {step_name} ({kind})")

    # Emit telemetry — dedup per (run_id, step, kind) using
    # telemetry_emitted set in session-context to avoid event flood when
    # AI runs touch multiple times for same marker.
    emitted = set(ctx.get("telemetry_emitted") or [])
    dedup_key = f"{step_name}:{kind}"
    if dedup_key not in emitted:
        emitted.add(dedup_key)
        ctx["telemetry_emitted"] = sorted(emitted)
        _write_session_context(ctx)
        _emit_telemetry(
            "hook.step_active",
            {
                "run_id": ctx.get("run_id"),
                "command": ctx.get("command"),
                "phase": ctx.get("phase"),
                "step": step_name,
                "transition": kind,
                "previous_step": previous_step,
            },
        )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        try:
            log(f"hook error (soft-approve): {e}")
        except Exception:
            pass
        sys.exit(0)
