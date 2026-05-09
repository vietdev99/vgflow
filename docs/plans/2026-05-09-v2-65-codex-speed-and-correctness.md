# v2.65.0 — Codex Review Speed + State-Shortcut Hardening

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Fix 3 root causes identified in audits — Codex review slowness (sequential probes + inline path), state-shortcut bypass (deepscan default OFF + soft markers), Codex marker gap (8/39 markers due to no hook system).

**Architecture:** A1+A2 parallelize sequential loops via ThreadPoolExecutor. A3+A6 add codex-spawn dual-path so Codex doesn't run review inline. A4 tightens existing fix-loop iteration cap. A5 adds `parallel_workers` config knob. A7 flips deepscan default ON. A8 adds enforcement test for must_be_created_in_run + check_provenance. A9 adds explicit `vg-orchestrator emit-marker` calls to codex-skills to bypass missing hook system.

**Tech Stack:** Python 3 (concurrent.futures.ThreadPoolExecutor + pytest), Bash (codex-spawn.sh dual-path), Markdown (review.md + codex-skills SKILL.md).

---

## Context

User-confirmed audit findings:

1. **Codex review slow** — "phần review khi chạy trên codex, khá chậm...nó vẫn chạy inline mà không spawn ra subagent". Two sequential bottlenecks: lens probe dispatch (`scripts/spawn_recursive_probe.py` iterator) + API contract probe list comp (`scripts/review-api-contract-probe.py:312-313`). Plus inline path for codex-inline scanner runtime.

2. **State-shortcut bypass** — "chỉ đọc state là bỏ qua luôn deepscan trong khi còn cả 1 tá lỗi". Phase 2b-2 deepscan OPT-IN OFF since v2.42.4 (`commands/vg/review.md:3551-3577`). Markers severity=warn → reviews pass silently with stale state.

3. **Codex marker gap** — "Orchestrator chỉ thấy 8/39 vì hook không tự chạy trong Codex". Claude Code's PreToolUse/PostToolUse hooks auto-emit step markers. Codex has no hook system → 31/39 markers missing → contract validator fails.

4. **Fix-loop classification** — "phần review của codex...quét nhận ra lỗi nhưng lại không fix loop". Review fix-loop exists (review.md:5689-5759) but max 3 iterations + classifier may misclassify SPEC_GAP as CODE_BUG.

VERSION baseline: 2.64.1. Bump to 2.65.0.

---

## Task 1 (A1): Parallelize lens probe dispatch

**Files:**
- Modify: `scripts/spawn_recursive_probe.py` (add ThreadPoolExecutor branch when `--parallel N` flag set)
- Modify: `commands/vg/review.md:3878-3895` (pass `--parallel ${PARALLEL_WORKERS}` from config)
- Modify: `.claude/commands/vg/review.md` + `.claude/scripts/spawn_recursive_probe.py` (mirror)
- Test: `tests/test_recursive_probe_parallel.py` (NEW)

**Step 1: Write failing test**

```python
# tests/test_recursive_probe_parallel.py
import json, subprocess, time
from pathlib import Path

def test_parallel_dispatch_faster_than_sequential(tmp_path):
    """5 mock dispatches × 1s sleep each → sequential ≥5s, parallel(5) ≤2s."""
    dispatch_plan = tmp_path / "dispatch.json"
    dispatch_plan.write_text(json.dumps({
        "dispatches": [
            {"id": f"d{i}", "lens": "csrf", "clickable": f"btn{i}", "mock_sleep_s": 1.0}
            for i in range(5)
        ]
    }))
    
    # Sequential
    t0 = time.time()
    rc = subprocess.run([
        "python", "scripts/spawn_recursive_probe.py",
        "--dispatch-plan", str(dispatch_plan), "--mock-mode", "--parallel", "1"
    ]).returncode
    seq_dt = time.time() - t0
    assert rc == 0
    assert seq_dt >= 4.5, f"sequential too fast: {seq_dt}s"
    
    # Parallel(5)
    t0 = time.time()
    rc = subprocess.run([
        "python", "scripts/spawn_recursive_probe.py",
        "--dispatch-plan", str(dispatch_plan), "--mock-mode", "--parallel", "5"
    ]).returncode
    par_dt = time.time() - t0
    assert rc == 0
    assert par_dt <= 2.0, f"parallel too slow: {par_dt}s"
    assert par_dt < seq_dt / 2, f"speedup too low: seq={seq_dt} par={par_dt}"


def test_parallel_preserves_dispatch_order_in_output():
    """Output JSON must list dispatches in input order even when parallel-executed."""
    # ... write dispatch with explicit ids d0..d4
    # ... run --parallel 5
    # ... assert output[i].id == f"d{i}"
    ...


def test_parallel_default_disabled_back_compat():
    """Without --parallel flag, behaves exactly as v2.64.x (sequential)."""
    # Run without --parallel
    # Assert log line "sequential dispatch" present
    ...
```

