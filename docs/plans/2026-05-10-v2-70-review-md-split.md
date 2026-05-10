# v2.70.0 — review.md Full Split

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Extract `commands/vg/review.md` (8159 lines monolithic) into `_shared/review/` subdir mirroring build.md slim entry + delegation files pattern. review.md slims to ~500 lines (frontmatter + STEP routing entries pointing to extracted files).

**Architecture:** 39 `<step name>` blocks identified. Group into 8 sub-files by phase + concern. review.md becomes routing entry; each STEP block replaced with single line: "Read `_shared/review/X.md` and follow it exactly." (mirror build.md:266-388 pattern).

**Tech Stack:** Markdown text manipulation. Mirror byte-identity for both `commands/` ↔ `.claude/commands/` pairs.

---

## Context

`commands/vg/build.md` already split (424 lines slim → `_shared/build/` 10+ delegation files). review.md never split. User confirmed "Full review.md split" for v2.70.0 scope.

**Section map** (39 steps):

| # | Section | Lines | Steps included |
|---|---|---|---|
| 1 | `_shared/review/preflight.md` | 477-1328 (~850) | 00_gate_integrity, 00_session_lifecycle, 0_parse_and_validate, 0a_env_mode_gate, 0b_goal_coverage_gate, 0c_telemetry_suggestions, create_task_tracker |
| 2 | `_shared/review/phase-p-variants.md` | 1328-2191 (~860) | phase_profile_branch, phaseP_infra_smoke, phaseP_delta, phaseP_regression, phaseP_schema_verify, phaseP_link_check |
| 3 | `_shared/review/code-scan.md` | 2191-2848 (~660) | phase1_code_scan (RFC v9 preflight + code scan), phase1_5_ripple_and_god_node |
| 4 | `_shared/review/api-and-discovery.md` | 2848-4010 (~1160) | phase2a_api_contract_probe, phase2_browser_discovery |
| 5 | `_shared/review/lens-and-findings.md` | 4010-4790 (~780) | phase2_5_recursive_lens_probe, phase2b_collect_merge, phase2c_enrich_test_goals, phase2c_pre_dispatch_gates, phase2d_crud_roundtrip_dispatch, phase2e_findings_merge, phase2e_post_challenge, phase2f_route_auto_fix |
| 6 | `_shared/review/limits-and-mobile.md` | 4873-5453 (~580) | phase2_exploration_limits, phase2_mobile_discovery, phase2_5_visual_checks, phase2_5_mobile_visual_checks |
| 7 | `_shared/review/url-and-error.md` | 5555-5878 (~325) | phase2_7_url_state_sync, phase2_8_url_state_runtime, phase2_9_error_message_runtime |
| 8 | `_shared/review/fix-loop-and-goals.md` | 5878-7323 (~1450) | phase3_fix_loop, phase4_goal_comparison **(largest section — 2 most-edited steps)** |
| 9 | `_shared/review/close.md` | 7323-7557 (~235) | unreachable_triage, crossai_review, write_artifacts, bootstrap_reflection, complete |

Total extracted: ~6900 lines into 9 files. Slim review.md retains: frontmatter + STEP routing (≈500-600 lines after slim).

**Reference pattern (build.md):**
- Slim entry at `commands/vg/build.md:266-388`
- Each STEP routes via "Read `_shared/build/X.md` and follow it exactly."
- Behavior preserved — extracted files contain verbatim original content.

VERSION baseline: 2.69.0. Bump to 2.70.0.

---

## Strategy

**Per-section extraction commit:**

1. Create `_shared/review/<name>.md` with extracted verbatim content (preserve XML tags, bash, markers, telemetry)
2. Replace section in review.md with slim STEP routing entry
3. Mirror canonical `_shared/review/<name>.md` → `.claude/commands/vg/_shared/review/<name>.md`
4. Mirror canonical `commands/vg/review.md` → `.claude/commands/vg/review.md`
5. Run smoke tests (test_review_*) to detect regressions on grep patterns
6. Commit per section

