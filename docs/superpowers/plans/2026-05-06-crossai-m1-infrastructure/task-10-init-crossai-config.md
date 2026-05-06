# Task 10: Integrate CrossAI config generation into `/vg:project --init-only`

**Goal:** Extend the existing `/vg:project --init-only` config generation pipeline so CrossAI sections are emitted through the canonical project-init flow. Auto-detect available CLI binaries (`shutil.which()`), derive profile-aware defaults from the same project-init inputs already used by `vg_generate_config.py`, and emit `crossai_clis` + `crossai_stages` + `crossai.policy` + `crossai.heuristic_thresholds` without inventing a separate authoritative workflow.

**Files:**
- Modify: `scripts/vg_generate_config.py`
- Modify: `scripts/vg-orchestrator/__main__.py` (only if helper plumbing is needed)
- Mirror: `.claude/scripts/vg_generate_config.py`
- Mirror: `.claude/scripts/vg-orchestrator/__main__.py` (if touched)
- Test: `scripts/tests/test_crossai_project_init_crossai.py` (new)

---

- [ ] **Step 1: Create the failing test file**

Create `scripts/tests/test_crossai_project_init_crossai.py`:

```python
"""Tests for CrossAI config generation through `/vg:project --init-only`.
Auto-detects CLIs, respects canonical config generation path, emits valid
vg.config.md content."""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GEN = REPO_ROOT / ".claude" / "scripts" / "vg_generate_config.py"


def _run_gen(args, env=None, cwd=None):
    full_env = {"PATH": "/usr/bin:/bin", **(env or {})}
    return subprocess.run(
        [sys.executable, str(GEN), *args],
        capture_output=True, text=True, cwd=cwd, env=full_env,
    )


def test_project_init_crossai_emit_block(tmp_path):
    """Config generator emits CrossAI sections through the canonical path."""
    proc = _run_gen([], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "crossai_clis:" in out
    assert "crossai_stages:" in out
    assert "crossai:" in out
    assert "policy:" in out
    assert "heuristic_thresholds:" in out
def test_project_init_crossai_includes_detected_clis(tmp_path):
    """Detected CLIs appear in the generated CrossAI registry."""
    proc = _run_gen([], cwd=tmp_path)
    out = proc.stdout
    # python3 is always available (we run with it). At least one CLI block:
    assert 'name: "python3"' in out or 'command:' in out


def test_project_init_crossai_default_stages_block(tmp_path):
    """Stages block contains scope/blueprint/build keys."""
    proc = _run_gen([], cwd=tmp_path)
    out = proc.stdout
    assert "scope:" in out
    assert "blueprint:" in out
    assert "build:" in out
    assert "primary_clis:" in out
    assert "verifier_cli:" in out


def test_project_init_crossai_resolved_config_loads(tmp_path):
    """Generated config resolves end-to-end with resolve_stage_config()."""
    proc = _run_gen([], cwd=tmp_path)
    assert proc.returncode == 0
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "vg.config.md").write_text(proc.stdout)
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
    from crossai_config import resolve_stage_config
    cfg = resolve_stage_config("blueprint", tmp_path)
    assert cfg.stage == "blueprint"
    assert len(cfg.primary_clis) >= 1
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_project_init_crossai.py -v
```

Expected: failures because the CrossAI sections are not yet generated through the canonical project-init pipeline.

- [ ] **Step 3: Extend canonical config generation path**

Do not add a new authoritative `init-crossai` workflow. Instead:

1. Extend `scripts/vg_generate_config.py` so its normal output includes the new CrossAI sections.
2. Reuse existing project-init inputs/profile signals rather than hardcoding `policy: auto` for every repo.
3. If a helper function in `scripts/vg-orchestrator/__main__.py` is useful for CLI detection, keep it internal and call it from the generator path.
4. An optional `init-crossai` helper may exist for debugging, but it must not become the primary documented entrypoint for M1.

Implementation requirements:

```python
# Pseudocode only — exact function names should follow vg_generate_config.py:
# - detect_crossai_clis()
# - render_crossai_config_block(profile, detected_clis)
# - include output in canonical generator result
```

- [ ] **Step 4: Sync mirror + run tests**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp scripts/vg_generate_config.py .claude/scripts/vg_generate_config.py
python3 -m pytest scripts/tests/test_crossai_project_init_crossai.py -v
```

Expected: tests pass and prove the CrossAI sections come from the canonical generator path.

- [ ] **Step 5: Commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
git add scripts/vg_generate_config.py \
        .claude/scripts/vg_generate_config.py \
        scripts/tests/test_crossai_project_init_crossai.py
git commit -m "feat(project-init): generate crossai config through canonical path

M1 Task 10 — emit CrossAI config sections through `/vg:project --init-only`
and `vg_generate_config.py`, not through a separate authoritative command.
Auto-detect codex/gemini/claude on PATH, derive profile-aware defaults,
and include registry + stages + policy + thresholds in the canonical
generated config.

Tests: generator-path coverage (emit block, detected CLIs, stages block,
resolved config loads).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
