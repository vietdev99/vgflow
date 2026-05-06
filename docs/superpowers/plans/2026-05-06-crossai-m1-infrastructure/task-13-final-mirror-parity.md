# Task 13: Final mirror parity sweep + regression run

**Goal:** Verify every modified/new source file has a byte-identical mirror under `.claude/`. Run full test suite to catch any regressions introduced across Tasks 01–12. This is the M1 acceptance gate — failing here blocks merge to PR.

**Files:**
- Verify (no change): `.claude/scripts/lib/crossai_config.py` ← `scripts/lib/crossai_config.py`
- Verify: `.claude/scripts/lib/crossai_skip_validation.py` ← `scripts/lib/crossai_skip_validation.py`
- Verify: `.claude/scripts/lib/crossai_loop.py` ← `scripts/lib/crossai_loop.py`
- Verify: `.claude/scripts/vg-build-crossai-loop.py` ← `scripts/vg-build-crossai-loop.py`
- Verify: `.claude/scripts/vg-scope-crossai-loop.py` ← `scripts/vg-scope-crossai-loop.py`
- Verify: `.claude/scripts/vg-blueprint-crossai-loop.py` ← `scripts/vg-blueprint-crossai-loop.py`
- Verify: `.claude/scripts/vg-orchestrator/__main__.py` ← `scripts/vg-orchestrator/__main__.py`
- Test: `scripts/tests/test_crossai_m1_mirror_parity.py` (new — formal mirror-parity gate)

---

- [ ] **Step 1: Create the failing test file**

Create `scripts/tests/test_crossai_m1_mirror_parity.py`:

```python
"""M1 acceptance gate — every CrossAI source file has byte-identical
.claude/ mirror. Failing here means a Task forgot to sync after edit."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

M1_MIRROR_PAIRS = [
    ("scripts/lib/crossai_config.py",
     ".claude/scripts/lib/crossai_config.py"),
    ("scripts/lib/crossai_skip_validation.py",
     ".claude/scripts/lib/crossai_skip_validation.py"),
    ("scripts/lib/crossai_loop.py",
     ".claude/scripts/lib/crossai_loop.py"),
    ("scripts/vg-build-crossai-loop.py",
     ".claude/scripts/vg-build-crossai-loop.py"),
    ("scripts/vg-scope-crossai-loop.py",
     ".claude/scripts/vg-scope-crossai-loop.py"),
    ("scripts/vg-blueprint-crossai-loop.py",
     ".claude/scripts/vg-blueprint-crossai-loop.py"),
    ("scripts/vg-orchestrator/__main__.py",
     ".claude/scripts/vg-orchestrator/__main__.py"),
]


def test_all_m1_files_exist():
    for src_rel, mirror_rel in M1_MIRROR_PAIRS:
        src = REPO_ROOT / src_rel
        mirror = REPO_ROOT / mirror_rel
        assert src.is_file(), f"source missing: {src_rel}"
        assert mirror.is_file(), f"mirror missing: {mirror_rel}"


def test_all_m1_files_byte_identical():
    drifted = []
    for src_rel, mirror_rel in M1_MIRROR_PAIRS:
        src = (REPO_ROOT / src_rel).read_bytes()
        mirror = (REPO_ROOT / mirror_rel).read_bytes()
        if src != mirror:
            drifted.append(f"{src_rel} ↔ {mirror_rel}")
    assert not drifted, "Mirror drift detected:\n  " + "\n  ".join(drifted)
```

- [ ] **Step 2: Run mirror-parity test (should pass if Tasks 01–12 synced correctly)**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_m1_mirror_parity.py -v
```

If FAIL: a previous task forgot `cp scripts/... .claude/scripts/...`. Fix by running:

```bash
for src in scripts/lib/crossai_config.py \
           scripts/lib/crossai_skip_validation.py \
           scripts/lib/crossai_loop.py \
           scripts/vg-build-crossai-loop.py \
           scripts/vg-scope-crossai-loop.py \
           scripts/vg-blueprint-crossai-loop.py \
           scripts/vg-orchestrator/__main__.py; do
  cp "$src" ".claude/$src"
