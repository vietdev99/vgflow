# B70 Plan — Adversarial Audit (Codex-fallback)

**Verdict:** FAIL

The plan operates on a partially-incorrect mental model of how PIPELINE-STATE.json and `.recon-state.json` are produced and consumed. Three of the proposed mechanisms are either redundant, racey, or schema-incompatible with what the rest of the harness already writes. Several proposed backfills will produce *new* silent failure modes worse than the one being fixed.

---

## BLOCKERS (must fix before B70a)

- **B-1: Bug-report premise is wrong — `PIPELINE-STATE.json` for 7.16 EXISTS but is INCOMPLETE.**
  Direct inspection of `D:/Workspace/Messi/Code/RTB/.vg/phases/7.16-ssp-publisher-ui-alignment/PIPELINE-STATE.json` returns:
  ```json
  {"steps":{"test-spec":{"status":"done","verdict":"PASS",...}},
   "pipeline_step":"test-spec-complete",
   "next_command":"/vg:test 7.16",
   "next_command_emitted_at":"2026-05-17T18:27:29Z"}
  ```
  The file is NOT missing — it was written by `test-spec/close.md` later, *after* review ran (without a `steps.review` entry because v4.40.0 review/close didn't write that key). And `next_command` IS `/vg:test 7.16`, which is the CORRECT value for current pipeline position (test-spec done → test next). The user-reported "PIPELINE-STATE.json KHÔNG có" appears to conflate "no `steps.review` subkey" with "file missing". The real bug is **stale `recon-state.next_command='/vg:build 7.16'`** dominating routing because /vg:next's Route 0b/recon route reads `.recon-state.json` (which reports `build: partial`) before reading `PIPELINE-STATE.json`. — **Fix:** rewrite the plan's problem statement against the actual files; confirm the bug repro path; do NOT ship a backfill script if the real defect is `/vg:next` routing precedence between recon-state and pipeline-state.

- **B-2: recon-state invalidate (B70c) is FUTILE — phase-recon.py re-emits `next_command` every run.**
  `scripts/phase-recon.py:824` writes `next_command: f"/vg:{next_step} {phase_num}"` from the heuristic `first step not done`. Even if `review/close.md` nukes the stale `next_command` to `null`, the very next `/vg:next` invocation re-runs `phase-recon.py --quiet`, which rewrites `.recon-state.json.next_command` from scratch based on `pipeline_position[*].status`. **The invalidate write lives for milliseconds.** — **Fix:** either (a) drop B70c entirely and instead fix `/vg:next` to prefer `PIPELINE-STATE.next_command` over `recon-state.next_command` when both present and pipeline-state is newer, OR (b) modify `phase-recon.py` to recognise the review-complete signal and emit `/vg:test-spec` directly.

- **B-3: Schema drift — backfilled `steps[]` diverges from close.md write.**
  `commands/vg/_shared/review/close.md` lines 295–315 writes ONLY top-level keys: `status`, `pipeline_step`, `updated_at`, `next_command`, `next_command_emitted_at`. It does NOT touch `steps.review` at all. Yet the plan's backfill emits a fully-populated `steps[]` dict (steps.specs/scope/blueprint/build/review/test-spec/test). After backfill, a phase that subsequently runs a fresh review on v4.62.x writes ONLY top-level keys → `steps.review` retains the *backfilled* values (potentially WRONG verdict, wrong finished_at) forever. Existing files like `07.10/PIPELINE-STATE.json` already carry `steps.review.verdict='PASS'` etc., so the canonical schema today is "whoever closed last writes `steps.<X>`". **Plan must specify which writer owns each key, and update review/close.md to also emit `steps.review` so future runs overwrite the backfilled stub.** — **Fix:** add a B70d (or fold into B70a): patch `review/close.md` to write `steps.review = {status, verdict, finished_at, ...}` alongside `next_command`. Otherwise backfill is a one-way write that calcifies wrong data.

- **B-4: BLOCK gate races mid-review writes.**
  The plan asserts "REVIEW.md exists + PIPELINE-STATE.json missing → BLOCK." But `review/close.md`'s `write_artifacts` step (line 156–164) `git add REVIEW.md` / `RUNTIME-MAP.json` BEFORE the `complete` step (line 295) writes PIPELINE-STATE.json. There is also a `git commit` between them. If `/vg:next` is invoked during that window (another terminal, a parallel codex/gemini agent, or a session-start hook firing on RESUME mid-review), the BLOCK fires falsely and tells the user to run `--repair`, which then writes a backfilled state that the real review/close will OVERWRITE moments later — **losing the in-progress review's verdict.** — **Fix:** gate the BLOCK on a stable terminal signal, not artifact presence. Use `.step-markers/review/complete.done` (the marker `review/close.md` writes at line 487) as the "review is truly closed" sentinel. Block only when `complete.done` exists AND `PIPELINE-STATE.json` is missing.

- **B-5: Heuristic ignores review verdict — backfilled next_command='/vg:test-spec' bypasses verdict gate in /vg:next.**
  `commands/vg/next.md` line 185 enforces: if `review.verdict ∈ {BLOCK, FAIL}` → refuse to auto-advance. The backfill script blindly sets `next_command='/vg:test-spec ${phase}'` when REVIEW.md + RUNTIME-MAP.json both exist, regardless of REVIEW.md content. Legacy phases with FAILED review (REVIEW.md present, gate=BLOCK in GOAL-COVERAGE-MATRIX.md) will be backfilled to advance to /vg:test-spec, then the verdict gate will fire (because `steps.review.verdict` is now backfilled — to what? plan doesn't specify) or fail silently if backfill leaves `steps.review.verdict` empty. **Plan must parse GOAL-COVERAGE-MATRIX.md / REVIEW.md verdict and set both `steps.review.verdict` AND skip/redirect next_command on BLOCK/FAIL.** — **Fix:** scan `${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md` for `Gate:` line (PASS/BLOCK/TEST_PENDING). Map BLOCK/FAIL → next_command=null + emit warning. Map TEST_PENDING/PASS → /vg:test-spec.

- **B-6: Migration version-gate logic in session-start hook is wrong on first install.**
  Plan: "If `version > last-migration` AND `version >= 4.62.0` → run migration." On a fresh project with no `.vg/.last-migration-version` file, the check becomes `"" > ""` (false) OR triggers a write of `4.62.0` and skips. Plan does not specify default value when file absent. Worse, the bash `version > last-migration` is **string comparison** — `"4.62.10" > "4.62.2"` evaluates as `false`. — **Fix:** explicit default `last_migration="0.0.0"` when file absent; use Python semver compare (or `sort -V`) not bash string compare.

---

## MAJORS (integrate into batch scope)

- **M-1: Heuristic false-positives — SUMMARY.md presence ≠ build done.**
  `SUMMARY.md` is written by build at wave boundaries even on FAILED waves (see build/close.md context). Plan maps `SUMMARY.md` → "build done", which will mark crashed-mid-wave builds as complete. Need to inspect `.step-markers/build/run-complete.done` or `pipeline_step: build-complete` from a prior partial state, not raw file presence. RTB phase 7.16 in fact has `recon: build.status=partial` despite SUMMARY.md existing in similar sibling phases.

- **M-2: Heuristic false-positives — REVIEW.md present without RUNTIME-MAP.json.**
  Plan requires BOTH for review-done, but several mid-review failure modes leave `REVIEW.md` (preliminary findings) without `RUNTIME-MAP.json` (which is written at close). Conversely, `--retry-failed` runs re-write `RUNTIME-MAP.json` while `REVIEW.md` may be from previous run. Need timestamp comparison + `.step-markers/review/complete.done` sentinel, not pair-presence.

- **M-3: `--repair` flag invokes migration synchronously inside /vg:next — hides errors.**
  Code: `python ${VG_HOME}/scripts/migrations/v4.61.0_backfill_pipeline_state.py ... || true`. The `|| true` swallows non-zero exits silently. If backfill fails (e.g. parse error on REVIEW.md, encoding issue, disk full), user sees "✓ --repair invoked; re-reading PIPELINE-STATE.json" then the next read fails again — infinite-loop pattern. **Fix:** capture exit code, on failure print actual stderr to user and exit 1.

- **M-4: Cross-platform — `bash` invocation inside next.md when shell is PowerShell.**
  The repo's host environment is Windows PowerShell (per `env` block in system context: "Shell: PowerShell"). The plan inserts `if [ -f "${PHASE_DIR}/REVIEW.md" ] && ...` bash syntax inside `commands/vg/next.md`. Existing next.md mixes bash + python invocations — works because Claude orchestrator runs commands via Bash tool. But `${VG_HOME}` resolution on Windows with bash path semantics (`$HOME/.vgflow` vs `C:\Users\...`) needs explicit testing. Plan's existing risk #6 mentions encoding but ignores VG_HOME path translation.

- **M-5: scripts/ does NOT mirror to codex-skills/ — but migrations dir is reachable from BOTH.**
  Plan check #7 says "scripts/ doesn't mirror, confirm." Confirmed via `scripts/generate-codex-skills.sh` — only commands/ + skills/ mirror. But `${VG_HOME}/scripts/migrations/v4.61.0_backfill_pipeline_state.py` is invoked from BOTH /vg:next BLOCK gate AND session-start hook (which lives in `scripts/hooks/`). On a Codex orchestrator session, `${VG_HOME}` points to the codex-installed dir which has `codex-skills/` but does the install also copy `scripts/`? **Plan does not specify whether codex install includes `scripts/` tree.** If not, --repair fails on codex sessions. Add mirror parity test for `scripts/migrations/` reachability from codex install layout.

- **M-6: Version bump scheme — three patch tags v4.62.0/.1/.2 ship unrelated features as separate releases.**
  B70a (migration script + hook), B70b (BLOCK gate), B70c (invalidate) are NOT independently shippable — B70b assumes B70a exists (calls migration script), and B70c is futile without B70a. A user upgrading only to v4.62.1 gets BLOCK gate but no `/vg:next --repair` migration script. Should be one v4.62.0 bundle. Plan's separation invites partial-upgrade incoherence. (Confirmed canonical scheme by v4.61.0/.1 hotfix pattern — but those WERE hotfixes; B70 is one feature.)

- **M-7: Backfilled `next_command_emitted_at` collides with future re-emit semantics.**
  When a real review runs on a backfilled phase later, `next_command_emitted_at` gets overwritten. Consumers comparing emitted_at to determine "is this fresh?" lose the ability to distinguish backfill timestamp (e.g. 2026-05-17T) from a real emit (e.g. 2026-06-01T). Plan adds `backfilled_at` + `backfilled_by` but doesn't say those persist across subsequent close.md writes. Per close.md line 313, `p.write_text(json.dumps(s, indent=2))` writes the merged dict back — so `backfilled_*` keys DO persist (good), but `next_command_emitted_at` gets refreshed. Acceptable, but document explicitly.

- **M-8: `.last-migration-version` placement at `.vg/.last-migration-version`.**
  Sits at project root in `.vg/`. The path is gitignored? Check `.gitignore` includes `.vg/.last-migration-version` else commits leak per-developer migration state. (Same issue applies to `.recon-state.json` — plan doesn't audit ignore patterns.)

---

## MINORS (note for follow-up)

- **m-1:** Plan says "Stdlib only" for migration script — good — but doesn't enforce Python ≥3.8 (f-strings + Pathlib + typing.Literal compatibility window). Specify minimum Python.
- **m-2:** Backfill report format `{scanned, skipped, backfilled, errors}` lacks per-phase detail. Include phase IDs in `errors[]` so user knows which phase to fix manually.
- **m-3:** `--phase NN` filter — what NN format? `7.16` (with dot) vs `07.10` (zero-padded) vs `7` (numeric)? Plan ambiguous; phase dirs use mixed formats (`07.10-...`, `7.16-...`, `13-...`).
- **m-4:** Mirror-parity test #6 in B70b enumerates "commands + .claude/commands" — but mirror also covers `codex-skills/`. Test name implies only 2 destinations; should be 3.
- **m-5:** `out of scope` item "Auto-fix `.recon-state.json` for non-review phase boundaries" is the WRONG framing — per B-2 above, the `recon-state.next_command` is auto-derived, so "fixing" it isn't needed; the real fix is `/vg:next` routing precedence. Reword scope.
- **m-6:** No telemetry emit for `migration.ran` / `migration.backfilled.count` — VG harness emits telemetry for nearly every other gate. Add `emit_telemetry "migration.ran"` to match convention.
- **m-7:** Hook insertion point "append" to vg-session-start.sh — but the script `printf`s JSON to stdout for Claude's `additionalContext` hook protocol. Inserting migration AFTER that JSON write will dump migration stdout into the JSON stream, corrupting hook output. **Insert BEFORE the printf, not after.** (Borderline blocker — verify.)
- **m-8:** Plan's "session-start hook latency" mitigation via version gate is good, but doesn't address slow scans on projects with 100+ phases (RTB has ~30+ already). Migration walks every dir; should glob `PIPELINE-STATE.json` absence first to short-circuit.

---

## Coverage gaps

- **G-1:** No test for "REVIEW.md gate=BLOCK + RUNTIME-MAP.json present → backfilled next_command should NOT be `/vg:test-spec`" (related to B-5). Add test.
- **G-2:** No test for parallel-session race: two concurrent `/vg:next` invocations, both seeing missing PIPELINE-STATE.json, both calling --repair simultaneously → file write race. Add fcntl/flock test.
- **G-3:** No test for "backfilled file then re-running review/close.md preserves `backfilled_by` provenance but updates `steps.review`" (schema-merge contract test). Without it, B-3 silently breaks.
- **G-4:** No test for `--repair` failure → user-visible error (M-3 silent swallow).
- **G-5:** No test for `.vg/.last-migration-version` semver vs string comparison (B-6).
- **G-6:** No test for "phase-recon.py re-runs after recon-state invalidate → next_command repopulated wrong" (B-2). Without it, B70c ships a placebo.
- **G-7:** No E2E test that takes a real legacy v4.40.0 phase fixture (REVIEW.md + RUNTIME-MAP.json + no PIPELINE-STATE.json) through migration, then through /vg:next, asserts `/vg:test-spec` invocation. Plan says "manual E2E" — should be automated.
- **G-8:** No test for codex-skills install layout reachability of migration script (M-5).
- **G-9:** No test for session-start hook stdout interleaving with hook JSON contract (m-7).
- **G-10:** 25 total tests is light for a migration that mutates files in `.vg/phases/*` across N project shapes. Add fuzz fixtures: corrupt JSON, BOM-prefixed UTF-8, CRLF line endings (Windows), symlinked PIPELINE-STATE.json.

---

## Risk assessment

**Overall risk: HIGH.** The plan ships three coupled mechanisms (backfill / BLOCK / invalidate) addressing what the bug report frames as one defect — but the bug report itself is mis-diagnosed (B-1) and the invalidate (B70c) is provably futile (B-2). Backfill (B70a) writes a schema that the rest of the harness will partially overwrite (B-3), and the BLOCK gate (B70b) races with mid-review file writes (B-4) and will fire false positives during normal `/vg:review` runs.

**The good:** intent is correct — legacy-phase compat IS a real concern post-B69, and explicit gating beats silent fallback. Conservative artifact-pair heuristic, idempotency-via-skip, and `--repair` flag are sound primitives.

**The bad:** Plan does not interrogate WHY `/vg:next` chose `/vg:test` instead of `/vg:test-spec` for phase 7.16. Looking at actual files: `7.16/PIPELINE-STATE.json.next_command = "/vg:test 7.16"` (written by test-spec/close.md on 2026-05-17). `7.16/.recon-state.json.recommended_action.next_command = "/vg:build 7.16"`. Both are wrong from a "review-just-ran" perspective because neither reflects review's verdict — review wrote `steps.review` is MISSING from the pipeline-state. The ROOT cause is **review/close.md does not write `steps.review`** — a single-line fix in B69's diff would have prevented all of this. B70 spends 25 tests + 3 tags on infra that doesn't address the root.

**Recommended sequence (re-plan):**
1. Reproduce the actual bug end-to-end against current v4.61.0 with phase 7.16 — confirm or refute B-1.
2. Patch `review/close.md` to write `steps.review = {status:done, verdict:<parsed>, finished_at:now}` alongside `next_command` (one-line fix to B69 oversight). Tag v4.61.2.
3. Fix `/vg:next` routing precedence: prefer `PIPELINE-STATE.next_command` over `recon-state.next_command` when both present and pipeline-state.updated_at is newer than recon-state.classified_at. Tag v4.61.3.
4. ONLY THEN, if legacy phases still need backfill, ship a minimal migration that reads GOAL-COVERAGE-MATRIX.md verdict and writes a complete `steps.review` (not the heuristic chain). Tag v4.62.0 as a single bundle.
5. Drop B70b BLOCK gate — verdict-aware step 3 makes it redundant.
6. Drop B70c recon-state invalidate — phase-recon re-derives, so the write is futile.

**Verdict: FAIL** — re-plan against actual root cause + actual file state. Do not merge B70a/b/c as currently specified.
