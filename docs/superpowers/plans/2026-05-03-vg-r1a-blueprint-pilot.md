# R1a Blueprint Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the canary pilot for VG harness refactor — slim `vg:blueprint.md` (3970→≤500 lines) + 8 flat reference files + 2 custom subagents + 7 hook scripts + 2 helper scripts + dogfood verify on PrintwayV3 phase 2. Pilot is the GATE that decides whether the pattern replicates to all 9 other VG commands.

**Architecture:** Anthropic-aligned progressive disclosure (≤500 line SKILL.md + on-demand references) + 8-layer enforcement (slim surface, imperative language, SessionStart context bootstrap, UserPromptSubmit start gate, PreToolUse Bash/Write/Agent gates, PostToolUse evidence capture, Stop completion + state-machine + diagnostic verification). HMAC-signed evidence prevents AI forgery. Subagents isolate heavy steps with narrow tools/context.

**Tech Stack:** bash (hook scripts), Python 3 (helpers + tests), pytest, Claude Code hooks API, sqlite3 (events.db queries), JSON (contracts/evidence files), HMAC-SHA256 (signed evidence).

**Spec source:** `docs/superpowers/specs/2026-05-03-vg-blueprint-pilot-design.md` (commit 17f7d60, 700+ lines, includes Codex review amendments).

**Branch:** `feat/rfc-v9-followup-fixes` (working). Each task commits incrementally; final dogfood before merge.

---

## Phase A — Shared Infrastructure (helpers, hooks, install)

Built ONCE in this pilot, inherited by R1b/c/d + R2-R5. Order: foundational helpers first (Tasks 1-2), then hooks consuming them (Tasks 3-9), then install + meta-skill (Tasks 10-11).

### Task 1: HMAC evidence helper script

**Files:**
- Create: `scripts/vg-orchestrator-emit-evidence-signed.py`
- Test: `scripts/tests/test_evidence_helper_signs_hmac.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_evidence_helper_signs_hmac.py
import hmac, hashlib, json, os, subprocess, tempfile
from pathlib import Path


def test_emit_evidence_signed_writes_hmac_payload(tmp_path, monkeypatch):
    key = b"test-key-32-bytes-aaaaaaaaaaaaaaa"
    key_path = tmp_path / ".evidence-key"
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    monkeypatch.setenv("VG_EVIDENCE_KEY_PATH", str(key_path))

    out_path = tmp_path / "evidence.json"
    payload = {"contract_sha256": "abc", "todowrite_at": "2026-05-03T10:00:00Z"}
    subprocess.run(
        [
            "python3", "scripts/vg-orchestrator-emit-evidence-signed.py",
            "--out", str(out_path),
            "--payload", json.dumps(payload),
        ],
        check=True,
    )
    written = json.loads(out_path.read_text())
    assert written["payload"] == payload
    expected = hmac.new(key, json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
    assert written["hmac_sha256"] == expected


def test_emit_evidence_signed_rejects_when_key_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("VG_EVIDENCE_KEY_PATH", str(tmp_path / "missing"))
    result = subprocess.run(
        ["python3", "scripts/vg-orchestrator-emit-evidence-signed.py",
         "--out", str(tmp_path / "out.json"), "--payload", "{}"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "evidence key" in result.stderr.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
pytest scripts/tests/test_evidence_helper_signs_hmac.py -v
```
Expected: FAIL with "No such file or directory: 'scripts/vg-orchestrator-emit-evidence-signed.py'"

- [ ] **Step 3: Implement helper**

```python
#!/usr/bin/env python3
# scripts/vg-orchestrator-emit-evidence-signed.py
"""HMAC-signed evidence emitter — only path that writes protected paths.

Usage:
    vg-orchestrator-emit-evidence-signed.py --out <path> --payload <json>

Reads HMAC key from $VG_EVIDENCE_KEY_PATH (default .vg/.evidence-key, mode 0600).
Writes JSON: {"payload": <input>, "hmac_sha256": "<hex>", "signed_at": "<iso8601>"}
"""
import argparse, hashlib, hmac, json, os, sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_KEY_PATH = ".vg/.evidence-key"


def load_key() -> bytes:
    key_path = Path(os.environ.get("VG_EVIDENCE_KEY_PATH", DEFAULT_KEY_PATH))
    if not key_path.exists():
        sys.stderr.write(
            f"ERROR: evidence key missing at {key_path}\n"
            f"Run: openssl rand -base64 32 > {key_path} && chmod 600 {key_path}\n"
        )
        sys.exit(2)
    if (key_path.stat().st_mode & 0o077) != 0:
        sys.stderr.write(f"ERROR: evidence key {key_path} must be mode 0600\n")
        sys.exit(2)
    return key_path.read_bytes().strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--payload", required=True, help="JSON string")
    args = ap.parse_args()

    payload = json.loads(args.payload)
    key = load_key()
    canonical = json.dumps(payload, sort_keys=True).encode()
    sig = hmac.new(key, canonical, hashlib.sha256).hexdigest()

    record = {
        "payload": payload,
        "hmac_sha256": sig,
        "signed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
```

```bash
chmod +x scripts/vg-orchestrator-emit-evidence-signed.py
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest scripts/tests/test_evidence_helper_signs_hmac.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/vg-orchestrator-emit-evidence-signed.py scripts/tests/test_evidence_helper_signs_hmac.py
git commit -m "feat(r1a): HMAC-signed evidence helper (Codex fix #2)

The only path that writes protected evidence files. Loads HMAC key
from .vg/.evidence-key (mode 0600), signs payload with HMAC-SHA256,
writes JSON record to disk. Hooks verify signature before trusting
evidence — closes AI evidence-forgery bypass."
```

---

### Task 2: State-machine validator script

**Files:**
- Create: `scripts/vg-state-machine-validator.py`
- Test: `scripts/tests/test_state_machine_validator.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_state_machine_validator.py
import json, sqlite3, subprocess
from pathlib import Path


def _seed_events(db_path: Path, events: list) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ts TEXT, event_type TEXT, phase TEXT, command TEXT, run_id TEXT,"
        "payload TEXT)"
    )
    for ev in events:
        conn.execute(
            "INSERT INTO events(ts,event_type,phase,command,run_id,payload) VALUES (?,?,?,?,?,?)",
            (ev["ts"], ev["event_type"], ev["phase"], "vg:blueprint", ev["run_id"], "{}"),
        )
    conn.commit()
    conn.close()


def test_blueprint_events_in_order_passes(tmp_path):
    db = tmp_path / "events.db"
    events = [
        {"ts": "2026-05-03T10:00:00Z", "event_type": "blueprint.tasklist_shown", "phase": "2", "run_id": "r1"},
        {"ts": "2026-05-03T10:00:01Z", "event_type": "blueprint.native_tasklist_projected", "phase": "2", "run_id": "r1"},
        {"ts": "2026-05-03T10:00:02Z", "event_type": "blueprint.plan_written", "phase": "2", "run_id": "r1"},
        {"ts": "2026-05-03T10:00:03Z", "event_type": "blueprint.contracts_generated", "phase": "2", "run_id": "r1"},
        {"ts": "2026-05-03T10:00:04Z", "event_type": "crossai.verdict", "phase": "2", "run_id": "r1"},
        {"ts": "2026-05-03T10:00:05Z", "event_type": "blueprint.completed", "phase": "2", "run_id": "r1"},
    ]
    _seed_events(db, events)
    result = subprocess.run(
        ["python3", "scripts/vg-state-machine-validator.py",
         "--db", str(db), "--command", "vg:blueprint", "--run-id", "r1"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_blueprint_events_out_of_order_fails(tmp_path):
    db = tmp_path / "events.db"
    events = [
        {"ts": "2026-05-03T10:00:00Z", "event_type": "blueprint.native_tasklist_projected", "phase": "2", "run_id": "r1"},
        {"ts": "2026-05-03T10:00:01Z", "event_type": "blueprint.tasklist_shown", "phase": "2", "run_id": "r1"},
    ]
    _seed_events(db, events)
    result = subprocess.run(
        ["python3", "scripts/vg-state-machine-validator.py",
         "--db", str(db), "--command", "vg:blueprint", "--run-id", "r1"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "out of order" in result.stderr.lower() or "expected" in result.stderr.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_state_machine_validator.py -v
```
Expected: FAIL with file-not-found.

- [ ] **Step 3: Implement validator**

```python
#!/usr/bin/env python3
# scripts/vg-state-machine-validator.py
"""Verify events emitted in the expected order per command (state machine).

Closes Codex bypass #5: must_emit checks count, not semantic order.
Stop hook invokes this before allowing run-complete.
"""
import argparse, sqlite3, sys


# Per-command expected event sequence (subset is required-in-order).
COMMAND_SEQUENCES = {
    "vg:blueprint": [
        "blueprint.tasklist_shown",
        "blueprint.native_tasklist_projected",
        "blueprint.plan_written",
        "blueprint.contracts_generated",
        "crossai.verdict",
        "blueprint.completed",
    ],
}


def fetch_events(db_path: str, command: str, run_id: str) -> list:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT event_type FROM events WHERE command=? AND run_id=? ORDER BY id ASC",
        (command, run_id),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def validate(events: list, expected: list) -> tuple[bool, str]:
    pointer = 0
    for ev in events:
        if pointer < len(expected) and ev == expected[pointer]:
            pointer += 1
    if pointer < len(expected):
        return False, f"expected event '{expected[pointer]}' missing or out of order at sequence position {pointer}"
    return True, "ok"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--command", required=True)
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()

    if args.command not in COMMAND_SEQUENCES:
        sys.stderr.write(f"ERROR: no state machine defined for command '{args.command}'\n")
        sys.exit(2)

    expected = COMMAND_SEQUENCES[args.command]
    events = fetch_events(args.db, args.command, args.run_id)
    ok, msg = validate(events, expected)
    if not ok:
        sys.stderr.write(f"STATE MACHINE FAIL: {msg}\nexpected sequence: {expected}\nactual events: {events}\n")
        sys.exit(2)
    print("STATE MACHINE OK")


if __name__ == "__main__":
    main()
```

```bash
chmod +x scripts/vg-state-machine-validator.py
```

- [ ] **Step 4: Run test**

```bash
pytest scripts/tests/test_state_machine_validator.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/vg-state-machine-validator.py scripts/tests/test_state_machine_validator.py
git commit -m "feat(r1a): state-machine validator (Codex fix #5)

Verifies events emitted in expected ORDER per command (semantic check
beyond mere event count). Stop hook invokes before allowing
run-complete. Initial blueprint sequence: tasklist_shown →
native_tasklist_projected → plan_written → contracts_generated →
crossai.verdict → completed."
```

---

### Task 3: vg-meta-skill.md content (SessionStart inject)

**Files:**
- Create: `scripts/hooks/vg-meta-skill.md`

- [ ] **Step 1: Write the meta-skill text**

```bash
cat > scripts/hooks/vg-meta-skill.md <<'META_SKILL'
<EXTREMELY-IMPORTANT>
You have entered a VGFlow workflow session.

VGFlow is a deterministic harness. Steps are not suggestions. They are
contracts validated by hooks. You CANNOT skip a step by claiming it is
"obvious" or "already done" — every step has a marker file and an event
record that the Stop hook verifies.

If a tool call is blocked by PreToolUse hook, read the stderr message,
fulfill the missing prerequisite, then retry. Do not work around the gate.
</EXTREMELY-IMPORTANT>

## Red Flags (you have used these before — they will not work)

| Thought | Reality |
|---|---|
| "I already understand the structure, no need to read references" | References contain step-specific instructions absent from entry |
| "Subagent overkill for this small step" | Heavy step has empirical 96.5% skip rate without subagent |
| "TodoWrite is just UI, the contract is in events" | Hook checks TodoWrite payload against contract checksum |
| "I can mark step done now and finish content later" | Stop hook reads must_write content_min_bytes; placeholder fails |
| "The block was a one-off, retrying should work" | Each block emits vg.block.fired; Stop hook blocks if unhandled |
| "I'll just retry, no need to tell the user" | Layer 5 rule: narrate in session language using template, never retry silently |
| "I'll write the evidence file directly" | Protected paths blocked by PreToolUse on Write — use vg-orchestrator-emit-evidence-signed.py |

## Open diagnostic threads (Layer 4 mechanism)

If this injected context contains "OPEN DIAGNOSTICS for current run", you
have unresolved blocks from earlier in this run (possibly across context
compactions). For each open diagnostic, you MUST:

1. Read the cause + required fix from the original block message (still in
   events.db, query: `vg-orchestrator query-events --event-type vg.block.fired`)
2. Apply the fix
3. Narrate to user in session language using the template from the original block
4. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`

You CANNOT do other work until all open diagnostics are closed. Stop hook
will refuse run-complete if any vg.block.fired is unpaired with vg.block.handled.

## Pipeline commands governed by VGFlow

