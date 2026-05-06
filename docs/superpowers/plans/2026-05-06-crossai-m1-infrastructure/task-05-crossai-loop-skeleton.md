# Task 05: Skeleton `scripts/lib/crossai_loop.py` + build-legacy extraction seam

**Goal:** Create the new `crossai_loop.py` library file as an extraction seam for the CURRENT build loop. M1 ships only the public surface + parity contract; Task 06 fills in the existing build behavior behind this seam.

**Files:**
- Create: `scripts/lib/crossai_loop.py`
- Mirror: `.claude/scripts/lib/crossai_loop.py`
- Test: `scripts/tests/test_crossai_loop_library.py` (new)

---

- [ ] **Step 1: Create the failing test file**

Create `scripts/tests/test_crossai_loop_library.py`:

```python
"""crossai_loop library — extraction seam for CrossAI orchestration.
M1 Tasks 05-06 preserve the CURRENT build runtime behavior behind a
library boundary; M3 later generalizes this into multi-stage consensus.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))


def test_run_loop_importable():
    """Public entry exists at expected path."""
    from crossai_loop import run_loop
    assert callable(run_loop)


def test_run_loop_signature():
    """Signature: run_loop(phase, iteration, brief_packer, stage_config,
    out_dir=None) → int."""
    import inspect
    from crossai_loop import run_loop
    sig = inspect.signature(run_loop)
    params = list(sig.parameters.keys())
    assert params[:4] == ["phase", "iteration", "brief_packer",
                           "stage_config"]
    # out_dir is optional
    assert "out_dir" in sig.parameters
    assert sig.parameters["out_dir"].default is None


def test_exit_code_constants_exported():
    """Library exports CLEAN/BLOCKS/INFRA_FAIL constants matching existing
    vg-build-crossai-loop.py exit-code semantics (0/1/2)."""
    import crossai_loop
    assert crossai_loop.EXIT_CLEAN == 0
    assert crossai_loop.EXIT_BLOCKS_FOUND == 1
    assert crossai_loop.EXIT_INFRA_FAIL == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_loop_library.py -v
```

Expected: 3 failures (`ModuleNotFoundError: No module named 'crossai_loop'`).

- [ ] **Step 3: Create skeleton library file**

Create `scripts/lib/crossai_loop.py`:

```python
"""CrossAI orchestration library — extraction seam for current build loop.

Public API:
    run_loop(phase, iteration, brief_packer, stage_config, out_dir=None) -> int

Exit codes (preserve existing vg-build-crossai-loop.py semantics):
    EXIT_CLEAN          = 0  -- iteration produced 0 BLOCK findings
    EXIT_BLOCKS_FOUND   = 1  -- BLOCK findings present, fix loop should iterate
    EXIT_INFRA_FAIL     = 2  -- CLI subprocess failed (network/quota/parse error)

M1 (Task 06) preserves the CURRENT build loop semantics: parallel Codex +
Gemini invocation, build-specific events, findings shape, and output path.
M3 will later add generic multi-stage/multi-primary orchestration on top
of that preserved baseline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from crossai_config import StageConfig

EXIT_CLEAN = 0
EXIT_BLOCKS_FOUND = 1
EXIT_INFRA_FAIL = 2


# Type alias for brief packer callbacks defined by per-stage wrappers.
#   def pack_brief(phase_dir: Path, phase_num: str, iteration: int,
#                  max_iter: int) -> str: ...
BriefPacker = Callable[[Path, str, int, int], str]


def run_loop(
    phase: str,
    iteration: int,
    brief_packer: BriefPacker,
    stage_config: StageConfig,
    out_dir: Path | None = None,
) -> int:
    """Run one CrossAI iteration for the given stage.

    Args:
        phase: phase number string (e.g. "4.2"). Forwarded to brief_packer.
        iteration: 1-indexed iteration count.
        brief_packer: callable returning the review brief text. Per-stage
            wrappers (vg-{scope,blueprint,build}-crossai-loop.py) provide
            their own brief packer.
        stage_config: resolved StageConfig from
            crossai_config.resolve_stage_config().
        out_dir: optional override for findings + raw CLI output directory.
            Build parity path in M1 stays `<phase_dir>/crossai-build-verify/`.

    Returns:
        Exit code: EXIT_CLEAN | EXIT_BLOCKS_FOUND | EXIT_INFRA_FAIL.

    M1 implementation: build-legacy behavior extraction (Task 06).
    M3 will extend to generic multi-primary consensus.
    """
    raise NotImplementedError(
        "run_loop body added in M1 Task 06. This skeleton ships in Task 05 "
        "to establish the public signature."
    )
```

- [ ] **Step 4: Run tests to verify Task 05 portion passes**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_loop_library.py -v
```

Expected: 3 passed (signature + constants exports satisfied; body NotImplementedError doesn't trigger because nothing calls run_loop yet).

- [ ] **Step 5: Sync mirror + commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp scripts/lib/crossai_loop.py .claude/scripts/lib/crossai_loop.py
git add scripts/lib/crossai_loop.py \
        .claude/scripts/lib/crossai_loop.py \
        scripts/tests/test_crossai_loop_library.py
git commit -m "feat(crossai-loop): skeleton library + run_loop signature

M1 Task 05 — public API for shared CrossAI orchestration. M3 will extend
to parallel multi-primary consensus; M1 Task 06 fills in single-primary
passthrough preserving existing vg-build-crossai-loop.py behavior.

Exports: run_loop(phase, iteration, brief_packer, stage_config, out_dir),
EXIT_CLEAN/EXIT_BLOCKS_FOUND/EXIT_INFRA_FAIL constants, BriefPacker type.

Tests: 3 (importable, signature contract, exit-code constants).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
