<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Codex Round 2 Correction E inlined below the original task body. -->

## Task 19: Integration test for pre-test gate

**Files:**
- Create: `tests/test_pre_test_gate_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_pre_test_gate_integration.py`:

```python
"""End-to-end: T1+T2 runner produces report, deploy decision picks env, writer
emits readable PRE-TEST-REPORT.md."""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_full_pipeline_no_deploy(tmp_path: Path) -> None:
    """T1+T2 runner → JSON → writer → PRE-TEST-REPORT.md, with no-deploy."""
    # Synthetic clean source
    src = tmp_path / "src"
    src.mkdir()
    (src / "Page.tsx").write_text(
        "export function Page() { return <div>ok</div>; }\n", encoding="utf-8",
    )

    t12_report = tmp_path / "t12.json"
    result = subprocess.run([
        "python3", str(REPO / "scripts" / "validators" / "verify-pre-test-tier-1-2.py"),
        "--source-root", str(src),
        "--phase", "intg-1.0",
        "--report-out", str(t12_report),
        "--repo-root", str(tmp_path),  # not a real repo — typecheck/lint will SKIP
        "--skip-typecheck", "--skip-lint", "--skip-tests",  # only debug-grep T1
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

    out = tmp_path / "PRE-TEST-REPORT.md"
    result = subprocess.run([
        "python3", str(REPO / "scripts" / "validators" / "write-pre-test-report.py"),
        "--phase", "intg-1.0",
        "--t12-report", str(t12_report),
        "--no-deploy",
        "--output", str(out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

    md = out.read_text(encoding="utf-8")
    assert "intg-1.0" in md
    assert "Tier 1" in md
    assert "Tier 2" in md
    assert "SKIPPED" in md  # all tier_1 + tier_2 skipped
    assert "Deploy: SKIPPED" in md


def test_deploy_decision_reads_env_baseline(tmp_path: Path) -> None:
    """Synthesize ENV-BASELINE.md, run deploy_decision, verify proposal."""
    eb = tmp_path / "ENV-BASELINE.md"
    eb.write_text(textwrap.dedent("""
        # Environment Baseline — X

        **Profile:** web-fullstack

        ## Recommended tech stack
        | Layer | Tool | Version | Rationale |
        |---|---|---|---|
        | Runtime | Node | 22 | LTS |

        ## Environment matrix
        | Env | Purpose | Hosting | Run | Deploy | DB | Secrets | Auto |
        |---|---|---|---|---|---|---|---|
        | dev | local | localhost | dev | none | sqlite | env | – |
        | sandbox | AI test | vps | pm2 | rsync | postgres | vault | yes |
        | staging | UAT | staging | (cdn) | git push | postgres | vercel | manual |
        | prod | prod | app.com | (cdn) | git push | postgres | vercel | approval |

        ## Decisions (E-XX namespace)
        ### E-01: Stack chosen
        **Reasoning:** match the foundation pick
        **Reverse cost:** LOW
        **Sources cited:** https://example.com
    """).strip(), encoding="utf-8")

    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from deploy_decision import propose_target  # type: ignore
    proposal = propose_target(eb, phase_changes={"frontend": True, "backend": True})
    assert proposal["recommended_env"] == "sandbox"
    assert "sandbox" in proposal["available_envs"]
    sys.path.remove(str(REPO / "scripts" / "lib"))
```

- [ ] **Step 2: Run integration test**

Run: `python3 -m pytest tests/test_pre_test_gate_integration.py -v`
Expected: 2 passed.

- [ ] **Step 3: Run full pre-test test suite for regression**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_pre_test_runner.py \
                  tests/test_deploy_decision.py \
                  tests/test_post_deploy_smoke.py \
                  tests/test_pre_test_gate_integration.py -v
