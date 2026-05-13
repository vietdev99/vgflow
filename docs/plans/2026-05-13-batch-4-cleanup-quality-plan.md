# Batch 4 — Cleanup quality + subagent strict schema (G1+G4+G5+G6+H10+C6+C7) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 7 gaps in 4 buckets:
- **Lifecycle generator quality** (G1, G4, G5, G6): preconditions, actor inference, fixture DAG, artifact capture each pull from goal/context data instead of templates
- **Reflector visibility** (H10): vg-reflector output preserved as artifact
- **Subagent strict schema** (C6, C7): goal-verifier + codegen post-spawn validation reconciles against vg-load index, files-exist checks

**Tech Stack:** Python + bash.

**Working directory:** `main`.

---

## Conventions

- Python: `from __future__ import annotations`
- Mirror byte-identical to `.claude/`
- Regression sweep: `python -m pytest tests/ -q --tb=no -k "g1 or g4 or g5 or g6 or h10 or c6 or c7 or lifecycle or codegen or goal_verif or reflector"`
- Single Co-Authored-By trailer per commit

---

## Task 1: G1+G4+G5+G6 — Lifecycle generator quality

**Files:**
- Modify: `scripts/generate-lifecycle-specs.py`
- Mirror: `.claude/scripts/generate-lifecycle-specs.py`
- Test: `tests/test_g1_g4_g5_g6_lifecycle_quality.py`

**Step 1: Failing test**

```python
"""tests/test_g1_g4_g5_g6_lifecycle_quality.py — Batch 4 lifecycle quality."""
from __future__ import annotations
import json
import subprocess
import sys
import os
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
GEN = REPO / "scripts" / "generate-lifecycle-specs.py"


def _gen(tmp_path, goals_md):
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text(goals_md, encoding="utf-8")
    out = phase_dir / "LIFECYCLE-SPECS.json"
    r = subprocess.run(
        [sys.executable, str(GEN), "--phase", "99", "--phase-dir", str(phase_dir),
         "--out", str(out)],
        capture_output=True, text=True, env={**os.environ, "VG_REPO_ROOT": str(tmp_path)},
    )
    assert r.returncode == 0, r.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_g1_preconditions_pull_from_dependencies(tmp_path):
    """G1: preconditions derived from goal.dependencies + infra_deps, not hardcoded 4-bullet."""
    goals = """## Goal G-01: User creates order

**goal_type:** create-only
**Surface:** api
**mutation_evidence:** POST /api/orders
**dependencies:** active session, payment provider connected, product catalog seeded
**infra_deps:** redis, postgres
"""
    spec = _gen(tmp_path, goals)
    goal = spec["goals"]["G-01"]
    preconds = goal.get("preconditions", [])
    # Must derive from dependencies + infra_deps, not be the 4-line boilerplate
    txt = "\n".join(str(p) for p in preconds)
    assert "session" in txt.lower() or "payment provider" in txt.lower() or "product catalog" in txt.lower(), (
        "G1: preconditions must derive from goal.dependencies. Currently boilerplate."
    )


def test_g4_actor_inference_uses_metadata(tmp_path):
    """G4: actor inference reads explicit goal metadata (e.g. actors: ['admin','owner'])
    in preference to word-match heuristic."""
    goals = """## Goal G-02: Owner reviews subscription

**goal_type:** read-only
**actors:** owner, billing_admin
**Surface:** api
"""
    spec = _gen(tmp_path, goals)
    goal = spec["goals"]["G-02"]
    actor_ids = {a["id"] for a in goal.get("actors", [])}
    # Explicit metadata 'actors: owner, billing_admin' must produce both actors
    assert "owner" in actor_ids or "billing_admin" in actor_ids, (
        f"G4: explicit actors metadata must be honored. Got actors={actor_ids}"
    )


def test_g5_fixture_dag_from_dependencies(tmp_path):
    """G5: fixture DAG built from goal.dependencies graph, not 2-template hardcode."""
    goals = """## Goal G-01: Foundation goal

**goal_type:** create-only
**dependencies:** baseline_seeded

## Goal G-02: Depends on G-01

**goal_type:** create-only
**dependencies:** G-01
"""
    spec = _gen(tmp_path, goals)
    dag = spec.get("fixture_dag") or {}
    # DAG must reflect G-02 → G-01 edge
    edges_or_deps = json.dumps(dag).lower()
    assert "g-01" in edges_or_deps or "g-02" in edges_or_deps, (
        "G5: fixture_dag must reference goals by ID (G-01 depends on G-02 etc)"
    )


def test_g6_artifact_capture_per_kind(tmp_path):
    """G6: artifact_capture entries reflect goal artifact_kind field."""
    goals = """## Goal G-01: Export CSV

**goal_type:** read-only
**Surface:** api
**artifact_kind:** csv-download
"""
    spec = _gen(tmp_path, goals)
    goal = spec["goals"]["G-01"]
    artifact_capture = goal.get("artifact_capture", []) if isinstance(goal.get("artifact_capture"), list) else [goal.get("artifact_capture")]
    txt = json.dumps(artifact_capture).lower()
    assert "csv" in txt or "download" in txt or "artifact_kind" in txt, (
        "G6: artifact_capture must reference goal.artifact_kind (e.g. csv-download), "
        "not generic boilerplate entry"
    )
```

