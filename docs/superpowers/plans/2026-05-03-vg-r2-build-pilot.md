# R2 Build Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `commands/vg/build.md` from 4,571 → ≤500-line slim entry + ~9 flat refs in `commands/vg/_shared/build/` + 2 custom subagents (`vg-build-task-executor`, `vg-build-post-executor`) + strengthened `vg-agent-spawn-guard.py` (spawn-count check). All 3 R1a UX baseline requirements baked in (per-task split, spawn narration, compact hook stderr). Pilot is GATE — if 12 exit criteria PASS, R2 test pilot proceeds.

**Architecture:** Reuse 100% of R1a infrastructure (HMAC evidence helper, state-machine validator, 7 hooks, install-hooks.sh, vg-meta-skill, vg-narrate-spawn, vg-load). Build-specific work: 1 helper enhancement + 1 subagent pair + 1 slim entry + ~9 refs. Heavy steps (8_execute_waves at 1881 lines, 9_post_execution at 896 lines) delegated to subagents. Build wave executor uses `vg-load --wave N` to load only current wave's tasks (saves context vs reading full PLAN).

**Tech Stack:** bash (hook script + helper), Python 3 (spawn-guard enhancement + tests), pytest, Claude Code Agent tool, sqlite3 (events.db queries), HMAC-SHA256 (signed evidence — reused).

**Spec source:** `docs/superpowers/specs/2026-05-03-vg-build-design.md` (508 lines, includes Codex review corrections + UX baseline).

**Branch:** `feat/rfc-v9-followup-fixes`. Each task commits incrementally. Final dogfood before merge.

---

## File structure (new + modified)

| File | Action | Lines | Purpose |
|---|---|---|---|
| `scripts/vg-agent-spawn-guard.py` | MODIFY (183 → ~280) | +97 | Add spawn-count check from R5 wave-spawn-plan.json |
| `scripts/tests/test_spawn_guard_count_check.py` | CREATE | ~120 | Verify spawn-count blocks + denies + emits event |
| `commands/vg/build.md` | REFACTOR (4571 → ~500) | -4071 | Slim entry per blueprint pilot template |
| `commands/vg/.build.md.r2-backup` | CREATE | 4571 | Backup of original (mirrors R1a pattern) |
| `commands/vg/_shared/build/preflight.md` | CREATE | ~250 | Steps 0_gate, 0_session, 1_parse, 1a/1b, create_task_tracker |
| `commands/vg/_shared/build/context.md` | CREATE | ~200 | Steps 2_initialize, 4_load_contracts_and_context (capsule loading) |
| `commands/vg/_shared/build/validate-blueprint.md` | CREATE | ~250 | Steps 3, 5, 6, 7 (blueprint validate, branching, phase verify, plan discovery) |
| `commands/vg/_shared/build/waves-overview.md` | CREATE | ~200 | Step 8 entry — HEAVY, delegates to vg-build-task-executor |
| `commands/vg/_shared/build/waves-delegation.md` | CREATE | ~250 | Input/output contract for vg-build-task-executor (with vg-load + narrate-spawn) |
| `commands/vg/_shared/build/post-execution-overview.md` | CREATE | ~200 | Step 9 entry — HEAVY, delegates to vg-build-post-executor |
| `commands/vg/_shared/build/post-execution-delegation.md` | CREATE | ~200 | Input/output contract for vg-build-post-executor |
| `commands/vg/_shared/build/crossai-loop.md` | CREATE | ~150 | Step 11 (CrossAI loop — refactor deferred per spec §1.5) |
| `commands/vg/_shared/build/close.md` | CREATE | ~200 | Steps 10_postmortem + 12_run_complete |
| `agents/vg-build-task-executor/SKILL.md` | CREATE | ~300 | Per-task subagent (parallel, runs N per wave) |
| `agents/vg-build-post-executor/SKILL.md` | CREATE | ~250 | Single post-wave verifier (L2/L3/L5/L6 + truthcheck + summary) |
| `scripts/emit-tasklist.py` | MODIFY | +0 | Verify CHECKLIST_DEFS for vg:build canonical (test) |
| `scripts/tests/test_build_slim_size.py` | CREATE | ~50 | Assert build.md ≤600 lines, refs listed in entry, uses Agent not Task |
| `scripts/tests/test_build_references_exist.py` | CREATE | ~60 | Per-ref ceiling assertions |
| `scripts/tests/test_build_subagent_definitions.py` | CREATE | ~80 | Both agents valid frontmatter, narrow tools, no nested spawn |
| `scripts/tests/test_build_runtime_contract_split.py` | CREATE | ~60 | Verify must_write includes BUILD-LOG/ + WAVE-RESULT/ globs |

---

## Phase A — Strengthen spawn-guard (1 audit FAIL fix)

### Task 1: Add spawn-count check to vg-agent-spawn-guard.py

**Files:**
- Modify: `scripts/vg-agent-spawn-guard.py:131-180`
- Test: `scripts/tests/test_spawn_guard_count_check.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_spawn_guard_count_check.py
import json, os, subprocess, tempfile
from pathlib import Path


GUARD = Path(__file__).resolve().parents[1] / "vg-agent-spawn-guard.py"


def _setup_run(tmp_path, run_id, expected_tasks):
    """Stage active-run + wave-spawn-plan + empty spawn-count files."""
    (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg/active-runs/test-session.json").write_text(
        json.dumps({"run_id": run_id, "command": "vg:build", "session_id": "test-session"})
    )
    (tmp_path / f".vg/runs/{run_id}").mkdir(parents=True, exist_ok=True)
    (tmp_path / f".vg/runs/{run_id}/.wave-spawn-plan.json").write_text(
        json.dumps({"wave_id": 3, "expected": expected_tasks})
    )


def _spawn(tmp_path, subagent_type, prompt_extra=""):
    """Invoke guard with given Agent tool input, return (rc, stderr)."""
    payload = {
        "tool_name": "Agent",
        "tool_input": {
            "subagent_type": subagent_type,
            "prompt": f"task_id=task-04\n{prompt_extra}",
        },
        "session_id": "test-session",
    }
    proc = subprocess.run(
        ["python3", str(GUARD)],
        input=json.dumps(payload),
        cwd=tmp_path,
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stderr


def test_spawn_count_allows_first_n_spawns(tmp_path, monkeypatch):
    """Wave plan expects 5 → first 5 spawns of vg-build-task-executor allowed."""
    monkeypatch.chdir(tmp_path)
    _setup_run(tmp_path, "run-1", expected_tasks=["task-01", "task-02", "task-03", "task-04", "task-05"])
    rc, _ = _spawn(tmp_path, "vg-build-task-executor", "task_id=task-04")
    assert rc == 0


def test_spawn_count_denies_unexpected_task(tmp_path, monkeypatch):
    """Wave plan expects task-04 → spawning task-99 (not in plan) blocked."""
    monkeypatch.chdir(tmp_path)
    _setup_run(tmp_path, "run-2", expected_tasks=["task-01", "task-02", "task-03", "task-04", "task-05"])
    rc, stderr = _spawn(tmp_path, "vg-build-task-executor", "task_id=task-99")
    assert rc != 0
    assert "task-99" in stderr or "not in remaining" in stderr.lower()


def test_spawn_count_preserves_existing_gsd_block(tmp_path, monkeypatch):
    """Regression: gsd-* still denied (pre-existing logic)."""
    monkeypatch.chdir(tmp_path)
    _setup_run(tmp_path, "run-3", expected_tasks=["task-01"])
    rc, stderr = _spawn(tmp_path, "gsd-executor", "task_id=task-01")
    assert rc != 0
    assert "gsd" in stderr.lower() or "forbidden" in stderr.lower()


def test_spawn_count_no_active_run_allows(tmp_path, monkeypatch):
    """No active VG run → spawn allowed (guard only enforces during active run)."""
    monkeypatch.chdir(tmp_path)
    rc, _ = _spawn(tmp_path, "vg-build-task-executor", "task_id=task-04")
    assert rc == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
pytest scripts/tests/test_spawn_guard_count_check.py -v
```
Expected: FAIL on `test_spawn_count_denies_unexpected_task` (current guard only checks gsd-*, not spawn-count).

