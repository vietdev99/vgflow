# VG R6a — Deploy Workflow Dedicated Implementation Plan (REVISED 2026-05-03)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `commands/vg/deploy.md` (588 → ≤500 lines) by extracting per-env execution logic (Step 1, lines 295–474) into a new `vg-deploy-executor` subagent. Spawn the subagent ONCE per env in the existing sequential loop. Preserve DEPLOY-STATE.json schema, telemetry events, step markers, and all 7 `<rules>` exactly as they are today.

**Architecture:** Entry skill `commands/vg/deploy.md` keeps Step 0 (parse + validate), Step 0a (env select + prod gate), Step 2 (merge results into DEPLOY-STATE), Final (mark + run-complete). Step 1's per-env loop body is replaced by `Agent(subagent_type="vg-deploy-executor")` spawn per env. Subagent runs the canonical sequence (pre → build → restart → health-retry × 6 → seed) and returns a result JSON. Orchestrator collects results and merges in Step 2. Subagent does NOT write DEPLOY-STATE.json — orchestrator-only writer per rule 5 (preserve `preferred_env_for` keys).

**Tech Stack:** bash 5+, python3, pytest 7+, PyYAML.

**Spec:** `docs/superpowers/specs/2026-05-03-vg-r6a-deploy-design.md` (revised companion).
**Depends on:** R5.5 hooks-source-isolation (merged: `d932710`).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `commands/vg/_shared/deploy/overview.md` | CREATE | Flow diagram + step responsibility table |
| `commands/vg/_shared/deploy/per-env-executor-contract.md` | CREATE | Subagent input/output contract |
| `.claude/agents/vg-deploy-executor.md` | CREATE | Subagent definition |
| `commands/vg/deploy.md` | REFACTOR | 588 → ≤500 lines (slim Step 1) |
| `scripts/hooks/vg-meta-skill.md` | EXTEND | Append deploy Red Flags |
| `tests/skills/test_deploy_slim_size.py` | CREATE | Assert ≤500 lines |
| `tests/skills/test_deploy_subagent_delegation.py` | CREATE | Assert Step 1 spawns subagent + narrates |
| `tests/skills/test_deploy_telemetry_preserved.py` | CREATE | Assert phase.deploy_started + phase.deploy_completed retained |
| `tests/skills/test_deploy_step_markers_preserved.py` | CREATE | Assert all 5 markers retained |
| `tests/skills/test_deploy_state_schema_real.py` | CREATE | Assert merge logic preserves real schema (no synthetic fixtures) |

NOTE: NO `tests/fixtures/deploy-state/*.json` files. Repo has no real DEPLOY-STATE.json fixtures (no phase has been deployed) so we exercise the merge logic against synthetic in-memory dicts inside the test, not against on-disk fixtures.

---

## Task 1: Verify R5.5 + snapshot pre-conditions

**Files:** read-only.

- [ ] **Step 1: Confirm R5.5 merged**

Run: `cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix" && git log --oneline | grep -E 'r5\.5|hooks-source-isolation' | head -3`

Expected: at least one commit with `r5.5`. If empty → STOP and execute R5.5 plan first.

- [ ] **Step 2: Snapshot current deploy.md**

Run: `wc -l commands/vg/deploy.md && grep -nE '^## Step|^## Final' commands/vg/deploy.md`

Expected output:
```
588 commands/vg/deploy.md
66:## Step 0 — Parse args, validate prerequisites
125:## Step 0a — Select envs (multi-select) + prod danger gate
281:## Step 1 — Deploy loop (sequential per env)
482:## Step 2 — Merge results into DEPLOY-STATE.json + summary
566:## Final — mark + run-complete
```

(Line numbers may differ slightly if other commits landed; structure must match.)

- [ ] **Step 3: Verify pytest skill-test infra exists**

Run: `ls tests/skills/conftest.py 2>/dev/null && echo EXISTS || echo MISSING`

If `EXISTS` (R5.5 created it OR earlier R6a attempt did), continue. If `MISSING`, refer to `tests/hooks/conftest.py` as a template — copy + adapt for skill tests (replace HOOK_DIR mapping with COMMANDS_DIR / AGENTS_DIR + skill_loader/agent_loader fixtures).

- [ ] **Step 4: No commit (read-only)**

Skip.

---

## Task 2: Skill-test infrastructure (only if missing)

**Files:**
- Create (if absent): `tests/skills/__init__.py`
- Create (if absent): `tests/skills/conftest.py`

- [ ] **Step 1: Skip if Task 1 Step 3 reported EXISTS**

If skill-test infra is already present, jump to Task 3.

- [ ] **Step 2: Create `tests/skills/__init__.py`**

```bash
mkdir -p tests/skills
: > tests/skills/__init__.py
```

- [ ] **Step 3: Create `tests/skills/conftest.py`**

Write to `tests/skills/conftest.py`:

```python
"""Shared fixtures for VG skill (commands/vg/*.md) static tests."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMANDS_DIR = REPO_ROOT / "commands" / "vg"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    fm = yaml.safe_load(text[4:end])
    body = text[end + 5:]
    return (fm or {}), body


@pytest.fixture
def skill_loader():
    def _load(name: str) -> dict:
        path = COMMANDS_DIR / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"skill {name} not at {path}")
        text = path.read_text()
        fm, body = _split_frontmatter(text)
        return {
            "name": name,
            "path": path,
            "text": text,
            "lines": text.count("\n") + (0 if text.endswith("\n") else 1),
            "frontmatter": fm,
            "body": body,
        }
    return _load


@pytest.fixture
def agent_loader():
    def _load(name: str) -> dict:
        # Agents may be stored as `<name>.md` OR as `<name>/` directory.
        md_path = AGENTS_DIR / f"{name}.md"
        dir_path = AGENTS_DIR / name
        path = md_path if md_path.exists() else (dir_path / "agent.md" if (dir_path / "agent.md").exists() else None)
        if path is None or not path.exists():
            raise FileNotFoundError(f"agent {name} not at {md_path} or {dir_path}/agent.md")
        text = path.read_text()
        fm, body = _split_frontmatter(text)
        return {"name": name, "path": path, "text": text, "frontmatter": fm, "body": body}
    return _load


def grep_count(body: str, pattern: str) -> int:
    return len(re.findall(pattern, body, flags=re.MULTILINE))
```

