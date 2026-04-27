# Phase 16 — Task Fidelity Lock — REVIEW (CrossAI/Skeptical)

**Reviewer:** Senior Code Reviewer (Claude Opus 4.7, 1M ctx)
**Date:** 2026-04-27
**Range reviewed:** `git log v2.11.0..HEAD --oneline` — 13 commits on `main`
**Test environment:** Windows 10 + Python 3.11 + pytest 9.0.2

---

## 1. Verdict

**BLOCK** — Phase 16 ships green tests but the **D-06 production wire is broken** in a way the test suite cannot detect (test fixture writes a different file shape than build.md actually persists). This invalidates the core "PARAPHRASE leg closure" claim of the entire phase. Plus 2 secondary blockers that would surface as runtime BLOCKs on the first real `/vg:build` invocation.

---

## 2. Summary

I read the 4 planning docs (HANDOFF, DECISIONS, SPECS, BLUEPRINT) end-to-end, then walked the actual code paths from `task_hasher.py` through `pre-executor-check.py extract_task_section_v2 / extract_all_tasks` into the 3 new validators, into the build.md step 8c persist + step 8d audit wire, into the test fixture, and into `vg_completeness_check.py Check E`. I confirmed the 207-pass + 1-skip claim reproducibly (8.87s).

**Confidence: HIGH** on the 3 BLOCKers below — I verified each by reading file contents directly and computing the actual production behavior, not relying on test results.

The hashing helper, parser, R4 conditional caps, body-cap Check E, and schema-mode matrix all look correct and tests cover the right surface. The `verify-task-fidelity.py` validator's logic is internally consistent — but it is fed the wrong input file in production. The test that "proves" it works writes the right input directly to disk, bypassing the production code path entirely.

The orchestrator (you) was biased toward shipping; the failure modes I found are exactly the kind a green test suite hides: integration boundary mismatches between adjacent commits T-1.2 (build.md persist) and T-4.3 (validator audit).

---

## 3. BLOCK findings (must fix before push)

### B1 — `verify-task-fidelity.py` audits the WRONG file in production (the test fixture lies)

**File:** `commands/vg/build.md:1354–1391` (T-1.2 wire) + `scripts/validators/verify-task-fidelity.py:170,93` (T-4.3 audit) + `scripts/tests/root_verifiers/test_phase16_acceptance.py:266–278` (test).

**What's wrong:**
- `build.md` step 8c persists `${PROMPT_PERSIST_DIR}/${TASK_NUM}.md` containing **only** the Phase 15 D-12a injection-audit wrapper:
  ```
  <!-- audit trail -->
  ## UI-MAP-SUBTREE-FOR-THIS-WAVE
  …
  ## DESIGN-REF
  …
  ```
  It does **NOT** contain the task body. The task body lives elsewhere (`${PHASE_DIR}/.wave-tasks/task-${TASK_NUM}.md`, line 862, awk-split from PLAN).
- `verify-task-fidelity.py` `_audit_pair()` reads `prompt_path = meta_path.parent / meta_path.name.replace(".meta.json", ".md")` (line 170) and computes `prompt_lines = prompt_text.count("\n") + …` (line 93). It then compares against `meta.source_block_line_count` which the hasher computed from `extract_task_section_v2(...)["body"]` (the actual PLAN task body).
- **These are two completely different artifacts.** A typical UI task has `task body ≈ 40–200 lines` and `UI-MAP+DESIGN snippet ≈ 8–30 lines` → **shortfall_pct ≈ 70–95% → BLOCK fires on every UI task on the first real `/vg:build` after Phase 16 ships.**
- The test `TestPhase16TaskFidelity._seed_pair` (line 266) bypasses the production wire entirely: it does `body = ctx["task_context"]` then `(prompt_dir / "1.md").write_text(body, …)`. Tests pass green because the test writes the *expected* file shape, not the *actual* file shape build.md writes.

**Suggested fix (one of):**
1. Make build.md step 8c **also** persist `${TASK_NUM}.body.md` from `$TASK_CONTEXT` (line 1287 already extracts it from CONTEXT_JSON), and have `verify-task-fidelity.py` read `*.body.md` instead of `*.md`. Adjust `meta_path.name.replace(".meta.json", ".md")` → `replace(".meta.json", ".body.md")`. Add an integration test that runs the actual build.md flow (or mocks step 8c) and asserts the audit PASSes.
2. OR: change build.md step 8c to write the full composed prompt (UI-MAP + task body + DESIGN-REF + ...) and re-hash on that — but then meta.source_block_sha256 must be computed against the same wrapped form, breaking the "PLAN task body fingerprint" semantic.
3. OR (simplest): write the raw `$TASK_CONTEXT` body to `${PROMPT_PERSIST}` itself instead of the UI-MAP wrapper, and move the UI-MAP injection audit to a sibling file `${TASK_NUM}.uimap.md`. This unifies what "executor prompt body" means across P15 D-12a and P16 D-06.

