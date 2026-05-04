# R7 — Blueprint→Build→Review continuity gaps

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Close 9 semantic-enforcement gaps where blueprint outputs are generated but downstream build/review pipelines don't faithfully consume/check them. Pipeline becomes "production-ready end-to-end" — not just per-workflow.

**Architecture:** Add post-build validators (RCRURD/workflow/edge implementation gates) + review preflight extensions (BUILD-LOG provenance, CrossAI carryover, post-executor evidence) to enforce that what blueprint promises, build delivers, and review verifies.

**Tech Stack:** bash refs, Python validators (`scripts/validators/verify-*.py`), spawn-guard hook extensions, schema files

---

## Audit basis

Independent codex GPT-5.5 audit (2026-05-05) verified 9 gaps with file:line evidence. Em re-verified 8/9 directly — codex audit ACCURATE.

| Gap | Severity | Reason |
|---|---|---|
| G1 RCRURDR invariants not enforced at build | High | Blueprint generates but build has no implementation check |
| G2 Workflow specs not enforced at build | High | Multi-actor flows generated, build only injects context (no gate) |
| G3 Edge cases coverage not enforced at build | Medium | Validator exists for artifact structure, not implementation coverage |
| G4 TDD evidence not cross-checked at review | Low/Medium | Build gate covers honest case; review doesn't re-verify |
| G5 Build CrossAI defer → review ignore | High | findings-iter5.json deferred but review doesn't consume → silent leak |
| G6 Post-executor compliance not re-verified at review | Medium | Hook-enforced at build; review doesn't check |
| G7 RCRURD artifact source-of-truth conflict | High | Blueprint writes inline yaml-rcrurd fences; pre-executor-check looks for separate dir |
| G8 BUILD-LOG not in review prereq | Medium | Review preflight prereq list omits BUILD-LOG provenance |
| G9 Workflow specs not in review verdict | High | Multi-actor replay path missing |

---

## Batches (priority-ordered)

### R7-A — G5: Review CrossAI carryover (1-2 days, highest ROI)

**Why first:** Single concrete leak (build defer → review skip → accept clean → ship bug). Lowest effort, eliminates a class of silent bugs.

#### Task 1: Review preflight ingest build CrossAI terminal state

**Files:**
- Modify: `commands/vg/_shared/review/preflight.md` — add CrossAI terminal-state ingest after REQUIRED_ARTIFACTS check
- Add: `scripts/validators/verify-build-crossai-carryover.py` (new)
- Test: `scripts/tests/test_review_crossai_carryover.py` (new)

**Steps:**

- [ ] Step 1: Write failing test asserting review preflight blocks when `${PHASE_DIR}/crossai-build-verify/findings-iter5.json` exists AND no override flag

- [ ] Step 2: Implement validator that reads `events.db` for `build.crossai_terminal` event + reads findings-iter5.json. Severity:
  - Terminal state = `clean` → PASS
  - Terminal state = `exhausted` → BLOCK unless `--allow-build-crossai-deferred --override-reason=<text>`
  - Terminal state = `user_override` → WARN (already user-acknowledged)
  - No terminal state recorded but findings-iter5.json exists → BLOCK (build state corrupted)

- [ ] Step 3: Wire validator into `review/preflight.md` after REQUIRED_ARTIFACTS check, before phase 2a probes

- [ ] Step 4: Update `commands/vg/review.md` frontmatter `forbidden_without_override` + `commands/vg/_shared/review/preflight.md` allowlist for `--allow-build-crossai-deferred`

- [ ] Step 5: Mirror sync + commit

---

### R7-B — G1+G7: RCRURD source unification + build gate (2-4 days)

**Why important:** Structural bug — 2 source of truth disagree. Closes G7 (artifact contract drift) + G1 (no build-side check).

#### Task 2: Normalize RCRURD source to inline yaml-rcrurd fences

**Files:**
- Modify: `scripts/pre-executor-check.py:633-645` — switch from `RCRURD-INVARIANTS/G-*.yaml` lookup to extract from TEST-GOALS yaml-rcrurd fences
- Add: `scripts/lib/rcrurd_invariant.py` (helper extract from goal yaml fences) — reuse existing if present
- Test: `scripts/tests/test_rcrurd_source_unified.py` (new)