project, roadmap, specs, scope, blueprint, build, review, test, accept

When the user invokes `/vg:<cmd>`, follow the slim entry SKILL.md exactly.
Read references when instructed. Spawn subagents (using tool name `Agent`,
NOT `Task`) when instructed.
META_SKILL
```

- [ ] **Step 2: Verify file exists**

```bash
test -f scripts/hooks/vg-meta-skill.md && wc -l scripts/hooks/vg-meta-skill.md
```
Expected: file exists, ~40 lines.

- [ ] **Step 3: Commit**

```bash
git add scripts/hooks/vg-meta-skill.md
git commit -m "feat(r1a): vg-meta-skill.md text injected by SessionStart

Contains EXTREMELY-IMPORTANT rules, Red Flags table (anti-rationalization),
open diagnostic threads protocol, and Agent vs Task tool name guidance.
Adopted from superpowers using-superpowers pattern."
```

---

### Task 4: SessionStart hook script

**Files:**
- Create: `scripts/hooks/vg-session-start.sh`
- Test: `scripts/tests/test_session_start_reinjects_open_diagnostics.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_session_start_reinjects_open_diagnostics.py
import json, os, sqlite3, subprocess
from pathlib import Path


def _seed_run_with_unhandled_block(repo: Path):
    (repo / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (repo / ".vg/active-runs/sess-1.json").write_text(json.dumps({
        "run_id": "r1", "command": "vg:blueprint", "phase": "2",
    }))
    db = repo / ".vg/events.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ts TEXT, event_type TEXT, phase TEXT, command TEXT, run_id TEXT,"
        "payload TEXT)"
    )
    conn.execute(
        "INSERT INTO events(ts,event_type,phase,command,run_id,payload) VALUES (?,?,?,?,?,?)",
        ("2026-05-03T10:00:00Z", "vg.block.fired", "2", "vg:blueprint", "r1",
         json.dumps({"gate": "PreToolUse-tasklist", "cause": "evidence missing"})),
    )
    conn.commit()
    conn.close()


def test_session_start_basic_injects_meta_skill(tmp_path, monkeypatch):
    repo = tmp_path
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "scripts/hooks")
    Path("scripts/hooks").mkdir(parents=True, exist_ok=True)
    Path("scripts/hooks/vg-meta-skill.md").write_text("<EXTREMELY-IMPORTANT>\nVGFlow rules\n</EXTREMELY-IMPORTANT>")
    result = subprocess.run(
        ["bash", os.path.join(os.getcwd(), "scripts/hooks/vg-session-start.sh")],
        capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_EVENT": "startup"},
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "EXTREMELY-IMPORTANT" in ctx
    assert "VGFlow rules" in ctx


def test_session_start_compact_reinjects_open_diagnostics(tmp_path, monkeypatch):
    repo = tmp_path
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "scripts/hooks")
    Path("scripts/hooks").mkdir(parents=True, exist_ok=True)
    Path("scripts/hooks/vg-meta-skill.md").write_text("base meta-skill")
    _seed_run_with_unhandled_block(repo)
    result = subprocess.run(
        ["bash", os.path.join(os.getcwd(), "scripts/hooks/vg-session-start.sh")],
        capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_EVENT": "compact",
             "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "OPEN DIAGNOSTICS" in ctx
    assert "PreToolUse-tasklist" in ctx
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_session_start_reinjects_open_diagnostics.py -v
```
Expected: FAIL — script does not exist.

- [ ] **Step 3: Implement hook script**

```bash
cat > scripts/hooks/vg-session-start.sh <<'HOOK'
#!/usr/bin/env bash
# SessionStart hook for VGFlow harness.
# Matchers: startup|resume|clear|compact (per Claude Code hooks docs)
# Injects vg-meta-skill.md content + open diagnostics from events.db.

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-scripts/hooks}"
META_SKILL_PATH="${PLUGIN_ROOT}/vg-meta-skill.md"
EVENTS_DB="${VG_EVENTS_DB:-.vg/events.db}"
ACTIVE_RUN_PATH=".vg/active-runs/${CLAUDE_HOOK_SESSION_ID:-default}.json"

if [ ! -f "$META_SKILL_PATH" ]; then
  echo "ERROR: meta-skill missing at $META_SKILL_PATH" >&2
  exit 1
fi

base_text="$(cat "$META_SKILL_PATH")"

# On compact/resume, append open diagnostics from active run (if any).
diagnostics=""
if [[ "${CLAUDE_HOOK_EVENT:-}" =~ ^(compact|resume)$ ]] && [ -f "$ACTIVE_RUN_PATH" ] && [ -f "$EVENTS_DB" ]; then
  run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$ACTIVE_RUN_PATH" 2>/dev/null || true)"
  if [ -n "$run_id" ]; then
    fired="$(sqlite3 "$EVENTS_DB" "SELECT payload FROM events WHERE run_id='$run_id' AND event_type='vg.block.fired'" 2>/dev/null || true)"
    handled="$(sqlite3 "$EVENTS_DB" "SELECT payload FROM events WHERE run_id='$run_id' AND event_type='vg.block.handled'" 2>/dev/null || true)"
    if [ -n "$fired" ]; then
      diagnostics="\n\n## OPEN DIAGNOSTICS for current run ${run_id}\n${fired}\nYou MUST close each diagnostic before continuing other work.\n"
    fi
  fi
fi

session_context="<EXTREMELY_IMPORTANT>\nYou have VGFlow harness loaded.\n\n${base_text}\n${diagnostics}\n</EXTREMELY_IMPORTANT>"

# Escape for JSON.
escaped="$(python3 -c '
import json,sys
print(json.dumps(sys.stdin.read())[1:-1])
' <<< "$session_context")"

printf '{\n  "hookSpecificOutput": {\n    "hookEventName": "SessionStart",\n    "additionalContext": "%s"\n  }\n}\n' "$escaped"
HOOK
chmod +x scripts/hooks/vg-session-start.sh
```

- [ ] **Step 4: Run test**

```bash
pytest scripts/tests/test_session_start_reinjects_open_diagnostics.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/hooks/vg-session-start.sh scripts/tests/test_session_start_reinjects_open_diagnostics.py
git commit -m "feat(r1a): SessionStart hook injects meta-skill + open diagnostics

Matchers: startup|resume|clear|compact. Injects vg-meta-skill.md content
plus, on compact/resume, any unhandled vg.block.fired events from active
run (Layer 4 of diagnostic flow). Pattern adopted from superpowers."
```

---

### Task 5: UserPromptSubmit hook script (start-of-run gate)

**Files:**
- Create: `scripts/hooks/vg-user-prompt-submit.sh`
- Test: `scripts/tests/test_user_prompt_submit_creates_run.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_user_prompt_submit_creates_run.py
import json, os, subprocess
from pathlib import Path


def test_user_prompt_creates_active_run_for_vg_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".vg").mkdir()
    payload = json.dumps({"prompt": "/vg:blueprint 2"})
    result = subprocess.run(
        ["bash", os.path.join(os.environ.get("OLDPWD", os.getcwd()),
                              "scripts/hooks/vg-user-prompt-submit.sh")]
        if False else ["bash", "-c",
                       f"cd {tmp_path} && bash {os.path.join(os.environ.get('OLDPWD', os.getcwd()), 'scripts/hooks/vg-user-prompt-submit.sh')}"],
        input=payload, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-test"},
    )
    assert result.returncode == 0, result.stderr
    run_file = tmp_path / ".vg/active-runs/sess-test.json"
    assert run_file.exists()
    state = json.loads(run_file.read_text())
    assert state["command"] == "vg:blueprint"
    assert state["phase"] == "2"


def test_user_prompt_no_op_for_non_vg(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".vg").mkdir()
    payload = json.dumps({"prompt": "explain this code"})
    result = subprocess.run(
        ["bash", "-c",
         f"cd {tmp_path} && bash {os.path.join(os.environ.get('OLDPWD', os.getcwd()), 'scripts/hooks/vg-user-prompt-submit.sh')}"],
        input=payload, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-test"},
    )
    assert result.returncode == 0
    run_file = tmp_path / ".vg/active-runs/sess-test.json"
    assert not run_file.exists()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_user_prompt_submit_creates_run.py -v
```
Expected: FAIL — script does not exist.

- [ ] **Step 3: Implement hook**

```bash
cat > scripts/hooks/vg-user-prompt-submit.sh <<'HOOK'
#!/usr/bin/env bash
# UserPromptSubmit hook — closes Codex bypass #1.
# Detects /vg:<cmd> <args> in prompt text. Creates active-run state file
# BEFORE the model runs so Stop hook later has run context to validate.

set -euo pipefail

input="$(cat)"
prompt="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("prompt",""))' 2>/dev/null || true)"

# Match /vg:<cmd> [<args>...]
if [[ ! "$prompt" =~ ^/vg:([a-z][a-z0-9_-]*)([[:space:]]+(.*))?$ ]]; then
  exit 0
fi

cmd="vg:${BASH_REMATCH[1]}"
args="${BASH_REMATCH[3]:-}"
phase="$(printf '%s' "$args" | awk '{print $1}')"
session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
run_file=".vg/active-runs/${session_id}.json"

mkdir -p ".vg/active-runs"

# Reject if active run already exists with different command (resolution gate).
if [ -f "$run_file" ]; then
  existing="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["command"])' "$run_file" 2>/dev/null || true)"
  if [ -n "$existing" ] && [ "$existing" != "$cmd" ]; then
    echo "ERROR: active run for $existing exists; finish or abort before invoking $cmd" >&2
    exit 2
  fi
fi

run_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "$run_file" <<JSON
{
  "run_id": "$run_id",
  "command": "$cmd",
  "phase": "$phase",
  "session_id": "$session_id",
  "started_at": "$ts"
}
JSON
HOOK
chmod +x scripts/hooks/vg-user-prompt-submit.sh
```

- [ ] **Step 4: Run test**

```bash
pytest scripts/tests/test_user_prompt_submit_creates_run.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/hooks/vg-user-prompt-submit.sh scripts/tests/test_user_prompt_submit_creates_run.py
git commit -m "feat(r1a): UserPromptSubmit hook (Codex fix #1) start-of-run gate

Detects /vg:<cmd> in prompt text, creates .vg/active-runs/<session>.json
BEFORE model executes. Closes Codex bypass #1 — Stop hook would otherwise
no-op without active run, allowing AI to bypass entire enforcement chain
by answering before invocation registered."
```

---

### Task 6: PreToolUse on Write/Edit hook (protect evidence paths)

**Files:**
- Create: `scripts/hooks/vg-pre-tool-use-write.sh`
- Test: `scripts/tests/test_pre_tool_use_write_blocks_protected.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_pre_tool_use_write_blocks_protected.py
import json, os, subprocess
from pathlib import Path

PROTECTED = [
    ".vg/runs/r1/.tasklist-projected.evidence.json",
    ".vg/runs/r1/evidence-something.json",
    ".vg/phases/01-foo/.step-markers/blueprint/2a_plan.done",
    ".vg/events.db",
    ".vg/events.jsonl",
]
ALLOWED = [
    "src/app/page.tsx",
    "docs/notes.md",
    ".vg/runs/r1/tasklist-contract.json",  # contract file is NOT protected (orchestrator writes directly)
]


def _run_hook(file_path: str, tool_name: str = "Write"):
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"file_path": file_path}})
    return subprocess.run(
        ["bash", "scripts/hooks/vg-pre-tool-use-write.sh"],
        input=payload, capture_output=True, text=True,
    )


def test_protected_paths_blocked():
    for path in PROTECTED:
        result = _run_hook(path, "Write")
        assert result.returncode == 2, f"expected block for {path}, got rc={result.returncode}"
        assert "vg-orchestrator-emit-evidence-signed" in result.stderr.lower() or "protected" in result.stderr.lower()


def test_protected_paths_blocked_for_edit():
    for path in PROTECTED:
        result = _run_hook(path, "Edit")
        assert result.returncode == 2, f"expected block for {path} (Edit)"


def test_allowed_paths_pass():
    for path in ALLOWED:
        result = _run_hook(path, "Write")
        assert result.returncode == 0, f"expected pass for {path}, got rc={result.returncode}, stderr={result.stderr}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_pre_tool_use_write_blocks_protected.py -v
```
Expected: FAIL — script does not exist.

- [ ] **Step 3: Implement hook**

```bash
cat > scripts/hooks/vg-pre-tool-use-write.sh <<'HOOK'
#!/usr/bin/env bash
# PreToolUse on Write/Edit — closes Codex bypass #2 (forgeable evidence).
# Blocks direct writes to protected evidence/marker/event paths.

set -euo pipefail

input="$(cat)"
file_path="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null || true)"

if [ -z "$file_path" ]; then
  exit 0
fi