- [ ] **Step 3: Implement spawn-count enhancement**

Modify `scripts/vg-agent-spawn-guard.py` — add new function `_enforce_spawn_count` and call it AFTER existing gsd-* check (around line 155 where `return allow()` for non-gsd happens):

```python
# Add near top imports
import re

# Add new constant near ALLOWED_GSD_SUBAGENTS
BUILD_TASK_EXECUTOR = "vg-build-task-executor"


def _spawn_count_paths(run_id: str) -> tuple[Path, Path]:
    base = Path(f".vg/runs/{run_id}")
    return base / ".wave-spawn-plan.json", base / ".spawn-count.json"


def _extract_task_id(prompt: str) -> str | None:
    """Parse 'task_id=task-NN' or 'task_id: task-NN' from subagent prompt."""
    m = re.search(r"task_id\s*[=:]\s*(task-[\w\d-]+)", prompt, re.IGNORECASE)
    return m.group(1) if m else None


def _enforce_spawn_count(hook_input: dict, run_id: str) -> int | None:
    """Returns deny rc if spawn shortfall/overshoot/unknown task; None to fall through."""
    subagent = (hook_input.get("tool_input") or {}).get("subagent_type", "")
    if subagent != BUILD_TASK_EXECUTOR:
        return None  # only enforce for build task executor

    plan_path, count_path = _spawn_count_paths(run_id)
    if not plan_path.exists():
        return None  # no plan → no enforcement (e.g., R5 not run yet)

    try:
        plan = json.loads(plan_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    expected = plan.get("expected") or []
    if not isinstance(expected, list):
        return None

    prompt = (hook_input.get("tool_input") or {}).get("prompt", "")
    task_id = _extract_task_id(prompt)
    if not task_id:
        return deny("⛔ vg-build-task-executor spawn missing task_id in prompt; spawn-guard cannot verify against wave plan.")

    # Load existing count (or init)
    if count_path.exists():
        try:
            count = json.loads(count_path.read_text())
        except (OSError, json.JSONDecodeError):
            count = {"wave_id": plan.get("wave_id"), "expected": expected, "spawned": [], "remaining": list(expected)}
    else:
        count = {"wave_id": plan.get("wave_id"), "expected": expected, "spawned": [], "remaining": list(expected)}

    if task_id not in count["remaining"]:
        already = task_id in count["spawned"]
        msg = (
            f"⛔ vg-agent-spawn-guard: task_id='{task_id}' "
            f"{'already spawned this wave' if already else 'not in wave plan'}.\n"
            f"Wave {count['wave_id']} expected: {count['expected']}\n"
            f"Already spawned: {count['spawned']}\n"
            f"Remaining: {count['remaining']}\n\n"
            f"Either correct the task_id, or update wave-spawn-plan.json with override-reason."
        )
        return deny(msg)

    # Move from remaining → spawned, persist
    count["remaining"].remove(task_id)
    count["spawned"].append(task_id)
    count_path.parent.mkdir(parents=True, exist_ok=True)
    count_path.write_text(json.dumps(count, indent=2))
    return None  # allow


# In main(), AFTER the gsd-* check (around line 155) and BEFORE return allow():
def main() -> int:
    # ... existing code through gsd-* check ...

    # NEW: spawn-count check for vg-build-task-executor
    is_active, _ = in_active_vg_run(hook_session=hook_session)
    if is_active:
        run_file = Path(f".vg/active-runs/{hook_session or 'default'}.json")
        if run_file.exists():
            try:
                run_id = json.loads(run_file.read_text())["run_id"]
                rc = _enforce_spawn_count(hook_input, run_id)
                if rc is not None:
                    return rc
            except (OSError, json.JSONDecodeError, KeyError):
                pass

    return allow()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest scripts/tests/test_spawn_guard_count_check.py -v
```
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add scripts/vg-agent-spawn-guard.py scripts/tests/test_spawn_guard_count_check.py
git commit -m "$(cat <<'EOF'
feat(r2): spawn-count check in vg-agent-spawn-guard (audit FAIL fix)

Spec §5.1 — only audit FAIL of 6 mechanisms. Without count check, AI can
spawn N-1 instead of N tasks per wave, claim done, advance silently.

Reads .vg/runs/<run_id>/.wave-spawn-plan.json (R5 output), tracks
.spawn-count.json (spawned[] + remaining[]). Per spawn:
1. Existing subagent_type allow-list check (preserved)
2. NEW: parse task_id from prompt
3. NEW: assert task_id in remaining[]
4. Move task_id remaining → spawned, persist
5. Wave-complete asserts spawned == expected (Stop hook)

4 tests cover allow-first-N, deny-unexpected-task, preserve-gsd-block-regression,
no-active-run-allows-pass-through.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase B — Build slim refs (9 files, mirrors R1a blueprint pattern)

### Task 2: Backup current build.md

**Files:**
- Create: `commands/vg/.build.md.r2-backup`

