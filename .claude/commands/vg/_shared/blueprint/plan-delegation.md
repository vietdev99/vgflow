# blueprint plan delegation contract (vg-blueprint-planner subagent)

<!-- # Exception: contract document, not step ref — H1/HARD-GATE not required.
     This ref describes a JSON envelope + prompt template + return contract
     for the `vg-blueprint-planner` subagent. It has no `step-active` /
     `mark-step` lifecycle of its own — `plan-overview.md` STEP 3 owns those.
     The reviewer audit (B1/B2 FAIL) flagged the missing
     `# blueprint <name> (STEP N)` H1 + top HARD-GATE; both are intentionally
     absent because this file is a contract, not an executable step body. -->

This file contains the prompt template the main agent passes to
`Agent(subagent_type="vg-blueprint-planner", prompt=...)`.

Read `plan-overview.md` for orchestration order (pre-spawn setup,
post-spawn validation). This file describes ONLY the spawn payload.

---

## Input contract (the JSON envelope)

```json
{
  "phase_dir": "${PHASE_DIR}",
  "phase_number": "${PHASE_NUMBER}",
  "context_path": "${PHASE_DIR}/CONTEXT.md",
  "specs_path": "${PHASE_DIR}/SPECS.md",
  "interface_standards_path": "${PHASE_DIR}/INTERFACE-STANDARDS.md",
  "graphify_brief": "${PHASE_DIR}/.graphify-brief.md",
  "deploy_lessons_brief": "${PHASE_DIR}/.deploy-lessons-brief.md",
  "design_refs": [
    "${PHASE_DIR}/UI-SPEC.md",
    "${PHASE_DIR}/UI-MAP.md",
    "${PHASE_DIR}/VIEW-COMPONENTS.md"
  ],
  "must_cite_bindings": [
    "CONTEXT:decisions",
    "INTERFACE-STANDARDS:error-shape"
  ],
  "config": {
    "profile": "${PROFILE}",
    "graphify_active": "${GRAPHIFY_ACTIVE}",
    "context_injection_mode": "${CONFIG_CONTEXT_INJECTION_MODE:-full}"
  }
}
```

---

## Prompt template

The main agent renders the template below (substituting `${...}` from
its environment) and passes it as the `prompt` argument.

````
<vg_planner_rules>
@.claude/commands/vg/_shared/vg-planner-rules.md
</vg_planner_rules>

<bootstrap_rules>
${BOOTSTRAP_RULES_BLOCK}
</bootstrap_rules>

<graphify_brief>
@${PHASE_DIR}/.graphify-brief.md
</graphify_brief>

<deploy_lessons>
@${PHASE_DIR}/.deploy-lessons-brief.md (if exists — v1.14.0+ C.5)
</deploy_lessons>

<specs>
@${PHASE_DIR}/SPECS.md
</specs>

<context>
@${PHASE_DIR}/CONTEXT.md
</context>

<architecture_context>
# FOUNDATION §9 Architecture Lock (injected if §9 exists).
# Authoritative architecture contract — every plan MUST respect:
# §9.1 Tech stack (no substitutions without /vg:project --update)
# §9.2 Module boundary (dependency direction rules)
# §9.3 Folder convention (route layout, test colocation)
# §9.4 Cross-cutting concerns (logging, error handling, async pattern)
# §9.5 Security baseline (session/identity + server hardening rules)
# §9.6 Performance baseline (p95 per tier, cache, bundle budget)
# §9.7 Testing baseline (runner, E2E framework, coverage)
# §9.8 Model-portable code style (imports, exports, naming, idioms)
# Plans MUST cite F-XX decisions when deviating; unreferenced deviation = drift.
@${PLANNING_DIR:-.vg}/FOUNDATION.md (section 9 only — verify-foundation-architecture.py enforces presence)
</architecture_context>

<security_test_plan>
# SECURITY-TEST-PLAN.md (injected if exists). Drives DAST severity gate
# + compliance control mapping per risk_profile.
@${PLANNING_DIR:-.vg}/SECURITY-TEST-PLAN.md (if exists)
</security_test_plan>

