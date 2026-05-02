# VG R6a — Deploy Workflow Dedicated Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `commands/vg/deploy.md` (588 → ≤500 lines) by extracting per-env SSH/restart/smoke logic into a new `vg-deploy-executor` subagent. Split reference material into `commands/vg/_shared/deploy/`. Preserve DEPLOY-STATE.json schema (backward compat). Add pytest suite for slim size + subagent delegation + telemetry + schema compat.

**Architecture:** Entry skill `commands/vg/deploy.md` becomes orchestrator (preflight → env selection → user confirm → spawn executor → verify → close). Subagent `.claude/agents/vg-deploy-executor.md` receives `{phase, env, force, vg_config_excerpt, commit_sha}`, runs per-env sequence, writes `deployed.{env}` block to DEPLOY-STATE.json, returns JSON result. Per-env policy (smoke threshold, retry, log retention) lives in `commands/vg/_shared/deploy/env-handling.md` — loaded by subagent only, never by orchestrator.

**Tech Stack:** bash 5+, python3, pytest 7+, jsonschema 4+, ssh client (existing).

**Spec:** `docs/superpowers/specs/2026-05-03-vg-r6a-deploy-design.md`
**Depends on:** R5.5 hooks-source-isolation (subagent allow-list silence on non-VG dogfood).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `commands/vg/_shared/deploy/overview.md` | CREATE | Flow diagram + step contract |
| `commands/vg/_shared/deploy/env-handling.md` | CREATE | Per-env policy table |
| `commands/vg/_shared/deploy/deploy-state.md` | CREATE | DEPLOY-STATE.json schema + r/w rules |
| `commands/vg/_shared/deploy/executor-delegation.md` | CREATE | Subagent input/output contract |
| `.claude/agents/vg-deploy-executor.md` | CREATE | Subagent definition |
| `commands/vg/deploy.md` | REFACTOR | 588 → ≤500 lines slim entry |
| `scripts/hooks/vg-meta-skill.md` | EXTEND | Append deploy Red Flags |
| `tests/skills/__init__.py` | CREATE (if absent) | Mark package |
| `tests/skills/conftest.py` | CREATE (if absent) | Fixture: skill file loader |
| `tests/skills/test_deploy_slim_size.py` | CREATE | Assert deploy.md ≤500 lines |
| `tests/skills/test_deploy_subagent_delegation.py` | CREATE | Assert STEP 4 spawns vg-deploy-executor |
| `tests/skills/test_deploy_telemetry_events.py` | CREATE | Assert frontmatter must_emit complete |
| `tests/skills/test_deploy_state_schema_compat.py` | CREATE | Assert pre-R6a fixture files parse |
| `tests/fixtures/deploy-state/pre-r6a-sandbox.json` | CREATE | Backward-compat fixture |
| `tests/fixtures/deploy-state/pre-r6a-staging.json` | CREATE | Backward-compat fixture |
| `tests/fixtures/deploy-state/pre-r6a-multi-env.json` | CREATE | Backward-compat fixture |

---

## Task 1: Backup current deploy.md + verify pre-conditions

**Files:**
- Read-only: `commands/vg/deploy.md`

- [ ] **Step 1: Confirm R5.5 is merged**

Run: `git log --oneline | grep -E 'r5\.5|hooks-source-isolation' | head -3`

Expected: at least one commit referencing R5.5. If empty, STOP — execute R5.5 plan first.

- [ ] **Step 2: Snapshot current deploy.md line count**

Run: `wc -l commands/vg/deploy.md`

Expected: 588 (or close — record actual). This is the pre-refactor baseline.

- [ ] **Step 3: Identify current STEP boundaries in deploy.md**

Run: `grep -n '^## STEP' commands/vg/deploy.md`

Record the line numbers. Refactor in Task 8-10 will preserve these section anchors so backward-compat references still resolve.

- [ ] **Step 4: Confirm DEPLOY-STATE schema version field**

Run: `grep -A 2 schema_version commands/vg/deploy.md | head -10`

Note the current `schema_version` value (expected: `"1.0"`). Schema will not change in R6a; this records the contract.

- [ ] **Step 5: No commit yet (read-only step)**

Skip.

---

## Task 2: Pytest skill-test infrastructure

**Files:**
- Create: `tests/skills/__init__.py` (if absent)
- Create: `tests/skills/conftest.py` (if absent)

- [ ] **Step 1: Check if `tests/skills/` already exists**

Run: `ls tests/skills/ 2>/dev/null && echo EXISTS || echo MISSING`

If `EXISTS`, skip to Task 3 (the conftest is already in place — read it first to confirm fixtures match the names below).

- [ ] **Step 2: Create `tests/skills/__init__.py` (empty)**

```bash
mkdir -p tests/skills
: > tests/skills/__init__.py
```

- [ ] **Step 3: Create `tests/skills/conftest.py`**

Write to `tests/skills/conftest.py`:

```python
"""Shared fixtures for VG skill (commands/vg/*.md) static tests.

Loads frontmatter + body, exposes line counts and grep helpers.
"""
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMANDS_DIR = REPO_ROOT / "commands" / "vg"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text). Raises if no frontmatter."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    fm = yaml.safe_load(text[4:end])
    body = text[end + 5 :]
    return (fm or {}), body


@pytest.fixture
def skill_loader():
    """Returns a callable: load_skill('deploy') -> {name, lines, frontmatter, body}."""

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
    """Returns a callable: load_agent('vg-deploy-executor') -> {...}."""

    def _load(name: str) -> dict:
        path = AGENTS_DIR / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"agent {name} not at {path}")
        text = path.read_text()
        fm, body = _split_frontmatter(text)
        return {"name": name, "path": path, "text": text, "frontmatter": fm, "body": body}

    return _load


def grep_count(body: str, pattern: str) -> int:
    """Count regex matches across body. Multiline-aware."""
    return len(re.findall(pattern, body, flags=re.MULTILINE))
```

- [ ] **Step 4: Verify pytest collection**

Run: `python3 -m pytest tests/skills/ --collect-only -q`

Expected: `no tests ran` (no test files yet, but conftest must import cleanly).

- [ ] **Step 5: Commit**

