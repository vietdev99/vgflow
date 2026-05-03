<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-04-vg-review-ergonomics.md -->
<!-- Spec: docs/superpowers/specs/2026-05-04-vg-review-ergonomics-design.md (Bug J lines 609-648) -->

## Task 42: wave-context.md cross-wave workflow references (M2)

**Files:**
- Create: `scripts/generate-wave-context.py` (new helper extracted from inline orchestrator logic)
- Modify: `commands/vg/_shared/build/waves-overview.md` (Step 2 — call new helper, document cross-wave block)
- Modify: `commands/vg/build.md` (declare `build.cross_wave_workflow_cited` telemetry event)
- Test: `tests/test_wave_context_cross_wave.py`

**Why:** Existing `wave-{N}-context.md` lists per-task constraints by file/field but NOT by workflow/state. Cross-wave workflow coordination is invisible: wave 3 USER subagent doesn't know wave 5 ADMIN subagent depends on its `state_after` value being literally `pending_admin_review`. Result = silent drift between waves implementing different halves of the same workflow.

Concrete drift path: wave 3 task 6 implements user-side `Create` and writes `state: 'awaiting_review'`. Wave 5 task 12 implements admin-side `Approve` and queries `WHERE status = 'pending_admin_review'`. Both pass typecheck/build/tests in isolation (different waves, different file sets). Drift caught only at integration / E2E.

Solution: wave-context generator queries WORKFLOW-SPECS once, builds workflow→tasks index. For each task in current wave with `capsule.workflow_id != null`, list workflow siblings across other waves + cite the exact `state_after` value the workflow declares.

**Cross-task contract recap (locked):**
- Cross-wave block format: `Cross-WORKFLOW constraint:` followed by N indented bullet lines per sibling task in another wave + 1 line per declared state_after fact
- Each sibling line: `- Task <NN> (wave <W>, <ACTOR>, step <S> of <WF>) <reads|writes> state ...`
- Each declared state line: `- Your state_after MUST be exactly '<value>' (per WORKFLOW-SPECS/<WF>.md state_machine.states)`
- Telemetry: `build.cross_wave_workflow_cited` (info) — emitted once per wave whose tasks span ≥1 workflow

Backward-compat: phases without WORKFLOW-SPECS or with all `workflow_id == null` skip the cross-WORKFLOW block silently. No telemetry emission for those waves.

---

- [ ] **Step 1: Write failing test for cross-wave generator**

Create `tests/test_wave_context_cross_wave.py`:

```python
"""Task 42 — verify wave-context generator adds cross-WORKFLOW block.

Pin: when ≥1 task in current wave has capsule.workflow_id != null AND
WORKFLOW-SPECS/<workflow_id>.md declares siblings in other waves, the
generated wave-{N}-context.md must include a 'Cross-WORKFLOW constraint:'
block citing those siblings + the exact state_after value.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture
def synthetic_phase(tmp_path: Path) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "N1"
    phase_dir.mkdir(parents=True)

    # WORKFLOW-SPECS — WF-001 spans waves 3 + 5 + 7
    wf_dir = phase_dir / "WORKFLOW-SPECS"
    wf_dir.mkdir()
    (wf_dir / "index.md").write_text("# WF index\n- WF-001\n", encoding="utf-8")
    (wf_dir / "WF-001.md").write_text(
        "```yaml\n"
        "workflow_id: WF-001\n"
        "name: User → admin approval → user notification\n"
        "actors:\n  - {role: user}\n  - {role: admin}\n"
        "steps:\n"
        "  - {step_id: 2, actor: user, api: POST /api/sites, state_after: {request: pending_admin_review}}\n"
        "  - {step_id: 4, actor: admin, cred_switch_marker: true, api: POST /api/admin/sites/:id/approve, state_after: {request: approved}}\n"
        "  - {step_id: 5, actor: user, cred_switch_marker: true, api: GET /api/sites}\n"
        "state_machine:\n"
        "  states: [pending_admin_review, approved]\n"
        "```\n",
        encoding="utf-8",
    )

    # Capsule cache for waves 3 + 5 + 7
    capsules_dir = tmp_path / ".task-capsules"
    capsules_dir.mkdir()

    def _w(task_num: int, wave: int, actor: str, workflow_step: int, write_phase: str | None) -> None:
        (capsules_dir / f"task-{task_num:02d}.capsule.json").write_text(
            json.dumps({
                "capsule_version": "2",
                "phase": "N1",
                "task_num": task_num,
                "wave_id": wave,
                "actor_role": actor,
                "workflow_id": "WF-001",
                "workflow_step": workflow_step,
                "write_phase": write_phase,
            }),
            encoding="utf-8",
        )

    _w(6, wave=3, actor="user", workflow_step=2, write_phase="create")
    _w(12, wave=5, actor="admin", workflow_step=4, write_phase="update")
    _w(18, wave=7, actor="user", workflow_step=5, write_phase=None)

    # Non-workflow task in wave 3 — should NOT appear in cross-WORKFLOW block
    (capsules_dir / "task-07.capsule.json").write_text(
        json.dumps({
            "capsule_version": "2",
            "phase": "N1",
            "task_num": 7,
            "wave_id": 3,
            "actor_role": None,
            "workflow_id": None,
            "workflow_step": None,
            "write_phase": None,
        }),
        encoding="utf-8",
    )

    return phase_dir