<contracts>
# Load via vg-load helper (3-layer split aware) — falls back to flat
# concat when split dirs absent. Subagent runs:
#   bash scripts/vg-load.sh --phase ${PHASE_NUMBER} --artifact contracts --index
# Then per endpoint of interest:
#   bash scripts/vg-load.sh --phase ${PHASE_NUMBER} --artifact contracts --endpoint <slug>
# Last-resort full read (legacy):
#   bash scripts/vg-load.sh --phase ${PHASE_NUMBER} --artifact contracts --full
</contracts>

<goals>
# Load via vg-load helper — partial loads keep planner context budget tight.
#   bash scripts/vg-load.sh --phase ${PHASE_NUMBER} --artifact goals --index
#   bash scripts/vg-load.sh --phase ${PHASE_NUMBER} --artifact goals --priority critical
#   bash scripts/vg-load.sh --phase ${PHASE_NUMBER} --artifact goals --goal G-NN
# Last-resort full read (legacy):
#   bash scripts/vg-load.sh --phase ${PHASE_NUMBER} --artifact goals --full
</goals>

<config>
profile: ${PROFILE}
typecheck_cmd: ${config.build_gates.typecheck_cmd}
contract_format: ${config.contract_format.type}
phase: ${PHASE_NUMBER}
phase_dir: ${PHASE_DIR}
graphify_active: ${GRAPHIFY_ACTIVE}
</config>

Create PLAN.md for phase ${PHASE_NUMBER}. Follow vg-planner-rules exactly.

PLAN SCHEMA REQUIREMENTS (BLOCKING):
- `${PHASE_DIR}/PLAN.md` MUST begin with YAML frontmatter that passes
  `.claude/schemas/plan.v1.json`.
- Required frontmatter keys: `phase`, `profile`, `goal_summary`,
  `total_waves`, `total_tasks`, `generated_at`.
- Allowed optional keys only: `platform`, `phase_name`, `blueprint_version`.
- `profile` is the schema category. Use one of:
  `feature`, `infra`, `hotfix`, `bugfix`, `migration`, `docs`.
- If `${PROFILE}` is a runtime surface/profile such as `web-fullstack`,
  `web-frontend-only`, `web-backend-only`, `mobile-*`, `cli-tool`, or
  `library`, set `profile: feature` and set `platform: ${PROFILE}`.
- Do NOT put `cli-tool` or `library` in frontmatter `profile`.
- Body MUST contain top-level H2 anchors:
  - `## Wave 1` through `## Wave <wave_count>` exactly matching
    frontmatter `total_waves`
  - `## Verification`
  - `## Risks`

TRACEABILITY TAGS (BLOCKING):
- Each task MUST include one `<implements-decision>D-ID</implements-decision>`
  line for every CONTEXT decision implemented by that task.
- Each task MUST include one `<goals-covered>G-XX,...</goals-covered>` line
  listing TEST-GOALS covered by that task.
- Each task MUST include a plain `Covers goal: G-XX, ...` line for legacy
  scanners.
- Do not rely only on human-readable `**Goals covered:**` or
  `**Decisions implemented:**`; validators grep the machine tags above.
- Layer 1 task files and Layer 3 `PLAN.md` flat concat must both contain these
  tags.

Frontmatter template:
```yaml
---
phase: "${PHASE_NUMBER}"
profile: feature
platform: ${PROFILE}
phase_name: "<human-readable phase name>"
goal_summary: "<one sentence, max 200 chars>"
total_waves: <int>
total_tasks: <int>
generated_at: "<YYYY-MM-DD>"
blueprint_version: "v1"
---
```

GRAPHIFY USAGE (when graphify_active=true):
- graphify_brief lists god nodes + existing symbols + sibling files.
- For EVERY task touching code, set <edits-*> attributes (REQUIRED, not optional)
  so the post-plan caller-graph script (step 2a5) can compute blast radius.
- When task touches a god node listed in brief, prefix description with
  "BLAST-RADIUS: god node — ripple to N callers expected" and include
  mitigation note (gradual rollout / feature flag / regression suite).
- When task lists an endpoint in <edits-endpoint>, check brief's existing
  symbols table — if found, mark as REUSED-MODIFY not NEW-CREATE.

DEPLOY_LESSONS USAGE (when brief exists):
- Service-specific lessons → reference DIRECTLY in task description for
  ORG dimensions 3/4/6. Example: "Rebuild incremental tsc (Phase 7.12
  lesson: force --skip-lib-check if node_modules freshly cleared)".
