---
name: vg:LIFECYCLE
description: VG pipeline taxonomy — single-page mental model of the 7-phase lifecycle. Each phase has its own slash command(s), required artifacts, and gate contract. Cite as the canonical 'where am I in the pipeline' reference.
---

# VG Lifecycle — 8 Phases

VG enforces a deterministic pipeline. Each phase has REQUIRED artifacts, a slash command, and a gate contract that the next phase reads. **Skipping a phase = breaking the contract = next phase BLOCKs.**

Inspired by [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) lifecycle taxonomy (Define / Plan / Build / Verify / Review / Ship / Meta) but tightened: VG phases bind to gate contracts, not just discipline.

---

## Visual map

```mermaid
flowchart LR
    Start([New project]) --> P0[0. Init]
    P0 --> P1[1. Define]
    P1 --> P2[2. Scope]
    P2 --> P3[3. Plan]
    P3 --> P4[4. Build]
    P4 --> P5[5. Verify]
    P5 --> P5B[5b. Test Spec]
    P5B --> P6[6. Test]
    P6 --> P7[7. Accept]
    P7 --> P8{Deploy?}
    P8 -->|yes| Deploy[8. Deploy]
    P8 -->|no| Close[Milestone close]
    Deploy --> Close
    Close --> NextPhase[Next phase]
    NextPhase --> P1

    style P0 fill:#fff3e0
    style P1 fill:#e3f2fd
    style P2 fill:#e3f2fd
    style P3 fill:#fff9c4
    style P4 fill:#c8e6c9
    style P5 fill:#f8bbd0
    style P5B fill:#ffe0b2
    style P6 fill:#f8bbd0
    style P7 fill:#dcedc8
    style Deploy fill:#bbdefb
    style Close fill:#d1c4e9
```

> **B69 fix (legacy):** mermaid corrected to match real code
> dependencies. `/vg:test-spec` Step 1 gate requires `RUNTIME-MAP.json`
> from `/vg:review` (lines 174-190 of test-spec.md). Therefore
> canonical order is `build → review → test-spec → test`. Prior v3.x
> diagram inverted that ordering and contradicted code.

---

## Phase contracts

| Phase | Slash command | Required output (artifact) | Gates next phase reads |
|---|---|---|---|
| **0. Init** | `/vg:project` (legacy `/vg:init`) | `.vg/FOUNDATION.md`, `.vg/config.md`, `.vg/ROADMAP.md` | All downstream phases require these to exist |
| **1. Define** | `/vg:specs <N>` | `${PHASE_DIR}/SPECS.md` (frontmatter: phase, status=draft, required H2 sections) + `${PHASE_DIR}/INTERFACE-STANDARDS.md` (when API/UI surface) | `/vg:scope` validates SPECS schema before round 1 |
| **2. Scope** | `/vg:scope <N>` (5 rounds + deep probe) | `${PHASE_DIR}/CONTEXT.md` (decisions D-XX, monotonic), `DISCUSSION-LOG.md` | `/vg:blueprint` reads CONTEXT decisions; missing D-IDs → BLOCK |
| **3. Plan** | `/vg:blueprint <N>` | `${PHASE_DIR}/PLAN.md`, `API-CONTRACTS.md`, `TEST-GOALS.md`, `CRUD-SURFACES.md`, `INTERFACE-STANDARDS.md` | `/vg:build` validates blueprint schema + plan-vs-context coherence |
| **4. Build** | `/vg:build <N>` (wave-based parallel) | `${PHASE_DIR}/SUMMARY.md` (per-wave commits + per-task evidence) | `/vg:review` reads build output for runtime discovery |
| **5. Verify** | `/vg:review <N>` (code scan + browser discovery + fix loop) | `${PHASE_DIR}/RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md` | `/vg:test-spec` reads RUNTIME-MAP + coverage matrix to author deep specs |
| **5b. Test Spec** | `/vg:test-spec <N>` (post-review deep spec authoring; B69 — runs AFTER review since Step 1 gate requires RUNTIME-MAP.json) | `${PHASE_DIR}/DEEP-TEST-SPECS.md`, `LIFECYCLE-SPECS.json`, `TEST-FIXTURE-DAG.json`, `TEST-EXECUTION-PLAN.json`, `TEST-SPEC-LOCALIZER/PROMPT.md`, `PLAYWRIGHT-SPEC-PLAN.md`, `TEST-SPEC-GAPS.md`, `CODEGEN-MANIFEST.json` | `/vg:test` consumes LIFECYCLE-SPECS + CODEGEN-MANIFEST for playwright runtime |
| **6. Test** | `/vg:test <N>` (codegen + smoke + regression + security) | `${PHASE_DIR}/SANDBOX-TEST.md` + `.test-step-status.json` + Playwright spec files | `/vg:accept` validates test outcomes |
| **7. Accept** | `/vg:accept <N>` (UAT checklist + audit + reflector) | `${PHASE_DIR}/UAT.md` (verdict + bootstrap candidates) | Phase considered complete; milestone closer reads accept verdict |
| **8. Deploy** | `/vg:deploy [<N>]` (multi-env: sandbox/staging/prod) | `.vg/deploy/STATE.json` (project-level v3.0.0+) | Optional — does not block next phase Init |