- [ ] **Step 1: Backup**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp commands/vg/build.md commands/vg/.build.md.r2-backup
wc -l commands/vg/.build.md.r2-backup
```
Expected: 4571 lines.

- [ ] **Step 2: Commit**

```bash
git add commands/vg/.build.md.r2-backup
git commit -m "chore(r2): backup build.md before slim refactor (4571 lines)"
```

### Task 3: Create _shared/build/preflight.md

**Files:**
- Create: `commands/vg/_shared/build/preflight.md`

- [ ] **Step 1: Extract bash from backup**

Read backup steps `0_gate_integrity_precheck`, `0_session_lifecycle`, `1_parse_args`, `1a_build_queue_preflight`, `1b_recon_gate`, `create_task_tracker` (these are at top of backup, ~330 total lines source). Extract bash inline into the ref. Each step wraps with `vg-orchestrator step-active <step>` before + `mark-step` after for hook gate.

```bash
mkdir -p commands/vg/_shared/build
```

Write the ref following the pattern from `commands/vg/_shared/blueprint/preflight.md`:

- File starts with `# build preflight (STEP 1)` H1.
- HARD-GATE block listing the 6 steps + marker requirement.
- One H2 section per step (`## STEP 1.1 — gate integrity precheck (0_gate_integrity_precheck)` etc.).
- Each section: prose explaining purpose + bash code block from backup with `vg-orchestrator step-active` wrap + `mark-step` after.
- For `create_task_tracker`: include the HARD-GATE about TodoWrite hierarchical projection (per R1a pattern in `commands/vg/_shared/blueprint/preflight.md` STEP 1.4 — copy that section verbatim, swap "blueprint" for "build" + adapt example projection).

- [ ] **Step 2: Verify file exists with content**

```bash
wc -l commands/vg/_shared/build/preflight.md
```
Expected: 200-350 lines.

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/build/preflight.md
git commit -m "feat(r2): build preflight ref (6 light steps from backup)

Steps 0_gate_integrity_precheck, 0_session_lifecycle, 1_parse_args,
1a_build_queue_preflight, 1b_recon_gate, create_task_tracker.
Includes hierarchical TodoWrite projection per R1a UX baseline."
```

### Task 4: Create _shared/build/context.md

**Files:**
- Create: `commands/vg/_shared/build/context.md`

- [ ] **Step 1: Extract bash from backup**

Read backup steps `2_initialize` (small) + `4_load_contracts_and_context` (353 lines). Extract bash. The 4_load step calls `pre-executor-check.py` to assemble per-task capsules — preserve verbatim (this is the critical capsule materialization).

Write the ref:

- H1 `# build context loading (STEP 2)`
- HARD-GATE: capsule materialization is mandatory; AI cannot skip; PreToolUse hook blocks spawn without capsule.
- STEP 2.1 — initialize (`2_initialize`)
- STEP 2.2 — load contracts and context (`4_load_contracts_and_context`) — paste backup bash including `pre-executor-check.py` invocation + capsule write loop.
- Note: per R1a UX baseline, contracts loaded via `vg-load --phase ${PHASE_NUMBER} --artifact contracts --endpoint <slug>` for partial loads (build doesn't need all endpoints loaded at once — only those referenced by current wave's tasks).

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/build/context.md
git commit -m "feat(r2): build context ref (steps 2 init + 4 capsule load)

Capsule materialization (pre-executor-check.py) preserved verbatim — it
is the contract executor reads. Notes vg-load partial-load pattern for
contracts/goals to avoid full-file context overload."
```

### Task 5: Create _shared/build/validate-blueprint.md

**Files:**
- Create: `commands/vg/_shared/build/validate-blueprint.md`

- [ ] **Step 1: Extract bash from backup**

Read backup steps `3_validate_blueprint` (163 lines), `5_handle_branching` (~60 lines), `6_validate_phase` (~50 lines), `7_discover_plans` (~60 lines). Extract bash.

Write the ref:

- H1 `# build validate-blueprint (STEP 3)`
- STEP 3.1 — validate blueprint exists + freshness (`3_validate_blueprint`)
- STEP 3.2 — handle branching (`5_handle_branching`) — partial-wave / --gaps-only / --only flag handling
- STEP 3.3 — validate phase (`6_validate_phase`)
- STEP 3.4 — discover plans (`7_discover_plans`) — uses `vg-load --artifact plan --list` to enumerate task files (R1a UX baseline)

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/build/validate-blueprint.md
git commit -m "feat(r2): build validate-blueprint ref (steps 3, 5, 6, 7)

Plan discovery now uses vg-load --artifact plan --list (UX baseline)
instead of grepping monolithic PLAN.md."
```

### Task 6: Create _shared/build/waves-overview.md + waves-delegation.md (HEAVY)

**Files:**
- Create: `commands/vg/_shared/build/waves-overview.md`
- Create: `commands/vg/_shared/build/waves-delegation.md`

- [ ] **Step 1: Write waves-overview.md**

H1 `# build waves (STEP 4 — HEAVY)`. HARD-GATE: AI MUST spawn N parallel `vg-build-task-executor` subagents (where N = wave's task count from `.wave-spawn-plan.json`). MUST NOT execute tasks inline. Spawn-guard (Task 1) blocks shortfall.

Pre-spawn checklist (preserved from backup step 8 lines 1271-1342 of original):
1. `vg-orchestrator step-active 8_execute_waves`
2. Bash: load wave plan via `vg-load --phase ${PHASE_NUMBER} --artifact plan --wave ${WAVE_ID}` (UX baseline — partial load, NOT full PLAN.md)
3. Read `.wave-spawn-plan.json` for N task list
4. For each task: verify capsule at `.task-capsules/task-${N}.capsule.json` exists (HARD BLOCK if missing — line 1414 backup)
5. Run L1 design-pixel gate per task (if design-ref present)
6. **Spawn ALL N subagents in ONE assistant message (parallel)**

For each spawn, narrate per UX baseline:
```bash
bash scripts/vg-narrate-spawn.sh vg-build-task-executor spawning "task-${N} wave-${W}"
# then Agent(subagent_type="vg-build-task-executor", prompt=...)
# on return:
bash scripts/vg-narrate-spawn.sh vg-build-task-executor returned "task-${N} commit ${SHA}"
# on failure:
bash scripts/vg-narrate-spawn.sh vg-build-task-executor failed "task-${N}: <cause>"
```

After all returns: aggregate count, validate spawn-count == expected (R5 budget), emit `wave.completed` event, mark step `8_execute_waves`.

Read `waves-delegation.md` for the exact prompt template the main agent passes.

- [ ] **Step 2: Write waves-delegation.md**

H1 `# build waves delegation contract (vg-build-task-executor subagent)`. Includes:

