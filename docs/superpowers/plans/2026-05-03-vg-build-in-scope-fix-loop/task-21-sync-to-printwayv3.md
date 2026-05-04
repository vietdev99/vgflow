<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->

## Task 21: Sync VGFlow harness changes to PrintwayV3 (dogfood target)

**Files:** (no new files — invokes existing sync infra against external target)

**Why:** PrintwayV3 (`/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/`) is the
dogfood project for VGFlow. After completing Tasks 1-20, the harness changes
must be synced to PV3 so the next `/vg:build` run on PV3 picks up:
- New L4a deterministic gates (FE→BE / contract / spec drift)
- L3 in-scope auto-fix loop
- Pre-test gate (STEP 6.5)
- `/vg:deploy --pre-test` mode

`sync.sh` is one-way: vgflow-bugfix repo → target `.claude/` + `.codex/`. PV3
already has VG installed — sync will overwrite `.claude/` + `.codex/` mirrors
with the new versions while preserving PV3's project-specific `.vg/` data.

- [ ] **Step 1: Verify PV3 path + state**

Run:
```bash
PV3="/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
[ -d "$PV3" ] || { echo "⛔ PV3 path not found: $PV3"; exit 1; }
[ -d "$PV3/.claude" ] || { echo "⛔ PV3 missing .claude/ — VG not installed?"; exit 1; }
[ -d "$PV3/.vg" ] || { echo "⚠ PV3 missing .vg/ — fresh project; sync will still work"; }
echo "✓ PV3 ready at $PV3"
```
Expected: PV3 exists with `.claude/` directory (legacy install).

- [ ] **Step 2: Capture PV3 baseline before sync (rollback safety)**

```bash
PV3="/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
cd "$PV3"
git status --short > /tmp/pv3-pre-sync-status.txt
git rev-parse HEAD > /tmp/pv3-pre-sync-sha.txt
echo "▸ PV3 baseline captured (status + HEAD SHA in /tmp/pv3-pre-sync-*)"
```
Expected: clean status preferred; if dirty, sếp may want to commit/stash before sync.

- [ ] **Step 3: Run sync.sh against PV3**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
DEV_ROOT="/Users/dzungnguyen/Vibe Code/Code/PrintwayV3" bash sync.sh --no-global 2>&1 | tail -20
```
Expected: "Changed: N" line with N > 0; no "Missing sources" errors. The
deploy/build/test slim entries + new validators (verify-fe-be-call-graph,
verify-contract-shape, verify-spec-drift, verify-pre-test-tier-1-2,
write-pre-test-report) + lib modules (severity_taxonomy, phase_ownership,
regression_smoke, rule_resolver, pre_test_runner, deploy_decision,
post_deploy_smoke) get mirrored to `$PV3/.claude/`.

- [ ] **Step 4: Run codex sync from PV3 root**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
python3 .claude/scripts/vg_sync_codex.py --apply 2>&1 | tail -3
```
Expected: codex-skills mirror updated with new build/deploy slim entries.

- [ ] **Step 5: Smoke-check PV3 still functional**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"

# Verify validators are executable + run a no-op call
for v in verify-fe-be-call-graph.py verify-contract-shape.py verify-spec-drift.py verify-pre-test-tier-1-2.py; do
  [ -x ".claude/scripts/validators/$v" ] || chmod +x ".claude/scripts/validators/$v" 2>/dev/null
  python3 ".claude/scripts/validators/$v" --help >/dev/null 2>&1 \
    && echo "✓ $v --help works" \
    || echo "⚠ $v --help failed (may be OK if it has required args)"
done

# Verify the orchestrator still runs
python3 .claude/scripts/vg-orchestrator --help >/dev/null 2>&1 \
  && echo "✓ vg-orchestrator help works" \
  || echo "⛔ vg-orchestrator broken after sync — investigate"

# Run any PV3-side test fixtures we know about (skip if absent)
if [ -d "tests" ]; then
  python3 -m pytest tests/ -x --ignore=tests/hooks 2>&1 | tail -10
fi
```
Expected: no broken executables; orchestrator help works; existing PV3 tests
still pass (or known pre-existing failures not introduced by this sync).

- [ ] **Step 6: Confirm PV3 .vg/ data unchanged**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
# .vg/ should NOT have been touched by sync (project-specific data)
ls -la .vg/ 2>/dev/null | head -10
git status .vg/ 2>&1 | tail -5
```
Expected: `.vg/` directory untouched (no diff against last commit).

- [ ] **Step 7: Commit PV3 sync state**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
git add .claude/ codex-skills/ .codex/ 2>/dev/null
git status --short
git commit -m "chore(sync): import VGFlow build-fix-loop + pre-test-gate harness ($(date -u +%Y-%m-%d))

Imports:
- L4a deterministic gates (FE→BE / contract shape / spec drift)
- L3 auto-fix loop STEP 5.5 + classifier + ownership + smoke
- L1 rule resolver (scope-matched)
- Pre-test gate STEP 6.5 (T1+T2 runner, deploy decision, post-deploy smoke)
- /vg:deploy --pre-test mode
- Forward-deps disposition gate in /vg:scope

Source: vgflow-bugfix sha $(cd /Users/dzungnguyen/Vibe\ Code/Code/vgflow-bugfix && git rev-parse --short HEAD)
"
```
Expected: commit succeeds. If hooks block, investigate (likely a pre-commit
that's not VG-related — fix root cause, do NOT bypass with `--no-verify`).

- [ ] **Step 8: Smoke a real VG command on PV3 (verify dogfood path)**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
# Just verify the slim entries are loadable — don't run a full pipeline.
ls .claude/commands/vg/build.md .claude/commands/vg/deploy.md
grep -l "12_5_pre_test_gate" .claude/commands/vg/build.md \
  && echo "✓ STEP 6.5 wiring present in PV3 build.md" \
  || echo "⛔ STEP 6.5 wiring missing — sync incomplete"
grep -l "\-\-pre-test" .claude/commands/vg/deploy.md \
  && echo "✓ --pre-test flag present in PV3 deploy.md" \
  || echo "⛔ --pre-test missing"
```
Expected: both grep matches succeed.

- [ ] **Step 9: Final report**

Print summary:
```bash
echo "========================================"
echo "PV3 sync complete."
echo "  Source SHA:  $(cd /Users/dzungnguyen/Vibe\ Code/Code/vgflow-bugfix && git rev-parse --short HEAD)"
echo "  Target SHA:  $(cd /Users/dzungnguyen/Vibe\ Code/Code/PrintwayV3 && git rev-parse --short HEAD)"
echo "  PV3 path:    /Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
echo ""
echo "Next: in PV3, run /vg:build <phase> to dogfood the new STEP 5/5.5/6.5 gates."
echo "========================================"
```

## Rollback (if sync corrupts PV3)

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
PRE_SYNC_SHA=$(cat /tmp/pv3-pre-sync-sha.txt)
git checkout "$PRE_SYNC_SHA" -- .claude/ codex-skills/ .codex/
git status --short
echo "▸ Rolled back PV3 .claude/ + .codex/ to $PRE_SYNC_SHA"
```

Use only if PV3 fundamentally breaks. Most issues are fixable in-place.