# Protected path patterns.
protected_patterns=(
  '\.vg/runs/[^/]+/\.tasklist-projected\.evidence\.json$'
  '\.vg/runs/[^/]+/evidence-.*\.json$'
  '\.vg/runs/[^/]+/.*evidence.*'
  '\.vg/phases/.*/\.step-markers/.*\.done$'
  '\.vg/events\.db$'
  '\.vg/events\.jsonl$'
)

for pattern in "${protected_patterns[@]}"; do
  if [[ "$file_path" =~ $pattern ]]; then
    cat >&2 <<MSG
═══════════════════════════════════════════
DIAGNOSTIC REQUIRED — Gate: PreToolUse-Write-protected
═══════════════════════════════════════════

CAUSE:
  Direct write to protected evidence path:
    ${file_path}
  This path holds harness-controlled evidence; direct writes would
  forge the harness's view of what AI did.

REQUIRED FIX:
  Use scripts/vg-orchestrator-emit-evidence-signed.py to write signed
  evidence, OR use vg-orchestrator subcommand for markers/events.

YOU MUST DO ALL THREE BEFORE CONTINUING:
  A) Tell user: "[VG diagnostic] Bước hiện tại bị chặn vì cố ghi vào
     đường dẫn được bảo vệ. Đang xử lý: dùng helper signed."
  B) Bash: vg-orchestrator emit-event vg.block.handled \\
            --gate PreToolUse-Write-protected \\
            --resolution "switched to signed helper"
  C) Retry with the signed helper.
═══════════════════════════════════════════
MSG
    # Emit vg.block.fired (best-effort).
    if command -v vg-orchestrator >/dev/null 2>&1; then
      vg-orchestrator emit-event vg.block.fired \
        --gate PreToolUse-Write-protected \
        --cause "direct write to $file_path" >/dev/null 2>&1 || true
    fi
    exit 2
  fi
done

exit 0
HOOK
chmod +x scripts/hooks/vg-pre-tool-use-write.sh
```

- [ ] **Step 4: Run test**

```bash
pytest scripts/tests/test_pre_tool_use_write_blocks_protected.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/hooks/vg-pre-tool-use-write.sh scripts/tests/test_pre_tool_use_write_blocks_protected.py
git commit -m "feat(r1a): PreToolUse Write/Edit hook (Codex fix #2)

Blocks AI direct writes to protected paths: tasklist-projected.evidence,
evidence-*, .step-markers, events.db, events.jsonl. Stderr is
diagnostic prompt per §4.5 Layer 1. Closes evidence forgery bypass —
AI must use signed helper or vg-orchestrator subcommands instead."
```

---

### Task 7: PreToolUse on Bash hook (tasklist evidence gate)

**Files:**
- Create: `scripts/hooks/vg-pre-tool-use-bash.sh`
- Test: `scripts/tests/test_hook_pretooluse_blocks.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_hook_pretooluse_blocks.py
import json, hashlib, hmac, os, subprocess
from pathlib import Path


def _seed_active_run(repo: Path):
    (repo / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (repo / ".vg/active-runs/sess-1.json").write_text(json.dumps({
        "run_id": "r1", "command": "vg:blueprint", "phase": "2",
        "session_id": "sess-1",
    }))


def _seed_signed_evidence(repo: Path, payload: dict, key: bytes):
    evidence_path = repo / ".vg/runs/r1/.tasklist-projected.evidence.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(payload, sort_keys=True).encode()
    sig = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    evidence_path.write_text(json.dumps(
        {"payload": payload, "hmac_sha256": sig}, sort_keys=True
    ))


def test_blocks_when_evidence_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    cmd_input = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "vg-orchestrator step-active 2a_plan"},
    })
    result = subprocess.run(
        ["bash", os.path.join(os.environ.get("OLDPWD", os.getcwd()),
                              "scripts/hooks/vg-pre-tool-use-bash.sh")],
        input=cmd_input, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 2
    assert "DIAGNOSTIC REQUIRED" in result.stderr
    assert "TodoWrite" in result.stderr or "tasklist" in result.stderr


def test_passes_when_evidence_signed_and_matches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    key = b"test-key-32-bytes-aaaaaaaaaaaaaaa"
    key_path = tmp_path / ".vg/.evidence-key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    monkeypatch.setenv("VG_EVIDENCE_KEY_PATH", str(key_path))
    _seed_active_run(tmp_path)
    contract_path = tmp_path / ".vg/runs/r1/tasklist-contract.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text('{"checklists":[{"id":"blueprint_preflight"}]}')
    contract_sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    _seed_signed_evidence(tmp_path, {"contract_sha256": contract_sha}, key)
    cmd_input = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "vg-orchestrator step-active 2a_plan"},
    })
    result = subprocess.run(
        ["bash", os.path.join(os.environ.get("OLDPWD", os.getcwd()),
                              "scripts/hooks/vg-pre-tool-use-bash.sh")],
        input=cmd_input, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 0, result.stderr


def test_passes_for_unrelated_bash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    cmd_input = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
    })
    result = subprocess.run(
        ["bash", os.path.join(os.environ.get("OLDPWD", os.getcwd()),
                              "scripts/hooks/vg-pre-tool-use-bash.sh")],
        input=cmd_input, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_hook_pretooluse_blocks.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement hook**

```bash
cat > scripts/hooks/vg-pre-tool-use-bash.sh <<'HOOK'
#!/usr/bin/env bash
# PreToolUse on Bash — gate before vg-orchestrator step-active.
# Verifies signed tasklist evidence file exists + checksum matches contract.

set -euo pipefail

input="$(cat)"
cmd_text="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null || true)"

# Only gate when bash invokes vg-orchestrator step-active.
if [[ ! "$cmd_text" =~ vg-orchestrator[[:space:]]+step-active ]]; then
  exit 0
fi

session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
run_file=".vg/active-runs/${session_id}.json"
if [ ! -f "$run_file" ]; then
  exit 0  # no active run; nothing to gate.
fi

run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$run_file")"
evidence_path=".vg/runs/${run_id}/.tasklist-projected.evidence.json"
contract_path=".vg/runs/${run_id}/tasklist-contract.json"
key_path="${VG_EVIDENCE_KEY_PATH:-.vg/.evidence-key}"

emit_block() {
  local cause="$1"
  cat >&2 <<MSG
═══════════════════════════════════════════
DIAGNOSTIC REQUIRED — Gate: PreToolUse-tasklist
═══════════════════════════════════════════

CAUSE:
  ${cause}

REQUIRED FIX:
  1. Read .vg/runs/${run_id}/tasklist-contract.json
  2. Call TodoWrite with each checklist group as one todo item
  3. Verify PostToolUse hook wrote signed evidence file
  4. Retry the blocked vg-orchestrator step-active call

YOU MUST DO ALL THREE BEFORE CONTINUING:
  A) Tell user (in session language) using template:
     "[VG diagnostic] Bước <step> đang bị chặn. Lý do: chưa gọi TodoWrite.
      Đang xử lý: project tasklist-contract. Sẽ tiếp tục sau khi xong."
  B) Bash: vg-orchestrator emit-event vg.block.handled \\
            --gate PreToolUse-tasklist \\
            --resolution "TodoWrite called, evidence regenerated"
  C) Retry the original tool call.

If this gate has blocked ≥3 times this run, you MUST call AskUserQuestion
instead of retrying.
═══════════════════════════════════════════
MSG
  if command -v vg-orchestrator >/dev/null 2>&1; then
    vg-orchestrator emit-event vg.block.fired \
      --gate PreToolUse-tasklist --cause "$cause" >/dev/null 2>&1 || true
  fi
  exit 2
}

if [ ! -f "$evidence_path" ]; then
  emit_block "evidence file missing at ${evidence_path}; TodoWrite has not been called for run ${run_id}"
fi

if [ ! -f "$key_path" ]; then
  emit_block "evidence key missing at ${key_path}; cannot verify HMAC"
fi

verify_result="$(python3 - "$evidence_path" "$key_path" "$contract_path" <<'PY'
import hashlib, hmac, json, sys
ev_path, key_path, contract_path = sys.argv[1:]
ev = json.loads(open(ev_path).read())
key = open(key_path, 'rb').read().strip()
canonical = json.dumps(ev["payload"], sort_keys=True).encode()
expected = hmac.new(key, canonical, hashlib.sha256).hexdigest()
if expected != ev.get("hmac_sha256"):
    print("hmac_invalid", end="")
    sys.exit(0)
contract_sha = ev["payload"].get("contract_sha256", "")
if contract_path:
    actual_contract = hashlib.sha256(open(contract_path, 'rb').read()).hexdigest()
    if contract_sha != actual_contract:
        print("contract_mismatch", end="")
        sys.exit(0)
print("ok", end="")
PY
)"

case "$verify_result" in
  ok) exit 0 ;;
  hmac_invalid) emit_block "evidence file HMAC invalid (signature does not match key)" ;;
  contract_mismatch) emit_block "evidence contract checksum does not match current tasklist-contract.json" ;;
  *) emit_block "evidence verification failed: ${verify_result}" ;;
esac
HOOK
chmod +x scripts/hooks/vg-pre-tool-use-bash.sh
```

- [ ] **Step 4: Run test**

```bash
pytest scripts/tests/test_hook_pretooluse_blocks.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/hooks/vg-pre-tool-use-bash.sh scripts/tests/test_hook_pretooluse_blocks.py
git commit -m "feat(r1a): PreToolUse Bash hook gates step-active

Blocks 'vg-orchestrator step-active' calls when signed evidence file
missing/HMAC-invalid/contract-mismatch. Stderr formatted per §4.5
Layer 1 diagnostic prompt. Emits vg.block.fired event for Layer 2
pairing tracking."
```

---

### Task 8: PostToolUse on TodoWrite hook (capture + sign evidence)

**Files:**
- Create: `scripts/hooks/vg-post-tool-use-todowrite.sh`
- Test: `scripts/tests/test_hook_posttooluse_writes_evidence.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_hook_posttooluse_writes_evidence.py
import hashlib, json, os, subprocess
from pathlib import Path


def test_post_tool_use_writes_signed_evidence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    key = b"test-key-32-bytes-aaaaaaaaaaaaaaa"
    key_path = tmp_path / ".vg/.evidence-key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    monkeypatch.setenv("VG_EVIDENCE_KEY_PATH", str(key_path))

    (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg/active-runs/sess-1.json").write_text(json.dumps({
        "run_id": "r1", "command": "vg:blueprint", "phase": "2",
    }))

    contract_path = tmp_path / ".vg/runs/r1/tasklist-contract.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract = {"checklists": [
        {"id": "blueprint_preflight", "title": "Preflight"},
        {"id": "blueprint_design", "title": "Design"},
    ]}
    contract_path.write_text(json.dumps(contract))

    todowrite_payload = json.dumps({
        "tool_name": "TodoWrite",
        "tool_input": {"todos": [
            {"content": "blueprint_preflight: Preflight", "status": "pending"},
            {"content": "blueprint_design: Design", "status": "pending"},
        ]},
    })

    result = subprocess.run(
        ["bash", os.path.join(os.environ.get("OLDPWD", os.getcwd()),
                              "scripts/hooks/vg-post-tool-use-todowrite.sh")],
        input=todowrite_payload, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 0, result.stderr

    evidence_path = tmp_path / ".vg/runs/r1/.tasklist-projected.evidence.json"
    assert evidence_path.exists()
    evidence = json.loads(evidence_path.read_text())
    assert "hmac_sha256" in evidence
    assert evidence["payload"]["contract_sha256"] == hashlib.sha256(
        contract_path.read_bytes()
    ).hexdigest()
    assert evidence["payload"]["match"] is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_hook_posttooluse_writes_evidence.py -v
```
Expected: FAIL — script does not exist.

- [ ] **Step 3: Implement hook**

```bash
cat > scripts/hooks/vg-post-tool-use-todowrite.sh <<'HOOK'
#!/usr/bin/env bash
# PostToolUse on TodoWrite — capture payload, diff vs contract,
# write signed evidence via vg-orchestrator-emit-evidence-signed.py.

set -euo pipefail

input="$(cat)"
session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
run_file=".vg/active-runs/${session_id}.json"
if [ ! -f "$run_file" ]; then
  exit 0
fi

run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$run_file")"
contract_path=".vg/runs/${run_id}/tasklist-contract.json"
if [ ! -f "$contract_path" ]; then
  exit 0
fi

# Build evidence payload.
payload="$(printf '%s' "$input" | python3 - "$contract_path" "$run_id" <<'PY'
import hashlib, json, sys
from datetime import datetime, timezone
contract_path, run_id = sys.argv[1:]
hook_input = json.load(sys.stdin)
todos = hook_input.get("tool_input", {}).get("todos", [])
todo_ids = sorted([t.get("content", "").split(":")[0].strip() for t in todos if t.get("content")])
contract = json.loads(open(contract_path).read())
contract_ids = sorted([c["id"] for c in contract.get("checklists", [])])
match = todo_ids == contract_ids
payload = {
    "run_id": run_id,
    "todowrite_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "todo_count": len(todos),
    "contract_sha256": hashlib.sha256(open(contract_path, "rb").read()).hexdigest(),
    "todo_ids": todo_ids,
    "contract_ids": contract_ids,
    "match": match,
}
print(json.dumps(payload))
PY
)"

evidence_out=".vg/runs/${run_id}/.tasklist-projected.evidence.json"
python3 scripts/vg-orchestrator-emit-evidence-signed.py \
  --out "$evidence_out" --payload "$payload"

# Emit telemetry event (best-effort).
if command -v vg-orchestrator >/dev/null 2>&1; then
  cmd="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["command"])' "$run_file" | sed 's/^vg://')"
  vg-orchestrator emit-event "${cmd}.native_tasklist_projected" >/dev/null 2>&1 || true
fi
HOOK
chmod +x scripts/hooks/vg-post-tool-use-todowrite.sh
```

- [ ] **Step 4: Run test**

```bash
pytest scripts/tests/test_hook_posttooluse_writes_evidence.py -v
```
Expected: 1 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/hooks/vg-post-tool-use-todowrite.sh scripts/tests/test_hook_posttooluse_writes_evidence.py
git commit -m "feat(r1a): PostToolUse TodoWrite hook captures signed evidence

Reads TodoWrite payload, diffs against tasklist-contract.json, writes
HMAC-signed evidence via vg-orchestrator-emit-evidence-signed.py.
PreToolUse Bash hook later verifies this evidence before allowing
step-active. Emits <cmd>.native_tasklist_projected telemetry event."
```

---

### Task 9: PreToolUse on Agent hook (spawn-count placeholder)

**Files:**
- Create: `scripts/hooks/vg-pre-tool-use-agent.sh`
- Test: `scripts/tests/test_pre_tool_use_agent_matcher.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_pre_tool_use_agent_matcher.py
import json, os, subprocess


def test_agent_hook_passes_for_known_subagent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = json.dumps({
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "vg-blueprint-planner", "prompt": "..."},
    })
    result = subprocess.run(
        ["bash", os.path.join(os.environ.get("OLDPWD", os.getcwd()),
                              "scripts/hooks/vg-pre-tool-use-agent.sh")],
        input=payload, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_agent_hook_blocks_gsd_subagent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = json.dumps({
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "gsd-executor", "prompt": "..."},
    })
    result = subprocess.run(
        ["bash", os.path.join(os.environ.get("OLDPWD", os.getcwd()),
                              "scripts/hooks/vg-pre-tool-use-agent.sh")],
        input=payload, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "gsd" in result.stderr.lower() or "not allowed" in result.stderr.lower()


def test_agent_hook_passes_for_general_purpose():
    payload = json.dumps({
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "general-purpose", "prompt": "..."},
    })
    result = subprocess.run(
        ["bash", "scripts/hooks/vg-pre-tool-use-agent.sh"],
        input=payload, capture_output=True, text=True,
    )
    assert result.returncode == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_pre_tool_use_agent_matcher.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement hook**