- [ ] **Step 4: Verify pytest collects cleanly**

Run: `python3 -m pytest tests/skills/ --collect-only -q`

Expected: `no tests collected` (no test files yet, no ImportError).

- [ ] **Step 5: Commit (only if files were created)**

```bash
git add tests/skills/__init__.py tests/skills/conftest.py
git commit -m "test(r6a): pytest skill-test infrastructure

skill_loader + agent_loader + grep_count helper. Foundation for
R6a deploy + R6b amend/debug skill tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

If files already existed, skip commit.

---

## Task 3: Create _shared/deploy/overview.md

**Files:**
- Create: `commands/vg/_shared/deploy/overview.md`

- [ ] **Step 1: Create directory**

```bash
mkdir -p commands/vg/_shared/deploy
```

- [ ] **Step 2: Write overview.md**

Write to `commands/vg/_shared/deploy/overview.md`:

```markdown
# Deploy — Overview (Shared Reference)

Loaded by `commands/vg/deploy.md` slim entry. Defines the orchestrator
flow at a glance. Detailed per-env executor contract lives in sibling
`per-env-executor-contract.md`.

## Flow diagram

    /vg:deploy <phase> [--envs=...] [--all-envs] [--dry-run] [--non-interactive] [--prod-confirm-token=...]
       │
       ▼
    Step 0   Parse args, validate prerequisites      (orchestrator)
       │     - resolve phase dir
       │     - check build-complete via PIPELINE-STATE
       │     - emit phase.deploy_started telemetry
       │
       ▼
    Step 0a  Select envs (multi-select) + prod gate  (orchestrator)
       │     - AskUserQuestion (or flags)
       │     - prod 3-option danger gate
       │     - validate envs in vg.config.md
       │
       ▼
    Step 1   Deploy loop (sequential per env)        (orchestrator + subagent)
       │     for env in selected:
       │       narrate-spawn green
       │       Agent(vg-deploy-executor)
       │       narrate-spawn cyan/red
       │       collect result
       │       on failure → AskUserQuestion (continue/skip/abort)
       │
       ▼
    Step 2   Merge results into DEPLOY-STATE.json    (orchestrator)
       │     - read existing (preserve preferred_env_for)
       │     - merge per-env results
       │     - emit phase.deploy_completed telemetry
       │
       ▼
    Final   mark + run-complete                      (orchestrator)

## Step responsibility split

| Step | Owner | Side effects | User interaction |
|---|---|---|---|
| 0    | orchestrator | telemetry start | none |
| 0a   | orchestrator | env selection persisted to vg.config | AskUserQuestion (env multi-select + prod gate) |
| 1    | orchestrator + subagent | deploy log per env | AskUserQuestion only on per-env failure |
| 2    | orchestrator | DEPLOY-STATE.json updated; telemetry end | none |
| Final | orchestrator | step marker + run-complete | none |

## Subagent boundary

`vg-deploy-executor` receives one env's exec context and returns a result
JSON. It does NOT:
- Read or write DEPLOY-STATE.json (orchestrator merges in Step 2 to
  preserve `preferred_env_for` keys per rule 5).
- Spawn other subagents (no nested Agent calls).
- Emit telemetry (orchestrator emits `phase.deploy_*` events).

It DOES:
- Run pre → build → restart → health-retry × 6 → seed.
- Append to `${PHASE_DIR}/.deploy-log.<env>.txt`.
- Return JSON `{env, sha, deployed_at, health, deploy_log, previous_sha, dry_run, error?}`.

## When orchestrator loads which ref

- `overview.md` (this file) — Step 1 + Step 2 (high-level flow).
- `per-env-executor-contract.md` — Step 1 (constructing spawn input + parsing return).
```

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/deploy/overview.md
git commit -m "docs(r6a): _shared/deploy/overview.md flow ref

Diagram + step responsibility table + subagent boundary rules.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Create _shared/deploy/per-env-executor-contract.md

**Files:**
- Create: `commands/vg/_shared/deploy/per-env-executor-contract.md`

- [ ] **Step 1: Write the contract ref**

Write to `commands/vg/_shared/deploy/per-env-executor-contract.md`:

```markdown
# Deploy — Per-Env Executor Contract (Shared Reference)

The contract between `commands/vg/deploy.md` orchestrator (Step 1) and
`vg-deploy-executor` subagent. Mirrors spec §4 (canonical source).

## Spawn site (orchestrator Step 1, per env)

```bash
bash scripts/vg-narrate-spawn.sh vg-deploy-executor spawning "phase=$PHASE env=$ENV"
```

Then construct the prompt JSON and call:

```text
Agent(
  subagent_type="vg-deploy-executor",
  prompt={
    "phase": "<phase id>",
    "phase_dir": "${PHASE_DIR}",
    "env": "<env>",
    "run_prefix": "<from vg.config.md env.<env>.run_prefix>",
    "build_cmd": "<from vg.config.md env.<env>.build_cmd>",
    "restart_cmd": "<from vg.config.md env.<env>.restart_cmd>",
    "health_cmd": "<from vg.config.md env.<env>.health_cmd>",
    "seed_cmd": "<from vg.config.md env.<env>.seed_cmd or empty>",
    "pre_cmd": "<from vg.config.md env.<env>.pre_cmd or empty>",
    "local_sha": "<git rev-parse HEAD>",
    "previous_sha": "<existing deployed.<env>.sha or null>",
    "dry_run": <bool from --dry-run flag>,
    "policy_ref": "commands/vg/_shared/deploy/per-env-executor-contract.md"
  }
)
```