- Input contract (JSON envelope): task_id, wave_id, capsule_path, plan_task_path (= `${PHASE_DIR}/PLAN/task-${N}.md` — UX baseline split), contract_slice_paths (= `vg-load --artifact contracts --endpoint <slug>` results), interface_standards_md_path, design_ref_path (optional), typecheck_cmd
- Prompt template (multi-line, AI renders by substituting variables): bullets the subagent reads + step-by-step procedure (1. Read capsule. 2. Implement per plan_task_slice. 3. Add `// vg-binding: <id>` to each modified file. 4. Run typecheck. 5. Make ONE commit. 6. Write fingerprint.md. 7. Write read-evidence.json if design-ref. 8. Return JSON with task_id, artifacts_written, commit_sha, bindings_satisfied, fingerprint_path, read_evidence_path.)
- Output JSON contract (return values main agent validates)
- Failure modes table (capsule missing field → error JSON; typecheck fail → error JSON with stderr; multiple commits → R5 catch; binding missing → output validator catch)

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/build/waves-overview.md commands/vg/_shared/build/waves-delegation.md
git commit -m "feat(r2): build waves refs — heavy step 8 delegation

waves-overview.md: STEP 4 entry with HARD-GATE forbid inline impl,
mandatory parallel spawn of N vg-build-task-executor subagents.
Includes vg-narrate-spawn (green chip per spawn) per R1a UX baseline.

waves-delegation.md: input/output contract for subagent. Loads
task content via vg-load --artifact plan --task NN (split file ~50
lines, not full PLAN). Loads contracts via vg-load --artifact
contracts --endpoint <slug> (per-endpoint, not full)."
```

### Task 7: Create _shared/build/post-execution-overview.md + post-execution-delegation.md (HEAVY)

**Files:**
- Create: `commands/vg/_shared/build/post-execution-overview.md`
- Create: `commands/vg/_shared/build/post-execution-delegation.md`

- [ ] **Step 1: Write post-execution-overview.md**

H1 `# build post-execution (STEP 5 — HEAVY)`. HARD-GATE: spawn ONE `vg-build-post-executor` subagent (single, not parallel — this verifier walks all task results sequentially). MUST NOT verify inline.

Pre-spawn checklist:
1. `vg-orchestrator step-active 9_post_execution`
2. Bash: aggregate per-wave results via `vg-load --artifact plan --list` to enumerate task files (UX baseline)
3. For each task in this build: verify `.fingerprints/task-${N}.fingerprint.md` exists (else fail-fast)
4. Spawn vg-build-post-executor with narration:
```bash
bash scripts/vg-narrate-spawn.sh vg-build-post-executor spawning "L2/L3/L5/L6 + truthcheck for ${PHASE_NUMBER}"
```

After return:
```bash
bash scripts/vg-narrate-spawn.sh vg-build-post-executor returned "${N} gates passed, summary written"
```

Validate returned JSON: `gates_passed[]` includes L2/L3/L5/L6, `summary_path` exists, `summary_sha256` matches.

Read `post-execution-delegation.md` for exact prompt template.

- [ ] **Step 2: Write post-execution-delegation.md**

Input contract: task_count, fingerprint_paths, read_evidence_paths, contract_slice_paths, design_ref_paths, design_fidelity_guard_script (= scripts/run-design-fidelity-guard.sh — existing).

Steps the post-executor performs (sequentially per task):
1. L2 fingerprint validation — read each `.fingerprints/task-${N}.fingerprint.md`, run `verify-fingerprint.py`
2. L3 SSIM diff — for tasks with design-ref, compare rendered screenshot vs PNG ref, threshold from `.fidelity-profile.lock`
3. L5 design-fidelity-guard — invoke existing script (which spawns Haiku zero-context)
4. L6 read-evidence — re-hash PNG, compare to `.read-evidence/task-${N}.json`
5. API truthcheck — extract endpoints from PLAN/task-NN.md `<edits-endpoint>` tags, curl `${SANDBOX_URL}/health`, log per-endpoint truthcheck result
6. Gap closure — if any failure, attempt 1 auto-fix iteration; else surface to main
7. Write `${PHASE_DIR}/SUMMARY.md` (single doc — not split, per R1a baseline only LARGE artifacts split)

Output JSON: gates_passed (array), gates_failed (array with per-task reasons), gaps_closed, summary_path, summary_sha256.

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/build/post-execution-overview.md commands/vg/_shared/build/post-execution-delegation.md
git commit -m "feat(r2): build post-execution refs — heavy step 9 delegation

post-execution-overview.md: STEP 5 single-subagent spawn pattern with
narrate-spawn chip. Validates L2-L6 gates + truthcheck inline-deferred
to subagent.

post-execution-delegation.md: input/output for vg-build-post-executor.
Sequential per-task gate walk (L2 fingerprint, L3 SSIM, L5 fidelity,
L6 read-evidence) + API truthcheck + SUMMARY.md write."
```

### Task 8: Create _shared/build/crossai-loop.md

**Files:**
- Create: `commands/vg/_shared/build/crossai-loop.md`

- [ ] **Step 1: Extract bash from backup**

Read backup step `11_crossai_build_verify_loop` (146 lines). Extract verbatim — refactor DEFERRED per spec §1.5 (88% loop fail is architectural, separate round).

Write the ref:
- H1 `# build CrossAI loop (STEP 6 — REFACTOR DEFERRED)`
- Note explicitly that this step is preserved as-is from backup; refactor pending separate round investigation
- Step 6.1 — invoke crossai-build-verify with bash from backup
- Mark step `11_crossai_build_verify_loop`

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/build/crossai-loop.md
git commit -m "feat(r2): build crossai-loop ref — preserves step 11 verbatim

Per spec §1.5, CrossAI loop refactor deferred to separate round (88%
loop fail rate is architectural). This ref captures backup bash without
behavior change so slim entry can route through it."
```

### Task 9: Create _shared/build/close.md

**Files:**
- Create: `commands/vg/_shared/build/close.md`

- [ ] **Step 1: Extract bash from backup**

Read backup steps `10_postmortem_sanity` (90 lines) + `12_run_complete` (395 lines). Extract bash.

Write the ref:
- H1 `# build close (STEP 7)`
- STEP 7.1 — postmortem sanity (`10_postmortem_sanity`) — diff committed files vs PLAN scope, flag unexpected
- STEP 7.2 — run complete (`12_run_complete`) — R7 markers verify gate, display summary, commit artifacts (SUMMARY.md + INTERFACE-STANDARDS.{md,json} + API-DOCS.md + .build-progress.json), traceability gates, terminal `build.completed` telemetry, vg-orchestrator run-complete, tasklist close-on-complete
- Per R1a baseline, commit step writes BOTH legacy single artifacts AND new split artifacts (e.g., BUILD-LOG/wave-*.md generated during waves)

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/build/close.md
git commit -m "feat(r2): build close ref — postmortem + run-complete