```bash
git add tests/skills/__init__.py tests/skills/conftest.py
git commit -m "test(r6a): pytest skill-test infrastructure

Adds skill_loader + agent_loader fixtures and grep_count helper.
Foundation for R6a deploy + R6b amend/debug skill tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

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
flow at a glance. Detailed contracts live in sibling refs.

## Flow diagram

    /vg:deploy <phase> [--env=sandbox|staging|prod] [--force]
       │
       ▼
    STEP 1  Preflight     ── verify phase + build artifact + vg.config env block
       │
       ▼
    STEP 2  Env Selection ── read DEPLOY-STATE.json + vg.config; suggest env
       │
       ▼
    STEP 3  User Confirm  ── AskUserQuestion; block on cancel
       │
       ▼
    STEP 4  Spawn Executor ── narrate-spawn green; Agent(vg-deploy-executor); narrate cyan/red
       │
       ▼
    STEP 5  Verify Result ── DEPLOY-STATE updated; smoke status recorded
       │
       ▼
    STEP 6  Close          ── emit telemetry + write step marker

## Step responsibility split

| Step | Side effects | Tool used | Failure mode |
|---|---|---|---|
| 1    | none (read-only) | Read, Bash | block — direct user to /vg:build |
| 2    | none | Read, Bash | block — env not configured |
| 3    | user input captured | AskUserQuestion | block — user cancels |
| 4    | subagent spawned | Agent | narrate red; do not abort entry |
| 5    | none (validation) | Read | block — schema mismatch |
| 6    | telemetry events + step marker file | Bash | block — emit-event failure |

## When to load other refs

- env-handling.md      — STEP 2 (selection logic) + subagent (per-env policy)
- deploy-state.md      — STEP 5 (verify) + subagent (write)
- executor-delegation.md — STEP 4 (spawn prompt construction)
```

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/deploy/overview.md
git commit -m "docs(r6a): _shared/deploy/overview.md flow ref

Diagram + step responsibility split + ref load triggers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Create _shared/deploy/env-handling.md

**Files:**
- Create: `commands/vg/_shared/deploy/env-handling.md`

- [ ] **Step 1: Write env-handling.md**

Write to `commands/vg/_shared/deploy/env-handling.md`:

```markdown
# Deploy — Env Handling (Shared Reference)

Per-env policy table loaded by `vg-deploy-executor` subagent and by
`commands/vg/deploy.md` STEP 2 (env selection). Orchestrator reads only
the env-selection columns; subagent reads the full table.

## Policy table

| Env     | Smoke threshold              | Auto-rollback | Log retention | Confirm gate |
|---------|------------------------------|---------------|---------------|--------------|
| sandbox | 1 endpoint up                | no            | 7 days        | optional (skip with --yes) |
| staging | 3 endpoints + auth probe     | no            | 30 days       | required |
| prod    | full smoke suite + DB write probe | yes (on smoke fail) | 90 days  | required (2nd factor: out of scope, future) |

## Smoke threshold semantics

- **sandbox** — `curl -fsS <smoke_endpoint_0>`; success = HTTP 200.
- **staging** — first 3 endpoints from `vg.config.md env.staging.smoke_endpoints[]` MUST return 200; auth probe POSTs to `/auth/probe` and expects 200.
- **prod** — all endpoints in `smoke_endpoints[]` MUST return 200, AND a DB write probe (`POST /admin/_probe`) MUST round-trip.

## Auto-rollback semantics (prod only)

If smoke fails on prod:
1. Subagent SSHes to prod host.
2. Runs `<vg.config.deploy.rollback_cmd>` (e.g. `kubectl rollout undo deploy/api`).
3. Re-runs smoke threshold.
4. Returns `{status: "smoke_fail_rolled_back"}` if rollback succeeds, else `{status: "smoke_fail_rollback_failed"}`.

## Log retention

Subagent writes `.vg/phases/<P>/.deploy-log.{env}.txt`. A scheduled cleanup
(out of R6a scope) prunes files older than the env's retention window.

## Env selection logic (used by orchestrator STEP 2)

```python
# pseudocode — actual implementation is bash + jq in deploy.md STEP 2
configured_envs = vg_config.envs.keys()  # e.g. ["sandbox", "staging"]
deployed_envs = {k for k, v in deploy_state.deployed.items() if v is not None}
unsatisfied = [e for e in configured_envs if e not in deployed_envs]
suggested = unsatisfied[0] if unsatisfied else "sandbox"  # always re-deployable
```

## Smoke endpoint resolution

`vg.config.md env.<env>.smoke_endpoints[]` is the canonical source.
Falls back to `[/health]` if absent. Subagent MUST log the resolved
endpoint list to deploy log before SSH.
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/deploy/env-handling.md
git commit -m "docs(r6a): _shared/deploy/env-handling.md per-env policy

Policy table (smoke/rollback/retention/confirm) + smoke semantics +
auto-rollback (prod) + selection logic. Loaded by subagent + STEP 2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Create _shared/deploy/deploy-state.md

**Files:**
- Create: `commands/vg/_shared/deploy/deploy-state.md`

- [ ] **Step 1: Write deploy-state.md**

Write to `commands/vg/_shared/deploy/deploy-state.md`:

```markdown
# Deploy — DEPLOY-STATE.json Contract (Shared Reference)

The single source of truth for "what is deployed where" per phase.

Path: `.vg/phases/<P>/DEPLOY-STATE.json`

## Schema (v1.0 — UNCHANGED in R6a)

```json
{
  "phase": "P1",
  "schema_version": "1.0",
  "deployed": {
    "sandbox": {
      "commit_sha": "abc123",
      "deployed_at": "2026-05-03T14:22:18Z",
      "smoke_status": "pass",
      "exit_code": 0,
      "deploy_log_path": ".vg/phases/P1/.deploy-log.sandbox.txt"
    },
    "staging": null,
    "prod": null
  }
}
```

### Field types

| Field | Type | Required | Notes |
|---|---|---|---|
| `phase` | string | yes | matches phase ID |
| `schema_version` | string | yes | always `"1.0"` in R6a |
| `deployed` | object | yes | keys = env names (sandbox/staging/prod) |
| `deployed.<env>` | object \| null | yes per configured env | null = not yet deployed |
| `deployed.<env>.commit_sha` | string | yes when non-null | git HEAD at deploy time |
| `deployed.<env>.deployed_at` | ISO-8601 UTC | yes | format YYYY-MM-DDTHH:MM:SSZ |
| `deployed.<env>.smoke_status` | enum: pass/fail/partial/skipped | yes | |
| `deployed.<env>.exit_code` | int | yes | subagent exit code |
| `deployed.<env>.deploy_log_path` | string | yes | relative to repo root |

