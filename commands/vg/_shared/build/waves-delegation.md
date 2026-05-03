# build waves delegation contract (vg-build-task-executor subagent)

This file contains the input envelope, prompt template, and output JSON
contract for `Agent(subagent_type="vg-build-task-executor", prompt=...)`.

Read `waves-overview.md` for the orchestrator-side responsibilities
(pre-spawn checklist, capsule materialization, spawn site narration,
post-spawn aggregation). This file describes ONLY the spawn payload +
return contract.

The shapes below are LOAD-BEARING for Task 10 (`vg-build-task-executor`
SKILL.md). Drift here breaks the subagent's input parser and the
orchestrator's return validator. Do not change field names.

---

## Input contract (the JSON envelope)

The orchestrator constructs this envelope per task before rendering the
prompt template below. All paths are absolute or `${PHASE_DIR}`-rooted.
The envelope is conceptual — the actual transport is the rendered prompt
text the orchestrator passes as the `prompt=` argument to the Agent
tool. The subagent recovers structured fields by reading the named
files (capsule, plan slice, contract slices, design ref).

```json
{
  "task_id": "task-04",
  "wave_id": 3,
  "phase_number": "${PHASE_NUMBER}",
  "phase_dir": "${PHASE_DIR}",
  "capsule_path": ".task-capsules/task-04.capsule.json",
  "plan_task_path": "${PHASE_DIR}/PLAN/task-04.md",
  "contract_slice_paths": [
    "${PHASE_DIR}/API-CONTRACTS/sites-create.md",
    "${PHASE_DIR}/API-CONTRACTS/sites-list.md"
  ],
  "interface_standards_md_path": "${PHASE_DIR}/INTERFACE-STANDARDS.md",
  "design_ref_path": "${PHASE_DIR}/design/sites-list-table.png",
  "wave_context_path": "${PHASE_DIR}/wave-3-context.md",
  "typecheck_cmd": "pnpm typecheck",
  "build_cmd": "pnpm build",
  "binding_requirements": [
    "binding-CONTEXT-D-02",
    "binding-INTERFACE-error-shape"
  ]
}
```

**Field semantics:**

| Field | Required | Description |
|---|---|---|
| `task_id` | yes | Full ID like `task-04`. Spawn-guard reads this from prompt to validate against `.spawn-count.json`'s `remaining[]`. |
| `wave_id` | yes | Integer wave number for narration + commit message tag. |
| `phase_number` | yes | e.g. `7.14`. Used in commit message `feat(7.14-04): ...`. |
| `phase_dir` | yes | Absolute path. Subagent reads files relative to this. |
| `capsule_path` | yes | `.task-capsules/task-${N}.capsule.json` written by `pre-executor-check.py`. PreToolUse Agent hook BLOCKS spawn if this file is missing. |
| `plan_task_path` | yes | Per-task split file. Subagent loads via `vg-load --artifact plan --task NN`. |
| `contract_slice_paths` | maybe | List of per-endpoint contract slices. Empty when task touches no API. |
| `interface_standards_md_path` | yes | Phase API/FE/CLI envelope contract. Subagent MUST follow before local preference. |
| `design_ref_path` | maybe | Resolved PNG from L1 design-pixel gate. Present when task has `<design-ref>`. NULL otherwise. |
| `wave_context_path` | yes | `${PHASE_DIR}/wave-{N}-context.md` listing wave-mate field alignment. |
| `typecheck_cmd` | yes | From `vg.config.md > build_gates.typecheck_cmd`. Subagent runs before commit. |
| `build_cmd` | maybe | From `vg.config.md > build_gates.build_cmd`. May be empty. |
| `binding_requirements` | yes | Citations the subagent's commit MUST satisfy via `// vg-binding: <id>` comments + commit-msg cite. |

---

## Prompt template

The orchestrator renders the template below (substituting `${...}` from
its environment + the per-task envelope above) and passes the result as
the `prompt` argument to the Agent tool call.