def test_wave_3_context_includes_cross_workflow_block(synthetic_phase: Path) -> None:
    from generate_wave_context import generate_wave_context  # type: ignore

    output = generate_wave_context(
        phase_dir=synthetic_phase,
        wave_id=3,
        wave_task_nums=[6, 7],
        capsules_dir=synthetic_phase.parent.parent.parent / ".task-capsules",
    )
    assert "## Task 6" in output
    assert "Cross-WORKFLOW constraint:" in output
    assert "Task 12" in output and "wave 5" in output and "ADMIN" in output
    assert "Task 18" in output and "wave 7" in output and "USER" in output
    assert "pending_admin_review" in output, \
        "must cite the state_after value per WORKFLOW-SPECS"


def test_wave_3_non_workflow_task_omitted_from_cross_block(synthetic_phase: Path) -> None:
    from generate_wave_context import generate_wave_context  # type: ignore

    output = generate_wave_context(
        phase_dir=synthetic_phase,
        wave_id=3,
        wave_task_nums=[6, 7],
        capsules_dir=synthetic_phase.parent.parent.parent / ".task-capsules",
    )
    # Task 7 has workflow_id=None, so its section must NOT contain Cross-WORKFLOW block
    task_7_section_start = output.find("## Task 7")
    if task_7_section_start == -1:
        return  # absent is fine
    task_7_to_end = output[task_7_section_start:]
    next_task = task_7_to_end.find("## Task ", 1)
    task_7_section = task_7_to_end[: next_task] if next_task != -1 else task_7_to_end
    assert "Cross-WORKFLOW constraint:" not in task_7_section, \
        "non-workflow task must not have cross-workflow block"


def test_no_workflow_specs_skips_cross_block(tmp_path: Path) -> None:
    """Phases without WORKFLOW-SPECS — generator falls back to existing behavior, no error."""
    from generate_wave_context import generate_wave_context  # type: ignore

    phase_dir = tmp_path / ".vg" / "phases" / "N1"
    phase_dir.mkdir(parents=True)
    capsules_dir = tmp_path / ".task-capsules"
    capsules_dir.mkdir()
    (capsules_dir / "task-01.capsule.json").write_text(
        json.dumps({"capsule_version": "1", "phase": "N1", "task_num": 1, "wave_id": 1}),
        encoding="utf-8",
    )

    output = generate_wave_context(
        phase_dir=phase_dir,
        wave_id=1,
        wave_task_nums=[1],
        capsules_dir=capsules_dir,
    )
    assert "Cross-WORKFLOW constraint:" not in output


def test_telemetry_event_declared_in_build_md() -> None:
    text = (REPO / "commands/vg/build.md").read_text(encoding="utf-8")
    assert "build.cross_wave_workflow_cited" in text
```

- [ ] **Step 2: Run failing test**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_wave_context_cross_wave.py -v
```

Expected: 4 FAILED.

- [ ] **Step 3: Implement `scripts/generate-wave-context.py`**

Create `scripts/generate-wave-context.py`:

```python
#!/usr/bin/env python3
"""Task 42 — generate wave-{N}-context.md with optional cross-WORKFLOW block.

Existing wave-context generator emitted file/field constraints by
listing waves' tasks. This module adds a Cross-WORKFLOW block per task
whose capsule references a workflow_id that has siblings in other waves.

Importable from orchestrator:
  from generate_wave_context import generate_wave_context
  text = generate_wave_context(phase_dir, wave_id, wave_task_nums, capsules_dir)

Or callable as a CLI:
  python3 generate-wave-context.py --phase-dir <p> --wave 3 \\
    --tasks 6,7 --capsules-dir <c> > wave-3-context.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

YAML_FENCE_RE = re.compile(r"```ya?ml\n(?P<body>.+?)\n```", re.DOTALL)


def _load_capsule(capsules_dir: Path, task_num: int) -> dict | None:
    f = capsules_dir / f"task-{task_num:02d}.capsule.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_workflow_spec(phase_dir: Path, workflow_id: str) -> dict | None:
    f = phase_dir / "WORKFLOW-SPECS" / f"{workflow_id}.md"
    if not f.exists():
        return None
    text = f.read_text(encoding="utf-8")
    m = YAML_FENCE_RE.search(text)
    if not m:
        return None
    try:
        return yaml.safe_load(m.group("body"))
    except yaml.YAMLError:
        return None


def _index_all_capsules(capsules_dir: Path) -> dict[str, list[dict]]:
    """Build workflow_id → list[capsule] index."""
    index: dict[str, list[dict]] = {}
    if not capsules_dir.is_dir():
        return index
    for f in sorted(capsules_dir.glob("task-*.capsule.json")):
        try:
            cap = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        wf = cap.get("workflow_id")
        if wf:
            index.setdefault(wf, []).append(cap)
    return index


def _state_after_for_step(spec: dict, step_id: int) -> str | None:
    for step in (spec.get("steps") or []):
        if step.get("step_id") == step_id:
            sa = step.get("state_after")
            if isinstance(sa, dict) and sa:
                return str(next(iter(sa.values())))
    return None


def _verb_for_step(spec: dict, step_id: int) -> str:
    """Return 'reads' or 'writes' based on whether step has state_after declared."""
    for step in (spec.get("steps") or []):
        if step.get("step_id") == step_id:
            return "writes" if isinstance(step.get("state_after"), dict) and step.get("state_after") else "reads"
    return "reads"


def _render_cross_workflow_block(
    current_capsule: dict,
    spec: dict,
    workflow_index: dict[str, list[dict]],
) -> list[str]:
    wf_id = current_capsule["workflow_id"]
    siblings = [c for c in workflow_index.get(wf_id, []) if c["task_num"] != current_capsule["task_num"]]
    if not siblings:
        return []

    lines = ["  Cross-WORKFLOW constraint:"]
    for sib in sorted(siblings, key=lambda c: (c.get("wave_id", 0), c["task_num"])):
        wave = sib.get("wave_id", "?")
        actor = (sib.get("actor_role") or "?").upper()
        step = sib.get("workflow_step", "?")
        verb = _verb_for_step(spec, step) if isinstance(step, int) else "interacts with"
        lines.append(
            f"    - Task {sib['task_num']} (wave {wave}, {actor}, step {step} of {wf_id}) "
            f"{verb} state established by your step"
        )

    own_step = current_capsule.get("workflow_step")
    if isinstance(own_step, int):
        sa = _state_after_for_step(spec, own_step)
        if sa:
            lines.append(
                f"    - Your `state_after` MUST be exactly `{sa}` "
                f"(per WORKFLOW-SPECS/{wf_id}.md state_machine.states)"
            )
    return lines


def generate_wave_context(
    phase_dir: Path,
    wave_id: int,
    wave_task_nums: list[int],
    capsules_dir: Path,
) -> str:
    """Render wave-{N}-context.md text. Cross-WORKFLOW block appended per task whose capsule has workflow_id."""
    workflow_index = _index_all_capsules(capsules_dir)

    out: list[str] = [f"# Wave {wave_id} Context — Phase {phase_dir.name}", ""]
    out.append(f"Tasks running in parallel this wave:")
    out.append("")

    cross_emitted = False
    for task_num in wave_task_nums:
        cap = _load_capsule(capsules_dir, task_num)
        if cap is None:
            out.append(f"## Task {task_num}")
            out.append("  (capsule not found — context degraded)")
            out.append("")
            continue
        title = cap.get("task_title") or f"Task {task_num}"
        out.append(f"## Task {task_num} — {title}")

        wf_id = cap.get("workflow_id")
        if wf_id:
            actor = (cap.get("actor_role") or "?").upper()
            step = cap.get("workflow_step", "?")
            out.append(f"  Workflow: {wf_id} step {step} ({actor})")
            spec = _load_workflow_spec(phase_dir, wf_id)
            if spec:
                cross = _render_cross_workflow_block(cap, spec, workflow_index)
                if cross:
                    out.extend(cross)
                    cross_emitted = True
        out.append("")

    if cross_emitted:
        # Telemetry hint for orchestrator (string sentinel parsed by caller).
        out.append("<!-- vg-telemetry: build.cross_wave_workflow_cited -->")
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--phase-dir", required=True)
    p.add_argument("--wave", required=True, type=int)
    p.add_argument("--tasks", required=True, help="Comma-separated task numbers")
    p.add_argument("--capsules-dir", required=True)
    args = p.parse_args()

    nums = [int(s) for s in args.tasks.split(",") if s.strip()]
    text = generate_wave_context(
        phase_dir=Path(args.phase_dir),
        wave_id=args.wave,
        wave_task_nums=nums,
        capsules_dir=Path(args.capsules_dir),
    )
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

```bash
chmod +x scripts/generate-wave-context.py
```

- [ ] **Step 4: Update `commands/vg/_shared/build/waves-overview.md` Step 2**

Edit `commands/vg/_shared/build/waves-overview.md`. Locate "### Step 2 — Generate `wave-{N}-context.md` (8a)" (line 108). Append after the existing markdown example:

```markdown
### Step 2.1 — Cross-WORKFLOW block (Task 42, M2)