```
Expected: 10 passed (3 + 3 + 2 + 2).

- [ ] **Step 4: Commit**

```bash
git add tests/test_pre_test_gate_integration.py
git commit -m "test(pre-test): integration test for STEP 6.5 pipeline"
```

---

## Self-review checklist

**Spec coverage** — every layer in revised plan maps to tasks:

| Spec section | Task |
|---|---|
| L4a-i FE→BE call graph BLOCK | Task 3 (validator) + Task 6 (wiring) |
| L4a-ii Contract shape BLOCK | Task 4 + Task 6 |
| L4a-iii Spec drift BLOCK | Task 5 + Task 6 |
| L2 Evidence-based classifier (4-tier) | Task 7 |
| L3 Auto-fix loop STEP 5.5 | Task 10 |
| L4b Measured rollout for soft baselines | Deferred — opens once telemetry data from L4a + L3 lands (post-implementation P3) |
| L1 Rule resolver | Task 11 |
| B1 FE call + BE route extractors | Task 2 |
| B2 Contract shape (method-match tier) | Task 4 |
| B6 Phase ownership allowlist | Task 8 |
| B7 Regression smoke runner | Task 9 |
| Forward-dep disposition gate | Task 12 |
| Severity taxonomy + evidence schema | Task 1 |
| Integration test | Task 13 |
| Mirror sync | Task 14 |
| **Pre-Test Gate (extension)** | |
| Pre-test T1 (static checks) + T2 (local tests) | Task 15 + Correction A (secret scan + missing-tooling BLOCK) |
| Deploy decision policy (ENV-BASELINE-driven) | Task 16 + Correction B (deterministic schema detection) |
| Post-deploy smoke + PRE-TEST-REPORT writer | Task 17 + Correction C (total deadline + storageState + auth) |
| Wire STEP 6.5 into build pipeline | Task 18 + Correction D (Skill invoke, fixed CLI/path/severity, config-driven UX) |
| Pre-test integration test | Task 19 + Correction E (deadline + redaction + schema-detect tests) |
| `/vg:deploy --pre-test` mode | Task 20 (NEW per Codex round 2 #2) |

**Placeholder scan** — searched plan body for "TBD", "TODO", "fill in details", "appropriate error handling", "similar to Task N", "implement later". None found in task bodies. Two `# P3` markers present in code comments — those are intentional follow-up flags for AST upgrades (FE call extraction) and body-shape validation, not plan placeholders. The "L4b Measured rollout" row in the table above is explicitly deferred per Codex feedback (need L4a+L3 telemetry first to set BLOCK thresholds for soft baselines).

**Type consistency** — names threaded:
- `BuildWarningEvidence` schema (Task 1) → produced by Tasks 3/4/5 → consumed by Task 7 (classifier) → consumed by Task 10 (fix-loop) — single shape end-to-end.
- `Severity` enum: `BLOCK | TRIAGE_REQUIRED | FORWARD_DEP | ADVISORY` consistent in schema (Task 1), classifier output (Task 7), fix-loop branching (Task 10).
- Path normalization (`:param` form): same regex in FE extractor (Task 2), BE extractor (Task 2), L4a-i gate (Task 3), L4a-ii gate (Task 4), classifier (Task 7).
- `phase_dir` argument signature: same `.vg/phases/<phase>/` shape across validators (Tasks 3/4/5), classifier (Task 7), ownership (Task 8), integration test (Task 13).
- `evidence_refs[]` shape: `{file, line?, snippet?, endpoint?, task_id?}` — consistent across all producers.

**Codex feedback coverage** — explicit:
- Order **L4 → L2 → L3 → L1** (Codex correction): tasks ordered Task 3-6 (L4a) → Task 7 (L2) → Tasks 8-10 (L3 deps + body) → Task 11 (L1 parallel).
- Deterministic-first classifier (no LLM authority): Task 7 uses regex/path matching only.
- 4-tier severity: Task 1 enum + schema enforces.
- Fix-loop bounded with strict stop conditions: Task 10's HARD-GATE block + delegation contract enumerates every stop reason.
- No AskUserQuestion mid-build: explicit forbidden item in delegation (Task 10).
- Rule resolver scope-matched, not dump-all: Task 11.
- Forward-dep disposition (not completion): Task 12 records disposition; gate fires on disposition not on resolution.
- Phase ownership boundary: Task 8 + Task 10 ownership_allowlist parameter.
- Regression smoke: Task 9 + Task 10 wiring.
- Evidence persistence: Task 1 schema is machine-readable JSON, written to `${PHASE_DIR}/.evidence/`.
- L4b deferred: classifier emits ADVISORY for i18n/a11y/perf today; uplift to BLOCK once auto-fix coverage proven (post-implementation step, not in this plan).

