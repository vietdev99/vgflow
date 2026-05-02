# VG R6b — Amend + Debug Workflows Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `vg-amend-impact-analyzer` and `vg-debug-classifier` subagents from `commands/vg/{amend,debug}.md`. Both entry skills stay below the 500-line slim ceiling; the refactor moves judgement-heavy analysis steps out of orchestrator AI context. Cap debug fix loop at 3 iterations (regression test). Add 7 pytest tests + 2 manual dogfood checklists.

**Architecture:** `amend.md` STEP 2 spawns `vg-amend-impact-analyzer` (read-only: scope+blueprint+plan+contracts+tests) which writes `RIPPLE-ANALYSIS.json`. `debug.md` STEP 2 spawns `vg-debug-classifier` (read-only + WebSearch) which writes `DEBUG-CLASSIFY.json`. Fix loop in `debug.md` STEP 4 stays in orchestrator (uses Edit/Write directly with user gate per iteration), hard-capped at 3.

**Tech Stack:** bash 5+, python3, pytest 7+, jsonschema 4+, PyYAML.

**Spec:** `docs/superpowers/specs/2026-05-03-vg-r6b-amend-debug-design.md`
**Depends on:** R5.5 hooks-source-isolation (subagent allow-list silence on non-VG dogfood).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `commands/vg/_shared/amend/severity-rules.md` | CREATE | Severity taxonomy (low/med/high) + reasoning rules |
| `commands/vg/_shared/debug/classify-taxonomy.md` | CREATE | Root-cause taxonomy (code/config/env/data) + ranking rules |
| `.claude/agents/vg-amend-impact-analyzer.md` | CREATE | Subagent — read CONTEXT + downstream → RIPPLE-ANALYSIS.json |
| `.claude/agents/vg-debug-classifier.md` | CREATE | Subagent — classify bug into ranked hypotheses |
| `commands/vg/amend.md` | REFACTOR | Delegate STEP 2 to analyzer (~330 lines total) |
| `commands/vg/debug.md` | REFACTOR | Delegate STEP 2 to classifier + cap fix loop at 3 (~390 lines total) |
| `scripts/hooks/vg-meta-skill.md` | EXTEND | Append amend + debug Red Flags |
| `tests/skills/test_amend_subagent_delegation.py` | CREATE | Assert STEP 2 spawns analyzer |
| `tests/skills/test_amend_telemetry_events.py` | CREATE | Assert frontmatter must_emit complete |
| `tests/skills/test_amend_ripple_schema.py` | CREATE | Assert RIPPLE-ANALYSIS schema parses |
| `tests/skills/test_debug_subagent_delegation.py` | CREATE | Assert STEP 2 spawns classifier |
| `tests/skills/test_debug_telemetry_events.py` | CREATE | Assert frontmatter must_emit complete |
| `tests/skills/test_debug_fix_loop_max_3.py` | CREATE | Assert fix loop hard-cap == 3 |
| `tests/skills/test_debug_classify_schema.py` | CREATE | Assert DEBUG-CLASSIFY schema parses |
| `tests/fixtures/amend/ripple-low.json` | CREATE | Schema fixture |
| `tests/fixtures/amend/ripple-high.json` | CREATE | Schema fixture |
| `tests/fixtures/debug/classify-3-hypotheses.json` | CREATE | Schema fixture |
| `tests/fixtures/debug/classify-1-hypothesis.json` | CREATE | Schema fixture |

---

## Task 1: Verify R5.5 merged + check skill-test infra

**Files:** read-only.

- [ ] **Step 1: Confirm R5.5 merged**

Run: `git log --oneline | grep -E 'r5\.5|hooks-source-isolation' | head -3`

Expected: at least one commit. If empty → STOP and execute R5.5 plan first.

- [ ] **Step 2: Check if `tests/skills/conftest.py` exists**

Run: `ls tests/skills/conftest.py 2>/dev/null && echo EXISTS || echo MISSING`

If `EXISTS` (R6a was executed first), continue to Task 2.

If `MISSING`, copy Task 2 setup from `docs/superpowers/plans/2026-05-03-vg-r6a-deploy.md` Task 2 — create `tests/skills/__init__.py` + `tests/skills/conftest.py` exactly as specified there.

- [ ] **Step 3: Snapshot current line counts**

Run: `wc -l commands/vg/amend.md commands/vg/debug.md`

Expected: 323 + 399. Both already under the 500-line slim ceiling — refactor is about delegation, not size reduction.

- [ ] **Step 4: Identify current STEP boundaries**

Run:
```bash
echo '=== amend.md ===' && grep -n '^## STEP' commands/vg/amend.md
echo '=== debug.md ===' && grep -n '^## STEP' commands/vg/debug.md
```

Record line numbers — refactor preserves these anchors.

- [ ] **Step 5: No commit (read-only)**

Skip.

---

## Task 2: Create _shared/amend/severity-rules.md

**Files:**
- Create: `commands/vg/_shared/amend/severity-rules.md`

- [ ] **Step 1: Create directory**

```bash
mkdir -p commands/vg/_shared/amend
```

- [ ] **Step 2: Write severity-rules.md**

Write to `commands/vg/_shared/amend/severity-rules.md`:

```markdown
# Amend — Severity Rules (Shared Reference)

Loaded by `vg-amend-impact-analyzer` subagent. Defines how the analyzer
classifies the severity of a single affected artifact.

## Severity levels

| Level | Meaning | Action |
|---|---|---|
| **high** | Affected artifact requires re-derivation; downstream guarantees broken | Recommend re-run originating skill (e.g. `/vg:blueprint`, `/vg:test-spec`) |
| **med**  | Artifact references the changed area; manual review needed but not full re-derive | Recommend targeted edit + verify |
| **low**  | Tangential reference; safe to leave as-is | Recommend annotate only (CONTEXT.md decision log) |

## Classification rules

For each downstream artifact, apply the following decision tree:

1. **Direct contract impact**
   - Endpoint signature change ↔ API-CONTRACTS file → **high**
   - Data shape change ↔ TEST-GOALS that read that shape → **high**
   - Field rename ↔ PLAN tasks that reference the field → **med**

2. **Behavioral impact (no contract change)**
   - Algorithm swap (e.g. sort order) ↔ TEST-GOALS that assert order → **high**
   - Internal refactor invisible to consumer → **low** (annotate only)

3. **Documentation/decision impact**
   - Decision in CONTEXT.md contradicted by change → **med** (update decision)
   - Old discussion log entry mentions feature → **low**

4. **Side-effect cascade**
   - Test fixtures used by changed code path → **med** (regenerate fixtures)
   - Migration scripts that depend on old shape → **high**

## Confidence scoring

Analyzer reports `confidence` ∈ {high, med, low}:
- **high** — direct ref grep hit + semantic match (e.g. exact endpoint name in API-CONTRACTS)
- **med** — indirect ref (e.g. helper function name match without semantic anchor)
- **low** — speculative impact based on file proximity only

Low-confidence findings should appear in RIPPLE-ANALYSIS but NOT trigger automatic recommended_action.

## Recommended action templates

The analyzer composes `recommended_action` from this set:

- `"rerun /vg:blueprint for phase, then /vg:test-spec"` — when ≥1 high in API-CONTRACTS or TEST-GOALS
- `"targeted edit in PLAN/task-NN.md, then re-run /vg:build wave N"` — when only PLAN-level med/high
- `"update CONTEXT.md decision log, no code change needed"` — when only low/med in CONTEXT.md
- `"manual review — analyzer cannot determine action"` — fallback when severity mix unclear
```

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/amend/severity-rules.md
git commit -m "docs(r6b): _shared/amend/severity-rules.md taxonomy

