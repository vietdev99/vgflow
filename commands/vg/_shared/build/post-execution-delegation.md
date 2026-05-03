# build post-execution delegation contract (vg-build-post-executor subagent)

<!-- # Exception: contract document, not step ref — H1/HARD-GATE not required.
     This ref describes a JSON envelope + prompt template + return contract
     for the `vg-build-post-executor` subagent. It has no `step-active` /
     `mark-step` lifecycle of its own — `post-execution-overview.md` STEP 5
     owns those. The reviewer audit (B1/B2 FAIL) flagged the missing
     `# build <name> (STEP N)` H1 + top HARD-GATE; both are intentionally
     absent because this file is a contract, not an executable step body. -->

This file contains the input envelope, prompt template, and output
JSON contract for `Agent(subagent_type="vg-build-post-executor",
prompt=...)`.

Read `post-execution-overview.md` for the orchestrator-side
responsibilities (pre-spawn checklist, fingerprint existence
fail-fast, spawn site narration, post-spawn validation of returned
JSON, marker emission). This file describes ONLY the spawn payload +
return contract.

The shapes below are LOAD-BEARING for Task 11
(`vg-build-post-executor` SKILL.md). Drift here breaks the
subagent's input parser and the orchestrator's return validator.
Do not change field names.

Unlike `waves-delegation.md` (parallel spawn — N executors per wave),
this delegation is **single-spawn**: the orchestrator emits ONE
Agent() call and the subagent walks all task results sequentially
inside its own context. This single-vs-parallel distinction is
enforced by the orchestrator prompt structure (see
`post-execution-overview.md` HARD-GATE), not by the spawn-guard
(which only enforces count for `vg-build-task-executor`).

---

## Input contract (the JSON envelope)

The orchestrator constructs this envelope ONCE per phase before
rendering the prompt template below. All paths are absolute or
`${PHASE_DIR}`-rooted. The envelope is conceptual — the actual
transport is the rendered prompt text the orchestrator passes as the
`prompt=` argument to the Agent tool. The subagent recovers
structured fields by reading the named files (fingerprints, read
evidence, contract slices, design refs).

```json
{
  "phase_number": "7.14",
  "phase_dir": "/abs/path/to/.vg/phases/7.14-foo",
  "task_count": 5,
  "fingerprint_paths": [
    ".fingerprints/task-01.fingerprint.md",
    ".fingerprints/task-02.fingerprint.md",
    ".fingerprints/task-03.fingerprint.md",
    ".fingerprints/task-04.fingerprint.md",
    ".fingerprints/task-05.fingerprint.md"
  ],
  "read_evidence_paths": [
    ".read-evidence/task-01.json",
    null,
    ".read-evidence/task-03.json",
    ".read-evidence/task-04.json",
    null
  ],
  "contract_slice_paths": [
    "${PHASE_DIR}/API-CONTRACTS/sites-create.md",
    "${PHASE_DIR}/API-CONTRACTS/sites-list.md"
  ],
  "design_ref_paths": [
    "${PHASE_DIR}/design/sites-list-table.png",
    null,
    "${PHASE_DIR}/design/sites-detail.png",
    "${PHASE_DIR}/design/sites-edit-modal.png",
    null
  ],
  "design_fidelity_guard_script": "scripts/run-design-fidelity-guard.sh",
  "fidelity_profile_lock_path": "${PHASE_DIR}/.fidelity-profile.lock",
  "sandbox_url": "${SANDBOX_URL}",
  "task_endpoint_map": [
    {"task_id": "task-01", "endpoints": ["POST /api/sites"]},
    {"task_id": "task-02", "endpoints": []},
    {"task_id": "task-03", "endpoints": ["GET /api/sites"]},
    {"task_id": "task-04", "endpoints": ["PATCH /api/sites/:id"]},
    {"task_id": "task-05", "endpoints": []}
  ]
}
```

**Field semantics:**

