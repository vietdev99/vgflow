<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-04-vg-review-ergonomics.md -->
<!-- Spec: docs/superpowers/specs/2026-05-04-vg-review-ergonomics-design.md (Bug E lines 260-289) -->

## Task 37: Build envelope per-task slices (CRUD-SURFACES + LENS-WALK + RCRURD invariants)

**Files:**
- Modify: `scripts/vg-load.sh` (add 3 new artifact handlers: `crud-surfaces`, `lens-walk`, `rcrurd-invariant`)
- Modify: `scripts/pre-executor-check.py` (orchestrator pre-resolves per-task slices into envelope)
- Modify: `commands/vg/_shared/build/waves-delegation.md` (add 3 envelope fields + reference blocks)
- Modify: `commands/vg/build.md` (add `build.envelope_slice_resolved` telemetry event)
- Test: `tests/test_build_envelope_slices.py`
- Test: `tests/test_vg_load_per_task_artifacts.py`

**Why:** Codex finding #33 corrected an earlier scope error: UI-MAP + VIEW-COMPONENTS are ALREADY in envelope (`waves-delegation.md:30-31, 61-62`). The actual missing artifacts are:

1. **CRUD-SURFACES.md** — produced by blueprint, consumed only by `/vg:test`. Build mutation tasks don't see `kit:crud-roundtrip` pattern → handler shape drift.
2. **LENS-WALK seeds** — produced by blueprint Step `2b5e_a_lens_walk`, consumed only by `/vg:review`. Build can't pre-test against lens scenarios.
3. **RCRURD invariant per task** — produced by Task 22 schema (per-goal), but envelope has no field for per-task invariant slice. Build FE/mutation task subagent doesn't see invariants → forgets to insert `expectReadAfterWrite()` from Task 24 helper.

Codex finding #34-35 established per-task slicing pattern: CRUD-SURFACES is per-phase but build envelope is per-task. Loading whole CRUD-SURFACES.md into every task's envelope inflates context budget. Solution: orchestrator pre-resolves per-task slices via `vg-load`, writes results to `.task-capsules/task-NN.{crud-surfaces,lens-walk,rcrurd}.<...>.md`, passes paths in envelope.

Codex finding #36 graceful-degradation: stale capsules from in-flight phases get warning + continue with reduced context. New fields are non-required.

**Cross-task contract recap (locked):** Envelope adds 3 fields:
- `crud_surfaces_slice_path: string | null`
- `lens_walk_slice_path: string | null`
- `rcrurd_invariants_paths: string[]` (one path per goal the task touches)

vg-load `--artifact rcrurd-invariant --task NN` returns ALL `G-XX` invariants for goals task NN implements. Per-goal slicing already supported by Task 22 (`${PHASE_DIR}/RCRURD-INVARIANTS/G-NN.yaml`).

---

- [ ] **Step 1: Write failing test for `vg-load` 3 new artifact handlers**

Create `tests/test_vg_load_per_task_artifacts.py`:

```python
"""Task 37 — verify vg-load.sh supports new artifacts: crud-surfaces, lens-walk, rcrurd-invariant.

Pin: per-task / per-goal slicing for build envelope (Bug E).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VG_LOAD = REPO / "scripts/vg-load.sh"


@pytest.fixture
def synthetic_phase(tmp_path: Path) -> Path:
    """Create a synthetic .vg/phases/N1 with CRUD-SURFACES, LENS-WALK, RCRURD-INVARIANTS."""
    phase_dir = tmp_path / ".vg" / "phases" / "N1"
    phase_dir.mkdir(parents=True)

    # CRUD-SURFACES split: per-resource files
    cs_dir = phase_dir / "CRUD-SURFACES"
    cs_dir.mkdir()
    (cs_dir / "index.md").write_text("# CRUD-SURFACES index\n- sites\n- users\n", encoding="utf-8")
    (cs_dir / "sites.md").write_text("# Resource: sites\n- create: POST /api/sites\n- read: GET /api/sites/{id}\n", encoding="utf-8")
    (cs_dir / "users.md").write_text("# Resource: users\n- create: POST /api/users\n", encoding="utf-8")
    (phase_dir / "CRUD-SURFACES.md").write_text("# CRUD-SURFACES (flat)\n", encoding="utf-8")

    # LENS-WALK: per-goal split (already exists in repo for blueprint output)
    lw_dir = phase_dir / "LENS-WALK"
    lw_dir.mkdir()
    (lw_dir / "index.md").write_text("# LENS-WALK index\n- G-04\n- G-12\n", encoding="utf-8")
    (lw_dir / "G-04.md").write_text("# G-04 lens-walk seeds\n## form-lifecycle\n- create_then_read\n", encoding="utf-8")
    (lw_dir / "G-12.md").write_text("# G-12 lens-walk seeds\n## modal-state\n- esc_dismiss\n", encoding="utf-8")

    # RCRURD-INVARIANTS: per-goal yaml files (Task 22 schema)
    ri_dir = phase_dir / "RCRURD-INVARIANTS"
    ri_dir.mkdir()
    (ri_dir / "index.md").write_text("# RCRURD index\n- G-04 (mutation)\n- G-12 (mutation)\n", encoding="utf-8")
    (ri_dir / "G-04.yaml").write_text("goal_id: G-04\nlifecycle: rcrurd\n", encoding="utf-8")
    (ri_dir / "G-12.yaml").write_text("goal_id: G-12\nlifecycle: rcrurdr\n", encoding="utf-8")

    return phase_dir


def _run(args: list[str], phase_root: Path) -> subprocess.CompletedProcess:
    """Invoke vg-load.sh with PHASE_ROOT env override."""
    env = {"PHASE_ROOT": str(phase_root.parent)}  # parent so phases/N1 resolves
    return subprocess.run(
        ["bash", str(VG_LOAD), *args],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, **env},
    )


def test_vg_load_crud_surfaces_by_resource(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "crud-surfaces", "--resource", "sites"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "Resource: sites" in result.stdout
    assert "POST /api/sites" in result.stdout


def test_vg_load_crud_surfaces_full(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "crud-surfaces", "--full"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "CRUD-SURFACES (flat)" in result.stdout


def test_vg_load_crud_surfaces_index(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "crud-surfaces", "--index"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "CRUD-SURFACES index" in result.stdout


def test_vg_load_lens_walk_by_goal(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "lens-walk", "--goal", "G-04"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "G-04 lens-walk seeds" in result.stdout
    assert "create_then_read" in result.stdout


def test_vg_load_rcrurd_invariant_by_goal(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "rcrurd-invariant", "--goal", "G-12"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "lifecycle: rcrurdr" in result.stdout


def test_vg_load_rcrurd_invariant_by_task_lists_paths(synthetic_phase: Path) -> None:
    """`--task NN` requires goals→task mapping. We test the listing form: use --list to enumerate
    available per-goal files, then orchestrator handles mapping. This test covers the --list filter."""
    result = _run(["--phase", "N1", "--artifact", "rcrurd-invariant", "--list"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "G-04.yaml" in result.stdout
    assert "G-12.yaml" in result.stdout


def test_vg_load_unknown_artifact_errors(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "totally-unknown"], synthetic_phase)
    assert result.returncode != 0
    assert "unknown artifact" in result.stderr.lower()
```