## Read rules

- Orchestrator STEP 2 reads to compute env suggestion.
- Orchestrator STEP 5 reads to verify subagent wrote the block.
- Subagent reads to honor `--force` semantics (allow re-deploy at same commit).
- Downstream consumers (review/test/roam) use `vg-load --phase N --artifact deploy-state --env <e>` (Layer 1 partial).

## Write rules

- ONLY `vg-deploy-executor` subagent writes.
- Atomic write — write to `.tmp` then `mv` over.
- Subagent MUST preserve all other env blocks (only update the target env's block).
- Schema version MUST stay `"1.0"`.

## Backward compatibility

Pre-R6a DEPLOY-STATE.json files MUST parse unchanged. Test fixtures in
`tests/fixtures/deploy-state/pre-r6a-*.json` enforce this.
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/deploy/deploy-state.md
git commit -m "docs(r6a): _shared/deploy/deploy-state.md schema contract

Schema v1.0 (unchanged) + field types + read/write rules + backward
compat invariant.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Create _shared/deploy/executor-delegation.md

**Files:**
- Create: `commands/vg/_shared/deploy/executor-delegation.md`

- [ ] **Step 1: Write executor-delegation.md**

Write to `commands/vg/_shared/deploy/executor-delegation.md`:

```markdown
# Deploy — Executor Delegation Contract (Shared Reference)

The contract between `commands/vg/deploy.md` orchestrator and
`vg-deploy-executor` subagent. Mirrors spec §4 (canonical source).

## Spawn site (orchestrator STEP 4)

```bash
bash scripts/vg-narrate-spawn.sh vg-deploy-executor spawning "phase=$PHASE env=$ENV"
```

Then:

```text
Agent(
  subagent_type="vg-deploy-executor",
  prompt={
    "phase": "<phase_id>",
    "env": "sandbox|staging|prod",
    "force": <bool>,
    "vg_config_excerpt": <env block from vg.config.md>,
    "commit_sha": "<git rev-parse HEAD>",
    "policy_ref": "commands/vg/_shared/deploy/env-handling.md"
  }
)
```

On return:

```bash
bash scripts/vg-narrate-spawn.sh vg-deploy-executor returned "status=$STATUS"
# OR on failure:
bash scripts/vg-narrate-spawn.sh vg-deploy-executor failed "<one-line cause>"
```

## Subagent return value (last line of stdout)

```json
{
  "status": "success" | "smoke_fail" | "smoke_fail_rolled_back" | "smoke_fail_rollback_failed" | "deploy_fail",
  "commit_sha": "abc123",
  "deployed_at": "2026-05-03T14:22:18Z",
  "smoke_status": "pass" | "fail" | "partial" | "skipped",
  "smoke_details": [{"endpoint": "/health", "status": 200}],
  "exit_code": 0,
  "deploy_log_path": ".vg/phases/P1/.deploy-log.sandbox.txt"
}
```

## Orchestrator post-spawn validation (STEP 5)

Orchestrator MUST cross-check:
1. Last stdout line of subagent parses as the JSON shape above.
2. `.vg/phases/<phase>/DEPLOY-STATE.json` `deployed.<env>` block matches the returned `commit_sha`, `deployed_at`, `smoke_status`, `exit_code`, `deploy_log_path`.
3. `<deploy_log_path>` exists.

If any mismatch → emit block `Deploy-State-Mismatch`, do NOT advance.

## Subagent tool restrictions

ALLOWED: Bash, Read, Write, Edit, Grep
FORBIDDEN: Agent (no nested spawns), WebSearch, WebFetch

## Error mode → orchestrator action

| status | orchestrator action |
|---|---|
| success | STEP 5 verify, STEP 6 close |
| smoke_fail (non-prod) | narrate red; surface log to user; do NOT advance |
| smoke_fail_rolled_back (prod) | narrate red + rollback note; surface log; do NOT advance |
| smoke_fail_rollback_failed (prod) | emit hard block `Deploy-Prod-Rollback-Failed` |
| deploy_fail | narrate red; surface log; emit block `Deploy-Executor-Failed` |
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/deploy/executor-delegation.md
git commit -m "docs(r6a): _shared/deploy/executor-delegation.md contract

Spawn site syntax (with narrate-spawn) + return JSON shape +
orchestrator post-spawn validation rules + tool restrictions +
error-mode-to-action mapping.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Backward-compat fixtures + failing schema test

**Files:**
- Create: `tests/fixtures/deploy-state/pre-r6a-sandbox.json`
- Create: `tests/fixtures/deploy-state/pre-r6a-staging.json`
- Create: `tests/fixtures/deploy-state/pre-r6a-multi-env.json`
- Create: `tests/skills/test_deploy_state_schema_compat.py`

- [ ] **Step 1: Create fixture directory**

```bash
mkdir -p tests/fixtures/deploy-state
```

- [ ] **Step 2: Write 3 fixture files**

Write to `tests/fixtures/deploy-state/pre-r6a-sandbox.json`:

```json
{
  "phase": "P1",
  "schema_version": "1.0",
  "deployed": {
    "sandbox": {
      "commit_sha": "f00ba12",
      "deployed_at": "2026-04-30T10:15:22Z",
      "smoke_status": "pass",
      "exit_code": 0,
      "deploy_log_path": ".vg/phases/P1/.deploy-log.sandbox.txt"
    },
    "staging": null,
    "prod": null
  }
}
```

Write to `tests/fixtures/deploy-state/pre-r6a-staging.json`:

```json
{
  "phase": "P2",
  "schema_version": "1.0",
  "deployed": {
    "sandbox": {
      "commit_sha": "abcdef0",
      "deployed_at": "2026-04-28T08:00:00Z",
      "smoke_status": "pass",
      "exit_code": 0,
      "deploy_log_path": ".vg/phases/P2/.deploy-log.sandbox.txt"
    },
    "staging": {
      "commit_sha": "abcdef0",
      "deployed_at": "2026-04-29T14:32:11Z",
      "smoke_status": "pass",
      "exit_code": 0,
      "deploy_log_path": ".vg/phases/P2/.deploy-log.staging.txt"
    },
    "prod": null
  }
}
```

Write to `tests/fixtures/deploy-state/pre-r6a-multi-env.json`:

```json
{
  "phase": "P3",
  "schema_version": "1.0",
  "deployed": {
    "sandbox": {
      "commit_sha": "11111aa",
      "deployed_at": "2026-04-25T12:00:00Z",
      "smoke_status": "pass",
      "exit_code": 0,
      "deploy_log_path": ".vg/phases/P3/.deploy-log.sandbox.txt"
    },
    "staging": {
      "commit_sha": "22222bb",
      "deployed_at": "2026-04-26T13:00:00Z",
      "smoke_status": "partial",
      "exit_code": 0,
      "deploy_log_path": ".vg/phases/P3/.deploy-log.staging.txt"
    },
    "prod": {
      "commit_sha": "33333cc",
      "deployed_at": "2026-04-27T14:00:00Z",
      "smoke_status": "pass",
      "exit_code": 0,
      "deploy_log_path": ".vg/phases/P3/.deploy-log.prod.txt"
    }
  }
}
```

- [ ] **Step 3: Write the schema-compat test**

Write to `tests/skills/test_deploy_state_schema_compat.py`:

```python
"""Backward-compat test: pre-R6a DEPLOY-STATE.json files MUST parse + roundtrip."""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "deploy-state"

REQUIRED_TOP_FIELDS = {"phase", "schema_version", "deployed"}
ENV_REQUIRED_FIELDS = {
    "commit_sha",
    "deployed_at",
    "smoke_status",
    "exit_code",
    "deploy_log_path",
}
SMOKE_STATUS_ENUM = {"pass", "fail", "partial", "skipped"}


@pytest.mark.parametrize(
    "fixture",
    sorted(FIXTURES.glob("pre-r6a-*.json")),
    ids=lambda p: p.name,
)
def test_pre_r6a_fixture_parses(fixture):
    data = json.loads(fixture.read_text())
    missing = REQUIRED_TOP_FIELDS - set(data)
    assert not missing, f"{fixture.name}: missing top-level fields: {missing}"
    assert data["schema_version"] == "1.0"


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("pre-r6a-*.json")), ids=lambda p: p.name)
def test_pre_r6a_env_blocks_well_formed(fixture):
    data = json.loads(fixture.read_text())
    for env, block in data["deployed"].items():
        if block is None:
            continue
        missing = ENV_REQUIRED_FIELDS - set(block)
        assert not missing, (
            f"{fixture.name} env={env}: missing fields {missing}"
        )
        assert block["smoke_status"] in SMOKE_STATUS_ENUM, (
            f"{fixture.name} env={env}: bad smoke_status {block['smoke_status']!r}"
        )
        assert isinstance(block["exit_code"], int), (
            f"{fixture.name} env={env}: exit_code must be int"
        )


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("pre-r6a-*.json")), ids=lambda p: p.name)
def test_pre_r6a_roundtrip_byte_stable(fixture):
    """json.loads -> json.dumps -> compare keys/values (not whitespace)."""
    original = json.loads(fixture.read_text())
    redumped = json.loads(json.dumps(original))
    assert original == redumped