**Step 2: Run** → 4 fail (current generator uses templates).

**Step 3: Implement**

In `scripts/generate-lifecycle-specs.py`, add helpers and wire into `_goal_spec()`:

```python
# G1 Batch 4: preconditions from goal data
_PRECOND_BOILERPLATE = [
    "User has active session and required permissions",
    "Database is reachable and migrations applied",
    "Target endpoint is deployed at expected URL",
    "Required entities seeded per fixture_dag",
]


def _preconditions(goal: dict) -> list[str]:
    """Build preconditions list from goal.dependencies + infra_deps. Fallback to boilerplate."""
    deps = goal.get("dependencies") or ""
    infra = goal.get("infra_deps") or ""
    items: list[str] = []
    if deps:
        for d in (deps if isinstance(deps, list) else [s.strip() for s in str(deps).replace("\n", ",").split(",")]):
            if d and d.lower() not in ("none", "n/a"):
                items.append(f"Dependency: {d}")
    if infra:
        for d in (infra if isinstance(infra, list) else [s.strip() for s in str(infra).replace("\n", ",").split(",")]):
            if d:
                items.append(f"Infrastructure: {d} available")
    return items or list(_PRECOND_BOILERPLATE)


# G4 Batch 4: actor inference reads explicit metadata first
ACTOR_METADATA_KEYS = ("actors", "actor")


def _infer_actors_v2(goal: dict) -> list[dict]:
    """Read explicit actors metadata first; fall back to word-match heuristic."""
    explicit = None
    for k in ACTOR_METADATA_KEYS:
        v = goal.get(k)
        if v:
            explicit = v
            break
    if explicit:
        # parse comma-separated list or list-of-strings
        if isinstance(explicit, list):
            items = [str(x).strip() for x in explicit if str(x).strip()]
        else:
            items = [s.strip() for s in str(explicit).split(",") if s.strip()]
        actors = []
        seen = set()
        for item in items:
            aid = item.lower().replace(" ", "_")
            if aid in seen: continue
            seen.add(aid)
            actors.append({"id": aid, "role": item, "session": f"{aid}_session"})
        if actors:
            return actors
    # Fallback to existing _infer_actors() word-match
    return _infer_actors(goal)


# G5 Batch 4: fixture DAG from goal.dependencies cross-references
def _fixture_dag(goals_meta: list[dict]) -> dict:
    """Build fixture DAG from goal.dependencies field referencing other goal IDs."""
    nodes = []
    edges = []
    for g in goals_meta:
        gid = g.get("goal_id") or g.get("id")
        if not gid: continue
        nodes.append({"id": gid, "kind": g.get("goal_type", "mutation")})
        deps = g.get("dependencies") or ""
        deps_text = deps if isinstance(deps, str) else " ".join(deps)
        import re as _re
        for m in _re.finditer(r"\b(G-\d+)\b", deps_text):
            ref = m.group(1)
            if ref != gid:
                edges.append({"from": gid, "to": ref})
    return {"nodes": nodes, "edges": edges}


# G6 Batch 4: artifact_capture from goal.artifact_kind
def _artifact_capture(goal: dict) -> list[dict]:
    """Build artifact_capture entries reflecting goal.artifact_kind."""
    kind = (goal.get("artifact_kind") or "").strip().lower()
    if not kind:
        # Default capture: response body + screenshot for UI goals
        return [{"kind": "response_body", "ref": "stdout"}]
    # Specific captures by kind
    if "csv" in kind or "download" in kind:
        return [{"kind": "csv-download", "ref": "${PHASE_DIR}/.captures/${GOAL_ID}.csv"}]
    if "pdf" in kind:
        return [{"kind": "pdf-download", "ref": "${PHASE_DIR}/.captures/${GOAL_ID}.pdf"}]
    if "image" in kind or "screenshot" in kind:
        return [{"kind": "screenshot", "ref": "${PHASE_DIR}/.captures/${GOAL_ID}.png"}]
    if "json" in kind:
        return [{"kind": "json-export", "ref": "${PHASE_DIR}/.captures/${GOAL_ID}.json"}]
    return [{"kind": kind, "ref": f"${{PHASE_DIR}}/.captures/${{GOAL_ID}}.{kind}"}]
```