On return:

```bash
# health == "ok" or "dry-run" → cyan
bash scripts/vg-narrate-spawn.sh vg-deploy-executor returned "env=$ENV health=$HEALTH"

# health == "failed" → red
bash scripts/vg-narrate-spawn.sh vg-deploy-executor failed "env=$ENV cause=$ERROR"
```

## Subagent return JSON (last line of stdout)

```json
{
  "env": "sandbox",
  "sha": "abc123",
  "deployed_at": "2026-05-03T14:22:18Z",
  "health": "ok" | "failed" | "dry-run",
  "deploy_log": "${PHASE_DIR}/.deploy-log.sandbox.txt",
  "previous_sha": "f00ba12" | null,
  "dry_run": false,
  "error": null | "<one-line cause>"
}
```

## Subagent workflow

1. **pre_cmd** (if non-empty): Bash → append output to deploy log → if non-zero → return `{health: "failed", error: "pre_cmd exit ${code}"}`.
2. **build_cmd**: `<run_prefix> <build_cmd>` → append → fail on non-zero.
3. **restart_cmd**: `<run_prefix> <restart_cmd>` → append → fail on non-zero.
4. **health retry**: 6 attempts, 5s sleep between. First passing exit code → success. After 6 → `{health: "failed", error: "health_cmd failed after 6 attempts"}`.
5. **seed_cmd** (if non-empty AND health passed): `<run_prefix> <seed_cmd>` → append → fail on non-zero.
6. Capture `deployed_at = $(date -u +%FT%TZ)`, `sha = local_sha`, `deploy_log = ${PHASE_DIR}/.deploy-log.<env>.txt`.
7. Print result JSON on LAST stdout line.

`--dry-run` short-circuit: print commands to deploy log, do NOT execute, return `{health: "dry-run", error: null}` with `sha = local_sha` and current timestamp.

## Tool restrictions

ALLOWED: Bash (SSH/curl/local exec), Read (vg.config.md + this contract), Write/Edit (deploy log file).
FORBIDDEN: Agent (no nested spawns), WebSearch, WebFetch.

Subagent MAY write only to `${PHASE_DIR}/.deploy-log.<env>.txt` (append).
Subagent MUST NOT write to `${PHASE_DIR}/DEPLOY-STATE.json` (orchestrator-only).

## Orchestrator post-spawn handling

After spawn returns:
1. Parse last stdout line as JSON. On parse failure → emit block `Deploy-Executor-Bad-Return`.
2. Verify `<deploy_log>` file exists. On missing → emit block `Deploy-Executor-Missing-Log`.
3. Append result to local accumulator (Python list).
4. If `health == "failed"` AND not `--non-interactive` → AskUserQuestion (continue / skip-failed / abort-all). On `--non-interactive` → continue with next env.
5. Loop to next env or exit Step 1.

## Failure-mode → orchestrator action map

| `health` | `error` example | Orchestrator action |
|---|---|---|
| `ok` | null | Append result, continue next env |
| `dry-run` | null | Append result with `dry_run: true`, continue |
| `failed` | "pre_cmd exit 2" | Narrate red, AskUserQuestion (interactive) or continue (non-interactive) |
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/deploy/per-env-executor-contract.md
git commit -m "docs(r6a): _shared/deploy/per-env-executor-contract.md

Spawn input shape + subagent workflow + return JSON + tool restrictions
+ orchestrator post-spawn handling. Mirrors spec §4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Create vg-deploy-executor subagent

**Files:**
- Create: `.claude/agents/vg-deploy-executor.md`

- [ ] **Step 1: Confirm `.claude/agents/` directory exists**

Run: `ls .claude/agents/ 2>/dev/null | head -5`

If missing: `mkdir -p .claude/agents`.

- [ ] **Step 2: Write the subagent definition**

Write to `.claude/agents/vg-deploy-executor.md`:

```markdown
---
name: vg-deploy-executor
description: Execute per-env deploy sequence (pre → build → restart → health-retry × 6 → seed). Spawned by /vg:deploy entry skill, ONE invocation per env. Returns result JSON on last stdout line. Does NOT write DEPLOY-STATE.json — orchestrator merges results in Step 2 to preserve preferred_env_for keys.
tools: Bash, Read, Write, Edit, Grep
model: claude-sonnet-4-6
---

# vg-deploy-executor

Per-env deploy executor. ALL per-env exec logic lives here so the
orchestrator in `commands/vg/deploy.md` Step 1 stays env-agnostic and
its AI context stays slim.

## Input contract (from spawning prompt)

You receive a JSON object with these fields:

- `phase`         — phase ID (e.g. "P1")
- `phase_dir`     — absolute path to phase directory
- `env`           — env name (e.g. "sandbox")
- `run_prefix`    — string from `vg.config.md env.<env>.run_prefix` (e.g. `ssh user@host` or empty for local)
- `build_cmd`     — string
- `restart_cmd`   — string
- `health_cmd`    — string returning HTTP status or exit code
- `seed_cmd`      — string (or empty)
- `pre_cmd`       — string (or empty)
- `local_sha`     — current git HEAD (orchestrator passes; do NOT re-resolve)
- `previous_sha`  — value of existing `deployed.<env>.sha` or null
- `dry_run`       — boolean
- `policy_ref`    — pointer to `commands/vg/_shared/deploy/per-env-executor-contract.md`

## Workflow

### STEP A — Open deploy log

Compute `deploy_log = <phase_dir>/.deploy-log.<env>.txt`. Touch the file
(create if absent). Append header:

```
=== deploy-executor session ===
phase=<phase> env=<env> dry_run=<dry_run> started=<iso8601>
local_sha=<local_sha> previous_sha=<previous_sha>
```

### STEP B — Dry-run short-circuit

If `dry_run`: print to deploy log:

```
[DRY RUN] would run: pre=<pre_cmd> build=<build_cmd> restart=<restart_cmd> health=<health_cmd> seed=<seed_cmd>
```

Then emit return JSON with `health: "dry-run"` and exit.

### STEP C — pre_cmd (if non-empty)

```bash
if [ -n "$pre_cmd" ]; then
  echo "+ <run_prefix> <pre_cmd>" >> $deploy_log
  <run_prefix> <pre_cmd> >> $deploy_log 2>&1
  rc=$?
  echo "[exit $rc]" >> $deploy_log
  if [ $rc -ne 0 ]; then
    echo '{"env":"<env>","sha":"<local_sha>","deployed_at":"<iso8601>","health":"failed","deploy_log":"<deploy_log>","previous_sha":<previous_sha_or_null>,"dry_run":false,"error":"pre_cmd exit '$rc'"}'
    exit 0
  fi
fi
```

### STEP D — build_cmd

Same shape as STEP C. On non-zero exit → return `health: "failed"`,
`error: "build_cmd exit ${rc}"`.

### STEP E — restart_cmd

Same shape. On non-zero → return failed.

### STEP F — health retry (6 × 5s = 30s total)

```bash
for attempt in 1 2 3 4 5 6; do
  echo "+ health attempt $attempt: <run_prefix> <health_cmd>" >> $deploy_log
  <run_prefix> <health_cmd> >> $deploy_log 2>&1
  rc=$?
  echo "[exit $rc]" >> $deploy_log
  if [ $rc -eq 0 ]; then
    health=ok
    break
  fi
  [ $attempt -lt 6 ] && sleep 5
done

if [ "$health" != "ok" ]; then
  echo '{"env":"<env>","sha":"<local_sha>","deployed_at":"<iso8601>","health":"failed","deploy_log":"<deploy_log>","previous_sha":<previous_sha_or_null>,"dry_run":false,"error":"health_cmd failed after 6 attempts (last exit '$rc')"}'
  exit 0
fi
```

### STEP G — seed_cmd (if non-empty AND health passed)

Same shape. On non-zero → return `health: "failed"`, `error: "seed_cmd exit ${rc}"`.
(Note: build/restart/health succeeded — but seed failed → still classify as failed.)

### STEP H — Emit success JSON

```bash
echo '{"env":"<env>","sha":"<local_sha>","deployed_at":"<iso8601>","health":"ok","deploy_log":"<deploy_log>","previous_sha":<previous_sha_or_null>,"dry_run":false,"error":null}'
```

The JSON MUST be the LAST line of your stdout.

## Tool restrictions

You MUST NOT use the Agent tool (no nested spawns).
You MUST NOT use WebSearch or WebFetch.
You MAY use Bash for SSH/SCP/curl/local exec, Read for vg.config.md + per-env-executor-contract, Write/Edit for the deploy log file ONLY.

You MUST NOT write to or modify `${phase_dir}/DEPLOY-STATE.json` — orchestrator owns that.
You MUST NOT touch any other file in the phase dir or repo.

## Failure mode summary

| Cause | `health` | `error` example |
|---|---|---|
| pre_cmd non-zero | `"failed"` | `"pre_cmd exit ${code}"` |
| build_cmd non-zero | `"failed"` | `"build_cmd exit ${code}"` |
| restart_cmd non-zero | `"failed"` | `"restart_cmd exit ${code}"` |
| health_cmd non-zero × 6 | `"failed"` | `"health_cmd failed after 6 attempts (last exit ${code})"` |
| seed_cmd non-zero | `"failed"` | `"seed_cmd exit ${code}"` |
| dry_run | `"dry-run"` | null |
| all stages pass | `"ok"` | null |
```

- [ ] **Step 3: Verify subagent file frontmatter parses**

Run:
```bash
python3 -c "
import yaml
text = open('.claude/agents/vg-deploy-executor.md').read()
end = text.find('\n---\n', 4)
fm = yaml.safe_load(text[4:end])
assert fm['name'] == 'vg-deploy-executor'
assert 'Bash' in fm['tools']
assert 'Agent' not in fm['tools']
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/vg-deploy-executor.md
git commit -m "feat(r6a): vg-deploy-executor subagent

Per-env deploy executor (sandbox/staging/prod-agnostic). Receives env
context (run_prefix + cmds + sha + dry_run flag), runs STEP A-H
(open log → dry-run check → pre → build → restart → health 6× → seed
→ emit JSON), returns result JSON on last stdout line. Tool-restricted
to Bash/Read/Write/Edit/Grep. No nested Agent spawns. Does NOT write
DEPLOY-STATE.json (orchestrator merges in Step 2 to preserve
preferred_env_for keys per rule 5).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Failing pytest — slim size + delegation + telemetry + markers + schema

**Files:**
- Create: `tests/skills/test_deploy_slim_size.py`
- Create: `tests/skills/test_deploy_subagent_delegation.py`
- Create: `tests/skills/test_deploy_telemetry_preserved.py`
- Create: `tests/skills/test_deploy_step_markers_preserved.py`
- Create: `tests/skills/test_deploy_state_schema_real.py`

- [ ] **Step 1: Write all 5 test files**

Write to `tests/skills/test_deploy_slim_size.py`:

```python
"""Slim entry size guard — commands/vg/deploy.md MUST stay <= 500 lines."""
SLIM_LIMIT = 500


