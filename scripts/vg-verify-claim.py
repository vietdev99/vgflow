#!/usr/bin/env python3
"""
Stop hook — deterministic verifier for VG command runtime contracts.

Hook runs when Claude Code session emits Stop event. Reads the last
invoked /vg:* command's runtime_contract from its skill frontmatter,
checks that every declared side effect actually exists on disk /
telemetry log. If ANY check fails, exits with code 2 so Claude is
forced to continue (can't claim done when evidence is missing).

Why this shape (vs NLP claim parsing):
    - Deterministic: same input → same verdict. No LLM disagreement.
    - Ungameable: AI cannot phrase-engineer past filesystem checks.
    - Cheap: ~50ms per run, pure file I/O.
    - Evidence-based: every failure names exactly which artifact is
      missing, so AI can fix specifically instead of flailing.

Hook input (stdin JSON, per Claude Code hooks contract):
    {
      "session_id": "...",
      "transcript_path": "...",
      "cwd": "...",
      "hook_event_name": "Stop",
      "stop_hook_active": false
    }

Hook output:
    - exit 0 + JSON `{"decision": "approve"}` on success → Stop allowed
    - exit 2 + stderr message → Stop BLOCKED, Claude must continue.
      Stderr content becomes feedback injected into Claude's next turn.

Discover-last-command strategy:
    We don't get the command name from Claude Code directly. Instead
    we read the last N turns of transcript + recent git log to infer
    which /vg:<cmd> most recently finished. Heuristic but good enough
    for POC — production version should have orchestrator write
    `.vg/current-run.json` with run_id + command on entry.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands" / "vg"
PHASES_DIR = REPO_ROOT / ".vg" / "phases"
TELEMETRY_LOG = REPO_ROOT / ".vg" / "telemetry.jsonl"
OVERRIDE_DEBT = REPO_ROOT / ".vg" / "OVERRIDE-DEBT.md"
CURRENT_RUN = REPO_ROOT / ".vg" / "current-run.json"
POC_LOG = REPO_ROOT / ".vg" / "hook-verifier.log"


def log(msg: str) -> None:
    """Append to hook log for forensics. Hook output is invisible in UI."""
    try:
        POC_LOG.parent.mkdir(parents=True, exist_ok=True)
        with POC_LOG.open("a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except Exception:
        pass


STALE_THRESHOLD_SECONDS = 30 * 60  # 30 minutes
TRANSCRIPT_RECENT_TURNS = 6        # only consider last N user/assistant turn pairs


def read_current_run() -> dict | None:
    """Orchestrator should write .vg/current-run.json at command entry.
    If file is missing OR stale (> 30 min old), return None.

    Staleness matters: abandoned/crashed /vg:* invocations leave the file
    behind. Without age check, every subsequent Stop event false-fires.
    """
    if not CURRENT_RUN.exists():
        return None
    try:
        data = json.loads(CURRENT_RUN.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"current-run.json parse error: {e}")
        return None

    # Staleness check — if started_at too old, treat as abandoned
    try:
        import datetime as _dt
        started = data.get("started_at") or ""
        if started:
            # Accept either Z-suffix ISO or naive ISO
            s = started.rstrip("Z")
            ts = _dt.datetime.fromisoformat(s)
            age = (_dt.datetime.utcnow() - ts).total_seconds()
            if age > STALE_THRESHOLD_SECONDS:
                log(f"current-run.json is {int(age)}s old — treating as abandoned (threshold {STALE_THRESHOLD_SECONDS}s)")
                return None
    except Exception as e:
        log(f"current-run.json age check failed: {e}")
        # Don't fail-close on parse error — proceed with content

    return data


def infer_last_command_from_transcript(transcript_path: str) -> dict | None:
    """Fallback: scan the most recent ~6 turns of transcript for a VG slash
    command invocation. Older entries are ignored to prevent stale triggers.

    Why recency-bounded: Claude Code transcripts accumulate across a session.
    Without this bound, Stop hooks fire on unrelated user turns long after a
    /vg:* command finished, producing false positives like "SUMMARY.md
    missing" when the user is just chatting.
    """
    if not transcript_path or not Path(transcript_path).exists():
        return None

    # Transcript is JSONL. Each line = one message event (user|assistant|tool).
    try:
        tail = []
        with Path(transcript_path).open(encoding="utf-8") as f:
            for line in f:
                tail.append(line)
                if len(tail) > 2000:
                    tail.pop(0)

        cmd_re = re.compile(r"<command-name>\s*(/vg:[\w-]+)\s*</command-name>")
        arg_re = re.compile(r"<command-args>\s*([^<]*)\s*</command-args>")

        # Recency bound: count "user" entries from the end; stop after N turns.
        # Each transcript line is a JSON object; we parse the "type" field.
        user_turns_seen = 0
        cmd_in_recent_window = None

        for line in reversed(tail):
            try:
                obj = json.loads(line)
            except Exception:
                continue

            msg_type = (obj.get("type") or "").lower()

            # Count user turns as our "recent window" metric
            if msg_type == "user":
                user_turns_seen += 1
                if user_turns_seen > TRANSCRIPT_RECENT_TURNS:
                    break  # older than recent window — stop searching

                # Check if THIS user turn contains a slash command
                content = json.dumps(obj)  # search full message for command tag
                m = cmd_re.search(content)
                if m:
                    cmd_name = m.group(1).lstrip("/")
                    args_match = arg_re.search(content)
                    args = args_match.group(1).strip() if args_match else ""
                    phase = ""
                    parts = args.split()
                    if parts and re.match(r"^\d+(\.\d+)*$", parts[0]):
                        phase = parts[0]
                    cmd_in_recent_window = {
                        "command": cmd_name,
                        "phase": phase,
                        "source": "transcript",
                        "user_turns_back": user_turns_seen,
                    }
                    # Keep oldest-in-window (the one furthest back but still recent)
                    # Actually we want the MOST RECENT /vg:* in window — so break:
                    break

        if cmd_in_recent_window:
            log(f"Transcript: found {cmd_in_recent_window['command']} "
                f"{cmd_in_recent_window['user_turns_back']} user-turn(s) back "
                f"(within recent window of {TRANSCRIPT_RECENT_TURNS})")
            return cmd_in_recent_window

        log(f"Transcript: no /vg:* command in last {TRANSCRIPT_RECENT_TURNS} user turns")
        return None
    except Exception as e:
        log(f"transcript inference error: {e}")

    return None


def parse_frontmatter_runtime_contract(command_file: Path) -> dict | None:
    """Extract runtime_contract block from a VG command skill MD.
    Returns parsed dict or None if absent/malformed.
    """
    if not command_file.exists():
        return None

    text = command_file.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return None

    # Find end of frontmatter
    end_m = re.search(r"\n---\s*\n", text[4:], re.MULTILINE)
    if not end_m:
        return None
    fm_text = text[4:4 + end_m.start()]

    # Minimal YAML-subset parser for runtime_contract block only.
    # Full yaml import would be better but we want stdlib-only for hook.
    try:
        import yaml  # type: ignore
        fm = yaml.safe_load(fm_text) or {}
        return fm.get("runtime_contract")
    except ImportError:
        # Fallback: hand-parse the runtime_contract block
        m = re.search(r"^runtime_contract:\s*\n((?:[ \t].*\n?)+)", fm_text, re.MULTILINE)
        if not m:
            return None
        block = m.group(1)
        # Very minimal — support only list-of-strings items
        contract: dict = {}
        current_key: str | None = None
        for line in block.splitlines():
            if not line.strip() or line.strip().startswith("#"):
                continue
            # Top-level key
            key_m = re.match(r"^  ([a-z_]+):\s*$", line)
            if key_m:
                current_key = key_m.group(1)
                contract[current_key] = []
                continue
            # List item
            item_m = re.match(r"^    -\s+\"?([^\"#]+)\"?\s*$", line)
            if item_m and current_key:
                contract[current_key].append(item_m.group(1).strip())
        return contract


def resolve_phase_dir(phase_number: str) -> Path | None:
    """Find phase dir matching the phase number (handles zero-padding variants)."""
    if not phase_number or not PHASES_DIR.exists():
        return None
    # Try exact + zero-padded
    candidates = []
    candidates += sorted(PHASES_DIR.glob(f"{phase_number}-*"))
    candidates += sorted(PHASES_DIR.glob(f"{phase_number.zfill(2)}-*"))
    if candidates:
        return candidates[0]
    return None


def substitute_vars(template: str, phase_dir: Path, phase_number: str) -> str:
    """Replace ${PHASE_DIR} and ${PHASE_NUMBER} in contract paths."""
    return (template
            .replace("${PHASE_DIR}", str(phase_dir))
            .replace("${PHASE_NUMBER}", phase_number))


def check_must_write(items: list, phase_dir: Path, phase_number: str) -> list[str]:
    """Returns list of missing file paths."""
    missing = []
    for raw in items:
        resolved = substitute_vars(raw, phase_dir, phase_number)
        p = Path(resolved)
        if not p.is_absolute():
            p = REPO_ROOT / p
        if not p.exists() or p.stat().st_size == 0:
            missing.append(str(p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p))
    return missing


def check_markers(marker_names: list, phase_dir: Path) -> list[str]:
    """Returns list of missing step markers."""
    markers_dir = phase_dir / ".step-markers"
    missing = []
    for name in marker_names:
        if not (markers_dir / f"{name}.done").exists():
            missing.append(name)
    return missing


def check_telemetry(events: list, phase_number: str, command: str) -> list[str]:
    """Returns list of missing telemetry events.
    Each event item can be a string (event_type only) or dict {event_type, phase}.
    """
    if not TELEMETRY_LOG.exists():
        return [f"{e if isinstance(e, str) else e.get('event_type','?')}(no telemetry file)"
                for e in events]

    try:
        lines = TELEMETRY_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ["(telemetry log unreadable)"]

    missing = []
    for evt in events:
        if isinstance(evt, str):
            event_type = evt
            expected_phase = phase_number
        elif isinstance(evt, dict):
            event_type = evt.get("event_type", "")
            expected_phase = substitute_vars(evt.get("phase", phase_number), Path(""), phase_number)
        else:
            continue

        found = False
        for line in lines:
            if event_type in line and (not expected_phase or f'"{expected_phase}"' in line):
                found = True
                break
        if not found:
            missing.append(f"{event_type} (phase={expected_phase or 'any'})")
    return missing


def check_override_debt_updated(run_args: str, forbidden_flags: list) -> list[str]:
    """If any forbidden_without_override flag is in run args, check
    override-debt register has an entry for this command.
    """
    used_flags = [f for f in forbidden_flags if f in run_args]
    if not used_flags:
        return []

    if not OVERRIDE_DEBT.exists():
        return [f"{f} used but OVERRIDE-DEBT.md missing entirely" for f in used_flags]

    debt_text = OVERRIDE_DEBT.read_text(encoding="utf-8", errors="replace")
    missing = []
    for flag in used_flags:
        # Heuristic: register should mention the flag text somewhere
        if flag not in debt_text:
            missing.append(f"{flag} used but no register entry")
    return missing


def verify(ctx: dict) -> dict:
    """Main verify. Returns {decision, violations[], command, phase}."""
    command = ctx.get("command", "")
    phase = ctx.get("phase", "")
    run_args = ctx.get("args", "") or ""

    result = {
        "decision": "approve",
        "command": command,
        "phase": phase,
        "violations": [],
        "checks_run": [],
    }

    if not command:
        log("No command inferred — approving (nothing to verify)")
        return result

    # Find command skill file
    cmd_base = command.replace("vg:", "").replace("/", "")
    cmd_file = COMMANDS_DIR / f"{cmd_base}.md"
    if not cmd_file.exists():
        log(f"Command file not found: {cmd_file} — approving")
        return result

    contract = parse_frontmatter_runtime_contract(cmd_file)
    if not contract:
        log(f"{command}: no runtime_contract in frontmatter — approving (not opted-in)")
        return result

    # Phase inference guard: if command requires a phase (has ${PHASE_DIR}
    # or ${PHASE_NUMBER} in its contract) but we couldn't infer one,
    # skip verification. Phase-less verification produces false positives —
    # the transcript-inferred command is almost certainly stale.
    needs_phase = False
    for section in ("must_write", "must_touch_markers", "must_emit_telemetry"):
        items = contract.get(section) or []
        blob = json.dumps(items)
        if "${PHASE_DIR}" in blob or "${PHASE_NUMBER}" in blob:
            needs_phase = True
            break

    if needs_phase and not phase:
        log(f"{command}: contract requires phase but none inferred "
            f"(transcript source, likely stale) — approving silently")
        result["skip_reason"] = "no-phase-with-phase-dependent-contract"
        return result

    # Resolve phase dir for path substitution
    phase_dir = resolve_phase_dir(phase) if phase else None
    if not phase_dir and needs_phase:
        log(f"{command}: phase='{phase}' but no matching phase dir — approving "
            f"(phase may not exist yet, or legacy naming)")
        result["skip_reason"] = "phase-dir-not-resolved"
        return result

    if not phase_dir:
        # Non-phase contract (none in current set but may exist future) — use repo root
        phase_dir = REPO_ROOT

    # must_write
    items = contract.get("must_write") or []
    if items:
        missing = check_must_write(items, phase_dir, phase)
        result["checks_run"].append(f"must_write({len(items)})")
        if missing:
            result["violations"].append({
                "type": "must_write",
                "missing": missing,
                "hint": "Artifact files missing or empty. Did the step actually run + write output?",
            })

    # must_touch_markers
    markers = contract.get("must_touch_markers") or []
    if markers and phase_dir and phase_dir != REPO_ROOT:
        missing = check_markers(markers, phase_dir)
        result["checks_run"].append(f"must_touch_markers({len(markers)})")
        if missing:
            result["violations"].append({
                "type": "must_touch_markers",
                "missing": missing,
                "hint": "Step markers missing. Each <step> MUST end with `touch .step-markers/{name}.done`. Silent skip = violation.",
            })

    # must_emit_telemetry
    events = contract.get("must_emit_telemetry") or []
    if events:
        missing = check_telemetry(events, phase, command)
        result["checks_run"].append(f"must_emit_telemetry({len(events)})")
        if missing:
            result["violations"].append({
                "type": "must_emit_telemetry",
                "missing": missing,
                "hint": "Telemetry events not in .vg/telemetry.jsonl. Either emit_telemetry was skipped, or telemetry helper not sourced. Don't claim done without evidence.",
            })

    # forbidden_without_override
    forbidden = contract.get("forbidden_without_override") or []
    if forbidden and run_args:
        missing = check_override_debt_updated(run_args, forbidden)
        result["checks_run"].append(f"forbidden_without_override({len(forbidden)})")
        if missing:
            result["violations"].append({
                "type": "forbidden_without_override",
                "missing": missing,
                "hint": "Override flag used without updating OVERRIDE-DEBT.md register. Every --allow/--skip/--override-reason MUST log to debt register for acceptance gate review.",
            })

    if result["violations"]:
        result["decision"] = "block"

    return result


def format_block_message(verdict: dict) -> str:
    """Build the stderr feedback that Claude sees on exit 2."""
    lines = [
        "⛔ VG Stop-hook: runtime contract violations detected.",
        "",
        f"Command: /{verdict['command']}" + (f" {verdict['phase']}" if verdict['phase'] else ""),
        f"Checks run: {', '.join(verdict.get('checks_run', [])) or 'none'}",
        "",
        "Missing evidence:",
    ]
    for v in verdict["violations"]:
        lines.append(f"  [{v['type']}]")
        for m in v["missing"]:
            lines.append(f"    - {m}")
        lines.append(f"    → {v['hint']}")
        lines.append("")

    lines.extend([
        "Do NOT claim done. Either:",
        "  1. Run the missing step + produce the artifacts",
        "  2. Document why it is acceptable to skip (--override-reason + debt register)",
        "  3. Fix the underlying helper so the side effect actually fires",
        "",
        "Hook log: .vg/hook-verifier.log",
    ])
    return "\n".join(lines)


def main() -> int:
    # Read hook input from stdin (Claude Code hooks contract)
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except Exception:
        hook_input = {}

    transcript_path = hook_input.get("transcript_path", "")
    stop_active = hook_input.get("stop_hook_active", False)

    log(f"--- Hook fire @ {os.environ.get('USER', '?')} — cwd={os.getcwd()}")
    log(f"stop_hook_active={stop_active}, transcript={transcript_path[:80]}")

    # Infinite-loop guard per hooks docs
    if stop_active:
        log("stop_hook_active=True — not re-blocking (avoids loop)")
        print(json.dumps({"decision": "approve", "reason": "loop-guard"}))
        return 0

    # Discover command context: prefer current-run.json, fallback transcript
    ctx = read_current_run()
    if not ctx:
        ctx = infer_last_command_from_transcript(transcript_path)
    if not ctx:
        log("No command context — approving (nothing to verify)")
        print(json.dumps({"decision": "approve", "reason": "no-command-context"}))
        return 0

    log(f"Inferred command: {ctx.get('command')} phase={ctx.get('phase')} source={ctx.get('source','?')}")

    verdict = verify(ctx)
    log(f"Verdict: {verdict['decision']} — {len(verdict['violations'])} violation(s)")

    if verdict["decision"] == "approve":
        # Happy path — emit approval JSON, exit 0
        print(json.dumps({"decision": "approve", "checks_run": verdict["checks_run"]}))
        return 0

    # Violations — block via exit 2 + stderr message
    msg = format_block_message(verdict)
    log("BLOCKED — feedback injected to Claude:")
    log(msg)
    print(msg, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Never crash — on error, log + approve (safer than false-block)
        try:
            log(f"HOOK ERROR (soft-approving): {e}")
        except Exception:
            pass
        print(json.dumps({"decision": "approve", "reason": "hook-error"}))
        sys.exit(0)