```

- [ ] **Step 4: Run schema-compat test, expect PASS (no skill changes yet)**

Run: `python3 -m pytest tests/skills/test_deploy_state_schema_compat.py -v`

Expected: 9 passed (3 fixtures × 3 tests).

This test guards backward compat — passing now means future R6a refactor cannot break the schema.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/deploy-state/ tests/skills/test_deploy_state_schema_compat.py
git commit -m "test(r6a): pre-R6a DEPLOY-STATE.json schema compat lock

3 fixture files (sandbox-only, staging, multi-env) + parametrized
parse/well-formed/roundtrip tests. Locks schema v1.0 — refactor cannot
break backward compat.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Create vg-deploy-executor subagent

**Files:**
- Create: `.claude/agents/vg-deploy-executor.md`

- [ ] **Step 1: Confirm `.claude/agents/` directory exists**

Run: `ls .claude/agents/ 2>/dev/null | head -5`

If missing, `mkdir -p .claude/agents`.

- [ ] **Step 2: Write the subagent definition**

Write to `.claude/agents/vg-deploy-executor.md`:

```markdown
---
name: vg-deploy-executor
description: Execute per-env deploy sequence (SSH upload, service restart, smoke check, rollback for prod). Spawned by /vg:deploy entry skill. Reports DEPLOY-STATE.json deployed.{env} block + JSON result on stdout last line.
tools: Bash, Read, Write, Edit, Grep
model: claude-sonnet-4-6
---

# vg-deploy-executor

Per-env deploy executor. ALL per-env logic lives here so the orchestrator
in `commands/vg/deploy.md` stays env-agnostic.

## Input contract (from spawning prompt)

You receive a JSON object with these fields:

- `phase`            — phase ID (e.g. "P1")
- `env`              — one of `sandbox|staging|prod`
- `force`            — boolean; if true, re-deploy even at same commit_sha
- `vg_config_excerpt` — the `env.<env>` block from `vg.config.md` (SSH host, build_cmd, deploy_path, smoke_endpoints[], rollback_cmd?)
- `commit_sha`       — current HEAD sha (orchestrator passes; do NOT re-resolve)
- `policy_ref`       — pointer to `commands/vg/_shared/deploy/env-handling.md`

## Workflow

### STEP A — Load policy

Read `commands/vg/_shared/deploy/env-handling.md`. Locate the row for
your `env`. Extract: smoke_threshold rule, auto_rollback flag,
log_retention (informational), confirm_gate (informational).

### STEP B — Preflight

- Verify `<phase>` directory exists at `.vg/phases/<phase>/`.
- Read existing `DEPLOY-STATE.json` if present.
- If `deployed.<env>.commit_sha == <commit_sha>` AND NOT `force` →
  return early with `{status: "deploy_skipped_same_commit", ...}`.
  Orchestrator surfaces this to user.

### STEP C — Build artifact upload

Run `<vg_config_excerpt.build_cmd>` (e.g. `npm run build`).
SCP the resulting artifact to `<vg_config_excerpt.host>:<vg_config_excerpt.deploy_path>`.

Log every command + exit code to `.vg/phases/<phase>/.deploy-log.<env>.txt`.

### STEP D — Service restart