STEP 7.1 postmortem (10_postmortem_sanity, scope diff).
STEP 7.2 run-complete (12_run_complete, R7 markers + traceability +
build.completed telemetry + tasklist close)."
```

---

## Phase C — Custom subagents

### Task 10: Create vg-build-task-executor subagent

**Files:**
- Create: `agents/vg-build-task-executor/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

```bash
mkdir -p agents/vg-build-task-executor
```

Write per spec §5.4 first subagent block, ~250 lines. Frontmatter MUST quote description (lessons R1a):

```yaml
---
name: vg-build-task-executor
description: "Execute one build task with full binding context (capsule). Output: artifacts written + commit_sha + bindings_satisfied. ONLY this task."
tools: [Read, Write, Edit, Bash, Glob, Grep]   # narrow; no Agent (no nested spawn), no AskUserQuestion
model: opus
---
```

Body MUST include HARD-GATE block from spec §5.4 verbatim. Then "Step-by-step" section with the 10 imperative procedure points + "Failure modes" section.

**Per R1a UX baseline Req 1**: subagent ALSO writes `${PHASE_DIR}/BUILD-LOG/task-${TASK_ID}.md` (per-task build log: capsule sha, files modified, typecheck output, commit sha, return JSON snapshot). Single SUMMARY.md aggregator concat done by post-executor in Task 7.

Return JSON includes new field: `build_log_path` pointing to the per-task log.

- [ ] **Step 2: Commit**

```bash
git add agents/vg-build-task-executor/SKILL.md
git commit -m "feat(r2): vg-build-task-executor subagent

Per-task parallel executor. Reads capsule, implements one PLAN task,
writes ONE commit with vg-binding citations, fingerprint, read-evidence.

Per R1a UX baseline: also writes BUILD-LOG/task-NN.md (per-task log)
for split artifact pattern. Aggregator concat in post-executor."
```

### Task 11: Create vg-build-post-executor subagent

**Files:**
- Create: `agents/vg-build-post-executor/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

```bash
mkdir -p agents/vg-build-post-executor
```

Frontmatter:
```yaml
---
name: vg-build-post-executor
description: "Verify L2/L3/L5/L6 gates per task + API truthcheck + write SUMMARY.md + concat BUILD-LOG. ONLY this task."
tools: [Read, Write, Edit, Bash, Glob, Grep]   # narrow; no Agent
model: opus
---
```

Body per spec §5.4 second subagent block, ~200 lines. HARD-GATE: process tasks sequentially (not parallel — gates have inter-task assertions); MUST NOT modify task implementations (read-only verifier); MUST NOT skip any L gate without override-debt.

Steps:
1. Read input: task_count, fingerprint_paths, read_evidence_paths, contract_slice_paths, design_ref_paths
2. For each task (sequential): L2 fingerprint validate, L3 SSIM (if design-ref), L5 design-fidelity-guard (Bash to existing script), L6 read-evidence re-hash
3. API truthcheck loop entry (delegates to step 11 crossai loop — defer)
4. Gap closure logic (1 auto-fix attempt then surface)
5. **Per R1a UX baseline**: concat all `${PHASE_DIR}/BUILD-LOG/task-*.md` → `${PHASE_DIR}/BUILD-LOG.md` (Layer 3 flat) + write `${PHASE_DIR}/BUILD-LOG/index.md` (Layer 2 TOC). SUMMARY.md remains single doc.
6. Write `${PHASE_DIR}/SUMMARY.md`
7. Return JSON

Output JSON: `gates_passed`, `gates_failed`, `gaps_closed`, `summary_path`, `summary_sha256`, `build_log_path`, `build_log_index_path`, `build_log_sub_files`.

- [ ] **Step 2: Commit**

```bash
git add agents/vg-build-post-executor/SKILL.md
git commit -m "feat(r2): vg-build-post-executor subagent

Single sequential verifier for L2/L3/L5/L6 gates + API truthcheck +
SUMMARY.md write. Read-only — does NOT modify task implementations.

Per R1a UX baseline Req 1: concats BUILD-LOG/task-*.md (written by
task-executor) into Layer 3 BUILD-LOG.md + Layer 2 BUILD-LOG/index.md."
```

---

## Phase D — Slim entry replacement

### Task 12: Replace build.md body with slim entry

**Files:**
- Modify: `commands/vg/build.md` (4571 → ~500 lines)

- [ ] **Step 1: Write slim entry**

Frontmatter PRESERVED from backup (must_write, must_touch_markers, must_emit_telemetry, forbidden_without_override) — body REPLACED with slim routing per spec §5.2.

Add per R1a UX baseline (per-task split for build artifacts):

```yaml
runtime_contract:
  must_write:
    # Existing
    - "${PHASE_DIR}/SUMMARY.md"
    - path: "${PHASE_DIR}/INTERFACE-STANDARDS.md"
      content_min_bytes: 500
    - path: "${PHASE_DIR}/INTERFACE-STANDARDS.json"
      content_min_bytes: 500
    - path: "${PHASE_DIR}/API-DOCS.md"
      content_min_bytes: 120
    - path: "${PHASE_DIR}/.build-progress.json"
      content_min_bytes: 50
    # NEW per UX baseline Req 1 — per-task build log split
    - path: "${PHASE_DIR}/BUILD-LOG/task-*.md"
      glob_min_count: 1
    - "${PHASE_DIR}/BUILD-LOG/index.md"
    - "${PHASE_DIR}/BUILD-LOG.md"
```

Body: HARD-GATE block + Red Flags table (build-specific from spec §5.2) + 7 STEP routing blocks (each instructs `Read _shared/build/<ref>` and follow exactly + spawn narration for HEAVY steps).

Use the slim entry from R1a `commands/vg/blueprint.md` as structural template (Frontmatter → HARD-GATE → Red Flags → Steps → Diagnostic flow).

- [ ] **Step 2: Verify size**

```bash
wc -l commands/vg/build.md
```
Expected: 400-600 lines.

- [ ] **Step 3: Commit**

```bash
git add commands/vg/build.md
git commit -m "refactor(r2): build.md slim entry (4571 → ~500 lines)

Mirror R1a blueprint slim refactor pattern:
- Frontmatter preserved (must_write/markers/telemetry/forbidden flags)
  + extended with BUILD-LOG split globs per UX baseline Req 1