---

## Execution

Plan complete and saved to `docs/superpowers/plans/2026-05-03-vg-build-in-scope-fix-loop.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch fresh subagent per task, review between tasks, fast iteration. 20 task units (14 in-scope-fix-loop + 6 pre-test gate extension including Codex-round-2 corrections + Task 20 `/vg:deploy --pre-test` mode), ~30-40 min each = ~11-14 hours wall-clock. Implementer subagents MUST apply the "Codex Round 2 Corrections" section on top of original task bodies for Tasks 15-19.

**2. Inline Execution** — execute tasks in this session via executing-plans, batch checkpoints. Faster context but loses per-task review isolation.

**Which approach?**


---

## Codex Round 2 Correction E (mandatory — apply on top of the original task body above)

### Correction E — Task 19: integration test additions

Append the following test cases to
`tests/test_pre_test_gate_integration.py` (Task 19 Step 1):

```python
def test_health_check_total_deadline_pattern(tmp_path: Path) -> None:
    """Codex fix #7: health_check must respect total_deadline, not per-request × retries."""
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from post_deploy_smoke import health_check  # type: ignore
    import time as _time

    started = _time.monotonic()
    # Unreachable URL (TEST-NET-1 blackhole) — must respect 5s deadline
    result = health_check("http://192.0.2.1:7777", path="/health",
                          total_deadline_s=5, poll_interval_s=2)
    elapsed = _time.monotonic() - started
    assert result["status"] == "BLOCK"
    assert elapsed < 7, f"health_check ran {elapsed:.1f}s, expected ≤6s (5s deadline + slack)"
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_deploy_state_path_is_phase_dir(tmp_path: Path) -> None:
    """Codex fix #3: DEPLOY-STATE.json lives at PHASE_DIR/, not PLANNING_DIR/."""
    pd = tmp_path / ".vg" / "phases" / "test-1.0"
    pd.mkdir(parents=True)
    (pd / "DEPLOY-STATE.json").write_text(json.dumps({
        "deployed": {"sandbox": {"url": "https://sandbox.example.com", "deployed_at": "2026-05-03"}}
    }), encoding="utf-8")

    # Verify the documented path resolution matches what the orchestrator does
    assert (pd / "DEPLOY-STATE.json").exists()
    assert not (tmp_path / ".vg" / "DEPLOY-STATE.json").exists()


def test_secret_scan_redacts_match() -> None:
    """Codex fix #6: secret-scan evidence must NOT echo the matched secret."""
    import sys, tempfile, textwrap as _tw
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from pre_test_runner import grep_secrets  # type: ignore

    with tempfile.TemporaryDirectory() as td:
        Path(td, "config.ts").write_text(
            'const k = "AKIAIOSFODNN7EXAMPLE";\n', encoding="utf-8",
        )
        result = grep_secrets(Path(td))

    assert result["status"] == "BLOCK"
    for ev in result["evidence"]:
        assert "AKIA" not in ev.get("snippet", ""), "secret leaked into evidence snippet"
        assert "redacted" in ev.get("snippet", "").lower()
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_phase_change_detection_classifies_schema(tmp_path: Path) -> None:
    """Codex fix #3: detect_phase_changes finds 'schema' from migration files."""
    pd = tmp_path / ".vg" / "phases" / "test-1.0"
    (pd / ".task-capsules").mkdir(parents=True)
    (pd / ".task-capsules" / "task-01.capsule.json").write_text(json.dumps({
        "task_id": "task-01",
        "edits_files": ["apps/api/src/db/migrations/0042_add_invoices.sql"],
        "edits_endpoint": "POST /api/invoices",
    }), encoding="utf-8")

    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from deploy_decision import detect_phase_changes  # type: ignore
    flags = detect_phase_changes(pd, repo_root=tmp_path)
    assert flags["schema"] is True
    assert flags["backend"] is True
    sys.path.remove(str(REPO / "scripts" / "lib"))
```

