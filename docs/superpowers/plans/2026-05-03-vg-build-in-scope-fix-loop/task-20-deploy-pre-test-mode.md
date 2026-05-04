<!-- Per-task plan file (NEW from Codex Round 2: --pre-test mode for /vg:deploy). -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->


## Task 20 (NEW): Add `--pre-test` mode to `/vg:deploy`

**Files:**
- Modify: `commands/vg/deploy.md` (slim entry — accept `--pre-test` flag)
- Modify: `commands/vg/_shared/deploy/overview.md` (relax build-complete check when `--pre-test` set)
- Test: extend `tests/test_deploy_pre_test_mode.py` (NEW)

**Why:** STEP 6.5 (Task 18) invokes `/vg:deploy` BEFORE STEP 7 close.
The current `/vg:deploy` skill requires build-complete unless
`--allow-build-incomplete`. Codex round 2 #2 recommends a first-class
`--pre-test` mode that:
- Allows invocation pre-close (build STEP 6.5)
- Marks DEPLOY-STATE.json `deployed.<env>.mode = "pre-test"` so
  downstream `/vg:test`, `/vg:review` can distinguish a pre-test deploy
  from a post-close deploy
- Does NOT log override-debt (it's a sanctioned pre-close path)
- Still requires `--non-interactive` (build is non-interactive)

- [ ] **Step 1: Write the failing test**

Create `tests/test_deploy_pre_test_mode.py`:

```python
"""Test --pre-test flag for /vg:deploy — Task 20."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_deploy_md_accepts_pre_test_flag() -> None:
    """commands/vg/deploy.md argument-hint must include --pre-test."""
    text = (REPO / "commands" / "vg" / "deploy.md").read_text(encoding="utf-8")
    assert "--pre-test" in text, "deploy.md must declare --pre-test in argument-hint"


def test_deploy_overview_handles_pre_test_pre_close() -> None:
    """deploy/overview.md must exempt build-complete check when --pre-test set."""
    text = (REPO / "commands" / "vg" / "_shared" / "deploy" / "overview.md").read_text(encoding="utf-8")
    # The pre-close exemption block exists and gates on --pre-test
    assert "--pre-test" in text
    assert "build_complete" in text or "build-complete" in text
    # Logic: when --pre-test set, skip build-complete check; otherwise enforce
    assert "pre_test" in text.lower() or "pre-test" in text.lower()


def test_deploy_state_records_pre_test_mode(tmp_path: Path) -> None:
    """DEPLOY-STATE.json must record mode='pre-test' when invoked with --pre-test."""
    # Synthetic pre-existing DEPLOY-STATE.json showing what the writer should produce
    sample = {
        "deployed": {
            "sandbox": {
                "url": "https://sandbox.example.com",
                "deployed_at": "2026-05-03T10:00:00Z",
                "mode": "pre-test",   # NEW field
                "phase": "test-1.0",
            }
        }
    }
    target = tmp_path / "DEPLOY-STATE.json"
    target.write_text(json.dumps(sample), encoding="utf-8")
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed["deployed"]["sandbox"]["mode"] == "pre-test"
```

- [ ] **Step 2: Run failing tests**

Run: `cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix" && python3 -m pytest tests/test_deploy_pre_test_mode.py -v`
Expected: 3 failures (deploy.md doesn't declare --pre-test yet).

- [ ] **Step 3: Add `--pre-test` to deploy.md argument-hint**

Edit `commands/vg/deploy.md`. Find `argument-hint:` and append `[--pre-test]`:

```yaml
argument-hint: "<phase> --envs=<env-list> [--non-interactive] [--allow-build-incomplete] [--pre-test] [--override-reason=<text>]"
```

Add to slim entry body, after the existing arg parsing:

```markdown
**`--pre-test` mode** — invoked from `/vg:build` STEP 6.5 (pre-test gate)
before STEP 7 close. Behavior:
- Skips the build-complete check (no `--override-reason` required because
  `--pre-test` is a sanctioned pre-close path, not a manual override)
- Sets `deployed.<env>.mode = "pre-test"` in `${PHASE_DIR}/DEPLOY-STATE.json`
- Requires `--non-interactive` implicitly (build is non-interactive)
- Telemetry: emits `deploy.pre_test_invoked` event
```

- [ ] **Step 4: Update deploy/overview.md to honor --pre-test**

Edit `commands/vg/_shared/deploy/overview.md`. Find the build-complete
gate block (look for `build-complete` or `12_run_complete` checks). Add
above the gate:

```bash
# Codex round 2 fix: --pre-test sanctioned pre-close invocation
PRE_TEST_MODE=false
if [[ "$ARGUMENTS" =~ --pre-test ]]; then
  PRE_TEST_MODE=true
  echo "▸ /vg:deploy --pre-test: bypass build-complete check (pre-close invocation from build STEP 6.5)"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "deploy.pre_test_invoked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
fi

# Existing build-complete gate, now skipped when PRE_TEST_MODE=true:
if [ "$PRE_TEST_MODE" = "false" ] && [ ! -f "${PHASE_DIR}/.step-markers/12_run_complete.done" ]; then
  if [[ ! "$ARGUMENTS" =~ --allow-build-incomplete ]]; then
    echo "⛔ /vg:deploy: build not complete. Run /vg:build first or pass --allow-build-incomplete + --override-reason"
    exit 1
  fi
fi
```

When writing DEPLOY-STATE.json's `deployed.<env>` entry, add the `mode` field:

```python
deployed_entry = {
    "url": deployed_url,
    "deployed_at": iso_timestamp,
    "phase": phase_number,
    "mode": "pre-test" if pre_test_mode else "post-close",
}
```

- [ ] **Step 5: Run tests + commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_deploy_pre_test_mode.py -v
git add commands/vg/deploy.md commands/vg/_shared/deploy/overview.md tests/test_deploy_pre_test_mode.py
git commit -m "feat(deploy): add --pre-test mode for build STEP 6.5 pre-close invocation"
```
Expected: 3 passed.

---