**Test impact:** Many existing tests grep `commands/vg/review.md` for specific patterns. After split, patterns may move to `_shared/review/`. Test fixes:
- For tests grep'ing review.md content directly: extend search to `_shared/review/` files (or use centralized helper that reads BOTH review.md and `_shared/review/*.md`)
- Tests checking marker entries / argument-hint / forbidden_without_override: these stay in review.md frontmatter, no fix needed
- Tests checking step XML or step-internal content: update to read corresponding `_shared/review/<name>.md`

**Helper pattern** (add to test conftest.py if pattern recurs):

```python
def review_text_full() -> str:
    """Concatenated review.md + all _shared/review/*.md content."""
    parts = [Path("commands/vg/review.md").read_text(encoding="utf-8")]
    for p in sorted(Path("commands/vg/_shared/review").glob("*.md")):
        parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)
```

---

## Task 1: Bootstrap split structure + extract preflight

**Goal:** Create `_shared/review/` dir, extract Section 1 (preflight.md, simplest), validate slim-entry pattern works.

**Files:**
- Create: `commands/vg/_shared/review/preflight.md` (~850 lines extracted)
- Create: `.claude/commands/vg/_shared/review/preflight.md` (mirror)
- Modify: `commands/vg/review.md:477-1328` (replace 7 step blocks with slim routing entry)
- Modify: `.claude/commands/vg/review.md` (mirror)
- Test: `tests/test_v2_70_review_split_preflight.py` (NEW)

**Step 1: Failing test**

```python
"""v2.70.0 T1 — review.md preflight section split."""
from pathlib import Path
import re


def test_preflight_subfile_exists():
    p = Path("commands/vg/_shared/review/preflight.md")
    assert p.exists(), "v2.70.0 T1 must create _shared/review/preflight.md"


def test_preflight_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/review/preflight.md").read_text(encoding="utf-8")
    expected_steps = [
        "00_gate_integrity_precheck", "00_session_lifecycle", "0_parse_and_validate",
        "0a_env_mode_gate", "0b_goal_coverage_gate", "0c_telemetry_suggestions",
        "create_task_tracker",
    ]
    for s in expected_steps:
        assert s in body, f"preflight.md missing step: {s}"


def test_review_md_routes_to_preflight_subfile():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    assert "_shared/review/preflight.md" in body, \
        "review.md must reference _shared/review/preflight.md after T1 split"


def test_review_md_no_longer_contains_extracted_step_bodies():
    """Verify steps moved out of review.md (only routing reference remains)."""
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # Step XML tag should still appear (slim wrapper) but body content should be gone
    # Strict check: count of `<step name=` for extracted steps should be <= 1 each (just routing wrapper or removed)
    for s in ["00_gate_integrity_precheck", "00_session_lifecycle", "0_parse_and_validate"]:
        # Either fully removed OR replaced with slim routing line
        # Look for "Read `_shared/review/preflight.md`" text near step references
        pass  # full validation in next test


def test_preflight_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/review/preflight.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/review/preflight.md").read_bytes()
    assert canonical == mirror, "_shared/review/preflight.md mirrors must be byte-identical"


def test_review_md_mirror_byte_identity():
    canonical = Path("commands/vg/review.md").read_bytes()
    mirror = Path(".claude/commands/vg/review.md").read_bytes()
    assert canonical == mirror
```

**Step 2: FAIL**

**Step 3: Implement**

Pattern:
1. `mkdir -p commands/vg/_shared/review`
2. Read review.md lines 477-1328 (boundary verified by grep)
3. Write extracted content to `commands/vg/_shared/review/preflight.md`
4. Replace lines 477-1328 in review.md with slim routing entry:

```markdown
### Preflight section (Section 1 — extracted v2.70.0)

Read `_shared/review/preflight.md` and follow it exactly.
Includes 7 steps: 00_gate_integrity_precheck, 00_session_lifecycle, 0_parse_and_validate, 0a_env_mode_gate, 0b_goal_coverage_gate, 0c_telemetry_suggestions, create_task_tracker.
```

