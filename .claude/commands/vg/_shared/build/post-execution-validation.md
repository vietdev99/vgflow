# build post-execution — Post-spawn validation + L4a gates + commit + schema + API-DOCS

Sub-ref of `post-execution-overview.md`. This file is the orchestrator's
work AFTER the `vg-build-post-executor` subagent returns its JSON
envelope. It runs through validation → deterministic phase-level
gates → SUMMARY commit → schema check → API-DOCS generation.

Read `post-execution-overview.md` first (HARD-GATE + Step ordering).
Read `post-execution-spawn.md` for the pre-spawn gates and the
single Agent() spawn call. Read `post-execution-delegation.md` for
the subagent's output JSON contract.

**HARD-GATE preserved (R2 round-2 BUILD-LOG enforcement):** the
post-executor returns `gates_passed`, `gates_failed`, `gaps_closed`,
`summary_path`, `summary_sha256`, AND BUILD-LOG layer keys
`build_log_path`, `build_log_index_path`, `build_log_sha256`,
`build_log_sub_files`. Marker write WITHOUT this validation is a
HARD VIOLATION — review/test/accept downstream consumes SUMMARY.md
and BUILD-LOG and trusts gates_passed; drift here corrupts the entire
phase tail.

After everything in this file completes, return to
`post-execution-overview.md` `## Step exit + marker` to touch
`9_post_execution.done`.

---

## Post-spawn validation

The orchestrator MUST validate the returned JSON BEFORE marking the
step complete. The post-executor returns the envelope shaped per
`post-execution-delegation.md`'s "Output JSON contract" section.

### Validation checks

1. **Schema**: returned value parses as JSON and contains required
   keys: `gates_passed`, `gates_failed`, `gaps_closed`, `summary_path`,
   `summary_sha256`, plus the BUILD-LOG layer keys `build_log_path`,
   `build_log_index_path`, `build_log_sha256`, `build_log_sub_files`
   (R2 round-2 — closes A4/E2/C5 BUILD-LOG contract drift between SKILL
   and delegation).
2. **Gates coverage**: `gates_passed[]` MUST include `L2`, `L5`, and
   `truthcheck` unconditionally; MUST include `L3` AND `L6` when ANY
   task in the phase carried a `<design-ref>` (i.e., when
   `${TASK_READ_EVIDENCE_LIST[@]}` contains any non-`null` entry).
3. **Summary path exists**: `[ -f "${summary_path}" ]` must succeed.
4. **Summary hash matches**: `sha256sum "${summary_path}" | cut -d' ' -f1`
   must equal `summary_sha256`.
5. **BUILD-LOG concat exists + hashes**: `[ -s "${build_log_path}" ]`
   AND `sha256sum "${build_log_path}" | cut -d' ' -f1` MUST equal
   `build_log_sha256`. The path MUST resolve to
   `${PHASE_DIR}/BUILD-LOG.md` (entry contract `must_write` Layer 3).
6. **BUILD-LOG index exists**: `[ -s "${build_log_index_path}" ]` AND
   the path MUST resolve to `${PHASE_DIR}/BUILD-LOG/index.md`.
7. **BUILD-LOG sub-files non-empty + on disk**: `build_log_sub_files[]`
   MUST be non-empty (entry contract `glob_min_count: 1` for
   `BUILD-LOG/task-*.md`) AND every entry must exist on disk.
8. **Failed-without-closure**: if `gates_failed[]` is non-empty AND
   no entry in `gaps_closed[]` covers each failure (matched by
   `task_id` + `gate`), route to gap-recovery (separate flow, out of
   scope here) — do NOT mark step complete.