In `_goal_spec()` function, replace:
- `"preconditions": [...]` literal → `"preconditions": _preconditions(goal)`
- `"actors": _infer_actors(goal)` → `"actors": _infer_actors_v2(goal)`
- `"artifact_capture": [...]` literal → `"artifact_capture": _artifact_capture(goal)`

For G5, add fixture_dag at the spec root level (outside goals loop):
```python
spec = {
    "phase": ...,
    "goals": {...},
    "fixture_dag": _fixture_dag(goals_meta),
    ...
}
```

**Step 4-6:** pass + mirror + commit.

```bash
git add scripts/generate-lifecycle-specs.py \
        .claude/scripts/generate-lifecycle-specs.py \
        tests/test_g1_g4_g5_g6_lifecycle_quality.py
git commit -m "feat(lifecycle-specs): G1+G4+G5+G6 — lifecycle quality (Batch 4)

Audit Gaps G1, G4, G5, G6: lifecycle generator was filling 4 fields with
boilerplate templates instead of pulling from goal data.

Fixes:
- G1 preconditions: _preconditions() builds from goal.dependencies +
  infra_deps. Boilerplate is fallback when both empty.
- G4 actors: _infer_actors_v2() reads explicit goal.actors metadata
  first. Word-match heuristic only used as fallback.
- G5 fixture_dag: _fixture_dag() iterates goal.dependencies, extracts
  G-NN refs, builds nodes + edges. Replaces 2-template hardcode.
- G6 artifact_capture: _artifact_capture() reflects goal.artifact_kind
  (csv-download, pdf, screenshot, json, etc) with capture path slot.

Tests: tests/test_g1_g4_g5_g6_lifecycle_quality.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: H10 — vg-reflector output preserved

**Files:**
- Modify: `commands/vg/_shared/test/close.md` (reflector spawn + capture output)
- Mirror
- Test: `tests/test_h10_reflector_artifact.py`

**Step 1: Failing test**

```python
"""tests/test_h10_reflector_artifact.py — H10 reflector output preserved."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
CLOSE = REPO / "commands" / "vg" / "_shared" / "test" / "close.md"


def test_reflector_output_persists_to_artifact():
    body = CLOSE.read_text(encoding="utf-8")
    # Reflector spawn must write output to REFLECTION.md
    assert "REFLECTION.md" in body, (
        "H10: vg-reflector subagent output must persist to "
        "${PHASE_DIR}/REFLECTION.md as artifact"
    )


def test_reflector_skip_flag_documented():
    body = CLOSE.read_text(encoding="utf-8")
    # --skip-reflection flag documented
    assert "--skip-reflection" in body, (
        "H10: --skip-reflection flag must be documented to allow opting out"
    )
```

**Step 2: Run** → 2 fail (current close.md just spawns reflector without artifact path).

**Step 3: Implement**

In `commands/vg/_shared/test/close.md` around line 211 reflector spawn section, add:

```bash
# H10 Batch 4: persist reflector output to artifact
if echo "${ARGUMENTS:-}" | grep -q -- "--skip-reflection"; then
  echo "ℹ vg-reflector skipped (--skip-reflection flag)"
else
  REFLECTION_OUT="${PHASE_DIR}/REFLECTION.md"
  # ... existing reflector spawn ...
  # After spawn returns, write subagent narrative to REFLECTION_OUT:
  # vg-narrate-spawn.sh hooks log path; copy or render here
  if [ -f "${VG_TMP}/vg-reflector-${PHASE_NUMBER}.md" ]; then
    cp "${VG_TMP}/vg-reflector-${PHASE_NUMBER}.md" "$REFLECTION_OUT"
    echo "✓ Reflection captured: $REFLECTION_OUT"
  fi
fi
```

Update the reflector spawn prompt section to document `--skip-reflection`:

```markdown
## Reflection (--skip-reflection to disable)

End-of-test reflection: spawns vg-reflector subagent (isolated Haiku) to
extract lessons from the test cycle. Output persists to
`${PHASE_DIR}/REFLECTION.md` as a phase artifact.

To skip reflection entirely (e.g. CI runs that don't need lesson capture),
pass `--skip-reflection` in `$ARGUMENTS`.
```

**Step 4-6:** pass + mirror + commit.

```bash
git add commands/vg/_shared/test/close.md \
        .claude/commands/vg/_shared/test/close.md \
        tests/test_h10_reflector_artifact.py
git commit -m "feat(test): H10 — vg-reflector output persisted to REFLECTION.md (Batch 4)

Audit Gap H10 (LOW): test/close.md spawns vg-reflector subagent for
end-of-test reflection. Output was ambiguous — narration went to stdout
or transient tmp file. User had no easy way to view what AI reflected on.

Fix:
- Reflector output written to \${PHASE_DIR}/REFLECTION.md as committed
  phase artifact.
- --skip-reflection flag documented + supported to opt out (e.g. CI).
- Existing vg-narrate-spawn.sh log path serves as source.

Tests: tests/test_h10_reflector_artifact.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: C6 — goal-verifier strict schema validation

**Files:**
- Modify: `commands/vg/_shared/test/goal-verification/overview.md` (post-spawn validation block)
- Mirror
- Test: `tests/test_c6_goal_verifier_strict_schema.py`

**Step 1: Failing test**

```python
"""tests/test_c6_goal_verifier_strict_schema.py — C6 strict schema validation."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
OVERVIEW = REPO / "commands" / "vg" / "_shared" / "test" / "goal-verification" / "overview.md"