**Step 2: Run test — expect FAIL** (`--mock-mode` and `--parallel` flags don't exist)

```bash
python -m pytest tests/test_recursive_probe_parallel.py -v
```

**Step 3: Implement**

Add to `scripts/spawn_recursive_probe.py`:

```python
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

def main():
    ap = argparse.ArgumentParser()
    # ... existing args ...
    ap.add_argument("--parallel", type=int, default=1, 
                    help="Max concurrent dispatches (default 1 = sequential)")
    ap.add_argument("--mock-mode", action="store_true",
                    help="Test mode: respects mock_sleep_s in dispatch entries")
    args = ap.parse_args()
    
    dispatches = load_dispatch_plan(args.dispatch_plan)
    
    if args.parallel <= 1:
        results = [execute_dispatch(d, args) for d in dispatches]
    else:
        results = [None] * len(dispatches)
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futures = {pool.submit(execute_dispatch, d, args): i 
                       for i, d in enumerate(dispatches)}
            for fut in as_completed(futures):
                idx = futures[fut]
                results[idx] = fut.result()
    
    # ... existing output write ...
```

Add `--parallel ${REVIEW_PARALLEL_WORKERS:-1}` to dispatch invocation in `review.md:3883`.

**Step 4: Run tests — expect PASS**

**Step 5: Mirror + commit**

```bash
cp scripts/spawn_recursive_probe.py .claude/scripts/spawn_recursive_probe.py
cp commands/vg/review.md .claude/commands/vg/review.md
git add scripts/spawn_recursive_probe.py .claude/scripts/spawn_recursive_probe.py \
        commands/vg/review.md .claude/commands/vg/review.md \
        tests/test_recursive_probe_parallel.py
git commit -m "perf(review): parallelize lens probe dispatch via ThreadPoolExecutor (A1)"
```

---

## Task 2 (A2): Parallelize API contract probe

**Files:**
- Modify: `scripts/review-api-contract-probe.py:312-313` (replace list comp with ThreadPoolExecutor)
- Mirror: `.claude/scripts/review-api-contract-probe.py`
- Test: `tests/test_api_contract_probe_parallel.py` (NEW)

**Step 1: Failing test**

```python
def test_api_probe_parallel_speedup(monkeypatch):
    from scripts.review_api_contract_probe import probe_endpoints
    
    sleeps = [1.0] * 5
    def mock_probe(*args, **kwargs):
        import time
        time.sleep(sleeps.pop(0) if sleeps else 0)
        return {"endpoint": kwargs.get("endpoint"), "status": "ok"}
    
    monkeypatch.setattr("scripts.review_api_contract_probe.probe_endpoint", mock_probe)
    
    endpoints = [{"path": f"/api/x{i}"} for i in range(5)]
    
    import time
    t0 = time.time()
    results = probe_endpoints(endpoints, base_url="http://x", parallel=5)
    par_dt = time.time() - t0
    
    assert len(results) == 5
    assert par_dt < 2.0, f"too slow: {par_dt}"


def test_api_probe_default_sequential():
    """parallel arg defaults to 1 — back-compat preserved."""
    ...
```

**Step 2-5:** Implement `probe_endpoints()` wrapper that branches on `parallel`. Replace `results = [probe_endpoint(...) for endpoint in endpoints]` at line 312-313. Mirror + commit.

```bash
git commit -m "perf(review): parallelize API contract probe via ThreadPoolExecutor (A2)"
```

---

## Task 3 (A3): codex-inline scanner — codex-spawn parallel option

**Files:**
- Modify: `commands/vg/review.md:985-1016` (add VG_RUNTIME=codex parallel branch)
- Modify: `commands/vg/review.md:3585-3595` (codex path contract update)
- Mirror: `.claude/commands/vg/review.md`
- Test: `tests/test_codex_inline_parallel.py` (smoke — assert review.md mentions codex-spawn parallel)

**Step 1: Failing test**

```python
def test_codex_inline_supports_parallel_spawn():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # Must mention codex-spawn dual-path for codex-inline
    assert "codex-spawn.sh --tier scanner" in body
    assert re.search(r"VG_RUNTIME.*codex.*parallel", body, re.IGNORECASE | re.DOTALL), \
        "codex-inline must support parallel codex-spawn fallback"
```

**Step 2: FAIL** (current text says "do NOT spawn Haiku on Codex")

**Step 3: Implement**

Update `commands/vg/review.md:985-1016`:

```markdown
**Codex runtime parallel scanner** (v2.65.0):
- Default codex-inline runs scanner sequentially in main orchestrator
- When `VG_RUNTIME=codex` AND `parallel_workers > 1` in vg.config:
  - Spawn N×`codex-spawn.sh --tier scanner --sandbox read-only` for non-MCP classification
  - MCP/browser actions stay in main Codex (codex-spawn cannot use MCP)
  - Each spawn: 1 scan-NN.json output → main orchestrator aggregates
```

**Step 4-5:** Mirror + commit

```bash
git commit -m "perf(review): codex-inline parallel scanner via codex-spawn fallback (A3)"
```

---

## Task 4 (A4): Review fix-loop iteration audit + tighten

**Files:**
- Modify: `commands/vg/review.md:5689-5759` (Phase 3 fix loop — bump max iterations from 3 to 5, add per-iteration progress event)
- Mirror
- Test: `tests/test_review_fix_loop_progress.py` (NEW)

**Step 1: Failing test**

```python
def test_fix_loop_emits_iteration_event():
    """Each fix loop iteration must emit review.fix_iteration_started event."""
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # Look for emit-event in fix loop region
    fix_loop_section = re.search(
        r"phase3_fix_loop.*?(?=phase\d|\Z)", body, re.DOTALL
    )
    assert fix_loop_section
    assert "review.fix_iteration_started" in fix_loop_section.group(0)


def test_fix_loop_max_iterations_5():
    """Max iter bumped from 3 to 5 to handle multi-class violations."""
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    m = re.search(r"max[\s_-]?iter(?:ations)?[\s:=]+(\d+)", body, re.IGNORECASE)
    assert m and int(m.group(1)) == 5
```

**Step 2-5:** Implement event emit per iteration. Bump iter cap. Mirror + commit.

```bash
git commit -m "feat(review): fix-loop max=5 iterations + per-iteration telemetry (A4)"
```

---

## Task 5 (A5): vg.config parallel_workers field

**Files:**
- Modify: `vg.config.template.md:401-419` (add parallel_workers under build/review sections)
- Modify: `commands/vg/review.md` (read CONFIG_PARALLEL_WORKERS env)
- Mirror in `.claude/templates/vg/vg.config.template.md`
- Test: `tests/test_parallel_workers_config.py` (NEW)

**Step 1: Failing test**

```python
def test_parallel_workers_in_template():
    body = Path("vg.config.template.md").read_text(encoding="utf-8")
    assert "parallel_workers:" in body, "template must declare parallel_workers field"
    assert re.search(r"parallel_workers:\s*\d+", body)


def test_parallel_workers_loaded_in_review():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    assert "PARALLEL_WORKERS" in body or "parallel_workers" in body
```

**Step 2-5:** Add to template:

```yaml
# v2.65.0 A5 — concurrent worker cap for parallelizable ops
# Applies to: A1 lens probe, A2 API contract probe, A3 codex-inline scanner
parallel_workers: 5
```

Read in review.md via grep parser. Mirror + commit.

```bash
git commit -m "feat(config): vg.config.md parallel_workers field for review parallelism (A5)"
```

---

## Task 6 (A6): Review fix-loop codex-spawn dual-path

**Files:**
- Modify: `commands/vg/review.md:5709-5759` (fix loop spawn agent — branch on VG_RUNTIME)
- Modify: `codex-skills/vg-build/SKILL.md:87-95` (codex-spawn-fix-agent mapping)
- Mirror
- Test: `tests/test_review_fix_loop_dual_path.py` (NEW)

**Step 1: Failing test**

```python
def test_fix_loop_codex_path_uses_codex_spawn():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # When VG_RUNTIME=codex, fix loop must use codex-spawn.sh, not Agent tool
    fix_loop_match = re.search(
        r"phase3_fix_loop.*?(?=phase\d|\Z)", body, re.DOTALL
    )
    assert fix_loop_match
    section = fix_loop_match.group(0)
    assert re.search(r"VG_RUNTIME.*codex.*codex-spawn\.sh", section, re.DOTALL), \
        "fix loop must dual-path: Claude=Agent tool, Codex=codex-spawn.sh"
```

**Step 2-5:** Implement branching:

```bash
if [ "${VG_RUNTIME:-claude}" = "codex" ]; then
  # Codex path: spawn fix agent via codex-spawn.sh (sandbox=executor)
  bash codex-skills/_shared/codex-spawn.sh --tier executor \
       --task "fix-${ERR_ID}" --sandbox workspace-write
else
  # Claude path: use Agent tool (existing pattern)
  # Agent(subagent_type="general-purpose", prompt=...)
fi
```

Mirror + commit.

```bash
git commit -m "feat(review): fix-loop dual-path codex-spawn for codex runtime (A6)"
```

---

## Task 7 (A7): State-shortcut + deepscan default ON

**Files:**
- Modify: `commands/vg/review.md:3551-3577` (DEEPSCAN_OPT_IN_GATE_v2.42.4 → OPT-OUT)
- Modify: `vg.config.template.md` (default `CONFIG_REVIEW_DEEPSCAN_DEFAULT: on`)
- Modify: `CHANGELOG.md` (breaking change note — deepscan now default ON, opt-out via `--skip-deepscan` or config flip)
- Mirror
- Test: `tests/test_deepscan_default_on.py` (NEW)

**Step 1: Failing test**

```python
def test_deepscan_default_on_in_template():
    body = Path("vg.config.template.md").read_text(encoding="utf-8")
    # Field present with value "on"
    m = re.search(r"CONFIG_REVIEW_DEEPSCAN_DEFAULT:\s*(\S+)", body)
    assert m and m.group(1) == "on", \
        f"deepscan default must be 'on' in v2.65.0 (was: {m.group(1) if m else 'MISSING'})"


def test_review_skip_deepscan_flag_exists():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # Must support --skip-deepscan opt-out
    assert "--skip-deepscan" in body, "Must provide opt-out flag"


def test_review_runs_deepscan_unless_skipped():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # Logic: run UNLESS --skip-deepscan OR config off
    skip_section = re.search(r"(?:skip|bypass).*deepscan", body, re.IGNORECASE)
    assert skip_section
```

**Step 2-5:** Flip review.md gate + add `--skip-deepscan` opt-out flag. Update CHANGELOG breaking-change section. Mirror + commit.

```bash
git commit -m "fix(review): deepscan default ON (BREAKING) + --skip-deepscan opt-out (A7)"
```

---

## Task 8 (A8): RUNTIME-MAP enforcement test

**Files:**
- NO source changes (verify existing must_be_created_in_run + check_provenance ENFORCE)
- Test: `tests/test_runtime_map_enforcement.py` (NEW)

**Step 1: Tests (must FAIL if enforcement broken)**

```python
def test_must_be_created_in_run_blocks_stale_artifact(tmp_path):
    """Stale RUNTIME-MAP.json from previous run must be rejected."""
    # Setup: create stale RUNTIME-MAP.json with old run_provenance
    # Run review run-complete
    # Expect rc != 0, error mentions "stale" or "must_be_created_in_run"
    ...


def test_check_provenance_validates_source_inputs(tmp_path):
    """RUNTIME-MAP.json missing source_inputs must be rejected."""
    # Setup: create RUNTIME-MAP.json without source_inputs key
    # Run review run-complete
    # Expect rc != 0, error mentions "provenance" or "source_inputs"
    ...


def test_normal_runtime_map_passes():
    """Fresh RUNTIME-MAP.json with valid provenance passes."""
    ...
```

**Step 2: Run — if FAIL, fix `scripts/vg-orchestrator/contracts.py:482-485`** (add explicit error message + assertion path)

**Step 3-5:** Document enforcement. Mirror tests. Commit.

```bash
git commit -m "test(review): RUNTIME-MAP must_be_created_in_run + provenance enforcement (A8)"
```

---

## Task 9 (A9): Codex marker manual-emit fallback

**Files:**
- Audit + extend: `codex-skills/vg-build/SKILL.md`, `codex-skills/vg-review/SKILL.md`, `codex-skills/vg-test/SKILL.md`, `codex-skills/vg-deploy/SKILL.md`, `codex-skills/vg-accept/SKILL.md`, `codex-skills/vg-blueprint/SKILL.md`, `codex-skills/vg-scope/SKILL.md`
- Modify: `scripts/vg-orchestrator/__main__.py` (relax/document hook-fallback when VG_RUNTIME=codex)
- Test: `tests/test_codex_marker_coverage.py` (NEW)

**Step 1: Failing test**

```python
import re
from pathlib import Path

CODEX_SKILLS = [
    "vg-build", "vg-review", "vg-test", "vg-deploy",
    "vg-accept", "vg-blueprint", "vg-scope",
]

def get_required_markers_from_command(cmd_name):
    """Parse must_touch_markers list from commands/vg/{cmd}.md frontmatter."""
    body = Path(f"commands/vg/{cmd_name}.md").read_text(encoding="utf-8")
    # Extract markers list (severity != warn)
    markers_section = re.search(r"must_touch_markers:(.*?)(?=must_emit_telemetry|forbidden|---)",
                                 body, re.DOTALL)
    assert markers_section, f"{cmd_name}: must_touch_markers section missing"
    
    # Hard markers (no severity: warn)
    text = markers_section.group(1)
    hard = re.findall(r'^\s*-\s*"([^"]+)"\s*$', text, re.MULTILINE)
    return set(hard)


@pytest.mark.parametrize("skill_name", CODEX_SKILLS)
def test_codex_skill_emits_all_hard_markers(skill_name):
    """Each codex-skill must explicitly call vg-orchestrator mark-step for every hard marker."""
    cmd_name = skill_name.removeprefix("vg-")
    required = get_required_markers_from_command(cmd_name)
    
    skill_body = Path(f"codex-skills/{skill_name}/SKILL.md").read_text(encoding="utf-8")
    
    missing = []
    for marker in required:
        if not re.search(rf"mark-step\s+\S+\s+{re.escape(marker)}", skill_body):
            missing.append(marker)
    
    assert not missing, (
        f"{skill_name}: missing manual mark-step calls for {len(missing)} markers: {missing[:5]}"
    )
```

**Step 2: Run — expect FAIL** (codex-skills currently rely on hooks)

**Step 3: Implement**

For each codex-skill, add manual emit blocks. Pattern:

```markdown
### STEP 1 — preflight

After preflight tool calls complete:

\`\`\`bash
${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator mark-step ${COMMAND} 1_parse_args
${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator mark-step ${COMMAND} 1a_build_queue_preflight
\`\`\`
```

Plus a top-level reminder:

```markdown
<HARD-GATE-CODEX>
Codex has no PreToolUse/PostToolUse hooks. AI MUST emit `vg-orchestrator mark-step` 
manually after EACH step's primary action completes. Missing markers → contract 
validator rejects run with "8/N markers found".
</HARD-GATE-CODEX>
```

**Step 4-5:** Mirror + commit (per-skill commits OR single bundled commit)

```bash
git commit -m "fix(codex-skills): explicit mark-step emit for 7 skills (no hook fallback) (A9)"
```

---

## Task 10: CHANGELOG + version bump + release tag

**Files:**
- Modify: `VERSION` (2.64.1 → 2.65.0)
- Modify: `package.json`
- Modify: `CHANGELOG.md`

**Step 1: Bump versions**

**Step 2: CHANGELOG entry**

```markdown
## v2.65.0 — Codex review speed + state-shortcut hardening (2026-05-09)

### Performance
- **A1:** Lens probe dispatch now parallelizable via `--parallel N` flag (`scripts/spawn_recursive_probe.py`). Default 1 (sequential, back-compat). Set `parallel_workers` in vg.config.md to opt in.
- **A2:** API contract probe parallelized via ThreadPoolExecutor (`scripts/review-api-contract-probe.py`). Same `parallel_workers` knob.
- **A3:** codex-inline scanner can now spawn N×`codex-spawn.sh --tier scanner` for non-MCP classification. MCP/browser stays inline (codex-spawn limitation).
- **A6:** Review fix-loop dual-path: Claude runtime uses Agent tool, Codex runtime uses `codex-spawn.sh --tier executor`.

### Correctness
- **A4:** Fix-loop max iterations 3 → 5. Each iteration emits `review.fix_iteration_started` for telemetry visibility.
- **A7 (BREAKING):** Phase 2b-2 deepscan now default ON. Previously OPT-IN since v2.42.4 → reviews silently skipped deepscan even when stale state present. Opt-out: `--skip-deepscan` flag OR `CONFIG_REVIEW_DEEPSCAN_DEFAULT: off` in vg.config.md.
- **A8:** Added enforcement tests for RUNTIME-MAP.json `must_be_created_in_run: true` + `check_provenance: true`. Stale or unprovenanced artifacts now reject run-complete.
- **A9:** Codex skills now manually emit step markers via `vg-orchestrator mark-step` (no PreToolUse/PostToolUse hooks in Codex). Fixes "8/39 markers found" contract validation failure across vg-build, vg-review, vg-test, vg-deploy, vg-accept, vg-blueprint, vg-scope.

### Configuration
- **A5:** New `parallel_workers: N` field in vg.config.template.md (default 5). Caps concurrent workers for A1, A2, A3 ops.

### Migration
- **A7 breaking change:** Existing reviews without `--skip-deepscan` will now run Phase 2b-2 (deepscan) by default. Adds ~30-90s to review wall time but catches state drift bugs missed in v2.64.x. To preserve old behavior, set `CONFIG_REVIEW_DEEPSCAN_DEFAULT: off` in your vg.config.md.
```

**Step 3: Commit + tag**

```bash
git add VERSION package.json CHANGELOG.md
git commit -m "release: v2.65.0 — codex review speed + state-shortcut hardening"
git tag v2.65.0
```

---

## Verification before complete

After each task:
- pytest pass for new test
- mirror byte-identity verified
- existing tests still pass (`pytest tests/ -x --ignore=tests/integration`)

After Task 10:
- `git log --oneline | head -10` shows 10 commits
- `cat VERSION` = `2.65.0`
- `python -m pytest tests/test_recursive_probe_parallel.py tests/test_api_contract_probe_parallel.py tests/test_codex_inline_parallel.py tests/test_review_fix_loop_progress.py tests/test_parallel_workers_config.py tests/test_review_fix_loop_dual_path.py tests/test_deepscan_default_on.py tests/test_runtime_map_enforcement.py tests/test_codex_marker_coverage.py -v` all pass

---

## Execution mode

Subagent-driven development (this session). Per task: implementer subagent (with questions before work) → spec compliance reviewer → code quality reviewer → mark complete → next task. Final reviewer for entire delta before release tag.