---

## Sub-phases (drill-down)

### Phase 2 (Scope) — 5 rounds + 1 probe

| Round | Focus | Output enrichment |
|---|---|---|
| 1 | Domain | Business rules, invariants, edge actors |
| 2 | Technical | Stack constraints, performance budgets, integration boundaries |
| 3 | API | Endpoints, contract shapes, error modes |
| 4 | UI | User flows, modal states, validation rules |
| 5 | Tests | Goal phrasing, coverage scope, deferred items |
| Deep probe | Adversarial | What breaks? What's missed? |

### Phase 3 (Plan) — 4 sub-steps

1. `2a_plan` — task breakdown (PLAN.md with NN tasks)
2. `2b_api_contracts` — API-CONTRACTS.md (per-endpoint, schema-validated)
3. `2c_workflows` — multi-actor flow specs (when applicable)
4. `2d_test_goals` — TEST-GOALS.md + CRUD-SURFACES.md

### Phase 5 (Verify / Review) — fix loop

1. Code scan (linter / sast / lens-prompts adversarial)
2. Browser discovery (Playwright recursive lens probes)
3. Goal comparison (RUNTIME-MAP vs PLAN goals)
4. Fix loop (3-tier routing: inline / spawn / escalate, max 5 iterations)
5. CrossAI peer review (Codex + Gemini consensus)

---

## What advances vs what completes a phase

A phase **advances** when its slash command emits `<cmd>.completed` telemetry + writes its required artifact.

A phase **completes** when:
- All `must_emit_telemetry` events landed in events.db
- All `must_touch_markers` files exist under `.step-markers/`
- Schema validators pass for produced artifacts
- `vg-orchestrator run-complete` returns 0

If verdict=True (contract clean) but caller passed `--outcome BLOCK` (goal coverage failed), terminal prints `⚠ contract PASS, outcome=BLOCK` separately — see issue #170 / fix v2.79.1.

---

## Cycle vs sequential

VG phases are NOT strictly sequential within a milestone. Cycles are explicit:
- `/vg:debug` re-enters Build/Verify when a bug is found post-acceptance — focused, no full review sweep.
- `/vg:amend` modifies CONTEXT decisions mid-phase + cascades impact analysis (read-only by `vg-amend-cascade-analyzer` subagent).
- `/vg:roam` is a Verify-mode sub-pipeline for runtime-only investigations (no plan binding).

---

## Pipeline Artifacts Reference (v4.12.0)

Every file written by the pipeline and consumed by a downstream gate. Phase origin noted.