5. Mirror canonical → `.claude/`
6. Run pytest

**Step 4-5:** Test, mirror, commit.

```bash
git commit -m "refactor(review): T1 extract preflight section to _shared/review/preflight.md (v2.70.0)"
```

---

## Task 2-9: Extract remaining 8 sections

**Each follows same pattern as Task 1.** Per task:

1. Read source lines per section map
2. Create `commands/vg/_shared/review/<name>.md`
3. Replace section in review.md with slim routing entry
4. Mirror canonical pair (sub-file + review.md)
5. Test (verify subfile exists + steps extracted + mirror byte-identity)
6. Commit

**Per-section task list:**

- **T2** `phase-p-variants.md` (lines 1328-2191) — 6 phaseP variants
- **T3** `code-scan.md` (lines 2191-2848) — phase1_code_scan + phase1_5_ripple_and_god_node
- **T4** `api-and-discovery.md` (lines 2848-4010) — phase2a + phase2 browser
- **T5** `lens-and-findings.md` (lines 4010-4790) — 8 phase2.5/2b/c/d/e/f steps
- **T6** `limits-and-mobile.md` (lines 4873-5453) — exploration + mobile + visual
- **T7** `url-and-error.md` (lines 5555-5878) — phase2.7/2.8/2.9
- **T8** `fix-loop-and-goals.md` (lines 5878-7323) — phase3 + phase4 (largest)
- **T9** `close.md` (lines 7323-7557) — unreachable + crossai + write + bootstrap + complete

**Note on line numbers:** Earlier tasks shrink review.md, so subsequent tasks read against current state, not original 8159-line file. Implementer must locate sections by step name (`<step name="X">`) not by absolute line number.

**Per task commit msg:** `refactor(review): T{N} extract <section> to _shared/review/<name>.md (v2.70.0)`

---

## Task 10: Final cleanup + ceiling test fix

**Files:**
- Modify: `scripts/tests/test_build_references_exist.py` (review.md line ceiling check — current ceiling N, after split expected ≪ N)
- Mirror
- Test: `tests/test_v2_70_review_slim_ceiling.py` (NEW — assert review.md ≤ 1500 lines after split)

**Step 1: Failing test**

```python
"""v2.70.0 T10 — review.md slim ceiling."""
from pathlib import Path


def test_review_md_under_slim_ceiling():
    """After full split, review.md should be slim routing + frontmatter only."""
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    # Original 8159 lines → split target ≤ 1500 (60% reduction minimum)
    assert line_count <= 1500, \
        f"v2.70.0 split target: review.md ≤ 1500 lines (got {line_count})"


def test_shared_review_dir_has_8_files():
    review_dir = Path("commands/vg/_shared/review")
    md_files = sorted(review_dir.glob("*.md"))
    assert len(md_files) >= 8, \
        f"v2.70.0 split target: ≥8 sub-files in _shared/review/ (got {len(md_files)})"


def test_review_md_routes_to_each_subfile():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    expected_subfiles = [
        "preflight.md", "phase-p-variants.md", "code-scan.md", "api-and-discovery.md",
        "lens-and-findings.md", "limits-and-mobile.md", "url-and-error.md",
        "fix-loop-and-goals.md", "close.md",
    ]
    missing = [s for s in expected_subfiles if f"_shared/review/{s}" not in body]
    assert not missing, f"review.md missing routes: {missing}"
```

**Step 2-5:** Update existing ceiling test to allow review.md ≤ 1500. Verify test_build_references_exist.py allows _shared/review/ subdir. Mirror.

```bash
git commit -m "refactor(review): T10 ceiling test fix + verify slim review.md ≤ 1500 lines (v2.70.0)"
```

---

## Task 11: Update test grep patterns + smoke regression

**Files:**
- Audit: tests that grep `commands/vg/review.md` body content (not frontmatter)
- Modify: tests that need to read extracted content — update path or add helper
- Test: re-run full test suite, verify zero regression on prior tests