Whichever path is chosen, the acceptance test `_seed_pair` must execute the **actual** build.md persist code (e.g., via subprocess invoking a one-task fixture build) — not write the expected shape directly. Otherwise the next regression slides through unseen.

---

### B2 — Meta + prompt persist is **gated on UI presence**; backend tasks get NO fidelity check

**File:** `commands/vg/build.md:1354` — outer `if [ -n "$UI_MAP_SUBTREE_BLOCK" ] || [ -n "$DESIGN_CONTEXT" ]; then …`. This conditional wraps **both** the prompt body persist AND the new D-01 meta.json sidecar persist.

**What's wrong:**
- For pure backend tasks (no UI subtree, no design-ref) → step 8c short-circuits entirely → no `.md` written, no `.meta.json` written.
- `verify-task-fidelity.py:145` then sees `meta_files = []` → emits a soft WARN and exits PASS:
  > "No .meta.json sidecars under … Either build hasn't run yet, or older build.md without P16 D-01 sidecar persist."
- **This is exactly the failure mode Phase 16 was meant to close**, but only for UI tasks. Orchestrator can paraphrase backend task bodies freely — the audit is silent.
- HANDOFF.md §"What this phase does" claims "AI orchestrator KHÔNG được paraphrase task". DECISIONS D-06 says "Catch orchestrator paraphrase tại runtime — final defense line." Both promises are violated for backend tasks.

