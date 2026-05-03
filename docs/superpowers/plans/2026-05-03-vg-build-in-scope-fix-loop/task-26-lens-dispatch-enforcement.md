<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->

## Task 26: Lens dispatch enforcement (AI-trust-by-design)

**Files:**
- Create: `schemas/lens-dispatch-plan.schema.json` (canonical dispatch manifest schema)
- Create: `scripts/lens-dispatch/emit-dispatch-plan.py` (emitter — generates LENS-DISPATCH-PLAN.json)
- Create: `scripts/validators/verify-lens-runs-coverage.py` (generalized coverage gate, all lenses)
- Create: `scripts/validators/verify-lens-action-trace.py` (M2 — MCP log vs self-reported actions cross-check)
- Create: `scripts/lib/lens_tier_dispatcher.py` (M1 — tier-aware spawn helper)
- Create: `scripts/aggregators/lens-coverage-matrix.py` (LENS-COVERAGE-MATRIX.md renderer)
- Modify: `commands/vg/_shared/lens-prompts/_TEMPLATE.md` (frontmatter: min_actions_floor, min_evidence_steps, required_probe_kinds, recommended_worker_tier, worker_complexity_score, fallback_on_inconclusive)
- Modify: each `commands/vg/_shared/lens-prompts/lens-*.md` (add new frontmatter fields per lens)
- Modify: `scripts/spawn_recursive_probe.py` (use lens_tier_dispatcher, write LENS-DISPATCH-PLAN.json before spawn, log MCP trace)
- Modify: `scripts/challenge-coverage.py` (recursive scan fix — `runs/<tool>/...` subdirs, not just root)
- Modify: `commands/vg/review.md` Phase 2.5 wiring (write dispatch plan first, run coverage gate after)
- Modify: `scripts/emit-tasklist.py` (grouped counters NOT leaf tasks per lens × goal)
- Test: `tests/test_lens_dispatch_enforcement.py`

