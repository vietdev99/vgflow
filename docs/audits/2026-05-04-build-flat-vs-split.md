# build.md flat-file consumption audit (2026-05-04, R2 scope)

Source: `commands/vg/.build.md.r2-backup` (4571 lines, snapshot before R2 refactor).
Methodology: `grep -nE "API-CONTRACTS\.md|PLAN\.md|TEST-GOALS\.md|cat \$\{?PHASE_DIR\}?|Read .*\.md"` then classified per surrounding context (5 lines before/after via `grep -B5 -A5` and targeted Reads of executor capsule assembly at lines 1340-1370 and 1700-1880).

Total hits: 40
- MIGRATE: 3 (drives Phase B refs — replace with `vg-load`)
- KEEP-FLAT: 37 (allow-list for Task 16b static enforcer)

Two structural facts shape the verdict:
1. The executor capsule (`<task_context>`, `<contract_context>`, `<goals_context>` etc.) is already populated by `pre-executor-check.py` (lines 1352-1373) — the script reads PLAN/CONTRACTS/GOALS deterministically and emits scoped JSON. The capsule injection points (1816, 1844, 1852, 1877) are variable expansions, not flat reads. R2 vg-load primarily replaces `pre-executor-check.py`'s upstream input shape (per-task split files instead of full flat parse), not the capsule injection itself.
2. Most flat-file mentions in build.md are echo strings, comments, mtime checks (`-nt`), `[ -f ]` presence tests, or path arguments to deterministic Python scripts (`generate-api-docs.py`, `verify-task-fidelity.py`, `verify-route-schema-coverage.py`). These are KEEP-FLAT — no AI consumes the file content directly.

## MIGRATE table (replace with vg-load in new refs)

| Backup line | Snippet | Classification | Replacement |
|---|---|---|---|
| 162 | `Key difference from V4 execute: executors read API-CONTRACTS.md to ensure BE routes match contract fields and FE calls match contract endpoints.` | MIGRATE (prose claim — instruction to executor that historically meant "read flat file") | Update prose to: "executors receive per-endpoint contract slices via `vg-load --artifact contracts --endpoint <slug>` resolved by `pre-executor-check.py`." |
| 783 | `` Read `${PHASE_DIR}/API-CONTRACTS.md`. Per plan task, extract only endpoint sections the task touches (grep for endpoint paths task mentions). `` | MIGRATE (explicit AI Read instruction in step 4a "Contract context") | Replace with: "Per plan task, run `vg-load --artifact contracts --task NN --endpoint <slug>` to obtain only the endpoint slice the task touches. Loader handles split (`API-CONTRACTS/<endpoint>.md`) and legacy flat fallback." |
| 1232 | `4. Run step 4d: extract task sections from PLAN*.md` | MIGRATE (instruction inside resume-recovery block at step 8 entry) | Replace with: "Run step 4d: `vg-load --artifact plan --task <N>` per task in wave (per-task split is the canonical source; loader falls back to flat parse only if split missing)." |

## KEEP-FLAT table (deterministic transforms only)