| Artifact | Phase origin | Written by | Consumed by |
|---|---|---|---|
| `PIPELINE-STATE.json` | All | Each phase close | Next phase preflight, `--auto-chain` reader |
| `.test-step-status.json` | Test (C5 Batch 9) | `test/close.md` step ledger | Verdict engine, test/preflight resume detection |
| `LIFECYCLE-SPECS.json` | Test Spec (Batch 1) | `test-spec.md` | `test/preflight.md` deep-spec contract gate |
| `DEEP-TEST-SPECS.md` | Test Spec | `test-spec.md` | Codegen, `test/preflight.md` |
| `GOAL-COVERAGE-MATRIX.json` | Review | `review/close.md` | `test/preflight.md`, accept gate |
| `SANDBOX-TEST.md` | Test | `test/close.md` | `accept/preflight.md` (renamed from `TEST-RESULTS.json` — that name is historical/deprecated) |
| `REVIEW.md` | Review | `review/close.md` | `test/preflight.md` |
| `.verdict-computed.json` | Test (Batch 9) | Verdict engine | `test/close.md` summary, accept gate |
| `evidence-manifest.json` | Build (issue #175) | `build/close.md` run-complete | `review/preflight.md` artifact freshness |
| `TEST-FAILURE-REPORT.md` | Test (H13 v4.12.0) | AI test introspection agent | `accept/preflight.md`, `vg:debug` |
| `REFLECTION.md` | Blueprint/Build/Test (H10) | Reflector subagent | `vg:roam`, operator review |
| `MATRIX-INTENT.json` | Blueprint | `blueprint/close.md` | `review/preflight.md` |
| `url-runtime-status.json` | Review (C11) | Browser discovery | `review/fix-loop.md` |
| `CODEGEN-BINDING-REPORT.json` | Test (C7) | Codegen binding validator | `test/fix-loop.md` |
| `CODEX-FIX-FAILURES.json` | Build (H8) | Codex fix agent | `build/crossai-loop.md` |
| `.amend-invalidation.json` | Amend (planned Batch 11) | `/vg:amend` | Blueprint/build close invalidation gate |

---

## Strict Marker Gate (v4.3.0+)

All 4 phase closes invoke `verify_all_markers_strict_runid` as of v4.13.0 (Batch 10 F3):

| Close file | Gate location | Introduced |
|---|---|---|
| `test/close.md` | §8.3.5b | Batch 9 (C9) |
| `blueprint/close.md` | After R7 block (§6.2.1) | Batch 10 (F3) |
| `build/close.md` | Before `vg-orchestrator run-complete` | Batch 10 (F3) |
| `accept/cleanup/overview.md` | After Gate B | Batch 10 (F3) |

The function `verify_all_markers_strict_runid(phase_dir, phase_num, run_id)` (from `lib/marker-schema.sh`) rejects:
- **Empty markers** — zero-byte `.done` files written without content
- **Stale markers** — marker `run_id` field differs from current `VG_RUN_ID`
- **Forged markers** — marker timestamp predates phase start time

Bypass: `VG_MARKER_STRICT=0` (UNSAFE — only for explicit migration of pre-Batch-9 phases).

---

## Auto-chain (v4.13.0+)

`--auto-chain` consumers read `PIPELINE-STATE.json:next_command` emitted by each phase close. As of Batch 10 (F1), all 6 phase boundaries are wired:

| Phase close | Emits `next_command` | Verdict condition |
|---|---|---|
| `specs/write-and-commit.md` | `/vg:scope {phase}` | always |
| `scope/close.md` | `/vg:blueprint {phase}` | always |
| `blueprint/close.md` | `/vg:build {phase}` | always |
| `build/close.md` | `/vg:review {phase}` | always (B69 fix — was missing emit) |
| `review/close.md` | `/vg:test-spec {phase}` | always (B69 fix — was implicit user-message only) |
| `test-spec.md` | `/vg:test {phase}` | always (B69 fix — was incorrectly /vg:review) |
| `test/close.md` | `/vg:accept {phase}` | PASSED / GAPS\_FOUND only |
| `test/close.md` | `/vg:review --resume {phase}` | FAILED |

Downstream consumers check `PIPELINE-STATE.json` for `next_command` and `next_command_emitted_at` fields.

---

## Domain/Team Isolation (v4.15.0+)

F7 Batch 12 introduces domain and team fields for multi-team parallel scheduling.

### ROADMAP.md fields (per phase)

```markdown
## Phase {NN}: {Name}
**Domain:** {business domain — e.g. identity, payments, catalog, infra}
**Team:** {owning team — e.g. auth-team, platform-team, or "unassigned"}
```

### PIPELINE-STATE.json fields

| Field | Type | Description |
|---|---|---|
| `domain` | string | Business domain from ROADMAP.md. Set by `specs/preflight.md`. |
| `team` | string | Owning team. `"unassigned"` if not set in ROADMAP. |

### Propagation

`specs/preflight.md` (Step 3 — domain_team_propagation) reads `domain` + `team`
from ROADMAP.md and:
1. Exports `VG_PHASE_DOMAIN` + `VG_PHASE_TEAM` env vars.
2. Writes `domain` + `team` into `PIPELINE-STATE.json`.

### Future: Parallel Team Scheduler (v5.0+)

The `domain` field provides the partition key for a future parallel scheduler.
Teams with non-overlapping domains can run concurrent phases. Cross-domain deps
are declared in `CROSS-PHASE-DEPS.md`. Full implementation deferred to v5.0+.

---

## Cross-references

- Skill discovery (which command for what intent): `_shared/discovery-flowchart.md`
- Engineering principles cited at gate boundaries: `_shared/eng-principles.md`
- Anti-rationalization tables: `_shared/rationalization-tables.md`
- Runtime routing: `commands/vg/next.md`
- Health diagnosis: `commands/vg/doctor.md`
