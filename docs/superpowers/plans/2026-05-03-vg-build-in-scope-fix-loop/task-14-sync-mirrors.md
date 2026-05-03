<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 14: Sync mirrors + final verification

- [ ] **Step 1: Run sync**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
DEV_ROOT=. bash sync.sh --no-global
python3 scripts/vg_sync_codex.py --apply 2>&1 | tail -3
```
Expected: sync applies cleanly; codex sync reports `53 applied`.

- [ ] **Step 2: Verify mirror parity**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
diff -q .claude/commands/vg/build.md commands/vg/build.md
diff -q .claude/commands/vg/scope.md commands/vg/scope.md
diff -q .claude/scripts/lib/severity_taxonomy.py scripts/lib/severity_taxonomy.py
diff -q .claude/scripts/classify-build-warning.py scripts/classify-build-warning.py
ls .claude/scripts/extractors/extract-*.py | wc -l
ls .claude/scripts/validators/verify-{fe-be-call-graph,contract-shape,spec-drift}.py 2>&1 | wc -l
```
Expected: all `diff` no output; extractor count 2; validator count 3.

- [ ] **Step 3: Run full test suite**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_severity_taxonomy.py \
                  tests/test_fe_be_call_graph.py \
                  tests/test_contract_shape_validator.py \
                  tests/test_spec_drift_validator.py \
                  tests/test_classify_build_warning.py \
                  tests/test_phase_ownership.py \
                  tests/test_rule_resolver.py \
                  tests/test_build_fix_loop_integration.py -v
```
Expected: all green (estimated 4 + 6 + 2 + 2 + 3 + 3 + 2 + 3 = 25 passed).

- [ ] **Step 4: Smoke-check no regression in existing suite**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/ -x --ignore=tests/hooks 2>&1 | tail -10
```
Expected: 0 new failures.

- [ ] **Step 5: Final commit**

```bash
git add .claude/ codex-skills/
git commit -m "chore(sync): mirror build-fix-loop to .claude/ + codex-skills/"
git log --oneline -20
```
Expected: 14 commits visible (one per task) plus prior history.

