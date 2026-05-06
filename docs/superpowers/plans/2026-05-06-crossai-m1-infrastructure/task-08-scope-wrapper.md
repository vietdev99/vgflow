# Task 08: Scope wrapper helper (not activated in M1)

**Goal:** Add a scope-stage helper wrapper only as preparation work. In M1 this file is not wired into the mainline `/vg:scope` flow, not covered by runtime-contract validators, and not allowed to trigger lazy migration side effects. Its job is limited to preserving the intended brief-packing shape so M2 can activate it safely later.

**Files:**
- Create: `scripts/vg-scope-crossai-loop.py`
- Mirror: `.claude/scripts/vg-scope-crossai-loop.py`
- Test: `scripts/tests/test_crossai_loop_library.py` (extend with scope wrapper integration test)

---

- [ ] **Step 1: Append failing test to `scripts/tests/test_crossai_loop_library.py`**

```python


# ---- Task 08 tests ----


def test_scope_wrapper_main_importable():
    """vg-scope-crossai-loop.py exports main() callable."""
    import importlib.util
    p = REPO_ROOT / "scripts" / "vg-scope-crossai-loop.py"
    spec = importlib.util.spec_from_file_location("vg_scope_crossai", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.main)
    assert callable(mod.pack_review_brief)


def test_scope_pack_review_brief_includes_specs_and_context(tmp_path):
    """Brief contains SPECS.md + CONTEXT.md content full body."""
    import importlib.util
    p = REPO_ROOT / "scripts" / "vg-scope-crossai-loop.py"
    spec = importlib.util.spec_from_file_location("vg_scope_crossai", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    phase_dir = tmp_path / "phase-test"
    phase_dir.mkdir()
    (phase_dir / "SPECS.md").write_text("# SPECS\n- requirement A")
    (phase_dir / "CONTEXT.md").write_text("# CONTEXT\n- D-01 use postgres")
    brief = mod.pack_review_brief(phase_dir, "4.2", 1, 5)
    assert "SPECS.md" in brief
    assert "requirement A" in brief
    assert "CONTEXT.md" in brief
    assert "D-01 use postgres" in brief
    # Scope CrossAI focuses on requirements↔decisions drift
    assert "drift" in brief.lower() or "contradicts" in brief.lower()


def test_scope_pack_review_brief_handles_missing_artifacts(tmp_path):
    """No SPECS.md → brief still produced with placeholder."""
    import importlib.util
    p = REPO_ROOT / "scripts" / "vg-scope-crossai-loop.py"
    spec = importlib.util.spec_from_file_location("vg_scope_crossai", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    phase_dir = tmp_path / "phase-empty"
    phase_dir.mkdir()
    brief = mod.pack_review_brief(phase_dir, "4.2", 1, 5)
    assert "missing" in brief or "(SPECS.md missing)" in brief
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_loop_library.py -v -k "scope"
```

Expected: 3 failures (file doesn't exist).

- [ ] **Step 3: Create `scripts/vg-scope-crossai-loop.py` as helper-only**

```python
#!/usr/bin/env python3
"""Scope CrossAI loop wrapper — invokes shared library with scope-stage
brief packer.

CLI: vg-scope-crossai-loop.py --phase X --iteration N [--max-iterations M]

Scope CrossAI's job: catch SPECS↔CONTEXT drift (requirements not honored
by decisions; decisions contradicting SPECS constraints) before blueprint
phase commits to a plan.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from crossai_config import resolve_stage_config  # noqa: E402
from crossai_loop import run_loop, EXIT_INFRA_FAIL  # noqa: E402


def pack_review_brief(
    phase_dir: Path,
    phase_num: str,
    iteration: int,
    max_iter: int,
) -> str:
    """Pack SPECS + CONTEXT (+ DISCUSSION-LOG if present) for scope review."""
    def read(rel: str) -> str:
        p = phase_dir / rel
        if not p.is_file():
            return f"({rel} missing)"
        return p.read_text(encoding="utf-8", errors="replace")

    specs = read("SPECS.md")
    context = read("CONTEXT.md")
    discussion = read("DISCUSSION-LOG.md")

    return f"""# Scope CrossAI Verification — Phase {phase_num} iteration {iteration}/{max_iter}

## Your task

Audit SPECS↔CONTEXT alignment. Find:

1. **Drift:** SPECS in-scope item with NO corresponding CONTEXT decision.
2. **Contradiction:** CONTEXT decision contradicting a SPECS constraint.
3. **Out-of-scope sneak:** CONTEXT decision adding scope not declared in SPECS.

Each issue → BLOCK finding with citation (SPECS section + CONTEXT D-XX).

## Output format

<crossai-verdict>
  <verdict>PASS|FAIL</verdict>
  <findings>
    <finding severity="BLOCK"><message>...</message></finding>
  </findings>
</crossai-verdict>

## Artifacts

### SPECS.md
{specs}

### CONTEXT.md
{context}

### DISCUSSION-LOG.md
{discussion}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--iteration", type=int, required=True)
    ap.add_argument("--max-iterations", type=int, default=5)
    args = ap.parse_args()

    repo_root = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    try:
        stage_cfg = resolve_stage_config("scope", repo_root)
    except ValueError as exc:
        print(f"\033[38;5;208m{exc}\033[0m", file=sys.stderr)
        return EXIT_INFRA_FAIL

    return run_loop(
        phase=args.phase,
        iteration=args.iteration,
        brief_packer=pack_review_brief,
        stage_config=stage_cfg,
    )


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
chmod +x scripts/vg-scope-crossai-loop.py
python3 -m pytest scripts/tests/test_crossai_loop_library.py -v -k "scope"
```

Expected: 3 passed.

- [ ] **Step 5: Sync mirror + commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp scripts/vg-scope-crossai-loop.py .claude/scripts/vg-scope-crossai-loop.py
chmod +x .claude/scripts/vg-scope-crossai-loop.py
git add scripts/vg-scope-crossai-loop.py \
        .claude/scripts/vg-scope-crossai-loop.py \
        scripts/tests/test_crossai_loop_library.py
git commit -m "feat(scope-crossai): new vg-scope-crossai-loop.py wrapper

M1 Task 08 — scope-stage CrossAI loop wrapper. Brief packs SPECS +
CONTEXT (+ DISCUSSION-LOG if present) full body, focused on
SPECS↔CONTEXT drift / contradiction / out-of-scope sneak detection.

Delegates orchestration to the shared library, but this file remains
helper-only in M1. Do not wire it into `/vg:scope`, validators, or any
auto-run path yet.

Tests: 3 (importable, brief content, missing-artifact placeholder).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