3-level severity scale + classification decision tree + confidence
scoring + recommended_action templates. Loaded by
vg-amend-impact-analyzer subagent (Task 4).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Create _shared/debug/classify-taxonomy.md

**Files:**
- Create: `commands/vg/_shared/debug/classify-taxonomy.md`

- [ ] **Step 1: Create directory**

```bash
mkdir -p commands/vg/_shared/debug
```

- [ ] **Step 2: Write classify-taxonomy.md**

Write to `commands/vg/_shared/debug/classify-taxonomy.md`:

```markdown
# Debug — Classify Taxonomy (Shared Reference)

Loaded by `vg-debug-classifier` subagent. Defines root-cause categories
and ranking rules for hypothesis generation.

## Root-cause types

| Type | Definition | Typical evidence |
|---|---|---|
| **code** | Bug in source code (logic error, race, off-by-one, missing await, type mismatch caught at runtime) | stack trace, error message matches source line |
| **config** | Wrong configuration (env var unset, wrong value, missing feature flag, bad TOML/JSON syntax) | startup log shows missing key, behavior changes between envs |
| **env** | Runtime environment issue (missing dep, wrong version, network reachability, file permissions, memory) | works locally / fails in target env, OS-level error |
| **data** | Bad input data (corrupt row, schema drift, encoding mismatch, missing required field) | error correlates with specific record IDs, recent data import |

## Ranking rules

For each candidate hypothesis, score:

- **Type-fit confidence** — how well evidence matches the type's typical pattern (high/med/low)
- **Reproducibility** — does the user's repro steps deterministically trigger the bug? (yes/intermittent/no)
- **Recency** — does the bug correlate with a recent change (commit, deploy, config push)? (yes/no/unknown)

Compute rank score:
- High type-fit + deterministic repro + recent change → rank 1
- High type-fit + intermittent repro → rank 2
- Med type-fit + any repro → rank 3+

Top 3 hypotheses returned. If only 1-2 are above the type-fit threshold,
return only what's confident.

## Hypothesis structure

Each hypothesis includes:

- `rank`           — 1-based, lower = more likely
- `type`           — one of {code, config, env, data}
- `file`           — path (best guess; null if not narrowable)
- `line`           — int (best guess; null if not narrowable)
- `hypothesis`     — one-sentence statement of root cause
- `evidence`       — list of strings, each citing a specific signal
- `confidence`     — high/med/low
- `suggested_fix`  — concrete one-line action (e.g. "add await keyword at line 42")

## WebSearch budget

Classifier MAY use WebSearch up to 3 queries per invocation, ONLY for
known-error-pattern lookup (e.g. "ECONNRESET race condition Node 22").
MUST NOT WebSearch for codebase-internal questions.

## When to return zero hypotheses

If evidence is insufficient (no error message, no file paths, no repro),
return `{hypotheses: []}` with `confidence: "low"`. Orchestrator will
prompt user for more info.
```

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/debug/classify-taxonomy.md
git commit -m "docs(r6b): _shared/debug/classify-taxonomy.md root-cause types

4 root-cause types (code/config/env/data) + ranking rules + hypothesis
structure + WebSearch budget. Loaded by vg-debug-classifier (Task 5).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Create vg-amend-impact-analyzer subagent

**Files:**
- Create: `.claude/agents/vg-amend-impact-analyzer.md`

- [ ] **Step 1: Write the subagent definition**

Write to `.claude/agents/vg-amend-impact-analyzer.md`:

```markdown
---
name: vg-amend-impact-analyzer
description: Analyze cascade impact of a mid-phase change request. Reads CONTEXT.md decisions + downstream artifacts (PLAN, API-CONTRACTS, TEST-GOALS, design refs), produces RIPPLE-ANALYSIS.json with affected list + severity + recommended action.
tools: Read, Grep, Bash
model: claude-sonnet-4-6
---

# vg-amend-impact-analyzer

Read-only impact analyzer for `/vg:amend`. Receives a change description
and produces a structured RIPPLE-ANALYSIS.json so the orchestrator can
present the cascade to the user before committing decisions.

## Input contract

You receive a JSON object with these fields:

- `phase`                 — phase ID (e.g. "P1")
- `change_description`    — free-text from user describing the requested change
- `current_artifacts_manifest` — list of paths under `.vg/phases/<phase>/` (orchestrator pre-enumerates; do NOT re-enumerate)
- `policy_ref`            — `commands/vg/_shared/amend/severity-rules.md`

## Workflow

### STEP A — Load policy

Read `commands/vg/_shared/amend/severity-rules.md`. Internalize:
- 3-level severity scale (low/med/high)
- Classification decision tree
- Confidence scoring rules
- Recommended-action templates

### STEP B — Read CONTEXT.md decisions

Read `.vg/phases/<phase>/CONTEXT.md`. Extract the existing decisions
list. Identify any that the `change_description` directly contradicts —
these are HIGH-severity by default (decision update required).

### STEP C — Traverse downstream artifacts

For each path in `current_artifacts_manifest`:
- Skip if not under `.vg/phases/<phase>/`.
- Read the file (or grep if file >100 KB).
- Apply the severity decision tree from STEP A.
- Build candidate `affected[]` entries.

Typical paths to check:
- `PLAN/task-*.md` (per-task split)
- `API-CONTRACTS/*.md` (per-endpoint split)
- `TEST-GOALS/G-*.md` (per-goal split)
- `DESIGN-REFS/*.md` (if present)
- `CONTEXT.md` (decisions section)

### STEP D — Compose recommended_action

Apply the template selection rules from STEP A. Pick the LEAST disruptive
template that covers all affected entries.

### STEP E — Write RIPPLE-ANALYSIS.json (atomic)

Write to `.vg/phases/<phase>/RIPPLE-ANALYSIS.json` (atomic — write
`.tmp` then mv).

Schema:

```json
{
  "phase": "<phase>",
  "change_summary": "<one-sentence summary of change_description>",
  "analyzed_at": "<ISO-8601 UTC>",
  "affected": [
    {
      "artifact": "<relative path under .vg/phases/<phase>/>",
      "severity": "low" | "med" | "high",
      "reason": "<one sentence>",
      "confidence": "high" | "med" | "low"
    }
  ],
  "recommended_action": "<from STEP A templates>",
  "confidence": "high" | "med" | "low"
}
```

If file size exceeds 30 KB advisory threshold, also write per-affected
split files at `RIPPLE-ANALYSIS/<artifact-slug>.md` (consumer pattern:
`vg-load --phase N --artifact ripple-analysis --affected <path>`).

### STEP F — Return on stdout

Print on the LAST line of stdout:

```json
{
  "status": "success",
  "ripple_path": ".vg/phases/<phase>/RIPPLE-ANALYSIS.json",
  "affected_count": <int>,
  "max_severity": "low" | "med" | "high"
}
```

## Tool restrictions

ALLOWED: Read, Grep, Bash (read-only — `cat`, `grep`, `wc`, `find`)
FORBIDDEN: Write\* (\*EXCEPTION: RIPPLE-ANALYSIS.json output via Write — no other writes), Edit, Agent, WebSearch

You MUST NOT modify CONTEXT.md or any source code. Orchestrator owns
those writes.

## Failure modes

| Cause | Action |
|---|---|
| `change_description` empty/unclear | Return `{status: "input_unclear", affected: []}` — orchestrator re-prompts |
| `phase` directory missing | Return `{status: "phase_missing"}` — orchestrator emits block |
| Manifest contains paths outside phase dir | Skip those paths; do NOT fail |
```

- [ ] **Step 2: Verify frontmatter parses**

Run:
```bash
python3 -c "
import yaml
text = open('.claude/agents/vg-amend-impact-analyzer.md').read()
end = text.find('\n---\n', 4)
fm = yaml.safe_load(text[4:end])
assert fm['name'] == 'vg-amend-impact-analyzer'
assert 'Read' in fm['tools']
assert 'Agent' not in fm['tools']
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/vg-amend-impact-analyzer.md
git commit -m "feat(r6b): vg-amend-impact-analyzer subagent

Read-only cascade analyzer. Workflow STEP A-F: load policy, read CONTEXT
decisions, traverse downstream artifacts, compose recommended_action,
write RIPPLE-ANALYSIS.json, return JSON on stdout. Tool-restricted to
Read/Grep/Bash + sole exception Write for the output file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Create vg-debug-classifier subagent

**Files:**
- Create: `.claude/agents/vg-debug-classifier.md`

- [ ] **Step 1: Write the subagent definition**

Write to `.claude/agents/vg-debug-classifier.md`:

```markdown
---
name: vg-debug-classifier
description: Classify a bug report into ranked root-cause hypotheses (code|config|env|data). Reads bug context + greps codebase for symptom patterns + bounded WebSearch for known patterns. Produces DEBUG-CLASSIFY.json with top hypotheses.
tools: Read, Grep, Bash, WebSearch
model: claude-sonnet-4-6
---

# vg-debug-classifier

Read-only bug classifier for `/vg:debug`. Receives a bug report and
produces a ranked DEBUG-CLASSIFY.json so the orchestrator can present
hypotheses to the user before fix-loop iterations.

## Input contract

You receive a JSON object with these fields:

- `bug_context`    — `{description, repro_steps, error_message?, file_paths?, recent_commits?}`
- `codebase_root`  — absolute path to the project root
- `policy_ref`     — `commands/vg/_shared/debug/classify-taxonomy.md`
- `run_id`         — orchestrator-assigned ID (use for output path)

## Workflow

### STEP A — Load taxonomy

Read `commands/vg/_shared/debug/classify-taxonomy.md`. Internalize:
- 4 root-cause types (code/config/env/data) and their typical evidence
- Ranking rules (type-fit + reproducibility + recency)
- Hypothesis structure
- WebSearch budget (3 queries max)
- When to return zero hypotheses

### STEP B — Anchor on evidence

Parse `bug_context.error_message` (if present). Extract:
- File path / line number from stack trace
- Exception class name
- Module/function name

If `bug_context.file_paths` provided, treat as confirmed loci.

If `bug_context.recent_commits` provided, run:
```bash
git log -p <recent_commits[0]>..<recent_commits[-1]> -- <file_paths> 2>/dev/null
```
to inspect the change diff.

### STEP C — Generate candidate hypotheses

Per loci identified:
- Read the source code around the line/function (Read tool).
- Match against typical evidence patterns (per type from taxonomy).
- Form a one-sentence hypothesis with `suggested_fix`.

If error message is unfamiliar, use WebSearch (max 3 queries):
- Query: `<error_message_first_60_chars> site:stackoverflow.com OR site:github.com`
- Cite top result URL in `evidence[]`.

### STEP D — Rank hypotheses

Apply ranking rules from STEP A. Score each candidate. Sort by score.
Truncate to top 3 (or fewer if confidence drops below med).

### STEP E — Write DEBUG-CLASSIFY.json (atomic)

Write to `.vg/debug/<run_id>/DEBUG-CLASSIFY.json`. Schema:

```json
{
  "bug_id": "<run_id>",
  "classified_at": "<ISO-8601 UTC>",
  "hypotheses": [
    {
      "rank": 1,
      "type": "code" | "config" | "env" | "data",
      "file": "<relative path or null>",
      "line": <int or null>,
      "hypothesis": "<one sentence>",
      "evidence": ["<signal 1>", "<signal 2>"],
      "confidence": "high" | "med" | "low",
      "suggested_fix": "<concrete action>"
    }
  ],
  "search_queries_run": ["<query string>"]
}
```

### STEP F — Return on stdout

Print on the LAST line of stdout:

```json
{
  "status": "success" | "insufficient_evidence",
  "classify_path": ".vg/debug/<run_id>/DEBUG-CLASSIFY.json",
  "hypothesis_count": <int>,
  "top_type": "code" | "config" | "env" | "data" | null
}
```

## Tool restrictions

ALLOWED: Read, Grep, Bash (read-only), WebSearch (≤3 queries)
FORBIDDEN: Write\* (\*EXCEPTION: DEBUG-CLASSIFY.json output via Write — no other writes), Edit, Agent, WebFetch

You MUST NOT modify code. Orchestrator owns the fix-loop edits in
`/vg:debug` STEP 4.

## Failure modes

| Cause | Action |
|---|---|
| `bug_context.description` empty | Return `{status: "insufficient_evidence", hypotheses: []}` |
| No error/file paths/commits | WebSearch from description; if still nothing → insufficient_evidence |
| Codebase root unreadable | Return `{status: "codebase_unreachable"}` |
```

- [ ] **Step 2: Verify frontmatter parses**

Run:
```bash
python3 -c "
import yaml
text = open('.claude/agents/vg-debug-classifier.md').read()
end = text.find('\n---\n', 4)
fm = yaml.safe_load(text[4:end])
assert fm['name'] == 'vg-debug-classifier'
assert 'WebSearch' in fm['tools']
assert 'Edit' not in fm['tools']
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/vg-debug-classifier.md
git commit -m "feat(r6b): vg-debug-classifier subagent

Read-only bug classifier. Workflow STEP A-F: load taxonomy, anchor on
evidence, generate candidate hypotheses, rank, write DEBUG-CLASSIFY.json,
return JSON on stdout. WebSearch budget capped at 3 queries.
Tool-restricted to Read/Grep/Bash/WebSearch + sole Write for output.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Schema fixtures + failing schema tests

**Files:**
- Create: `tests/fixtures/amend/ripple-low.json`
- Create: `tests/fixtures/amend/ripple-high.json`
- Create: `tests/fixtures/debug/classify-3-hypotheses.json`
- Create: `tests/fixtures/debug/classify-1-hypothesis.json`
- Create: `tests/skills/test_amend_ripple_schema.py`
- Create: `tests/skills/test_debug_classify_schema.py`

- [ ] **Step 1: Create fixture directories**

```bash
mkdir -p tests/fixtures/amend tests/fixtures/debug
```

- [ ] **Step 2: Write 4 fixture files**

Write to `tests/fixtures/amend/ripple-low.json`:

```json
{
  "phase": "P1",
  "change_summary": "Rename helper function getUserName to fetchUserName",
  "analyzed_at": "2026-05-03T14:30:00Z",
  "affected": [
    {
      "artifact": "PLAN/task-03.md",
      "severity": "low",
      "reason": "References function in task description prose",
      "confidence": "high"
    }
  ],
  "recommended_action": "update CONTEXT.md decision log, no code change needed",
  "confidence": "high"
}
```

Write to `tests/fixtures/amend/ripple-high.json`:

```json
{
  "phase": "P2",
  "change_summary": "Add OAuth2 to user-login endpoint, replacing session cookie auth",
  "analyzed_at": "2026-05-03T14:35:00Z",
  "affected": [
    {
      "artifact": "API-CONTRACTS/POST-user-login.md",
      "severity": "high",
      "reason": "Endpoint request/response shape changes (Bearer token replaces Set-Cookie)",
      "confidence": "high"
    },
    {
      "artifact": "PLAN/task-04.md",
      "severity": "med",
      "reason": "Task references current cookie-based session flow",
      "confidence": "high"
    },
    {
      "artifact": "TEST-GOALS/G-07.md",
      "severity": "high",
      "reason": "Test goal pre-dates OAuth2; assertions on Set-Cookie obsolete",
      "confidence": "high"
    },
    {
      "artifact": "CONTEXT.md",
      "severity": "med",
      "reason": "Decision D-03 says 'session cookies for v1'; contradicted",
      "confidence": "high"
    }
  ],
  "recommended_action": "rerun /vg:blueprint for phase, then /vg:test-spec",
  "confidence": "high"
}
```

Write to `tests/fixtures/debug/classify-3-hypotheses.json`:

```json
{
  "bug_id": "debug-run-001",
  "classified_at": "2026-05-03T15:00:00Z",
  "hypotheses": [
    {
      "rank": 1,
      "type": "code",
      "file": "src/auth/login.ts",
      "line": 42,
      "hypothesis": "Missing await on token validation; race condition under load",
      "evidence": [
        "Error 'Cannot read properties of undefined' matches async-race pattern",
        "git blame shows recent change to async flow at line 42 in commit abc123"
      ],
      "confidence": "high",
      "suggested_fix": "Add await keyword before validateToken() call at line 42"
    },
    {
      "rank": 2,
      "type": "config",
      "file": ".env.production",
      "line": null,
      "hypothesis": "JWT_SECRET env var unset in prod, falling back to default-empty",
      "evidence": [
        "Bug only reproduces in prod, not local",
        "validateToken() returns falsy when secret is empty"
      ],
      "confidence": "med",
      "suggested_fix": "Set JWT_SECRET in production env config"
    },
    {
      "rank": 3,
      "type": "data",
      "file": null,
      "line": null,
      "hypothesis": "User session table contains rows with null token_hash from migration",
      "evidence": [
        "Bug correlates with user accounts created before 2026-04-15"
      ],
      "confidence": "low",
      "suggested_fix": "Run backfill migration to populate token_hash for legacy rows"
    }
  ],
  "search_queries_run": [
    "Cannot read properties of undefined async race site:stackoverflow.com"
  ]
}
```

Write to `tests/fixtures/debug/classify-1-hypothesis.json`:

```json
{
  "bug_id": "debug-run-002",
  "classified_at": "2026-05-03T15:10:00Z",
  "hypotheses": [
    {
      "rank": 1,
      "type": "env",
      "file": null,
      "line": null,
      "hypothesis": "Disk full on /tmp, causing fs.writeFile to throw ENOSPC",
      "evidence": [
        "Error message contains 'ENOSPC: no space left on device'"
      ],
      "confidence": "high",
      "suggested_fix": "Free space on /tmp or move temp dir to a partition with more space"
    }
  ],
  "search_queries_run": []
}
```

- [ ] **Step 3: Write the schema test files**

Write to `tests/skills/test_amend_ripple_schema.py`:

```python
"""RIPPLE-ANALYSIS.json schema validation."""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "amend"

SEVERITY_ENUM = {"low", "med", "high"}
CONFIDENCE_ENUM = {"low", "med", "high"}
REQUIRED_TOP = {"phase", "change_summary", "analyzed_at", "affected",
                "recommended_action", "confidence"}
REQUIRED_AFFECTED = {"artifact", "severity", "reason", "confidence"}


@pytest.mark.parametrize(
    "fixture",
    sorted(FIXTURES.glob("ripple-*.json")),
    ids=lambda p: p.name,
)
def test_ripple_top_level_fields(fixture):
    data = json.loads(fixture.read_text())
    missing = REQUIRED_TOP - set(data)
    assert not missing, f"{fixture.name}: missing {missing}"
    assert data["confidence"] in CONFIDENCE_ENUM


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("ripple-*.json")), ids=lambda p: p.name)
def test_ripple_affected_entries_well_formed(fixture):
    data = json.loads(fixture.read_text())
    assert isinstance(data["affected"], list)
    for i, entry in enumerate(data["affected"]):
        missing = REQUIRED_AFFECTED - set(entry)
        assert not missing, f"{fixture.name}[{i}]: missing {missing}"
        assert entry["severity"] in SEVERITY_ENUM
        assert entry["confidence"] in CONFIDENCE_ENUM
```

Write to `tests/skills/test_debug_classify_schema.py`:

```python
"""DEBUG-CLASSIFY.json schema validation."""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "debug"

TYPE_ENUM = {"code", "config", "env", "data"}
CONFIDENCE_ENUM = {"low", "med", "high"}
REQUIRED_TOP = {"bug_id", "classified_at", "hypotheses", "search_queries_run"}
REQUIRED_HYPO = {"rank", "type", "file", "line", "hypothesis", "evidence",
                 "confidence", "suggested_fix"}


@pytest.mark.parametrize(
    "fixture",
    sorted(FIXTURES.glob("classify-*.json")),
    ids=lambda p: p.name,
)
def test_classify_top_level_fields(fixture):
    data = json.loads(fixture.read_text())
    missing = REQUIRED_TOP - set(data)
    assert not missing, f"{fixture.name}: missing {missing}"
    assert isinstance(data["search_queries_run"], list)


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("classify-*.json")), ids=lambda p: p.name)
def test_classify_hypotheses_well_formed(fixture):
    data = json.loads(fixture.read_text())
    assert isinstance(data["hypotheses"], list)
    assert len(data["hypotheses"]) <= 3, "max 3 hypotheses per spec"
    for i, hypo in enumerate(data["hypotheses"]):
        missing = REQUIRED_HYPO - set(hypo)
        assert not missing, f"{fixture.name}[{i}]: missing {missing}"
        assert hypo["type"] in TYPE_ENUM
        assert hypo["confidence"] in CONFIDENCE_ENUM
        assert hypo["rank"] == i + 1, "rank must equal index+1"
        assert isinstance(hypo["evidence"], list) and hypo["evidence"], (
            "evidence must be non-empty list"
        )


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("classify-*.json")), ids=lambda p: p.name)
def test_classify_websearch_budget(fixture):
    data = json.loads(fixture.read_text())
    assert len(data["search_queries_run"]) <= 3, "WebSearch budget exceeded"
```

- [ ] **Step 4: Run schema tests, expect ALL PASS**

Run: `python3 -m pytest tests/skills/test_amend_ripple_schema.py tests/skills/test_debug_classify_schema.py -v`

Expected: 4 + 6 = 10 passed (2 fixtures × 2 tests for amend, 2 fixtures × 3 tests for debug).

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/amend/ tests/fixtures/debug/ tests/skills/test_amend_ripple_schema.py tests/skills/test_debug_classify_schema.py
git commit -m "test(r6b): RIPPLE-ANALYSIS + DEBUG-CLASSIFY schema fixtures + tests

4 fixtures (2 ripple, 2 classify) covering low/high severity and
1/3-hypothesis cases. Parametrized schema validation tests lock the
JSON shapes from spec §4.1 and §4.2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Failing tests — amend delegation + telemetry

**Files:**
- Create: `tests/skills/test_amend_subagent_delegation.py`
- Create: `tests/skills/test_amend_telemetry_events.py`

- [ ] **Step 1: Write delegation test**

Write to `tests/skills/test_amend_subagent_delegation.py`:

```python
"""STEP 2 of amend.md MUST spawn vg-amend-impact-analyzer with narrate-spawn."""
import re

from .conftest import grep_count


def test_amend_step2_spawns_analyzer(skill_loader):
    skill = skill_loader("amend")
    body = skill["body"]
    spawn_refs = grep_count(
        body,
        r'subagent_type=["\']vg-amend-impact-analyzer["\']',
    )
    assert spawn_refs >= 1, (
        "amend.md does not spawn vg-amend-impact-analyzer; "
        "STEP 2 must call Agent(subagent_type='vg-amend-impact-analyzer', ...)"
    )


def test_amend_step2_wraps_spawn_with_narration(skill_loader):
    skill = skill_loader("amend")
    body = skill["body"]
    narrate_calls = grep_count(
        body,
        r"vg-narrate-spawn\.sh\s+vg-amend-impact-analyzer",
    )
    assert narrate_calls >= 2, (
        "amend.md MUST wrap analyzer spawn with at least 2 vg-narrate-spawn.sh "
        f"calls (spawning + returned/failed); found {narrate_calls}"
    )


def test_amend_within_500_lines(skill_loader):
    skill = skill_loader("amend")
    assert skill["lines"] <= 500, (
        f"commands/vg/amend.md is {skill['lines']} lines (limit 500)"
    )


def test_analyzer_agent_definition_exists(agent_loader):
    agent = agent_loader("vg-amend-impact-analyzer")
    assert agent["frontmatter"].get("name") == "vg-amend-impact-analyzer"
    tools = agent["frontmatter"].get("tools", "")
    assert "Agent" not in tools, "analyzer must not be allowed Agent (no nested spawns)"
    assert "Edit" not in tools, "analyzer is read-only — no Edit tool"
```

- [ ] **Step 2: Write telemetry test**

Write to `tests/skills/test_amend_telemetry_events.py`:

```python
"""amend frontmatter must_emit_telemetry MUST list analyzer + completion events."""

REQUIRED_EVENTS = {
    "amend.tasklist_shown",
    "amend.native_tasklist_projected",
    "amend.analyzer_spawned",
    "amend.analyzer_returned",
    "amend.analyzer_failed",
    "amend.ripple_presented",
    "amend.context_updated",
    "amend.completed",
}


def test_amend_telemetry_events_complete(skill_loader):
    skill = skill_loader("amend")
    fm = skill["frontmatter"]
    rc = fm.get("runtime_contract", {})
    emit = set(rc.get("must_emit_telemetry", []))
    missing = REQUIRED_EVENTS - emit
    assert not missing, (
        f"frontmatter must_emit_telemetry missing events: {missing}\n"
        f"current: {sorted(emit)}"
    )
```

- [ ] **Step 3: Run tests, expect mixed (delegation FAIL, agent-existence PASS, telemetry FAIL)**

Run: `python3 -m pytest tests/skills/test_amend_subagent_delegation.py tests/skills/test_amend_telemetry_events.py -v`

Expected:
- `test_amend_step2_spawns_analyzer` — FAIL (no spawn yet)
- `test_amend_step2_wraps_spawn_with_narration` — FAIL
- `test_amend_within_500_lines` — PASS (already 323)
- `test_analyzer_agent_definition_exists` — PASS (Task 4 created it)
- `test_amend_telemetry_events_complete` — FAIL (missing analyzer_* events)

- [ ] **Step 4: Commit failing tests**

```bash
git add tests/skills/test_amend_subagent_delegation.py tests/skills/test_amend_telemetry_events.py
git commit -m "test(r6b): failing tests — amend delegation + telemetry

Locks contract: STEP 2 spawns vg-amend-impact-analyzer with
narrate-spawn wrap; frontmatter emits analyzer_{spawned,returned,failed}
+ ripple_presented + context_updated + completed.

Refactor in next task makes them pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Refactor amend.md — delegate STEP 2

**Files:**
- Modify: `commands/vg/amend.md` (frontmatter + STEP 2 body)

- [ ] **Step 1: Update frontmatter must_emit_telemetry**

In `commands/vg/amend.md` frontmatter, ensure `runtime_contract.must_emit_telemetry` lists ALL of:

```yaml
- "amend.tasklist_shown"
- "amend.native_tasklist_projected"
- "amend.analyzer_spawned"
- "amend.analyzer_returned"
- "amend.analyzer_failed"
- "amend.ripple_presented"
- "amend.context_updated"
- "amend.completed"
```

Add any missing entries (preserve existing ones).

- [ ] **Step 2: Replace STEP 2 body with analyzer-spawn pattern**

Locate the current STEP 2 section (between `## STEP 2` heading and the next `## STEP` heading). Replace its body with:

```markdown
## STEP 2 — Spawn vg-amend-impact-analyzer

Load contract: `commands/vg/_shared/amend/severity-rules.md` (analyzer
will load this too — orchestrator does not need the full table, only
the awareness that the analyzer applies it).

### 2.1 Pre-spawn narrate (green pill)

```bash
bash scripts/vg-narrate-spawn.sh vg-amend-impact-analyzer spawning "phase=$PHASE"
vg-orchestrator emit-event amend.analyzer_spawned --gate STEP-2 \
  --payload "{\"phase\":\"$PHASE\"}"
```

### 2.2 Build manifest + spawn

Enumerate current artifacts:

```bash
manifest=$(find ".vg/phases/$PHASE/" -type f \
  \( -name '*.md' -o -name '*.json' \) \
  -not -path '*/.step-markers/*' \
  -not -path '*/.deploy-log*' \
  | sort)
