#!/usr/bin/env bash
# SessionStart hook for VGFlow harness.
# Matchers: startup|resume|clear|compact (per Claude Code hooks docs)
# Injects vg-meta-skill.md content + open diagnostics from events.db.

set -euo pipefail

# Default PLUGIN_ROOT to the directory containing this script — vg-meta-skill.md
# sits next to it. Avoids relative-path failure when hook fires from arbitrary CWD.
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
META_SKILL_PATH="${PLUGIN_ROOT}/vg-meta-skill.md"
EVENTS_DB="${VG_EVENTS_DB:-.vg/events.db}"
ACTIVE_RUN_PATH=".vg/active-runs/${CLAUDE_HOOK_SESSION_ID:-default}.json"

if [ ! -f "$META_SKILL_PATH" ]; then
  # Graceful degrade — VG meta-skill missing, no context to inject.
  # Log once per invocation for diagnostics; do NOT block session.
  warn_log=".vg/.session-start-warn.log"
  mkdir -p "$(dirname "$warn_log")" 2>/dev/null || true
  printf '%s session=%s meta-skill missing at %s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "${CLAUDE_HOOK_SESSION_ID:-default}" \
    "$META_SKILL_PATH" >> "$warn_log" 2>/dev/null || true
  exit 0
fi

base_text="$(cat "$META_SKILL_PATH")"

diagnostics=""
# Task 31 (cross-session block awareness): enumerate ALL .vg/active-runs/*.json,
# filter unhandled blocks (severity error|critical, no matching vg.block.handled,
# run not in terminal state), report own session first then other sessions.
# Resume/compact triggers full enumeration; startup/clear stays minimal.
if [[ "${CLAUDE_HOOK_EVENT:-}" =~ ^(compact|resume|startup)$ ]] && [ -f "$EVENTS_DB" ] && [ -d ".vg/active-runs" ]; then
  diagnostics="$(VG_OWN_SESSION_ID="${CLAUDE_HOOK_SESSION_ID:-default}" \
    VG_EVENTS_DB="$EVENTS_DB" \
    python3 - <<'PY' 2>/dev/null || true
import json, os, sqlite3, sys
from pathlib import Path

own_session = os.environ.get("VG_OWN_SESSION_ID", "default")
events_db = Path(os.environ.get("VG_EVENTS_DB", ".vg/events.db"))
active_dir = Path(".vg/active-runs")

def unhandled_for(conn, run_id: str) -> list[dict]:
    """Distinct gates with NO matching handled, severity error|critical."""
    try:
        rows = conn.execute("""
            SELECT DISTINCT
              json_extract(payload_json, '$.gate'),
              json_extract(payload_json, '$.cause'),
              json_extract(payload_json, '$.block_file'),
              COALESCE(json_extract(payload_json, '$.severity'), 'error'),
              json_extract(payload_json, '$.skill_path')
            FROM events
            WHERE run_id = ? AND event_type IN ('vg.block.fired', 'vg.block.refired')
              AND COALESCE(json_extract(payload_json, '$.severity'), 'error') IN ('error','critical')
              AND json_extract(payload_json, '$.gate') NOT IN (
                SELECT json_extract(payload_json, '$.gate')
                FROM events
                WHERE run_id = ? AND event_type = 'vg.block.handled'
              )
        """, (run_id, run_id)).fetchall()
    except sqlite3.Error:
        return []
    return [{"gate": r[0], "cause": r[1], "block_file": r[2],
             "severity": r[3], "skill_path": r[4]} for r in rows if r[0]]

def is_terminal(conn, run_id: str) -> bool:
    try:
        row = conn.execute("""
            SELECT 1 FROM events
            WHERE run_id = ? AND event_type IN ('run.completed', 'run.aborted')
            LIMIT 1
        """, (run_id,)).fetchone()
    except sqlite3.Error:
        return False
    return row is not None

if not events_db.exists():
    sys.exit(0)

try:
    conn = sqlite3.connect(str(events_db), timeout=2.0)
except sqlite3.Error:
    sys.exit(0)

own_run_file = active_dir / f"{own_session}.json"
own_run_id = ""
if own_run_file.exists():
    try:
        own_run_id = json.loads(own_run_file.read_text(encoding="utf-8")).get("run_id", "")
    except (OSError, ValueError):
        pass

sections: list[str] = []

def render_section(label: str, run_id: str, items: list[dict]) -> str:
    lines = [f"\n## OPEN DIAGNOSTICS — {label} (run {run_id})"]
    for it in items:
        sev = it.get("severity", "error")
        lines.append(f"- gate={it['gate']} severity={sev}")
        if it.get("cause"):
            lines.append(f"  cause: {it['cause']}")
        if it.get("block_file"):
            lines.append(f"  block_file: {it['block_file']}")
        if it.get("skill_path"):
            lines.append(f"  skill: {it['skill_path']}")
    return "\n".join(lines)

if own_run_id:
    own = unhandled_for(conn, own_run_id)
    if own and not is_terminal(conn, own_run_id):
        sections.append(render_section("this session", own_run_id, own))

if active_dir.exists():
    for run_file in sorted(active_dir.glob("*.json")):
        if run_file.name == f"{own_session}.json":
            continue
        try:
            other = json.loads(run_file.read_text(encoding="utf-8")).get("run_id", "")
        except (OSError, ValueError):
            continue
        if not other or is_terminal(conn, other):
            continue
        items = unhandled_for(conn, other)
        if items:
            other_sess = run_file.stem
            label = f"session {other_sess[:8]}... (cross-session — not yours, but stuck)"
            sections.append(render_section(label, other, items))

if sections:
    sys.stdout.write("\n".join(sections))
    sys.stdout.write("\n\nYou MUST close each diagnostic above before continuing other work.\n")
PY
)"
fi

session_context=$'<EXTREMELY_IMPORTANT>\nYou have VGFlow harness loaded.\n\n'"${base_text}${diagnostics}"$'\n</EXTREMELY_IMPORTANT>'

# Tier 1 #108 — already uses JSON hookSpecificOutput.additionalContext shape.
# Switched to python3 json.dumps (full envelope, not just the string) for
# consistency with the dual-channel pattern in sibling hooks. Auto-handles
# 10K char cap with file+preview fallback (Claude Code 2.0+).
VG_SESSION_CTX="$session_context" python3 -c '
import json, os, sys
sys.stdout.write(json.dumps({
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": os.environ.get("VG_SESSION_CTX", ""),
  }
}))
sys.stdout.write("\n")
'