def test_post_spawn_validates_goal_ids_against_index():
    body = OVERVIEW.read_text(encoding="utf-8")
    # Must reference vg-load index reconciliation
    assert ("vg-load" in body or "GOAL_INDEX" in body or "goal_id_set" in body), (
        "C6: post-spawn validation must reconcile goals_verified[].goal_id "
        "against vg-load index (or equivalent goal ID source)"
    )


def test_post_spawn_validates_status_enum():
    body = OVERVIEW.read_text(encoding="utf-8")
    # Status must be in enum {PASSED, FAILED, BLOCKED, UNREACHABLE, SKIPPED}
    enum_present = all(s in body for s in ["PASSED", "FAILED"])
    assert enum_present, (
        "C6: post-spawn validation must enforce status enum"
    )
    # New: explicit STATUS_ENUM check
    assert ("STATUS_ENUM" in body or "valid_statuses" in body or "status_enum" in body), (
        "C6: must check status against an explicit enum, not just shape"
    )


def test_post_spawn_validates_evidence_ref_exists():
    body = OVERVIEW.read_text(encoding="utf-8")
    # Evidence ref path must be verified
    assert "evidence_ref" in body
    assert ("exists" in body.lower() and "evidence" in body.lower()) or "evidence_ref_missing" in body, (
        "C6: post-spawn validation must check evidence_ref file existence"
    )