- Env vars → tasks adding new var MUST follow reload/rotation/storage
  format established in ENV-CATALOG (90-day vault for secrets, config-
  stable for URLs, tuning-knob for TTL/cache).
- No lessons relevant → ignore block (OK).

CONTEXT-REFS USAGE (Phase C v2.5 — context_injection.mode: scoped):
When config.context_injection.mode is "scoped" (or phase_number >= phase_cutover),
each task MUST include a <context-refs> element listing the specific
decision IDs from CONTEXT.md that the executor needs. Example:

## Task 03: Add POST /api/v1/sites handler
<context-refs>P7.14.D-02,P7.14.D-05</context-refs>
<file-path>apps/api/src/modules/sites/routes.ts</file-path>

Rules for picking refs:
- Only cite decisions that directly constrain the task's implementation.
- Include D-XX for auth model, schema format, error handling idiom, naming.
- EXCLUDE decisions about other subsystems the task doesn't touch.
- If task is infra-only (Ansible, env) → cite infra/env decisions only.
- Maximum 5 refs per task (more = over-citing; executor gets noise).

When mode is "full" (phases 0-13), <context-refs> is optional.

OUTPUT: Write the 3-layer artifacts described in vg-blueprint-planner
SKILL.md (Layer 1 ${PHASE_DIR}/PLAN/task-NN.md per task, Layer 2
${PHASE_DIR}/PLAN/index.md, Layer 3 ${PHASE_DIR}/PLAN.md flat concat).
Layer 2 index.md MUST include the same frontmatter because Layer 3 begins by
copying index.md verbatim. Put `## Wave N`, `## Verification`, and `## Risks`
in index.md before task concatenation so the flat PLAN.md validates.
Each task MUST contain `<!-- vg-binding: <id> -->` HTML comments for
each citation in must_cite_bindings.
Each task MUST contain `<implements-decision>...</implements-decision>`,
`<goals-covered>...</goals-covered>`, and `Covers goal: ...` traceability
lines as described above.

Then return JSON to main agent (shape MUST match SKILL.md "Example return"):

{
  "path": "${PHASE_DIR}/PLAN.md",
  "index_path": "${PHASE_DIR}/PLAN/index.md",
  "sub_files": [
    "${PHASE_DIR}/PLAN/task-01.md",
    "${PHASE_DIR}/PLAN/task-02.md"
  ],
  "task_count": <int>,
  "wave_count": <int>,
  "sha256": "<sha256sum of PLAN.md>",
  "summary": "<one-paragraph plan summary>",
  "bindings_satisfied": ["CONTEXT:decisions", "INTERFACE-STANDARDS:error-shape"],
  "warnings": ["<any non-blocking issues>"]
}
````

---

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

---

## Output (subagent returns)

Shape MUST match `agents/vg-blueprint-planner/SKILL.md` "Example return"
exactly. Drift between this contract and SKILL.md breaks the post-spawn
validator.

```json
{
  "path": "${PHASE_DIR}/PLAN.md",
  "index_path": "${PHASE_DIR}/PLAN/index.md",
  "sub_files": [
    "${PHASE_DIR}/PLAN/task-01.md",
    "${PHASE_DIR}/PLAN/task-02.md"
  ],
  "task_count": 5,
  "wave_count": 3,
  "sha256": "<hex sha256 of PLAN.md contents>",
  "summary": "<one paragraph summary of plan structure>",
  "bindings_satisfied": ["CONTEXT:decisions", "INTERFACE-STANDARDS:error-shape"],
  "warnings": []
}
```

---

## Failure modes

If subagent returns error JSON, do NOT mark step done. Re-spawn after
fixing input.

| Error | Cause | Action |
|---|---|---|
| `{"error": "missing_input", "field": "<name>"}` | Required input file missing | Verify file exists; re-spawn |
| `{"error": "org_6dim_incomplete", "missing": [...]}` | Plan missing critical ORG dim (Deploy/Rollback) | Manual planner intervention; re-spawn |
| `{"error": "binding_unmet", "missing": [...]}` | Required citation not in PLAN.md | Re-spawn with explicit binding instruction |

Retry up to 2 times, then escalate via `AskUserQuestion` (Layer 3).
