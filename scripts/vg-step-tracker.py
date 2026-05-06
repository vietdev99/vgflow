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
SESSION_CONTEXTS_DIR = REPO_ROOT / ".vg" / "session-contexts"
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
    # Avoid treating shell capability probes as real step transitions.
    # Example: `type -t mark_step >/dev/null 2>&1 && mark_step ...`
    # previously matched `mark_step >/dev/null 2` and recorded step "2".
    probe_scrubbed = re.sub(
        r"(?:^|[;&|()\s])(?:type\s+-t|command\s+-v)\s+mark_step\b[^\n;&|)]*",
        " ",
        command,
    )
    m = TOUCH_MARKER_RE.search(probe_scrubbed)
    if m:
        return (m.group("step"), m.group("transition"))
    m = MARK_STEP_HELPER_RE.search(probe_scrubbed)
    if m:
        return (m.group("step"), "mark")
    m = MARK_STEP_CMD_RE.search(probe_scrubbed)
    if m:
        return (m.group("step"), "mark")
    return None


def _session_context_path(session_id: str | None) -> Path | None:
    if not session_id:
        return None
    return SESSION_CONTEXTS_DIR / f"{_safe_session_filename(session_id)}.json"

def _read_session_context(hook_session_id: str | None = None) -> dict | None:
    candidates: list[Path] = []
    per_session = _session_context_path(hook_session_id)
    if per_session is not None:
        candidates.append(per_session)
    candidates.append(SESSION_CONTEXT)

    for path in candidates:
        if not path.exists():
            continue
        try:
            ctx = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"session-context parse error ({path}): {e}")
            continue
        if (
            hook_session_id
            and isinstance(ctx, dict)
            and ctx.get("session_id")
            and str(ctx.get("session_id")) != str(hook_session_id)
        ):
            continue
        return ctx if isinstance(ctx, dict) else None
    return None


def _atomic_write_json(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except Exception as e:
        log(f"session-context write error ({path}): {e}")


def _write_session_context(ctx: dict) -> None:
    _atomic_write_json(SESSION_CONTEXT, ctx)
    per_session = _session_context_path(str(ctx.get("session_id") or ""))
    if per_session is not None:
        _atomic_write_json(per_session, ctx)


def _safe_session_filename(sid: str) -> str:
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")
    return safe or "unknown"


def _read_json(path: Path) -> dict | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _context_matches_active_run(ctx: dict, hook_session_id: str | None) -> bool:
    ctx_session = ctx.get("session_id")
    if hook_session_id and ctx_session and hook_session_id != ctx_session:
        log(f"skip stale context: hook session {hook_session_id} != ctx session {ctx_session}")
        return False

    candidates: list[Path] = []
    if ctx_session:
        candidates.append(REPO_ROOT / ".vg" / "active-runs" / f"{_safe_session_filename(str(ctx_session))}.json")
    candidates.append(REPO_ROOT / ".vg" / "current-run.json")

    for path in candidates:
        run = _read_json(path)
        if not run:
            continue
        if ctx.get("run_id") and run.get("run_id") != ctx.get("run_id"):
            continue
        if ctx_session and run.get("session_id") and str(run.get("session_id")) != str(ctx_session):
            continue
        mismatched = False
        for key in ("command", "phase"):
            if ctx.get(key) and run.get(key) and str(ctx.get(key)) != str(run.get(key)):
                mismatched = True
                break
        if not mismatched:
            return True

    log(
        "skip stale context: no active-run matches "
        f"run_id={ctx.get('run_id')} command={ctx.get('command')} phase={ctx.get('phase')}"
    )
    return False


def _emit_telemetry(event_type: str, payload: dict) -> None:
    """Best-effort `hook.*` telemetry via vg-orchestrator emit-event.
    `hook.*` prefix is reserved-safe (not in RESERVED_EVENT_PREFIXES).
    """
    try:
        env = os.environ.copy()
        session_id = payload.get("session_id")
        if session_id:
            env["CLAUDE_SESSION_ID"] = str(session_id)
            env["CLAUDE_HOOK_SESSION_ID"] = str(session_id)
        subprocess.run(
            [sys.executable, str(ORCHESTRATOR), "emit-event",
             event_type,
             "--actor", "hook",
             "--outcome", "INFO",
             "--payload", json.dumps(payload)],
            capture_output=True, text=True, timeout=5, env=env,
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
    hook_session_id = hook_input.get("session_id")
    ctx = _read_session_context(str(hook_session_id) if hook_session_id else None)
    if not ctx:
        return 0
    if not _context_matches_active_run(ctx, hook_session_id):
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
                "session_id": ctx.get("session_id"),
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