````
<vg_executor_rules>
@.claude/commands/vg/_shared/vg-executor-rules.md
</vg_executor_rules>

<bootstrap_rules>
${BOOTSTRAP_RULES_BLOCK}
</bootstrap_rules>

<build_config>
typecheck_cmd: ${typecheck_cmd}
build_cmd: ${build_cmd}
phase: ${phase_number}
wave: ${wave_id}
task_id: ${task_id}
</build_config>

<task_context_capsule path="${capsule_path}">
# CRITICAL: read this file FIRST. The capsule is the deterministic
# context contract assembled by pre-executor-check.py. The PreToolUse
# Agent hook denied your spawn unless this file exists on disk.
@${capsule_path}
</task_context_capsule>

<task_plan_slice>
# Per-task plan slice (split form). Loaded via:
#   vg-load --phase ${phase_number} --artifact plan --task ${task_id}
# This is your task body — implement EXACTLY what is described here.
# Do NOT paraphrase, expand scope, or invent additional behavior.
@${plan_task_path}
</task_plan_slice>

<contract_context>
# Per-endpoint contract slices. Loaded via:
#   vg-load --phase ${phase_number} --artifact contracts --endpoint <slug>
# COPY VERBATIM (not retype). The slices below are scoped to the
# endpoints THIS task touches — full API-CONTRACTS.md is NOT injected
# (per audit doc 2026-05-04 line 783 migration).
${CONTRACT_SLICE_BLOCKS}    # one @<path> per contract_slice_paths entry
</contract_context>

<interface_standards_context>
# Phase-local API/FE/CLI communication contract.
@${interface_standards_md_path}
</interface_standards_context>

<wave_context>
# Other tasks running in THIS WAVE — field names + endpoints MUST align.
@${wave_context_path}
</wave_context>

<design_context>
# L1 design-pixel gate verified this PNG exists on disk before spawn.
# Match the screenshot exactly. No "improvements".
${DESIGN_REF_BLOCK}    # @${design_ref_path} when present, else "NONE — non-UI task"
</design_context>

<binding_requirements>
${BINDING_REQUIREMENTS_LIST}
# Each requirement MUST be satisfied via a `// vg-binding: <id>` comment
# in the modified file AND cited in the commit message body.
</binding_requirements>

# ============================================================
# PROCEDURE — execute these steps in order
# ============================================================

1. **Read capsule** at `${capsule_path}`. Validate required fields
   present (`task_context`, `contract_context`, `goals_context`,
   `sibling_context`, `downstream_callers`, `build_config`). If any
   required field is missing or empty, return error JSON immediately:
   `{"error": "capsule_field_missing", "field": "<name>", "task_id": "${task_id}"}`.

2. **Implement** per the `<task_plan_slice>` body. Touch ONLY the files
   listed in the task's `<file-path>` / `<edits-*>` attributes. Do not
   refactor unrelated code.

3. **Add binding markers** — for each modified source file, add a
   `// vg-binding: <id>` comment (or language-appropriate equivalent:
   `# vg-binding:` for Python, `<!-- vg-binding: -->` for HTML/MD)
   covering each entry in `binding_requirements`.

4. **Run typecheck**: `${typecheck_cmd}`. If exit code != 0, return
   error JSON: `{"error": "typecheck_failed", "stderr": "<tail>", "task_id": "${task_id}"}`.
   Do NOT commit on typecheck failure.

5. **Stage + commit** — exactly ONE commit. Multiple commits are caught
   by post-spawn R5 check (`git log --oneline ${prev_sha}..HEAD | wc -l > 1`).
   Commit message format:
     `<type>(${phase_number}-${task_num}): <subject>`
     where type ∈ {feat, fix, refactor, test, chore}
   Body MUST cite each binding: `Per CONTEXT.md D-XX` or
   `Per INTERFACE-STANDARDS § <section>`.
   NO `--no-verify` on `apps/**/src/**`, `packages/**/src/**`.