When any task in the wave has `capsule.workflow_id != null` AND
`${PHASE_DIR}/WORKFLOW-SPECS/<workflow_id>.md` exists, the orchestrator
appends a `Cross-WORKFLOW constraint:` block per such task. This block
cites siblings in other waves + the exact `state_after` value the workflow
declares for the current task's step.

Use the canonical helper:

```bash
python3 scripts/generate-wave-context.py \
  --phase-dir "${PHASE_DIR}" \
  --wave "${WAVE_ID}" \
  --tasks "$(IFS=,; echo "${WAVE_TASK_NUMS[*]}")" \
  --capsules-dir "${PHASE_DIR}/.task-capsules" \
  > "${PHASE_DIR}/wave-${WAVE_ID}-context.md"
```

The script:
- Reads each task's capsule (Task 41 schema) for `workflow_id` / `workflow_step` / `actor_role`
- Reads `WORKFLOW-SPECS/<workflow_id>.md` to resolve the `state_after` value for the task's step
- Indexes capsules across ALL waves to find siblings
- Emits HTML comment sentinel `<!-- vg-telemetry: build.cross_wave_workflow_cited -->` when the block was added — orchestrator greps this and emits the telemetry event

Backward-compat: phases without WORKFLOW-SPECS or all-null workflow_ids
skip the block silently. The script never errors on missing artifacts.

Example output:

```markdown
## Task 6 — tx_groups enum extension
  Workflow: WF-001 step 2 (USER)
  Cross-WORKFLOW constraint:
    - Task 12 (wave 5, ADMIN, step 4 of WF-001) writes state established by your step
    - Task 18 (wave 7, USER, step 5 of WF-001) reads state established by your step
    - Your `state_after` MUST be exactly `pending_admin_review` (per WORKFLOW-SPECS/WF-001.md state_machine.states)
```
```

- [ ] **Step 5: Add telemetry event to `commands/vg/build.md`**

Edit `commands/vg/build.md`. Add to `must_emit_telemetry`:

```yaml
    # Task 42 — cross-wave workflow citation (M2)
    - event_type: "build.cross_wave_workflow_cited"
      phase: "${PHASE_NUMBER}"
      severity: "info"
```

The orchestrator emits this event after `generate-wave-context.py` returns IF its output contains `<!-- vg-telemetry: build.cross_wave_workflow_cited -->`.

- [ ] **Step 6: Run all task-42 tests — verify GREEN**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_wave_context_cross_wave.py -v
```

Expected: 4 PASSED.

- [ ] **Step 7: Sync + commit**

```bash
DEV_ROOT=. bash sync.sh --no-global 2>&1 | tail -3
git add scripts/generate-wave-context.py \
        commands/vg/_shared/build/waves-overview.md \
        commands/vg/build.md \
        tests/test_wave_context_cross_wave.py \
        .claude/ codex-skills/ .codex/
git commit -m "feat(build): wave-context cross-WORKFLOW citation (Task 42, Bug J, M2)

Existing wave-{N}-context.md cited per-task constraints by file/field
but NOT by workflow/state. Cross-wave coordination invisible: wave 3
USER subagent didn't know wave 5 ADMIN subagent depends on its
state_after being literally 'pending_admin_review'.

Drift example: wave 3 task 6 writes state='awaiting_review'; wave 5
task 12 queries WHERE status='pending_admin_review'. Both pass
typecheck/build/tests in isolation; drift caught only at integration.

Fix: scripts/generate-wave-context.py builds workflow→tasks index from
all capsules (Task 41 schema), then emits a Cross-WORKFLOW block per
task whose capsule has workflow_id. Block cites siblings in other waves
+ pulls the exact state_after value from WORKFLOW-SPECS/<WF>.md.

HTML comment sentinel <!-- vg-telemetry: build.cross_wave_workflow_cited -->
in output triggers orchestrator telemetry emission.

Backward-compat: phases without WORKFLOW-SPECS or all-null workflow_ids
skip the block silently — no error, no telemetry.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