**Step 1: Audit broken tests**

```bash
python -m pytest tests/ -x --no-header 2>&1 | grep -E "FAILED|ERROR" | head -30
```

For each failure where root cause is "moved content not found in review.md":
- Update test to read corresponding `_shared/review/<name>.md`
- OR use `review_text_full()` helper to read concatenated content

**Step 2:** Apply fixes per failing test.

**Step 3:** Re-run full suite, expect prior pass-rate restored.

**Step 4:** Commit.

```bash
git commit -m "refactor(review): T11 update test grep patterns for split structure (v2.70.0)"
```

---

## Task 12: Release commit + tag + push

**Files:** VERSION (2.69.0→2.70.0) + package.json + CHANGELOG.

**CHANGELOG entry:**

```markdown
## v2.70.0 — review.md full split (2026-05-10)

### Refactor
Extracted `commands/vg/review.md` (8159 lines monolithic) into `commands/vg/_shared/review/` subdir mirroring build.md slim entry + delegation files pattern.

### Sub-files (9 new)
- `_shared/review/preflight.md` — 7 gate/parse/profile steps
- `_shared/review/phase-p-variants.md` — 6 phaseP variants (infra-smoke, delta, regression, schema-verify, link-check)
- `_shared/review/code-scan.md` — phase1 code scan + phase1.5 graphify ripple
- `_shared/review/api-and-discovery.md` — phase2a API contract probe + phase2 browser discovery
- `_shared/review/lens-and-findings.md` — 8 phase2.5/2b/c/d/e/f steps (lens probe, findings derivation, auto-fix routing)
- `_shared/review/limits-and-mobile.md` — exploration limits + mobile discovery + visual checks
- `_shared/review/url-and-error.md` — phase2.7/2.8/2.9 URL state + error message runtime
- `_shared/review/fix-loop-and-goals.md` — phase3 fix loop + phase4 goal comparison (largest combined section)
- `_shared/review/close.md` — unreachable triage + crossai review + write artifacts + bootstrap reflection + complete

### review.md slim entry
review.md retains frontmatter + LANGUAGE_POLICY + HARD-GATE + STEP routing. Each STEP block replaced with: "Read `_shared/review/X.md` and follow it exactly." Pattern matches `commands/vg/build.md:266-388` slim entry style.

### Behavior
**Zero behavior change.** Extracted content is verbatim. Step markers, telemetry events, bash logic preserved exactly. Mirror byte-identity verified canonical/.claude pairs.

### Test impact
Test patterns grep'ing review.md body content updated to read `_shared/review/*.md`. Centralized helper available for tests needing concatenated review text. Prior test pass-rate restored.

### Migration
No migration. Operators continue calling `/vg:review {phase}` — entry routes through slim review.md → extracted sub-files transparently.
```

Tag + push + GitHub release.

---

## Verification

- `git log --oneline | head -15` shows 11 commits (T1-T11 + release)
- `cat VERSION` = `2.70.0`
- `wc -l commands/vg/review.md` ≤ 1500
- `ls commands/vg/_shared/review/*.md | wc -l` ≥ 9
- All v2.65.0-v2.69.0 tests pass

---

## Execution mode

Subagent-driven development. **Per task = own commit.** Suggested parallelism:

- **Batch A:** T1 + T2 (preflight + phase-p-variants — 2 commits)
- **Batch B:** T3 + T4 (code-scan + api-and-discovery — 2 commits)
- **Batch C:** T5 + T6 (lens-and-findings + limits-and-mobile — 2 commits)
- **Batch D:** T7 + T8 (url-and-error + fix-loop-and-goals — 2 commits, T8 is largest)
- **Batch E:** T9 (close — 1 commit)
- **Batch F:** T10 + T11 (ceiling fix + test pattern fixes — 2 commits)
- **Release:** T12

**Critical constraint:** Each section extraction must preserve verbatim content. NO behavior changes. NO opportunistic refactor inside extracted files. Just move-and-route.
