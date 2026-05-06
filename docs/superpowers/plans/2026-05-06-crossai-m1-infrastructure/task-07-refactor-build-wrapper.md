# Task 07: Refactor `vg-build-crossai-loop.py` to use library

**Goal:** Convert existing `scripts/vg-build-crossai-loop.py` (656 lines) into a thinner wrapper only after Task 06 has frozen current build behavior in the library. Preserve CLI signature (`--phase X --iteration N --max-iterations M`) AND preserve current behavior at the observable boundary: events, output paths, findings shape, diff-aware brief content, and infra-fail semantics.

**Files:**
- Modify: `scripts/vg-build-crossai-loop.py`
- Mirror: `.claude/scripts/vg-build-crossai-loop.py`
- Test: existing `scripts/tests/test_codex_blueprint_plan_contract.py`, `scripts/tests/test_build_references_exist.py`, etc. — full regression must pass.

---

- [ ] **Step 1: Capture current behavior baseline**

Run existing tests + record outputs:

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_codex_blueprint_plan_contract.py \
                  scripts/tests/test_build_references_exist.py \
                  scripts/tests/test_codex_runtime_adapter.py \
                  -v 2>&1 | tail -10
```

Record passed count. Goal: number unchanged after refactor. Also record the current build-loop output contract so the new parity test can compare:

- output dir name: `crossai-build-verify`
- raw outputs: `codex-iterN.md`, `gemini-iterN.md`
- findings JSON keys
- event names `build.crossai_*`

- [ ] **Step 2: Read existing wrapper**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
wc -l scripts/vg-build-crossai-loop.py
```

Expected: 656 lines. Inspect `pack_review_brief()` (around line 123-247), `invoke_codex()` (250-285), `invoke_gemini()` (287-315), `parse_verdict()` helpers, and `main()` (around 470+). These are the behaviors Task 06 must preserve.

- [ ] **Step 3: Refactor — delegate to library without changing observable behavior**

Do not rewrite the wrapper into a simplified prompt packer. Instead:

1. Move only orchestration internals that are already covered by the new build-parity tests into `crossai_loop.py`.
2. Keep `pack_review_brief()` functionally identical, including git diff and commit evidence.
3. Keep current `<crossai-build-verdict>` parsing contract and current `crossai-build-verify` output directory.
4. Keep `--max-iterations` threaded through the library path; do not hardcode `5` inside extracted code.
5. If needed, prefer a build-specific extracted runner such as `run_build_legacy_iteration(...)` over forcing a prematurely generic `run_loop(...)` contract.

At the end of this step, the wrapper should be materially smaller, but it must still behave exactly like the current script from the caller's point of view.

- [ ] **Step 4: Run regression suite**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/ -v -x 2>&1 | tail -20
```

Expected: count from Step 1 unchanged. If any test fails, or if the new build-parity test detects drift, the refactor is not acceptable for M1.

- [ ] **Step 5: Sync mirror + commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp scripts/vg-build-crossai-loop.py .claude/scripts/vg-build-crossai-loop.py
git add scripts/vg-build-crossai-loop.py \
        .claude/scripts/vg-build-crossai-loop.py
git commit -m "refactor(build-crossai): extract wrapper internals with parity

M1 Task 07 — extract current build orchestration behind crossai_loop.py
without changing observable behavior. Wrapper still owns build-specific
brief semantics and any glue needed to preserve current events, output
paths, and findings schema.

CLI signature preserved: --phase --iteration --max-iterations.
Exit codes preserved: 0/1/2 (CLEAN/BLOCKS/INFRA).
Existing test suite and build-parity suite pass unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