def test_deploy_md_within_slim_limit(skill_loader):
    skill = skill_loader("deploy")
    assert skill["lines"] <= SLIM_LIMIT, (
        f"commands/vg/deploy.md is {skill['lines']} lines (limit {SLIM_LIMIT}). "
        "Refactor Step 1 to spawn vg-deploy-executor instead of inline per-env loop, "
        "and push detail to commands/vg/_shared/deploy/."
    )
```

Write to `tests/skills/test_deploy_subagent_delegation.py`:

```python
"""Step 1 of deploy.md MUST spawn vg-deploy-executor with narrate-spawn wrap."""
import re

from .conftest import grep_count


def test_step1_spawns_executor(skill_loader):
    skill = skill_loader("deploy")
    body = skill["body"]
    spawn_refs = grep_count(
        body,
        r'subagent_type=["\']vg-deploy-executor["\']',
    )
    assert spawn_refs >= 1, (
        "deploy.md does not spawn vg-deploy-executor anywhere; "
        "Step 1 must call Agent(subagent_type='vg-deploy-executor', ...) per env"
    )


def test_step1_wraps_spawn_with_narration(skill_loader):
    skill = skill_loader("deploy")
    body = skill["body"]
    narrate_calls = grep_count(
        body,
        r"vg-narrate-spawn\.sh\s+vg-deploy-executor",
    )
    assert narrate_calls >= 2, (
        "deploy.md MUST wrap vg-deploy-executor spawn with at least 2 "
        "vg-narrate-spawn.sh calls (spawning + returned/failed); "
        f"found {narrate_calls}"
    )


def test_step1_section_exists(skill_loader):
    skill = skill_loader("deploy")
    body = skill["body"]
    assert re.search(r"^## Step 1", body, flags=re.MULTILINE), (
        "Step 1 section header missing from deploy.md body"
    )


def test_executor_agent_definition_exists(agent_loader):
    agent = agent_loader("vg-deploy-executor")
    assert agent["frontmatter"].get("name") == "vg-deploy-executor"
    tools = agent["frontmatter"].get("tools", "")
    if isinstance(tools, list):
        tools_str = " ".join(tools)
    else:
        tools_str = str(tools)
    assert "Agent" not in tools_str, (
        "executor must NOT have Agent tool (no nested spawns)"
    )
```

Write to `tests/skills/test_deploy_telemetry_preserved.py`:

```python
"""deploy.md frontmatter MUST retain phase.deploy_started + phase.deploy_completed.

These events are consumed by downstream env-recommendation gates (review/test/roam
via enrich-env-question.py). Any rename or removal breaks the contract.
"""

REQUIRED_EVENT_TYPES = {"phase.deploy_started", "phase.deploy_completed"}


def test_deploy_telemetry_events_preserved(skill_loader):
    skill = skill_loader("deploy")
    fm = skill["frontmatter"]
    rc = fm.get("runtime_contract", {})
    events = rc.get("must_emit_telemetry", [])
    # Each entry is a dict with `event_type` key (per real frontmatter shape).
    found = {e["event_type"] for e in events if isinstance(e, dict) and "event_type" in e}
    missing = REQUIRED_EVENT_TYPES - found
    assert not missing, (
        f"frontmatter must_emit_telemetry missing event_types: {missing}\n"
        f"current event_types: {sorted(found)}"
    )
```

Write to `tests/skills/test_deploy_step_markers_preserved.py`:

```python
"""deploy.md frontmatter MUST retain all 5 step markers.

Refactor must not drop or rename any marker — the orchestrator relies on
each marker to drive state-machine validation.
"""

REQUIRED_MARKERS = {
    "0_parse_and_validate",
    "0a_env_select_and_confirm",
    "1_deploy_per_env",
    "2_persist_summary",
    "complete",
}


def test_deploy_step_markers_preserved(skill_loader):
    skill = skill_loader("deploy")
    fm = skill["frontmatter"]
    rc = fm.get("runtime_contract", {})
    markers = set(rc.get("must_touch_markers", []))
    missing = REQUIRED_MARKERS - markers
    assert not missing, (
        f"frontmatter must_touch_markers missing: {missing}\n"
        f"current markers: {sorted(markers)}"
    )
```

Write to `tests/skills/test_deploy_state_schema_real.py`:

```python
"""DEPLOY-STATE.json schema invariant — preserved keys + per-env fields.

NO real fixture exists in repo (no phase has been deployed). This test
synthesizes an in-memory pre-deploy state matching the REAL schema and
asserts that a hypothetical Step 2 merge preserves all keys.
"""
import json
from copy import deepcopy

# Real schema fields per spec §3.4 (verified against current deploy.md Step 2).
REAL_PER_ENV_FIELDS = {
    "sha", "deployed_at", "health", "deploy_log", "previous_sha", "dry_run"
}
HEALTH_ENUM = {"ok", "failed", "dry-run"}


def _synthesize_state() -> dict:
    """Build an in-memory pre-deploy state mirroring real schema."""
    return {
        "phase": "P1",
        "deployed": {
            "sandbox": {
                "sha": "f00ba12",
                "deployed_at": "2026-04-30T10:15:22Z",
                "health": "ok",
                "deploy_log": ".vg/phases/P1/.deploy-log.sandbox.txt",
                "previous_sha": None,
                "dry_run": False,
            },
            "staging": None,
            "prod": None,
        },
        "preferred_env_for": {"feature_x": "staging"},
        "preferred_env_for_skipped": False,
    }