```bash
cat > scripts/hooks/vg-pre-tool-use-agent.sh <<'HOOK'
#!/usr/bin/env bash
# PreToolUse on Agent — Codex fix #3 (correct tool name "Agent" not "Task").
# R1a scope: enforce subagent allow-list. Spawn-count check added in R2 build spec.

set -euo pipefail

input="$(cat)"
subagent="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("subagent_type",""))' 2>/dev/null || true)"

# Allow-list: general-purpose, Explore, Plan, vg-* custom agents, gsd-debugger only.
if [[ "$subagent" =~ ^(general-purpose|Explore|Plan|gsd-debugger)$ ]]; then
  exit 0
fi
if [[ "$subagent" == vg-* ]]; then
  exit 0
fi

# Block other gsd-* explicitly.
if [[ "$subagent" == gsd-* ]]; then
  cat >&2 <<MSG
ERROR: subagent type '${subagent}' not allowed.
Only general-purpose, Explore, Plan, vg-*, gsd-debugger are allowed.
MSG
  exit 2
fi

# Default deny unknown.
cat >&2 <<MSG
ERROR: unknown subagent type '${subagent}'. Allowed: general-purpose, Explore, Plan, vg-*, gsd-debugger.
MSG
exit 2
HOOK
chmod +x scripts/hooks/vg-pre-tool-use-agent.sh
```

- [ ] **Step 4: Run test**

```bash
pytest scripts/tests/test_pre_tool_use_agent_matcher.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/hooks/vg-pre-tool-use-agent.sh scripts/tests/test_pre_tool_use_agent_matcher.py
git commit -m "feat(r1a): PreToolUse Agent hook enforces subagent allow-list

Tool name 'Agent' (not 'Task') per Claude Code hooks docs (Codex fix #3).
Allow-list: general-purpose, Explore, Plan, vg-*, gsd-debugger.
Blocks other gsd-* and unknown subagent types. Spawn-count enforcement
deferred to R2 build spec."
```

---

### Task 10: Stop hook (contract verify + state-machine + diagnostic pairing)

**Files:**
- Create: `scripts/hooks/vg-stop.sh`
- Test: `scripts/tests/test_stop_hook_requires_block_handled_pair.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_stop_hook_requires_block_handled_pair.py
import json, os, sqlite3, subprocess
from pathlib import Path


def _setup_run(repo: Path, fired_count: int = 0, handled_count: int = 0):
    (repo / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (repo / ".vg/active-runs/sess-1.json").write_text(json.dumps({
        "run_id": "r1", "command": "vg:blueprint", "phase": "2",
    }))
    db = repo / ".vg/events.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ts TEXT, event_type TEXT, phase TEXT, command TEXT, run_id TEXT,"
        "payload TEXT)"
    )
    for i in range(fired_count):
        conn.execute(
            "INSERT INTO events(ts,event_type,phase,command,run_id,payload) VALUES (?,?,?,?,?,?)",
            ("2026-05-03T10:00:00Z", "vg.block.fired", "2", "vg:blueprint", "r1",
             json.dumps({"gate": f"gate-{i}"})),
        )
    for i in range(handled_count):
        conn.execute(
            "INSERT INTO events(ts,event_type,phase,command,run_id,payload) VALUES (?,?,?,?,?,?)",
            ("2026-05-03T10:00:01Z", "vg.block.handled", "2", "vg:blueprint", "r1",
             json.dumps({"gate": f"gate-{i}"})),
        )
    conn.commit()
    conn.close()


def test_stop_passes_when_no_active_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = subprocess.run(
        ["bash", os.path.join(os.environ.get("OLDPWD", os.getcwd()),
                              "scripts/hooks/vg-stop.sh")],
        input="{}", capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 0


def test_stop_blocks_on_unpaired_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _setup_run(tmp_path, fired_count=2, handled_count=1)
    result = subprocess.run(
        ["bash", os.path.join(os.environ.get("OLDPWD", os.getcwd()),
                              "scripts/hooks/vg-stop.sh")],
        input="{}", capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 2
    assert "UNHANDLED DIAGNOSTIC" in result.stderr or "vg.block" in result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_stop_hook_requires_block_handled_pair.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement hook**

```bash
cat > scripts/hooks/vg-stop.sh <<'HOOK'
#!/usr/bin/env bash
# Stop hook — verifies runtime contract + state machine + diagnostic pairing.

set -euo pipefail

session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
run_file=".vg/active-runs/${session_id}.json"

# No active VG run — no-op (don't block ordinary work).
if [ ! -f "$run_file" ]; then
  exit 0
fi

run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$run_file")"
command="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["command"])' "$run_file")"
db=".vg/events.db"

failures=()

# 1. Diagnostic pairing: vg.block.fired count must equal vg.block.handled count.
if [ -f "$db" ]; then
  fired="$(sqlite3 "$db" "SELECT COUNT(*) FROM events WHERE run_id='$run_id' AND event_type='vg.block.fired'" 2>/dev/null || echo 0)"
  handled="$(sqlite3 "$db" "SELECT COUNT(*) FROM events WHERE run_id='$run_id' AND event_type='vg.block.handled'" 2>/dev/null || echo 0)"
  if [ "$fired" -gt "$handled" ]; then
    unpaired="$(sqlite3 "$db" "SELECT payload FROM events WHERE run_id='$run_id' AND event_type='vg.block.fired'" 2>/dev/null)"
    failures+=("UNHANDLED DIAGNOSTIC: ${fired} blocks fired but only ${handled} handled. Open: ${unpaired}")
  fi
fi

# 2. State machine ordering check (best-effort — script may not have command sequence).
if [ -x "scripts/vg-state-machine-validator.py" ] && [ -f "$db" ]; then
  if ! python3 scripts/vg-state-machine-validator.py --db "$db" --command "$command" --run-id "$run_id" 2>/tmp/sm-err; then
    failures+=("STATE MACHINE: $(cat /tmp/sm-err)")
  fi
fi

# 3. Contract verify (delegated to existing vg-orchestrator if present).
if command -v vg-orchestrator >/dev/null 2>&1; then
  if ! vg-orchestrator run-status --check-contract "$run_id" >/tmp/contract-err 2>&1; then
    failures+=("CONTRACT: $(cat /tmp/contract-err)")
  fi
fi

if [ "${#failures[@]}" -gt 0 ]; then
  echo "═══════════════════════════════════════════" >&2
  echo "STOP BLOCKED — runtime contract incomplete for run ${run_id} (${command})" >&2
  echo "═══════════════════════════════════════════" >&2
  for f in "${failures[@]}"; do
    echo "  ✗ $f" >&2
  done
  echo "" >&2
  echo "Resolve each above before completing the run." >&2
  exit 2
fi

exit 0
HOOK
chmod +x scripts/hooks/vg-stop.sh
```

- [ ] **Step 4: Run test**

```bash
pytest scripts/tests/test_stop_hook_requires_block_handled_pair.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/hooks/vg-stop.sh scripts/tests/test_stop_hook_requires_block_handled_pair.py
git commit -m "feat(r1a): Stop hook verifies contract + state-machine + diagnostic pairing

(1) No-op if no active VG run. (2) Diagnostic pairing: vg.block.fired
count must equal vg.block.handled count. (3) State-machine validator
verifies event ORDER per command. (4) Contract verify via vg-orchestrator
if available. Failures → exit 2 with explicit list."
```

---

### Task 11: install-hooks.sh (idempotent merge into settings.json)

**Files:**
- Create: `scripts/hooks/install-hooks.sh`
- Test: `scripts/tests/test_install_hooks_idempotent.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_install_hooks_idempotent.py
import json, os, subprocess
from pathlib import Path


def test_install_creates_hooks_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".claude").mkdir()
    result = subprocess.run(
        ["bash", os.path.join(os.environ.get("OLDPWD", os.getcwd()),
                              "scripts/hooks/install-hooks.sh"),
         "--target", str(tmp_path / ".claude/settings.json")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    settings = json.loads((tmp_path / ".claude/settings.json").read_text())
    assert "hooks" in settings
    assert "PreToolUse" in settings["hooks"]
    assert "Stop" in settings["hooks"]
    assert "UserPromptSubmit" in settings["hooks"]


def test_install_idempotent_no_duplicates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".claude").mkdir()
    target = str(tmp_path / ".claude/settings.json")
    for _ in range(3):
        subprocess.run(
            ["bash", os.path.join(os.environ.get("OLDPWD", os.getcwd()),
                                  "scripts/hooks/install-hooks.sh"),
             "--target", target],
            check=True, capture_output=True,
        )
    settings = json.loads((tmp_path / ".claude/settings.json").read_text())
    pre = settings["hooks"]["PreToolUse"]
    bash_entries = [m for m in pre if m.get("matcher") == "Bash"]
    assert len(bash_entries) == 1, f"expected 1 Bash entry, got {len(bash_entries)}"


def test_install_preserves_existing_user_hooks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".claude").mkdir()
    target = tmp_path / ".claude/settings.json"
    target.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [
                {"matcher": "WebFetch", "hooks": [{"type": "command", "command": "echo user-hook"}]},
            ],
        },
    }))
    subprocess.run(
        ["bash", os.path.join(os.environ.get("OLDPWD", os.getcwd()),
                              "scripts/hooks/install-hooks.sh"),
         "--target", str(target)],
        check=True, capture_output=True,
    )
    settings = json.loads(target.read_text())
    matchers = [m.get("matcher") for m in settings["hooks"]["PreToolUse"]]
    assert "WebFetch" in matchers  # user hook preserved
    assert "Bash" in matchers  # VG hook added
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_install_hooks_idempotent.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement install script**