done
```

Then re-run the parity test.

- [ ] **Step 3: Run full M1 test suite**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest \
  scripts/tests/test_crossai_skip_validation_compat.py \
  scripts/tests/test_crossai_config_resolve.py \
  scripts/tests/test_crossai_loop_library.py \
  scripts/tests/test_crossai_project_init_crossai.py \
  scripts/tests/test_crossai_migrate_plan.py \
  scripts/tests/test_crossai_m1_mirror_parity.py \
  -v 2>&1 | tail -10
```

Expected: full M1-targeted test set passes. Exact count may move as parity
coverage grows; use green status, not the historical rough estimate, as
the merge gate.

- [ ] **Step 4: Run full project regression suite**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/ 2>&1 | tail -5
```

Expected: same passed count as before M1 + the new tests added in Tasks 01–13. Failures here = M1 broke an existing test, must fix before commit.

- [ ] **Step 5: Sanity check canonical project-init CrossAI generation**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
mkdir -p /tmp/vg-m1-smoke && cd /tmp/vg-m1-smoke
python3 "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix/.claude/scripts/vg_generate_config.py" 2>&1 | head -30
```

Expected: output includes valid CrossAI config sections from the canonical generator path. No errors on stderr.

- [ ] **Step 6: Sanity check `migrate-crossai --dry-run` on legacy fixture**

```bash
mkdir -p /tmp/vg-m1-smoke-legacy/.claude && cd /tmp/vg-m1-smoke-legacy
cat > .claude/vg.config.md <<'EOF'
crossai_clis:
  - name: "Codex"
    command: 'cmd'
    label: "Codex"
EOF
python3 "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix/.claude/scripts/vg-orchestrator" migrate-crossai --dry-run 2>&1
```

Expected: prints `crossai_stages:` + `crossai:` blocks (additive, no removal).

- [ ] **Step 7: Commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
git add scripts/tests/test_crossai_m1_mirror_parity.py
git commit -m "test(crossai-m1): final mirror parity sweep

M1 Task 13 — formal mirror-parity gate. Verifies every CrossAI source
file has byte-identical .claude/ mirror across all 7 M1-touched paths
(config, loop library, 3 wrappers, orchestrator). Failing test here
blocks merge — mirror drift = a Task forgot to sync after edit.

Tests: 2 (all files exist, byte-identical).

M1 acceptance criteria all met:
- 7 source files + 7 mirrors byte-identical
- ~44 new tests passing (5 compat + 16 config + 8 loop + 8 init +
  5 migrate + 2 parity)
- Existing build CrossAI tests pass unchanged (Task 07 refactor was
  behavior-preserving)
- `/vg:project --init-only` generator path produces valid CrossAI config sections
- migrate-crossai --dry-run additive on legacy fixture

Ready to merge M1 → branch → PR. M2 (gating policy) starts next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: Push branch + verify PR cleanliness**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
git push origin feat/rfc-v9-followup-fixes 2>&1 | tail -3
gh pr view 108 --repo vietdev99/vgflow --json mergeable,mergeStateStatus
```

Expected: mergeable=MERGEABLE, mergeStateStatus=CLEAN.

---

## M1 deliverables checklist

After Task 13 completes, the branch should have:

- [ ] 7 source files + 7 mirrors (byte-identical)
- [ ] 1 fixture template extended
- [ ] 6 test files (~44 tests passing)
- [ ] 13 atomic commits (1 per task)
- [ ] No regressions in existing test suite
- [ ] canonical project-init CrossAI generation + optional `migrate-crossai` helper functional
- [ ] PR mergeable + clean

**Next milestone:** M2 (gating policy) — see follow-up plan in
`docs/superpowers/plans/2026-05-?-crossai-m2-gating.md`.