6. **Write fingerprint** at `${phase_dir}/.fingerprints/task-${task_id}.fingerprint.md`
   summarizing files touched, line count delta, gate evidence (typecheck
   exit code, test count). Format per `vg-executor-rules.md § Fingerprint`.

7. **Write read-evidence** at `${phase_dir}/.read-evidence/task-${task_id}.json`
   IF `design_ref_path` was present in input. JSON must contain:
   ```json
   {
     "design_ref_path": "...",
     "read_at": "ISO-8601",
     "screenshot_sha256": "...",
     "rendered_components": ["..."]
   }
   ```
   If `design_ref_path` was NULL (non-UI task), DO NOT create this file —
   the post-spawn validator will check both directions.

8. **Return JSON** to the orchestrator (see Output JSON contract below).
````

**Rendering notes for the orchestrator:**

- `${BOOTSTRAP_RULES_BLOCK}` comes from `vg_bootstrap_render_block` in
  `bootstrap-inject.sh` (target_step="build").
- `${CONTRACT_SLICE_BLOCKS}` is built by joining `@<path>` lines for
  each entry in `contract_slice_paths` (one per endpoint).
- `${DESIGN_REF_BLOCK}` is `@${design_ref_path}` when present, else the
  literal string `NONE — non-UI task`.
- `${BINDING_REQUIREMENTS_LIST}` is a markdown bullet list of the
  `binding_requirements` array.

The full rendered prompt is also persisted to
`${PHASE_DIR}/.build/wave-${wave_id}/executor-prompts/${task_id}.prompt.md`
for the D-06 task-fidelity audit (post-spawn 3-way hash compare).

---

## Output JSON contract (subagent returns)

```json
{
  "task_id": "task-04",
  "artifacts_written": [
    "src/foo.ts",
    "tests/foo.spec.ts"
  ],
  "commit_sha": "abc123def4567890",
  "bindings_satisfied": [
    "binding-CONTEXT-D-02",
    "binding-INTERFACE-error-shape"
  ],
  "fingerprint_path": "${PHASE_DIR}/.fingerprints/task-04.fingerprint.md",
  "read_evidence_path": "${PHASE_DIR}/.read-evidence/task-04.json",
  "build_log_path": "${PHASE_DIR}/BUILD-LOG/task-04.md",
  "warnings": []
}
```

**Field semantics:**

| Field | Required | Description |
|---|---|---|
| `task_id` | yes | MUST match the input `task_id` exactly. Mismatch = orchestrator rejects return. |
| `artifacts_written` | yes | List of repo-relative paths the subagent created or modified. Each MUST exist on disk at return time. |
| `commit_sha` | yes | Full or short SHA of the single commit this task produced. Orchestrator validates `git rev-parse <sha>` succeeds. |
| `bindings_satisfied` | yes | Subset of input `binding_requirements` the subagent satisfied. Empty = task plan binding requirements not met. |
| `fingerprint_path` | yes | Path written in step 6 of procedure. Must exist on disk. |
| `read_evidence_path` | maybe | Path written in step 7. NULL when no `design_ref_path` was passed. |
| `build_log_path` | yes | Path written by subagent procedure step 13 — `${PHASE_DIR}/BUILD-LOG/task-${task_id}.md`. R1a UX baseline Req 1 layer 1 (per-task split). Orchestrator validates the file exists on disk before marking task complete. Post-executor (Task 11) concats every `BUILD-LOG/task-*.md` into Layer 3 `BUILD-LOG.md`; missing this file breaks aggregation. |
| `warnings` | optional | Non-blocking issues the subagent surfaces (e.g., flaky test re-tried, deprecated API used). |

**Error return format** (any procedure step failure):