```bash
cat > scripts/hooks/install-hooks.sh <<'HOOK'
#!/usr/bin/env bash
# Idempotently merge VG hook entries into target Claude Code settings.json.
# Preserves user's existing hook entries.

set -euo pipefail

target=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target) target="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$target" ]; then
  echo "usage: install-hooks.sh --target <path-to-settings.json>" >&2
  exit 1
fi

PLUGIN_ROOT="${VG_PLUGIN_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/scripts/hooks"

python3 - "$target" "$HOOKS_DIR" <<'PY'
import json, os, sys
from pathlib import Path

target = Path(sys.argv[1])
hooks_dir = sys.argv[2]

if target.exists():
    settings = json.loads(target.read_text())
else:
    settings = {}
settings.setdefault("hooks", {})

VG_ENTRIES = {
    "UserPromptSubmit": [{"matcher": "", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-user-prompt-submit.sh"}]}],
    "SessionStart": [{"matcher": "startup|resume|clear|compact", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-session-start.sh"}]}],
    "PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-pre-tool-use-bash.sh"}]},
        {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-pre-tool-use-write.sh"}]},
        {"matcher": "Agent", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-pre-tool-use-agent.sh"}]},
    ],
    "PostToolUse": [{"matcher": "TodoWrite", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-post-tool-use-todowrite.sh"}]}],
    "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-stop.sh"}]}],
}

def signature(entry):
    cmds = [h.get("command", "") for h in entry.get("hooks", [])]
    return (entry.get("matcher", ""), tuple(sorted(cmds)))

def is_vg_hook(entry):
    return any("vg-" in h.get("command", "") for h in entry.get("hooks", []))

for event, vg_entries in VG_ENTRIES.items():
    existing = settings["hooks"].setdefault(event, [])
    # Remove any prior VG entries (so we re-install fresh, no duplicates).
    existing[:] = [e for e in existing if not is_vg_hook(e)]
    # Add VG entries fresh.
    existing.extend(vg_entries)

target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(settings, indent=2, sort_keys=True))
print(f"installed VG hooks into {target}")
PY
HOOK
chmod +x scripts/hooks/install-hooks.sh
```

- [ ] **Step 4: Run test**

```bash
pytest scripts/tests/test_install_hooks_idempotent.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/hooks/install-hooks.sh scripts/tests/test_install_hooks_idempotent.py
git commit -m "feat(r1a): install-hooks.sh idempotent merge into settings.json

Idempotent: re-running drops prior VG entries (signature: any 'vg-' in
command path) and re-adds fresh, preventing duplicates. Preserves
user's existing non-VG hook entries. Used by sync.sh to install
hooks into PrintwayV3 .claude/settings.json."
```

---

## Phase B — Blueprint-Specific Refactor (slim entry, refs, subagents)

### Task 12: Backup current blueprint.md + measure baseline

**Files:**
- Create: `commands/vg/.blueprint.md.r1a-backup` (rename of original)
- Modify: `commands/vg/blueprint.md` (will be replaced after refs created)

- [ ] **Step 1: Backup original**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp commands/vg/blueprint.md commands/vg/.blueprint.md.r1a-backup
wc -l commands/vg/.blueprint.md.r1a-backup
```
Expected: 3970 lines.

- [ ] **Step 2: Commit backup**

```bash
git add commands/vg/.blueprint.md.r1a-backup
git commit -m "chore(r1a): backup blueprint.md before slim refactor

Preserved as .blueprint.md.r1a-backup for diff/rollback during pilot."
```

---

### Task 13: Create `_shared/blueprint/preflight.md`

**Files:**
- Create: `commands/vg/_shared/blueprint/preflight.md`

- [ ] **Step 1: Create the reference file**

```bash
mkdir -p commands/vg/_shared/blueprint
cat > commands/vg/_shared/blueprint/preflight.md <<'REF'
# blueprint preflight (STEP 1)

Light steps: 0_design_discovery, 0_amendment_preflight, 1_parse_args,
create_task_tracker, 2_verify_prerequisites.

<HARD-GATE>
You MUST execute steps in this order. Each step finishes with a marker
touch. Skipping = Stop hook block.
</HARD-GATE>

## STEP 1.1 — design discovery (0_design_discovery)

Run discovery script:

```bash
python3 .claude/scripts/vg-design-discovery.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/0_design_discovery.done"
vg-orchestrator mark-step blueprint 0_design_discovery
```

## STEP 1.2 — amendment preflight (0_amendment_preflight)

Check for pending amendments:

```bash
if [ -f "${PHASE_DIR}/AMENDMENTS.md" ]; then
  python3 .claude/scripts/vg-check-amendments.py --phase ${PHASE_NUMBER}
fi
touch "${PHASE_DIR}/.step-markers/0_amendment_preflight.done"
vg-orchestrator mark-step blueprint 0_amendment_preflight
```

## STEP 1.3 — parse args (1_parse_args)

Parse the slash-command args ($ARGUMENTS). Extract:
- PHASE_NUMBER (positional)
- Flags: --skip-research, --gaps, --reviews, --text, --crossai-only,
  --skip-crossai, --from=<substep>, --override-reason=<text>, --apply-amendments

```bash
touch "${PHASE_DIR}/.step-markers/1_parse_args.done"
vg-orchestrator mark-step blueprint 1_parse_args
```

## STEP 1.4 — create task tracker (create_task_tracker)

Run the tasklist emitter:

```bash
python3 .claude/scripts/emit-tasklist.py \
  --command vg:blueprint \
  --profile $PROFILE \
  --phase ${PHASE_NUMBER}
```

This writes `.vg/runs/<run_id>/tasklist-contract.json`. THEN:

**You MUST IMMEDIATELY call TodoWrite with one item per checklist group from the contract.**
Use the JSON template printed by emit-tasklist.py output. Do NOT continue without TodoWrite.

After TodoWrite, the PostToolUse hook auto-writes signed evidence to
`.vg/runs/<run_id>/.tasklist-projected.evidence.json`.

```bash
touch "${PHASE_DIR}/.step-markers/create_task_tracker.done"
vg-orchestrator mark-step blueprint create_task_tracker
```

## STEP 1.5 — verify prerequisites (2_verify_prerequisites)

Verify CONTEXT.md exists, INTERFACE-STANDARDS template available, etc:

```bash
[ -f "${PHASE_DIR}/CONTEXT.md" ] || { echo "CONTEXT.md missing — run /vg:scope first"; exit 1; }
[ -f .vg/templates/INTERFACE-STANDARDS-template.md ] || { echo "interface template missing"; exit 1; }
touch "${PHASE_DIR}/.step-markers/2_verify_prerequisites.done"
vg-orchestrator mark-step blueprint 2_verify_prerequisites
```

After ALL 5 step markers touched, return to entry SKILL.md and proceed to STEP 2.
REF
wc -l commands/vg/_shared/blueprint/preflight.md
```
Expected: file exists, ≤300 lines.

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/blueprint/preflight.md
git commit -m "feat(r1a): blueprint preflight reference (5 light steps)

Step 1.1-1.5 spec: design discovery, amendment preflight, parse args,
create_task_tracker (with imperative TodoWrite call), prereq verify.
Each step touches marker + mark-step. Slim entry SKILL.md instructs
Read on this file."
```

---

### Task 14: Create `_shared/blueprint/design.md`

**Files:**
- Create: `commands/vg/_shared/blueprint/design.md`

- [ ] **Step 1: Create reference**

```bash
cat > commands/vg/_shared/blueprint/design.md <<'REF'
# blueprint design (STEP 2)

UI/design-related steps: 2_fidelity_profile_lock, 2b6c_view_decomposition,
2b6_ui_spec, 2b6b_ui_map. Profile-aware (web-fullstack, web-frontend-only).

<HARD-GATE>
For backend-only / cli-tool / library profiles, this STEP is SKIPPED via
profile branch. For web profiles, you MUST execute all 4 sub-steps.
</HARD-GATE>

## STEP 2.1 — fidelity profile lock (2_fidelity_profile_lock)

Lock the design fidelity profile (pixel-perfect | semantic | structural):

```bash
python3 .claude/scripts/vg-fidelity-lock.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2_fidelity_profile_lock.done"
vg-orchestrator mark-step blueprint 2_fidelity_profile_lock
```

## STEP 2.2 — view decomposition (2b6c_view_decomposition)

Decompose the phase into UI views (one per route/screen):

```bash
python3 .claude/scripts/vg-view-decompose.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2b6c_view_decomposition.done"
vg-orchestrator mark-step blueprint 2b6c_view_decomposition
```

## STEP 2.3 — UI spec (2b6_ui_spec)

Write per-view UI spec (component tree + interactions):

```bash
# AI generates UI-SPEC.md per template
[ -f "${PHASE_DIR}/UI-SPEC.md" ] || { echo "UI-SPEC.md missing"; exit 1; }
touch "${PHASE_DIR}/.step-markers/2b6_ui_spec.done"
vg-orchestrator mark-step blueprint 2b6_ui_spec
```

## STEP 2.4 — UI map (2b6b_ui_map)

Build mapping: view → component → state → API endpoint:

```bash
python3 .claude/scripts/vg-ui-map.py --phase ${PHASE_NUMBER}
[ -f "${PHASE_DIR}/UI-MAP.md" ] || { echo "UI-MAP.md missing"; exit 1; }
touch "${PHASE_DIR}/.step-markers/2b6b_ui_map.done"
vg-orchestrator mark-step blueprint 2b6b_ui_map
```

After all 4 markers touched, return to entry SKILL.md and proceed to STEP 3.
REF
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/blueprint/design.md
git commit -m "feat(r1a): blueprint design reference (4 UI steps)

STEP 2.1-2.4 spec: fidelity lock, view decompose, UI spec, UI map.
Profile-aware (skipped for backend-only/cli/library)."
```

---

### Task 15: Create `_shared/blueprint/plan-overview.md` + `plan-delegation.md`

**Files:**
- Create: `commands/vg/_shared/blueprint/plan-overview.md`
- Create: `commands/vg/_shared/blueprint/plan-delegation.md`

