<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-04-vg-review-ergonomics.md -->
<!-- Spec: docs/superpowers/specs/2026-05-04-vg-review-ergonomics-design.md (Bug I lines 559-607) -->

## Task 41: Capsule extension — actor_role + workflow_id + workflow_step + write_phase + execution_contract.must_match_workflow_state (M1)

**Files:**
- Modify: `scripts/pre-executor-check.py` (extend `build_task_context_capsule()` + add tag-extraction helpers)
- Modify: `commands/vg/_shared/blueprint/plan-delegation.md` (declare PLAN task tag conventions)
- Test: `tests/test_capsule_workflow_fields.py`

**Why:** Without these capsule fields, build subagent doesn't know "I'm USER half of G-04 implementing step 2 of WF-001". Result = silent drift between user-half and admin-half code, even when both pass typecheck/build/tests in isolation.

**Cross-task contract recap (locked):**
- `actor_role: "user" | "admin" | "system" | null` (parsed from PLAN task `<actor>` tag; null = legacy / single-actor)
- `workflow_id: "WF-NN" | null` (parsed from PLAN task `<workflow>` tag)
- `workflow_step: int | null` (parsed from PLAN task `<workflow-step>` tag)
- `write_phase: "create" | "update" | "delete" | null` (parsed from `<write-phase>` tag — DISTINCT from Task 39's RCRURDR `lifecycle_phases[]` which has 7 op-names. `write_phase` is single-write classifier for the task; `lifecycle_phases` is full RCRURDR cycle. Codex round-2 Amendment B locked the rename.)
- `capsule_version: "2"` (was `"1"`; new shape; v1 capsules tolerated for in-flight phases — graceful-degradation reads them with all 4 new fields = null)
- `execution_contract.must_match_workflow_state: bool` (true when workflow_id != None)
- `execution_contract.actor_role_hint: str` (subagent uses for cred fixture selection)
- 2 new entries appended to `anti_lazy_read_rules`

**Backward-compat:** Tasks 37 / 39 / 40 / 42 / 43 may consume `capsule_version` to choose code-paths — for legacy capsules without these fields, treat as `null` and proceed with reduced context (warning logged).

---

- [ ] **Step 1: Write failing test for capsule schema**

Create `tests/test_capsule_workflow_fields.py`:

```python
"""Task 41 — verify capsule extension for actor + workflow + write_phase awareness.

Pin: build_task_context_capsule() returns capsule_version='2' with
actor_role / workflow_id / workflow_step / write_phase fields. Missing
PLAN tags = None (graceful, backward-compat).

execution_contract gains must_match_workflow_state + actor_role_hint.
anti_lazy_read_rules gains 2 workflow-aware entries.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture
def synthetic_phase(tmp_path: Path) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "N1"
    phase_dir.mkdir(parents=True)
    return phase_dir


def _import_helpers():
    from pre_executor_check import (  # type: ignore
        build_task_context_capsule,
        extract_actor_role,
        extract_workflow_id,
        extract_workflow_step,
        extract_write_phase,
    )
    return build_task_context_capsule, extract_actor_role, extract_workflow_id, extract_workflow_step, extract_write_phase


def test_extract_actor_role_present() -> None:
    _, extract_actor_role, *_ = _import_helpers()
    body = "## Task 03: Add POST /api/sites handler\n<actor>user</actor>\n"
    assert extract_actor_role(body) == "user"


def test_extract_actor_role_missing_returns_none() -> None:
    _, extract_actor_role, *_ = _import_helpers()
    body = "## Task 03: Add POST /api/sites handler\n"
    assert extract_actor_role(body) is None


def test_extract_workflow_id_and_step() -> None:
    _, _, extract_workflow_id, extract_workflow_step, _ = _import_helpers()
    body = "<workflow>WF-001</workflow>\n<workflow-step>2</workflow-step>\n"
    assert extract_workflow_id(body) == "WF-001"
    assert extract_workflow_step(body) == 2


def test_extract_write_phase_create() -> None:
    *_, extract_write_phase = _import_helpers()
    assert extract_write_phase("<write-phase>create</write-phase>\n") == "create"


def test_extract_write_phase_invalid_returns_none() -> None:
    *_, extract_write_phase = _import_helpers()
    # Only create|update|delete|null are accepted
    assert extract_write_phase("<write-phase>banana</write-phase>\n") is None


def test_capsule_v2_includes_workflow_fields_when_tags_present(synthetic_phase: Path) -> None:
    build_task_context_capsule, *_ = _import_helpers()
    task_body = (
        "## Task 03: Add POST /api/sites handler\n"
        "<file-path>apps/api/src/sites/routes.ts</file-path>\n"
        "<actor>user</actor>\n"
        "<workflow>WF-001</workflow>\n"
        "<workflow-step>2</workflow-step>\n"
        "<write-phase>create</write-phase>\n"
    )
    capsule = build_task_context_capsule(
        phase_dir=synthetic_phase,
        task_num=3,
        task_context=task_body,
        contract_context="POST /api/sites\n",
        goals_context="G-04",
        crud_surface_context="sites",
        sibling_context="none",
        downstream_callers="none",
        design_context="none",
        build_config={"phase": "N1"},
    )
    assert capsule["capsule_version"] == "2"
    assert capsule["actor_role"] == "user"
    assert capsule["workflow_id"] == "WF-001"
    assert capsule["workflow_step"] == 2
    assert capsule["write_phase"] == "create"
    # execution_contract additions
    assert capsule["execution_contract"]["must_match_workflow_state"] is True
    assert capsule["execution_contract"]["actor_role_hint"] == "user"
    # anti_lazy_read_rules — 2 new entries
    rules = capsule["anti_lazy_read_rules"]
    assert any("WORKFLOW-SPECS" in r for r in rules), \
        "anti_lazy_read_rules must add workflow-spec read rule"
    assert any("state_machine.states" in r for r in rules), \
        "anti_lazy_read_rules must enforce state-name discipline"


def test_capsule_v2_null_fields_when_tags_absent(synthetic_phase: Path) -> None:
    build_task_context_capsule, *_ = _import_helpers()
    task_body = (
        "## Task 99: Migration script\n"
        "<file-path>scripts/migrate-2026.sql</file-path>\n"
    )
    capsule = build_task_context_capsule(
        phase_dir=synthetic_phase,
        task_num=99,
        task_context=task_body,
        contract_context="",
        goals_context="",
        crud_surface_context="none",
        sibling_context="none",
        downstream_callers="none",
        design_context="none",
        build_config={"phase": "N1"},
    )
    assert capsule["capsule_version"] == "2"
    assert capsule["actor_role"] is None
    assert capsule["workflow_id"] is None
    assert capsule["workflow_step"] is None
    assert capsule["write_phase"] is None
    assert capsule["execution_contract"]["must_match_workflow_state"] is False
    assert capsule["execution_contract"]["actor_role_hint"] in ("", None)


def test_plan_delegation_md_documents_tag_conventions() -> None:
    plan_del = REPO / "commands/vg/_shared/blueprint/plan-delegation.md"
    text = plan_del.read_text(encoding="utf-8")
    for tag in ("<actor>", "<workflow>", "<workflow-step>", "<write-phase>"):
        assert tag in text, f"plan-delegation.md must document tag: {tag}"
    # Must enumerate valid actor + write_phase values
    assert "user" in text and "admin" in text
    assert "create" in text and "update" in text and "delete" in text
```

- [ ] **Step 2: Run failing test**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_capsule_workflow_fields.py -v
```

Expected: 8 FAILED.

- [ ] **Step 3: Add tag-extraction helpers + extend capsule in `pre-executor-check.py`**

Edit `scripts/pre-executor-check.py`. Add 4 helper functions above `build_task_context_capsule()` (around line 570):

```python
_ACTOR_ROLE_RE = re.compile(r"<actor>\s*([\w-]+)\s*</actor>")
_WORKFLOW_RE = re.compile(r"<workflow>\s*(WF-\d{1,3})\s*</workflow>")
_WORKFLOW_STEP_RE = re.compile(r"<workflow-step>\s*(\d{1,3})\s*</workflow-step>")
_WRITE_PHASE_RE = re.compile(r"<write-phase>\s*(create|update|delete)\s*</write-phase>")


def extract_actor_role(task_body: str) -> str | None:
    """Parse `<actor>...</actor>` from a PLAN task body. Returns None if absent."""
    m = _ACTOR_ROLE_RE.search(task_body)
    return m.group(1) if m else None


def extract_workflow_id(task_body: str) -> str | None:
    m = _WORKFLOW_RE.search(task_body)
    return m.group(1) if m else None


def extract_workflow_step(task_body: str) -> int | None:
    m = _WORKFLOW_STEP_RE.search(task_body)
    return int(m.group(1)) if m else None


def extract_write_phase(task_body: str) -> str | None:
    """Parse `<write-phase>create|update|delete</write-phase>`. Other values return None."""
    m = _WRITE_PHASE_RE.search(task_body)
    return m.group(1) if m else None
```

Modify `build_task_context_capsule()`. Update the `capsule = {...}` literal:

```python
    actor_role = extract_actor_role(task_context)
    workflow_id = extract_workflow_id(task_context)
    workflow_step = extract_workflow_step(task_context)
    write_phase = extract_write_phase(task_context)
    must_match_workflow_state = workflow_id is not None

    capsule = {
        "capsule_version": "2",          # was "1"; Task 41 schema bump
        "phase": build_config.get("phase"),
        "task_num": task_num,
        "task_title": next((line.strip("# ").strip() for line in task_context.splitlines() if line.strip()), ""),
        "source_artifacts": source_artifacts,
        "context_refs": _extract_context_refs(task_context),
        "goals": _extract_goal_ids(task_context, goals_context),
        "endpoints": endpoints,
        "file_paths": _extract_file_paths(task_context),
        # Task 41 — actor + workflow + write_phase awareness (M1)
        "actor_role": actor_role,
        "workflow_id": workflow_id,
        "workflow_step": workflow_step,
        "write_phase": write_phase,
        "required_context": {
            ...existing nested fields...,
        },
        "execution_contract": {
            ...existing flags...,
            # Task 41 additions
            "must_match_workflow_state": must_match_workflow_state,
            "actor_role_hint": actor_role or "",
        },
        "anti_lazy_read_rules": [
            ...existing rules...,
            # Task 41 — 2 new rules
            "If workflow_id is set, read WORKFLOW-SPECS/<workflow_id>.md slice and verify your code matches the state_after declaration for your step_id.",
            "Do NOT invent state names — use exact strings from state_machine.states[].",
        ],
    }
```

(Preserve the existing fields exactly — only ADD the 4 new top-level keys + 2 execution_contract entries + 2 anti_lazy_read_rules. Do not remove anything.)

- [ ] **Step 4: Update `commands/vg/_shared/blueprint/plan-delegation.md` — document PLAN task tag conventions**

Edit `commands/vg/_shared/blueprint/plan-delegation.md`. Locate the section where existing tags (`<file-path>`, `<goal>`, etc.) are documented, then add this section:

```markdown
## Task 41 — Multi-actor + workflow tags (M1)

Tasks that participate in cross-actor workflows MUST declare these
optional tags within the task body. Missing tags = single-actor /
non-workflow task (legacy default, backward-compat).

| Tag | Values | Required when |
|---|---|---|
| `<actor>` | `user`, `admin`, `system`, or other custom role | Task is one half of a cross-role workflow (e.g., user-side `Create` paired with admin-side `Approve`). Subagent uses for cred fixture selection. |
| `<workflow>` | `WF-NN` (3-digit) | Task is referenced in `WORKFLOW-SPECS/WF-NN.md`. Must match the file ID exactly. |
| `<workflow-step>` | integer | Step index within the workflow. Matches `steps[].step_id` in the WF spec. |
| `<write-phase>` | `create` / `update` / `delete` | Task implements a single write op. Used by Task 41 capsule + Task 42 wave-context cross-wave references. (Distinct from Task 39 RCRURDR `lifecycle_phases[]` — that schema covers 7 ops in one cycle.) |

### Example

```markdown
## Task 03: Add POST /api/sites handler (user-side create)

<file-path>apps/api/src/modules/sites/routes.ts</file-path>
<actor>user</actor>
<workflow>WF-001</workflow>
<workflow-step>2</workflow-step>
<write-phase>create</write-phase>
<goal>G-04</goal>
```

### Validator behavior

- Unknown `<actor>` value: stored as-is (validator does not enforce a closed enum — projects may add custom roles).
- Unknown `<write-phase>` value: parser returns `None`; capsule `write_phase` is null. Plan-checker emits warn-tier event `plan.unknown_write_phase`.
- `<workflow>` references a non-existent `WF-NN.md`: validator BLOCKs at blueprint close (`WORKFLOW-SPECS` consistency check).
```

- [ ] **Step 5: Run all task-41 tests — verify GREEN**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_capsule_workflow_fields.py -v
```

Expected: 8 PASSED.

- [ ] **Step 6: Verify nothing broke for existing capsule users**

Run full pre-executor-check test suite:

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/ -k "pre_executor_check or capsule" -v
```

Expected: all PASSED. If a legacy test asserts `capsule_version == "1"`, update it to `"2"` and add a comment `# Task 41 schema bump`. Legacy tests must NOT assert absence of `actor_role` etc. — those keys now always exist (null when absent).

- [ ] **Step 7: Sync + commit**

```bash
DEV_ROOT=. bash sync.sh --no-global 2>&1 | tail -3
git add scripts/pre-executor-check.py \
        commands/vg/_shared/blueprint/plan-delegation.md \
        tests/test_capsule_workflow_fields.py \
        .claude/ codex-skills/ .codex/
git commit -m "feat(build): capsule extension — actor + workflow + write_phase (Task 41, Bug I, M1)

Build subagents previously had no way to know 'I'm USER half of G-04
implementing step 2 of WF-001'. Without that context, user-side and
admin-side code drift even when both pass typecheck/build/tests in
isolation.

capsule_version bump: '1' → '2'. New top-level fields:
- actor_role: user|admin|system|null (from PLAN <actor> tag)
- workflow_id: WF-NN|null (from <workflow>)
- workflow_step: int|null (from <workflow-step>)
- write_phase: create|update|delete|null (from <write-phase>)

execution_contract additions:
- must_match_workflow_state: True when workflow_id != None
- actor_role_hint: subagent uses for cred fixture selection

anti_lazy_read_rules additions (2 new):
- 'If workflow_id is set, read WORKFLOW-SPECS/<workflow_id>.md...'
- 'Do NOT invent state names — use exact strings from state_machine.states[]'

Codex round-2 Amendment B locked write_phase rename: distinct from
Task 39 RCRURDR lifecycle_phases[] (7 ops in one cycle). write_phase
is single-write classifier; lifecycle_phases is full RCRURDR cycle.

Backward-compat: v1 capsules tolerated; missing PLAN tags = null fields.
Legacy capsule readers continue to work (existing fields unchanged).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