```bash
RET="$POST_EXECUTOR_RETURN_JSON"   # captured from Agent() return
${PYTHON_BIN} - "$RET" "$PHASE_DIR" "${TASK_READ_EVIDENCE_LIST[*]}" <<'PY' || exit 1
import json, sys, hashlib, os
from pathlib import Path

ret = json.loads(sys.argv[1])
phase_dir = Path(sys.argv[2]).resolve()
re_list = sys.argv[3].split()

required_keys = {
    "gates_passed", "gates_failed", "gaps_closed",
    "summary_path", "summary_sha256",
    # R2 round-2: BUILD-LOG contract keys (closes A4/E2/C5 drift).
    "build_log_path", "build_log_index_path",
    "build_log_sha256", "build_log_sub_files",
}
missing_keys = required_keys - ret.keys()
if missing_keys:
    print(f"⛔ Post-executor return missing keys: {missing_keys}"); sys.exit(1)

gates_passed = set(ret["gates_passed"])
required_gates = {"L2", "L5", "truthcheck"}
has_design_ref = any(p != "null" for p in re_list)
if has_design_ref:
    required_gates |= {"L3", "L6"}

missing_gates = required_gates - gates_passed
if missing_gates:
    print(f"⛔ Post-executor gates_passed missing required: {missing_gates}"); sys.exit(1)

summary_path = ret["summary_path"]
if not Path(summary_path).is_file():
    print(f"⛔ summary_path does not exist on disk: {summary_path}"); sys.exit(1)

actual_sha = hashlib.sha256(Path(summary_path).read_bytes()).hexdigest()
if actual_sha != ret["summary_sha256"]:
    print(f"⛔ summary_sha256 mismatch: returned={ret['summary_sha256']} actual={actual_sha}")
    sys.exit(1)

# BUILD-LOG layer 3 (flat concat) — must equal entry contract path.
expected_build_log = phase_dir / "BUILD-LOG.md"
build_log_path = Path(ret["build_log_path"])
if build_log_path.resolve() != expected_build_log.resolve():
    print(f"⛔ build_log_path drift: returned={build_log_path} expected={expected_build_log}")
    sys.exit(1)
if not build_log_path.is_file() or build_log_path.stat().st_size == 0:
    print(f"⛔ build_log_path missing or empty: {build_log_path}"); sys.exit(1)
actual_bl_sha = hashlib.sha256(build_log_path.read_bytes()).hexdigest()
if actual_bl_sha != ret["build_log_sha256"]:
    print(f"⛔ build_log_sha256 mismatch: returned={ret['build_log_sha256']} actual={actual_bl_sha}")
    sys.exit(1)

# BUILD-LOG layer 2 (index TOC).
expected_index = phase_dir / "BUILD-LOG" / "index.md"
build_log_index_path = Path(ret["build_log_index_path"])
if build_log_index_path.resolve() != expected_index.resolve():
    print(f"⛔ build_log_index_path drift: returned={build_log_index_path} expected={expected_index}")
    sys.exit(1)
if not build_log_index_path.is_file() or build_log_index_path.stat().st_size == 0:
    print(f"⛔ build_log_index_path missing or empty: {build_log_index_path}"); sys.exit(1)

# BUILD-LOG layer 1 (per-task split) — entry contract glob_min_count: 1.
sub_files = ret.get("build_log_sub_files") or []
if not sub_files:
    print("⛔ build_log_sub_files empty — Layer 1 split missing (R1a UX baseline Req 1)")
    sys.exit(1)
missing_subs = [p for p in sub_files if not Path(p).is_file()]
if missing_subs:
    print(f"⛔ build_log_sub_files paths missing on disk: {missing_subs}"); sys.exit(1)

# Failed-without-closure check
unclosed = []
for fail in ret.get("gates_failed", []):
    matched = any(
        c.get("task_id") == fail.get("task_id") and c.get("gate") == fail.get("gate")
        for c in ret.get("gaps_closed", [])
    )
    if not matched:
        unclosed.append(f"{fail.get('task_id')}:{fail.get('gate')}")

if unclosed:
    print(f"⛔ Post-executor failures without gap closure: {unclosed}")
    print("   Route to gap-recovery before marking step complete.")
    sys.exit(1)

print(f"✓ Post-executor return validated: gates={sorted(gates_passed)}, "
      f"summary+build_log sha256 match, {len(sub_files)} BUILD-LOG sub-files")
PY
```

### Step 4.5 — L4a deterministic phase-level gates (BLOCK on violation)

After per-task gates complete and before SUMMARY.md is written, run 3
deterministic phase-level gates that catch issues per-task gates cannot
see (cross-file FE↔BE comparisons + cross-document spec drift):

