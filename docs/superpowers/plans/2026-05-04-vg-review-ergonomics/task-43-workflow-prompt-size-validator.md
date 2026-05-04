<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-04-vg-review-ergonomics.md -->
<!-- Spec: docs/superpowers/specs/2026-05-04-vg-review-ergonomics-design.md (Bug K lines 650-696) -->

## Task 43: Subagent `<workflow_context>` prompt block + per-slice ≤5K-token size BLOCK validator (M3)

**Files:**
- Create: `scripts/validators/verify-artifact-slice-size.py`
- Modify: `requirements.txt` (add `tiktoken>=0.7` — MANDATORY per Codex round-2 Amendment C)
- Modify: `commands/vg/_shared/build/waves-delegation.md` (add `<workflow_context>` block + variable resolution doc)
- Modify: `commands/vg/_shared/blueprint/close.md` (run `verify-artifact-slice-size.py`)
- Modify: `commands/vg/_shared/build/preflight.md` (run `verify-artifact-slice-size.py`)
- Modify: `commands/vg/blueprint.md` (declare `blueprint.slice_size_blocked` telemetry event)
- Modify: `commands/vg/build.md` (declare `build.workflow_state_drift_detected` telemetry event)
- Test: `tests/test_artifact_slice_size_validator.py`
- Test: `tests/test_workflow_context_prompt_block.py`

**Why:**

**(a) `<workflow_context>` prompt gap** — `commands/vg/_shared/build/waves-delegation.md` prompt template has 11 blocks (`<vg_executor_rules>`, `<bootstrap_rules>`, `<build_config>`, `<task_context_capsule>`, `<task_plan_slice>`, `<edge_cases_for_goals>`, `<contract_context>`, `<interface_standards_context>`, `<wave_context>`, `<design_context>`, `<binding_requirements>`). NONE load workflow spec automatically. Subagent must remember to call `vg-load --artifact workflow` — and won't, when capsule says workflow_id but prompt doesn't surface it.

**(b) Slice size silent growth** — `scripts/validators/verify-blueprint-split-size.py` exists but flags 30 KB warn (advisory, not BLOCK). Per-task / per-goal / per-endpoint / per-resource / per-workflow slices can grow silently past the empirical 5K-token AI-skim boundary, causing subagent to skim and miss content past its read window.

**Tiktoken mandatory** (Codex round-2 Amendment C): VG is Vietnamese-first. Naive `len(content) / 4` heuristic UNDERESTIMATES tokens by ~50% for Vietnamese diacritics (real ratio ≈ 2 chars/token, not 4). Subagent prompt could exceed real 5K-token budget while heuristic-validator says "OK 4K". Cannot ship a fallback that silently misjudges Vietnamese content.

**Cross-task contract recap (locked):**
- Per-unit slice rules (BLOCK):
  - ≤ 5K tokens per per-unit slice (`PLAN/task-NN.md`, `API-CONTRACTS/<slug>.md`, `TEST-GOALS/G-NN.md`, `CRUD-SURFACES/<resource>.md`, `WORKFLOW-SPECS/WF-NN.md`)
  - ≤ 1K tokens per index file
- `--allow-oversized-slice --override-reason="..."` escape with override-debt
- Tiktoken import at module load — `ImportError` = loud fail, blueprint close BLOCKs with fix-path "pip install tiktoken"
- `<workflow_context>` block format: `${WORKFLOW_SLICE_BLOCK}` substituted to `@${workflow_slice_path}` when capsule.workflow_id present, else literal `NONE — non-workflow task`

---

- [ ] **Step 1: Add tiktoken to requirements.txt**

Edit `requirements.txt`. Add line:

```
# Task 43 (Bug K, M3) — MANDATORY for Vietnamese-aware token counting
tiktoken>=0.7
```

