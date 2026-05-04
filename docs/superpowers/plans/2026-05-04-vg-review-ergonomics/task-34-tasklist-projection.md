<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-04-vg-review-ergonomics.md -->
<!-- Spec: docs/superpowers/specs/2026-05-04-vg-review-ergonomics-design.md -->

## Task 34: Force `TodoWrite` projection before any review `step-active`

**Files:**
- Create: `commands/vg/_shared/lib/tasklist-projection-instruction.md`
- Modify: `scripts/hooks/vg-pre-tool-use-bash.sh` (improve block diagnostic + emit warn telemetry for review runs)
- Modify: `commands/vg/review.md` (reorder slim entry — instruction block FIRST, before any step-active)
- Test: `tests/test_review_tasklist_projection.py`

**Why:** PV3 events.db shows 15 historical `PreToolUse-tasklist` block.handled events for review runs. Hook fires (good) but AI emits `vg.block.handled` without actually calling `TodoWrite` to create `.tasklist-projected.evidence.json` (bad). Root cause is two-fold: (1) the slim entry instruction to call `TodoWrite` is buried at line 297, AFTER multiple `step-active` invocations would naturally happen; (2) the existing block diagnostic mentions HMAC + checksum jargon and doesn't tell the AI exactly what tool to call.

This task moves the instruction to the top of the slim entry, makes the block diagnostic prescriptive, and adds a new warn-tier telemetry event so we can graph future bypass attempts.

- [ ] **Step 1: Write the failing test**

Create `tests/test_review_tasklist_projection.py`:

```python
"""Task 34 — tasklist projection enforcement for /vg:review.

Pin: when an AI tries `vg-orchestrator step-active` for a review run
without first creating `.tasklist-projected.evidence.json`, the
PreToolUse-bash hook MUST BLOCK with a diagnostic that explicitly
names the TodoWrite tool + tasklist-projected subcommand.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = str(REPO_ROOT / "scripts/hooks/vg-pre-tool-use-bash.sh")


def _setup_review_run(tmp: Path) -> str:
    """Create a synthetic review run with tasklist-contract.json but no evidence."""
    run_id = "test-run-tasklist-34"
    runs_dir = tmp / ".vg" / "runs" / run_id
    runs_dir.mkdir(parents=True)
    (runs_dir / "tasklist-contract.json").write_text(json.dumps({
        "schema": "native-tasklist.v2",
        "run_id": run_id,
        "command": "vg:review",
        "phase": "test-1.0",
        "checklists": [{"id": "review_preflight", "items": ["0a_env_mode_gate"], "status": "pending"}],
    }), encoding="utf-8")

    active_dir = tmp / ".vg" / "active-runs"
    active_dir.mkdir(parents=True)
    (active_dir / "test-session.json").write_text(json.dumps({
        "run_id": run_id, "command": "vg:review", "phase": "test-1.0",
    }), encoding="utf-8")
    return run_id


def _run_hook(tmp: Path, command: str, session_id: str = "test-session") -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(
        ["bash", HOOK],
        input=payload,
        env={**os.environ,
             "CLAUDE_HOOK_SESSION_ID": session_id,
             "VG_REPO_ROOT": str(tmp)},
        capture_output=True, text=True, cwd=str(tmp), timeout=10,
    )


def test_block_message_names_todowrite_tool(tmp_path: Path) -> None:
    """When evidence missing, block diagnostic MUST mention `TodoWrite` + `tasklist-projected`."""
    _setup_review_run(tmp_path)
    cmd = "python3 .claude/scripts/vg-orchestrator step-active 0a_env_mode_gate"
    result = _run_hook(tmp_path, cmd)
    assert result.returncode == 2, f"expected BLOCK exit 2, got {result.returncode}: {result.stderr}"
    diag = result.stderr
    assert "TodoWrite" in diag, f"diagnostic must name TodoWrite tool; got:\n{diag}"
    assert "tasklist-projected" in diag, f"diagnostic must name tasklist-projected subcommand; got:\n{diag}"


def test_block_emits_review_specific_telemetry(tmp_path: Path) -> None:
    """When BLOCK fires for a review run, hook MUST emit `review.tasklist_projection_skipped`."""
    run_id = _setup_review_run(tmp_path)
    # Seed events.db so emit-event has a target. Hook calls vg-orchestrator
    # which writes to .vg/events.db.
    events_db = tmp_path / ".vg" / "events.db"
    if not events_db.exists():
        import sqlite3
        conn = sqlite3.connect(str(events_db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                run_id TEXT, command TEXT, event_type TEXT,
                ts TEXT, payload_json TEXT, actor TEXT, outcome TEXT
            )""")
        conn.commit()
        conn.close()

    cmd = "python3 .claude/scripts/vg-orchestrator step-active 0a_env_mode_gate"
    _run_hook(tmp_path, cmd)

    import sqlite3
    conn = sqlite3.connect(str(events_db))
    rows = conn.execute(
        "SELECT event_type FROM events WHERE event_type='review.tasklist_projection_skipped'"
    ).fetchall()
    conn.close()
    assert len(rows) >= 1, "expected at least 1 review.tasklist_projection_skipped event"


def test_pass_when_evidence_exists(tmp_path: Path) -> None:
    """Hook PASSes when both tasklist-contract.json and evidence file present."""
    run_id = _setup_review_run(tmp_path)
    evidence = tmp_path / ".vg" / "runs" / run_id / ".tasklist-projected.evidence.json"
    evidence.write_text(json.dumps({"projected_at": "2026-05-04T00:00:00Z"}), encoding="utf-8")

    cmd = "python3 .claude/scripts/vg-orchestrator step-active 0a_env_mode_gate"
    result = _run_hook(tmp_path, cmd)
    # Hook may exit 0 (pass) OR exit 2 for OTHER reasons (HMAC sig missing in
    # synthetic env). Accept exit 0 as definitive PASS; if non-zero, just
    # assert the diagnostic does NOT mention tasklist projection.
    if result.returncode != 0:
        assert "TodoWrite" not in result.stderr, (
            "hook blocked but for non-tasklist reason; should not mention "
            f"TodoWrite. stderr:\n{result.stderr}"
        )


def test_review_md_instruction_block_present_at_top(tmp_path: Path) -> None:
    """review.md slim entry MUST have the projection instruction block BEFORE
    any `vg-orchestrator step-active` invocation in the same file."""
    review_md = (REPO_ROOT / "commands/vg/review.md").read_text(encoding="utf-8")

    # The shared instruction reference
    instruction_marker = "_shared/lib/tasklist-projection-instruction.md"
    first_step_active = review_md.find("vg-orchestrator step-active")
    instruction_pos = review_md.find(instruction_marker)

    assert instruction_pos != -1, (
        "review.md must reference _shared/lib/tasklist-projection-instruction.md"
    )
    assert first_step_active != -1, "review.md must invoke step-active somewhere"
    assert instruction_pos < first_step_active, (
        f"projection instruction at byte {instruction_pos} must come BEFORE "
        f"first step-active at byte {first_step_active}"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix" && python3 -m pytest tests/test_review_tasklist_projection.py -v`

