# Task 09: Blueprint wrapper helper (not activated in M1)

**Goal:** Add a blueprint-stage helper wrapper only as preparation work. In M1 this file is not wired into the mainline `/vg:blueprint` flow, not covered by runtime-contract validators, and not allowed to trigger lazy migration side effects. Its job is limited to preserving the intended blueprint brief-packing shape so M2 can activate it safely later.

**Files:**
- Create: `scripts/vg-blueprint-crossai-loop.py`
- Mirror: `.claude/scripts/vg-blueprint-crossai-loop.py`
- Test: `scripts/tests/test_crossai_loop_library.py` (extend)

---

- [ ] **Step 1: Append failing tests**

```python


# ---- Task 09 tests ----


def test_blueprint_wrapper_main_importable():
    import importlib.util
    p = REPO_ROOT / "scripts" / "vg-blueprint-crossai-loop.py"
    spec = importlib.util.spec_from_file_location("vg_blueprint_crossai", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.main)
    assert callable(mod.pack_review_brief)


def test_blueprint_brief_includes_full_body_artifacts(tmp_path):
    """Brief contains PLAN + CONTRACTS + GOALS + CONTEXT body, AND new
    artifacts when present (UI-MAP, WORKFLOW-SPECS, CRUD-SURFACES, BLOCK 5)."""
    import importlib.util
    p = REPO_ROOT / "scripts" / "vg-blueprint-crossai-loop.py"
    spec = importlib.util.spec_from_file_location("vg_blueprint_crossai", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    (phase_dir / "PLAN.md").write_text("# PLAN\nTask 1: foo")
    (phase_dir / "API-CONTRACTS.md").write_text("# CONTRACTS\nGET /api/x")
    (phase_dir / "TEST-GOALS.md").write_text("# GOALS\nG-01: critical")
    (phase_dir / "CONTEXT.md").write_text("# CONTEXT\nD-01: postgres")
    (phase_dir / "UI-MAP.md").write_text("# UI MAP\n/dashboard")
    (phase_dir / "WORKFLOW-SPECS").mkdir()
    (phase_dir / "WORKFLOW-SPECS" / "WF-01.md").write_text("# WF-01\nactor A")
    (phase_dir / "CRUD-SURFACES.md").write_text("# CRUD\nuser table")
    (phase_dir / "VIEW-COMPONENTS.md").write_text("# VIEW\n<UserList/>")

    brief = mod.pack_review_brief(phase_dir, "4.2", 1, 5)

    assert "PLAN.md" in brief and "Task 1: foo" in brief
    assert "API-CONTRACTS" in brief and "GET /api/x" in brief
    assert "TEST-GOALS" in brief and "G-01" in brief
    assert "CONTEXT" in brief and "D-01" in brief
    assert "UI-MAP" in brief
    assert "WORKFLOW" in brief and "WF-01" in brief
    assert "CRUD" in brief
    assert "VIEW-COMPONENTS" in brief


def test_blueprint_brief_uses_split_files_when_present(tmp_path):
    """If PLAN/ and API-CONTRACTS/ split dirs exist, brief includes those
    files preferring the split (per phase-artifact convention)."""
    import importlib.util
    p = REPO_ROOT / "scripts" / "vg-blueprint-crossai-loop.py"
    spec = importlib.util.spec_from_file_location("vg_blueprint_crossai", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    (phase_dir / "PLAN").mkdir()
    (phase_dir / "PLAN" / "index.md").write_text("# PLAN index")
    (phase_dir / "PLAN" / "task-01.md").write_text("# Task 01\nfoo bar")
    (phase_dir / "API-CONTRACTS").mkdir()
    (phase_dir / "API-CONTRACTS" / "endpoint-1.md").write_text(
        "# Endpoint 1\nPOST /api/y"
    )
    (phase_dir / "TEST-GOALS").mkdir()
    (phase_dir / "TEST-GOALS" / "G-01.md").write_text("# G-01\ncritical goal")
    (phase_dir / "CONTEXT.md").write_text("# CONTEXT\nD-01")

    brief = mod.pack_review_brief(phase_dir, "4.2", 1, 5)
    assert "Task 01" in brief and "foo bar" in brief
    assert "Endpoint 1" in brief and "POST /api/y" in brief
    assert "G-01" in brief and "critical goal" in brief
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_loop_library.py -v -k "blueprint"
```