```

Spawn:

```
Agent(
  subagent_type="vg-amend-impact-analyzer",
  prompt={
    "phase": "<phase>",
    "change_description": "<from STEP 1 user input>",
    "current_artifacts_manifest": <manifest as JSON list>,
    "policy_ref": "commands/vg/_shared/amend/severity-rules.md"
  }
)
```

### 2.3 Post-spawn narrate

On success:

```bash
bash scripts/vg-narrate-spawn.sh vg-amend-impact-analyzer returned "affected=$N max_severity=$SEV"
vg-orchestrator emit-event amend.analyzer_returned --gate STEP-2 \
  --payload "{\"affected_count\":$N,\"max_severity\":\"$SEV\"}"
```

On failure (status ∈ {input_unclear, phase_missing}):

```bash
bash scripts/vg-narrate-spawn.sh vg-amend-impact-analyzer failed "<one-line cause>"
vg-orchestrator emit-event amend.analyzer_failed --gate STEP-2 \
  --payload "{\"status\":\"$STATUS\"}"
```

If `status == "input_unclear"`, return to STEP 1 to re-prompt user.
If `status == "phase_missing"`, emit hard block.

### 2.4 Read RIPPLE-ANALYSIS.json

Read the file the analyzer wrote at `.vg/phases/$PHASE/RIPPLE-ANALYSIS.json`.
Validate top-level fields (phase, affected[], recommended_action,
confidence). On schema mismatch, emit block `Amend-Ripple-Schema-Mismatch`.
```