- [ ] **Step 1: Create both refs (FLAT structure per Codex fix #4)**

```bash
cat > commands/vg/_shared/blueprint/plan-overview.md <<'REF'
# blueprint plan group — STEP 3 overview

This is a HEAVY step (current spec ~673 lines). You MUST delegate to the
`vg-blueprint-planner` subagent (tool name `Agent`, NOT `Task`).

<HARD-GATE>
You MUST spawn `vg-blueprint-planner` for step 2a_plan.
You MUST NOT generate PLAN.md inline.
</HARD-GATE>

## How to spawn

1. `vg-orchestrator step-active 2a_plan`
2. Read `plan-delegation.md` for exact input/output contract.
3. Call `Agent(subagent_type="vg-blueprint-planner", prompt=<as defined in delegation.md>)`
4. On return, validate `path` + `sha256` of returned PLAN.md.
5. Touch marker + `vg-orchestrator mark-step blueprint 2a_plan`.
6. Emit telemetry: `vg-orchestrator emit-event blueprint.plan_written`.

The PreToolUse Bash hook will block step 5/6 if step 1 was not preceded by
TodoWrite (signed evidence required).
REF

cat > commands/vg/_shared/blueprint/plan-delegation.md <<'REF'
# blueprint plan delegation contract (vg-blueprint-planner subagent)

## Input

Pass to `Agent(subagent_type="vg-blueprint-planner", prompt={...})`:

```json
{
  "phase_dir": "${PHASE_DIR}",
  "context_path": "${PHASE_DIR}/CONTEXT.md",
  "interface_standards_path": "${PHASE_DIR}/INTERFACE-STANDARDS.md",
  "design_refs": [
    "${PHASE_DIR}/UI-SPEC.md",
    "${PHASE_DIR}/UI-MAP.md"
  ],
  "must_cite_bindings": [
    "CONTEXT:decisions",
    "INTERFACE-STANDARDS:error-shape"
  ]
}
```

## Output (subagent returns)

```json
{
  "path": "${PHASE_DIR}/PLAN.md",
  "sha256": "<hex sha256 of PLAN.md contents>",
  "summary": "<one paragraph summary of plan structure>",
  "bindings_satisfied": ["CONTEXT:decisions", "INTERFACE-STANDARDS:error-shape"],
  "warnings": []
}
```

## Main agent post-spawn validation

1. Open returned `path`, recompute sha256, assert match.
2. Confirm PLAN.md ≥ 500 bytes (content_min_bytes).
3. Confirm `bindings_satisfied` covers required `must_cite_bindings`.
4. If validation fails, retry up to 2 times, then escalate AskUserQuestion.

## Failure mode

If subagent returns error JSON (missing input, ORG 6-dim violation, etc.),
do NOT mark step done. Re-spawn after fixing input.
REF
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/blueprint/plan-overview.md commands/vg/_shared/blueprint/plan-delegation.md
git commit -m "feat(r1a): blueprint plan refs (FLAT structure, Codex fix #4)

plan-overview.md: STEP 3 entry, instructs spawning vg-blueprint-planner.
plan-delegation.md: input/output contract for the subagent.
NO nested directory — kept FLAT per Anthropic 1-level guidance."
```

---

### Task 16: Create `_shared/blueprint/contracts-overview.md` + `contracts-delegation.md`

**Files:**
- Create: `commands/vg/_shared/blueprint/contracts-overview.md`
- Create: `commands/vg/_shared/blueprint/contracts-delegation.md`

- [ ] **Step 1: Create both refs**

```bash
cat > commands/vg/_shared/blueprint/contracts-overview.md <<'REF'
# blueprint contracts group — STEP 4 overview

HEAVY step. You MUST delegate to `vg-blueprint-contracts` subagent.

<HARD-GATE>
You MUST spawn `vg-blueprint-contracts` for steps 2b_contracts +
2b5_test_goals + 2b5a_codex_test_goal_lane.
You MUST NOT generate API-CONTRACTS.md inline.
</HARD-GATE>

## How to spawn

1. `vg-orchestrator step-active 2b_contracts`
2. Read `contracts-delegation.md` for input/output contract.
3. Call `Agent(subagent_type="vg-blueprint-contracts", prompt=<as defined>)`.
4. Validate returned API-CONTRACTS.md + INTERFACE-STANDARDS.{md,json}
   + TEST-GOALS.md + (optional) TEST-GOALS.codex-proposal.md.
5. Touch markers for each step + `vg-orchestrator mark-step blueprint <step>`.
6. Emit telemetry: `vg-orchestrator emit-event blueprint.contracts_generated`.
REF

cat > commands/vg/_shared/blueprint/contracts-delegation.md <<'REF'
# blueprint contracts delegation contract (vg-blueprint-contracts subagent)

## Input

```json
{
  "phase_dir": "${PHASE_DIR}",
  "plan_path": "${PHASE_DIR}/PLAN.md",
  "context_path": "${PHASE_DIR}/CONTEXT.md",
  "ui_map_path": "${PHASE_DIR}/UI-MAP.md",
  "must_cite_bindings": [
    "PLAN:tasks",
    "INTERFACE-STANDARDS:error-shape",
    "INTERFACE-STANDARDS:response-envelope"
  ],
  "include_codex_lane": true
}
```

## Output

```json
{
  "api_contracts_path": "${PHASE_DIR}/API-CONTRACTS.md",
  "api_contracts_sha256": "<hex>",
  "interface_md_path": "${PHASE_DIR}/INTERFACE-STANDARDS.md",
  "interface_json_path": "${PHASE_DIR}/INTERFACE-STANDARDS.json",
  "test_goals_path": "${PHASE_DIR}/TEST-GOALS.md",
  "codex_proposal_path": "${PHASE_DIR}/TEST-GOALS.codex-proposal.md",
  "codex_delta_path": "${PHASE_DIR}/TEST-GOALS.codex-delta.md",
  "crud_surfaces_path": "${PHASE_DIR}/CRUD-SURFACES.md",
  "summary": "<one paragraph>",
  "bindings_satisfied": ["PLAN:tasks", "INTERFACE-STANDARDS:error-shape", ...],
  "warnings": []
}
```

## Main agent post-spawn validation

1. Each path exists with content_min_bytes per blueprint.md frontmatter
   (API-CONTRACTS.md no min, codex-proposal ≥ 40 bytes, codex-delta ≥ 80,
   CRUD-SURFACES.md ≥ 120 unless --crossai-only).
2. Recompute sha256 of API-CONTRACTS.md, assert match.
3. Confirm bindings_satisfied covers must_cite.
4. Failure → retry 2× then AskUserQuestion.
REF
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/blueprint/contracts-overview.md commands/vg/_shared/blueprint/contracts-delegation.md
git commit -m "feat(r1a): blueprint contracts refs (FLAT structure)

contracts-overview.md: STEP 4 entry, spawn vg-blueprint-contracts.
contracts-delegation.md: produces API-CONTRACTS.md + INTERFACE-STANDARDS
+ TEST-GOALS + Codex proposal/delta + CRUD-SURFACES."
```

---

### Task 17: Create `_shared/blueprint/verify.md`

**Files:**
- Create: `commands/vg/_shared/blueprint/verify.md`

- [ ] **Step 1: Create reference**

```bash
cat > commands/vg/_shared/blueprint/verify.md <<'REF'
# blueprint verify (STEP 5)

7 verify steps. Pure grep/path checks — fast, no AI required for the verify
itself. AI orchestrates the bash calls.

<HARD-GATE>
ALL 7 verify steps MUST execute. Each must touch its marker.
</HARD-GATE>

## STEP 5.1 — grep verify (2c_verify)

```bash
python3 .claude/scripts/vg-grep-verify.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2c_verify.done"
vg-orchestrator mark-step blueprint 2c_verify
```

## STEP 5.2 — path verify (2c_verify_plan_paths)

```bash
python3 .claude/scripts/vg-verify-plan-paths.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2c_verify_plan_paths.done"
vg-orchestrator mark-step blueprint 2c_verify_plan_paths
```

## STEP 5.3 — utility reuse (2c_utility_reuse)

```bash
python3 .claude/scripts/vg-utility-reuse-check.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2c_utility_reuse.done"
vg-orchestrator mark-step blueprint 2c_utility_reuse
```

## STEP 5.4 — compile check (2c_compile_check)

```bash
python3 .claude/scripts/vg-compile-check.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2c_compile_check.done"
vg-orchestrator mark-step blueprint 2c_compile_check
```

## STEP 5.5 — validation gate (2d_validation_gate)

```bash
python3 .claude/scripts/vg-validation-gate.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2d_validation_gate.done"
vg-orchestrator mark-step blueprint 2d_validation_gate
```

## STEP 5.6 — test type coverage (2d_test_type_coverage)

```bash
python3 .claude/scripts/vg-test-type-coverage.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2d_test_type_coverage.done"
vg-orchestrator mark-step blueprint 2d_test_type_coverage
```

## STEP 5.7 — goal grounding (2d_goal_grounding)

```bash
python3 .claude/scripts/vg-goal-grounding.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2d_goal_grounding.done"
vg-orchestrator mark-step blueprint 2d_goal_grounding
```

After all 7 markers, return to entry SKILL.md → STEP 6.
REF
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/blueprint/verify.md
git commit -m "feat(r1a): blueprint verify reference (7 grep/path checks)"
```

---

### Task 18: Create `_shared/blueprint/close.md`

**Files:**
- Create: `commands/vg/_shared/blueprint/close.md`

- [ ] **Step 1: Create reference**

```bash
cat > commands/vg/_shared/blueprint/close.md <<'REF'
# blueprint close (STEP 6)

Final 2 steps: bootstrap reflection + run-complete.

## STEP 6.1 — bootstrap reflection (2e_bootstrap_reflection)

Spawn the existing vg-reflector skill via the Skill tool:

```
Skill(skill="vg-reflector", args="--phase ${PHASE_NUMBER} --command vg:blueprint")
```

Then:

```bash
touch "${PHASE_DIR}/.step-markers/2e_bootstrap_reflection.done"
vg-orchestrator mark-step blueprint 2e_bootstrap_reflection
```

## STEP 6.2 — run complete (3_complete)

Final marker + emit completion event:

```bash
vg-orchestrator emit-event blueprint.completed --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/3_complete.done"
vg-orchestrator mark-step blueprint 3_complete
vg-orchestrator run-complete
```

The Stop hook will then verify:
- All `must_write` artifacts present + content_min_bytes met
- All `must_emit_telemetry` events present
- All `must_touch_markers` touched
- vg.block.fired count == vg.block.handled count
- State machine ordering valid

If any fails → exit 2 + diagnostic. Else → run successful.

## Update tasklist (close-on-complete)

Mark all checklist items completed via TodoWrite. Then either clear the
list (preferred) or replace with one sentinel: "vg:blueprint phase ${PHASE_NUMBER} complete".
REF
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/blueprint/close.md
git commit -m "feat(r1a): blueprint close reference (reflection + run-complete + tasklist clear)"
```

---

### Task 19: Create `vg-blueprint-planner` subagent SKILL.md

**Files:**
- Create: `agents/vg-blueprint-planner/SKILL.md`

- [ ] **Step 1: Create the subagent definition**

```bash
mkdir -p agents/vg-blueprint-planner
cat > agents/vg-blueprint-planner/SKILL.md <<'SKILL'
---
name: vg-blueprint-planner
description: Generate PLAN.md for one phase. Input: phase context. Output: PLAN.md path + sha256 + summary + bindings_satisfied. ONLY this task.
tools: [Read, Write, Bash, Grep]
model: opus
---

<HARD-GATE>
You are a planner. Your ONLY output is PLAN.md plus a JSON return.
Return JSON: { "path", "sha256", "summary", "bindings_satisfied", "warnings" }.
You MUST NOT browse files outside your input.
You MUST NOT modify files except writing PLAN.md.
You MUST NOT ask the user questions — your input is the contract.
</HARD-GATE>

## Input contract (from main agent)

- `phase_dir` — phase directory (e.g., .vg/phases/01-foo)
- `context_path` — CONTEXT.md to draw decisions from
- `interface_standards_path` — INTERFACE-STANDARDS.md
- `design_refs` — array of design ref paths (UI-SPEC, UI-MAP, etc.)
- `must_cite_bindings` — IDs you MUST satisfy in PLAN.md text

## Steps

1. Read all input paths.
2. Apply ORG 6-dimension framework: Infra, Env, Deploy, Smoke, Integration, Rollback.
3. Generate PLAN.md per project template (path: `<phase_dir>/PLAN.md`).
4. PLAN.md MUST contain `<!-- vg-binding: <id> -->` comments for each citation
   in `must_cite_bindings`.
5. Compute `sha256sum <phase_dir>/PLAN.md`.
6. Return JSON to main agent.

## Failure modes

- Missing input → return `{"error": "missing_input", "field": "<name>"}` and exit.
- Cannot satisfy ORG 6-dim → return `{"error": "org_6dim_incomplete", "missing": [...]}`.
- Cannot satisfy must_cite_bindings → return `{"error": "binding_unmet", "missing": [...]}`.
- Do NOT write a partial PLAN.md on error.

## Example return

```json
{
  "path": ".vg/phases/01-foo/PLAN.md",
  "sha256": "abc123...",
  "summary": "Plan covers 5 tasks across 3 waves: backend models, FE pages, integration.",
  "bindings_satisfied": ["CONTEXT:decisions", "INTERFACE-STANDARDS:error-shape"],
  "warnings": []
}
```
SKILL
```

- [ ] **Step 2: Commit**

```bash
git add agents/vg-blueprint-planner/SKILL.md
git commit -m "feat(r1a): vg-blueprint-planner subagent definition

Narrow tools (Read/Write/Bash/Grep, NO Edit, NO AskUserQuestion, NO Task).
HARD-GATE: only output PLAN.md, return JSON contract. ORG 6-dim framework
plus mandatory binding citations as <!-- vg-binding: --> comments."
```

---

### Task 20: Create `vg-blueprint-contracts` subagent SKILL.md

**Files:**
- Create: `agents/vg-blueprint-contracts/SKILL.md`

- [ ] **Step 1: Create the subagent definition**

```bash
mkdir -p agents/vg-blueprint-contracts
cat > agents/vg-blueprint-contracts/SKILL.md <<'SKILL'
---
name: vg-blueprint-contracts
description: Generate API-CONTRACTS.md + INTERFACE-STANDARDS.{md,json} + TEST-GOALS.md + Codex proposal/delta + CRUD-SURFACES.md for a phase. ONLY this task.
tools: [Read, Write, Bash, Grep]
model: opus
---

<HARD-GATE>
You are a contracts generator. Your ONLY outputs are the listed contract
files plus a JSON return.
You MUST NOT modify other files.
You MUST NOT ask user questions.
</HARD-GATE>

## Input contract

- `phase_dir`
- `plan_path`
- `context_path`
- `ui_map_path` (optional)
- `must_cite_bindings`
- `include_codex_lane` (bool, default true)

## Required outputs (paths under `phase_dir`)

| File | Min bytes | Notes |
|---|---|---|
| API-CONTRACTS.md | (no min) | endpoints + request/response shapes |
| INTERFACE-STANDARDS.md | 500 | response/error envelope rules |
| INTERFACE-STANDARDS.json | 500 | machine-readable schema |
| TEST-GOALS.md | (no min) | one G-XX per acceptance criterion |
| TEST-GOALS.codex-proposal.md | 40 | only if `include_codex_lane=true` |
| TEST-GOALS.codex-delta.md | 80 | only if `include_codex_lane=true` |
| CRUD-SURFACES.md | 120 | resource × operation matrix |

Each output file MUST contain `<!-- vg-binding: <id> -->` comments matching
`must_cite_bindings`.

## Steps

1. Read PLAN.md, CONTEXT.md, INTERFACE-STANDARDS template.
2. Derive endpoints from PLAN tasks; write API-CONTRACTS.md.
3. Write INTERFACE-STANDARDS.md + .json (response envelope, error shape, error codes).
4. Write TEST-GOALS.md (one G-XX per task acceptance criterion).
5. If `include_codex_lane`: invoke Codex lane via existing helper:
   `bash scripts/vg-codex-test-goal-lane.sh --phase <num>`.
   This produces both `.codex-proposal.md` and `.codex-delta.md`.
6. Write CRUD-SURFACES.md from PLAN tasks (resource × CRUD op matrix).
7. Compute sha256 for API-CONTRACTS.md, return JSON.

## Failure modes

- Missing input → `{"error": "missing_input", "field": "<name>"}`.
- Codex lane fails → return success with `warnings: ["codex_lane_failed: <stderr>"]`,
  do NOT fail outright (codex lane is optional unless --skip-codex-test-goal-lane absent).
- Binding unmet → `{"error": "binding_unmet", "missing": [...]}`.

## Example return

```json
{
  "api_contracts_path": ".vg/phases/01-foo/API-CONTRACTS.md",
  "api_contracts_sha256": "abc123...",
  "interface_md_path": ".vg/phases/01-foo/INTERFACE-STANDARDS.md",
  "interface_json_path": ".vg/phases/01-foo/INTERFACE-STANDARDS.json",
  "test_goals_path": ".vg/phases/01-foo/TEST-GOALS.md",
  "codex_proposal_path": ".vg/phases/01-foo/TEST-GOALS.codex-proposal.md",
  "codex_delta_path": ".vg/phases/01-foo/TEST-GOALS.codex-delta.md",
  "crud_surfaces_path": ".vg/phases/01-foo/CRUD-SURFACES.md",
  "summary": "Generated 8 endpoints across 4 resources, 12 G-XX test goals, 4 CRUD surfaces.",
  "bindings_satisfied": ["PLAN:tasks", "INTERFACE-STANDARDS:error-shape"],
  "warnings": []
}
```
SKILL
```

- [ ] **Step 2: Commit**

```bash
git add agents/vg-blueprint-contracts/SKILL.md
git commit -m "feat(r1a): vg-blueprint-contracts subagent definition

Generates 7 contract files (API-CONTRACTS, INTERFACE-STANDARDS md+json,
TEST-GOALS, codex proposal/delta, CRUD-SURFACES). Narrow tools, JSON
return. Mandatory binding citation comments."
```

---

### Task 21: Replace blueprint.md body with slim entry

**Files:**
- Modify: `commands/vg/blueprint.md` (full rewrite)

- [ ] **Step 1: Write failing static-test for slim size**

```python
# scripts/tests/test_blueprint_slim_size.py
from pathlib import Path

def test_blueprint_slim():
    path = Path("commands/vg/blueprint.md")
    lines = path.read_text().splitlines()
    assert len(lines) <= 600, f"blueprint.md exceeds 600 lines (got {len(lines)})"


def test_blueprint_imperative_language():
    path = Path("commands/vg/blueprint.md")
    body = path.read_text()
    # Must have HARD-GATE
    assert "<HARD-GATE>" in body
    # Must have Red Flags
    assert "Red Flags" in body
    # Imperative markers required
    assert "MUST" in body
    assert "STEP 1" in body
    # No descriptive language in instruction context (sample patterns)
    forbidden_in_imperative = [" should call ", " may call ", " will call "]
    for phrase in forbidden_in_imperative:
        assert phrase not in body.lower(), f"forbidden descriptive phrase: '{phrase}'"


def test_blueprint_refs_listed_directly():
    path = Path("commands/vg/blueprint.md")
    body = path.read_text()
    # Each step must directly reference a leaf ref (not nested overview chain)
    expected_refs = [
        "_shared/blueprint/preflight.md",
        "_shared/blueprint/design.md",
        "_shared/blueprint/plan-overview.md",
        "_shared/blueprint/plan-delegation.md",
        "_shared/blueprint/contracts-overview.md",
        "_shared/blueprint/contracts-delegation.md",
        "_shared/blueprint/verify.md",
        "_shared/blueprint/close.md",
    ]
    for ref in expected_refs:
        assert ref in body, f"entry SKILL.md must directly list leaf ref: {ref}"
```

- [ ] **Step 2: Run test to verify it fails (current blueprint.md is 3970 lines)**

```bash
pytest scripts/tests/test_blueprint_slim_size.py -v
```
Expected: FAIL — line count exceeds 600.

- [ ] **Step 3: Replace blueprint.md with slim entry**

```bash
cat > commands/vg/blueprint.md <<'BLUEPRINT'
---
name: vg:blueprint
description: Plan + API contracts + verify + CrossAI review — 4 sub-steps before build
argument-hint: "<phase> [--skip-research] [--gaps] [--reviews] [--text] [--crossai-only] [--skip-crossai] [--from=<substep>] [--override-reason=<text>] [--apply-amendments]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Agent
  - TodoWrite
runtime_contract:
  must_write:
    - "${PHASE_DIR}/PLAN.md"
    - "${PHASE_DIR}/INTERFACE-STANDARDS.md"
    - "${PHASE_DIR}/INTERFACE-STANDARDS.json"
    - "${PHASE_DIR}/API-CONTRACTS.md"
    - "${PHASE_DIR}/TEST-GOALS.md"
    - path: "${PHASE_DIR}/TEST-GOALS.codex-proposal.md"
      content_min_bytes: 40
      required_unless_flag: "--skip-codex-test-goal-lane"
    - path: "${PHASE_DIR}/TEST-GOALS.codex-delta.md"
      content_min_bytes: 80
      required_unless_flag: "--skip-codex-test-goal-lane"
    - path: "${PHASE_DIR}/CRUD-SURFACES.md"
      content_min_bytes: 120
      required_unless_flag: "--crossai-only"
    - path: "${PHASE_DIR}/crossai/result-*.xml"
      glob_min_count: 1
      required_unless_flag: "--skip-crossai"
  must_touch_markers:
    - "0_design_discovery"
    - "0_amendment_preflight"
    - "1_parse_args"
    - "create_task_tracker"
    - "2_verify_prerequisites"
    - "2_fidelity_profile_lock"
    - "2b6c_view_decomposition"
    - "2b6_ui_spec"
    - "2b6b_ui_map"
    - "2a_plan"
    - "2b_contracts"
    - "2b5_test_goals"
    - name: "2b5a_codex_test_goal_lane"
      required_unless_flag: "--skip-codex-test-goal-lane"
    - "2c_verify"
    - "2c_verify_plan_paths"
    - "2c_utility_reuse"
    - "2c_compile_check"
    - "2d_validation_gate"
    - "2d_test_type_coverage"
    - "2d_goal_grounding"
    - name: "2d_crossai_review"
      required_unless_flag: "--skip-crossai"
    - "2e_bootstrap_reflection"
    - "3_complete"
  must_emit_telemetry:
    - event_type: "blueprint.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "blueprint.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "blueprint.plan_written"
      phase: "${PHASE_NUMBER}"
    - event_type: "blueprint.contracts_generated"
      phase: "${PHASE_NUMBER}"
    - event_type: "crossai.verdict"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-crossai"
    - event_type: "blueprint.completed"
      phase: "${PHASE_NUMBER}"
  forbidden_without_override:
    - "--skip-crossai"
    - "--skip-codex-test-goal-lane"
    - "--override-reason"
---

<HARD-GATE>
You MUST follow STEP 1 through STEP 6 in exact order. Each step is gated
by hooks. Skipping ANY step will be blocked by PreToolUse + Stop hooks.
You CANNOT rationalize past these gates.

You MUST call TodoWrite IMMEDIATELY after STEP 1.4 (create_task_tracker)
runs emit-tasklist.py — DO NOT continue without it. The PreToolUse Bash
hook will block all subsequent step-active calls until signed evidence
exists.

For HEAVY steps (STEP 3, STEP 4), you MUST spawn the named subagent via
the `Agent` tool (NOT `Task` — Codex confirmed correct tool name per
Claude Code docs). DO NOT generate PLAN.md or API-CONTRACTS.md inline.
</HARD-GATE>

## Red Flags (do not rationalize)

| Thought | Reality |
|---|---|
| "Tasklist không quan trọng, để sau" | PreToolUse Bash hook BLOCKS step-active without signed evidence |
| "Step này đơn giản, bỏ qua" | Marker thiếu = Stop hook fail = run cannot complete |
| "Subagent overkill cho step nặng" | Heavy step empirical 96.5% skip rate without subagent (Codex review confirmed) |
| "Tôi đã hiểu, không cần đọc reference" | Reference contains step-specific bash commands not in entry |
| "TodoWrite gọi sau cũng được" | Layer 2 diagnostic: PreToolUse blocks subsequent tool calls |
| "Write evidence file trực tiếp cho nhanh" | PreToolUse Write hook blocks protected paths (Codex fix #2) |
| "Spawn Task() như cũ" | Tool name is `Agent`, not `Task` (Codex fix #3) |
| "Block message bỏ qua, retry là xong" | §4.5 Layer 2: vg.block.fired must pair with vg.block.handled or Stop blocks |

## Steps (6 checklist groups)

### STEP 1 — preflight
Read `_shared/blueprint/preflight.md` and follow it exactly.
This step includes the IMPERATIVE TodoWrite call after emit-tasklist.py.

### STEP 2 — design (skipped for backend-only / cli-tool / library profiles)
Read `_shared/blueprint/design.md` and follow it exactly.

### STEP 3 — plan (HEAVY)
Read `_shared/blueprint/plan-overview.md` AND `_shared/blueprint/plan-delegation.md`.
Then call `Agent(subagent_type="vg-blueprint-planner", prompt=<from delegation>)`.
DO NOT plan inline.

### STEP 4 — contracts (HEAVY)
Read `_shared/blueprint/contracts-overview.md` AND `_shared/blueprint/contracts-delegation.md`.
Then call `Agent(subagent_type="vg-blueprint-contracts", prompt=<from delegation>)`.
DO NOT generate contracts inline.

### STEP 5 — verify (7 grep/path checks)
Read `_shared/blueprint/verify.md` and follow it exactly.

### STEP 6 — close (reflection + run-complete + tasklist clear)
Read `_shared/blueprint/close.md` and follow it exactly.

## Diagnostic flow (5 layers — see vg-meta-skill.md)

If any tool call is blocked by a hook:
1. Read the stderr DIAGNOSTIC REQUIRED prompt (Layer 1 format).
2. Tell the user using the narrative template inside the message (Layer 5).
3. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`.
4. Apply the REQUIRED FIX described in the prompt.
5. Retry the original tool call.

After ≥3 blocks on the same gate, you MUST call AskUserQuestion (Layer 3 escalation).
After context compaction, SessionStart hook re-injects open diagnostics (Layer 4).
BLUEPRINT
```

- [ ] **Step 4: Run static tests**

```bash
pytest scripts/tests/test_blueprint_slim_size.py -v
wc -l commands/vg/blueprint.md
```
Expected: 3 PASSED. Line count ≤500.

- [ ] **Step 5: Commit**

```bash
git add commands/vg/blueprint.md scripts/tests/test_blueprint_slim_size.py
git commit -m "refactor(r1a): blueprint.md slim entry (3970 → ~250 lines)

Frontmatter preserved (Stop hook authority). Body replaced with HARD-GATE
+ Red Flags + 6-step routing to flat refs in _shared/blueprint/. Tool
name 'Agent' used (Codex fix #3). All 23 markers + 6 telemetry events +
4 forbidden-without-override flags carried over.

Static tests added: slim_size (≤600), imperative_language (MUST/STEP X,
no should/may/will), refs_listed_directly (8 leaf refs in entry)."
```

---

## Phase C — Subagent + Reference Tests

### Task 22: Static test for subagents + flat refs

**Files:**
- Create: `scripts/tests/test_subagent_definitions_exist.py`
- Create: `scripts/tests/test_blueprint_references_exist.py`
- Create: `scripts/tests/test_blueprint_refs_flat_structure.py`

- [ ] **Step 1: Write tests**

```python
# scripts/tests/test_subagent_definitions_exist.py
import yaml
from pathlib import Path


def _frontmatter(path: Path) -> dict:
    body = path.read_text()
    assert body.startswith("---\n"), f"{path} missing YAML frontmatter"
    end = body.index("\n---\n", 4)
    return yaml.safe_load(body[4:end])


def test_planner_subagent():
    fm = _frontmatter(Path("agents/vg-blueprint-planner/SKILL.md"))
    assert fm["name"] == "vg-blueprint-planner"
    assert fm["model"] == "opus"
    assert set(fm["tools"]) == {"Read", "Write", "Bash", "Grep"}


def test_contracts_subagent():
    fm = _frontmatter(Path("agents/vg-blueprint-contracts/SKILL.md"))
    assert fm["name"] == "vg-blueprint-contracts"
    assert fm["model"] == "opus"
    assert set(fm["tools"]) == {"Read", "Write", "Bash", "Grep"}
```

```python
# scripts/tests/test_blueprint_references_exist.py
from pathlib import Path

REFS = [
    "preflight.md",
    "design.md",
    "plan-overview.md",
    "plan-delegation.md",
    "contracts-overview.md",
    "contracts-delegation.md",
    "verify.md",
    "close.md",
]


def test_all_blueprint_refs_exist():
    base = Path("commands/vg/_shared/blueprint")
    for ref in REFS:
        p = base / ref
        assert p.exists(), f"missing ref: {p}"
        assert p.stat().st_size > 100, f"ref {p} too small ({p.stat().st_size} bytes)"
        # Each ref ≤500 lines (Anthropic ceiling)
        lines = p.read_text().splitlines()
        assert len(lines) <= 500, f"ref {p} exceeds 500 lines (got {len(lines)})"
```

```python
# scripts/tests/test_blueprint_refs_flat_structure.py
from pathlib import Path


def test_no_nested_subdirs():
    base = Path("commands/vg/_shared/blueprint")
    for child in base.iterdir():
        assert not child.is_dir(), (
            f"nested subdir found: {child} — Codex fix #4 requires FLAT structure "
            f"(1-level refs, no plan/overview.md chains)"
        )
```

- [ ] **Step 2: Run tests**

```bash
pytest scripts/tests/test_subagent_definitions_exist.py \
       scripts/tests/test_blueprint_references_exist.py \
       scripts/tests/test_blueprint_refs_flat_structure.py -v
```
Expected: ALL PASSED.

- [ ] **Step 3: Commit**

```bash
git add scripts/tests/test_subagent_definitions_exist.py \
        scripts/tests/test_blueprint_references_exist.py \
        scripts/tests/test_blueprint_refs_flat_structure.py
git commit -m "test(r1a): static checks for subagents + flat ref structure

Subagents: frontmatter valid, model=opus, narrow tools whitelist.
Refs: all 8 exist, ≥100 bytes, ≤500 lines (Anthropic ceiling).
Flat structure: no nested subdirs (Codex fix #4)."
```

---

### Task 23: Hook scripts executable test

**Files:**
- Create: `scripts/tests/test_hook_scripts_executable.py`

- [ ] **Step 1: Write test**

```python
# scripts/tests/test_hook_scripts_executable.py
import os
from pathlib import Path

HOOKS = [
    "scripts/hooks/vg-user-prompt-submit.sh",
    "scripts/hooks/vg-session-start.sh",
    "scripts/hooks/vg-pre-tool-use-bash.sh",
    "scripts/hooks/vg-pre-tool-use-write.sh",
    "scripts/hooks/vg-pre-tool-use-agent.sh",
    "scripts/hooks/vg-post-tool-use-todowrite.sh",
    "scripts/hooks/vg-stop.sh",
    "scripts/hooks/install-hooks.sh",
]


def test_all_hooks_executable():
    for path in HOOKS:
        p = Path(path)
        assert p.exists(), f"missing hook: {path}"
        assert os.access(str(p), os.X_OK), f"hook not executable: {path}"


def test_helpers_executable():
    for path in ["scripts/vg-orchestrator-emit-evidence-signed.py",
                 "scripts/vg-state-machine-validator.py"]:
        p = Path(path)
        assert p.exists()
        assert os.access(str(p), os.X_OK), f"helper not executable: {path}"
```

- [ ] **Step 2: Run test**

```bash
pytest scripts/tests/test_hook_scripts_executable.py -v
```
Expected: 2 PASSED.

- [ ] **Step 3: Commit**

```bash
git add scripts/tests/test_hook_scripts_executable.py
git commit -m "test(r1a): all hook scripts + helpers have +x bit"
```

---

## Phase D — Sync + Dogfood

### Task 24: Update sync.sh to copy hooks + agents

**Files:**
- Modify: `sync.sh`

- [ ] **Step 1: Inspect current sync.sh**

```bash
grep -n "scripts/hooks\|agents/" sync.sh | head -20
```
If hooks/agents not currently synced, proceed to step 2.

- [ ] **Step 2: Add hook + agent sync logic**

Edit `sync.sh` to include after the existing scripts/ rsync block:

```bash
# Sync VG hook scripts (R1a pilot)
if [ -d "$DEV_ROOT/.claude/scripts/hooks" ] || [ -d "$REPO_ROOT/scripts/hooks" ]; then
  mkdir -p "$DEV_ROOT/.claude/scripts/hooks"
  rsync -a "$REPO_ROOT/scripts/hooks/" "$DEV_ROOT/.claude/scripts/hooks/"
  echo "✓ synced hooks → .claude/scripts/hooks/"
fi

# Sync VG custom agents (R1a pilot)
if [ -d "$REPO_ROOT/agents" ]; then
  mkdir -p "$DEV_ROOT/.claude/agents"
  rsync -a "$REPO_ROOT/agents/" "$DEV_ROOT/.claude/agents/"
  echo "✓ synced agents → .claude/agents/"
fi

# Install hooks into .claude/settings.json (idempotent)
if [ "${VG_INSTALL_HOOKS:-1}" = "1" ]; then
  bash "$REPO_ROOT/scripts/hooks/install-hooks.sh" \
    --target "$DEV_ROOT/.claude/settings.json"
fi
```

- [ ] **Step 3: Run sync.sh check (no DEV_ROOT, just verify script parses)**

```bash
bash -n sync.sh && echo "sync.sh syntax ok"
```
Expected: `sync.sh syntax ok`.

- [ ] **Step 4: Commit**

```bash
git add sync.sh
git commit -m "feat(r1a): sync.sh copies hooks + agents + installs settings

Adds rsync of scripts/hooks/ → .claude/scripts/hooks/ and agents/ →
.claude/agents/ in sync.sh. Then runs install-hooks.sh to merge VG hook
entries into target .claude/settings.json (idempotent). Disable with
VG_INSTALL_HOOKS=0 if user manages hooks manually."
```

---

### Task 25: Run full pytest suite (regression check)

**Files:** none — verify only.

- [ ] **Step 1: Run all VG tests**

```bash
pytest -q scripts/tests/ 2>&1 | tail -20
```
Expected: All tests pass. Existing 138 tests + new R1a tests should sum to ~150+, 0 failures.

If any prior test fails, investigate — should not happen since R1a only adds new files (no edits to existing test paths). If a prior test fails, debug before proceeding.

- [ ] **Step 2: Commit any test fixes**

If fixes needed:
```bash
git add scripts/tests/
git commit -m "test(r1a): align prior tests with R1a additions"
```

If no fixes needed, proceed.

---

### Task 26: Sync to PrintwayV3 + verify install

**Files:** none — operational.

- [ ] **Step 1: Generate evidence key (one-time)**

```bash
PRINTWAY="/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
mkdir -p "$PRINTWAY/.vg"
if [ ! -f "$PRINTWAY/.vg/.evidence-key" ]; then
  openssl rand -base64 32 > "$PRINTWAY/.vg/.evidence-key"
  chmod 600 "$PRINTWAY/.vg/.evidence-key"
  echo ".vg/.evidence-key" >> "$PRINTWAY/.gitignore" || true
fi
```

- [ ] **Step 2: Sync via sync.sh**

```bash
DEV_ROOT="$PRINTWAY" ./sync.sh --no-global
```
Expected: prints "synced hooks", "synced agents", "installed VG hooks".

- [ ] **Step 3: Verify install**

```bash
ls "$PRINTWAY/.claude/scripts/hooks/" | head
ls "$PRINTWAY/.claude/agents/"
python3 -c "import json; print(json.dumps(json.load(open('$PRINTWAY/.claude/settings.json')).get('hooks', {}).keys() | list(), indent=2))" 2>/dev/null || cat "$PRINTWAY/.claude/settings.json" | head -30
```
Expected: hook scripts present, agents present, settings.json contains UserPromptSubmit/SessionStart/PreToolUse/PostToolUse/Stop.

- [ ] **Step 4: Run sync check**

```bash
DEV_ROOT="$PRINTWAY" ./sync.sh --check --no-global
```
Expected: `All in sync`.

- [ ] **Step 5: No commit needed (operational only)**

---

### Task 27: Dogfood `/vg:blueprint 2` on PrintwayV3

**Files:** none — execution + observation.

- [ ] **Step 1: Open fresh Claude Code session**

User must restart Claude Code in PrintwayV3 directory. Communicate this:
> "Open a NEW Claude Code session in /Users/dzungnguyen/Vibe Code/Code/PrintwayV3. Do NOT reuse the current session — command text is cached per session."

- [ ] **Step 2: User invokes the pilot**

User types in fresh session:
```
/vg:blueprint 2
```

- [ ] **Step 3: Observe + record outcomes**

While AI runs, watch for:
- Tasklist appears immediately (UserPromptSubmit + SessionStart fired correctly)
- AI calls TodoWrite early (PostToolUse signs evidence)
- Each step touches marker (vg-orchestrator step-active calls succeed)
- Both `Agent(subagent_type="vg-blueprint-planner")` and `Agent(subagent_type="vg-blueprint-contracts")` fire
- PLAN.md + API-CONTRACTS.md materialize with real content
- Stop hook allows clean completion

- [ ] **Step 4: Query metrics post-run**

```bash
PRINTWAY="/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
sqlite3 "$PRINTWAY/.vg/events.db" <<'SQL'
SELECT event_type, COUNT(*) 
FROM events 
WHERE phase='2' AND ts >= datetime('now', '-30 minutes')
GROUP BY event_type 
ORDER BY 2 DESC;
SQL
```

- [ ] **Step 5: Verify exit criteria checklist**

Compare results to spec §5.4 criteria 1-13. For each, mark PASS/FAIL:

```bash
cat > /tmp/r1a-pilot-results.md <<'EOF'
# R1a Blueprint Pilot Results — <date>

| # | Criterion | Result |
|---|---|---|
| 1 | Tasklist visible immediately | PASS/FAIL |
| 2 | blueprint.native_tasklist_projected ≥1 | PASS/FAIL |
| 3 | All 18+ step markers touched | PASS/FAIL |
| 4 | PLAN.md + API-CONTRACTS.md content_min_bytes met | PASS/FAIL |
| 5 | Two Agent invocations present | PASS/FAIL |
| 6 | PreToolUse blocks simulated TodoWrite skip | PASS/FAIL |
| 7 | User reports understanding workflow | PASS/FAIL |
| 8 | Stop hook fires without exit 2 | PASS/FAIL |
| 9 | Block triggers diagnostic narration template | PASS/FAIL |
| 10 | Stop fails closed if vg.block unpaired | PASS/FAIL |
| 11 | UserPromptSubmit creates active-run BEFORE response | PASS/FAIL |
| 12 | PreToolUse Write blocks evidence forgery | PASS/FAIL |
| 13 | State-machine validator catches out-of-order events | PASS/FAIL |

Verdict: PASS / FAIL
EOF
cat /tmp/r1a-pilot-results.md
```

- [ ] **Step 6: Commit results to repo**

```bash
cp /tmp/r1a-pilot-results.md docs/superpowers/plans/2026-05-03-vg-r1a-blueprint-pilot-results.md
git add docs/superpowers/plans/2026-05-03-vg-r1a-blueprint-pilot-results.md
git commit -m "docs(r1a): blueprint pilot results — <PASS|FAIL>"
```

- [ ] **Step 7: Verdict gate**

If ALL 13 criteria PASS → R1a passes. Proceed to plan R1b (phase orchestrator).
If ANY criterion FAILS → R1a fails. Return to design phase. DO NOT scale to other commands.

---

## Plan Self-Review Checklist (post-write)

The author of this plan must check before handoff:

- [ ] **Spec coverage**: every spec §1-§7 has at least one task? (Verified: hooks §4.4 → Tasks 4-10, slim entry §4.1 → Task 21, subagents §4.3 → Tasks 19-20, refs §4.2 → Tasks 13-18, install §4.4 → Task 11, helpers §4.4b/c → Tasks 1-2, 5-layer diagnostic embedded in hook impls, multi-canary R1 §5.5 noted in Task 27 verdict gate.)
- [ ] **Placeholder scan**: no TBD/TODO/etc in steps. (Verified inline.)
- [ ] **Type consistency**: signed evidence schema (`payload`/`hmac_sha256`/`signed_at`) used consistently across helper, PostToolUse hook, PreToolUse Bash hook, tests. State machine `events` table schema (`ts/event_type/phase/command/run_id/payload`) used consistently in tests.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-03-vg-r1a-blueprint-pilot.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for the 27-task R1a scope (you don't have to babysit each commit).

2. **Inline Execution** — Execute tasks in this session using executing-plans, batch with checkpoints. Best if you want to watch each commit live.

**Which approach?**