Expected: 4 FAILures (no instruction file, hook diagnostic doesn't name TodoWrite/tasklist-projected, no telemetry, review.md missing instruction marker).

- [ ] **Step 3: Create the shared instruction reference**

Create `commands/vg/_shared/lib/tasklist-projection-instruction.md`:

```markdown
# Tasklist projection instruction (shared reference)

Slim entries (build/test/review/accept/scope) MUST embed this block as
the FIRST imperative after `vg-orchestrator run-start` and BEFORE any
`vg-orchestrator step-active` call. The PreToolUse-bash hook BLOCKs all
step-active calls until evidence file exists; running step-active first
will trigger the block, which AI agents have historically resolved
without actually projecting (15+ such bypasses recorded in PV3 events.db).

## Embed this block verbatim:

```bash
# BEFORE any step-active — project the tasklist contract to the native UI.
# The PreToolUse-bash hook will BLOCK step-active calls until evidence exists.

CONTRACT_PATH=".vg/runs/${RUN_ID}/tasklist-contract.json"
if [ ! -f "$CONTRACT_PATH" ]; then
  echo "⛔ tasklist-contract.json missing — orchestrator should have written it during run-start" >&2
  exit 1
fi
```

Then **the AI agent MUST** (this is the part the hook enforces):

1. Read `${CONTRACT_PATH}` and parse `checklists[]`.
2. Call `TodoWrite` with one todo entry per `items[]` row across all checklists.
   Each todo's `content` field = the item ID (e.g. `0a_env_mode_gate`).
   The PostToolUse-TodoWrite hook signs `.tasklist-projected.evidence.json`.
3. Run:
   ```bash
   python3 .claude/scripts/vg-orchestrator tasklist-projected --adapter claude
   ```
   This validates that the most recent TodoWrite payload matches the contract checksum
   AND writes `.vg/runs/${RUN_ID}/.tasklist-projected.evidence.json`. CLI emit of the
   `*.native_tasklist_projected` event is rejected by the orchestrator (sole-owner rule).

After both succeed, subsequent `step-active` calls pass the PreToolUse-bash hook.

## Why this is mandatory

- Native task UI is the user's primary signal of progress. Markdown tables
  in chat are NOT a substitute — sếp Dũng cannot see which step is in flight.
- Reordering: place this block IMMEDIATELY after `run-start` so the AI cannot
  "forget" or skip past it on the way to step-active.
- Hook enforcement: PreToolUse-bash blocks `step-active` if evidence missing.
  Bypassing the block (emitting `vg.block.handled` without resolution) leaves
  evidence still missing — next step-active blocks again. Telemetry event
  `<command>.tasklist_projection_skipped` (warn-tier) records each bypass
  attempt for `/vg:gate-stats` analysis.
```

- [ ] **Step 4: Improve hook block diagnostic + emit telemetry**

Read current `emit_block` function in `scripts/hooks/vg-pre-tool-use-bash.sh`:

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
grep -nA 30 "^emit_block()" scripts/hooks/vg-pre-tool-use-bash.sh | head -45
```

Find the existing block diagnostic file write (the `.vg/blocks/<run_id>/<gate_id>.md` template). Modify the `emit_block()` function to:

1. Include a "Required fix" section that names exactly `TodoWrite` + `vg-orchestrator tasklist-projected`.
2. After writing the block file but before `exit 2`, emit a per-command warn-tier telemetry event.

Apply this edit pattern to `scripts/hooks/vg-pre-tool-use-bash.sh`. Find the
existing `emit_block` function body and add the imperative fix lines to the
block file content + add the telemetry emit before `exit 2`:

```bash
# Inside emit_block(), AFTER writing the block file, BEFORE the existing exit 2:

# Per-command telemetry — gate-stats can graph bypass attempts.
command_from_run="$(python3 -c '
import json,sys
try: print(json.load(open(sys.argv[1]))["command"])
except: print("")
' "$run_file" 2>/dev/null || echo "")"

if [ -n "$command_from_run" ]; then
  event_type="${command_from_run/vg:/}.tasklist_projection_skipped"
  python3 .claude/scripts/vg-orchestrator emit-event "$event_type" \
    --actor hook \
    --outcome WARN \
    --payload "{\"run_id\":\"${run_id}\",\"contract_path\":\"${contract_path}\"}" \
    >/dev/null 2>&1 || true
fi
```

Also UPDATE the `Required fix` section that is written into the block file. Find the existing block file content in `emit_block()` (it has `## Required fix` heading already) and replace whatever fix-text is there now with this exact block:

```bash
echo "## Required fix"
echo ""
echo "Before any \`vg-orchestrator step-active\` call, you MUST:"
echo ""
echo "1. Read \`${contract_path}\` (parse \`checklists[]\`)."
echo "2. Call the \`TodoWrite\` tool with one entry per \`items[]\` row."
echo "3. Run:"
echo "   \`\`\`bash"
echo "   python3 .claude/scripts/vg-orchestrator tasklist-projected --adapter claude"
echo "   \`\`\`"
echo "   This writes \`.tasklist-projected.evidence.json\` so subsequent"
echo "   step-active calls pass this hook."
echo ""
echo "Do NOT just emit \`vg.block.handled\` — the evidence file must exist."
echo "See \`commands/vg/_shared/lib/tasklist-projection-instruction.md\` for full instructions."
```

- [ ] **Step 5: Reorder review.md slim entry**

Edit `commands/vg/review.md`. Find the line where the slim entry first invokes step-active or the create_task_tracker step.

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
grep -nE "^### STEP|^<step|step-active" commands/vg/review.md | head -10
```

Locate the FIRST `vg-orchestrator step-active` invocation. Insert ABOVE it (still after `run-start`) a reference to the shared instruction:

```markdown
### Tasklist projection (REQUIRED before any step-active)

Read `_shared/lib/tasklist-projection-instruction.md` and follow it
verbatim. The PreToolUse-bash hook will BLOCK every `step-active` call
in this slim entry until `.vg/runs/${RUN_ID}/.tasklist-projected.evidence.json`
exists.
```

Also append to `must_emit_telemetry:` block (around line 149) so the
Stop hook recognizes `review.tasklist_projection_skipped` events
emitted by the upgraded hook (spec lines 770-781; Codex round-3 B3 fix):

```yaml
    # Task 34 — tasklist projection enforcement (Bug B)
    - event_type: "review.tasklist_projection_skipped"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
```

Add a test asserting the declaration:

```python
def test_review_md_declares_tasklist_projection_skipped_telemetry() -> None:
    text = (REPO_ROOT / "commands/vg/review.md").read_text(encoding="utf-8")
    assert "review.tasklist_projection_skipped" in text, \
        "review.md must_emit_telemetry must declare 'review.tasklist_projection_skipped' (else Stop hook silent-skips)"
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_review_tasklist_projection.py -v
```

Expected: 4 PASSed.

- [ ] **Step 7: Sync mirrors**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
DEV_ROOT=. bash sync.sh --no-global 2>&1 | tail -3
python3 scripts/vg_sync_codex.py --apply 2>&1 | tail -2
```

Expected: "Changed: N" with N >= 3, codex sync 53 applied.

- [ ] **Step 8: Commit**

```bash
git add commands/vg/_shared/lib/tasklist-projection-instruction.md \
        scripts/hooks/vg-pre-tool-use-bash.sh \
        commands/vg/review.md \
        tests/test_review_tasklist_projection.py \
        .claude/ codex-skills/ .codex/
git commit -m "feat(review): force TodoWrite projection before step-active (Task 34)

Pre-fix: PV3 events.db showed 15 PreToolUse-tasklist block.handled events
where AI bypassed the block by emitting handled without actually calling
TodoWrite. Two root causes:
  1. Slim entry instruction to call TodoWrite was buried at line 297,
     after AI would naturally hit step-active first.
  2. Existing block diagnostic mentioned HMAC/checksum jargon, didn't
     name the actual fix tools (TodoWrite + tasklist-projected).

Post-fix:
- New _shared/lib/tasklist-projection-instruction.md — canonical embed
  block for all slim entries (review/build/test/accept/scope).
- review.md slim entry references the instruction IMMEDIATELY after
  run-start, before any step-active. Test asserts byte position.
- PreToolUse-bash hook diagnostic now explicitly names TodoWrite +
  tasklist-projected subcommand. Pre-fix said \"signed evidence file
  exists + HMAC valid\"; post-fix tells AI the exact fix path.
- New warn-tier telemetry event \"<command>.tasklist_projection_skipped\"
  emitted by hook on BLOCK. /vg:gate-stats can now graph bypass
  attempts for AI-behavior debugging.

Tests: 4 cases (block names tools, telemetry fires, pass when evidence
present, review.md positions instruction before step-active).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