```bash
EVIDENCE_DIR="${PHASE_DIR}/.evidence"
mkdir -p "$EVIDENCE_DIR"

# L4a-i: FE → BE call graph (exits 1 + writes evidence on gap)
FE_ROOT=$(vg_config_get paths.web_pages "apps/web/src")
BE_ROOT=$(vg_config_get code_patterns.api_routes "apps/api/src")
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-fe-be-call-graph.py \
  --fe-root "$FE_ROOT" --be-root "$BE_ROOT" \
  --phase "${PHASE_NUMBER}" \
  --evidence-out "${EVIDENCE_DIR}/fe-be-call-graph.json" || {
  echo "⛔ L4a-i: FE→BE call graph violations — see ${EVIDENCE_DIR}/fe-be-call-graph.json"
  L4A_FAILED=1
}

# L4a-ii: Contract shape (method match for now — body P3)
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-contract-shape.py \
  --contracts-dir "${PHASE_DIR}/API-CONTRACTS" \
  --fe-root "$FE_ROOT" \
  --phase "${PHASE_NUMBER}" \
  --evidence-out "${EVIDENCE_DIR}/contract-shape.json" || {
  echo "⛔ L4a-ii: contract shape mismatches — see ${EVIDENCE_DIR}/contract-shape.json"
  L4A_FAILED=1
}

# L4a-iii: Spec drift (status code heuristic)
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-spec-drift.py \
  --phase-dir "${PHASE_DIR}" \
  --phase "${PHASE_NUMBER}" \
  --evidence-out "${EVIDENCE_DIR}/spec-drift.json" || {
  echo "⛔ L4a-iii: spec drift — see ${EVIDENCE_DIR}/spec-drift.json"
  L4A_FAILED=1
}

if [ "${L4A_FAILED:-0}" = "1" ]; then
  # Emit telemetry — STEP 5.5 (next task) will pick up these evidence files
  # and run the auto-fix loop. Build does NOT mark complete with L4a violations.
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "build.l4a_violations_detected" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"evidence_dir\":\"${EVIDENCE_DIR}\"}" \
    2>/dev/null || true
else
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "build.l4a_gates_passed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\"}" \
    2>/dev/null || true
fi
```

### Commit SUMMARY.md + state files

The post-executor writes SUMMARY.md atomically. The orchestrator
commits it together with the updated state files:

```bash
git add ${PHASE_DIR}/SUMMARY*.md ${PLANNING_DIR}/STATE.md ${PLANNING_DIR}/ROADMAP.md
git commit -m "build({phase}): {completed}/{total} plans executed"
```

### Schema validation (BLOCK on SUMMARY.md frontmatter drift)

```bash
# v2.7 Phase E — schema validation post-write (BLOCK on SUMMARY.md frontmatter drift).
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-artifact-schema.py \
  --phase "${PHASE_NUMBER}" --artifact summary \
  > "${PHASE_DIR}/.tmp/artifact-schema-summary.json" 2>&1
SCHEMA_RC=$?
if [ "${SCHEMA_RC}" != "0" ]; then
  echo "⛔ SUMMARY.md schema violation — see ${PHASE_DIR}/.tmp/artifact-schema-summary.json"
  cat "${PHASE_DIR}/.tmp/artifact-schema-summary.json"
  exit 2
fi
```

### API-DOCS.md generation + coverage verify

```bash
# v2.48 — build-time API docs. Generated from API-CONTRACTS plus the current
# implementation so review/test consume what was actually built, not only the
# planning-time contract.
API_DOCS_PATH="${PHASE_DIR}/API-DOCS.md"
"${PYTHON_BIN}" .claude/scripts/generate-api-docs.py \
  --phase "${PHASE_NUMBER}" \
  --contracts "${PHASE_DIR}/API-CONTRACTS.md" \
  --plan "${PHASE_DIR}/PLAN.md" \
  --goals "${PHASE_DIR}/TEST-GOALS.md" \
  --interface-standards "${PHASE_DIR}/INTERFACE-STANDARDS.json" \
  --out "${API_DOCS_PATH}"
API_DOCS_RC=$?
if [ "${API_DOCS_RC}" != "0" ]; then
  echo "⛔ API docs generation failed — build cannot complete without API-DOCS.md."
  exit 2
fi

"${PYTHON_BIN}" .claude/scripts/validators/verify-api-docs-coverage.py \
  --phase "${PHASE_NUMBER}" \
  > "${PHASE_DIR}/.tmp/api-docs-coverage.json" 2>&1
API_DOCS_VERIFY_RC=$?
if [ "${API_DOCS_VERIFY_RC}" != "0" ]; then
  echo "⛔ API docs coverage failed — see ${PHASE_DIR}/.tmp/api-docs-coverage.json"
  cat "${PHASE_DIR}/.tmp/api-docs-coverage.json"
  exit 2
fi

"${PYTHON_BIN}" .claude/scripts/emit-evidence-manifest.py \
  --path "${API_DOCS_PATH}" \
  --source-inputs "${PHASE_DIR}/API-CONTRACTS.md,${PHASE_DIR}/PLAN.md,${PHASE_DIR}/TEST-GOALS.md" \
  --producer "vg:build/9_post_execution" >/dev/null 2>&1 || {
    echo "⛔ API-DOCS.md was written but evidence binding failed."
    exit 2
  }
echo "✓ API-DOCS.md generated and validated for review/test consumption"
```


