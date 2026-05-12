# Lifecycle-specs generator redesign — Design v5.0

**Date:** 2026-05-13
**Status:** Design v1 — based on audit findings + Codex GPT-5.5 second-opinion
**Trigger:** Audit revealed `scripts/generate-lifecycle-specs.py` is scaffold generator (template-filled placeholder), not contract source. v4.1 deferred items already wired existing primitives; this is the upstream content fix.

## Bottom line

Codex's verdict: *"v4.0 pipeline lane reorder đúng hướng (review → test-spec → test), nhưng `generate-lifecycle-specs.py` chưa đủ chín để làm 'contract source'. Hiện trạng là scaffold generator, không phải contract source. Chừng nào chưa sửa, `vg:test-spec` đang produce confidence nhiều hơn truth."*

→ Cần shift architecture từ "static-spec scaffold + LLM refines" → "static-spec rich, LLM minimal".

## 14 gaps (11 audit + 3 Codex)

| # | Gap | Severity | Batch |
|---|---|---|---|
| G1 | preconditions hardcoded 4-bullet boilerplate | Real | 4 |
| G2 | RCRURDR always 7-stage even for delete-only | Code smell | 2 |
| G3 | step body template-interpolated strings | Real | 3 |
| G4 | actor inference via word match (admin/owner) | Real | 4 |
| G5 | fixture DAG hardcoded 2-template | Real | 4 |
| G6 | artifact_capture single boilerplate entry | Real | 4 |
| **G7** | **no endpoint binding in steps** | **CRITICAL** | **1** |
| G8 | freeform success_criteria, no discrete assertions | Real | 3 |
| **G9** | **D-XX decisions không propagate** | **CRITICAL** | **1** |
| G10 | read-only goals skip lifecycle entirely | High | 2 |
| G11 | no runtime contract conformance check | Real | 3 |
| **G12** | **multi-actor steps collapse về actor[0] (line 310-334)** | **CRITICAL** | **1** |
| G13 | validator chỉ check shape không check semantic | Systemic | 3 |
| G14 | read-only goals rơi khỏi v4.0 pipeline (no codegen, test BLOCK) | Coverage hole | 2 |
| G15 | contract fragmentation (5 source artifacts no single truth) | Architecture | Defer to v5.1 |

## Architecture target

**From:**
```
TEST-GOALS.md (text) → generator (regex+templates) → LIFECYCLE-SPECS.json (placeholders) → LLM codegen (re-derives from text)
```

**To:**
```
TEST-GOALS.md + API-CONTRACTS.md + CONTEXT.md (D-XX)
   → generator (multi-source bind)
   → LIFECYCLE-SPECS.json (rich contract with endpoint/actor/decision binding)
   → LLM codegen (renders only — no decision making)
```

## Batch 1 — Critical (this design, ship first)

### G12: Multi-actor step switching

**Problem:** `_step()` lines 310-334 use single `actor_id = actors[0]["id"]` for all 7 stages. Multi-actor goals execute as single-actor in lifecycle.

**Fix:**
- Per-stage actor inference based on stage semantics + goal text
- Mutation stage (`create`/`update`/`delete`) → primary actor
- Approval/review stage → reviewer/approver actor
- Each step entry carries explicit `actor` field
- Validator (G13 preview) checks actor coverage

**API change:**
```python
def _step(stage: str, goal: dict, actors: list[dict]) -> dict:
    actor_id = _stage_actor(stage, goal, actors)  # NEW: per-stage resolution
    return {...}
```

### G7: Endpoint binding from API-CONTRACTS.md

**Problem:** Steps don't bind endpoint URL/method/payload. Codegen has to re-derive from TEST-GOAL text → drift.

**Fix:**
- Read `${PHASE_DIR}/API-CONTRACTS.md` (existing artifact)
- Parse endpoint entries (`## METHOD /path` headers + schema bodies)
- Match endpoint per stage via goal's `mutation_evidence` / `dependencies` / goal title
- Each step gets `endpoint: {method, path, request_schema_ref, response_schema_ref}` field