- [ ] **Step 3: Run amend tests, expect ALL PASS**

Run: `python3 -m pytest tests/skills/test_amend_subagent_delegation.py tests/skills/test_amend_telemetry_events.py -v`

Expected: 5 passed.

- [ ] **Step 4: Append References footer (if not present)**

At end of `commands/vg/amend.md`, ensure this block exists:

```markdown
---

## References

- Severity taxonomy: `commands/vg/_shared/amend/severity-rules.md`
- Analyzer subagent: `.claude/agents/vg-amend-impact-analyzer.md`
- UX baseline: `docs/superpowers/specs/_shared-ux-baseline.md`
- R6b design spec: `docs/superpowers/specs/2026-05-03-vg-r6b-amend-debug-design.md`
```

- [ ] **Step 5: Commit**

```bash
git add commands/vg/amend.md
git commit -m "refactor(r6b): amend.md STEP 2 — delegate to vg-amend-impact-analyzer

Cascade impact analysis moved to subagent. STEP 2 now: build manifest,
spawn (narrate green), receive return (narrate cyan/red), read
RIPPLE-ANALYSIS.json, validate schema. Frontmatter telemetry expanded
with analyzer_{spawned,returned,failed} + ripple_presented +
context_updated + completed.

All 5 amend pytest tests pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Failing tests — debug delegation + telemetry + fix loop max 3

**Files:**
- Create: `tests/skills/test_debug_subagent_delegation.py`
- Create: `tests/skills/test_debug_telemetry_events.py`
- Create: `tests/skills/test_debug_fix_loop_max_3.py`

- [ ] **Step 1: Write delegation test**

Write to `tests/skills/test_debug_subagent_delegation.py`:

```python
"""STEP 2 of debug.md MUST spawn vg-debug-classifier with narrate-spawn."""
import re