Run install:

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
pip install tiktoken
```

- [ ] **Step 2: Write failing test for slice-size validator**

Create `tests/test_artifact_slice_size_validator.py`:

```python
"""Task 43 — verify per-slice ≤5K-token BLOCK validator.

Pin: oversized slice (>5K tokens) BLOCKs at default. --allow-oversized-slice
+ --override-reason escapes BLOCK with override-debt entry. Index files
have stricter ≤1K-token budget.

Tiktoken is MANDATORY (Codex round-2 Amendment C); ImportError on missing
package is a deliberate loud-fail.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "scripts/validators/verify-artifact-slice-size.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(VALIDATOR), *args],
        cwd=cwd, capture_output=True, text=True,
    )


def test_small_slice_passes(tmp_path: Path) -> None:
    phase = tmp_path / "phase"
    plan = phase / "PLAN"
    plan.mkdir(parents=True)
    (plan / "task-01.md").write_text("# Task 01\nSmall content.\n", encoding="utf-8")
    (plan / "index.md").write_text("# index\n- task-01\n", encoding="utf-8")

    result = _run(["--phase-dir", str(phase)], REPO)
    assert result.returncode == 0, f"got: {result.stdout}\n{result.stderr}"


def test_oversized_per_unit_slice_blocks(tmp_path: Path) -> None:
    phase = tmp_path / "phase"
    plan = phase / "PLAN"
    plan.mkdir(parents=True)
    # ~30K chars ≈ 6-15K tokens depending on tokenizer + content; exceeds 5K limit
    big = ("Very long English content. " * 1500)
    (plan / "task-99.md").write_text(big, encoding="utf-8")
    (plan / "index.md").write_text("# index\n- task-99\n", encoding="utf-8")

    result = _run(["--phase-dir", str(phase)], REPO)
    assert result.returncode != 0
    assert "task-99" in result.stdout + result.stderr
    assert "5000" in result.stdout + result.stderr or "5K" in result.stdout + result.stderr


def test_oversized_index_file_blocks(tmp_path: Path) -> None:
    phase = tmp_path / "phase"
    plan = phase / "PLAN"
    plan.mkdir(parents=True)
    (plan / "task-01.md").write_text("# small\n", encoding="utf-8")
    # Index files have stricter 1K-token limit
    big_index = ("Lorem ipsum dolor sit amet. " * 600)
    (plan / "index.md").write_text(big_index, encoding="utf-8")

    result = _run(["--phase-dir", str(phase)], REPO)
    assert result.returncode != 0
    assert "index.md" in result.stdout + result.stderr


def test_allow_oversized_with_override_reason(tmp_path: Path) -> None:
    phase = tmp_path / "phase"
    plan = phase / "PLAN"
    plan.mkdir(parents=True)
    big = ("Very long content. " * 1500)
    (plan / "task-99.md").write_text(big, encoding="utf-8")
    (plan / "index.md").write_text("# small\n", encoding="utf-8")
    debt_path = tmp_path / "override-debt.json"

    result = _run(
        [
            "--phase-dir", str(phase),
            "--allow-oversized-slice",
            "--override-reason", "PV3 4.1 legacy slice — Task 43 grace window",
            "--override-debt-path", str(debt_path),
        ],
        REPO,
    )
    assert result.returncode == 0, result.stderr
    assert debt_path.exists()
    debt = json.loads(debt_path.read_text(encoding="utf-8"))
    assert debt["scope"] == "artifact-slice-oversized"
    assert debt["reason"]


def test_vietnamese_text_uses_tiktoken_not_char_heuristic(tmp_path: Path) -> None:
    """Vietnamese diacritics: 2 chars/token. Heuristic (4 chars/token) would underestimate.

    A 12K-char Vietnamese block is ~6K tokens (real) but only 3K via heuristic.
    The validator MUST flag this as oversized."""
    phase = tmp_path / "phase"
    api = phase / "API-CONTRACTS"
    api.mkdir(parents=True)
    # Vietnamese phrase repeated; ~12K chars
    vn = "Sếp đang dogfood quy trình duyệt nội dung mỗi ngày. " * 230
    (api / "post-api-content.md").write_text(vn, encoding="utf-8")
    (api / "index.md").write_text("# api index\n", encoding="utf-8")

    result = _run(["--phase-dir", str(phase)], REPO)
    # Vietnamese tokenizes denser; 12K chars ≈ 6K tokens — should BLOCK
    assert result.returncode != 0, "Vietnamese 12K chars must BLOCK at ≤5K tokens"


def test_tiktoken_import_loud_fail_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If tiktoken is uninstalled, validator MUST exit with ImportError-derived BLOCK.

    Test by spawning python with PYTHONPATH that hides tiktoken (via --hide-tiktoken stub flag).
    """
    phase = tmp_path / "phase"
    (phase / "PLAN").mkdir(parents=True)
    (phase / "PLAN" / "task-01.md").write_text("# small\n", encoding="utf-8")
    (phase / "PLAN" / "index.md").write_text("# small\n", encoding="utf-8")

    # Run with a hidden-tiktoken environment by inserting a fake tiktoken module that raises.
    fake_pkg = tmp_path / "fake_pkg"
    (fake_pkg / "tiktoken").mkdir(parents=True)
    (fake_pkg / "tiktoken" / "__init__.py").write_text(
        "raise ImportError('tiktoken simulated missing')\n", encoding="utf-8"
    )
    env = {"PYTHONPATH": str(fake_pkg), "PATH": __import__("os").environ.get("PATH", "")}
    result = subprocess.run(
        ["python3", str(VALIDATOR), "--phase-dir", str(phase)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "tiktoken" in combined.lower()
    assert "pip install tiktoken" in combined or "install tiktoken" in combined.lower()
```

- [ ] **Step 3: Run failing test**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_artifact_slice_size_validator.py -v
```

Expected: 6 FAILED.

- [ ] **Step 4: Implement `scripts/validators/verify-artifact-slice-size.py`**

Create `scripts/validators/verify-artifact-slice-size.py`:

```python
#!/usr/bin/env python3
"""Task 43 — verify per-slice ≤5K-token BLOCK validator (Bug K, M3).

Scans all per-unit slice directories under ${PHASE_DIR}:
  - PLAN/task-NN.md
  - API-CONTRACTS/<slug>.md
  - TEST-GOALS/G-NN.md
  - CRUD-SURFACES/<resource>.md
  - WORKFLOW-SPECS/WF-NN.md
Plus index.md files in each of the above directories.

Token-counting: tiktoken cl100k_base (MANDATORY per Codex round-2
Amendment C). Naive char-heuristic underestimates Vietnamese content.

Exit codes:
- 0 = OK or override accepted
- 1 = BLOCK (oversized slice) or tiktoken-import failure
- 2 = wrong invocation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# MANDATORY import — loud-fail if missing.
try:
    import tiktoken
except ImportError as exc:
    sys.stderr.write(
        f"BLOCK: tiktoken is MANDATORY for slice-size validation.\n"
        f"  Reason: Vietnamese diacritics tokenize at ~2 chars/token; the\n"
        f"  naive char-count heuristic underestimates real token count by\n"
        f"  ~50%, allowing oversized prompts to slip past as 'OK'.\n"
        f"  Fix: pip install tiktoken>=0.7\n"
        f"  Underlying error: {exc}\n"
    )
    sys.exit(1)


_ENCODING = tiktoken.get_encoding("cl100k_base")

PER_UNIT_LIMIT = 5000
INDEX_LIMIT = 1000

SLICE_DIRS = (
    ("PLAN", "task-*.md"),
    ("API-CONTRACTS", "*.md"),
    ("TEST-GOALS", "G-*.md"),
    ("CRUD-SURFACES", "*.md"),
    ("WORKFLOW-SPECS", "WF-*.md"),
)


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _scan(phase_dir: Path) -> list[tuple[Path, int, int]]:
    """Return list of (file, token_count, limit) for files exceeding their limit."""
    findings: list[tuple[Path, int, int]] = []
    for sub, pattern in SLICE_DIRS:
        d = phase_dir / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob(pattern)):
            if f.name == "index.md":
                continue
            tokens = _count_tokens(f.read_text(encoding="utf-8"))
            if tokens > PER_UNIT_LIMIT:
                findings.append((f, tokens, PER_UNIT_LIMIT))
        idx = d / "index.md"
        if idx.exists():
            tokens = _count_tokens(idx.read_text(encoding="utf-8"))
            if tokens > INDEX_LIMIT:
                findings.append((idx, tokens, INDEX_LIMIT))
    return findings


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--phase-dir", required=True)
    p.add_argument("--allow-oversized-slice", action="store_true")
    p.add_argument("--override-reason", default="")
    p.add_argument("--override-debt-path", default="")
    args = p.parse_args()

    phase_dir = Path(args.phase_dir)
    if not phase_dir.is_dir():
        print(f"ERROR: --phase-dir not a directory: {phase_dir}", file=sys.stderr)
        return 2

    findings = _scan(phase_dir)
    if not findings:
        return 0

    if args.allow_oversized_slice:
        if not args.override_reason:
            print("ERROR: --allow-oversized-slice requires --override-reason", file=sys.stderr)
            return 2
        debt = {
            "scope": "artifact-slice-oversized",
            "reason": args.override_reason,
            "findings": [
                {"path": str(f.relative_to(phase_dir)), "tokens": tokens, "limit": limit}
                for f, tokens, limit in findings
            ],
        }
        if args.override_debt_path:
            Path(args.override_debt_path).write_text(json.dumps(debt, indent=2), encoding="utf-8")
        print(f"OVERRIDE accepted ({len(findings)} oversized slices logged to override-debt)")
        return 0

    print("BLOCK: artifact slice size violations:")
    for f, tokens, limit in findings:
        rel = f.relative_to(phase_dir)
        print(f"  - {rel}: {tokens} tokens > {limit} limit")
    print("Fix: split the slice into smaller units, OR pass --allow-oversized-slice "
          "--override-reason='<text>' for legacy phases.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

```bash
chmod +x scripts/validators/verify-artifact-slice-size.py
```

- [ ] **Step 5: Run validator tests — verify GREEN**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_artifact_slice_size_validator.py -v
```

Expected: 6 PASSED.

- [ ] **Step 6: Write failing test for `<workflow_context>` prompt block**

Create `tests/test_workflow_context_prompt_block.py`:

```python
"""Task 43 — verify <workflow_context> block in waves-delegation.md prompt template.

Pin: prompt template MUST declare a <workflow_context> block that
substitutes ${WORKFLOW_SLICE_BLOCK}. Orchestrator resolves to either
@${workflow_slice_path} (when capsule.workflow_id present) or literal
NONE string (when null).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WAVES_DEL = REPO / "commands/vg/_shared/build/waves-delegation.md"
BUILD_MD = REPO / "commands/vg/build.md"


def test_workflow_context_block_present() -> None:
    text = WAVES_DEL.read_text(encoding="utf-8")
    assert "<workflow_context>" in text and "</workflow_context>" in text, \
        "waves-delegation.md prompt template must contain <workflow_context> block"


def test_workflow_slice_block_substitution_documented() -> None:
    text = WAVES_DEL.read_text(encoding="utf-8")
    assert "${WORKFLOW_SLICE_BLOCK}" in text, \
        "block must use ${WORKFLOW_SLICE_BLOCK} substitution token"


def test_documents_none_fallback_for_non_workflow_tasks() -> None:
    text = WAVES_DEL.read_text(encoding="utf-8")
    # Should mention literal NONE substitution when workflow_id is null
    pattern = r"workflow_id\s*(?:==|is)?\s*null|non-workflow task"
    assert re.search(pattern, text, re.IGNORECASE), \
        "must document NONE substitution behavior when capsule.workflow_id is null"


def test_block_instructs_state_after_discipline() -> None:
    text = WAVES_DEL.read_text(encoding="utf-8")
    # Block must tell subagent to honor state_after declarations from WF spec
    assert "state_after" in text, \
        "block must instruct subagent to honor state_after declarations"


def test_workflow_state_drift_telemetry_declared() -> None:
    text = BUILD_MD.read_text(encoding="utf-8")
    assert "build.workflow_state_drift_detected" in text, \
        "build.md must declare workflow_state_drift_detected telemetry event"
```

- [ ] **Step 7: Run failing test**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_workflow_context_prompt_block.py -v
```

Expected: 5 FAILED.

- [ ] **Step 8: Add `<workflow_context>` block to `waves-delegation.md`**

Edit `commands/vg/_shared/build/waves-delegation.md`. Locate the existing prompt-template block list (after `<wave_context>` and before `<binding_requirements>`). Insert this NEW block:

```
<workflow_context>
# Task 43 (Bug K, M3) — multi-actor workflow awareness.
# When capsule.workflow_id is present, the orchestrator substitutes
# ${WORKFLOW_SLICE_BLOCK} with @${workflow_slice_path} (the per-workflow
# WF-NN.md file produced by Pass 3 in Task 40). When workflow_id is null,
# the substitution is the literal string "NONE — non-workflow task" and
# subagent skips workflow verification.
#
# When loaded, you MUST:
# 1. Read the workflow spec to identify your step's expected `state_after`
#    value (under steps[step_id == capsule.workflow_step].state_after).
# 2. Verify your code matches that exact state value when implementing
#    a write (status fields, enum values, transition labels). DO NOT
#    invent a new state name — use the literal string from the spec.
# 3. Cred-switch boundaries are FE codegen concerns (handled by Playwright
#    testRoleSwitch() in tests). YOUR backend/frontend code MUST set the
#    state field to the value declared at this step's state_after.
# 4. Cross-actor siblings (other waves) read or write related states.
#    The wave-context.md `Cross-WORKFLOW constraint:` section (Task 42)
#    enumerates them. Honor those constraints in your design choices.
${WORKFLOW_SLICE_BLOCK}
</workflow_context>
```

Add a new field-semantics row (in the same table that documents `wave_context_path`, etc.):

```
| `workflow_slice_path` | maybe | `${PHASE_DIR}/WORKFLOW-SPECS/${capsule.workflow_id}.md` when capsule.workflow_id present, else NULL. Orchestrator pre-resolves before spawn. Subagent reads via `cat $workflow_slice_path` or via `vg-load --artifact workflow --workflow ${capsule.workflow_id}`. |
```

In the JSON envelope example, add:

```json
  "workflow_slice_path": "${PHASE_DIR}/WORKFLOW-SPECS/WF-001.md",
```

- [ ] **Step 9: Wire validator into `commands/vg/_shared/blueprint/close.md` + `commands/vg/_shared/build/preflight.md`**

In `close.md`, after the existing FE-contract + workflows validators (Tasks 38, 40), add:

```bash
python3 scripts/validators/verify-artifact-slice-size.py \
  --phase-dir "${PHASE_DIR}" \
  ${ALLOW_OVERSIZED_SLICE_FLAG}
rc=$?
if [ "$rc" -ne 0 ]; then
  vg-orchestrator emit-event blueprint.slice_size_blocked --phase "${PHASE_NUMBER}"
  echo "BLOCK: artifact slice size validator failed. Use --allow-oversized-slice for legacy phases." >&2
  exit "$rc"
fi
```

In `preflight.md` (build pipeline), add the SAME validator call as a defense-in-depth check — a phase that skipped blueprint close validation MUST be caught before build executor spawn:

```bash
python3 scripts/validators/verify-artifact-slice-size.py \
  --phase-dir "${PHASE_DIR}" \
  ${ALLOW_OVERSIZED_SLICE_FLAG}
rc=$?
if [ "$rc" -ne 0 ]; then
  vg-orchestrator emit-event build.slice_size_blocked --phase "${PHASE_NUMBER}"
  exit "$rc"
fi
```

- [ ] **Step 10: Add 2 telemetry events to slim entries**

Edit `commands/vg/blueprint.md` — add to `must_emit_telemetry`:

```yaml
    # Task 43 (M3) — slice-size validator
    - event_type: "blueprint.slice_size_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
```

Edit `commands/vg/build.md` — add:

```yaml
    # Task 43 (M3) — workflow state drift detection (post-execution validator)
    - event_type: "build.workflow_state_drift_detected"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
```

The `build.workflow_state_drift_detected` event is emitted by post-execution analysis when a subagent's commit `state_after` value doesn't match the WORKFLOW-SPECS declaration for that step. Implementation hook: Task 23 review runtime gate (already exists) extended to compare commit-level state strings against WF spec when capsule has `workflow_id` + `workflow_step`. Implementation detail: the comparator runs as part of the existing `verify-rcrurd-runtime.py` (Task 23 surface) — add a parallel check that reads the capsule + opens the matching `WORKFLOW-SPECS/<wf>.md` and asserts no drift.

- [ ] **Step 11: Run all task-43 tests — verify GREEN**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_artifact_slice_size_validator.py tests/test_workflow_context_prompt_block.py -v
```

Expected: 11 PASSED.

- [ ] **Step 12: Sync + commit**

```bash
DEV_ROOT=. bash sync.sh --no-global 2>&1 | tail -3
git add scripts/validators/verify-artifact-slice-size.py \
        commands/vg/_shared/build/waves-delegation.md \
        commands/vg/_shared/blueprint/close.md \
        commands/vg/_shared/build/preflight.md \
        commands/vg/blueprint.md \
        commands/vg/build.md \
        requirements.txt \
        tests/test_artifact_slice_size_validator.py \
        tests/test_workflow_context_prompt_block.py \
        .claude/ codex-skills/ .codex/
git commit -m "feat(build): <workflow_context> prompt block + per-slice ≤5K-token BLOCK (Task 43, Bug K, M3)

Two coordinated fixes for build subagent multi-actor coordination:

(a) <workflow_context> prompt block — waves-delegation.md prompt template
had 11 blocks but NONE loaded workflow spec automatically. Subagent
relied on remembering to call vg-load --artifact workflow, and didn't
when capsule said workflow_id but prompt didn't surface it. NEW block
substitutes \${WORKFLOW_SLICE_BLOCK} → @\${workflow_slice_path} when
capsule.workflow_id present, else literal 'NONE — non-workflow task'.

(b) Per-slice ≤5K-token BLOCK validator —
verify-artifact-slice-size.py scans PLAN/task-NN.md, API-CONTRACTS/*.md,
TEST-GOALS/G-NN.md, CRUD-SURFACES/*.md, WORKFLOW-SPECS/WF-NN.md +
index.md files. ≤5K tokens per per-unit slice; ≤1K tokens per index.
BLOCK on violation. --allow-oversized-slice escape with override-debt.

Tiktoken MANDATORY (Codex round-2 Amendment C): VG is Vietnamese-first.
Naive char-heuristic underestimates Vietnamese tokens by ~50% (real
ratio ~2 chars/token vs heuristic 4 chars/token). ImportError on
missing tiktoken is a deliberate loud-fail, not silent fallback —
shipping a Vietnamese-blind validator would defeat the budget.

Telemetry: blueprint.slice_size_blocked (warn),
build.workflow_state_drift_detected (warn — emitted post-execution
when subagent commit state_after diverges from WORKFLOW-SPECS).

Wired into blueprint close.md + build preflight.md (defense in depth).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