| Field | Required | Description |
|---|---|---|
| `phase_number` | yes | e.g. `7.14`. Used in summary header + truthcheck commit attribution. |
| `phase_dir` | yes | Absolute path. Subagent resolves all relative paths against this. |
| `task_count` | yes | Integer count of tasks the subagent must walk. MUST equal `len(fingerprint_paths)`. |
| `fingerprint_paths` | yes | Per-task `.fingerprints/task-${N}.fingerprint.md` paths in task-id order. Pre-spawn fail-fast (overview Step 10) guarantees every entry exists. |
| `read_evidence_paths` | yes | Per-task `.read-evidence/task-${N}.json` paths. `null` entries for tasks WITHOUT a `<design-ref>`. Length MUST equal `task_count`. |
| `contract_slice_paths` | maybe | Phase-wide list of per-endpoint contract slices (one per touched endpoint). Loaded by orchestrator via `vg-load --artifact contracts --endpoint <slug>`. Empty when phase touches no API. |
| `design_ref_paths` | yes | Per-task design reference PNG paths. `null` per task without `<design-ref>`. Length MUST equal `task_count`. |
| `design_fidelity_guard_script` | yes | Path to the Haiku zero-context launcher (`scripts/run-design-fidelity-guard.sh`). When the script is absent (older installs / non-FE projects), the subagent invokes the inline validator `.claude/scripts/validators/verify-vision-self-verify.py` instead — see Procedure step 3. |
| `fidelity_profile_lock_path` | yes | Path to the locked fidelity profile YAML (declares `ssim_threshold`, `pixelmatch_threshold_pct`, `vision_self_verify` model + timeout). Subagent reads this for the L3 SSIM threshold. |
| `sandbox_url` | yes | Base URL for the truthcheck step (e.g. `http://localhost:3000`). Subagent curls `${sandbox_url}/health` to confirm reachability before per-endpoint checks. |
| `task_endpoint_map` | yes | Per-task list of endpoints (`<edits-endpoint>` extractions). Empty `endpoints[]` for non-API tasks (truthcheck SKIPs them, does NOT fail). |

---

## Prompt template

The orchestrator renders the template below (substituting `${...}`
from its environment + the envelope above) and passes the result as
the `prompt` argument to the Agent tool call. There is exactly ONE
Agent() call in this step.

````
<vg_executor_rules>
@.claude/commands/vg/_shared/vg-executor-rules.md
</vg_executor_rules>

<bootstrap_rules>
${BOOTSTRAP_RULES_BLOCK}
</bootstrap_rules>

<post_execution_config>
phase_number: ${phase_number}
phase_dir: ${phase_dir}
task_count: ${task_count}
sandbox_url: ${sandbox_url}
design_fidelity_guard_script: ${design_fidelity_guard_script}
fidelity_profile_lock_path: ${fidelity_profile_lock_path}
</post_execution_config>

<fingerprint_paths>
# One per task, task-id order. Validate L2 by hashing each.
${FINGERPRINT_PATHS_BLOCK}    # one path per line
</fingerprint_paths>

<read_evidence_paths>
# One per task, task-id order. `null` entries are tasks without design-ref.
# Validate L6 only for non-null entries.
${READ_EVIDENCE_PATHS_BLOCK}    # one path-or-null per line
</read_evidence_paths>

<design_ref_paths>
# One per task, task-id order. `null` entries are non-UI tasks (skip L3, L5, L6).
${DESIGN_REF_PATHS_BLOCK}    # one path-or-null per line
</design_ref_paths>

<contract_slice_paths>
# Per-endpoint contract slices for truthcheck reference.
${CONTRACT_SLICE_PATHS_BLOCK}    # one path per line
</contract_slice_paths>

<task_endpoint_map>
# Per-task endpoints to truthcheck via sandbox curl.
${TASK_ENDPOINT_MAP_JSON}    # JSON literal
</task_endpoint_map>

# ============================================================
# PROCEDURE — execute these steps in order, sequentially per task
# ============================================================