**Steps:**

- [ ] Step 1: Audit existing `scripts/lib/rcrurd_invariant.py` — confirm `extract_from_test_goal_md` exists (R6 Task 1 added it)

- [ ] Step 2: Write failing test asserting capsule `rcrurd_invariants_paths` is populated when blueprint wrote inline fences (not separate dir)

- [ ] Step 3: Refactor pre-executor-check.py to use `extract_from_test_goal_md` per goal — extract yaml fence content to `${VG_TMP}/.rcrurd-extracted/G-NN.yaml` and populate `rcrurd_invariants_paths` with these paths

- [ ] Step 4: Update `commands/vg/_shared/blueprint/rcrurdr-overview.md` to clarify single source of truth (inline only) + delete any ref to RCRURD-INVARIANTS/ dir as "alternative"

- [ ] Step 5: Mirror sync + commit

#### Task 3: Build post-spawn gate verifying implementation honors RCRURD invariants

**Files:**
- Add: `scripts/validators/verify-rcrurd-implementation.py` (new)
- Modify: `commands/vg/_shared/build/post-execution-validation.md` — add RCRURD audit between task-fidelity and TDD-evidence audit
- Test: `scripts/tests/test_verify_rcrurd_implementation.py` (new)

**Steps:**

- [ ] Step 1: Define check shape — for each goal with mutation behavior:
  - Read invariant from extracted yaml (read_after_create, read_after_update, read_after_delete, error_response_shape)
  - Grep modified files for handler implementation
  - Heuristic: invariant declares `delete → 404` then handler should have a 404 path; invariant declares `create → return id` then handler should return field with id key
  - Severity: WARN on heuristic miss, BLOCK on contradiction (handler returns 200 when invariant says 404)

- [ ] Step 2: Write tests covering 4 invariant types + 2 violation scenarios

- [ ] Step 3: Implement validator using AST/grep heuristics

- [ ] Step 4: Wire into post-execution-validation.md with `--skip-rcrurd-implementation-audit` override pattern

- [ ] Step 5: Mirror sync + commit

---

### R7-C — G2+G9: Workflow build gate + review multi-actor replay (3-5 days)

**Why critical:** Multi-actor flows = highest-risk UX path. Currently silent bypass possible.

#### Task 4: Build post-spawn gate verifying workflow implementation

**Files:**
- Add: `scripts/validators/verify-workflow-implementation.py` (new)
- Modify: `commands/vg/_shared/build/post-execution-validation.md`
- Test: `scripts/tests/test_verify_workflow_implementation.py`

**Steps:**

- [ ] Step 1: For each task with `capsule.workflow_id != null`:
  - Read WORKFLOW-SPECS/<workflow_id>.md state machine
  - Find expected `state_after` for task's `workflow_step`
  - Grep task's modified files for state literal (e.g., `pending_admin_review`)
  - Severity: BLOCK if workflow_id declared but state literal not present in commit

- [ ] Step 2: Write 6 tests (4 happy paths + 2 violation scenarios)

- [ ] Step 3: Implement validator

- [ ] Step 4: Wire override `--skip-workflow-implementation-audit`

- [ ] Step 5: Mirror sync + commit

#### Task 5: Review multi-actor workflow replay (verdict layer)

**Files:**
- Add: `commands/vg/_shared/review/verdict/multi-actor-workflow.md` (new)
- Modify: `commands/vg/_shared/review/runtime-checks-dynamic.md` — add multi-actor probe trigger
- Test: `scripts/tests/test_review_workflow_replay.py`

**Steps:**

- [ ] Step 1: For each WORKFLOW-SPECS/<WF-NN>.md:
  - Parse actor list + state transitions
  - Generate replay plan: actor A → action → state X → actor B → action → state Y
  - Browser MCP execute (MCP playwright per actor session)

- [ ] Step 2: Compare runtime states vs WORKFLOW-SPECS declared states. Report mismatches.

- [ ] Step 3: Wire into review verdict for profile=backend-multi-actor or web-fullstack with workflow_id present

- [ ] Step 4: Tests + mirror sync + commit

---

### R7-D — G6+G8: Review build provenance gate (1 day)