```

**Step 2: Run** → 2-3 fail.

**Step 3: Implement**

In `commands/vg/_shared/test/goal-verification/overview.md` around line 159-183 (post-spawn validation block), replace the current shape-only check with:

```python
# C6 Batch 4: strict schema validation
STATUS_ENUM = {"PASSED", "FAILED", "BLOCKED", "UNREACHABLE", "SKIPPED", "TEST_PENDING"}

# 1. Goal IDs reconciliation against vg-load index
try:
    expected_ids = set(json.load(open("${PHASE_DIR}/GOAL-COVERAGE-MATRIX.json", encoding="utf-8")).get("goals", {}).keys())
except Exception:
    expected_ids = set()
returned_ids = {g.get("goal_id") for g in subagent_output.get("goals_verified", []) if g.get("goal_id")}
unknown_ids = returned_ids - expected_ids
if expected_ids and unknown_ids:
    print(f"⚠ C6: subagent returned unknown goal_ids: {unknown_ids}")

# 2. Status enum check
for g in subagent_output.get("goals_verified", []):
    s = g.get("status")
    if s not in STATUS_ENUM:
        print(f"⚠ C6: invalid status '{s}' for goal {g.get('goal_id')}")

# 3. evidence_ref existence check
for g in subagent_output.get("goals_verified", []):
    ev = g.get("evidence_ref")
    if ev and not Path(ev).is_file():
        print(f"⚠ C6: evidence_ref '{ev}' for goal {g.get('goal_id')} does not exist")
```

(In MD context, this becomes prose + a code block inside the existing validation section. Treat it as a documented contract — the harness orchestrator follows the prose.)

**Step 4-6:** pass + mirror + commit.

```bash
git add commands/vg/_shared/test/goal-verification/overview.md \
        .claude/commands/vg/_shared/test/goal-verification/overview.md \
        tests/test_c6_goal_verifier_strict_schema.py
git commit -m "feat(test): C6 — goal-verifier post-spawn strict schema (Batch 4)

Codex audit Gap C6 (HIGH): goal-verification/overview.md:159,183 post-
spawn validation checked only array length + presence of one boolean.
Subagent could return wrong goal IDs, invalid statuses, non-existent
evidence_ref and harness would still rewrite GOAL-COVERAGE-MATRIX.md +
emit telemetry.

Fix: strict schema validation block:
1. goal_id reconciliation vs GOAL-COVERAGE-MATRIX.json (expected_ids)
2. Status enum check (STATUS_ENUM = PASSED|FAILED|BLOCKED|UNREACHABLE|
   SKIPPED|TEST_PENDING)
3. evidence_ref file existence check

Each violation prints a warning. Returns still get processed but with
visible drift signal for downstream investigation.

Tests: tests/test_c6_goal_verifier_strict_schema.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: C7 — codegen post-spawn strict schema

**Files:**
- Modify: `commands/vg/_shared/test/codegen/overview.md` (post-spawn validation)
- Mirror
- Test: `tests/test_c7_codegen_strict_schema.py`

**Step 1: Failing test**

```python
"""tests/test_c7_codegen_strict_schema.py — C7 codegen strict schema."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
OVERVIEW = REPO / "commands" / "vg" / "_shared" / "test" / "codegen" / "overview.md"


def test_codegen_validates_files_exist_on_disk():
    body = OVERVIEW.read_text(encoding="utf-8")
    # Must verify every spec_files[] entry exists
    assert ("spec_files" in body) and ("Path(" in body or "exists" in body.lower() or "is_file" in body.lower()), (
        "C7: codegen post-spawn validation must verify each spec_files[] "
        "entry exists on disk"
    )


def test_codegen_reconciles_against_ready_goals():
    body = OVERVIEW.read_text(encoding="utf-8")
    # Must reconcile READY/MANUAL/DEFERRED goals against generated outputs
    assert ("READY" in body and "MANUAL" in body) or "goal_coverage" in body.lower(), (
        "C7: post-spawn validation must reconcile generated specs against "
        "READY/MANUAL/DEFERRED goal verdicts"
    )


def test_codegen_persists_binding_report():
    body = OVERVIEW.read_text(encoding="utf-8")
    # Must require binding_report artifact
    assert ("binding_report" in body or "BINDING-REPORT" in body or "bindings_satisfied" in body), (
        "C7: codegen must persist a binding report artifact, not just a "
        "bindings_satisfied boolean"
    )
```