**Step 0 — BUILD-LOG concat (Layer 2 + Layer 3 — runs FIRST per
R1a UX baseline Req 1).** Aggregate the per-task BUILD-LOG split that
each `vg-build-task-executor` wrote (Layer 1) into the canonical flat
log + index BEFORE per-task gate validation, so SUMMARY.md (Step 7) can
reference finalized paths:

  1. Enumerate `${phase_dir}/BUILD-LOG/task-*.md` lexicographically.
  2. Write `${phase_dir}/BUILD-LOG/index.md` (Layer 2 TOC) — one bullet
     per task file, citing the H1 line as the one-line summary.
  3. Concat `BUILD-LOG/index.md` + every `BUILD-LOG/task-*.md` →
     `${phase_dir}/BUILD-LOG.md` (Layer 3 flat). Use atomic write
     (`BUILD-LOG.md.tmp` → `mv`).
  4. On filesystem error / sub-files missing → return error JSON
     `{"error": "build_log_concat_failed", "reason": "<errno>"}` and
     exit before any per-task gate work.

The orchestrator's post-spawn validator hashes the returned
`build_log_path` and rejects mismatch — drift here is a hard error.
This step exists in delegation (not just SKILL) because the
orchestrator-side validator and the SKILL-side procedure must agree on
the same field names + ordering.

For each task index `i` in [0, task_count):

1. **L2 fingerprint validation** — read
   `${fingerprint_paths[i]}` and run:
     `python3 scripts/verify-fingerprint.py --fingerprint ${fingerprint_paths[i]}`
   The validator re-hashes every file SHA cited in the fingerprint
   against the committed disk state. Exit code 0 = PASS. Non-zero =
   fingerprint references a file whose disk hash does not match —
   means the task either truncated or rewrote a file outside the
   committed scope. Add to `gates_failed[]` (gate=`L2`) and skip
   remaining gates for this task index (a corrupt fingerprint
   invalidates the rest).

2. **L3 SSIM diff** — only when `${design_ref_paths[i]} != null`.
   Read the SSIM threshold from `${fidelity_profile_lock_path}`
   (YAML key `ssim_threshold`, default `0.95`). Render the current
   build of the route associated with this task (use
   `verify-build-visual.py` which spins up the dev server and uses
   pixelmatch+PIL). If SSIM < threshold OR pixelmatch drift exceeds
   `pixelmatch_threshold_pct`, add to `gates_failed[]` (gate=`L3`).

3. **L5 design-fidelity-guard** — only when `${design_ref_paths[i]}
   != null`. Invoke:
     `bash ${design_fidelity_guard_script} --task ${task_id} \
       --phase-dir ${phase_dir} --design-ref ${design_ref_paths[i]}`
   The script spawns a Haiku zero-context with the design PNG + the
   task's commit diff and asks "does the code ship the components
   the PNG shows?". Verdict ∈ {PASS, FLAG, BLOCK}.
   - PASS → no action
   - FLAG → log to override-debt, do NOT add to gates_failed
   - BLOCK → add to `gates_failed[]` (gate=`L5`)

   When `${design_fidelity_guard_script}` is missing on disk
   (`[ ! -x "${design_fidelity_guard_script}" ]`), fall back to the
   inline validator:
     `python3 .claude/scripts/validators/verify-vision-self-verify.py \
       --phase-dir ${phase_dir} --task-num ${task_num} --slug <slug>`
   Same verdict semantics. This keeps installs without the script
   shim functional.

4. **L6 read-evidence** — only when `${design_ref_paths[i]} != null`.
   Re-hash the design PNG at `${design_ref_paths[i]}` and compare
   with the `screenshot_sha256` (or equivalent) recorded in
   `${read_evidence_paths[i]}`. Mismatch means the design was
   modified between executor read-time and post-execution — the
   executor's claim of "I read this PNG" is now stale. Return
   error JSON immediately:
     `{"error": "design_ref_drift", "task_id": "${task_id}", "expected": "<recorded>", "actual": "<rehashed>"}`
   (This is a hard error — no gap-closure attempt; the entire phase
   needs re-build against the current PNG.)

5. **API truthcheck** — for each task `i`, look up
   `task_endpoint_map[i].endpoints[]`. If empty, SKIP (non-API task).
   Otherwise:
   - Curl `${sandbox_url}/health` once per phase (cache the result).
     If health fails → add `{"task_id": "<all>", "gate": "truthcheck",
     "reason": "sandbox_unhealthy"}` to `gates_failed[]` and skip
     remaining truthcheck per-endpoint calls.
   - For each endpoint, curl `${sandbox_url}<method-and-path>` with
     a minimal smoke payload. 404 / connection refused → add
     `{"task_id": "${task_id}", "gate": "truthcheck", "reason":
     "endpoint_unreachable: <method-path>"}`.