- Body replaced with HARD-GATE + Red Flags + 7 STEP routing blocks
  to _shared/build/{preflight,context,validate-blueprint,waves-overview,
  post-execution-overview,crossai-loop,close}.md
- Heavy steps (waves, post-execution) instruct Agent spawn with
  narrate-spawn chip per UX baseline Req 2"
```

---

## Phase E — Static tests

### Task 13: Static test for build slim size + structure

**Files:**
- Create: `scripts/tests/test_build_slim_size.py`

- [ ] **Step 1: Write test**

```python
# scripts/tests/test_build_slim_size.py
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENTRY = REPO / "commands/vg/build.md"


def test_build_slim():
    text = ENTRY.read_text()
    lines = text.splitlines()
    assert len(lines) <= 600, f"build.md exceeds 600 lines (got {len(lines)})"


def test_build_imperative_language():
    text = ENTRY.read_text().lower()
    # Must use imperative (You MUST/DO NOT) per Anthropic SKILL.md guidance
    assert "you must" in text, "build.md missing 'You MUST' imperative phrasing"
    assert "do not" in text or "must not" in text, "build.md missing 'Do not'/'MUST NOT'"


def test_build_uses_agent_not_task():
    text = ENTRY.read_text()
    # Tool name is Agent, not Task (Codex correction baked into spec Appendix)
    assert "Agent(subagent_type=" in text or "subagent_type=" in text, "build.md should reference Agent tool"


def test_build_refs_listed_directly():
    text = ENTRY.read_text()
    expected = [
        "_shared/build/preflight.md",
        "_shared/build/context.md",
        "_shared/build/validate-blueprint.md",
        "_shared/build/waves-overview.md",
        "_shared/build/post-execution-overview.md",
        "_shared/build/crossai-loop.md",
        "_shared/build/close.md",
    ]
    for ref in expected:
        assert ref in text, f"build.md missing reference to {ref}"
```

- [ ] **Step 2: Run test**

```bash
pytest scripts/tests/test_build_slim_size.py -v
```
Expected: 4 PASSED.

- [ ] **Step 3: Commit**

```bash
git add scripts/tests/test_build_slim_size.py
git commit -m "test(r2): build slim size + structure (4 assertions)"
```

### Task 14: Static test for build references exist

**Files:**
- Create: `scripts/tests/test_build_references_exist.py`

- [ ] **Step 1: Write test**

```python
# scripts/tests/test_build_references_exist.py
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Per-ref ceiling. Mirror R1a blueprint convention — large refs allowed exceptions
# documented in file header.
REFS = {
    "preflight.md":              500,
    "context.md":                500,
    "validate-blueprint.md":     500,
    "waves-overview.md":         500,
    "waves-delegation.md":       500,
    "post-execution-overview.md": 500,
    "post-execution-delegation.md": 500,
    "crossai-loop.md":           500,
    "close.md":                  500,
}


def test_all_build_refs_exist():
    base = REPO / "commands/vg/_shared/build"
    for ref, ceiling in REFS.items():
        p = base / ref
        assert p.exists(), f"missing ref: {p}"
        assert p.stat().st_size > 100, f"ref {p} too small ({p.stat().st_size} bytes)"
        lines = p.read_text().splitlines()
        assert len(lines) <= ceiling, f"ref {p} exceeds {ceiling} lines (got {len(lines)})"
```

- [ ] **Step 2: Run test**

```bash
pytest scripts/tests/test_build_references_exist.py -v
```
Expected: 1 PASSED.

- [ ] **Step 3: Commit**

```bash
git add scripts/tests/test_build_references_exist.py
git commit -m "test(r2): build refs exist + ceiling check (9 refs)"
```

### Task 15: Static test for build subagent definitions

**Files:**
- Create: `scripts/tests/test_build_subagent_definitions.py`

- [ ] **Step 1: Write test**

```python
# scripts/tests/test_build_subagent_definitions.py
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, f"{path} missing YAML frontmatter"
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def test_task_executor_definition():
    p = REPO / "agents/vg-build-task-executor/SKILL.md"
    assert p.exists(), f"missing {p}"
    fm = _frontmatter(p)
    assert fm.get("name") == "vg-build-task-executor"
    assert fm.get("description", "").startswith('"'), "description must be quoted (R1a YAML lesson)"
    body = p.read_text()
    # Must NOT include Agent in tools (no nested spawn)
    assert "Agent" not in fm.get("tools", ""), "task-executor must not have Agent tool (no nested spawn)"
    # Must include HARD-GATE
    assert "<HARD-GATE>" in body, "task-executor missing HARD-GATE block"


def test_post_executor_definition():
    p = REPO / "agents/vg-build-post-executor/SKILL.md"
    assert p.exists(), f"missing {p}"
    fm = _frontmatter(p)
    assert fm.get("name") == "vg-build-post-executor"
    assert fm.get("description", "").startswith('"'), "description must be quoted"
    body = p.read_text()
    assert "Agent" not in fm.get("tools", ""), "post-executor must not have Agent tool"
    assert "<HARD-GATE>" in body
```

- [ ] **Step 2: Run test**

```bash
pytest scripts/tests/test_build_subagent_definitions.py -v
```
Expected: 2 PASSED.

- [ ] **Step 3: Commit**

```bash
git add scripts/tests/test_build_subagent_definitions.py
git commit -m "test(r2): build subagent definitions (frontmatter + tools allowlist + HARD-GATE)"
```

### Task 16: Static test for build runtime contract split globs

**Files:**
- Create: `scripts/tests/test_build_runtime_contract_split.py`

- [ ] **Step 1: Write test**

```python
# scripts/tests/test_build_runtime_contract_split.py
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENTRY = REPO / "commands/vg/build.md"


def test_must_write_includes_per_task_split():
    """UX baseline Req 1 — build runtime_contract must enforce BUILD-LOG split."""
    text = ENTRY.read_text()
    # Frontmatter must_write block
    fm_m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert fm_m, "build.md missing frontmatter"
    fm = fm_m.group(1)
    # Layer 1 — per-task glob
    assert "BUILD-LOG/task-*.md" in fm, "must_write missing BUILD-LOG/task-*.md (Layer 1)"
    assert "glob_min_count" in fm, "must_write missing glob_min_count assertion"
    # Layer 2 — index
    assert "BUILD-LOG/index.md" in fm, "must_write missing BUILD-LOG/index.md (Layer 2)"
    # Layer 3 — flat concat
    assert "BUILD-LOG.md" in fm, "must_write missing BUILD-LOG.md (Layer 3 concat)"