from .conftest import grep_count


def test_debug_step2_spawns_classifier(skill_loader):
    skill = skill_loader("debug")
    body = skill["body"]
    spawn_refs = grep_count(
        body,
        r'subagent_type=["\']vg-debug-classifier["\']',
    )
    assert spawn_refs >= 1


def test_debug_step2_wraps_spawn_with_narration(skill_loader):
    skill = skill_loader("debug")
    body = skill["body"]
    narrate_calls = grep_count(
        body,
        r"vg-narrate-spawn\.sh\s+vg-debug-classifier",
    )
    assert narrate_calls >= 2


def test_debug_within_500_lines(skill_loader):
    skill = skill_loader("debug")
    assert skill["lines"] <= 500


def test_classifier_agent_definition_exists(agent_loader):
    agent = agent_loader("vg-debug-classifier")
    assert agent["frontmatter"].get("name") == "vg-debug-classifier"
    tools = agent["frontmatter"].get("tools", "")
    assert "Agent" not in tools
    assert "Edit" not in tools
```

- [ ] **Step 2: Write telemetry test**

Write to `tests/skills/test_debug_telemetry_events.py`:

```python
"""debug frontmatter must_emit_telemetry MUST list classifier + fix loop events."""

REQUIRED_EVENTS = {
    "debug.tasklist_shown",
    "debug.native_tasklist_projected",
    "debug.classifier_spawned",
    "debug.classifier_returned",
    "debug.classifier_failed",
    "debug.fix_attempted",
    "debug.fix_loop_exhausted",
    "debug.user_verified",
    "debug.completed",
}


def test_debug_telemetry_events_complete(skill_loader):
    skill = skill_loader("debug")
    fm = skill["frontmatter"]
    rc = fm.get("runtime_contract", {})
    emit = set(rc.get("must_emit_telemetry", []))
    missing = REQUIRED_EVENTS - emit
    assert not missing, (
        f"frontmatter must_emit_telemetry missing events: {missing}\n"
        f"current: {sorted(emit)}"
    )
```

- [ ] **Step 3: Write fix-loop max-3 test**

Write to `tests/skills/test_debug_fix_loop_max_3.py`:

```python
"""debug.md fix loop in STEP 4 MUST be hard-capped at 3 iterations."""
import re