6. **Gap closure** — for each entry in `gates_failed[]` produced in
   steps 1-5, attempt ONE auto-fix iteration:
   - Wait 5 seconds (lets background servers settle / dev server
     finish hot-reload).
   - Re-run the failed gate's validator command.
   - If the re-run passes, append to `gaps_closed[]` with `fix:
     "re-ran <gate>, now PASS"`.
   - If the re-run still fails, leave the entry in `gates_failed[]`
     (do NOT block here — the orchestrator decides via the
     post-spawn validator in `post-execution-overview.md`).

7. **Write SUMMARY.md** — atomically write the consolidated summary
   to `${phase_dir}/SUMMARY.md`. Per R1a UX baseline (only LARGE
   artifacts split — PLAN/API-CONTRACTS/TEST-GOALS/BUILD-LOG),
   SUMMARY.md is a SINGLE doc; do NOT 3-layer split.
   Required sections:
     ```markdown
     # Build Summary — Phase ${phase_number}

     **Total tasks:** ${task_count}
     **Verdict:** PASS | FAIL_WITH_GAPS | FAIL

     ## Per-task results
     | Task | L2 | L3 | L5 | L6 | Truthcheck |
     |---|---|---|---|---|---|
     | task-01 | PASS | PASS | PASS | PASS | PASS |
     | task-02 | PASS | n/a | n/a | n/a | n/a |
     | ...

     ## Gates failed
     - <task_id> <gate>: <reason>

     ## Gaps closed
     - <task_id> <gate>: <fix>
     ```
   Write atomically: write to `SUMMARY.md.tmp` then
   `mv SUMMARY.md.tmp SUMMARY.md` to avoid partial-write corruption
   if the subagent is killed mid-write.

8. **Compute summary_sha256**:
     `sha256sum ${phase_dir}/SUMMARY.md | cut -d' ' -f1`

9. **Compute build_log_sha256** (Layer 3 atomicity proof):
     `sha256sum ${phase_dir}/BUILD-LOG.md | cut -d' ' -f1`
   This is what the orchestrator re-hashes post-return to detect
   subagent confabulation about Layer 3 contents.

10. **Return JSON** to the orchestrator (see Output JSON contract
   below). Required keys include `build_log_path`,
   `build_log_index_path`, `build_log_sub_files`, and `build_log_sha256`
   produced in Step 0 + Step 9.
````

**Rendering notes for the orchestrator:**

- `${BOOTSTRAP_RULES_BLOCK}` comes from `vg_bootstrap_render_block`
  in `bootstrap-inject.sh` (target_step="build").
- `${FINGERPRINT_PATHS_BLOCK}` is a newline-joined list of
  `fingerprint_paths` entries.
- `${READ_EVIDENCE_PATHS_BLOCK}` is a newline-joined list with
  literal `null` for absent entries.
- `${DESIGN_REF_PATHS_BLOCK}` is a newline-joined list with literal
  `null` for absent entries.
- `${CONTRACT_SLICE_PATHS_BLOCK}` is a newline-joined list of
  `contract_slice_paths` entries.
- `${TASK_ENDPOINT_MAP_JSON}` is the JSON literal from the
  orchestrator's `${TASK_ENDPOINT_MAP_JSON}` file (overview Step 11).

The full rendered prompt is also persisted to
`${PHASE_DIR}/.build/post-executor-prompt.md` for audit replay.

---

## Output JSON contract (subagent returns)

