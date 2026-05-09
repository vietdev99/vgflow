# v2.66.1 — Plan-fidelity followup + 2 deferred issues

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Close 2 deferred MEDIUM issues (#153 #154) + ship B2-B4 plan-fidelity (questions+self-review, TDD plan structure, in-build final reviewer).

**Architecture:** #153 reshapes aggregator dedup key to cluster by API endpoint shape. #154 makes crossai_review.done marker verdict-gated. B2 relaxes executor "must not ask questions" rule + adds self-review step. B3 makes planner enforce TDD per-task structure. B4 adds final-delta reviewer subagent after all waves.

**Tech Stack:** Python 3 (aggregator + tests), Bash + Markdown (review.md, agents), Markdown (planner template).

**Issues closed:** #153 #154 (last 2 of 8 dogfood issues).

---

## Context

v2.66.0 closed 6 of 8 issues + B1 reviewer agent + C4 prereq strict default. v2.66.1 closes remaining 2 issues + B2-B4 plan-fidelity bundle.

**File targets (from research):**
- `scripts/derive-findings.py:79` — dedup key currently `{resource}-{role}-{step}-{title}` (view-based, not API shape)
- `commands/vg/review.md:7171-7186` — crossai_review step spec; marker write needs verdict-gating
- `.claude/agents/vg-build-task-executor/SKILL.md:8-44` — HARD-GATE "MUST NOT ask questions" + no self-review
- `.claude/agents/vg-blueprint-planner/SKILL.md:111-122` — planner has wave decomposition but no TDD enforcement
- `commands/vg/_shared/build/close.md:1-40` — postmortem exists; no final reviewer subagent

VERSION baseline: 2.66.0. Bump to 2.66.1.

---

## Task 1 (#153): Aggregator clustering by API endpoint

**Files:**
- Modify: `scripts/derive-findings.py:76-86` (dedup key includes `api_endpoint` shape)
- Mirror: `.claude/scripts/derive-findings.py`
- Test: `tests/test_findings_api_clustering.py` (NEW)

**Problem:** 1 missing backend endpoint → N findings (one per consumer view). All MINOR severity, none reach auto-fix routing gate.

**Fix approach:** Extract API endpoint shape (METHOD + path-template) from network errors. Cluster findings sharing same `api_endpoint` shape into a single ROOT finding (severity escalated) with N child references (still listed, but de-emphasized).

**Step 1: Failing test**

```python
"""v2.66.1 #153 — Findings clustered by API endpoint shape."""
import importlib.util
import sys
from pathlib import Path
import pytest


def _load_derive():
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "derive_findings",
        repo_root / "scripts" / "derive-findings.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_findings_with_same_endpoint_clustered():
    """3 findings on different views all hitting POST /api/v1/orders/:id/pay → 1 ROOT + 3 child refs."""
    mod = _load_derive()
    findings = [
        {"resource": "/orders", "role": "ALL", "step_ref": "smoke",
         "title": "400 /api/v1/orders/123/pay",
         "api_endpoint": "POST /api/v1/orders/:id/pay",
         "severity": "MINOR"},
        {"resource": "/orders/views", "role": "ALL", "step_ref": "smoke",
         "title": "400 /api/v1/orders/456/pay",
         "api_endpoint": "POST /api/v1/orders/:id/pay",
         "severity": "MINOR"},
        {"resource": "/checkout", "role": "ALL", "step_ref": "smoke",
         "title": "400 /api/v1/orders/789/pay",
         "api_endpoint": "POST /api/v1/orders/:id/pay",
         "severity": "MINOR"},
    ]
    clustered = mod.cluster_by_api_endpoint(findings)
    
    # Expect 1 ROOT (escalated severity) + 3 child references in metadata
    roots = [f for f in clustered if f.get("cluster_role") == "root"]
    assert len(roots) == 1, f"Expected 1 root, got {len(roots)}"
    
    root = roots[0]
    assert root["api_endpoint"] == "POST /api/v1/orders/:id/pay"
    assert root["severity"] in ("MAJOR", "CRITICAL"), \
        f"Root must escalate severity, got {root['severity']}"
    assert root.get("affected_views_count") == 3 or len(root.get("affected_views", [])) == 3


def test_findings_without_api_endpoint_passthrough():
    """Findings without api_endpoint key pass through dedup unchanged (back-compat)."""
    mod = _load_derive()
    findings = [
        {"resource": "/x", "role": "ALL", "step_ref": "ssim",
         "title": "Pixel diff", "severity": "MINOR"},
    ]
    out = mod.cluster_by_api_endpoint(findings)
    assert len(out) == 1
    assert out[0].get("cluster_role") in (None, "standalone")


def test_dedupe_still_runs_after_clustering():
    """Existing dedupe by view + title still applies AFTER clustering (orthogonal)."""
    mod = _load_derive()
    # 2 findings on same view, same title — dedup to 1
    findings = [
        {"resource": "/x", "role": "ALL", "step_ref": "smoke", "title": "Console error A"},
        {"resource": "/x", "role": "ALL", "step_ref": "smoke", "title": "Console error A"},
    ]
    out = mod.dedupe(findings)
    assert len(out) == 1


def test_normalize_api_endpoint_strips_query_and_ids():
    """api_endpoint shape extraction must replace numeric IDs with :id, strip query."""
    mod = _load_derive()
    cases = [
        ("POST /api/v1/orders/123/pay", "POST /api/v1/orders/:id/pay"),
        ("GET /api/v1/users/abc-uuid?include=profile", "GET /api/v1/users/:id"),
        ("DELETE /api/v1/items/42", "DELETE /api/v1/items/:id"),
    ]
    for raw, expected in cases:
        got = mod.normalize_api_endpoint(raw)
        assert got == expected, f"normalize({raw!r}) = {got!r}, want {expected!r}"
```

**Step 2: FAIL** (`cluster_by_api_endpoint` + `normalize_api_endpoint` don't exist)

**Step 3: Implement** in `scripts/derive-findings.py`:

```python
import re

def normalize_api_endpoint(raw: str) -> str:
    """Extract endpoint shape: METHOD /path/with/:id (strip query, replace IDs)."""
    if not raw:
        return ""
    # Strip query string
    raw = raw.split("?", 1)[0].strip()
    # Replace numeric/uuid path segments with :id
    parts = raw.split(" ", 1)
    if len(parts) != 2:
        return raw
    method, path = parts
    segments = path.split("/")
    norm = []
    for seg in segments:
        if not seg:
            norm.append(seg)
            continue
        # numeric or uuid-like
        if re.fullmatch(r"\d+|[a-f0-9-]{8,}", seg, re.IGNORECASE):
            norm.append(":id")
        else:
            norm.append(seg)
    return f"{method} {'/'.join(norm)}"


def cluster_by_api_endpoint(findings: list[dict]) -> list[dict]:
    """Cluster findings sharing same api_endpoint shape into ROOT + children.
    
    Findings without api_endpoint key pass through as standalone.
    """
    clusters: dict[str, list[dict]] = {}
    standalone: list[dict] = []
    
    for f in findings:
        ep = f.get("api_endpoint")
        if not ep:
            f.setdefault("cluster_role", "standalone")
            standalone.append(f)
            continue
        norm = normalize_api_endpoint(ep)
        clusters.setdefault(norm, []).append(f)
    
    out = []
    for norm_ep, items in clusters.items():
        if len(items) == 1:
            items[0].setdefault("cluster_role", "standalone")
            out.append(items[0])
            continue
        # Build ROOT finding (escalated severity)
        root = dict(items[0])
        root["cluster_role"] = "root"
        root["api_endpoint"] = norm_ep
        root["severity"] = "MAJOR"  # escalate
        root["title"] = f"{norm_ep} — failing on {len(items)} views"
        root["affected_views"] = [it.get("resource", "?") for it in items]
        root["affected_views_count"] = len(items)
        out.append(root)
        # Children retain original metadata + cluster_role=child
        for child in items[1:]:
            child["cluster_role"] = "child"
            child["cluster_root_endpoint"] = norm_ep
            out.append(child)
    
    return out + standalone
```

Wire `cluster_by_api_endpoint(findings)` BEFORE existing `dedupe(findings)` call in main flow.

**Step 4-5:** Mirror + commit.

```bash
git commit -m "fix(review): cluster findings by API endpoint shape (#153)"
```

---

## Task 2 (#154): Verdict-gated crossai_review.done marker

**Files:**
- Modify: `commands/vg/review.md` Phase 2c (search for crossai_review marker write)
- Modify: `scripts/crossai-aggregate-results.py` or wherever marker write happens
- Mirror
- Test: `tests/test_crossai_marker_verdict_gated.py` (NEW)

**Problem:** When all 3 reviewers fail (CLI missing/auth missing/path bug), aggregator emits `<verdict>inconclusive</verdict>` with `<ok_count>0</ok_count>`. Orchestrator still writes `.step-markers/review/crossai_review.done`. `/vg:next` skips re-run because marker exists.

**Fix:** Marker write must check verdict + ok_count. Only write `crossai_review.done` when verdict in {ok, partial} AND ok_count > 0. Otherwise emit `crossai_review.inconclusive` marker (different name) so orchestrator knows to retry.

**Step 1: Failing test**

```python
"""v2.66.1 #154 — crossai_review.done marker verdict-gated."""
import re
from pathlib import Path


def test_review_md_documents_verdict_gating():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # Must mention verdict-gating logic for crossai_review marker
    assert re.search(
        r"crossai_review.*(?:verdict|ok_count).*(?:gat|condition|check)",
        body, re.IGNORECASE | re.DOTALL
    ), "review.md must document verdict-gated crossai_review marker"


def test_inconclusive_marker_alternative_documented():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # When verdict=inconclusive, write crossai_review.inconclusive (different name) instead
    assert "crossai_review.inconclusive" in body, \
        "review.md must document fallback marker name for inconclusive"


def test_aggregator_logic_branches_on_verdict():
    """aggregator script must branch marker write on verdict + ok_count."""
    # Find script that writes the marker
    candidates = [
        "scripts/crossai-aggregate-results.py",
        "scripts/crossai-normalize-results.py",
        "scripts/crossai-runner.py",
    ]
    found = False
    for c in candidates:
        p = Path(c)
        if p.exists():
            body = p.read_text(encoding="utf-8")
            if "crossai_review.done" in body or "crossai_review.inconclusive" in body:
                found = True
                # Logic must reference verdict variable
                assert re.search(
                    r"verdict.*['\"](?:ok|partial|inconclusive|fail)['\"]",
                    body, re.IGNORECASE
                ), f"{c}: verdict-branching logic missing"
                break
    
    if not found:
        # If marker write is in review.md bash directly, that's also acceptable
        body = Path("commands/vg/review.md").read_text(encoding="utf-8")
        assert re.search(
            r"crossai_review\.done.*verdict|verdict.*crossai_review\.done",
            body, re.IGNORECASE | re.DOTALL
        ), "marker write logic must reference verdict either in script or review.md"
```

**Step 2: FAIL**

**Step 3: Locate + fix marker write site.** Implementer must:
1. Grep for `crossai_review.done` across repo to find write site
2. Add verdict + ok_count check before writing
3. On inconclusive/fail: write `crossai_review.inconclusive` instead so `/vg:next` re-runs
4. Document in review.md Phase 2c text

**Step 4-5:** Mirror + commit.

```bash
git commit -m "fix(review): crossai_review.done marker verdict-gated (#154)"
```

---

## Task 3 (B2): Implementer questions + self-review

**Files:**
- Modify: `.claude/agents/vg-build-task-executor/SKILL.md:8-44` (relax HARD-GATE "MUST NOT ask questions" + add self-review step)
- Modify: `commands/vg/_shared/build/waves-delegation.md` (delegation prompt mentions allowed questions)
- Test: `tests/test_b2_executor_questions_selfreview.py` (NEW)

**Problem:** v2.66.0 research showed executor template explicitly forbids asking questions ("You MUST NOT ask user questions") AND no self-review of diff before commit. Both gaps cause plan-fidelity issues.

**Fix scope:** RELAX (not remove) the no-questions rule — allow questions when capsule + plan slice are genuinely ambiguous. Add mandatory self-review pass before commit.

**Step 1: Failing test**

```python
"""v2.66.1 B2 — executor allows questions + self-reviews diff."""
from pathlib import Path
import re


def test_executor_allows_questions_when_capsule_ambiguous():
    body = Path(".claude/agents/vg-build-task-executor/SKILL.md").read_text(encoding="utf-8")
    # Must NOT have absolute "MUST NOT ask questions" anymore
    bad = re.search(r"MUST NOT ask user questions", body)
    assert not bad, "executor must allow questions when capsule ambiguous (v2.66.1 B2)"
    # Must have explicit "MAY ask" or "if ambiguous, ask" clause
    assert re.search(
        r"(?:MAY|may|allowed to)\s+ask\s+(?:user\s+)?questions|ambiguous.*ask",
        body, re.IGNORECASE
    ), "executor must explicitly permit questions when capsule ambiguous"


def test_executor_has_self_review_step():
    body = Path(".claude/agents/vg-build-task-executor/SKILL.md").read_text(encoding="utf-8")
    # Must mention self-review of diff before commit
    assert re.search(r"self.?review", body, re.IGNORECASE), \
        "executor must include self-review step (v2.66.1 B2)"
    # Must specify when (before commit)
    assert re.search(
        r"(?:before commit|before staging|after impl).*self.?review|self.?review.*before commit",
        body, re.IGNORECASE | re.DOTALL
    ), "self-review must be explicitly before commit"


def test_self_review_checklist_present():
    body = Path(".claude/agents/vg-build-task-executor/SKILL.md").read_text(encoding="utf-8")
    # Self-review section should have concrete checklist items
    # (e.g., scope creep, missing tests, mirror byte-identity)
    assert re.search(r"(?:scope\s*creep|test.*present|mirror.*byte)", body, re.IGNORECASE), \
        "self-review must have concrete checklist items"
```

**Step 2: FAIL**

**Step 3: Implement** — edit `.claude/agents/vg-build-task-executor/SKILL.md` lines 8-44:

```markdown
<HARD-GATE>
You execute ONE task — capsule + plan slice + contract slices + interface
standards are your contract. Before starting:

**You MAY ask user questions ONLY when capsule + plan slice contain
ambiguity that prevents correct implementation.** Examples of valid
questions:
- Two API contract slices conflict on response shape (impossible to satisfy both)
- Plan task references a file path that doesn't exist (typo? renamed?)
- Capsule binding shows API-CONTRACTS.md goal G-04 but plan task says G-03

**You MUST NOT ask questions for:**
- Stylistic preferences (just follow existing patterns)
- Whether to add tests (always add per plan)
- Whether to bump version (NO unless task is explicit release task)
- Whether to mirror canonical→.claude/ (ALWAYS yes)

You MUST NOT spawn nested subagents (no Agent calls inside executor).
You MUST NOT skip the typecheck step.
</HARD-GATE>

<SELF-REVIEW>
**Mandatory before commit:** After implementation + tests pass, BEFORE
running `git add` + `git commit`, perform self-review:

1. Read full diff: `git diff` (unstaged) + `git diff --cached` (if any)
2. Verify against checklist:
   - [ ] All required files modified per plan task spec? (no missing edits)
   - [ ] No scope creep — touched ONLY files plan task names
   - [ ] All required tests added? (no missing test cases)
   - [ ] Mirror byte-identity: `commands/` ↔ `.claude/commands/`, `scripts/` ↔ `.claude/scripts/` (run `diff -q`)
   - [ ] No VERSION/package.json bump (unless this IS the release task)
   - [ ] No `--no-verify` or `--amend` snuck in
   - [ ] Test count matches plan spec (3 tests required → 3 added, not 2)
3. If checklist reveals issue: fix BEFORE staging. Do NOT commit + amend.
</SELF-REVIEW>
```

**Step 4-5:** Mirror canonical (executor agent has no Claude mirror). Wire reminder in `commands/vg/_shared/build/waves-delegation.md` delegation prompt:

```markdown
**Self-review note (v2.66.1 B2):** Per `.claude/agents/vg-build-task-executor/SKILL.md`,
implementer must self-review diff against the 7-item checklist before commit.
```

Commit:

```bash
git commit -m "feat(executor): B2 questions when ambiguous + self-review checklist (v2.66.1)"
```

---

## Task 4 (B3): TDD plan structure enforcement

**Files:**
- Modify: `.claude/agents/vg-blueprint-planner/SKILL.md:111-122` (planner template enforces TDD per-task)
- Modify: `commands/vg/_shared/blueprint/plan-template.md` if exists (else create)
- Test: `tests/test_b3_planner_tdd_structure.py` (NEW)

**Problem:** Planner generates wave decomposition + task ordering but each task body is freeform. Implementers may skip tests entirely or write tests AFTER impl (defeats TDD).

**Fix:** Planner template REQUIRES each task body have 5 explicit steps:
1. Write failing test
2. Run test → confirm FAIL  
3. Implement minimal change
4. Run test → confirm PASS
5. Mirror + commit

**Step 1: Failing test**

```python
"""v2.66.1 B3 — Planner enforces TDD structure per task."""
from pathlib import Path
import re


def test_planner_template_mentions_tdd():
    body = Path(".claude/agents/vg-blueprint-planner/SKILL.md").read_text(encoding="utf-8")
    assert "TDD" in body or "test-driven" in body.lower(), \
        "planner must reference TDD pattern (v2.66.1 B3)"


def test_planner_requires_5_step_structure():
    body = Path(".claude/agents/vg-blueprint-planner/SKILL.md").read_text(encoding="utf-8")
    # Must mention all 5 steps OR reference template that does
    required_phrases = [
        "failing test", "confirm FAIL", "minimal", "confirm PASS", "commit"
    ]
    missing = [p for p in required_phrases if p.lower() not in body.lower()]
    assert not missing, f"planner missing TDD step phrases: {missing}"


def test_planner_test_first_assertion():
    body = Path(".claude/agents/vg-blueprint-planner/SKILL.md").read_text(encoding="utf-8")
    # Must explicitly say tests come BEFORE implementation
    assert re.search(
        r"test.{0,40}(?:before|first|prior).{0,40}impl|write.{0,40}test.{0,40}first",
        body, re.IGNORECASE
    ), "planner must enforce test-first ordering"
```

**Step 2: FAIL**

**Step 3: Implement** — append to `.claude/agents/vg-blueprint-planner/SKILL.md`:

```markdown
## TDD Plan Structure Enforcement (v2.66.1 B3)

**Every task body in PLAN/task-NN.md MUST follow this 5-step TDD structure
verbatim.** Operators rely on consistent structure to spawn implementers
that follow superpowers:test-driven-development.

### Required task body template

\`\`\`markdown
### Task N: [Component name]

**Files:**
- Create/Modify: `path/to/file.ext`
- Test: `tests/path/test.py`

**Step 1: Write failing test FIRST (before implementation)**

\\`\\`\\`python
def test_specific_behavior():
    result = function(input)
    assert result == expected
\\`\\`\\`

**Step 2: Run test → confirm FAIL**

\\`\\`\\`bash
pytest tests/path/test.py::test_specific_behavior -v
\\`\\`\\`
Expected: FAIL with "function not defined" or similar.

**Step 3: Implement minimal change**

\\`\\`\\`python
def function(input):
    return expected
\\`\\`\\`

**Step 4: Run test → confirm PASS**

**Step 5: Mirror canonical → .claude/ + commit**

\\`\\`\\`bash
git add tests/path/test.py path/to/file.ext .claude/path/to/file.ext
git commit -m "feat: ..."
\\`\\`\\`
\`\`\`

### Why test-first ordering

Writing the test FIRST ensures:
- Test actually fails before fix (no false-pass)
- Implementation matches test (not test matched to passing impl)
- Test surface area documented before code reviewed

When writing PLAN/task-NN.md, AI MUST emit all 5 steps per task. Skipping
step 1 (test) or step 2 (confirm FAIL) violates B3 — task header lock
(`.task-fidelity.lock.json`) flags missing steps in audit.
```

**Step 4-5:** Commit (no mirror — `.claude/agents/` is canonical).

```bash
git commit -m "feat(planner): B3 TDD plan structure enforcement (v2.66.1)"
```

---

## Task 5 (B4): In-build final reviewer

**Files:**
- Create: `.claude/agents/vg-build-final-reviewer/SKILL.md` (NEW agent)
- Modify: `commands/vg/_shared/build/close.md:1-40` (spawn final reviewer in STEP 7.1.5)
- Modify: `commands/vg/build.md` (add STEP 7.5 wire if needed)
- Mirror
- Test: `tests/test_b4_final_reviewer.py` (NEW)

**Problem:** Build pipeline ends with postmortem + verify-goal-coverage advisory. NO subagent reviews the cumulative delta vs PLAN.md. Per-task spec reviewer (B1) doesn't see cross-task patterns (e.g. did all tasks together actually achieve the phase goal?).

**Fix:** New `vg-build-final-reviewer` agent that reads PLAN.md + git log of phase commits + L-gate results, evaluates: "did the implementation collectively achieve the phase goal?" Returns PASS/PARTIAL/FAIL. Severity=warn (advisory) until v2.67.0 telemetry-driven flip.

**Step 1: Failing test**

```python
"""v2.66.1 B4 — In-build final reviewer agent."""
from pathlib import Path
import re


def test_final_reviewer_agent_exists():
    p = Path(".claude/agents/vg-build-final-reviewer/SKILL.md")
    assert p.exists(), "vg-build-final-reviewer agent definition missing (v2.66.1 B4)"
    body = p.read_text(encoding="utf-8")
    # Must reference cumulative review (not per-task — that's B1's lane)
    assert re.search(
        r"(?:cumulative|entire|full|all)\s+(?:delta|tasks|phase|implementation)",
        body, re.IGNORECASE
    ), "final reviewer must explicitly target cumulative delta"


def test_final_reviewer_reads_plan_md():
    p = Path(".claude/agents/vg-build-final-reviewer/SKILL.md")
    body = p.read_text(encoding="utf-8")
    assert "PLAN.md" in body, "final reviewer must read PLAN.md as source of truth"


def test_close_md_spawns_final_reviewer():
    body = Path("commands/vg/_shared/build/close.md").read_text(encoding="utf-8")
    assert "vg-build-final-reviewer" in body, \
        "close.md must spawn final reviewer (v2.66.1 B4)"


def test_final_reviewer_returns_three_verdicts():
    p = Path(".claude/agents/vg-build-final-reviewer/SKILL.md")
    body = p.read_text(encoding="utf-8")
    # Must define PASS / PARTIAL / FAIL verdict semantics
    for v in ["PASS", "PARTIAL", "FAIL"]:
        assert v in body, f"final reviewer must define {v} verdict"
```

**Step 2: FAIL**

**Step 3: Create** `.claude/agents/vg-build-final-reviewer/SKILL.md`:

```markdown
---
name: vg-build-final-reviewer
description: |
  Cumulative delta reviewer. Runs once at end of build (after all waves +
  L-gates + postmortem). Reads PLAN.md goal + reviews ENTIRE phase commit
  range vs plan goal. Verdict: PASS | PARTIAL | FAIL. Advisory in v2.66.1
  (severity=warn). Will block in v2.67.0 after telemetry calibration.
allowed-tools:
  - Read
  - Bash
  - Grep
---

# vg-build-final-reviewer

You are the final cumulative reviewer for v2.66.1 B4. Run ONCE at end of build,
AFTER per-task spec reviewers (B1) and L-gates have passed. Your scope:
**did the implementation, taken as a whole, achieve the phase goal stated
in PLAN.md?**

## Input

- `phase_dir` — phase artifact directory containing PLAN.md
- `commit_range` — git revision range covering this phase's commits (e.g. `BUILD_START_SHA..HEAD`)

## Job

1. Read PLAN.md `Goal:` line + `Architecture:` paragraph
2. Run `git log --oneline ${commit_range}` to see all commits
3. For each task in PLAN.md, verify a corresponding commit exists
4. Read L-gate result files (L2, L3, L5, L6, truthcheck) — note any `WARN` or `FAIL`
5. Cross-task check: **does the cumulative delta actually deliver the phase Goal?**
   - Example: if Goal is "Add user auth", verify auth flow works end-to-end (not just individual tasks)
   - Look for integration gaps between tasks (e.g. Task 3 frontend uses an API Task 2 backend didn't implement)
6. Output structured verdict:

## Output format

```
## Cumulative Review — Phase {phase_number}

### Goal vs delivery
- **Phase goal:** {one-line from PLAN.md}
- **Commits in range:** {N}
- **Tasks planned:** {M}
- **Tasks with commits:** {K} of M

### Per-task commit map
- [✅/❌] Task 1: {title} — commit {sha} or MISSING
- ...

### L-gate roll-up
- L2 fingerprint: {PASS/WARN/FAIL count}
- L3 SSIM: ...

### Cross-task integration
- {check 1}: {finding}
- {check 2}: {finding}

### Verdict
**PASS** | **PARTIAL** | **FAIL** — {one-line reason}

### If PARTIAL/FAIL — gaps
1. {gap with file:line + remediation}
```

## Verdict semantics

- **PASS:** All planned tasks have commits, all L-gates pass, cross-task integration coherent, phase goal achieved
- **PARTIAL:** Some L-gates WARN OR 1-2 tasks missing OR cross-task gap detected. Build CONTINUES (advisory) but operator reviews
- **FAIL:** Multiple L-gates FAIL OR phase goal not achieved OR major integration gap. Build CONTINUES in v2.66.1 (severity=warn) but operator MUST review before /vg:test

## v2.67.0 future

Severity will flip to `block` in v2.67.0 once telemetry shows verdict
distribution + false-positive rate. For now, this is purely informational.
```

**Step 4: Wire in close.md** — add STEP 7.1.5 between postmortem and run-complete:

```markdown
### STEP 7.1.5 — B4 cumulative final review (v2.66.1)

After STEP 7.1 postmortem completes:

\`\`\`bash
BUILD_START_SHA=$(cat "${PHASE_DIR}/.build-start-sha" 2>/dev/null || git rev-parse HEAD~10)
COMMIT_RANGE="${BUILD_START_SHA}..HEAD"

bash scripts/vg-narrate-spawn.sh vg-build-final-reviewer spawning "cumulative review ${COMMIT_RANGE}"

# Then: Agent(subagent_type="vg-build-final-reviewer", prompt=<rendered with phase_dir + commit_range>)
\`\`\`

Marker: `7_1_5_final_review` (severity: warn — informational; will flip to block in v2.67.0).
```

**Step 5:** Mirror `commands/` ↔ `.claude/commands/`. Commit.

```bash
git commit -m "feat(build): B4 in-build final reviewer agent + close.md wiring (v2.66.1)"
```

---

## Task 6: VERSION + CHANGELOG + tag + push + close 2 issues

**Files:**
- Modify: `VERSION` (2.66.0 → 2.66.1)
- Modify: `package.json`
- Modify: `CHANGELOG.md` (prepend v2.66.1)

**CHANGELOG entry:**

```markdown
## v2.66.1 — Plan-fidelity followup + 2 deferred issues (2026-05-09)

### Bug fixes (closes 2 deferred dogfood issues)
- **#153 MEDIUM:** Review aggregator now clusters findings by API endpoint shape. 1 missing backend endpoint → 1 ROOT finding (severity escalated to MAJOR) + N child references — instead of N MINOR leaves that hide the upstream root cause. Findings without `api_endpoint` key pass through unchanged.
- **#154 MEDIUM:** `crossai_review.done` marker write now verdict-gated. When `verdict=inconclusive` or `ok_count=0`, writes `crossai_review.inconclusive` instead so `/vg:next` re-runs CrossAI on subsequent invocations.

### Plan-fidelity (B2-B4)
- **B2:** Implementer (`.claude/agents/vg-build-task-executor/SKILL.md`) RELAXED — may ask questions when capsule + plan slice are genuinely ambiguous (was: forbidden absolutely). Added mandatory 7-item self-review checklist before commit (scope creep, missing tests, mirror byte-identity, no VERSION bump, no --no-verify/amend, test count matches spec).
- **B3:** Planner (`.claude/agents/vg-blueprint-planner/SKILL.md`) now enforces 5-step TDD task body structure (failing test → confirm FAIL → minimal impl → confirm PASS → mirror + commit). Required for all `PLAN/task-NN.md` outputs.
- **B4:** New `.claude/agents/vg-build-final-reviewer/SKILL.md` cumulative reviewer agent. Runs once at end of build (STEP 7.1.5 in close.md), reads PLAN.md goal + entire phase commit range + L-gate results. Verdict: PASS/PARTIAL/FAIL. Severity=warn (advisory). Will flip to block in v2.67.0 after telemetry calibration.

### Test coverage
**14 new tests across 5 suites.** All pass.

### Migration
- **#153/#154:** Transparent bug fixes. No migration.
- **B2/B3/B4:** Behavioral changes only affect new builds. Existing in-progress phases unaffected. v2.67.0 will tighten B4 to blocking — operators have one minor cycle to adapt.

### Closes 8/8 dogfood issues
With v2.66.1, all 8 PrintwayV3 dogfood issues from 2026-05-09 are now closed. Roadmap continues with v2.67.0 C-tier strict review research adoptions.
```

**Steps:**
1. Bump VERSION + package.json
2. Prepend CHANGELOG entry
3. Commit: `release: v2.66.1 — plan-fidelity followup + 2 deferred issues`
4. Tag `v2.66.1`
5. Push origin main + tag
6. `gh release create v2.66.1 ...`
7. Close issues #153 #154 with v2.66.1 reference

---

## Verification

After each task: pytest pass + mirror byte-identity + no regression.

After Task 6:
- `git log --oneline | head -8` shows 6 commits (5 tasks + release)
- `cat VERSION` = `2.66.1`
- 14 new tests across 5 suites pass
- 2 GitHub issues closed (#153 #154)
- All 8 dogfood issues closed total

---

## Execution mode

Subagent-driven development. Per task: implementer → spec compliance check (manual via grep + plan re-read since B1 agent newly landed) → quality check (focused on diff scope creep) → mark complete → next.

Tasks 1-2 are issue fixes (~3+2h). Tasks 3-5 are agent template updates (~3h each). Task 6 release.