SSH to `<vg_config_excerpt.host>` and run the env-specific restart cmd
from `vg_config_excerpt.restart_cmd`.

### STEP E — Smoke check (per-env policy)

Run smoke per the threshold rule from STEP A. Capture each endpoint
status into `smoke_details[]`. Compute `smoke_status`:
- All endpoints 200 → `"pass"`
- All endpoints non-200 → `"fail"`
- Mixed → `"partial"` (treated as fail for non-prod, fail+rollback for prod)

### STEP F — Rollback (prod only, on smoke fail)

If `env == "prod"` AND smoke_status != "pass":
- Run `<vg_config_excerpt.rollback_cmd>` (e.g. `kubectl rollout undo deploy/api`).
- Re-run smoke.
- If post-rollback smoke passes → `status = "smoke_fail_rolled_back"`.
- Else → `status = "smoke_fail_rollback_failed"`.

### STEP G — Update DEPLOY-STATE.json (atomic)

Read current `.vg/phases/<phase>/DEPLOY-STATE.json` (or create with v1.0
schema if absent). Update ONLY `deployed.<env>` block. Preserve all
other env blocks. Write to `.tmp` then `mv` over.

### STEP H — Return JSON on last stdout line

Print exactly one JSON object as the LAST line of your stdout:

```json
{
  "status": "success" | "smoke_fail" | "smoke_fail_rolled_back" | "smoke_fail_rollback_failed" | "deploy_fail" | "deploy_skipped_same_commit",
  "commit_sha": "<commit_sha>",
  "deployed_at": "<ISO-8601 UTC>",
  "smoke_status": "pass" | "fail" | "partial" | "skipped",
  "smoke_details": [{"endpoint": "/health", "status": 200}],
  "exit_code": <int>,
  "deploy_log_path": ".vg/phases/<phase>/.deploy-log.<env>.txt"
}
```

## Tool restrictions

You MUST NOT use the Agent tool (no nested spawns).
You MUST NOT use WebSearch or WebFetch.
You MAY use Bash for SSH/SCP/curl, Read for vg.config + env-handling +
DEPLOY-STATE, Write for the .tmp + log file, Edit for log appends.

## Failure modes

| Cause | status | log line example |
|---|---|---|
| SSH unreachable | `deploy_fail` | `SSH host unreachable: <host>` |
| Build failure | `deploy_fail` | `Build cmd failed: exit_code=<n>` |
| Smoke fail (non-prod) | `smoke_fail` | `Smoke fail: <endpoint> got <status>` |
| Smoke fail (prod, rollback ok) | `smoke_fail_rolled_back` | `Rollback succeeded; pre-rollback smoke fail` |
| Smoke fail (prod, rollback fail) | `smoke_fail_rollback_failed` | `Rollback FAILED — manual intervention required` |
```

- [ ] **Step 3: Verify subagent file parses (frontmatter)**

Run:
```bash
python3 -c "
import yaml, sys
text = open('.claude/agents/vg-deploy-executor.md').read()
assert text.startswith('---\n')
end = text.find('\n---\n', 4)
fm = yaml.safe_load(text[4:end])
assert fm['name'] == 'vg-deploy-executor'
assert 'Bash' in fm['tools']
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/vg-deploy-executor.md
git commit -m "feat(r6a): vg-deploy-executor subagent

Per-env deploy executor (sandbox/staging/prod). Receives input contract,
runs STEP A-H, writes DEPLOY-STATE.json deployed.<env> block atomically,
returns JSON on last stdout line. Honors prod auto-rollback policy.

Tool-restricted: Bash/Read/Write/Edit/Grep only. No nested Agent spawns.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Failing pytest tests for slim-size + delegation + telemetry

**Files:**
- Create: `tests/skills/test_deploy_slim_size.py`
- Create: `tests/skills/test_deploy_subagent_delegation.py`
- Create: `tests/skills/test_deploy_telemetry_events.py`

- [ ] **Step 1: Write all 3 test files**

Write to `tests/skills/test_deploy_slim_size.py`:

```python
"""Slim entry size guard — commands/vg/deploy.md MUST stay <= 500 lines."""
SLIM_LIMIT = 500


def test_deploy_md_within_slim_limit(skill_loader):
    skill = skill_loader("deploy")
    assert skill["lines"] <= SLIM_LIMIT, (
        f"commands/vg/deploy.md is {skill['lines']} lines (limit {SLIM_LIMIT}). "
        "Push more body content into commands/vg/_shared/deploy/."
    )
```

Write to `tests/skills/test_deploy_subagent_delegation.py`:

```python
"""STEP 4 of deploy.md MUST spawn vg-deploy-executor with narrate-spawn wrap."""
import re

from .conftest import grep_count


def test_step4_spawns_executor(skill_loader):
    skill = skill_loader("deploy")
    body = skill["body"]
    # Must reference Agent spawn for vg-deploy-executor at least once
    spawn_refs = grep_count(
        body,
        r'subagent_type=["\']vg-deploy-executor["\']',
    )
    assert spawn_refs >= 1, (
        "deploy.md does not spawn vg-deploy-executor anywhere; "
        "STEP 4 must call Agent(subagent_type='vg-deploy-executor', ...)"
    )


def test_step4_wraps_spawn_with_narration(skill_loader):
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


def test_step4_section_exists(skill_loader):
    skill = skill_loader("deploy")
    body = skill["body"]
    assert re.search(r"^## STEP 4", body, flags=re.MULTILINE), (
        "STEP 4 section header missing from deploy.md body"
    )


def test_executor_agent_definition_exists(agent_loader):
    agent = agent_loader("vg-deploy-executor")
    assert agent["frontmatter"].get("name") == "vg-deploy-executor"
```

Write to `tests/skills/test_deploy_telemetry_events.py`:

```python
"""Frontmatter must_emit_telemetry MUST list executor + completion events."""

REQUIRED_EVENTS = {
    "deploy.tasklist_shown",
    "deploy.native_tasklist_projected",
    "deploy.executor_spawned",
    "deploy.executor_returned",
    "deploy.executor_failed",
    "deploy.completed",
}


def test_deploy_telemetry_events_complete(skill_loader):
    skill = skill_loader("deploy")
    fm = skill["frontmatter"]
    rc = fm.get("runtime_contract", {})
    emit = set(rc.get("must_emit_telemetry", []))
    missing = REQUIRED_EVENTS - emit
    assert not missing, (
        f"frontmatter must_emit_telemetry missing events: {missing}\n"
        f"current: {sorted(emit)}"
    )
```