**Why important:** Closes 2 review prereq blind spots cheaply.

#### Task 6: Add BUILD-LOG + post-executor evidence to review prereq

**Files:**
- Modify: `commands/vg/_shared/review/preflight.md` — extend REQUIRED_ARTIFACTS or add separate BUILD-LOG check
- Test: `scripts/tests/test_review_build_provenance.py`

**Steps:**

- [ ] Step 1: Write failing test asserting review preflight blocks when BUILD-LOG/index.md missing OR `.post-executor-spawns.json` missing OR `build.completed` event not in events.db

- [ ] Step 2: Add prereq check inline (use `events.db` query for build.completed, file existence for BUILD-LOG/index.md)

- [ ] Step 3: Override `--allow-missing-build-provenance` for legacy phases (with --override-reason)

- [ ] Step 4: Mirror sync + commit

---

### R7-E — G3: Build edge-case implementation coverage (1-2 days)

**Why medium priority:** Edge cases declared but coverage not enforced. Lower than RCRURD/workflow because review verdict already replays variants — gap is "delayed detection", not "missed forever".

#### Task 7: Build post-spawn gate for edge-case marker coverage

**Files:**
- Add: `scripts/validators/verify-edge-case-coverage.py` (new)
- Modify: `commands/vg/_shared/build/post-execution-validation.md`
- Test: `scripts/tests/test_verify_edge_case_coverage.py`

**Steps:**

- [ ] Step 1: For each goal in `edge_cases_for_goals` capsule field:
  - Read EDGE-CASES/<G-NN>.md variant list
  - Filter critical + high priority variants
  - Grep modified files for `// vg-edge-case: <variant_id>` markers
  - Severity: BLOCK if any critical variant lacks marker; WARN if high-priority variant lacks marker

- [ ] Step 2: Tests covering 3 happy paths + 2 violation scenarios

- [ ] Step 3: Implement validator + wire into post-execution-validation

- [ ] Step 4: Override `--skip-edge-case-coverage-audit` (if validator BLOCK is too aggressive for early-phase work)

- [ ] Step 5: Mirror sync + commit

---

### R7-F — Close (Tasks 8-9, ~0.5 day)

#### Task 8: Full pytest regression + PV3 sync + audit doc update

#### Task 9: Push + final commit summary + audit-MASTER.md mark all gaps RESOLVED

---

## Dependency order

```
R7-A (Task 1)            → independent
R7-B Task 2 (RCRURD source unify) → independent (closes G7 alone)
R7-B Task 3 (RCRURD impl gate) → after Task 2 (uses extracted invariants)
R7-C Task 4 (workflow build gate) → independent
R7-C Task 5 (workflow review replay) → after Task 4 (uses build evidence)
R7-D Task 6 (review provenance) → independent
R7-E Task 7 (edge-case coverage) → independent
R7-F Tasks 8-9 → final
```

---

## Success criteria

1. All 9 gaps closed with verifiable validators + test coverage
2. Codex re-audit (round 2) finds zero High/Critical, ≤2 Medium
3. Pytest regression: all newly-added tests pass; pre-existing failures unchanged
4. Sếp dogfood next phase end-to-end without silent skip on any gap

---

## Risk + mitigation

| Risk | Likelihood | Mitigation |
|---|---|---|
| RCRURD source unification breaks legacy phases (separate dir) | Medium | Backward-compat: keep dir-lookup as fallback when fences absent; emit telemetry for legacy detection |
| Workflow implementation gate too strict (false-positive BLOCK) | Medium | Heuristic-based with `--skip-` override; promote to BLOCK only after dogfood validates accuracy |
| Multi-actor browser replay flaky (Playwright timing) | High | Reuse existing flow-runner pattern (checkpoint+retry); start with happy-path then expand |
| 9 gaps × multi-day effort = scope creep | Medium | Ship per-batch (R7-A first), validate via dogfood between batches |

---

## Audit metadata

- Codex GPT-5.5 audit: this conversation 2026-05-05 (verbatim findings preserved as G1-G9)
- Re-verification: directly read all cited file:line evidence — 8/9 VERIFIED, 1/9 PARTIAL as codex self-rated
- Plan author: claude-opus-4-7[1m] (Claude Code CLI)