| Backup line | Snippet | Classification | Reason |
|---|---|---|---|
| 140 | `Blueprint required — phase must have PLAN*.md AND API-CONTRACTS.md before build. Missing = BLOCK.` | KEEP-FLAT | Rule prose; no read |
| 141 | `for each ## METHOD /path endpoint declared in API-CONTRACTS.md, static presence check across framework patterns` | KEEP-FLAT | Describes verify-contract-runtime grep validator (deterministic) |
| 143 | `materialize ${PHASE_DIR}/API-DOCS.md from API-CONTRACTS.md plus the implemented code surface` | KEEP-FLAT | Rule prose pointing at generate-api-docs.py (deterministic transform) |
| 171 | `Config: Read .claude/commands/vg/_shared/config-loader.md first.` | KEEP-FLAT | Shared infra ref, not a phase artifact (out of vg-load scope) |
| 173 | `Read .claude/commands/vg/_shared/bug-detection-guide.md BEFORE starting.` | KEEP-FLAT | Shared infra ref, not a phase artifact |
| 501 | `CONTRACTS=$(ls "${PHASE_DIR}"/API-CONTRACTS.md 2>/dev/null)` | KEEP-FLAT | Presence check via `ls` |
| 588 | `If user runs amend AFTER blueprint but BEFORE build, PLAN.md / API-CONTRACTS.md are stale relative to the amendment.` | KEEP-FLAT | Why-prose for amendment freshness gate |
| 595 | `PLAN_FILE="${PHASE_DIR}/PLAN.md"` | KEEP-FLAT | Variable assignment for `-nt` mtime check |
| 596 | `CONTRACTS_FILE="${PHASE_DIR}/API-CONTRACTS.md"` | KEEP-FLAT | Variable assignment for `-nt` mtime check |
| 599 | `STALE="PLAN.md"` | KEEP-FLAT | Echo string literal for stale message |
| 602 | `STALE="${STALE:+$STALE+}API-CONTRACTS.md"` | KEEP-FLAT | Echo string literal for stale message |
| 626 | `### 3d: CONTEXT.md freshness vs PLAN.md (harness v2.7-fixup-M4)` | KEEP-FLAT | Heading prose |
| 628 | `Mid-phase decision tweak ... leaves PLAN.md stale referencing the pre-edit decision set.` | KEEP-FLAT | Why-prose for CONTEXT freshness gate |
| 634 | `PLAN_FILE="${PHASE_DIR}/PLAN.md"` | KEEP-FLAT | Variable assignment for `-nt` mtime check |
| 636 | `echo "⛔ CONTEXT.md modified after PLAN.md — re-blueprint or run /vg:amend"` | KEEP-FLAT | User-facing echo string |
| 637 | `echo "   PLAN.md is stale relative to current CONTEXT.md decisions."` | KEEP-FLAT | User-facing echo string |
| 653 | `CONTEXT.md older than PLAN.md → PASS (blueprint incorporated current decisions)` | KEEP-FLAT | Result-routing prose |
| 824 | `echo "⚠ .wave-tasks design-ref signature is stale vs PLAN.md; regenerating task capsules before executor spawn."` | KEEP-FLAT | User-facing echo string |
| 1136 | `Contract ref: API-CONTRACTS.md line <start>-<end>` | KEEP-FLAT | Pointer string in wave-context template (no read; just locator) |
| 1142 | `Contract ref: API-CONTRACTS.md line <start>-<end>` | KEEP-FLAT | Pointer string in wave-context template |
| 1147 | `Contract ref: API-CONTRACTS.md line <start>-<end>` | KEEP-FLAT | Pointer string in wave-context template |
| 1229 | `1. Read .claude/vg.config.md — extract graphify.enabled, semantic_regression.enabled` | KEEP-FLAT | Config file (not phase artifact); already deterministic via vg_config_get |
| 1525 | `echo "<!-- Read by verify-uimap-injection.py — separate from .body.md (P16 hotfix). -->"` | KEEP-FLAT | Persisted heredoc comment |
| 1849 | `M3 fix (harness v2.7-fixup): DROPPED full-file @-include of API-CONTRACTS.md.` | KEEP-FLAT | Historical comment in capsule template (the actual injection is `${CONTRACT_CONTEXT}` from pre-executor-check.py) |
| 2274 | `1. PLAN.md task block re-extracted now (current truth)` | KEEP-FLAT | Describes verify-task-fidelity.py 3-way hash audit (deterministic) |
| 2427 | `# Gate 4: Contract verify (grep built code vs API-CONTRACTS.md)` | KEEP-FLAT | Comment for contract_verify_grep validator (deterministic grep) |
| 2874 | `if [ -d "${VG_SCRIPT_ROOT}/runtime" ] && [ -f "${PHASE_DIR}/TEST-GOALS.md" ]; then` | KEEP-FLAT | `[ -f ]` presence check |
| 2880 | `test_goals = phase_dir / "TEST-GOALS.md"` | KEEP-FLAT | Python regex parse for goal IDs → fixture verify (deterministic) |
| 3465 | `# Surface scan: new/changed endpoints vs API-CONTRACTS.md` | KEEP-FLAT | Comment above git diff scan |
| 3470 | `echo "Code changed after build — API-CONTRACTS.md may need sync."` | KEEP-FLAT | User-facing echo string |
| 3482 | `# Canonical: blueprint writes single PLAN.md → expect SUMMARY.md.` | KEEP-FLAT | Bash comment |
| 3586 | `--contracts "${PHASE_DIR}/API-CONTRACTS.md" \` | KEEP-FLAT | Path argument to generate-api-docs.py (deterministic Python) |
| 3587 | `--plan "${PHASE_DIR}/PLAN.md" \` | KEEP-FLAT | Path argument to generate-api-docs.py |
| 3588 | `--goals "${PHASE_DIR}/TEST-GOALS.md" \` | KEEP-FLAT | Path argument to generate-api-docs.py |
| 3609 | `--source-inputs "${PHASE_DIR}/API-CONTRACTS.md,${PHASE_DIR}/PLAN.md,${PHASE_DIR}/TEST-GOALS.md" \` | KEEP-FLAT | Path arguments to emit-evidence-manifest.py (SHA256 manifest, deterministic) |
| 4024 | `completed against its 4 source-of-truth artifacts (API-CONTRACTS.md,` | KEEP-FLAT | Step 11 prose listing source artifacts (validator-driven, not direct read) |
| 4025 | `TEST-GOALS.md, CONTEXT.md decisions, PLAN.md tasks). This is ENFORCED` | KEEP-FLAT | Continuation of L4024 prose |
| 4249 | `"${PHASE_DIR}/TEST-GOALS.md" 2>/dev/null \| head -1)` | KEEP-FLAT | `git log --reverse --format=%ct` mtime/commit-time check |

## Replacement index by future ref file

Phase B refs and the steps they cover (per R2 plan Tasks 3-9):

- `_shared/build/preflight.md` (Task 3): backup steps `0_gate_integrity_precheck`, `0_session_lifecycle`, `1_parse_args`, `1a_build_queue_preflight`, `1b_recon_gate`, `create_task_tracker` — backup lines 175-475.
  - **MIGRATE**: none.
  - **KEEP-FLAT carry-over**: lines 140, 141, 143, 171, 173 (rule/header prose; live in entry build.md or preflight preamble).

- `_shared/build/context.md` (Task 4): backup steps `2_initialize`, `4_load_contracts_and_context` — backup lines 476-1013 + ~1340-1900 (executor context assembly).
  - **MIGRATE**: line 162 (objective prose), line 783 (step 4a Contract context Read instruction). Replace 783 with `vg-load --artifact contracts --task NN --endpoint <slug>` and tighten 162 to reference the loader rather than implying executors read the flat file.
  - **KEEP-FLAT carry-over**: 501, 588, 595, 596, 599, 602, 626, 628, 634, 636, 637, 653, 824, 1136, 1142, 1147, 1229, 1525, 1849.

- `_shared/build/validate-blueprint.md` (Task 5): backup steps `3_validate_blueprint`, `5_handle_branching`, `6_validate_phase`, `7_discover_plans` — backup lines ~494-1109.
  - **MIGRATE**: none (all flat references in this band are presence checks, mtime checks, or echo strings — already KEEP-FLAT).
  - **KEEP-FLAT carry-over**: 501, 588-653 cluster (amendment + CONTEXT freshness gates).

- `_shared/build/waves-overview.md` + `waves-delegation.md` (Task 6): backup step `8_execute_waves` — backup lines 1110-2992.
  - **MIGRATE**: line 1232 (resume-recovery prose `extract task sections from PLAN*.md`). Replace with vg-load per-task call.
  - **KEEP-FLAT carry-over**: 1136, 1142, 1147, 1229, 1525, 1849, 2274 (these stay because they're template strings, validator inputs, or pointer strings in the wave-context template).

- `_shared/build/post-execution-overview.md` + `post-execution-delegation.md` (Task 7): backup step `9_post_execution` — backup lines 3030-3927.
  - **MIGRATE**: none.
  - **KEEP-FLAT carry-over**: 3465, 3470, 3482, 3586, 3587, 3588, 3609 (all deterministic Python script inputs or echo strings).

- `_shared/build/crossai-loop.md` (Task 8): backup step `11_crossai_build_verify_loop` — backup lines 4020-4167. **Refactor deferred — preserve verbatim per R2 plan.**
  - **MIGRATE**: none (the step itself drives `vg-build-crossai-loop.py` which has its own input handling).
  - **KEEP-FLAT carry-over**: 4024, 4025 (prose listing source artifacts).

- `_shared/build/close.md` (Task 9): backup steps `10_postmortem_sanity`, `12_run_complete` — backup lines 3928-4019 + 4168-4571.
  - **MIGRATE**: none.
  - **KEEP-FLAT carry-over**: 4249 (git log mtime check on TEST-GOALS.md).

## Notes for Task 16b enforcer

`ALLOWED_FLAT_LINES` for `scripts/tests/test_build_uses_vg_load.py` should include only entries that survive the refactor (i.e., KEEP-FLAT hits that remain in Phase B ref files). Use **post-refactor** line numbers, not the backup line numbers — Task 16b reads the migrated refs, not the backup. The backup line numbers in this audit are the **classification keys** the implementer maps from when populating the allow-list.

Categories of KEEP-FLAT hits the enforcer must permit (express as regex/category match, not just line numbers, where possible):
1. **Echo / user-facing string literals** mentioning PLAN.md / API-CONTRACTS.md / TEST-GOALS.md (lines 599, 602, 636, 637, 824, 3470 — all in `echo "…"` form).
2. **Bash variable assignment for mtime/presence checks** (lines 595, 596, 634): `PLAN_FILE="${PHASE_DIR}/PLAN.md"` followed by `[ -f ]` or `-nt`.
3. **`ls`/`[ -f ]` presence tests** (lines 501, 2874).
4. **`git log` / `git diff` path arguments** (lines 4249, 3466-3467 region).
5. **Path arguments to deterministic Python scripts** (lines 3586-3588, 3609 — passed to `generate-api-docs.py`, `emit-evidence-manifest.py`; lines 2880 — Python `phase_dir / "TEST-GOALS.md"` in inline heredoc for fixture verify).
6. **Comments / heading text / why-prose** (lines 140, 141, 143, 588, 626, 628, 653, 1525, 1849, 2274, 2427, 3465, 3482, 4024, 4025).
7. **Pointer strings in templates** (lines 1136, 1142, 1147 — `Contract ref: API-CONTRACTS.md line X-Y` is a locator the AI receives, but no flat read happens — vg-load output should still produce this pointer for traceability).
8. **Shared infra ref Reads** (lines 171, 173, 1229 — `_shared/*.md` and `vg.config.md` are NOT phase artifacts and out of vg-load scope; the enforcer regex should target only `PLAN*.md`, `API-CONTRACTS*.md`, `TEST-GOALS*.md` paths under `${PHASE_DIR}`).

The simplest enforcer shape: forbid lines matching `Read \`?\${PHASE_DIR}/(PLAN|API-CONTRACTS|TEST-GOALS)` and `cat \${PHASE_DIR}/(PLAN|API-CONTRACTS|TEST-GOALS)` — these patterns capture only AI-context flat reads. The current backup has zero `cat ${PHASE_DIR}/PLAN.md` style reads (the original grep hit 0 of those) and exactly one `Read ${PHASE_DIR}/API-CONTRACTS.md` (line 783, which Phase B migrates). Echo strings, mtime checks, and Python script args don't trigger the enforcer because they don't match `Read`/`cat` of the phase artifact.

## Confidence notes

- All 3 MIGRATE classifications are unambiguous (explicit `Read` instruction or "executors read X" prose).
- 1136/1142/1147 (`Contract ref: …` template strings) were the closest call — they LOOK like AI-facing text inside a wave-context template, but they're locator strings, not content. Even after migration, the wave-context template still wants to emit the same pointer. Classified KEEP-FLAT.
- 4024/4025 (step 11 prose "4 source-of-truth artifacts") describes what the CrossAI loop validates against; the validator (`build-crossai-required.py`) reads these via its own logic, not via build.md prose. KEEP-FLAT.
- No NEEDS-REVIEW lines.