- [ ] **Step 2: Run all 3 tests, expect ALL FAIL**

Run: `python3 -m pytest tests/skills/test_deploy_slim_size.py tests/skills/test_deploy_subagent_delegation.py tests/skills/test_deploy_telemetry_events.py -v`

Expected:
- `test_deploy_md_within_slim_limit` — FAIL (588 > 500)
- `test_step4_spawns_executor` — FAIL (no spawn yet)
- `test_step4_wraps_spawn_with_narration` — FAIL
- `test_step4_section_exists` — likely PASS (existing deploy.md probably has STEP 4 header — verify)
- `test_executor_agent_definition_exists` — PASS (Task 8 created the agent)
- `test_deploy_telemetry_events_complete` — FAIL (missing executor_* events)

If `test_step4_section_exists` fails because the current deploy.md uses different STEP heading style, adjust the regex in the test to match actual format BEFORE proceeding — this test must reflect reality, not aspiration.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/skills/test_deploy_slim_size.py tests/skills/test_deploy_subagent_delegation.py tests/skills/test_deploy_telemetry_events.py
git commit -m "test(r6a): failing tests — slim size + delegation + telemetry

Locks the post-refactor contract:
- deploy.md ≤500 lines (currently 588 → must shrink)
- STEP 4 spawns vg-deploy-executor with narrate-spawn wrap
- frontmatter emits executor_{spawned,returned,failed} + completed

Refactor in next tasks makes these pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Refactor deploy.md frontmatter — add telemetry events

**Files:**
- Modify: `commands/vg/deploy.md` (frontmatter `must_emit_telemetry`)

- [ ] **Step 1: Read current frontmatter**

Run: `head -40 commands/vg/deploy.md`

Locate the `runtime_contract.must_emit_telemetry:` block.

- [ ] **Step 2: Add the 3 missing executor events**

In the frontmatter `runtime_contract.must_emit_telemetry` list, add these entries (preserve existing entries):

```yaml
- "deploy.executor_spawned"
- "deploy.executor_returned"
- "deploy.executor_failed"
```

If `deploy.completed` or `deploy.tasklist_shown` or `deploy.native_tasklist_projected` are missing, also add them.

- [ ] **Step 3: Run telemetry test, expect PASS**

Run: `python3 -m pytest tests/skills/test_deploy_telemetry_events.py -v`

Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add commands/vg/deploy.md
git commit -m "feat(r6a): deploy.md frontmatter — add executor telemetry events

Adds deploy.executor_{spawned,returned,failed} to must_emit_telemetry.
Other event names (tasklist_shown, native_tasklist_projected, completed)
already present (or now added).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Refactor deploy.md body — slim entry STEP 4 (spawn executor)

**Files:**
- Modify: `commands/vg/deploy.md` (replace existing per-env logic in STEP 4 with subagent spawn)

- [ ] **Step 1: Identify the existing per-env logic block**

Run:
```bash
awk '/^## STEP 4/,/^## STEP 5/' commands/vg/deploy.md | head -80
```

This is the block that contains current per-env SSH commands. Note the exact line range.

- [ ] **Step 2: Replace STEP 4 body with spawn-executor pattern**

Replace the current STEP 4 body (between `## STEP 4` heading and the next `## STEP` heading) with:

```markdown
## STEP 4 — Spawn vg-deploy-executor

Load contract: `commands/vg/_shared/deploy/executor-delegation.md`.

### 4.1 Pre-spawn narrate (green pill)

Run:

```bash
bash scripts/vg-narrate-spawn.sh vg-deploy-executor spawning "phase=$PHASE env=$ENV"
```

Emit telemetry:

```bash
vg-orchestrator emit-event deploy.executor_spawned --gate STEP-4 \
  --payload "{\"phase\":\"$PHASE\",\"env\":\"$ENV\"}"
```

### 4.2 Spawn the subagent

Resolve the spawn input:

- `phase`             — `$PHASE` from STEP 1
- `env`               — `$ENV` from STEP 2/3
- `force`             — boolean, from `--force` flag
- `vg_config_excerpt` — read `vg.config.md` env.$ENV block (jq)
- `commit_sha`        — `git rev-parse HEAD`
- `policy_ref`        — `commands/vg/_shared/deploy/env-handling.md`

Construct the JSON prompt and spawn:

```
Agent(
  subagent_type="vg-deploy-executor",
  prompt=<JSON described above>
)
```

### 4.3 Post-spawn narrate

On success (subagent returned with `status` ∈ {success, smoke_fail_rolled_back, deploy_skipped_same_commit}):

```bash
bash scripts/vg-narrate-spawn.sh vg-deploy-executor returned "status=$STATUS"
vg-orchestrator emit-event deploy.executor_returned --gate STEP-4 \
  --payload "{\"status\":\"$STATUS\"}"
```

On failure (subagent returned with `status` ∈ {smoke_fail, smoke_fail_rollback_failed, deploy_fail}):

```bash
bash scripts/vg-narrate-spawn.sh vg-deploy-executor failed "<one-line cause>"
vg-orchestrator emit-event deploy.executor_failed --gate STEP-4 \
  --payload "{\"status\":\"$STATUS\",\"cause\":\"<...>\"}"
```

In failure case, do NOT advance to STEP 5; surface deploy log path to user.

See `_shared/deploy/executor-delegation.md` for the full spawn input
schema and orchestrator post-spawn validation rules.
```

- [ ] **Step 3: Run delegation tests, expect PASS**

Run: `python3 -m pytest tests/skills/test_deploy_subagent_delegation.py -v`

Expected: 4 passed (spawn + 2 narrate + section + agent-definition).

- [ ] **Step 4: Run slim-size test (probably still failing, will pass after Task 12)**

Run: `python3 -m pytest tests/skills/test_deploy_slim_size.py -v`

Expected: still FAIL — STEP 4 shrank but STEP 1-3, 5-6 still verbose. Task 12 finishes the slim refactor.

- [ ] **Step 5: Commit**