**API addition:**
```python
def _bind_endpoint(stage: str, goal: dict, contracts: dict) -> dict | None:
    """Bind stage to API contract entry. Returns {method, path, schemas} or None."""
```

### G9: D-XX propagation from CONTEXT.md

**Problem:** Decisions (`D-7: max 3 retry, expected 429`) live in `CONTEXT.md`. Generator never reads it. Codegen has to discover via text mining → drift.

**Fix:**
- Read `${PHASE_DIR}/CONTEXT.md` decisions block
- Per-goal `decision_refs` array (e.g. `["D-7", "D-14"]`) — explicit refs goal touches
- Per-decision `expected_assertion` propagated into relevant step's assertions array

**Schema addition:**
```json
{
  "goals": {
    "G-01": {
      "decision_refs": ["D-7", "D-14"],
      "steps": [{
        "name": "create",
        "actor": "owner",
        "endpoint": {"method": "POST", "path": "/api/projects", "request_schema_ref": "..."},
        "assertions": [
          {"source": "D-7", "check": "status == 429 on 4th retry"},
          {"source": "API-CONTRACTS", "check": "response matches ProjectCreated schema"}
        ]
      }]
    }
  }
}
```

## Batch 2 — High (after Batch 1 ships)

- G2: per-verb stage derivation (delete-only → R+D+R, create-only → R+C+R, full mutation → RCRURDR)
- G14: read-only goals get lifecycle with precondition + filter spec (closes coverage hole)

## Batch 3 — Medium

- G8: discrete assertion arrays (already partially in G9 schema)
- G11: post-codegen runtime conformance gate (test step verifies generated spec matches lifecycle)
- G13: validator semantic checks (stage↔endpoint, assertion↔D-XX, actor-step mapping)
- G3: step body content from binding (not template strings)

## Batch 4 — Cleanup quality

- G1: business-specific preconditions from goal dependencies + infra_deps
- G4: actor inference via TEST-GOALS metadata (not word match)
- G5: fixture DAG from goal dependencies graph
- G6: artifact_capture per goal artifact_kind field

## Batch 5 — Test execution observability (NEW, ship after Batch 1)

### Problem

Pre-v4.0 review chạy e2e qua MCP Playwright HEADED → user xem live. v4.0 đã tách review (discovery-only) khỏi test (codegen + regression). Hiện trạng test execution:

| Step | Visibility | Source |
|---|---|---|
| `5c_smoke` (test/runtime.md:130) | HEADED via MCP — OK | giữ nguyên |
| `5c_flow` (test/runtime.md:162) | HEADED via MCP — OK | giữ nguyên |
| `5e_regression` (test/regression-security.md:39) | **HEADLESS — user mù** | `npx playwright test` không config |

→ Generated Playwright spec chạy headless mặc định. User không thấy browser, không xem được hành vi, debug khó.

### Fix design

**Layered visibility control:**

1. **Generated playwright config** — `${GENERATED_TESTS_DIR}/playwright.config.generated.ts` auto-created (currently file mentioned line 42-43 but không chỉ định nội dung). Defaults:
   ```ts
   export default defineConfig({
     use: {
       headless: !!process.env.CI,
       launchOptions: { slowMo: process.env.CI ? 0 : 250 },
       trace: 'retain-on-failure',
       video: 'retain-on-failure',
       screenshot: 'only-on-failure',
     },
     reporter: process.env.CI ? [['dot']] : [['list'], ['html', { open: 'never' }]],
     workers: process.env.CI ? undefined : 1,  // serial when headed for watchability
   });
   ```

2. **Config flag** — `vg.config.template.md` thêm block:
   ```
   ## test
   execution:
     headed_default: auto   # auto | true | false (auto = headed when TTY)
     slow_mo_ms: 250
     show_trace_on_failure: true
   ```