Expected: 3 failures (file doesn't exist).

- [ ] **Step 3: Create `scripts/vg-blueprint-crossai-loop.py`**

```python
#!/usr/bin/env python3
"""Blueprint CrossAI loop wrapper — invokes shared library with
blueprint-stage brief packer (FULL BODY artifacts).

CLI: vg-blueprint-crossai-loop.py --phase X --iteration N [--max-iterations M]

Blueprint CrossAI's job: catch decision↔contract↔plan↔goal misalignments
BEFORE build invests 25 task commits. Brief includes full body of all
phase artifacts (Q8=B): PLAN + CONTRACTS + TEST-GOALS + CONTEXT + UI-MAP +
WORKFLOW-SPECS + CRUD-SURFACES + VIEW-COMPONENTS + BLOCK 5 FE-contracts.
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


def _read_artifact(phase_dir: Path, artifact: str) -> str:
    """Read either flat artifact (e.g. PLAN.md) or split dir
    (PLAN/index.md + PLAN/*.md). Prefer split when present."""
    split_dir = phase_dir / artifact.removesuffix(".md")
    if split_dir.is_dir():
        chunks: list[str] = []
        for child in sorted(split_dir.glob("*.md")):
            chunks.append(f"### {child.name}\n{child.read_text(encoding='utf-8', errors='replace')}")
        return "\n\n".join(chunks) if chunks else f"({artifact} split dir empty)"
    flat = phase_dir / artifact
    if flat.is_file():
        return flat.read_text(encoding="utf-8", errors="replace")
    return f"({artifact} missing)"


def _read_workflow_specs(phase_dir: Path) -> str:
    wf_dir = phase_dir / "WORKFLOW-SPECS"
    if not wf_dir.is_dir():
        return "(WORKFLOW-SPECS missing)"
    chunks = []
    for child in sorted(wf_dir.glob("WF-*.md")):
        chunks.append(f"### {child.name}\n{child.read_text(encoding='utf-8', errors='replace')}")
    return "\n\n".join(chunks) if chunks else "(WORKFLOW-SPECS empty)"


def pack_review_brief(
    phase_dir: Path,
    phase_num: str,
    iteration: int,
    max_iter: int,
) -> str:
    """Pack ALL blueprint artifacts (full body, no caps — Q8=B Gemini Pro fits)."""
    plan = _read_artifact(phase_dir, "PLAN.md")
    contracts = _read_artifact(phase_dir, "API-CONTRACTS.md")
    goals = _read_artifact(phase_dir, "TEST-GOALS.md")
    context = _read_artifact(phase_dir, "CONTEXT.md")
    ui_map = _read_artifact(phase_dir, "UI-MAP.md")
    crud = _read_artifact(phase_dir, "CRUD-SURFACES.md")
    view_comp = _read_artifact(phase_dir, "VIEW-COMPONENTS.md")
    workflows = _read_workflow_specs(phase_dir)

    return f"""# Blueprint CrossAI Verification — Phase {phase_num} iteration {iteration}/{max_iter}

## Your task

Audit blueprint completeness. Find:

1. **D-XX → tasks coverage:** every D-XX in CONTEXT must be referenced
   in ≥1 PLAN task. Missing → BLOCK.
2. **D-XX → goals coverage:** every D-XX must be cited by ≥1 TEST-GOALS
   goal. Missing → BLOCK.
3. **Endpoint → goal coverage:** every endpoint in API-CONTRACTS must
   have a goal in TEST-GOALS. Missing → BLOCK.
4. **UI surface ↔ workflow coverage:** every UI-MAP route or
   VIEW-COMPONENTS view should appear in a WORKFLOW-SPECS WF or be
   covered by a CRUD-SURFACES table. Missing → FLAG (not BLOCK).
5. **CRUD surface ↔ contract:** every CRUD-SURFACES table needs at
   least 1 mutation endpoint. Missing → BLOCK.
6. **Schema/decision contradiction:** API-CONTRACTS schema fields
   contradicting CONTEXT D-XX → BLOCK.

## Output format

<crossai-verdict>
  <verdict>PASS|FAIL</verdict>
  <findings>
    <finding severity="BLOCK|FLAG"><message>...</message></finding>
  </findings>
</crossai-verdict>

## Artifacts (full body)

### PLAN.md
{plan}

### API-CONTRACTS.md
{contracts}

### TEST-GOALS.md
{goals}

### CONTEXT.md
{context}

### UI-MAP.md
{ui_map}

### CRUD-SURFACES.md
{crud}

### VIEW-COMPONENTS.md
{view_comp}

### WORKFLOW-SPECS
{workflows}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--iteration", type=int, required=True)
    ap.add_argument("--max-iterations", type=int, default=5)
    args = ap.parse_args()

    repo_root = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    try:
        stage_cfg = resolve_stage_config("blueprint", repo_root)
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
chmod +x scripts/vg-blueprint-crossai-loop.py
python3 -m pytest scripts/tests/test_crossai_loop_library.py -v -k "blueprint"
```

Expected: 3 passed.

- [ ] **Step 5: Sync mirror + commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp scripts/vg-blueprint-crossai-loop.py .claude/scripts/vg-blueprint-crossai-loop.py
chmod +x .claude/scripts/vg-blueprint-crossai-loop.py
git add scripts/vg-blueprint-crossai-loop.py \
        .claude/scripts/vg-blueprint-crossai-loop.py \
        scripts/tests/test_crossai_loop_library.py
git commit -m "feat(blueprint-crossai): new vg-blueprint-crossai-loop.py wrapper

M1 Task 09 — blueprint-stage CrossAI loop wrapper. Brief includes full
body of all phase artifacts (Q8=B): PLAN + API-CONTRACTS + TEST-GOALS +
CONTEXT + UI-MAP + WORKFLOW-SPECS + CRUD-SURFACES + VIEW-COMPONENTS.
Prefers split-file artifacts (PLAN/task-NN.md, API-CONTRACTS/*.md)
when present, falls back to flat .md.

Coverage rules in prompt: D-XX → tasks, D-XX → goals,
endpoint → goal, CRUD ↔ contract, schema-vs-decision contradiction.

Delegates orchestration to crossai_loop.run_loop().

Tests: 3 (importable, full body brief, split-file preference).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
