# Plan: B70 — Legacy phase PIPELINE-STATE.json backfill + /vg:next BLOCK + recon-state invalidate

## Context

**User report (dogfood RTB):** Phase `7.16-ssp-publisher-ui-alignment` chạy review xong, `/vg:next` gợi ý `/vg:test` thay vì `/vg:test-spec`. Investigation:

- VG_HOME = v4.61.0 (chứa B69 fix routing).
- Phase 7.16 đã chạy review TRƯỚC khi VG_HOME upgrade từ v4.40.0 → v4.61.0.
- `REVIEW.md`, `RUNTIME-MAP.json` tồn tại nhưng `PIPELINE-STATE.json` KHÔNG có (v4.40.0 close.md không emit).
- `/vg:next` fallback im lặng `/vg:test` (default cũ).
- Bonus: `.recon-state.json` stale từ phase build có `next_command: /vg:build 7.16`.

**Intended outcome:** Eliminate 3 silent-failure modes:
1. Legacy phase không có PIPELINE-STATE.json → no fallback misleading.
2. /vg:next fallback silent → BLOCK + actionable message.
3. Stale `.recon-state.json` từ previous phase step → invalidate.

Harness scope only. Không touch RTB hoặc dogfood project.

## Approach

3 sub-batches + codex audit pre/post.

### Phase 0 — Codex audit on this plan (PRE)

Spawn codex CLI `--tier adversarial --sandbox read-only` với plan markdown này. Audit verdict: PASS / PASS-WITH-NOTES / FAIL. Output: `dev-phases/B70-legacy-pipeline-state-migration/CODEX-AUDIT.md`.

BLOCKERs → revise plan before B70a. MAJORs → integrate. MINORs → note.

### Batch 70a — Migration backfill script — v4.62.0

**Create:**
- `scripts/migrations/v4.61.0_backfill_pipeline_state.py`
  - Stdlib only.
  - Args: `--planning-dir .vg/phases --dry-run --verbose --phase NN (filter)`.
  - For each `.vg/phases/*/`:
    - SKIP if `PIPELINE-STATE.json` already exists.
    - SKIP if `REVIEW.md` does not exist (review chưa chạy).
    - SKIP if phase number isn't parseable.
    - Detect last completed step from artifact presence:
      - `SPECS.md` → specs done
      - `CONTEXT.md` + `DISCUSSION-LOG.md` → scope done
      - `PLAN.md` + `API-CONTRACTS.md` + `TEST-GOALS.md` → blueprint done
      - `SUMMARY.md` (with wave-N evidence) → build done
      - `REVIEW.md` + `RUNTIME-MAP.json` → review done → emit `next_command='/vg:test-spec ${phase}'`
      - `DEEP-TEST-SPECS.md` + `LIFECYCLE-SPECS.json` → test-spec done → emit `next_command='/vg:test ${phase}'`
      - `SANDBOX-TEST.md` + `.test-step-status.json` → test done → emit `next_command='/vg:accept ${phase}'`
    - Write `PIPELINE-STATE.json` with `steps[]` derived from artifact heuristic + `next_command` + `next_command_emitted_at` + `backfilled_at` + `backfilled_by='v4.61.0_backfill'`.
  - Print report: `{scanned, skipped, backfilled, errors}`.