3. **CLI args** — `/vg:test` chấp nhận:
   - `--headed` / `--headless` → override config
   - `--ui` → spawn `npx playwright test --ui` (full inspector)
   - `--slow-mo=<ms>` → override slowMo

4. **`--auto-chain` semantics** — auto-chain implies CI mode → force headless + dot reporter (giữ pipeline tốc độ).

5. **Reporter switch** — interactive: `list` (mỗi spec in tên ngay khi start, status khi done). CI: `dot` (1 ký tự/spec).

### Acceptance criteria

1. `5e_regression` step generates `playwright.config.generated.ts` if missing, with profile-driven defaults.
2. Headed mode khi: không có `CI` env + không có `--auto-chain` + `headed_default` không phải `false`.
3. `--headed` flag force on. `--headless` flag force off.
4. Trace + video + screenshot artifacts saved on failure, path emitted to SANDBOX-TEST.md.
5. `--ui` flag spawns Playwright UI inspector (block until close).
6. Config flag respected: `headed_default: false` → headless ngay cả khi interactive.
7. Tests: integration test verifying generated config has `headless: !!process.env.CI` line + 1 unit test for CLI arg precedence.

### Out of scope (Batch 5)

- Live console streaming to terminal (Playwright `list` reporter đã đủ)
- Per-step screenshot capture (chỉ on-failure trong batch này)
- Trace viewer auto-open (chỉ link path; user mở thủ công)

## Deferred (v5.1+)

- G15: single source of truth — consolidate 5 artifacts into 1 phase-contract.json (large refactor, defer)
- Read-write split spec for streaming endpoints
- WebSocket lifecycle specs
- Multi-tenant boundary specs

## Args cleanup (deprecation cycle, NOT batch)

Per Codex: `--with-deepscan` has refs in `scripts/vg-orchestrator/recovery_paths.py` + tests. Don't remove. Cycle:
1. v5.x: keep parser + deprecation warning (current state OK)
2. v5.y: migrate recovery_paths refs
3. v6.0: remove flag

`--skip-lens-plan-gate` still alive in `_shared/test/fix-loop-and-verdict.md` — KEEP.

Marker renumber: DO NOT. Codex: markers are contract for hook/telemetry/recovery/tasklist. Renumber without migration plan = breaking change for ~0 value.

## Acceptance criteria (per batch)

### Batch 1 acceptance

1. `generate-lifecycle-specs.py` accepts `--api-contracts PATH` + `--context PATH` flags (or auto-detects in phase-dir).
2. LIFECYCLE-SPECS.json schema extended: every step has `actor`, `endpoint`, `assertions[].source` fields.
3. Multi-actor goals: each step's `actor` field reflects stage-appropriate actor (not all collapsed to `actors[0]`).
4. Endpoint binding: 90%+ stages on real phases bind to an API-CONTRACTS entry (some manual goals may skip).
5. Decision propagation: any goal mentioning a D-XX in `dependencies` or `mutation_evidence` produces `decision_refs` array.
6. Backward compat: old LIFECYCLE-SPECS.json (without new fields) still parses; new fields are additive.
7. Tests: ≥6 new tests covering G12/G7/G9 behaviors. All pre-existing tests pass.

## Risk register

| Risk | Mitigation |
|---|---|
| API-CONTRACTS.md format varies across phases | Multi-pattern parser; fall back to None binding if no match (graceful) |
| CONTEXT.md decision block format varies | Try 2 patterns (D-XX heading + bullet list); skip silently if neither matches |
| Multi-actor stage assignment heuristic wrong | Per-stage actor stays nullable; codegen falls back to actors[0] if null |
| Breaking change for downstream consumers | New fields additive only; codegen reads new fields with `.get()` defaults |
| Generator slowdown reading 3 artifacts | All artifacts small (<100KB typical); single-pass parse, no nested IO |

## Out of scope (this design)

- Codegen subagent rewrites
- Validator semantic checks (G13 — batch 3)
- Read-only lifecycle (G14 — batch 2)
- Single-source-of-truth consolidation (G15 — v5.1)