def test_fix_loop_explicit_max_3(skill_loader):
    """Body must contain a literal '3' iteration cap reference in STEP 4."""
    skill = skill_loader("debug")
    body = skill["body"]
    step4_match = re.search(
        r"^## STEP 4(.*?)^## STEP 5",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert step4_match, "STEP 4 section not found in debug.md"
    step4 = step4_match.group(1)
    # Look for explicit "3 iteration" or "max 3" or "iteration < 3" or "iteration_count < 3"
    cap_patterns = [
        r"max(?:\s+|\s*=\s*|imum\s+)3\s+iteration",
        r"3\s+iteration\s+max",
        r"hard[-\s]?cap\w*\s+(?:at\s+|of\s+)?3",
        r"iteration\s*[<≤]=?\s*3",
        r"iteration_count\s*[<≤]=?\s*3",
    ]
    found = any(re.search(p, step4, flags=re.IGNORECASE) for p in cap_patterns)
    assert found, (
        "STEP 4 must explicitly state the fix loop is capped at 3 iterations. "
        "Use one of: 'max 3 iterations', '3 iteration max', 'hard-cap at 3', "
        "'iteration < 3', 'iteration_count < 3'."
    )


def test_fix_loop_exhausted_event_referenced(skill_loader):
    """STEP 4 must reference debug.fix_loop_exhausted on cap-hit path."""
    skill = skill_loader("debug")
    body = skill["body"]
    assert "debug.fix_loop_exhausted" in body, (
        "STEP 4 must emit debug.fix_loop_exhausted when iteration == 3 "
        "without resolution"
    )
```

- [ ] **Step 4: Run tests, expect mixed**

Run: `python3 -m pytest tests/skills/test_debug_subagent_delegation.py tests/skills/test_debug_telemetry_events.py tests/skills/test_debug_fix_loop_max_3.py -v`

Expected:
- delegation tests — FAIL (no spawn yet)
- agent-existence — PASS (Task 5 created it)
- telemetry — FAIL
- within_500_lines — PASS (399 already)
- fix_loop tests — FAIL (no explicit cap yet)

- [ ] **Step 5: Commit failing tests**

```bash
git add tests/skills/test_debug_subagent_delegation.py tests/skills/test_debug_telemetry_events.py tests/skills/test_debug_fix_loop_max_3.py
git commit -m "test(r6b): failing tests — debug delegation + telemetry + fix loop cap

Locks: STEP 2 spawns vg-debug-classifier with narrate; frontmatter
emits classifier_{spawned,returned,failed} + fix_attempted +
fix_loop_exhausted + user_verified + completed; STEP 4 fix loop
hard-capped at 3 iterations.

Refactor in next task makes them pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Refactor debug.md — delegate STEP 2 + cap STEP 4

**Files:**
- Modify: `commands/vg/debug.md`

- [ ] **Step 1: Update frontmatter must_emit_telemetry**

Add (preserving existing entries) to `runtime_contract.must_emit_telemetry`:

```yaml
- "debug.tasklist_shown"
- "debug.native_tasklist_projected"
- "debug.classifier_spawned"
- "debug.classifier_returned"
- "debug.classifier_failed"
- "debug.fix_attempted"
- "debug.fix_loop_exhausted"
- "debug.user_verified"
- "debug.completed"
```

- [ ] **Step 2: Replace STEP 2 body with classifier-spawn pattern**

Locate STEP 2. Replace body with:

```markdown
## STEP 2 — Spawn vg-debug-classifier

Load contract: `commands/vg/_shared/debug/classify-taxonomy.md` (the
classifier will load it too).

### 2.1 Pre-spawn narrate

```bash
bash scripts/vg-narrate-spawn.sh vg-debug-classifier spawning "bug=$BUG_SHORT"
vg-orchestrator emit-event debug.classifier_spawned --gate STEP-2 \
  --payload "{\"run_id\":\"$RUN_ID\"}"
```

### 2.2 Spawn

```
Agent(
  subagent_type="vg-debug-classifier",
  prompt={
    "bug_context": <from STEP 1 user input — description, repro_steps, error_message?, file_paths?, recent_commits?>,
    "codebase_root": "<git rev-parse --show-toplevel>",
    "policy_ref": "commands/vg/_shared/debug/classify-taxonomy.md",
    "run_id": "<RUN_ID>"
  }
)
```

### 2.3 Post-spawn narrate

On success (status ∈ {success, insufficient_evidence}):

```bash
bash scripts/vg-narrate-spawn.sh vg-debug-classifier returned "hypotheses=$N top_type=$TYPE"
vg-orchestrator emit-event debug.classifier_returned --gate STEP-2 \
  --payload "{\"hypothesis_count\":$N,\"top_type\":\"$TYPE\"}"
```

On failure (status == "codebase_unreachable"):

```bash
bash scripts/vg-narrate-spawn.sh vg-debug-classifier failed "codebase unreachable"
vg-orchestrator emit-event debug.classifier_failed --gate STEP-2 \
  --payload "{\"cause\":\"codebase_unreachable\"}"
```

If `status == "insufficient_evidence"`, return to STEP 1 to gather more
info from user.

### 2.4 Read DEBUG-CLASSIFY.json

Read `.vg/debug/<RUN_ID>/DEBUG-CLASSIFY.json`. Validate hypotheses[]
schema. On mismatch → emit block `Debug-Classify-Schema-Mismatch`.
```

- [ ] **Step 3: Replace STEP 4 body — fix loop with explicit max-3 cap**

Locate STEP 4. Replace body with:

```markdown
## STEP 4 — Fix Loop (hard-cap at 3 iterations)

Iterate over hypotheses ranked 1..N. The loop is hard-capped at
`iteration_count < 3` — under no circumstance attempt a 4th iteration
without restarting the skill.

```bash
iteration_count=0
resolved=false

while [ "$iteration_count" -lt 3 ] && [ "$resolved" = "false" ]; do
  iteration_count=$((iteration_count + 1))
  hypothesis="${HYPOTHESES[$((iteration_count - 1))]}"

  # 4.1 Apply candidate fix using Edit/Write directly.
  #     Orchestrator AI inspects the hypothesis suggested_fix field
  #     and applies the change. NO subagent spawn here — fix is in
  #     orchestrator context so the user can review every Edit call.

  vg-orchestrator emit-event debug.fix_attempted --gate STEP-4 \
    --payload "{\"iteration\":$iteration_count,\"hypothesis_rank\":$iteration_count}"

  # 4.2 Ask user if fix worked.
  #     AskUserQuestion: "Did the fix resolve the bug? (yes/no)"
  if [ "$USER_REPLY" = "yes" ]; then
    resolved=true
  fi
done

if [ "$resolved" = "false" ]; then
  vg-orchestrator emit-event debug.fix_loop_exhausted --gate STEP-4 \
    --payload "{\"iterations_run\":$iteration_count}"
  # Surface to user: "Tried 3 hypotheses, none resolved. Status=unresolved."
fi
```

### Cap rationale

3 iterations balances thoroughness with cost. After 3 failed attempts,
the classifier's hypothesis pool is likely wrong for this bug —
returning to /vg:debug with refined evidence is better than continuing.
```

- [ ] **Step 4: Append References footer (if not present)**

```markdown
---

## References

- Classify taxonomy: `commands/vg/_shared/debug/classify-taxonomy.md`
- Classifier subagent: `.claude/agents/vg-debug-classifier.md`
- Bug detection guide: `vg:_shared:bug-detection-guide`
- UX baseline: `docs/superpowers/specs/_shared-ux-baseline.md`
- R6b design spec: `docs/superpowers/specs/2026-05-03-vg-r6b-amend-debug-design.md`
```

- [ ] **Step 5: Run all debug tests, expect ALL PASS**

Run: `python3 -m pytest tests/skills/test_debug_subagent_delegation.py tests/skills/test_debug_telemetry_events.py tests/skills/test_debug_fix_loop_max_3.py -v`

Expected: 4 + 1 + 2 = 7 passed.

- [ ] **Step 6: Commit**

```bash
git add commands/vg/debug.md
git commit -m "refactor(r6b): debug.md STEP 2 + STEP 4 — delegate + cap fix loop

STEP 2: classify moved to vg-debug-classifier subagent. STEP 4: fix
loop hard-capped at 3 iterations via while [\$iteration_count -lt 3];
emits debug.fix_attempted per iter and debug.fix_loop_exhausted on
cap-hit. Frontmatter telemetry expanded.

All 7 debug pytest tests pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: vg-meta-skill.md — append amend + debug Red Flags

**Files:**
- Modify: `scripts/hooks/vg-meta-skill.md`

- [ ] **Step 1: Append amend Red Flags section**

Append at end of `scripts/hooks/vg-meta-skill.md`:

```markdown

## Amend-specific Red Flags

| Thought | Reality |
|---|---|
| "Skip cascade impact analysis — change is small" | Mid-phase change impacts downstream artifacts; analyzer surfaces what you'd miss |
| "Inline analyzer logic in entry — easier to maintain" | R6b explicitly extracts to subagent; orchestrator AI context stays slim |
| "Auto-update CONTEXT.md without user confirm" | User confirm is mandatory — decisions are append-only audit log |
| "Skip narrate-spawn for analyzer — it's read-only" | UX consistency matters; chip-style status applies to all spawns |

## Debug-specific Red Flags

| Thought | Reality |
|---|---|
| "Skip classification, jump to fix" | Targeted bug-fix requires classifier output; jumping = guess work |
| "Bump fix loop to 4 iterations — almost there" | Hard-cap 3 is intentional; 4th iter = restart with refined evidence |
| "Verify with user fast, just confirm" | User verification gate is mandatory; theatre-confirm = bug returns |
| "Apply fix in subagent — keep orchestrator clean" | Fix-applier MUST stay in orchestrator so user reviews every Edit |
| "Skip WebSearch — codebase is enough" | WebSearch budget (3 queries) is for unfamiliar error patterns; use it |
```

- [ ] **Step 2: Verify markdown parses**

Run: `python3 -c "from pathlib import Path; t = Path('scripts/hooks/vg-meta-skill.md').read_text(); assert t.count('|') > 100; print('OK')"`

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add scripts/hooks/vg-meta-skill.md
git commit -m "docs(r6b): vg-meta-skill.md — amend + debug Red Flags

4 amend entries (impact-skip, inline-analyzer, auto-update, narrate-skip)
+ 5 debug entries (skip-classify, bump-loop, theatre-verify, fix-in-
subagent, skip-websearch).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Manual dogfood — amend + debug

**Files:** none modified.

- [ ] **Step 1: amend dogfood — preconditions**

Pick a phase that has multiple artifacts (PLAN/, API-CONTRACTS/,
TEST-GOALS/, CONTEXT.md). A phase with the per-task split format from
R1a blueprint pilot is ideal.

- [ ] **Step 2: Run /vg:amend <phase>**

In the test project:

```
/vg:amend P1
```

When STEP 1 prompts: enter a meaningful change description, e.g.
`"Rename POST /users endpoint to POST /accounts; update response shape"`.

- [ ] **Step 3: Verify amend chip narration + ripple**

Look for:
- 🟢 green pill: `vg-amend-impact-analyzer spawning phase=P1`
- 🔵 cyan pill: `vg-amend-impact-analyzer returned affected=N max_severity=high`
- RIPPLE-ANALYSIS shown to you with ≥2 affected entries
- AskUserQuestion: "Apply change?"

- [ ] **Step 4: Verify RIPPLE-ANALYSIS.json on disk**

```bash
cat .vg/phases/P1/RIPPLE-ANALYSIS.json | python3 -m json.tool
```

Verify:
- All 6 top-level fields (phase, change_summary, analyzed_at, affected, recommended_action, confidence)
- ≥1 entry in affected[]
- recommended_action matches one of the templates from severity-rules.md

- [ ] **Step 5: Verify amend telemetry**

```bash
sqlite3 .vg/events.db \
  "SELECT event_type FROM events WHERE event_type LIKE 'amend.%' ORDER BY id DESC LIMIT 10"
```

Expected (most recent first): `amend.completed`, `amend.context_updated`,
`amend.ripple_presented`, `amend.analyzer_returned`, `amend.analyzer_spawned`,
`amend.native_tasklist_projected`, `amend.tasklist_shown`.

- [ ] **Step 6: debug dogfood — preconditions**

Use any project. Have a contrived bug ready, e.g. introduce a typo in a
known function name and ensure the error message references the file.

- [ ] **Step 7: Run /vg:debug**

```
/vg:debug
```

When STEP 1 prompts:
- description: `"login fails with 500 on prod"`
- repro_steps: `"POST /auth/login with valid creds → 500"`
- error_message: `"Cannot read properties of undefined (reading 'token')"`
- file_paths: `"src/auth/login.ts"`
- recent_commits: leave blank (or add the commit you contrived)

- [ ] **Step 8: Verify debug chip narration + classify**

Look for:
- 🟢 green pill: `vg-debug-classifier spawning bug=login fails with 500...`
- 🔵 cyan pill: `vg-debug-classifier returned hypotheses=N top_type=code`
- Top-3 hypotheses shown to you
- AskUserQuestion: "Which hypothesis to try first?"

- [ ] **Step 9: Verify DEBUG-CLASSIFY.json**

```bash
cat .vg/debug/*/DEBUG-CLASSIFY.json | python3 -m json.tool
```

Verify:
- bug_id, classified_at, hypotheses[], search_queries_run present
- ≤3 hypotheses; ranks 1, 2, 3
- Each hypothesis has all 8 required fields

- [ ] **Step 10: Verify fix loop cap**

Reject the first 3 fixes by answering "no" to the verify question each
time. Verify:
- Loop stops after iteration 3 (do NOT see iteration 4)
- `debug.fix_loop_exhausted` event emitted
- Skill closes with status=unresolved

- [ ] **Step 11: Verify debug telemetry**

```bash
sqlite3 .vg/events.db \
  "SELECT event_type FROM events WHERE event_type LIKE 'debug.%' ORDER BY id DESC LIMIT 15"
```

Expected events present: classifier_spawned/returned, fix_attempted (×3),
fix_loop_exhausted, user_verified, completed.

- [ ] **Step 12: Final summary**

R6b ship-ready when ALL above pass:
- amend dogfood: chip narration + RIPPLE-ANALYSIS valid + telemetry complete.
- debug dogfood: chip narration + DEBUG-CLASSIFY valid + fix loop stops at 3 + telemetry complete.
- All 12 R6b pytest tests pass.
- R5.5 + R6a tests still pass (no regression).

Optional tag:

```bash
git tag -a r6b-amend-debug-dedicated -m "R6b amend+debug subagent extraction"
```

---

## Self-Review

**Spec coverage check:**

| Spec § | Task(s) |
|---|---|
| §3.1 amend flow (orchestrator + analyzer split) | Tasks 4 (analyzer), 8 (entry refactor) |
| §3.2 debug flow (orchestrator + classifier split, 3-iter cap) | Tasks 5 (classifier), 10 (entry refactor) |
| §3.3 Slim entry constraints | Tasks 7+9 (within_500_lines tests) |
| §4.1 vg-amend-impact-analyzer contract | Task 4 |
| §4.2 vg-debug-classifier contract | Task 5 |
| §5 File and directory layout | All tasks (each row mapped) |
| §6.1 amend telemetry events (8) | Tasks 7 (telem test), 8 (frontmatter update) |
| §6.2 debug telemetry events (9) | Tasks 9 (telem test), 10 (frontmatter update) |
| §7.1 Error handling (subagent fail, fix loop exhaustion, schema validation) | Tasks 8 (analyzer fail paths), 10 (fix-loop cap + emit), 6 (schema tests) |
| §7.2 Migration (pre-R6b artifacts parse) | Task 6 (RIPPLE fixtures parse) |
| §7.3 Pytest static + manual dogfood | Tasks 6, 7, 9, 12 |
| §7.4 Exit criteria 1-6 | Task 12 step 12 (summary) |
| §10 UX baseline | Tasks 8, 10 (narration), 11 (Red Flags) |

No gaps detected.

**Placeholder scan:** searched for TBD/TODO — none in plan body.

**Type/path consistency:**
- Subagent names `vg-amend-impact-analyzer`, `vg-debug-classifier` consistent across spec, agent files, delegation steps in entries, all 4 pytest files referencing them.
- RIPPLE-ANALYSIS.json field names (`phase`, `change_summary`, `analyzed_at`, `affected[].{artifact,severity,reason,confidence}`, `recommended_action`, `confidence`) consistent across schema doc, fixtures, schema test, analyzer subagent STEP E, orchestrator STEP 2.4.
- DEBUG-CLASSIFY.json field names (`bug_id`, `classified_at`, `hypotheses[].{rank,type,file,line,hypothesis,evidence,confidence,suggested_fix}`, `search_queries_run`) consistent across same trio.
- Telemetry event names consistent across telem tests, STEP 2 emit calls, STEP 4 emit calls (debug only), vg-meta-skill Red Flags.
- Severity enum {low, med, high} used consistently in fixtures, schema test, severity-rules.md.
- Type enum {code, config, env, data} used consistently in fixtures, schema test, classify-taxonomy.md.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-03-vg-r6b-amend-debug.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
