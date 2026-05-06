# Task 01: Rename `crossai_skip_validation.py` → `crossai_config.py` + import shim

**Goal:** Rename the file with `git mv` to preserve history, then add a thin re-export shim at the old path so existing imports keep working throughout M1. Do not schedule shim removal in M1/M2 until every current validator/orchestrator import and CLI-availability assumption has been migrated safely.

**Files:**
- Rename: `scripts/lib/crossai_skip_validation.py` → `scripts/lib/crossai_config.py`
- Create: `scripts/lib/crossai_skip_validation.py` (new — thin shim)
- Mirror: `.claude/scripts/lib/crossai_config.py` (new copy)
- Mirror: `.claude/scripts/lib/crossai_skip_validation.py` (new copy of shim)
- Test: `scripts/tests/test_crossai_skip_validation_compat.py` (new)

---

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/test_crossai_skip_validation_compat.py`:

```python
"""Backwards-compat: existing imports of crossai_skip_validation module
still work after rename to crossai_config.

Mechanism: scripts/lib/crossai_skip_validation.py becomes a thin shim that
re-exports the public API from crossai_config. External code that did
`from crossai_skip_validation import validate_skip_legitimate` keeps working.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))


def test_validate_skip_legitimate_importable_from_old_name():
    """Old import path still resolves the canonical function."""
    from crossai_skip_validation import validate_skip_legitimate
    assert callable(validate_skip_legitimate)


def test_format_rejection_importable_from_old_name():
    from crossai_skip_validation import format_rejection
    assert callable(format_rejection)


def test_skip_validation_result_importable_from_old_name():
    from crossai_skip_validation import SkipValidationResult
    sv = SkipValidationResult(legitimate=True)
    assert sv.legitimate is True


def test_canonical_module_exists():
    """The new module name `crossai_config` should be importable."""
    from crossai_config import validate_skip_legitimate
    assert callable(validate_skip_legitimate)


def test_old_and_new_resolve_same_function():
    """Both module names should expose the same function object."""
    from crossai_skip_validation import validate_skip_legitimate as old_fn
    from crossai_config import validate_skip_legitimate as new_fn
    assert old_fn is new_fn
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_skip_validation_compat.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'crossai_config'` (or similar — module doesn't exist yet).

- [ ] **Step 3: Rename file with `git mv` to preserve history**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
git mv scripts/lib/crossai_skip_validation.py scripts/lib/crossai_config.py
```

- [ ] **Step 4: Update file docstring + module-level comment in the renamed file**

Edit `scripts/lib/crossai_config.py` — replace the top docstring (lines 1–22) with:

```python
"""CrossAI configuration helper — anti-rationalization validator + stage config.

This module is the canonical configuration layer for the VG harness CrossAI
loop. M1 (2026-05-06) renamed it from `crossai_skip_validation.py` to make
room for stage-config resolution (Tasks 2–4). The original API
(`validate_skip_legitimate`, `format_rejection`, `SkipValidationResult`) is
preserved unchanged; existing imports of `crossai_skip_validation` keep
working via a re-export shim at the old path.

PV3 build 4.2 dogfood (2026-05-05) revealed AI emitting:
  vg-orchestrator override --flag=skip-build-crossai \\
    --reason="...no Codex CLI configured per .claude/vg.config.md..."

while:
  - vg.config.md `crossai_clis:` lists Codex
  - `which codex` returns /usr/.../bin/codex

This module fact-checks the override reason against:
  1. `.claude/vg.config.md` `crossai_clis:` list
  2. `shutil.which(<name>)` for each configured CLI

Skip is **legitimate** ONLY when no CrossAI CLI is both:
  - Configured in vg.config.md crossai_clis
  - Installed on PATH

Otherwise the loop physically CAN run, and the override is a
rationalization attempting to bypass the build-crossai-required gate.

Public API:
    validate_skip_legitimate(repo_root, override_reason) -> SkipValidationResult
    format_rejection(result) -> str
    resolve_stage_config(stage, repo_root) -> StageConfig  # added in Task 3

Used by:
    - scripts/vg-orchestrator/__main__.py::cmd_override (pre-validation)
    - scripts/validators/build-crossai-required.py (terminal-event check)
    - scripts/lib/crossai_loop.py (stage config lookup, added in Task 5)
"""
```

- [ ] **Step 5: Create thin re-export shim at old path**

Create `scripts/lib/crossai_skip_validation.py`:

```python
"""DEPRECATED: re-export shim — import from `crossai_config` instead.

Renamed in M1 (2026-05-06) to make room for stage-config helpers
(`resolve_stage_config`, `StageConfig`, `CLISpec`). External callers that
import from this old path keep working but should migrate to
`crossai_config`. Removal target is intentionally deferred beyond M1 until
all validator/orchestrator callers and installed-CLI probing paths have
been migrated together.
"""
from crossai_config import (  # noqa: F401  (re-export)
    SkipValidationResult,
    validate_skip_legitimate,
    format_rejection,
)
```

- [ ] **Step 6: Sync `.claude/` mirrors**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
mkdir -p .claude/scripts/lib
cp scripts/lib/crossai_config.py .claude/scripts/lib/crossai_config.py
cp scripts/lib/crossai_skip_validation.py .claude/scripts/lib/crossai_skip_validation.py
```

If the old mirror still exists, refresh it; the byte-identical mirror is enforced by mirror-parity tests in later tasks.

- [ ] **Step 7: Run test to verify it passes**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_skip_validation_compat.py -v
```

Expected: 5 passed.

- [ ] **Step 8: Run existing crossai_skip_validation regression tests**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_skip_validation.py -v
```

Expected: All existing tests still pass (rename preserved API).

- [ ] **Step 9: Commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
git add scripts/lib/crossai_config.py \
        scripts/lib/crossai_skip_validation.py \
        .claude/scripts/lib/crossai_config.py \
        .claude/scripts/lib/crossai_skip_validation.py \
        scripts/tests/test_crossai_skip_validation_compat.py
git commit -m "refactor(crossai-config): rename crossai_skip_validation.py → crossai_config.py + shim

M1 Task 01 — make room for stage-config helpers (StageConfig, CLISpec,
resolve_stage_config) coming in Tasks 2-4. Public API unchanged. Old
path scripts/lib/crossai_skip_validation.py becomes a thin re-export
shim so existing imports keep working until M2.

Mirror sync: .claude/scripts/lib/{crossai_config,crossai_skip_validation}.py
byte-identical to source.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