def _merge_executor_result(state: dict, result: dict) -> dict:
    """Reference merge logic — MUST match commands/vg/deploy.md Step 2 behavior.

    Preserves all top-level non-deployed keys; updates only deployed.<env>.
    """
    new_state = deepcopy(state)
    env = result["env"]
    new_state["deployed"][env] = {
        "sha": result["sha"],
        "deployed_at": result["deployed_at"],
        "health": result["health"],
        "deploy_log": result["deploy_log"],
        "previous_sha": result["previous_sha"],
        "dry_run": result["dry_run"],
    }
    return new_state


def test_state_round_trip_preserves_preferred_env_for():
    state = _synthesize_state()
    result = {
        "env": "staging",
        "sha": "abcdef0",
        "deployed_at": "2026-05-03T14:32:11Z",
        "health": "ok",
        "deploy_log": ".vg/phases/P1/.deploy-log.staging.txt",
        "previous_sha": None,
        "dry_run": False,
        "error": None,
    }
    merged = _merge_executor_result(state, result)
    assert merged["preferred_env_for"] == {"feature_x": "staging"}, "must preserve preferred_env_for"
    assert merged["preferred_env_for_skipped"] is False, "must preserve preferred_env_for_skipped"
    assert merged["deployed"]["sandbox"]["sha"] == "f00ba12", "must not overwrite other env's block"
    assert merged["deployed"]["staging"]["sha"] == "abcdef0", "must update target env block"


def test_per_env_fields_complete():
    state = _synthesize_state()
    sandbox = state["deployed"]["sandbox"]
    missing = REAL_PER_ENV_FIELDS - set(sandbox)
    assert not missing, f"synthesized fixture missing real fields: {missing}"
    assert sandbox["health"] in HEALTH_ENUM


def test_executor_result_shape_compatible_with_merge():
    """The subagent return JSON shape must be sufficient to populate per-env block."""
    result = {
        "env": "sandbox", "sha": "abc", "deployed_at": "2026-05-03T00:00:00Z",
        "health": "ok", "deploy_log": "/tmp/log.txt",
        "previous_sha": None, "dry_run": False, "error": None,
    }
    state = _synthesize_state()
    merged = _merge_executor_result(state, result)
    block = merged["deployed"]["sandbox"]
    assert set(block) == REAL_PER_ENV_FIELDS, (
        f"merged block has wrong fields: {set(block)} vs {REAL_PER_ENV_FIELDS}"
    )
```

- [ ] **Step 2: Run all 5 tests, expect mixed results**

Run: `python3 -m pytest tests/skills/ -v`

Expected:
- `test_deploy_md_within_slim_limit` — FAIL (588 > 500)
- `test_step1_spawns_executor` — FAIL (no spawn yet)
- `test_step1_wraps_spawn_with_narration` — FAIL
- `test_step1_section_exists` — PASS (real Step 1 exists today)
- `test_executor_agent_definition_exists` — PASS (Task 5 created it)
- `test_deploy_telemetry_events_preserved` — PASS (already correct today)
- `test_deploy_step_markers_preserved` — PASS (already correct today)
- 3× `test_state_round_trip_*` etc. — PASS (in-memory tests, no skill changes needed)

If any of the "PASS today" tests fail, investigate before proceeding.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/skills/
git commit -m "test(r6a): failing tests — slim size + delegation; passing baseline tests for telemetry + markers + schema

Locks the post-refactor contract:
- deploy.md ≤500 lines (currently 588 → must shrink)
- Step 1 spawns vg-deploy-executor with narrate-spawn wrap
Plus baseline locks (passing today, must stay passing):
- frontmatter retains phase.deploy_started + phase.deploy_completed
- frontmatter retains all 5 step markers
- DEPLOY-STATE schema preserved (in-memory tests; no on-disk fixtures)

Refactor in next task makes the failing tests pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Refactor deploy.md Step 1 — replace inline per-env loop with subagent spawn

**Files:**
- Modify: `commands/vg/deploy.md` (Step 1 body, lines ~281–474)

- [ ] **Step 1: Re-read current Step 1 body**

Run:
```bash
awk '/^## Step 1/,/^## Step 2/' commands/vg/deploy.md > /tmp/step1-current.md
wc -l /tmp/step1-current.md
```

Note the line range and total. The replacement should be substantially shorter (~70 lines vs ~190 lines).

- [ ] **Step 2: Replace Step 1 body**

Locate `## Step 1 — Deploy loop (sequential per env)` heading and the next `## Step 2` heading. Replace EVERYTHING between them (preserve those two heading lines themselves) with:

```markdown
## Step 1 — Deploy loop (sequential per env)

Load contract: `commands/vg/_shared/deploy/per-env-executor-contract.md`.

Per-env work is delegated to `vg-deploy-executor` subagent. Orchestrator
loop only constructs spawn input, narrates, collects results, and asks
user on per-env failure (rule 4).

Touch step marker:

```bash
mkdir -p ${PHASE_DIR}/.step-markers/deploy
touch ${PHASE_DIR}/.step-markers/deploy/1_deploy_per_env.done
```

Initialize accumulator:

```bash
results_json=".tmp/deploy-results.json"
mkdir -p .tmp
echo "[]" > $results_json
```

For each env in `$SELECTED_ENVS`:

```bash
for ENV in $SELECTED_ENVS; do
  # Resolve config for this env (reads vg.config.md ONCE per env)
  RUN_PREFIX=$(python3 scripts/lib/vg-config-extract.py "env.$ENV.run_prefix" || echo "")
  BUILD_CMD=$(python3 scripts/lib/vg-config-extract.py "env.$ENV.build_cmd")
  RESTART_CMD=$(python3 scripts/lib/vg-config-extract.py "env.$ENV.restart_cmd")
  HEALTH_CMD=$(python3 scripts/lib/vg-config-extract.py "env.$ENV.health_cmd")
  SEED_CMD=$(python3 scripts/lib/vg-config-extract.py "env.$ENV.seed_cmd" || echo "")
  PRE_CMD=$(python3 scripts/lib/vg-config-extract.py "env.$ENV.pre_cmd" || echo "")

  LOCAL_SHA=$(git rev-parse HEAD)
  PREVIOUS_SHA=$(python3 -c "
import json,sys
try:
    d = json.load(open('${PHASE_DIR}/DEPLOY-STATE.json'))
    print(d.get('deployed', {}).get('$ENV', {}).get('sha') or '')
except: print('')
")

  # ─── Spawn vg-deploy-executor ───
  bash scripts/vg-narrate-spawn.sh vg-deploy-executor spawning "phase=$PHASE_NUMBER env=$ENV"

  # Construct prompt JSON and spawn:
  #   Agent(
  #     subagent_type="vg-deploy-executor",
  #     prompt={ phase, phase_dir, env, run_prefix, build_cmd, restart_cmd,
  #              health_cmd, seed_cmd, pre_cmd, local_sha, previous_sha,
  #              dry_run, policy_ref }
  #   )
  # → returns JSON on last stdout line

  # Capture subagent stdout, extract last line as result JSON
  RESULT_JSON=$(... last line of subagent stdout ...)
  HEALTH=$(echo "$RESULT_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['health'])")
  ERROR=$(echo "$RESULT_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('error') or 'none')")

  if [ "$HEALTH" = "failed" ]; then
    bash scripts/vg-narrate-spawn.sh vg-deploy-executor failed "env=$ENV cause=$ERROR"
  else
    bash scripts/vg-narrate-spawn.sh vg-deploy-executor returned "env=$ENV health=$HEALTH"
  fi

  # Append to accumulator
  python3 -c "
import json,sys
acc = json.load(open('$results_json'))
acc.append(json.loads('''$RESULT_JSON'''))
json.dump(acc, open('$results_json', 'w'), indent=2)
"

  # Per-env failure handling (rule 4)
  if [ "$HEALTH" = "failed" ] && [ "$NON_INTERACTIVE" != "true" ]; then
    # AskUserQuestion: "Env $ENV failed. Continue / Skip-failed-as-recorded / Abort all?"
    # On 'abort-all' → break loop
    # On 'continue'  → next iteration
    # On 'skip-failed' → next iteration (failure recorded, no further action)
    :
  fi
done
```

See `_shared/deploy/per-env-executor-contract.md` for the full spawn input
schema and orchestrator post-spawn validation rules.
```

- [ ] **Step 3: Run all 5 R6a tests**

Run: `python3 -m pytest tests/skills/test_deploy_*.py -v`

Expected: ALL 5 + 3 sub-tests pass (slim size now ≤500, Step 1 spawns executor, narration count ≥2, telemetry/markers/schema preserved).

If `test_deploy_md_within_slim_limit` still fails, run `wc -l commands/vg/deploy.md` and identify which other section to trim. Push detail to `_shared/deploy/per-env-executor-contract.md` if needed.

- [ ] **Step 4: Commit**

```bash
git add commands/vg/deploy.md
git commit -m "refactor(r6a): deploy.md Step 1 — spawn vg-deploy-executor per env

Per-env work (config parsing + pre/build/restart/health-retry/seed)
delegated to vg-deploy-executor subagent. Orchestrator loop only:
- constructs spawn input (vg.config.md env block + sha + dry_run)
- narrates green/cyan/red pill per spawn
- collects result JSON
- handles per-env failure via AskUserQuestion (rule 4 preserved)

Step 1 body shrunk from ~190 lines to ~70 lines. Total file ≤500.

Telemetry events (phase.deploy_started, phase.deploy_completed) and all
5 step markers UNCHANGED — refactor only restructures Step 1 internals.

All 5 R6a pytest tests pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: vg-meta-skill.md — append deploy Red Flags

**Files:**
- Modify: `scripts/hooks/vg-meta-skill.md`

- [ ] **Step 1: Append deploy Red Flags section**

Append at end of `scripts/hooks/vg-meta-skill.md`:

```markdown

## Deploy-specific Red Flags

| Thought | Reality |
|---|---|
| "Spawn vg-deploy-executor with parallel envs for speed" | Rule 2: sequential — parallel risks shared SSH/DB contention. R7 may add `--parallel-envs`; until then keep sequential. |
| "Subagent should write DEPLOY-STATE.json directly" | NO — orchestrator-only writer to preserve `preferred_env_for` keys per rule 5. Subagent returns JSON; Step 2 merges. |
| "Skip narrate-spawn for vg-deploy-executor — UX nicety only" | UX baseline R2 makes it MANDATORY. Each env iteration → green pill at start, cyan/red at end. |
| "Health check 1× is enough" | 6× retry with 5s sleep (30s total) is the contract. Reducing masks transient cold-start failures. |
| "Dry-run can skip emitting result JSON" | Dry-run MUST emit JSON with `health: "dry-run"` so orchestrator merge in Step 2 has a record to write. |
| "Add a schema_version to DEPLOY-STATE.json — best practice" | R6a explicitly does NOT introduce one. Existing consumers don't expect it. |
```

- [ ] **Step 2: Verify markdown still parses**

Run: `python3 -c "from pathlib import Path; t = Path('scripts/hooks/vg-meta-skill.md').read_text(); assert t.count('|') > 100; print('OK')"`

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add scripts/hooks/vg-meta-skill.md
git commit -m "docs(r6a): vg-meta-skill.md — deploy Red Flags appendix

6 entries covering parallel-env temptation, schema-write boundary,
narration-skip, health retry shrink, dry-run JSON skip, schema_version
introduction.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Mock dogfood — stubbed sandbox env

**Files:** none modified — verification only.

- [ ] **Step 1: Set up stub vg.config**

Pick a phase directory in this repo with PIPELINE-STATE showing build complete (or temporarily stub PIPELINE-STATE to fake it). Add a temporary env block to `.claude/vg.config.md` (or its equivalent for this project):

```yaml
env:
  sandbox:
    run_prefix: ""
    build_cmd: "true"
    restart_cmd: "true"
    health_cmd: "echo healthy"
    seed_cmd: ""
    pre_cmd: ""
```

(No real SSH; all commands run locally and trivially succeed.)

- [ ] **Step 2: Invoke /vg:deploy with non-interactive flag**

Run the slash command in a Claude Code session:

```
/vg:deploy <phase> --envs=sandbox --non-interactive
```

- [ ] **Step 3: Verify chip narration**

Look in chat for:
- 🟢 green pill: `vg-deploy-executor spawning phase=<phase> env=sandbox`
- 🔵 cyan pill: `vg-deploy-executor returned env=sandbox health=ok`

If pill colors absent, check `scripts/vg-narrate-spawn.sh` is executable and ANSI codes render in your terminal.

- [ ] **Step 4: Verify DEPLOY-STATE.json populated**

```bash
cat ${PHASE_DIR}/DEPLOY-STATE.json | python3 -m json.tool
```

Expected:
- `phase` = your phase number
- `deployed.sandbox.sha` = `git rev-parse HEAD`
- `deployed.sandbox.health` = `"ok"`
- `deployed.sandbox.deploy_log` exists as a real file
- `deployed.sandbox.previous_sha` = null (first deploy) or prior sha
- `deployed.sandbox.dry_run` = false
- Other env keys (staging/prod) absent OR null
- `preferred_env_for*` keys preserved if previously set

- [ ] **Step 5: Verify telemetry events**

```bash
sqlite3 .vg/events.db \
  "SELECT event_type FROM events WHERE event_type LIKE 'phase.deploy_%' ORDER BY id DESC LIMIT 5"
```

Expected events present:
- `phase.deploy_completed`
- `phase.deploy_started`

If either missing → Step 0 or Step 2 didn't fire — investigate.

- [ ] **Step 6: Verify step markers**

```bash
ls ${PHASE_DIR}/.step-markers/deploy/
```

Expected: `0_parse_and_validate.done`, `0a_env_select_and_confirm.done`, `1_deploy_per_env.done`, `2_persist_summary.done`, `complete.done`.

- [ ] **Step 7: Failure-path dogfood (optional)**

Modify the stub `health_cmd: "false"` (always exits 1) and re-run with `--envs=sandbox --non-interactive`. Verify:
- 🔴 red pill: `vg-deploy-executor failed env=sandbox cause=health_cmd failed after 6 attempts...`
- DEPLOY-STATE.json `deployed.sandbox.health = "failed"`
- Run completes (no abort) because non-interactive defaults to continue

- [ ] **Step 8: Restore vg.config.md**

Remove the stub `env.sandbox` block (or restore the real one). Do NOT commit the stub.

- [ ] **Step 9: Final summary**

R6a ship-ready when ALL above pass:
- 5/5 pytest tests pass
- Mock sandbox dogfood: chip narration + DEPLOY-STATE populated + telemetry + markers
- Failure-path dogfood: red pill + state correctly reflects fail
- R5.5 hook tests still pass (no regression)

Optional tag:

```bash
git tag -a r6a-deploy-dedicated -m "R6a deploy workflow dedicated subagent extraction"
```

---

## Self-Review

**Spec coverage:**

| Spec § | Task(s) |
|---|---|
| §3.1 Orchestrator vs executor split | Tasks 5 (subagent), 7 (entry refactor) |
| §3.2 What stays in orchestrator | Task 7 (Step 1 keeps loop control + AskUserQuestion) |
| §3.3 What moves to subagent | Task 5 (subagent body STEP A-H) |
| §3.4 DEPLOY-STATE schema (UNCHANGED) | Tasks 6 (schema_real test), 8 (Red Flags) |
| §3.5 Slim entry layout (≤500) | Tasks 6 (slim size test), 7 (refactor) |
| §4 Subagent contract | Tasks 4 (contract ref), 5 (subagent definition) |
| §5 File and directory layout | All tasks |
| §6 Telemetry events (UNCHANGED) | Tasks 6 (telemetry_preserved test) |
| §7.1 Error handling | Task 5 (failure modes), Task 7 (orchestrator failure handling) |
| §7.3 Pytest static + mock dogfood | Tasks 6, 9 |
| §7.4 Exit criteria 1-6 | Task 9 step 9 |
| §10 UX baseline | Task 7 (narration in Step 1), Task 8 (Red Flags) |

No gaps detected.

**Placeholder scan:** searched for TBD/TODO — none in plan body.

**Type/path consistency:**
- Subagent name `vg-deploy-executor` consistent across spec, agent file, contract ref, entry Step 1, all 5 pytest files.
- DEPLOY-STATE.json field names (`sha`, `deployed_at`, `health`, `deploy_log`, `previous_sha`, `dry_run`) consistent. NO `schema_version` anywhere — explicit decision.
- Telemetry event names (`phase.deploy_started`, `phase.deploy_completed`) consistent.
- Step marker names (5 markers) consistent across plan + spec + tests.
- File path `commands/vg/_shared/deploy/{overview,per-env-executor-contract}.md` consistent.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-03-vg-r6a-deploy.md` (REVISED). Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints.

Which approach?