```json
{
  "gates_passed": ["L2", "L3", "L5", "L6", "truthcheck"],
  "gates_failed": [
    {"task_id": "task-04", "gate": "L3", "reason": "SSIM 0.83 < threshold 0.95"}
  ],
  "gaps_closed": [
    {"task_id": "task-04", "gate": "L3", "fix": "re-rendered screenshot, SSIM 0.97 PASS"}
  ],
  "summary_path": "${PHASE_DIR}/SUMMARY.md",
  "summary_sha256": "abc123def4567890abc123def4567890abc123def4567890abc123def4567890",
  "build_log_path": "${PHASE_DIR}/BUILD-LOG.md",
  "build_log_index_path": "${PHASE_DIR}/BUILD-LOG/index.md",
  "build_log_sha256": "fed987...64hex",
  "build_log_sub_files": [
    "${PHASE_DIR}/BUILD-LOG/task-01.md",
    "${PHASE_DIR}/BUILD-LOG/task-02.md"
  ]
}
```

**Field semantics:**

| Field | Required | Description |
|---|---|---|
| `gates_passed` | yes | List of gate IDs that passed for AT LEAST ONE task in the phase. Orchestrator validates this is a SUPERSET of the required gates (`L2`, `L5`, `truthcheck` always; `L3`, `L6` when any task has `design_ref`). |
| `gates_failed` | yes | List of `{task_id, gate, reason}` triples for failures detected in steps 1-5. May be empty (clean phase). Each entry NOT closed by `gaps_closed[]` blocks marker write. |
| `gaps_closed` | yes | List of `{task_id, gate, fix}` triples for failures that re-passed after the 1-retry gap closure (procedure step 6). Used by orchestrator to determine whether to route to gap-recovery. |
| `summary_path` | yes | Absolute path to the SUMMARY.md file written in procedure step 7. Orchestrator validates `[ -f "${summary_path}" ]`. |
| `summary_sha256` | yes | SHA-256 hex of `${summary_path}` contents. Orchestrator re-hashes the file post-return and rejects mismatch (catches subagent confabulation about file contents). |
| `build_log_path` | yes | Absolute path to the Layer 3 flat concat written in procedure step 0 (`${PHASE_DIR}/BUILD-LOG.md`). Orchestrator validates `[ -s "${build_log_path}" ]` AND that it matches the entry contract `${PHASE_DIR}/BUILD-LOG.md`. R1a UX baseline Req 1. |
| `build_log_index_path` | yes | Absolute path to the Layer 2 TOC written in procedure step 0 (`${PHASE_DIR}/BUILD-LOG/index.md`). Orchestrator validates `[ -s "${build_log_index_path}" ]`. |
| `build_log_sha256` | yes | SHA-256 hex of `${build_log_path}` contents (procedure step 9). Orchestrator re-hashes post-return and rejects mismatch (catches subagent confabulation about concat contents). |
| `build_log_sub_files` | yes | List of every `${PHASE_DIR}/BUILD-LOG/task-*.md` (Layer 1 split) the subagent enumerated in procedure step 0. MUST be non-empty (entry contract `glob_min_count: 1`). Orchestrator validates each path exists. |

**Error return format** (any procedure step failure that prevents
SUMMARY.md write):

```json
{
  "error": "<machine-readable error code>",
  "task_id": "<id when applicable>",
  "details": "<one-line human-readable cause>"
}
```

The orchestrator narrates failure via:
```bash
bash scripts/vg-narrate-spawn.sh vg-build-post-executor failed "<gate-id>: <error>"
```

---

## Failure modes table