**Step 2: Run** → likely 2 fail (existing has bindings_satisfied but no file-exists or coverage reconciliation).

**Step 3: Implement**

In `commands/vg/_shared/test/codegen/overview.md` around line 163-183, replace shape-only check with:

```python
# C7 Batch 4: strict schema validation for codegen subagent return

# 1. Files exist on disk
missing_files = []
for f in subagent_output.get("spec_files", []):
    fpath = Path(f) if Path(f).is_absolute() else Path("${PHASE_DIR}") / f
    if not fpath.is_file():
        missing_files.append(str(f))
if missing_files:
    raise ValueError(f"C7: codegen returned non-existent spec files: {missing_files}")

# 2. Coverage reconciliation against READY goals
try:
    matrix = json.load(open("${PHASE_DIR}/GOAL-COVERAGE-MATRIX.json", encoding="utf-8"))
    ready_goals = {gid for gid, g in matrix.get("goals", {}).items() if g.get("verdict") in ("READY", "READY_BEHAVIORAL", "READY_STRUCTURAL")}
except Exception:
    ready_goals = set()
covered_goals = set()
for f in subagent_output.get("spec_files", []):
    # Parse header for goal binding (e.g. // GOAL: G-01)
    try:
        head = (Path(f) if Path(f).is_absolute() else Path("${PHASE_DIR}") / f).read_text(encoding="utf-8")[:2000]
        import re
        for m in re.finditer(r"\bG-\d+\b", head):
            covered_goals.add(m.group(0))
    except Exception:
        pass
uncovered = ready_goals - covered_goals
if uncovered:
    print(f"⚠ C7: READY goals without generated spec: {uncovered}")

# 3. Persist binding report
binding_report = {
    "spec_files": list(subagent_output.get("spec_files", [])),
    "ready_goals": sorted(ready_goals),
    "covered_goals": sorted(covered_goals),
    "uncovered_goals": sorted(uncovered),
    "bindings_satisfied": bool(subagent_output.get("bindings_satisfied")),
}
Path("${PHASE_DIR}/CODEGEN-BINDING-REPORT.json").write_text(json.dumps(binding_report, indent=2), encoding="utf-8")
```

**Step 4-6:** pass + mirror + commit.

```bash
git add commands/vg/_shared/test/codegen/overview.md \
        .claude/commands/vg/_shared/test/codegen/overview.md \
        tests/test_c7_codegen_strict_schema.py
git commit -m "feat(test-spec): C7 — codegen post-spawn strict schema (Batch 4)

Codex audit Gap C7 (HIGH): codegen/overview.md:163,183 post-spawn check
was spec_files.length > 0 + bindings_satisfied presence. Subagent could
return one dummy spec, skip READY goals silently, and pass validation.

Fix: strict schema validation:
1. Verify every spec_files[] entry exists on disk; fail if any missing.
2. Reconcile against READY/READY_BEHAVIORAL/READY_STRUCTURAL goals from
   GOAL-COVERAGE-MATRIX.json. Parse spec file headers for G-NN refs.
   Print warning for uncovered READY goals.
3. Persist CODEGEN-BINDING-REPORT.json artifact with full coverage map
   (ready/covered/uncovered + bindings_satisfied flag).

Tests: tests/test_c7_codegen_strict_schema.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Regression sweep + release v4.9.0

Bump VERSION 4.8.0 → 4.9.0. CHANGELOG entry per 7 gaps closed. Tag v4.9.0. Push. Re-sync ~/.vgflow for: generate-lifecycle-specs.py, test/close.md, test/goal-verification/overview.md, test/codegen/overview.md.

End of Batch 4 plan. Estimated 4 hours.