```bash
git add commands/vg/deploy.md
git commit -m "feat(r6a): deploy.md STEP 4 — spawn vg-deploy-executor

Per-env SSH/restart/smoke logic moved to subagent. STEP 4 now wraps
spawn with vg-narrate-spawn.sh (green/cyan/red pills) and emits
deploy.executor_{spawned,returned,failed} telemetry. Spawn input
contract documented inline + cross-references _shared/deploy/
executor-delegation.md.

Delegation tests pass; slim-size still pending other-step trims.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Refactor deploy.md STEP 1, 2, 3, 5, 6 — push detail to refs

**Files:**
- Modify: `commands/vg/deploy.md`

- [ ] **Step 1: Trim STEP 1 (Preflight)**

Replace current STEP 1 body with:

```markdown
## STEP 1 — Preflight

Verify (in order; block on first failure):

1. `$PHASE` directory exists at `.vg/phases/$PHASE/`.
2. Build artifact present (`PHASE-STATE.md` shows build complete OR `BUILD-STATE.json` exists with `status: "complete"`).
3. `vg.config.md` has an `env.<requested-or-suggested-env>` block.

On block, surface to user with the specific failure cause + a fix
suggestion (e.g. "Run /vg:build $PHASE first").

Emit `deploy.tasklist_shown` after preflight passes.
```

- [ ] **Step 2: Trim STEP 2 (Env Selection)**

Replace current STEP 2 body with:

```markdown
## STEP 2 — Env Selection

Load `commands/vg/_shared/deploy/env-handling.md` (selection logic
section).

Compute:
- `configured_envs`  — keys from `vg.config.md env`
- `deployed_envs`    — keys with non-null block in DEPLOY-STATE.json
- `unsatisfied`      — `configured_envs - deployed_envs`
- `suggested_env`    — `unsatisfied[0]` if non-empty, else `"sandbox"` (always re-deployable)

If user passed `--env=<X>`, use that and skip suggestion.

Else: suggest `suggested_env` and proceed to STEP 3 for confirmation.
```

- [ ] **Step 3: Trim STEP 3 (User Confirm)**

Replace current STEP 3 body with:

```markdown
## STEP 3 — User Confirm Env

Use `AskUserQuestion`:

> "Deploy phase $PHASE to $ENV?"
>
> Options: ["yes", "switch env", "cancel"]

- yes → set `$ENV` for downstream steps; emit `deploy.native_tasklist_projected`.
- switch env → re-run STEP 2 with user's chosen env.
- cancel → abort entry skill (no telemetry beyond what was emitted).

Special case: `$ENV == "sandbox"` AND CLI flag `--yes` set → skip prompt.
```

- [ ] **Step 4: Trim STEP 5 (Verify Result)**

Replace current STEP 5 body with:

```markdown
## STEP 5 — Verify Executor Result

Load `commands/vg/_shared/deploy/deploy-state.md` (write rules section)
and `commands/vg/_shared/deploy/executor-delegation.md` (post-spawn
validation rules).

Cross-checks:
1. Last stdout line of subagent parses as the JSON shape from `executor-delegation.md`.
2. `.vg/phases/$PHASE/DEPLOY-STATE.json` `deployed.$ENV` block matches the returned `commit_sha`, `deployed_at`, `smoke_status`, `exit_code`, `deploy_log_path`.
3. `<deploy_log_path>` file exists.

Any mismatch → emit block `Deploy-State-Mismatch`, surface to user, do
NOT advance to STEP 6.
```

- [ ] **Step 5: Trim STEP 6 (Close)**

Replace current STEP 6 body with:

```markdown
## STEP 6 — Close

Emit telemetry:

```bash
vg-orchestrator emit-event deploy.completed --gate STEP-6 \
  --payload "{\"phase\":\"$PHASE\",\"env\":\"$ENV\",\"status\":\"$STATUS\"}"
```

Write step marker:

```bash
mkdir -p .vg/phases/$PHASE/.step-markers/
touch .vg/phases/$PHASE/.step-markers/deploy-$ENV.done
```

Show user a one-line summary:

> ✅ Deployed phase $PHASE to $ENV at $TIMESTAMP. Log: $DEPLOY_LOG_PATH

End of skill.
```

- [ ] **Step 6: Append References footer**

Append at end of `commands/vg/deploy.md`:

```markdown
---

## References

- Flow + step responsibilities: `commands/vg/_shared/deploy/overview.md`
- Per-env policy + smoke semantics: `commands/vg/_shared/deploy/env-handling.md`
- DEPLOY-STATE.json schema + r/w rules: `commands/vg/_shared/deploy/deploy-state.md`
- Subagent input/output contract: `commands/vg/_shared/deploy/executor-delegation.md`
- UX baseline: `docs/superpowers/specs/_shared-ux-baseline.md`
- R6a design spec: `docs/superpowers/specs/2026-05-03-vg-r6a-deploy-design.md`
```

- [ ] **Step 7: Run all R6a skill tests**

Run: `python3 -m pytest tests/skills/test_deploy_slim_size.py tests/skills/test_deploy_subagent_delegation.py tests/skills/test_deploy_telemetry_events.py tests/skills/test_deploy_state_schema_compat.py -v`

Expected: ALL pass (slim limit, delegation, telemetry, schema-compat).

If `test_deploy_md_within_slim_limit` still fails, run `wc -l commands/vg/deploy.md` and aggressively trim the most verbose remaining section. Push detail to a NEW ref doc if needed (e.g. `_shared/deploy/error-recovery.md`).

- [ ] **Step 8: Commit**

```bash
git add commands/vg/deploy.md
git commit -m "refactor(r6a): deploy.md slim entry — STEP 1/2/3/5/6 trimmed

Push detailed bash + policy explanations to commands/vg/_shared/deploy/
refs. Each STEP body now ≤80 lines: contract surface only. Total file
under 500-line limit. Added References footer pointing to the 4 refs
+ UX baseline + R6a spec.

All R6a skill tests pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: vg-meta-skill.md — append deploy Red Flags

**Files:**
- Modify: `scripts/hooks/vg-meta-skill.md`

- [ ] **Step 1: Append deploy Red Flags section**

Append at end of `scripts/hooks/vg-meta-skill.md`:

```markdown

## Deploy-specific Red Flags

| Thought | Reality |
|---|---|
| "Sandbox env enough, skip staging" | Multi-env spec: each env has own DEPLOY-STATE block |
| "Reuse last deploy state" | DEPLOY-STATE.json must be fresh per invocation |
| "Skip narrate-spawn for vg-deploy-executor — UX nicety only" | Hook does not enforce, but R6a spec §9 makes it MANDATORY for chip-style status visibility |
| "Per-env logic should live in entry skill — easier to read" | Polluting orchestrator AI context is exactly what R6a fixes; keep it in the subagent |
| "Skip post-spawn JSON cross-check, trust the subagent" | Orchestrator MUST verify DEPLOY-STATE matches returned JSON; mismatch = silent corruption |
```

- [ ] **Step 2: Verify markdown still parses**

Run: `python3 -c "from pathlib import Path; t = Path('scripts/hooks/vg-meta-skill.md').read_text(); assert t.count('|') > 100; print('OK')"`

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add scripts/hooks/vg-meta-skill.md
git commit -m "docs(r6a): vg-meta-skill.md — deploy Red Flags appendix

5 entries covering env-skip, stale state, narration skip, inline-vs-
subagent rationalization, JSON cross-check skip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Manual dogfood — sandbox deploy

**Files:** none modified.

- [ ] **Step 1: Pick a test project with sandbox env configured**

Identify a project that has:
- A phase with build complete
- `vg.config.md` env.sandbox block (host, build_cmd, deploy_path, smoke_endpoints)
- Reachable sandbox host (SSH key configured)

If you do not have such a project handy, use a localhost mock: set `vg.config.md env.sandbox.host = "localhost"` and `restart_cmd = "true"`, with `smoke_endpoints = ["http://localhost:8080/health"]` — start a Python http.server on 8080 with a `/health` route returning 200 BEFORE invoking deploy.

- [ ] **Step 2: Invoke /vg:deploy <phase> --env=sandbox**

In the test project's Claude Code session, run the slash command:

```
/vg:deploy P1 --env=sandbox
```

- [ ] **Step 3: Verify chip-style narration**

In the chat, look for:
- 🟢 green pill: `vg-deploy-executor spawning phase=P1 env=sandbox`
- 🔵 cyan pill: `vg-deploy-executor returned status=success`

If pill colors do not appear, check `scripts/vg-narrate-spawn.sh` is executable and ANSI codes render in your terminal.

- [ ] **Step 4: Verify DEPLOY-STATE.json updated**

Run:

```bash
cat .vg/phases/P1/DEPLOY-STATE.json | python3 -m json.tool
```

Expected:
- `deployed.sandbox.commit_sha` matches `git rev-parse HEAD`.
- `deployed.sandbox.smoke_status == "pass"`.
- `deployed.sandbox.deploy_log_path` exists as a file.
- `deployed.staging` and `deployed.prod` still `null` (preserved).

- [ ] **Step 5: Verify telemetry events**

Run:

```bash
sqlite3 .vg/events.db \
  "SELECT event_type FROM events WHERE event_type LIKE 'deploy.%' ORDER BY id DESC LIMIT 10"
```

Expected events present (most recent first):
- `deploy.completed`
- `deploy.executor_returned`
- `deploy.executor_spawned`
- `deploy.native_tasklist_projected`
- `deploy.tasklist_shown`

If any expected event is missing, the corresponding STEP block did not fire — investigate the entry skill flow.

- [ ] **Step 6: Verify step marker file**

Run:

```bash
ls .vg/phases/P1/.step-markers/deploy-sandbox.done
```

Expected: file exists.

- [ ] **Step 7: Failure-path dogfood (optional but recommended)**

Stop the localhost http.server (or break the smoke endpoint) and re-run `/vg:deploy P1 --env=sandbox --force`. Verify:
- 🔴 red pill: `vg-deploy-executor failed Smoke fail: ...`
- DEPLOY-STATE.json `deployed.sandbox.smoke_status == "fail"` (NOT advanced past STEP 5 — orchestrator surfaced log to user).
- `deploy.executor_failed` event present.

- [ ] **Step 8: Final summary**

R6a ship-ready when ALL above pass:
- Sandbox dogfood happy path: chip narration + DEPLOY-STATE updated + telemetry + step marker.
- Failure-path dogfood: red pill + state correctly reflects fail + executor_failed event.
- All 4 pytest test files pass.
- R5.5 hook tests still pass (no regression).

Optional tag:

```bash
git tag -a r6a-deploy-dedicated -m "R6a deploy workflow dedicated subagent extraction"
```

---

## Self-Review

**Spec coverage check:**

| Spec § | Task(s) |
|---|---|
| §3.1 Orchestrator vs executor split | Tasks 8 (subagent), 11+12 (entry refactor) |
| §3.2 Per-env policy table | Task 4 (env-handling.md) |
| §3.3 DEPLOY-STATE schema unchanged | Tasks 5 (deploy-state.md), 7 (compat fixtures + test) |
| §3.4 Slim entry layout (≤500) | Tasks 11 (STEP 4), 12 (STEP 1/2/3/5/6), 9 (slim test) |
| §4.1-4.5 Subagent contract | Tasks 6 (delegation ref), 8 (subagent definition) |
| §5 File and directory layout | All tasks (each row in §5 mapped) |
| §6.1 Error handling | Task 8 STEP F (rollback), Task 11 (failure narration) |
| §6.2 Migration (backward compat) | Task 7 (fixtures + test) |
| §6.3 Pytest static + manual dogfood | Tasks 7, 9, 14 |
| §6.4 Exit criteria 1-6 | Task 14 step 8 (summary) |
| §9 UX baseline | Task 11 (narration), Task 13 (Red Flags) |

No gaps detected.

**Placeholder scan:** searched for TBD/TODO — none in plan body.

**Type/path consistency:**
- Subagent name `vg-deploy-executor` consistent across spec, agent file, delegation ref, entry STEP 4, all 4 pytest files.
- DEPLOY-STATE.json field names (`commit_sha`, `deployed_at`, `smoke_status`, `exit_code`, `deploy_log_path`) consistent across schema doc, fixtures, schema-compat test, subagent STEP H, orchestrator STEP 5.
- Telemetry event names (`deploy.executor_spawned/returned/failed`, `deploy.completed`, etc.) consistent across telemetry test, STEP 4 emit calls, STEP 6 emit call, vg-meta-skill Red Flags.
- File path `commands/vg/_shared/deploy/{overview,env-handling,deploy-state,executor-delegation}.md` consistent across plan + entry References footer.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-03-vg-r6a-deploy.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