```

- [ ] **Step 2: Run test**

```bash
pytest scripts/tests/test_build_runtime_contract_split.py -v
```
Expected: 1 PASSED.

- [ ] **Step 3: Commit**

```bash
git add scripts/tests/test_build_runtime_contract_split.py
git commit -m "test(r2): build runtime_contract enforces 3-layer BUILD-LOG split"
```

### Task 17: Update emit-tasklist.py CHECKLIST_DEFS for vg:build canonical names

**Files:**
- Modify: `scripts/emit-tasklist.py:109-125`

- [ ] **Step 1: Verify current CHECKLIST_DEFS for vg:build**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
grep -A 20 '"vg:build":' scripts/emit-tasklist.py | head -25
```

Cross-check the listed step names against `commands/vg/build.md` `must_touch_markers` (R1a lesson — drift between CHECKLIST_DEFS and runtime_contract → workflow_other catch-all).

Expected canonical from current build.md frontmatter:
- preflight: 0_gate_integrity_precheck, 0_session_lifecycle, 1_parse_args, 1a_build_queue_preflight, 1b_recon_gate, create_task_tracker
- context: 2_initialize, 4_load_contracts_and_context
- validate-blueprint: 3_validate_blueprint, 5_handle_branching, 6_validate_phase, 7_discover_plans
- waves: 8_execute_waves, 8_5_bootstrap_reflection_per_wave
- post-execution: 9_post_execution
- crossai-loop: 11_crossai_build_verify_loop
- close: 10_postmortem_sanity, 12_run_complete

- [ ] **Step 2: Update CHECKLIST_DEFS to align with refs (7 groups instead of 5)**

Replace the existing `"vg:build"` block in CHECKLIST_DEFS with:

```python
"vg:build": [
    ("build_preflight", "Build Preflight", [
        "0_gate_integrity_precheck", "0_session_lifecycle", "1_parse_args",
        "1a_build_queue_preflight", "1b_recon_gate", "create_task_tracker",
    ]),
    ("build_context", "Context Loading", [
        "2_initialize", "4_load_contracts_and_context",
    ]),
    ("build_validate_blueprint", "Blueprint And Plan Validation", [
        "3_validate_blueprint", "5_handle_branching", "6_validate_phase",
        "7_discover_plans",
    ]),
    ("build_waves", "Wave Execution", [
        "8_execute_waves", "8_5_bootstrap_reflection_per_wave",
    ]),
    ("build_post_execution", "Post Execution Verification", [
        "9_post_execution",
    ]),
    ("build_crossai", "CrossAI Build Verify", [
        "11_crossai_build_verify_loop",
    ]),
    ("build_close", "Postmortem And Complete", [
        "10_postmortem_sanity", "12_run_complete",
    ]),
],
```

- [ ] **Step 3: Verify alignment**

```bash
python3 scripts/emit-tasklist.py --command vg:build --profile web-fullstack --phase 99 --no-emit 2>&1 | grep -E "Checklists|workflow_other"
```
Expected: 7 group(s); NO `workflow_other` line (= all canonical steps mapped).

- [ ] **Step 4: Commit**

```bash
git add scripts/emit-tasklist.py
git commit -m "fix(r2): emit-tasklist CHECKLIST_DEFS for vg:build canonical names

7 groups aligned with slim refs (preflight, context, validate-blueprint,
waves, post-execution, crossai, close). Avoids R1a workflow_other drift."
```

---

## Phase F — Sync + dogfood

### Task 18: Update sync.sh for build artifacts

**Files:**
- Verify: `sync.sh` already syncs `commands/vg/`, `agents/`, `scripts/` trees.

- [ ] **Step 1: Verify sync coverage**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
grep -E "sync_tree.*vg|sync_tree.*agents|sync_tree.*scripts" sync.sh
```
Expected: lines covering commands/vg, agents, scripts. If new top-level dir was added (none expected for R2), would need a new sync_tree call.

- [ ] **Step 2: Test sync to PrintwayV3**

```bash
DEV_ROOT="/Users/dzungnguyen/Vibe Code/Code/PrintwayV3" bash sync.sh --check 2>&1 | grep -E "build|spawn-guard|vg-build" | head -20
```
Expected: 12+ lines showing UPDATED build.md + 9 refs + 2 agents + spawn-guard test.

- [ ] **Step 3: Apply sync**

```bash
DEV_ROOT="/Users/dzungnguyen/Vibe Code/Code/PrintwayV3" bash sync.sh 2>&1 | tail -3
```
Expected: `Changed: <N>` and `Missing sources: 0`.

- [ ] **Step 4: Commit (if any sync.sh changes were needed)**

If sync.sh required NO changes (R2 reuses R1a tree structure), skip the commit step. Otherwise:

```bash
git add sync.sh
git commit -m "chore(r2): sync.sh covers build artifacts (no-op verify or extension)"
```

### Task 19: Run full pytest suite (regression)

**Files:** N/A (verification step only)

- [ ] **Step 1: Run all R1a + R2 tests together**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
pytest scripts/tests/test_blueprint_*.py scripts/tests/test_build_*.py scripts/tests/test_install_hooks_idempotent.py scripts/tests/test_spawn_guard_count_check.py -v 2>&1 | tail -25
```
Expected: all PASS (R1a 6 + R2 ~10 + install 4 + spawn 4 = ~24 tests).

- [ ] **Step 2: Note pre-existing failures (debt from R1a)**

If pre-existing failures show up (path lookup issues), they are R1a debt — not R2 regression. Document in commit if present:

```bash
pytest scripts/tests/ -v 2>&1 | grep -E "PASSED|FAILED" | wc -l
```

### Task 20: Sync to PrintwayV3 + dogfood `/vg:build <small-phase>`

**Files:** N/A (operational step — needs user collaboration in fresh Claude Code session on PrintwayV3)

- [ ] **Step 1: Pick a small dogfood phase**

Browse `/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.vg/phases/` for a phase with:
- ≤5 tasks (small wave count for fast feedback)
- has PLAN.md + API-CONTRACTS.md + TEST-GOALS.md (blueprint complete)
- NOT phase 1 / 3.2 / 7 (already executed — would conflict)

```bash
ls "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.vg/phases/" | head -10
```

User picks (recommend phase 4 — small, untouched).

- [ ] **Step 2: Open fresh Claude Code session in PrintwayV3 + invoke**

User runs:
```
cd "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
claude
# In session:
/vg:build 4
```

Watch for:
- Tasklist visible in Claude Code UI within first 30 seconds (UX baseline Req — hierarchical projection)
- vg-build-task-executor subagent spawn appears as 🟢 green chip (UX baseline Req 2)
- Hook block (if any) shows 3 lines + file pointer (UX baseline Req 3)
- Wave subagent spawns ALL N at once in single assistant message (NOT one-at-a-time — would violate spec §5.2 HARD-GATE)