- [ ] **Step 2: Run failing test**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_vg_load_per_task_artifacts.py -v
```

Expected: 6 FAILED + 1 PASSED (`test_vg_load_unknown_artifact_errors` already passes).

- [ ] **Step 3: Extend `scripts/vg-load.sh` — 3 new artifact handlers**

Edit `scripts/vg-load.sh`. Locate the existing `case "$artifact" in` block (around line 106). Add 3 new branches BEFORE the catch-all `*)`:

```bash
  crud-surfaces)
    # Task 37 (Bug E) — per-resource slicing for build envelope.
    sub_dir="$phase_dir/CRUD-SURFACES"
    flat_file="$phase_dir/CRUD-SURFACES.md"
    case "$filter_kind" in
      full)  cat "$flat_file" 2>/dev/null || { echo "ERROR: $flat_file not found" >&2; exit 2; } ;;
      index) cat "$sub_dir/index.md" 2>/dev/null || { echo "ERROR: $sub_dir/index.md not found" >&2; exit 2; } ;;
      list)  ls "$sub_dir"/*.md 2>/dev/null | grep -v '/index\.md$' || { echo "no resource files" >&2; exit 3; } ;;
      resource)
        f="$sub_dir/${filter_value}.md"
        [ -f "$f" ] || { echo "ERROR: resource file not found: $f" >&2; exit 2; }
        cat "$f"
        ;;
      *) echo "ERROR: unsupported filter '$filter_kind' for crud-surfaces (use --resource <name>, --full, --index, --list)" >&2; exit 1 ;;
    esac
    ;;

  lens-walk)
    # Task 37 — per-goal slicing for build envelope (consumes blueprint 2b5e_a_lens_walk output).
    sub_dir="$phase_dir/LENS-WALK"
    flat_file="$phase_dir/LENS-WALK.md"
    case "$filter_kind" in
      full)  cat "$flat_file" 2>/dev/null || { echo "ERROR: $flat_file not found" >&2; exit 2; } ;;
      index) cat "$sub_dir/index.md" 2>/dev/null || { echo "ERROR: $sub_dir/index.md not found" >&2; exit 2; } ;;
      list)  ls "$sub_dir"/G-*.md 2>/dev/null || { echo "no lens-walk goal files" >&2; exit 3; } ;;
      goal)
        f="$sub_dir/${filter_value}.md"
        [ -f "$f" ] || { echo "ERROR: lens-walk file not found: $f" >&2; exit 2; }
        cat "$f"
        ;;
      *) echo "ERROR: unsupported filter '$filter_kind' for lens-walk (use --goal G-NN, --full, --index, --list)" >&2; exit 1 ;;
    esac
    ;;

  rcrurd-invariant)
    # Task 37 — per-goal RCRURD/RCRURDR invariants (Task 22 schema, extended Task 39).
    sub_dir="$phase_dir/RCRURD-INVARIANTS"
    case "$filter_kind" in
      index) cat "$sub_dir/index.md" 2>/dev/null || { echo "ERROR: $sub_dir/index.md not found" >&2; exit 2; } ;;
      list)  ls "$sub_dir"/G-*.yaml 2>/dev/null || { echo "no rcrurd files" >&2; exit 3; } ;;
      goal)
        f="$sub_dir/${filter_value}.yaml"
        [ -f "$f" ] || { echo "ERROR: rcrurd file not found: $f" >&2; exit 2; }
        cat "$f"
        ;;
      *) echo "ERROR: unsupported filter '$filter_kind' for rcrurd-invariant (use --goal G-NN, --index, --list)" >&2; exit 1 ;;
    esac
    ;;
```

Also update the catch-all error message at the end of the case statement:

```bash
  *)
    echo "ERROR: unknown artifact '$artifact'. Supported: plan, contracts, goals, edge-cases, crud-surfaces, lens-walk, rcrurd-invariant" >&2
    exit 1
    ;;
```

And update the help-text comments at the top of the file (around line 9):

```
#   --artifact crud-surfaces (Task 37 — Bug E)
#       --resource <name>    → CRUD-SURFACES/<name>.md (per-resource slice)
#       --full | --index | --list
#
#   --artifact lens-walk (Task 37 — Bug E)
#       --goal G-NN          → LENS-WALK/G-NN.md (per-goal lens seeds)
#       --full | --index | --list
#
#   --artifact rcrurd-invariant (Task 37 — Bug E)
#       --goal G-NN          → RCRURD-INVARIANTS/G-NN.yaml (per-goal invariant)
#       --index | --list
```

- [ ] **Step 4: Run vg-load tests — verify GREEN**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_vg_load_per_task_artifacts.py -v
```

Expected: 7 PASSED.

- [ ] **Step 5: Write failing test for envelope slice resolution**

Create `tests/test_build_envelope_slices.py`:

```python
"""Task 37 — verify pre-executor-check.py orchestrator resolves per-task slices.

Pin: capsule build resolves crud_surfaces_slice_path + lens_walk_slice_path +
rcrurd_invariants_paths from goals→task mapping. Stale capsules degrade
gracefully (warning, not fail).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# We test the new helper function build_per_task_slices directly via import.
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture
def synthetic_phase(tmp_path: Path) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "N1"
    phase_dir.mkdir(parents=True)

    # CRUD-SURFACES per-resource
    (phase_dir / "CRUD-SURFACES").mkdir()
    (phase_dir / "CRUD-SURFACES" / "sites.md").write_text("# Resource: sites\n", encoding="utf-8")
    (phase_dir / "CRUD-SURFACES.md").write_text("flat\n", encoding="utf-8")

    # LENS-WALK per-goal
    (phase_dir / "LENS-WALK").mkdir()
    (phase_dir / "LENS-WALK" / "G-04.md").write_text("# G-04\n", encoding="utf-8")

    # RCRURD-INVARIANTS per-goal
    (phase_dir / "RCRURD-INVARIANTS").mkdir()
    (phase_dir / "RCRURD-INVARIANTS" / "G-04.yaml").write_text("goal_id: G-04\n", encoding="utf-8")

    # Task capsule cache dir
    (tmp_path / ".task-capsules").mkdir()
    return phase_dir


def test_build_per_task_slices_resolves_resource_and_goals(synthetic_phase: Path) -> None:
    from pre_executor_check import build_per_task_slices  # type: ignore

    slices = build_per_task_slices(
        phase_dir=synthetic_phase,
        task_num=4,
        endpoints=["POST /api/sites", "GET /api/sites/{id}"],
        goals=["G-04"],
        cache_dir=synthetic_phase.parent.parent.parent / ".task-capsules",
    )
    assert slices["crud_surfaces_slice_path"] is not None
    assert "sites" in slices["crud_surfaces_slice_path"]
    assert slices["lens_walk_slice_path"] is not None
    assert "G-04" in slices["lens_walk_slice_path"]
    assert isinstance(slices["rcrurd_invariants_paths"], list)
    assert len(slices["rcrurd_invariants_paths"]) == 1
    assert "G-04" in slices["rcrurd_invariants_paths"][0]


def test_build_per_task_slices_handles_missing_artifact(tmp_path: Path) -> None:
    """Phase without CRUD-SURFACES gets None for slice path; no exception."""
    from pre_executor_check import build_per_task_slices  # type: ignore

    empty_phase = tmp_path / ".vg" / "phases" / "N2"
    empty_phase.mkdir(parents=True)
    (tmp_path / ".task-capsules").mkdir()

    slices = build_per_task_slices(
        phase_dir=empty_phase,
        task_num=1,
        endpoints=[],
        goals=[],
        cache_dir=tmp_path / ".task-capsules",
    )
    assert slices["crud_surfaces_slice_path"] is None
    assert slices["lens_walk_slice_path"] is None
    assert slices["rcrurd_invariants_paths"] == []


def test_capsule_includes_slice_paths(synthetic_phase: Path) -> None:
    from pre_executor_check import build_task_context_capsule  # type: ignore

    capsule = build_task_context_capsule(
        phase_dir=synthetic_phase,
        task_num=4,
        task_context="## Task 04: Add POST /api/sites handler\n<file-path>apps/api/src/sites/routes.ts</file-path>\n<goal>G-04</goal>\n",
        contract_context="POST /api/sites\n",
        goals_context="G-04",
        crud_surface_context="sites",
        sibling_context="none",
        downstream_callers="none",
        design_context="none",
        build_config={"phase": "N1"},
    )
    # New fields (Task 37) — present even if null
    assert "crud_surfaces_slice_path" in capsule
    assert "lens_walk_slice_path" in capsule
    assert "rcrurd_invariants_paths" in capsule
    assert isinstance(capsule["rcrurd_invariants_paths"], list)


def test_telemetry_emits_envelope_slice_resolved(synthetic_phase: Path, tmp_path: Path) -> None:
    """`build.envelope_slice_resolved` event must be declared in build.md must_emit_telemetry."""
    build_md = REPO / "commands/vg/build.md"
    text = build_md.read_text(encoding="utf-8")
    assert "build.envelope_slice_resolved" in text, \
        "Task 37 telemetry event must be declared in build.md must_emit_telemetry"
```

- [ ] **Step 6: Run failing test**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_build_envelope_slices.py -v
```

Expected: 4 FAILED.

- [ ] **Step 7: Extend `scripts/pre-executor-check.py` with `build_per_task_slices()` + capsule integration**

Edit `scripts/pre-executor-check.py`. Add this helper function above `build_task_context_capsule()` (around line 570):

```python
def _resource_from_endpoint(endpoint: str) -> str | None:
    """Extract resource name from `POST /api/sites` → `sites`. Returns None if path lacks /api/<resource>."""
    parts = endpoint.split(maxsplit=1)
    if len(parts) < 2:
        return None
    path = parts[1]
    m = re.search(r"/api/([a-z][a-z0-9-]*)", path)
    return m.group(1) if m else None


def build_per_task_slices(
    phase_dir: Path,
    task_num: int,
    endpoints: list[str],
    goals: list[str],
    cache_dir: Path,
) -> dict:
    """Task 37 — orchestrator pre-resolves per-task artifact slices.

    Returns a dict with 3 keys:
      - crud_surfaces_slice_path: str | None — concatenated per-resource slices
      - lens_walk_slice_path:     str | None — concatenated per-goal lens-walk slices
      - rcrurd_invariants_paths:  list[str] — list of per-goal yaml paths

    Stale phases (missing CRUD-SURFACES or LENS-WALK directory) get None
    + a warning logged to stderr — NOT an exception (Codex finding #36
    graceful-degradation).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    # CRUD-SURFACES: union of resources extracted from endpoints
    cs_dir = phase_dir / "CRUD-SURFACES"
    crud_path: str | None = None
    if cs_dir.exists() and endpoints:
        resources = sorted({r for r in (_resource_from_endpoint(e) for e in endpoints) if r})
        chunks = []
        for r in resources:
            f = cs_dir / f"{r}.md"
            if f.exists():
                chunks.append(f"# Resource: {r}\n" + f.read_text(encoding="utf-8"))
        if chunks:
            slice_file = cache_dir / f"task-{task_num:02d}.crud-surfaces.md"
            slice_file.write_text("\n\n".join(chunks), encoding="utf-8")
            crud_path = str(slice_file.relative_to(phase_dir.parent.parent.parent)) \
                if str(slice_file).startswith(str(phase_dir.parent.parent.parent)) else str(slice_file)
    elif endpoints and not cs_dir.exists():
        sys.stderr.write(
            f"WARN: CRUD-SURFACES/ missing for task-{task_num} — context degraded.\n"
        )

    # LENS-WALK: union of per-goal slices
    lw_dir = phase_dir / "LENS-WALK"
    lw_path: str | None = None
    if lw_dir.exists() and goals:
        chunks = []
        for g in goals:
            f = lw_dir / f"{g}.md"
            if f.exists():
                chunks.append(f.read_text(encoding="utf-8"))
        if chunks:
            slice_file = cache_dir / f"task-{task_num:02d}.lens-walk.md"
            slice_file.write_text("\n\n".join(chunks), encoding="utf-8")
            lw_path = str(slice_file)
    elif goals and not lw_dir.exists():
        sys.stderr.write(
            f"WARN: LENS-WALK/ missing for task-{task_num} — context degraded.\n"
        )

    # RCRURD-INVARIANTS: list of per-goal yaml paths (no concat — yaml parsed by subagent)
    ri_dir = phase_dir / "RCRURD-INVARIANTS"
    rcrurd_paths: list[str] = []
    if ri_dir.exists():
        for g in goals:
            f = ri_dir / f"{g}.yaml"
            if f.exists():
                rcrurd_paths.append(str(f))

    return {
        "crud_surfaces_slice_path": crud_path,
        "lens_walk_slice_path": lw_path,
        "rcrurd_invariants_paths": rcrurd_paths,
    }
```

Then modify `build_task_context_capsule()` to call this helper. Around line 605 (the `capsule = {...}` literal), add 3 fields. Pass `endpoints` + `_extract_goal_ids(...)` already computed:

```python
    # Task 37 — pre-resolve per-task slices for build envelope
    slices = build_per_task_slices(
        phase_dir=phase_dir,
        task_num=task_num,
        endpoints=endpoints,
        goals=_extract_goal_ids(task_context, goals_context),
        cache_dir=phase_dir.parent.parent.parent / ".task-capsules",
    )

    capsule = {
        "capsule_version": "1",
        # ...existing fields up through anti_lazy_read_rules...
        "crud_surfaces_slice_path": slices["crud_surfaces_slice_path"],
        "lens_walk_slice_path": slices["lens_walk_slice_path"],
        "rcrurd_invariants_paths": slices["rcrurd_invariants_paths"],
    }
```

Add `import sys` if not already imported at top of file.

- [ ] **Step 8: Update `commands/vg/_shared/build/waves-delegation.md` — declare 3 envelope fields**

In the JSON envelope example (around line 35), add 3 fields after `edge_cases_for_goals`:

```json
{
  ...existing fields...,
  "edge_cases_for_goals": ["G-04", "G-12"],
  "crud_surfaces_slice_path": ".task-capsules/task-04.crud-surfaces.md",
  "lens_walk_slice_path": ".task-capsules/task-04.lens-walk.md",
  "rcrurd_invariants_paths": [
    "${PHASE_DIR}/RCRURD-INVARIANTS/G-04.yaml",
    "${PHASE_DIR}/RCRURD-INVARIANTS/G-12.yaml"
  ],
  "bootstrap_rules": [...]
}
```

In the field-semantics table (around line 79), add 3 rows AFTER `edge_cases_for_goals`:

```
| `crud_surfaces_slice_path` | maybe | Pre-resolved CRUD-SURFACES slice for resources this task touches. NULL when task has no API endpoints OR phase predates Task 37. Subagent reads via `cat $crud_surfaces_slice_path` (file is concatenation of per-resource slices). |
| `lens_walk_slice_path` | maybe | Pre-resolved LENS-WALK slice for goals this task implements. NULL when task touches no goals OR phase has no `LENS-WALK/`. Subagent loads to understand bug-class probe variants. |
| `rcrurd_invariants_paths` | maybe | List of per-goal RCRURD-INVARIANTS yaml paths (Task 22 schema, Task 39 RCRURDR extension). One entry per goal. Empty list = no invariants apply. Subagent MUST honor `lifecycle: rcrurd \| rcrurdr \| partial` when emitting test code or handler ordering. |
```

In the prompt template (after the existing `<edge_cases_for_goals>` block), add 3 new context blocks. Locate the existing `<contract_context>` or `<wave_context>` reference points and insert:

```
<crud_surface_context>
${CRUD_SURFACE_BLOCK}    # @${crud_surfaces_slice_path} when present, else "NONE — task touches no CRUD resources"
</crud_surface_context>

<lens_walk_context>
${LENS_WALK_BLOCK}       # @${lens_walk_slice_path} when present, else "NONE — task touches no goals"
</lens_walk_context>

<rcrurd_invariants_context>
${RCRURD_INVARIANTS_BLOCK}    # Concatenation of @${rcrurd_invariants_paths[N]} entries; "NONE" when list empty.
</rcrurd_invariants_context>
```

The orchestrator resolves `${CRUD_SURFACE_BLOCK}` etc. by reading slice_paths and substituting `@${path}` references for each, OR literal `NONE — ...` when paths are null/empty. This pattern matches the existing `${DESIGN_CONTEXT_BLOCK}` resolution logic.

- [ ] **Step 9: Add telemetry event to `commands/vg/build.md`**

Edit `commands/vg/build.md`. In the `must_emit_telemetry` block, add:

```yaml
    # Task 37 — per-task slice resolution (Bug E)
    - event_type: "build.envelope_slice_resolved"
      phase: "${PHASE_NUMBER}"
      severity: "info"
```

The orchestrator emits this event ONCE per task spawn after `build_per_task_slices()` returns, with `details.task_num` + `details.slices_resolved` count.

- [ ] **Step 10: Run all task-37 tests — verify GREEN**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_vg_load_per_task_artifacts.py tests/test_build_envelope_slices.py -v
```

Expected: 11 PASSED (7 vg-load + 4 envelope).

- [ ] **Step 11: Sync + commit**

```bash
DEV_ROOT=. bash sync.sh --no-global 2>&1 | tail -3
git add scripts/vg-load.sh \
        scripts/pre-executor-check.py \
        commands/vg/_shared/build/waves-delegation.md \
        commands/vg/build.md \
        tests/test_vg_load_per_task_artifacts.py \
        tests/test_build_envelope_slices.py \
        .claude/ codex-skills/ .codex/
git commit -m "feat(build): per-task envelope slices for CRUD-SURFACES + LENS-WALK + RCRURD (Task 37, Bug E)

Codex finding #33 corrected scope: UI-MAP + VIEW-COMPONENTS already in
envelope. Real gaps were CRUD-SURFACES (consumed only by /vg:test),
LENS-WALK (consumed only by /vg:review), RCRURD invariants (consumed
only by Task 23 review runtime gate). Build mutation tasks didn't see
kit:crud-roundtrip pattern, lens scenarios, or invariant requirements.

Per Codex finding #34-35: orchestrator pre-resolves per-task slices via
vg-load (CRUD-SURFACES is per-phase but envelope is per-task; loading
whole file inflates context budget). Slices written to
.task-capsules/task-NN.{crud-surfaces,lens-walk}.md + RCRURD-INVARIANTS
yaml paths listed.

3 new vg-load.sh artifact handlers:
- crud-surfaces (--resource <name> | --full | --index | --list)
- lens-walk (--goal G-NN | --full | --index | --list)
- rcrurd-invariant (--goal G-NN | --index | --list)

3 new envelope fields (waves-delegation.md):
- crud_surfaces_slice_path: string | null
- lens_walk_slice_path: string | null
- rcrurd_invariants_paths: string[]

Codex finding #36 graceful-degradation: stale capsules from in-flight
phases (PV3 4.1) get warn + null/empty fields, not exception.

Telemetry: build.envelope_slice_resolved (info, per task spawn).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