| Failure | Detection | Subagent action |
|---|---|---|
| fingerprint missing on disk | step 1 (file not found before validator runs) | error JSON `{"error": "fingerprint_missing", "task_id": "<id>"}` (pre-spawn fail-fast SHOULD have caught this; if it slips through, hard error here) |
| fingerprint hash mismatch (file SHA drift) | step 1 (validator exit code != 0) | log to `gates_failed[]` with `gate=L2`; skip steps 2-5 for this task (corrupt fingerprint invalidates rest) |
| SSIM below threshold | step 2 (SSIM < `ssim_threshold` from profile lock) | log to `gates_failed[]` with `gate=L3`; attempt gap closure (step 6) |
| pixelmatch drift exceeds threshold | step 2 (pixelmatch_pct > `pixelmatch_threshold_pct`) | log to `gates_failed[]` with `gate=L3`; attempt gap closure |
| design-fidelity-guard verdict=BLOCK | step 3 (Haiku zero-context returns BLOCK) | log to `gates_failed[]` with `gate=L5`; attempt gap closure |
| design-fidelity-guard verdict=FLAG | step 3 | log to override-debt; do NOT add to gates_failed |
| design-fidelity-guard script + fallback validator both missing | step 3 (`[ ! -x "${script}" ]` AND validator absent) | SKIP L5 (do NOT add to gates_passed; do NOT block) — log warning |
| read-evidence hash mismatch | step 4 (re-hashed PNG sha256 != recorded) | error JSON `{"error": "design_ref_drift", "task_id": "<id>", "expected": "...", "actual": "..."}` — hard error, no gap-closure attempt |
| read-evidence file missing despite design_ref present | step 4 (`design_ref_paths[i] != null` AND `read_evidence_paths[i] == null`) | log to `gates_failed[]` with `gate=L6`, reason `evidence_missing`; attempt gap closure |
| sandbox unreachable (health check fail) | step 5 (curl `${sandbox_url}/health` fails) | log single `{"task_id": "<all>", "gate": "truthcheck", "reason": "sandbox_unhealthy"}`; skip per-endpoint truthcheck calls |
| truthcheck endpoint 404 / connection refused | step 5 (curl `${sandbox_url}<endpoint>` fails) | log to `gates_failed[]` with `gate=truthcheck`; attempt gap closure |
| Gap closure exhausted (1 retry still fails) | step 6 (post-fix re-run still non-zero) | leave entry in `gates_failed[]`; do NOT block here (orchestrator decides) |
| SUMMARY.md write failed | step 7 (filesystem error, disk full, etc.) | error JSON `{"error": "summary_write_failed", "details": "<errno>"}` |
| SUMMARY.md path mismatch on return | step 8 (computed sha != re-hashed sha) | error JSON `{"error": "summary_hash_self_check_failed"}` (subagent should never emit this — internal consistency) |

---

## Validation by main agent on subagent return

The main agent (orchestrator) MUST validate the returned JSON before
writing the step marker. Per the post-spawn validation script in
`post-execution-overview.md`:

- Returned value parses as JSON and contains required keys
  (`gates_passed`, `gates_failed`, `gaps_closed`, `summary_path`,
  `summary_sha256`, `build_log_path`, `build_log_index_path`,
  `build_log_sha256`, `build_log_sub_files`)
- `gates_passed[]` is a SUPERSET of:
  - `{L2, L5, truthcheck}` always
  - `{L3, L6}` when ANY task in the phase has a non-`null`
    `design_ref_paths[i]` entry
- `summary_path` exists on disk: `[ -f "${summary_path}" ]`
- `sha256sum ${summary_path} | cut -d' ' -f1` equals
  `summary_sha256`
- `build_log_path` resolves to `${PHASE_DIR}/BUILD-LOG.md` (entry
  contract `must_write`), exists on disk, AND
  `sha256sum ${build_log_path} | cut -d' ' -f1` equals
  `build_log_sha256` (R2 round-2 fix — closes A4/E2/C5 BUILD-LOG
  contract drift between SKILL and delegation)
- `build_log_index_path` exists on disk and resolves to
  `${PHASE_DIR}/BUILD-LOG/index.md`
- `build_log_sub_files[]` is non-empty AND every entry exists on disk
  (entry contract `glob_min_count: 1` for `BUILD-LOG/task-*.md`)
- For every entry in `gates_failed[]`, there MUST be a matching
  entry in `gaps_closed[]` (same `task_id` + `gate`) — OTHERWISE
  route to gap-recovery (separate flow, out of scope here) BEFORE
  marking step complete

If any check fails: do NOT write the step marker. Either re-spawn
the post-executor (transient validator/sandbox failure) or surface
to the user (persistent failure requiring code fix). The
post-execution step is idempotent — re-spawn is safe.

The orchestrator's post-spawn validation is the LAST line of
defense; the subagent's per-task gate walk is the FIRST. Both
together ensure that no SUMMARY.md is written when L2/L3/L5/L6 +
truthcheck have not all PASSED (or been gap-closed) for every task.