- [ ] **Step 3: Verify 12 exit criteria after run**

Per spec §6.4. Run after build completes:

```bash
PHASE=4
RUN_ID=$(jq -r '.run_id' "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.vg/active-runs/"*.json | head -1)
DB="/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.vg/events.db"

echo "=== Exit criteria check ==="
sqlite3 "$DB" "SELECT event_type, COUNT(*) FROM events WHERE run_id='$RUN_ID' GROUP BY event_type ORDER BY event_type" 2>/dev/null
```

Expected events present (per spec §6.4):
- build.tasklist_shown ≥1
- build.native_tasklist_projected ≥1 (THE pilot pass criterion — baseline 1.1%)
- build.started ≥1
- wave.started ≥N (where N = wave count)
- wave.completed ≥N (no silent abort)
- build.completed ≥1
- crossai.verdict ≥1 (deferred refactor — accept whatever)
- vg.block.fired count == vg.block.handled count (Stop hook check)

```bash
ls -la "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.vg/phases/${PHASE}-"*/SUMMARY.md \
       "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.vg/phases/${PHASE}-"*/INTERFACE-STANDARDS.{md,json} \
       "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.vg/phases/${PHASE}-"*/API-DOCS.md \
       "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.vg/phases/${PHASE}-"*/.build-progress.json \
       "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.vg/phases/${PHASE}-"*/BUILD-LOG/index.md \
       "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.vg/phases/${PHASE}-"*/BUILD-LOG/task-*.md
```

Expected: all files exist with non-zero size.

```bash
ls "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.vg/phases/${PHASE}-"*/.step-markers/
```
Expected: all 13 hard-gate markers present (`0_gate_integrity_precheck.done`, ..., `12_run_complete.done`).

- [ ] **Step 4: Manual induce-and-fix tests for spawn-guard + Stop hook**

(a) Spawn-guard shortfall test:
- During a wave with N≥2 tasks, manually instruct AI to "spawn only N-1 tasks, skip task-X"
- Expected: spawn-guard blocks with diagnostic stderr `⛔ vg-agent-spawn-guard: task_id=task-X not in remaining`
- Read `.vg/blocks/${RUN_ID}/PreToolUse-Agent-spawn-count.md` for full diagnostic

(b) Stop hook diagnostic pairing test:
- Induce a block (e.g., delete `.tasklist-projected.evidence.json` mid-run)
- Skip handling — let `vg.block.fired` accumulate without `vg.block.handled`
- Try to complete run via `vg-orchestrator run-complete`
- Expected: Stop hook exits 2 with 3-line stderr + diagnostic file pointer

- [ ] **Step 5: Verdict + summary**

If all 12 exit criteria PASS: R2 build pilot PASSES. Open Phase G to plan R2 test pilot (next).

If any criterion FAIL: R2 PILOT FAILS. Per spec §6.4, return to design phase. Do NOT scale.

Document verdict in:
```bash
cat > docs/superpowers/specs/2026-05-03-vg-r2-build-verdict.md <<EOF
# R2 Build Pilot Verdict

**Date:** $(date -u +%Y-%m-%d)
**Phase tested:** ${PHASE}
**Run ID:** ${RUN_ID}

## Exit criteria (12)
[Fill in PASS/FAIL per spec §6.4 with evidence]

## Verdict
PASS | FAIL

## If PASS: next round
R2 test pilot — separate plan, same infrastructure reuse pattern.

## If FAIL: rollback action
Roll back commands/vg/build.md from .build.md.r2-backup; investigate
which gate failed; re-design before re-attempt.
EOF
```

```bash
git add docs/superpowers/specs/2026-05-03-vg-r2-build-verdict.md
git commit -m "docs(r2): build pilot dogfood verdict + exit criteria evidence"
```

---

## Self-review notes

**Spec coverage check:**
- §1.4 goal "build.md ≤500 lines" → Task 12 (slim entry replacement) + Task 13 (size assertion test)
- §3 audit FAIL "spawn-guard count check" → Task 1 (implementation) + integrated in Task 20 step 4 (manual dogfood)
- §4.1 file layout — 9 refs in `_shared/build/` → Tasks 3-9
- §5.1 strengthened spawn-guard — Task 1
- §5.2 slim entry template → Task 12
- §5.3 reference files (with hybrid nested per blueprint pilot pattern) → Tasks 3-9
- §5.4 2 custom subagents → Tasks 10, 11
- §5.5 hooks SHARED with R1a → no new tasks (reuse R1a Tasks 4-10)
- §5.6 build-specific addendum to vg-meta-skill → handled in Task 12 entry Red Flags table (no separate file edit needed since meta-skill stays generic; build-specific Red Flags live in slim entry)
- §6.3 testing — Tasks 13-16
- §6.4 12 exit criteria — Task 20

**UX baseline coverage check (per `_shared-ux-baseline.md`):**
- Req 1 (per-task split): Task 10 writes BUILD-LOG/task-NN.md; Task 11 concats Layer 3 + Layer 2 index; Task 12 adds globs to runtime_contract; Task 16 asserts split enforced. Plan/contracts loaded via `vg-load --wave/--endpoint` (Tasks 5, 6).
- Req 2 (spawn narration): Tasks 6, 7 include `bash scripts/vg-narrate-spawn.sh` calls in waves-overview + post-execution-overview spawn sites.
- Req 3 (compact hooks): Task 1 spawn-guard new code uses `printf "⛔ ..."` + writes block file (3-line + pointer pattern), reusing R1a hook stderr convention.

**Type/name consistency:**
- All step IDs match `commands/vg/build.md` runtime_contract markers (verified Task 17).
- Subagent names: `vg-build-task-executor`, `vg-build-post-executor` (consistent across spec §5.4, plan Tasks 6/7/10/11/13/15).
- Helper names: `vg-narrate-spawn.sh`, `vg-load.sh` (R1a-shared, no rename).
- Artifact path conventions: `BUILD-LOG/task-NN.md` (Layer 1), `BUILD-LOG/index.md` (Layer 2), `BUILD-LOG.md` (Layer 3) — consistent with R1a `PLAN/`, `API-CONTRACTS/`, `TEST-GOALS/` precedent.

**Placeholder scan:** none found. Each Task has actual code/bash, exact file paths, expected outputs.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-03-vg-r2-build-pilot.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec → quality), fast iteration. REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**2. Inline Execution** — execute tasks in this session with checkpoints. REQUIRED SUB-SKILL: `superpowers:executing-plans`.

Pick 1 or 2.