**Why (Codex GPT-5.5 round 5 review 2026-05-03 + sếp's AI-trust concern):**

VG already enforces a chain for `kit:crud-roundtrip`: declared plan → spawn → schema-valid run artifact → coverage gate → 25% sample challenge → replay. But the chain only covers crud-roundtrip kit; recursive lens probes (form-lifecycle, business-coherence, idor, csrf, etc) get planned but NO equivalent gate ensures they actually executed with sufficient depth.

User's concern, exact translation: "I'm still concerned that during /vg:review, lens may not be injected, or even if injected, the AI may not actually treat it as a rule to check. What evidence guarantees the discovery bot actually covers those lenses for checking?"

Answer: today, NONE for non-CRUD lenses. Plus a deeper concern raised after Codex round 5: discovery agent runs on a CHEAPER model (Haiku) to reduce cost — but Haiku's reasoning capability is bounded. It may follow lens prompt protocol literally but skip "DIG on anomaly" branches, return all `status: pass` without actually probing, miss subtle invariants requiring multi-layer reasoning.

This task closes the loop with **post-hoc verification + runtime enforcement + capability-matched dispatch**:

1. **Generic dispatch manifest** (Codex correction: trust anchor — current `review-lens-plan.py` is plugin-level, not exact `lens × goal` dispatch). New `LENS-DISPATCH-PLAN.json` emitted by spawner BEFORE workers spawn. All gates consume this single source.
2. **Coverage gate generalized** beyond crud-roundtrip — every dispatch has matching artifact with structural integrity (BLOCK day 1).
3. **M1 — Tier-aware spawn** (NEW per sếp's concern): each lens declares `recommended_worker_tier` + `worker_complexity_score`. Spawner picks model accordingly. Lens with complexity ≥ 4 (form-lifecycle, business-coherence) require Sonnet+, NOT Haiku. Fallback to higher tier on `INCONCLUSIVE`.
4. **M2 — MCP action-trace cross-check** (NEW): MCP server logs every browser action externally. Gate cross-references log count vs artifact's `actions_taken`. Mismatch = AI faked work. Worker CANNOT fake without producing actual MCP calls.
5. **7-state coverage matrix** (Codex correction): PASS / FAIL / INCONCLUSIVE / N/A / SKIPPED_BY_POLICY / SKIPPED_BY_OVERRIDE / MISSING. Gate BLOCKs only MISSING. Policy skips require manifest entry recording reason.
6. **Phase-in severity** (Codex correction): structural integrity BLOCK day 1; `actions_taken` floor ADVISORY for 2 weeks then promote.
7. **Recursive scan fix** (Codex correction): existing `challenge-coverage.py:47` only scans root `runs/*.json`; recursive probes write `runs/<tool>/...` (`spawn_recursive_probe.py:564`). Update glob.
8. **Grouped tasklist counters** (Codex correction): 160 leaf tasks = UI noise. Show counters, expand only failures.

**Skip M3 (sample re-run with different model)** for now per sếp's cost-cap preference. Promote to Task 27 if telemetry shows fake rate > threshold after 2 weeks.

---

### Deliverable 1 — LENS-DISPATCH-PLAN.json schema (trust anchor)

Create `schemas/lens-dispatch-plan.schema.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "LensDispatchPlan",
  "description": "Canonical manifest of expected (lens × goal/element/role) dispatches for a phase review. Written by spawner BEFORE workers spawn. Consumed by verify-lens-runs-coverage.py.",
  "type": "object",
  "required": ["review_run_id", "phase", "plan_hash", "commit_sha", "dispatches"],
  "properties": {
    "review_run_id": {"type": "string", "minLength": 1},
    "phase": {"type": "string", "minLength": 1},
    "plan_hash": {"type": "string", "pattern": "^[a-f0-9]{16,64}$",
      "description": "sha256 prefix of the dispatch plan body — detects reuse from prior runs"},
    "commit_sha": {"type": "string", "pattern": "^[a-f0-9]{7,40}$"},
    "emitted_at": {"type": "string", "format": "date-time"},
    "dispatches": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["dispatch_id", "lens", "goal_id", "applicability_status", "expected_artifact_path"],
        "properties": {
          "dispatch_id": {"type": "string"},
          "lens": {"type": "string", "pattern": "^lens-[a-z][a-z0-9-]*$"},
          "goal_id": {"type": "string", "pattern": "^G-\\d+$"},
          "view": {"type": "string"},
          "element_class": {"type": "string"},
          "selector_hash": {"type": "string"},
          "resource": {"type": "string"},
          "role": {"type": "string"},
          "applicability_status": {
            "type": "string",
            "enum": ["APPLICABLE", "N/A", "SKIPPED_BY_POLICY", "SKIPPED_BY_OVERRIDE"]
          },
          "applicability_reason": {"type": "string",
            "description": "Required when status != APPLICABLE; cited from lens frontmatter applies_to_*"},
          "expected_artifact_path": {"type": "string"},
          "worker_tier": {"type": "string", "enum": ["haiku", "sonnet", "opus", "crossai"]},
          "worker_tool": {"type": "string", "enum": ["claude", "codex", "gemini"]},
          "min_actions_floor": {"type": "integer", "minimum": 1},
          "min_evidence_steps": {"type": "integer", "minimum": 1},
          "required_probe_kinds": {"type": "array", "items": {"type": "string"}}
        }
      }
    }
  }
}
```

`plan_hash` = sha256(canonical JSON of `dispatches` array sorted by dispatch_id). Stored AND replicated into every `runs/<artifact>.json` so coverage gate verifies artifact-was-produced-against-this-plan (not reused from prior).

---

### Deliverable 2 — Lens frontmatter extension

Add to `commands/vg/_shared/lens-prompts/_TEMPLATE.md` frontmatter (and propagate to each lens-*.md):

```yaml
# Existing fields:
name: lens-<slug>
bug_class: <...>
applies_to_element_classes: [...]
applies_to_phase_profiles: [...]
strix_reference: ...
severity_default: warn|block
estimated_action_budget: <int>
output_schema_version: 3
runtime: roam|review

# NEW (Task 26):
recommended_worker_tier: haiku|sonnet|opus|crossai
  # haiku   — mechanical scan, low ambiguity (info-disclosure, header-check)
  # sonnet  — observation + branching (form-lifecycle, business-coherence)
  # opus    — multi-layer reasoning + state-machine (business-logic, complex bizflow)
  # crossai — adversarial cross-model verification (high-stakes — auth, billing)

worker_complexity_score: 1|2|3|4|5
  # 1 = checklist-only; AI just executes step list verbatim
  # 2 = light branching; pick from probe ideas with low judgment
  # 3 = adaptive probing; observe → decide next probe
  # 4 = multi-layer cross-check (UI ↔ network ↔ DB ↔ console)
  # 5 = state-machine reasoning, requires deep context

fallback_on_inconclusive: <tier>|none
  # If worker returns INCONCLUSIVE, escalate to this tier and re-spawn ONCE.
  # `none` = accept INCONCLUSIVE, log advisory, no re-spawn.

min_actions_floor: <int>
  # Minimum actions_taken expected for a non-skipped run. Initial ADVISORY.
  # Default formula: max(5, ceil(estimated_action_budget * 0.4)).
  # Author overrides if probe count justifies different floor.

min_evidence_steps: <int>
  # Minimum number of steps in artifact with non-empty `evidence_ref`.
  # Catches "8 actions but only 1 with real evidence" gaming.

required_probe_kinds: [<kind>, ...]
  # Distinct operation kinds the worker MUST attempt (subset of probe ideas).
  # E.g. lens-idor: [horizontal_id_swap, vertical_role_swap, peer_tenant_replay]
  # Gate verifies artifact's steps[].name covers each kind at least once.
```

Per-lens initial values (representative; lens authors finalize):

| Lens | tier | complexity | min_actions | min_evidence | fallback |
|---|---|---|---|---|---|
| lens-info-disclosure | haiku | 2 | 5 | 3 | sonnet |
| lens-csrf | haiku | 2 | 4 | 3 | sonnet |
| lens-input-injection | haiku | 2 | 6 | 4 | sonnet |
| lens-modal-state | sonnet | 3 | 8 | 5 | opus |
| lens-form-lifecycle | sonnet | 4 | 10 | 8 | opus |
| lens-business-coherence | sonnet | 4 | 8 | 6 | opus |
| lens-idor / lens-bfla | sonnet | 3 | 8 | 6 | opus |
| lens-tenant-boundary | sonnet | 4 | 10 | 8 | opus |
| lens-auth-jwt | sonnet | 3 | 6 | 5 | opus |
| lens-business-logic | opus | 5 | 12 | 10 | crossai |
| lens-mass-assignment | sonnet | 3 | 6 | 5 | opus |
| lens-ssrf / lens-open-redirect / lens-path-traversal | haiku | 2 | 5 | 4 | sonnet |
| lens-file-upload | haiku | 2 | 6 | 4 | sonnet |
| lens-duplicate-submit | sonnet | 4 | 8 | 6 | opus |
| lens-table-interaction | haiku | 2 | 6 | 4 | sonnet |

---

### Deliverable 3 — emit-dispatch-plan.py

Create `scripts/lens-dispatch/emit-dispatch-plan.py`:

```python
#!/usr/bin/env python3
"""emit-dispatch-plan.py — emit LENS-DISPATCH-PLAN.json before any worker spawns.

Inputs:
  - phase TEST-GOALS/G-*.md (goal IDs + metadata)
  - lens-prompts/lens-*.md (frontmatter — applies_to_*, complexity, tier)
  - vg.config.md (review.lens_overrides for project-specific skips)

Output:
  - ${PHASE_DIR}/LENS-DISPATCH-PLAN.json (canonical manifest, schema-validated)

Trust anchor (Codex round 5):
  Every (lens × goal) intent must be declared here BEFORE spawn. Coverage gate
  later asserts every APPLICABLE dispatch has matching artifact. plan_hash
  pinned in each artifact prevents reuse from prior runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
LENS_DIR = REPO / "commands" / "vg" / "_shared" / "lens-prompts"


def _read_lens_frontmatter(lens_path: Path) -> dict:
    text = lens_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.+?)\n---", text, re.DOTALL)
    if not m:
        raise ValueError(f"no frontmatter in {lens_path}")
    return yaml.safe_load(m.group(1)) or {}


def _read_goal_metadata(goal_path: Path) -> dict:
    text = goal_path.read_text(encoding="utf-8")
    out: dict = {"goal_id": goal_path.stem}
    m = re.search(r"\*\*goal_type:\*\*\s*(\S+)", text)
    out["goal_type"] = m.group(1).strip() if m else "unknown"
    m = re.search(r"\*\*element_class:\*\*\s*(\S+)", text)
    out["element_class"] = m.group(1).strip() if m else None
    m = re.search(r"\*\*resource:\*\*\s*(\S+)", text)
    out["resource"] = m.group(1).strip() if m else None
    m = re.search(r"\*\*view:\*\*\s*(\S+)", text)
    out["view"] = m.group(1).strip() if m else None
    return out


def _classify_applicability(lens_fm: dict, goal: dict, profile: str) -> tuple[str, str]:
    """Return (status, reason). Status ∈ APPLICABLE, N/A, SKIPPED_BY_POLICY, SKIPPED_BY_OVERRIDE."""
    # Profile filter
    profiles = lens_fm.get("applies_to_phase_profiles", [])
    if profiles and profile not in profiles:
        return ("N/A", f"lens not applicable to phase profile {profile}")
    # Element class filter
    element_classes = lens_fm.get("applies_to_element_classes", [])
    if element_classes and goal.get("element_class"):
        if goal["element_class"] not in element_classes:
            return ("N/A", f"lens not applicable to element_class {goal['element_class']}")
    # Goal type filter (mutation lenses skip read-only)
    if lens_fm.get("bug_class") in {"state-coherence", "bizlogic"}:
        if goal.get("goal_type") == "read_only":
            return ("N/A", "mutation lens not applicable to read-only goal")
    return ("APPLICABLE", "matches frontmatter applies_to_* + goal type")


def _git_commit_sha() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()[:40] if r.returncode == 0 else "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def _canonical_hash(dispatches: list[dict]) -> str:
    """sha256 of canonical JSON of dispatches sorted by dispatch_id."""
    sorted_d = sorted(dispatches, key=lambda d: d["dispatch_id"])
    blob = json.dumps(sorted_d, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-dir", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--profile", default="web-fullstack")
    parser.add_argument("--review-run-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--policy-overrides", help="JSON file of lens-overrides (skip reasons)")
    args = parser.parse_args()

    phase_dir = Path(args.phase_dir)
    goals_dir = phase_dir / "TEST-GOALS"
    if not goals_dir.exists():
        print(f"ERROR: TEST-GOALS missing at {goals_dir}", file=sys.stderr)
        return 1

    overrides = {}
    if args.policy_overrides and Path(args.policy_overrides).exists():
        overrides = json.loads(Path(args.policy_overrides).read_text(encoding="utf-8"))

    dispatches: list[dict] = []
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        lens_fm = _read_lens_frontmatter(lens_path)
        lens_name = lens_fm.get("name", lens_path.stem)
        for goal_path in sorted(goals_dir.glob("G-*.md")):
            goal = _read_goal_metadata(goal_path)
            status, reason = _classify_applicability(lens_fm, goal, args.profile)

            # Honor user policy overrides
            override_key = f"{lens_name}/{goal['goal_id']}"
            if override_key in overrides:
                status = "SKIPPED_BY_POLICY"
                reason = overrides[override_key].get("reason", "policy skip")

            dispatch_id = f"{lens_name}__{goal['goal_id']}"
            expected_path = (f"runs/{lens_name}/{goal['goal_id']}.json"
                             if status == "APPLICABLE" else "")
            dispatches.append({
                "dispatch_id": dispatch_id,
                "lens": lens_name,
                "goal_id": goal["goal_id"],
                "view": goal.get("view"),
                "element_class": goal.get("element_class"),
                "resource": goal.get("resource"),
                "role": None,  # filled by tier-dispatcher (M1) at spawn time
                "applicability_status": status,
                "applicability_reason": reason,
                "expected_artifact_path": expected_path,
                "worker_tier": lens_fm.get("recommended_worker_tier", "haiku"),
                "worker_tool": "claude",  # dispatcher decides per project config
                "min_actions_floor": lens_fm.get("min_actions_floor",
                                                  max(5, int((lens_fm.get("estimated_action_budget", 30) or 30) * 0.4))),
                "min_evidence_steps": lens_fm.get("min_evidence_steps", 3),
                "required_probe_kinds": lens_fm.get("required_probe_kinds", []),
            })

    plan = {
        "review_run_id": args.review_run_id,
        "phase": args.phase,
        "commit_sha": _git_commit_sha(),
        "emitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dispatches": dispatches,
        "plan_hash": _canonical_hash(dispatches),
    }

    Path(args.output).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"✓ LENS-DISPATCH-PLAN.json written: {len(dispatches)} dispatches "
          f"({sum(1 for d in dispatches if d['applicability_status']=='APPLICABLE')} APPLICABLE), "
          f"plan_hash={plan['plan_hash'][:12]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

### Deliverable 4 — verify-lens-runs-coverage.py (generalized gate)

Create `scripts/validators/verify-lens-runs-coverage.py`. For every `applicability_status == APPLICABLE` dispatch:

1. Artifact exists at `expected_artifact_path` (BLOCK day 1)
2. Artifact's `plan_hash` matches dispatch's `plan_hash` (BLOCK — prevents reuse)
3. Artifact's `lens` matches dispatch's `lens` (BLOCK — prevents wrong-artifact gaming)
4. Artifact's `goal_id` / `view` / `element_class` / `selector_hash` match (BLOCK)
5. Artifact's `steps[]` non-empty (BLOCK)
6. Artifact's `steps[]` with non-empty `evidence_ref` count >= `min_evidence_steps` (BLOCK)
7. Artifact's `actions_taken >= min_actions_floor` (ADVISORY for first 2 weeks, then BLOCK)
8. Artifact's `required_probe_kinds` all covered by `steps[].name` matching (ADVISORY)
9. Each `evidence_ref` resolves to actual file (network_log entry, screenshot file, DOM snapshot) (BLOCK day 1 for missing, ADVISORY for malformed)
10. `stopping_reason="budget"` requires `actions_taken >= action_budget` OR explicit timeout evidence (ADVISORY)

Output BuildWarningEvidence per failed dispatch with category=`lens_coverage_gate`. Routes via classifier (Task 7) to STEP 5.5 fix-loop (Task 10).

(Full script body ~200 lines — pattern follows `verify-crud-runs-coverage.py` with extensions above. Implementer agent writes it from the spec.)

---

### Deliverable 5 — M1 tier-aware dispatcher (`scripts/lib/lens_tier_dispatcher.py`)

```python
"""lens_tier_dispatcher — pick the right model for each lens × goal dispatch.

Reads lens frontmatter (recommended_worker_tier + worker_complexity_score)
and project config (vg.config.md cost_caps). Returns spawn parameters:
  {worker_tool: claude|codex|gemini, model: haiku-4-5|sonnet-4-6|opus-4-7}

Rules (sếp's M1 concern — Haiku capability bounded):
  1. complexity_score >= 4 → require sonnet+ floor (downgrade to sonnet only via
     explicit project override with override-debt entry)
  2. complexity_score == 5 → require opus floor (no downgrade without
     project-level cost_cap override + telemetry justification)
  3. fallback_on_inconclusive: if first spawn returns INCONCLUSIVE, re-spawn
     once at the declared fallback tier.

Cost cap (vg.config.md):
  review:
    cost_caps:
      max_haiku_per_phase: 60        # default; project overrides
      max_sonnet_per_phase: 20
      max_opus_per_phase: 5
      hard_max_usd_per_phase: 10
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


_TIER_MODEL = {
    "haiku":  "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-7",
    # crossai handled separately — spawns parallel models for adversarial verification
}


@dataclass(frozen=True)
class DispatchTier:
    tier: Literal["haiku", "sonnet", "opus", "crossai"]
    model: str
    fallback_tier: str | None
    override_required: bool   # True when complexity demanded higher tier than
                              # project cost_cap allows; project must opt-in


def select_tier(lens_frontmatter: dict, project_cost_caps: dict) -> DispatchTier:
    recommended = lens_frontmatter.get("recommended_worker_tier", "haiku")
    complexity = int(lens_frontmatter.get("worker_complexity_score", 1))
    fallback = lens_frontmatter.get("fallback_on_inconclusive", "none")

    # Capability floor enforcement (sếp's M1 — Haiku not allowed for complex lenses)
    if complexity >= 5 and recommended != "opus":
        recommended = "opus"
    elif complexity >= 4 and recommended == "haiku":
        recommended = "sonnet"

    # Cost cap check
    cap_used = project_cost_caps.get(f"used_{recommended}", 0)
    cap_max = project_cost_caps.get(f"max_{recommended}_per_phase", float("inf"))
    override_required = False
    if cap_used >= cap_max:
        # Cap exceeded — downgrade is forbidden for high complexity. Caller decides:
        # raise or accept override-debt entry.
        override_required = True

    return DispatchTier(
        tier=recommended,
        model=_TIER_MODEL.get(recommended, _TIER_MODEL["haiku"]),
        fallback_tier=fallback if fallback != "none" else None,
        override_required=override_required,
    )
```

Spawner (`spawn_recursive_probe.py`) calls `select_tier()` per dispatch. If `override_required` and lens complexity_score >= 4: BLOCK spawn (project must explicitly raise cost_cap or accept skip with override-debt).

---

### Deliverable 6 — M2 MCP action-trace cross-check (`scripts/validators/verify-lens-action-trace.py`)

```python
"""verify-lens-action-trace — cross-reference self-reported actions vs MCP log.

The MCP server (Playwright MCP, Codex MCP) emits a tool-call log for every
browser action. Log lives at `${PHASE_DIR}/.mcp-trace/<run_id>.jsonl`,
written externally by the MCP server (NOT by the worker).

Worker self-reports `actions_taken: N` in run artifact. Gate compares:
  - mcp_action_count(run_id) == artifact.actions_taken → PASS
  - mismatch > tolerance (default ±2 for tool-internal retries) → BLOCK,
    severity=BLOCK day 1 (this is hard anti-fake — no advisory phase-in)

Tolerance accounts for MCP-internal retries on transient errors. >2 mismatch
cannot be explained by retries alone — implies fabrication.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _count_mcp_actions(trace_path: Path, run_id: str) -> int:
    if not trace_path.exists():
        return -1  # no trace at all → suspicious
    count = 0
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("run_id") == run_id and entry.get("tool", "").startswith("browser_"):
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--mcp-trace", required=True)
    parser.add_argument("--tolerance", type=int, default=2)
    parser.add_argument("--evidence-out")
    args = parser.parse_args()

    artifact = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    self_reported = artifact.get("actions_taken", 0)
    run_id = artifact.get("run_id")
    mcp_count = _count_mcp_actions(Path(args.mcp_trace), run_id)

    if mcp_count == -1:
        print(f"⛔ MCP trace missing for run_id {run_id}", file=sys.stderr)
        return 1
    drift = abs(self_reported - mcp_count)
    if drift > args.tolerance:
        print(f"⛔ M2 trace mismatch: self_reported={self_reported}, "
              f"mcp_count={mcp_count}, drift={drift} > tolerance={args.tolerance}",
              file=sys.stderr)
        if args.evidence_out:
            ev = {
                "warning_id": f"lens-trace-mismatch-{run_id}",
                "severity": "BLOCK",
                "category": "lens_action_trace_mismatch",
                "summary": (f"Worker reported {self_reported} actions but MCP log shows "
                            f"{mcp_count}. Drift {drift} > tolerance {args.tolerance}. "
                            "AI fabrication suspected."),
                "detected_by": "verify-lens-action-trace.py",
                "details": {"run_id": run_id, "self_reported": self_reported,
                            "mcp_count": mcp_count, "drift": drift},
            }
            Path(args.evidence_out).write_text(json.dumps(ev, indent=2), encoding="utf-8")
        return 1

    print(f"✓ M2 trace match: {self_reported} ≈ {mcp_count} (drift {drift} ≤ {args.tolerance})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

MCP server config (separate from this task — already in `.mcp.json`): each MCP tool call appends to `${PHASE_DIR}/.mcp-trace/<run_id>.jsonl` with `{tool, run_id, timestamp, args_hash}`. This is OPS work — Task 26 specifies the gate; MCP trace pipeline is preexisting (see VG MCP integration docs).

---

### Deliverable 7 — Recursive scan fix for challenge-coverage.py

`scripts/challenge-coverage.py:47` currently:
```python
for artifact_path in (phase_dir / "runs").glob("*.json"):
```

Change to:
```python
for artifact_path in (phase_dir / "runs").rglob("*.json"):
    if artifact_path.name == "INDEX.json":
        continue
```

This catches `runs/<tool>/<lens>/<goal_id>.json` recursive paths produced by `spawn_recursive_probe.py:564`.

---

### Deliverable 8 — LENS-COVERAGE-MATRIX.md renderer

Create `scripts/aggregators/lens-coverage-matrix.py`:

```python
"""Render LENS-COVERAGE-MATRIX.md from LENS-DISPATCH-PLAN.json + run artifacts.

7 status enum (Codex round 5):
  PASS                   — artifact present, all checks pass
  FAIL                   — artifact present, contains finding_fact entries
  INCONCLUSIVE           — artifact present, status=inconclusive in steps[]
  N/A                    — applicability_status=N/A in dispatch plan
  SKIPPED_BY_POLICY      — applicability_status=SKIPPED_BY_POLICY (with reason)
  SKIPPED_BY_OVERRIDE    — applicability_status=SKIPPED_BY_OVERRIDE
  MISSING                — applicable but artifact missing (gate BLOCKs)

Output: human-readable matrix table + per-cell footnote linking to
artifact path + applicability reason for skips.
"""
# (Body ~150 lines — straightforward dispatch-plan + artifact iteration + Markdown table render)
```

---

### Deliverable 9 — Tasklist grouped counters (NOT 160 leaf tasks)

Modify `scripts/emit-tasklist.py`. After Phase 2.5 step entry, append a single counter group:

```
◼ Lens probes: 0/40 complete, 0 blocked
  ↳ haiku tier: 0/15
  ↳ sonnet tier: 0/20
  ↳ opus tier: 0/5
```

After spawn returns:
```
◼ Lens probes: 37/40 complete, 4 blocked
  ↳ lens-form-lifecycle × G-04 (BLOCKED — R8 update_did_not_apply)   ← only failed children expanded
  ↳ lens-business-coherence × G-12 (BLOCKED — drift in audit log)
```

Operator sees high-level + drills into failures only. Full detail in `LENS-COVERAGE-MATRIX.md`.

---

### Deliverable 10 — Wire into review.md Phase 2.5

Edit `commands/vg/review.md` Phase 2.5 (`recursive_lens_probe`):

```bash
# 1. Emit dispatch plan FIRST (trust anchor)
"${PYTHON_BIN:-python3}" .claude/scripts/lens-dispatch/emit-dispatch-plan.py \
  --phase-dir "${PHASE_DIR}" \
  --phase "${PHASE_NUMBER}" \
  --profile "$(vg_config_get profile web-fullstack)" \
  --review-run-id "${REVIEW_RUN_ID}" \
  --output "${PHASE_DIR}/LENS-DISPATCH-PLAN.json"

# 2. Spawn workers per dispatch (M1 tier-aware)
# (existing spawn_recursive_probe.py wired to read dispatch plan + lens_tier_dispatcher)

# 3. After all spawns return, run gates in order:
# 3a. Coverage gate (structural)
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-lens-runs-coverage.py \
  --dispatch-plan "${PHASE_DIR}/LENS-DISPATCH-PLAN.json" \
  --runs-dir "${PHASE_DIR}/runs" \
  --phase "${PHASE_NUMBER}" \
  --evidence-out "${PHASE_DIR}/.lens-coverage-evidence.json" || COVERAGE_FAIL=1

# 3b. M2 action-trace per artifact
for artifact in "${PHASE_DIR}"/runs/*/*.json; do
  [ "$(basename "$artifact")" = "INDEX.json" ] && continue
  run_id=$(jq -r '.run_id' "$artifact" 2>/dev/null)
  "${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-lens-action-trace.py \
    --artifact "$artifact" \
    --mcp-trace "${PHASE_DIR}/.mcp-trace/${run_id}.jsonl" \
    --evidence-out "${PHASE_DIR}/.lens-trace-evidence-${run_id}.json" || TRACE_FAIL=1
done

# 3c. Recursive scan challenge (Codex fix)
"${PYTHON_BIN:-python3}" .claude/scripts/challenge-coverage.py \
  --phase-dir "${PHASE_DIR}" --recursive

# 4. Render matrix
"${PYTHON_BIN:-python3}" .claude/scripts/aggregators/lens-coverage-matrix.py \
  --dispatch-plan "${PHASE_DIR}/LENS-DISPATCH-PLAN.json" \
  --runs-dir "${PHASE_DIR}/runs" \
  --output "${PHASE_DIR}/LENS-COVERAGE-MATRIX.md"

# 5. BLOCK if any structural failure (action floor advisory for 2 weeks)
if [ "${COVERAGE_FAIL:-0}" = "1" ] || [ "${TRACE_FAIL:-0}" = "1" ]; then
  echo "⛔ Phase 2.5 lens dispatch enforcement — see LENS-COVERAGE-MATRIX.md"
  echo "   Coverage gate evidence: ${PHASE_DIR}/.lens-coverage-evidence.json"
  echo "   Trace mismatch evidence: ${PHASE_DIR}/.lens-trace-evidence-*.json"
  exit 1
fi
```

Add to `commands/vg/review.md` frontmatter `must_write`:

```yaml
- path: "${PHASE_DIR}/LENS-DISPATCH-PLAN.json"
  content_min_bytes: 200
- path: "${PHASE_DIR}/LENS-COVERAGE-MATRIX.md"
  content_min_bytes: 100
```

`must_emit_telemetry`:

```yaml
- event_type: "review.lens_dispatch_emitted"
  phase: "${PHASE_NUMBER}"
- event_type: "review.lens_coverage_passed"
  phase: "${PHASE_NUMBER}"
- event_type: "review.lens_coverage_blocked"
  phase: "${PHASE_NUMBER}"
  severity: "warn"
- event_type: "review.lens_trace_mismatch"
  phase: "${PHASE_NUMBER}"
  severity: "warn"
```

---

### Tests (`tests/test_lens_dispatch_enforcement.py`)

Cover at minimum:

1. **Schema validation** — emit-dispatch-plan output passes JSON schema
2. **Applicability classification** — read-only goal × mutation lens → N/A
3. **Plan hash determinism** — same input twice produces same hash
4. **Coverage gate happy path** — all APPLICABLE dispatches have artifacts → PASS
5. **Coverage gate detects MISSING** — applicable dispatch without artifact → BLOCK
6. **Coverage gate detects WRONG_LENS** — artifact lens != dispatch lens → BLOCK
7. **Coverage gate detects PLAN_HASH_MISMATCH** — artifact reused from prior run → BLOCK
8. **Coverage gate detects EVIDENCE_REF_MISSING** — steps[] without resolvable evidence → BLOCK
9. **M1 tier dispatcher**: complexity 5 lens with `recommended_worker_tier: haiku` → upgraded to opus
10. **M1 tier dispatcher**: cost cap exceeded → override_required=true
11. **M2 trace mismatch**: self_reported=8, mcp_count=2 → BLOCK with drift evidence
12. **M2 trace match**: self_reported=8, mcp_count=9 (retries) → PASS within tolerance
13. **Matrix renderer**: all 7 status states render correctly
14. **Recursive scan**: artifact at `runs/codex/lens-idor/G-04.json` discovered (not just root)

---

### Step-by-step execution

- [ ] **Step 1** — Write `tests/test_lens_dispatch_enforcement.py` with all 14 cases (failing initially)
- [ ] **Step 2** — Run tests → 14 failures
- [ ] **Step 3** — Write `schemas/lens-dispatch-plan.schema.json`
- [ ] **Step 4** — Write `scripts/lens-dispatch/emit-dispatch-plan.py`
- [ ] **Step 5** — Write `scripts/lib/lens_tier_dispatcher.py`
- [ ] **Step 6** — Write `scripts/validators/verify-lens-runs-coverage.py` (extend pattern from `verify-crud-runs-coverage.py`)
- [ ] **Step 7** — Write `scripts/validators/verify-lens-action-trace.py`
- [ ] **Step 8** — Write `scripts/aggregators/lens-coverage-matrix.py`
- [ ] **Step 9** — Patch `scripts/challenge-coverage.py:47` (rglob fix)
- [ ] **Step 10** — Add frontmatter fields to `_TEMPLATE.md` + each `lens-*.md` (16 files)
- [ ] **Step 11** — Update `scripts/spawn_recursive_probe.py` to call lens_tier_dispatcher + write artifact with plan_hash
- [ ] **Step 12** — Update `scripts/emit-tasklist.py` for grouped counters
- [ ] **Step 13** — Update `commands/vg/review.md` Phase 2.5 wiring + frontmatter
- [ ] **Step 14** — Run all 14 tests → expect PASS
- [ ] **Step 15** — Run existing pytest suite for regression
- [ ] **Step 16** — Sync to `.claude/` mirror via `sync.sh`
- [ ] **Step 17** — Commit:

```bash
git add schemas/lens-dispatch-plan.schema.json \
        scripts/lens-dispatch/ \
        scripts/lib/lens_tier_dispatcher.py \
        scripts/validators/verify-lens-runs-coverage.py \
        scripts/validators/verify-lens-action-trace.py \
        scripts/aggregators/lens-coverage-matrix.py \
        scripts/challenge-coverage.py \
        scripts/spawn_recursive_probe.py \
        scripts/emit-tasklist.py \
        commands/vg/_shared/lens-prompts/ \
        commands/vg/review.md \
        tests/test_lens_dispatch_enforcement.py \
        .claude/

git commit -m "feat(lens-enforcement): generalized dispatch plan + coverage gate + tier-aware spawn + MCP trace cross-check

Codex GPT-5.5 round 5 + sếp's AI-trust concern (2026-05-03):
- LENS-DISPATCH-PLAN.json as trust anchor (plan_hash pinned in artifacts)
- verify-lens-runs-coverage.py generalizes kit:crud-roundtrip pattern to all lenses
- M1 tier-aware: lens declares complexity_score; complexity >= 4 requires sonnet+,
  blocks Haiku for form-lifecycle / business-coherence (sếp's R8/R9 case)
- M2 MCP action-trace cross-check: BLOCK on self-reported vs MCP log drift (anti-fake)
- 7 status enum (PASS/FAIL/INCONCLUSIVE/N/A/SKIPPED_*/MISSING)
- Recursive scan fix for challenge-coverage.py (subagent paths)
- Grouped tasklist counters (NOT 160 leaf tasks)
- Phase-in: structural BLOCK day 1, action_floor ADVISORY 2 weeks

Closes user trust gap: lens injection ≠ enforcement → now enforced
end-to-end with external (MCP) verification."
```
