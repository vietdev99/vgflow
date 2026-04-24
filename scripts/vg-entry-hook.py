#!/usr/bin/env python3
"""
UserPromptSubmit hook — pre-seeds orchestrator run-start BEFORE Claude
processes a /vg:* command.

Purpose: close the "AI can skip init" gap. Skill-MD has a
`vg-orchestrator run-start` call at top, but AI could rationalize past it.
This hook fires OUTSIDE the LLM loop — Claude Code harness invokes it on
every user message submit. If the message is a /vg:* slash command, we
register the run atomically before Claude loads skill-MD.

Design:
- Fast path: non-/vg:* messages → early approve, <5ms.
- Only acts on /vg:{command} {phase} patterns.
- Idempotent: if active run already matches (same command+phase), skip.
- Never blocks user — approve always. Orchestrator rejection logged only.
- If orchestrator missing or crashes, log + approve (degraded-correct).

Hook input (stdin JSON, Claude Code UserPromptSubmit contract):
  {
    "session_id": "...",
    "transcript_path": "...",
    "cwd": "...",
    "hook_event_name": "UserPromptSubmit",
    "prompt": "user message text"
  }

Hook output (stdout):
  {"decision": "approve"}  — always (we never block input)
  Optionally with `additionalContext` to inform Claude the run was registered.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
CURRENT_RUN = REPO_ROOT / ".vg" / "current-run.json"
ORCH = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
LOG = REPO_ROOT / ".vg" / "hook-entry.log"

# Match /vg:command followed by optional args. Phase is usually first
# positional numeric token; capture it when present.
VG_CMD_RE = re.compile(
    r"/vg:([a-z][a-z-]*)(?:\s+(\S+))?"
)


def log(msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.utcnow().isoformat()}Z] {msg}\n")
    except Exception:
        pass


def approve(context: str | None = None) -> None:
    resp = {"decision": "approve"}
    if context:
        resp["hookSpecificOutput"] = {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    print(json.dumps(resp))
    sys.exit(0)


def already_active(command: str, phase: str) -> bool:
    """Skip if current-run.json already matches."""
    if not CURRENT_RUN.exists():
        return False
    try:
        d = json.loads(CURRENT_RUN.read_text(encoding="utf-8"))
        return d.get("command") == command and d.get("phase") == phase
    except Exception:
        return False


def _looks_like_paste_back(prompt: str) -> bool:
    """v2.5.2.5 — detect Stop-hook feedback echoed into next prompt.

    Bug: Stop hook output contains `Command: /vg:review 7.14`; when user
    pastes (or Claude Code auto-forwards) that feedback in the next turn,
    VG_CMD_RE matched the embedded reference and re-registered a phantom
    run. Resulting in an infinite stop-hook loop that could only be broken
    by manual `run-abort`.

    Signals we're looking at paste-back text, not a fresh user command:
      - "Stop hook feedback" (Claude Code literal prefix)
      - "runtime_contract violations" (verify-claim error text)
      - "Command: /vg:" (verify-claim "Command:" line)
      - "Fix options:" + "vg-orchestrator override" (verify-claim footer)
      - "Missing evidence:" (verify-claim body marker)
    """
    markers = (
        "Stop hook feedback",
        "runtime_contract violations",
        "Missing evidence:",
        "vg-orchestrator override",
        "vg-orchestrator run-abort",
    )
    return any(m in prompt for m in markers)


def _vg_cmd_at_line_start(prompt: str):
    """Find /vg:command matching a fresh invocation: MUST be first
    non-whitespace content of a line. Embedded references like
    `Command: /vg:review 7.14` fail this check.
    """
    for line in prompt.splitlines():
        stripped = line.lstrip()
        m = VG_CMD_RE.match(stripped)  # match (not search) — anchored to line start
        if m:
            return m
    return None


def main() -> int:
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except Exception:
        approve()

    prompt = hook_input.get("prompt") or ""

    # Fast path: non-VG messages
    if "/vg:" not in prompt:
        approve()

    # v2.5.2.5: reject paste-back text from Stop-hook feedback loops
    if _looks_like_paste_back(prompt):
        log(f"paste-back detected (Stop-hook feedback echo) — skipping run-start")
        approve()

    # v2.5.2.5: require /vg:cmd at START of a line (not embedded in prose).
    # A fresh user invocation always has /vg:X at column 0 of some line.
    # Paste-back text ("Command: /vg:review 7.14"), inline references
    # ("just run /vg:X please"), or quoted examples in docs/prose will NOT
    # match and are correctly skipped.
    m = _vg_cmd_at_line_start(prompt)
    if not m:
        log("/vg: pattern not at line start — treating as prose reference, skip")
        approve()

    cmd_name = m.group(1)
    phase_token = m.group(2) or ""

    # Skip non-phase commands (e.g. /vg:progress, /vg:doctor) — these have
    # their own lifecycle or no phase concept. Phase must look like a number
    # (14, 7.6, 07.12).
    if not re.match(r"^\d+(\.\d+)*$", phase_token):
        log(f"non-phase /vg:{cmd_name} — skipping run-start")
        approve()

    command = f"vg:{cmd_name}"

    # Idempotent check
    if already_active(command, phase_token):
        log(f"{command} phase={phase_token} already active — skip")
        approve(context=f"VG run {command} phase={phase_token} already "
                        f"registered (orchestrator idempotent).")

    # Orchestrator must exist
    if not (ORCH / "__main__.py").exists():
        log(f"orchestrator missing at {ORCH} — approve degraded")
        approve()

    # Fire run-start
    try:
        r = subprocess.run(
            [sys.executable, str(ORCH), "run-start", command, phase_token],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT),
        )
        if r.returncode == 0:
            run_id = r.stdout.strip()
            log(f"registered {command} phase={phase_token} run_id={run_id[:8]}")
            approve(context=(
                f"VG orchestrator registered run {command} phase={phase_token} "
                f"(run_id {run_id[:8]}). Skill-MD will inherit active run."
            ))
        else:
            # Orchestrator rejected (e.g. concurrent active run). Log only.
            log(f"orchestrator run-start rc={r.returncode} "
                f"stderr={r.stderr[:200]}")
            approve(context=(
                f"⚠ VG orchestrator rejected run-start for {command} "
                f"phase={phase_token}: {r.stderr.strip()[:200]}. "
                f"Resolve via /vg:doctor stack or vg-orchestrator run-abort."
            ))
    except Exception as e:
        log(f"orchestrator invoke error: {e}")
        approve()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            log(f"hook error (soft-approve): {e}")
        except Exception:
            pass
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)