**Suggested fix:** Move the `# Phase 16 D-01 — write .meta.json sidecar` block (lines 1374–1390) **outside** the outer UI-conditional. Always persist meta.json. Persist `${PROMPT_PERSIST}` unconditionally too (or have step 8d's audit explicitly fall back to a backend-task path that just hashes meta vs PLAN re-extract, without comparing to a prompt body). Combined with B1 fix, the cleanest design is:

```bash
PROMPT_PERSIST_DIR="${PHASE_DIR}/.build/wave-${N}/executor-prompts"
mkdir -p "$PROMPT_PERSIST_DIR" 2>/dev/null
PROMPT_BODY_PERSIST="${PROMPT_PERSIST_DIR}/${TASK_NUM}.body.md"
PROMPT_META_PERSIST="${PROMPT_PERSIST_DIR}/${TASK_NUM}.meta.json"
echo "$TASK_CONTEXT" > "$PROMPT_BODY_PERSIST"   # always
echo "$CONTEXT_JSON" | python -c "..." > "$PROMPT_META_PERSIST"   # always

# Then existing UI conditional only writes the UI-MAP wrapper for D-12a:
if [ -n "$UI_MAP_SUBTREE_BLOCK" ] || [ -n "$DESIGN_CONTEXT" ]; then
  PROMPT_UIMAP_PERSIST="${PROMPT_PERSIST_DIR}/${TASK_NUM}.uimap.md"
  { echo …UI-MAP… ; echo …DESIGN-REF… ; } > "$PROMPT_UIMAP_PERSIST"
fi
```

Update `verify-uimap-injection.py` to read `*.uimap.md` and `verify-task-fidelity.py` to read `*.body.md`.

---

### B3 — `verify-task-schema.py` and `verify-crossai-output.py` are **registered but not wired** into any skill body

**Files:** `scripts/validators/registry.yaml:721,729` declares `phases_active: [blueprint]` and `[scope, blueprint]` respectively. BLUEPRINT.md T-2.2 line 126 promises "Wired in `commands/vg/scope.md` Check section + `commands/vg/blueprint.md` step 2d validation gate." T-4.2 line 182 promises "Wiring: `commands/vg/scope.md` after Check E + `commands/vg/blueprint.md` after Check section, only triggered when `--crossai` flag in args."

**What's wrong:** I greped both `commands/vg/scope.md` and `commands/vg/blueprint.md` for `verify-task-schema`, `verify-crossai-output`, `verify-task-fidelity` — **zero matches**. None of the three validators is invoked from any skill body. They will never run in the actual /vg pipeline.

The registry tags them `phases_active`, but registry tagging is documentation, not orchestration. Without a bash invocation in the skill body (parallel to the existing `verify-uimap-injection` pattern in build.md step 8d), the validators are dead code from the user's perspective.

The 207-pass test claim hides this because the acceptance tests invoke the validators directly via `subprocess.run([…verify-task-schema.py, --phase, …])` — they never test "does running /vg:blueprint surface the validator's BLOCK?".

**Suggested fix:**
- Add to `commands/vg/blueprint.md` step 2d (after orphan-validator wires from P17 polish):
  ```bash
  TS_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-task-schema.py"
  if [ -x "$TS_VAL" ]; then
    ${PYTHON_BIN} "$TS_VAL" --phase "${PHASE_NUMBER}" \
        > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/task-schema.json" 2>&1 || true
    # parse verdict, BLOCK on BLOCK (warn-only in legacy mode by default)
  fi
  ```
- Add similar block in `scope.md` and `blueprint.md` for `verify-crossai-output.py`, **gated on `[[ "$ARGUMENTS" =~ --crossai ]]`** so it only fires after a cross-AI enrichment run.
- Extend `test_phase16_acceptance.py` with `TestPhase16Wire` class asserting `"verify-task-schema.py" in blueprint_md` and `"verify-crossai-output.py" in (scope_md + blueprint_md)`. Mirror the existing `TestPhase16BuildWire.test_task_fidelity_audit_wired` pattern.

---

## 4. WARN findings (should fix or document before next ship)

### W1 — Doc D-XX label inconsistency (`crossai-invoke.md` line 253 says "P16 D-06" but means "P16 D-05")

**File:** `commands/vg/_shared/crossai-invoke.md:253`:
> `verify-crossai-output.py` validator (P16 D-06) passes.

D-06 is `verify-task-fidelity.py` (post-spawn audit). The crossai-output validator IS the implementation of D-05. Reader confusion guaranteed.

Fix: change `(P16 D-06)` → `(P16 D-05)` in crossai-invoke.md line 253. Verify-crossai-output.py docstring is consistent (says "P16 D-05" throughout — only D-04 cross-reference appears, which is correct because D-05 references D-04's enriched flag).

### W2 — `pre-executor-check.py` argparse missing `allow_abbrev=False`

**File:** `scripts/pre-executor-check.py:608`. The 3 new validators correctly use `allow_abbrev=False` (B-fix from v2.8.6 hotfix `5b15233`), but the central `pre-executor-check.py` script — which has `--phase-dir` AND no `--phase` (yet — but easy to add) — is the exact script that triggered the v2.8.6 bug. Defense-in-depth: add `allow_abbrev=False` here too. Cost zero, prevents recurrence if anyone adds a `--phase` flag later.

### W3 — `pre-executor-check.py:639` extracts task_meta but discards `extract_task_section_v2` body for downstream context

**File:** `scripts/pre-executor-check.py:633` calls `extract_task_section()` (v1, returns str) for `task_context`, then **separately** calls `extract_task_section_v2()` (v2, returns dict) at line 647 just to compute the meta hash. For XML-format PLANs, v1 falls back to "Task N not found in PLAN files" because v1's regex is heading-only — meaning the executor prompt's `task_context` block would be the not-found sentinel, while `task_meta.source_block_sha256` would be a hash of the actual XML body. This dual-path design is a footgun for the inevitable migration to XML PLANs (Phase 16 D-02's stated trajectory).

Fix: switch the main flow to use `extract_task_section_v2(...)["body"]` for both the executor `task_context` AND the meta hash. The v1 function can stay as a back-compat shim for `ensure_siblings()` (line 491) which only needs file-path extraction. One source of truth = no drift.

### W4 — Acceptance test claim mismatch in commit message

**Commit:** `d8d7af0 test(phase-16-T5.1+T5.2): acceptance suite — 29 tests across 8 dimensions`. Actual count in `test_phase16_acceptance.py` = 29 (verified — `parametrize` matrix expands to 6 schema combos + 3 fidelity + 2 cap + 2 R4 + …). But T-5.2 promised in BLUEPRINT.md line 217 ("Extend `TestPhase15RegressionGreen.test_phase15_suite_passes` to ALSO invoke Phase 16 + Phase 17 test files in subprocess") — I do not see this extension. The commit `d8d7af0` modifies `test_phase16_acceptance.py` and `test_phase16_task_hasher.py` only (per `git show --stat`). Phase 15 cross-phase regression hook is missing.

Fix: either ship the T-5.2 extension or update BLUEPRINT.md to drop it as `out-of-blueprint` deferred. Don't leave the commit-message-vs-blueprint gap silent.

### W5 — `verify-crossai-output.py` git diff parser doesn't validate that the `<task>` block opening `+` line wasn't itself a removal-then-add

**File:** `scripts/validators/verify-crossai-output.py:75–113`. The diff parser tracks `current_task` based on any line containing `<task id="N">` (including context lines). If a cross-AI run **removed** task N entirely and **added** task N with new shorter body, the `task_open_re.search(line)` matches both the `-` and `+` line in the diff. The parser doesn't distinguish — it treats the `+` count as additive growth from the previous version. This could give false-PASS on a "rewrite from scratch" enrichment that legitimately should be reviewed.

Fix: when entering a task block via a `+` line that matches `task_open_re`, also count whether there was a corresponding `-` line opening the same task earlier in the same hunk; if so, treat the `+prose_added` as "rewrite delta" and apply the threshold against `(added - removed)` not `added` alone. Or simpler: add a unit test fixture for the "rewrite same task with shorter body" scenario and pin current behavior with a documented `# Known limitation` comment.

### W6 — Hash determinism rule "collapse 3+ blanks" not "2+" — silent semantic decision

**File:** `scripts/lib/task_hasher.py:37` `_BLANK_LINE_RUN = re.compile(r"\n{3,}")`. SPECS.md D-01 line 36 says "Collapse runs of 2+ blank lines into single blank line" — but the regex `\n{3,}` collapses 3+ NEWLINES (= 2+ blank lines = 1 separator + 1+ blank). I verified empirically: `"A\n\nB"` (1 blank line, 2 newlines) hashes the same as `"A\n\n\nB"` (2 blank lines, 3 newlines) only after the regex matches `\n\n\n` → `\n\n`. So `\n{3,}` is correct semantics-wise, but the SPECS prose ("2+ blank lines") is ambiguous (could mean 2+ blank chars, 2+ newlines, or 2+ blank-line gaps). Document the chosen semantic in the SPECS to prevent a future "fix" from breaking determinism.

Fix: edit SPECS.md D-01 line 36: `"2. Collapse runs of 3+ consecutive newlines (= 2+ empty lines) into a single blank line (= 2 newlines)."` Or update the regex to `\n{2,}` if the SPECS literal interpretation was intended (would be a hash-breaking change — defer to next major bump).

---

## 5. INFO / positives

- **`task_hasher.py` is well-scoped, tested, and pure** — `task_block_sha256` + `stable_meta` separation is clean. CRLF normalization, NFC, trailing-strip, blank-collapse all behave correctly under unit tests. Empty/None coercion works (verified: both `""` and `None` produce the SHA256 of empty input). Unicode NFC works (verified: `café` NFC and NFD hash identically).
- **`extract_all_tasks` precedence rule** (XML-first then heading, with XML id collision suppressing heading) is correct and matches SPECS D-02. Mixed-format detection works. Frontmatter parser handles inline lists, multi-line lists, integers, booleans, and quoted strings with embedded colons.
- **`_common.py` `find_phase_dir` reuse** in all 3 validators — good (centralized phase-resolution fix from OHOK v2 audit). `Output` dataclass with `add()` (BLOCK) vs `warn()` (WARN) verdict escalation is the right shape.
- **R4 conditional caps in pre-executor-check.py** (lines 707–745) are clean: enriched flag → bumped caps + total → emit JSON + log to stderr. Build.md correctly reads `ctx.get('applied_caps') or {default…}` so older CONTEXT_JSON without P16 D-04 still works.
- **Check E in vg_completeness_check.py** is well-engineered: cap precedence is `body_max_lines > enriched > default`, `cap_source` reported in evidence, integrated into existing `check_e/check_a/check_c` exit-code aggregation. `--allow-long-task` override correctly downgrades BLOCK→WARN.
- **All 3 new validators use `argparse(allow_abbrev=False)`** — the v2.8.6 regression is locked out at the validator boundary (just not at pre-executor-check.py — see W2).
- **Atomic commits** are clean: each touches 1–5 files, each runs standalone, each commit message matches `feat(phase-16-T<N>.<M>): <subject>` convention. No commit half-breaks the suite (verified by ordered re-traversal — registry T-0.1 references files added in later commits, but registry parse doesn't validate paths exist, so harmless).
- **Docstrings + planning hand-back markers** (`[T-X.Y implements; T-5.1 verifies]`) in SPECS.md make code → spec traceability easy.

---

## 6. Test verification

Reproduced the 207-pass + 1-skip claim:

```
$ python -m pytest \
    scripts/tests/root_verifiers/test_phase15_acceptance.py \
    scripts/tests/root_verifiers/test_phase15_design_extractors.py \
    scripts/tests/root_verifiers/test_phase15_validators_and_matrix.py \
    scripts/tests/root_verifiers/test_phase16_acceptance.py \
    scripts/tests/root_verifiers/test_phase16_task_hasher.py \
    scripts/tests/root_verifiers/test_phase17_acceptance.py \
    scripts/tests/root_verifiers/test_phase17_extraction_fixes.py \
    scripts/tests/root_verifiers/test_phase17_helpers.py
======================= 207 passed, 1 skipped in 8.87s ========================
```

**Breakdown actually observed:**
- P15 acceptance: 80 tests (rough count from `[ 7%]→[ 38%]` band × ratio)
- P15 design extractors: 4 (1 skipped — known)
- P15 validators+matrix: 17
- **P16 acceptance: 29** (matches commit `d8d7af0` claim)
- **P16 task_hasher: 14** (matches `2dbb7f8` commit message)
- P17 acceptance: 42
- P17 extraction fixes: 4
- P17 helpers: 18
- **Total = 208 collected, 1 skipped, 207 passed** ✓

No flaky tests on 1 run (8.87s wall time). The Phase 16 hashing tests are deterministic (re-ran 3 times, same hex digests).

**Critical observation about test coverage gaps** (already enumerated in BLOCK section, restated for clarity):
- No test exercises the actual `commands/vg/build.md` step 8c → step 8d pipeline end-to-end. The fidelity test fixture writes the prompt body shape it *expects* the audit to receive, not the shape build.md *actually* writes.
- No test asserts that `verify-task-schema.py` or `verify-crossai-output.py` are wired into any skill body. They could be entirely deleted from `scope.md`/`blueprint.md` and tests would stay green.
- `TestPhase17OrphanValidators.test_blueprint_md_wires_validator` exists for P17 polish — the same pattern should be applied for P16 validators in T-5.1's wave.

---

## 7. Recommendation

**Do NOT push v2.12.0-phase-16 in current state.** The phase ships a green test suite for a feature that doesn't work end-to-end:
- D-06 audit fires false BLOCK on every UI task on first real `/vg:build` (B1).
- D-06 audit silently skips backend tasks entirely (B2).
- D-02 schema validator + D-05 crossai-output validator never run from any skill (B3).

**Minimum to unblock ship:**
1. Fix B1 + B2 together (one design change to build.md step 8c — separate task body persist from UI-MAP wrapper persist; unconditionally persist both meta + body).
2. Fix B3 by adding `verify-task-schema.py` and `verify-crossai-output.py` invocations to scope.md/blueprint.md skill bodies (mirror the build.md step 8d pattern for task-fidelity).
3. Add 1 acceptance test that runs an actual minimal `/vg:build` flow on a fixture phase and asserts the persisted `<task>.body.md` exists, has line count ≥ N, and audit returns PASS. Without this, the next regression here is invisible.
4. Address W1, W4 (doc/spec alignment cleanup; trivial).

**Defer for next polish:** W2, W3, W5, W6 are non-blocking but worth queueing.

---

## One-paragraph reply summary (also in main reply text)

The Phase 16 hashing helper, parser, R4 caps, and Check E are correctly built and tested. **However, the keystone D-06 audit is broken in production** — `build.md` step 8c persists a UI-MAP+DESIGN-REF wrapper to `${TASK_NUM}.md`, not the task body, so `verify-task-fidelity.py`'s line-count comparison is comparing two different artifacts and will fire false BLOCK on every UI task. The test fixture hides this by writing the expected body shape directly to the file, bypassing the production code path. Compounding this: the persist block is gated on UI presence so backend tasks never get a meta sidecar at all (silent PASS — paraphrase still possible), and `verify-task-schema.py` + `verify-crossai-output.py` are registered but not wired into any skill body (registry's `phases_active` tag is documentation, not orchestration). 207/207 tests pass but the phase as shipped does not close the PARAPHRASE leg it claims to. **Verdict: BLOCK.**