```json
{
  "error": "<machine-readable error code>",
  "task_id": "task-04",
  "details": "<one-line human-readable cause>",
  "stderr": "<command stderr tail when applicable>"
}
```

The orchestrator narrates failure via:
```bash
bash scripts/vg-narrate-spawn.sh vg-build-task-executor failed "task-${N}: <error>"
```

---

## Failure modes table

| Failure | Detection | Subagent action |
|---|---|---|
| capsule missing field | first-line check at procedure step 1 | return error JSON `{"error": "capsule_field_missing", "field": "<name>", "task_id": "<id>"}` |
| capsule file missing on disk | spawn-guard PreToolUse hook denies BEFORE subagent runs | (subagent never starts; orchestrator gets deny message and re-runs `pre-executor-check.py`) |
| typecheck fail | exit code != 0 from `${typecheck_cmd}` | return error JSON with `stderr` tail; DO NOT commit |
| build fail | exit code != 0 from `${build_cmd}` (when set) | return error JSON; DO NOT commit |
| multiple commits | R5 catches via `git log --oneline ${prev_sha}..HEAD \| wc -l > 1` (orchestrator post-spawn) | subagent should never produce multiple commits; if it does, returns error noting accidental split |
| binding missing in modified file | post-spawn output validator greps modified files for `// vg-binding:` markers | return error JSON listing unsatisfied bindings |
| design-ref read but no read-evidence written | post-spawn output validator: `design_ref_path` in input + `read_evidence_path` NULL in return | return error JSON `{"error": "design_evidence_missing", ...}` |
| commit-msg hook rejection (binding cite missing) | `git commit` exit code 1, hook stderr contains "binding" | return error JSON; orchestrator routes to gap-recovery |
| `subagent_type` typo in spawn | spawn-guard PreToolUse hook denies | (orchestrator sees deny; re-spawn with correct `vg-build-task-executor`) |
| `task_id` not in `remaining[]` | spawn-guard PreToolUse hook denies (Task 1, commit `6135701`) | (orchestrator sees deny; either typo in task_id or already spawned this task) |

---

## Validation by main agent on subagent return

The main agent (orchestrator) MUST validate the returned JSON before
marking the task complete. Per task:

- `task_id` matches the spawn input `task_id` exactly
- `commit_sha` resolves: `git rev-parse ${commit_sha}` exit code 0
- `bindings_satisfied` non-empty AND superset of `binding_requirements`
  required for this task
- `fingerprint_path` file exists on disk + non-empty
- `read_evidence_path` exists on disk IF `design_ref_path` was passed in
  input envelope; MUST be absent (or null in return) when `design_ref_path`
  was NULL
- `build_log_path` is present in return JSON (non-empty string), file
  exists on disk + non-empty, and resolves to
  `${PHASE_DIR}/BUILD-LOG/task-${task_id}.md` (per R1a UX baseline Req 1
  layer 1). Orchestrator MUST `[ -s "${build_log_path}" ]` before marking
  task complete; missing layer-1 split breaks post-executor's Layer 2/3
  aggregation (Task 11 concats every `BUILD-LOG/task-*.md` into the
  canonical `BUILD-LOG.md`).
- All `artifacts_written` paths exist on disk
- `commit_sha` appears in `git log ${WAVE_TAG}..HEAD` (i.e., the commit
  was made within this wave's range, not pre-existing)

If any check fails: do NOT mark task complete. Route to gap-recovery
via the orchestrator's standard re-dispatch path
(block-resolver L1 in `waves-overview.md` § 8d.1) before treating the
wave as failed.

The post-wave aggregation in `waves-overview.md` § 8d (R5 spawn plan
honor check, commit count audit, attribution audit, integrity
reconcile, UI-MAP injection audit, task-fidelity audit) provides the
secondary safety net — even if a subagent's return JSON looks valid,
the wave gates catch parallel-executor races, paraphrase, and
attribution corruption that single-task validation cannot see.