- `scripts/hooks/vg-session-start.sh` — append auto-invoke block:
  - Read `VG_HOME/VERSION`.
  - Read `.vg/.last-migration-version` (project-level, create on first run).
  - If `version > last-migration` AND `version >= 4.62.0` → run `python scripts/migrations/v4.61.0_backfill_pipeline_state.py --planning-dir .vg/phases` → write `.vg/.last-migration-version`.
  - Non-blocking (warn on fail, don't abort session).

**Test:** `tests/test_batch70_legacy_state_migration.py` — 14 tests:
1. Skip phase with PIPELINE-STATE.json present.
2. Skip phase without REVIEW.md.
3. Backfill phase with REVIEW.md + RUNTIME-MAP.json → next_command=/vg:test-spec.
4. Backfill phase post-test-spec → next_command=/vg:test.
5. Backfill phase post-test → next_command=/vg:accept.
6. --dry-run does not write file.
7. --phase NN filter only touches matching dir.
8. Output report counts correct.
9. Idempotent — second run on backfilled phase = skipped.
10. Phase number unparseable → graceful skip (not crash).
11. Backfilled file schema matches close.md write format (next_command, next_command_emitted_at, backfilled_at, backfilled_by).
12. session-start hook auto-invoke gated by version comparison.
13. session-start hook writes `.vg/.last-migration-version` after run.
14. session-start hook non-blocking on migration failure.

**Commit:** `feat(migration): B70a — v4.61.0 PIPELINE-STATE backfill + session-start auto-invoke`
**Tag:** v4.62.0

### Batch 70b — /vg:next BLOCK gate for legacy inconsistency — v4.62.1

**Modify:**
- `commands/vg/next.md` — insert NEW BLOCK gate BEFORE Route 0 priority check (around line 60):
  ```bash
  # B70b — legacy state inconsistency BLOCK
  if [ -f "${PHASE_DIR}/REVIEW.md" ] && [ ! -f "${PHASE_DIR}/PIPELINE-STATE.json" ]; then
    if [[ ! "$ARGUMENTS" =~ --repair ]]; then
      echo "⛔ Phase ${PHASE_NUMBER} LEGACY-STATE-INCONSISTENT — REVIEW.md exists but PIPELINE-STATE.json missing." >&2
      echo "   Likely cause: review closed on VGFlow <v4.61.0 (pre-B69)." >&2
      echo "   Fix automatic: /vg:next --repair (runs v4.61.0_backfill_pipeline_state.py)" >&2
      echo "   Fix manual:    /vg:review --resume ${PHASE_NUMBER}" >&2
      exit 1
    else
      python ${VG_HOME}/scripts/migrations/v4.61.0_backfill_pipeline_state.py --planning-dir .vg/phases --phase ${PHASE_NUMBER} || true
      echo "✓ --repair invoked; re-reading PIPELINE-STATE.json" >&2
    fi
  fi
  ```

**Test:** `tests/test_batch70b_next_legacy_block.py` — 6 tests:
1. Block fires when REVIEW.md exists + state missing.
2. No block when state file exists.
3. No block when REVIEW.md missing (early phase).
4. --repair flag bypasses block + invokes migration script.
5. Exit code 1 on block (gate semantics).
6. Mirror parity (commands + .claude/commands).

**Commit:** `feat(next): B70b — BLOCK on legacy PIPELINE-STATE inconsistency`
**Tag:** v4.62.1

### Batch 70c — review/close.md invalidate stale recon-state — v4.62.2

**Modify:**
- `commands/vg/_shared/review/close.md` — after PIPELINE-STATE.json write block (around line 313), append:
  ```python
  # B70c — invalidate stale .recon-state.json next_command from prior phase step
  recon_state = Path("${PHASE_DIR}/.recon-state.json")
  if recon_state.exists():
      try:
          r = json.loads(recon_state.read_text(encoding="utf-8"))
          if r.get("next_command") and not r["next_command"].startswith("/vg:test-spec"):
              r["next_command"] = None
              r["next_command_invalidated_at"] = now
              r["next_command_invalidated_by"] = "review/close.md:B70c"
              recon_state.write_text(json.dumps(r, indent=2))
      except Exception:
          pass  # don't fail close on recon-state corruption
  ```

**Test:** `tests/test_batch70c_recon_state_invalidate.py` — 5 tests:
1. Stale recon-state.next_command → null after review close.
2. recon-state.next_command already null → no-op.
3. recon-state.next_command='/vg:test-spec ...' → preserved (not invalidated — already correct).
4. Corrupt recon-state.json → close does not fail.
5. Mirror parity.

**Commit:** `feat(review): B70c — invalidate stale recon-state on review close`
**Tag:** v4.62.2

### Phase 0 replay — Codex audit on v4.61.1..v4.62.2 diff (POST)

After B70c lands, re-spawn codex with cumulative diff + Phase 0 audit. Confirm BLOCKER + MAJOR items addressed. Output: `dev-phases/B70-legacy-pipeline-state-migration/CODEX-AUDIT-REPLAY.md`.

## Critical files

- `scripts/migrations/v4.61.0_backfill_pipeline_state.py` (NEW)
- `scripts/hooks/vg-session-start.sh` (append auto-invoke)
- `commands/vg/next.md` (line ~60 — insert BLOCK gate)
- `commands/vg/_shared/review/close.md` (line ~313 — append invalidate block)
- `commands/vg/LIFECYCLE.md` (note B70 in version history)

## Risks + mitigations

1. **Backfill wrong next_command** — heuristic from artifact presence could mis-detect last step. Mitigation: conservative — require BOTH primary + secondary artifacts (e.g. REVIEW.md AND RUNTIME-MAP.json) before declaring review done.

2. **session-start hook latency** — migration scan on every session start = slow. Mitigation: `.vg/.last-migration-version` gates run to once-per-version-bump.

3. **BLOCK gate too aggressive** — phase intentionally without review yet → false BLOCK. Mitigation: check REVIEW.md presence as guard, only block when review EXISTS but state missing.

4. **recon-state invalidate breaks downstream consumers** — if other tool reads recon-state.next_command for routing. Mitigation: only invalidate when next_command does NOT start with /vg:test-spec (preserve correct routing if present).

5. **Mirror drift** — every batch includes mirror parity test.

6. **Migration on Windows path issues** — `.vg/.last-migration-version` write encoding. Mitigation: encoding="utf-8" explicit, Path-based.

## Verification

- Phase 0: inspect `dev-phases/B70-legacy-pipeline-state-migration/CODEX-AUDIT.md`.
- Per batch:
  - `python -m pytest tests/test_batch70_legacy_state_migration.py -v` (14 GREEN)
  - `python -m pytest tests/test_batch70b_next_legacy_block.py -v` (6 GREEN)
  - `python -m pytest tests/test_batch70c_recon_state_invalidate.py -v` (5 GREEN)
- Mirror: `bash scripts/generate-codex-skills.sh --force --force-overwrite-curated && python scripts/verify-codex-mirror-equivalence.py`
- E2E manual: create fixture phase with REVIEW.md + RUNTIME-MAP.json but no PIPELINE-STATE.json → run migration → verify next_command='/vg:test-spec'.
- Tag v4.62.x → wait `gh run list` both `release` + `Test` workflow GREEN.
- Codex replay: inspect `dev-phases/B70-legacy-pipeline-state-migration/CODEX-AUDIT-REPLAY.md`.

## Out of scope

- Auto-fix `.recon-state.json` for non-review phase boundaries (build/test/etc.) — deferred to B71 if needed.
- Migration of `.vg/PIPELINE-STATE.json` (root-level, project) — separate concern.
- Bidirectional state recovery (artifact → state and state → artifact) — only one direction here.
