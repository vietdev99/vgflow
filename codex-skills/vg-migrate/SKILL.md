---
name: "vg-migrate"
description: "Convert legacy GSD phase artifacts to VG format"
metadata:
  short-description: "Convert legacy GSD phase artifacts to VG format"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Markdown progress + step markers | Do not rely on Claude's persistent task tail UI. |
| Playwright MCP | Main Codex orchestrator MCP tools, or smoke-tested subagents | If an MCP-using subagent cannot access tools in a target environment, fall back to orchestrator-driven/inline scanner flow. |
| Graphify MCP | Python/CLI graphify calls | VGFlow's build/review paths already use deterministic scripts where possible. |

<codex_runtime_contract>
### Provider/runtime parity contract

This generated skill must preserve the source command's artifacts, gates,
telemetry events, and step ordering on both Claude and Codex. Do not remove,
skip, or weaken a source workflow step because a Claude-only primitive appears
in the body below.

#### Provider mapping

| Source pattern | Claude path | Codex path |
|---|---|---|
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `commands/vg/_shared/lib/codex-spawn.sh --tier planner` |
| Build executor Agent | Use the source executor `Agent(...)` call | Use `codex-spawn.sh --tier executor --sandbox workspace-write` with explicit file ownership and expected artifact output |
| Adversarial/CrossAI reviewer | Use configured external CLIs and consensus validators | Use configured `codex exec`/Gemini/Claude commands from `.claude/vg.config.md`; fail if required CLI output is missing or unparsable |
| Haiku scanner / Playwright / Maestro / MCP-heavy work | Use Claude subagents where the source command requires them | Keep MCP-heavy work in the main Codex orchestrator unless child MCP access was smoke-tested; scanner work may run inline/sequential instead of parallel, but must write the same scan artifacts and events |
| Reflection / learning | Use `vg-reflector` workflow | Use the Codex `vg-reflector` adapter or `codex-spawn.sh --tier scanner`; candidates still require the same user gate |

### Codex hook parity

Claude Code has a project-local hook substrate; Codex skills do not receive
Claude `UserPromptSubmit`, `Stop`, or `PostToolUse` hooks automatically.
Therefore Codex must execute the lifecycle explicitly through the same
orchestrator that writes `.vg/events.db`:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Treat the command body's explicit `vg-orchestrator run-start` as mandatory; if missing or failing, BLOCK before doing work |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Run the command body's terminal `vg-orchestrator run-complete` before claiming completion; if it returns non-zero, fix evidence and retry |
| `PostToolUse` edit -> `vg-edit-warn.py` | Warns that command/skill edits require session reload | After editing VG workflow files on Codex, tell the user the current session may still use cached skill text |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Do not rely on the hook; call explicit `vg-orchestrator mark-step` lines in the skill and preserve marker/telemetry events |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Do NOT blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
| `/vg:review` fix agents and `/vg:test` codegen agents | Use `codex-spawn.sh --tier executor` because they edit code/tests | `VG_CODEX_MODEL_EXECUTOR` or explicit `--model` if the command selected a configured fix model | `workspace-write` | changed files, tests run, unresolved risks |
| Rationalization guard, reflector, gap hunters | Use `codex-spawn.sh --tier scanner` for read-only classification, or `--tier adversarial` for independent challenge/review | `VG_CODEX_MODEL_SCANNER` or `VG_CODEX_MODEL_ADVERSARIAL` | `read-only` by default | compact JSON/markdown verdict; fail closed on empty/unparseable output |

If a source sentence says "MUST spawn Haiku" and the step needs MCP/browser
tools, Codex interprets that as "MUST run the scanner protocol and emit the
same artifacts/events"; it does not require a child process unless child MCP
access was smoke-tested in the current environment.

#### Non-negotiable guarantees

- Never skip source workflow gates, validators, telemetry events, or must-write artifacts.
- If Codex cannot emulate a Claude primitive safely, BLOCK instead of silently degrading.
- UI/UX, security, and business-flow checks remain artifact/gate driven: follow the source command's DESIGN/UI-MAP/TEST-GOALS/security validator requirements exactly.
- A slower Codex inline path is acceptable; a weaker path that omits evidence is not.
</codex_runtime_contract>

### Model tier mapping

Model mapping is tier-based, not vendor-name-based.

VGFlow keeps tier names in `.claude/vg.config.md`; Codex subprocesses use
the user's Codex config model by default. Pin a tier only after smoke-testing
that model in the target account, via `VG_CODEX_MODEL_PLANNER`,
`VG_CODEX_MODEL_EXECUTOR`, `VG_CODEX_MODEL_SCANNER`, or
`VG_CODEX_MODEL_ADVERSARIAL`:

| VG tier | Claude-style role | Codex default | Fallback |
|---|---|---|---|
| planner | Opus-class planning/reasoning | Codex config default | Set `VG_CODEX_MODEL_PLANNER` only after smoke-testing |
| executor | Sonnet-class coding/review | Codex config default | Set `VG_CODEX_MODEL_EXECUTOR` only after smoke-testing |
| scanner | Haiku-class scan/classify | Codex config default | Set `VG_CODEX_MODEL_SCANNER` only after smoke-testing |
| adversarial | independent reviewer | Codex config default | Set `VG_CODEX_MODEL_ADVERSARIAL` only after smoke-testing |

### Spawn helper

For subprocess-based children, use:

```bash
bash .claude/commands/vg/_shared/lib/codex-spawn.sh \
  --tier executor \
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.

### Known Codex caveats to design around

- Do not trust inline model selection for native subagents unless verified in the current Codex version; use TOML-pinned agents or `codex exec --model`.
- Do not combine structured `--output-schema` with MCP-heavy runs until the target Codex version is smoke-tested. Prefer plain text + post-parse for MCP flows.
- Recursive `codex exec` runs inherit sandbox constraints. Use the least sandbox that still allows the child to write expected artifacts.

### Support-skill MCP pattern

Pattern A: INLINE ORCHESTRATOR. For MCP-heavy support skills such as
`vg-haiku-scanner`, Codex keeps Playwright/Maestro actions in the main
orchestrator and only delegates read-only classification after snapshots are
captured. This preserves MCP access and avoids false confidence from a child
process that cannot see browser tools.

## Invocation

Invoke this skill as `$vg-migrate`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **Non-destructive** — never delete GSD originals. Move to `.gsd-backup/` within phase dir.
2. **MERGE, DO NOT OVERWRITE (tightened 2026-04-17)** — any existing artifact with user-authored content must be merged, not replaced. Agent writes to `{file}.staged` (not target). Before promoting staging → target, run preservation gates:
   - **ID preservation**: every `D-XX` (decisions) / `G-XX` (goals) / `Task N` / endpoint path in original MUST exist in staging. Missing = agent dropped content → ABORT, original untouched.
   - **Body preservation**: each element's body text must be ≥ 80% similar to original (`difflib.SequenceMatcher`). Lower ratio = agent rewrote prose → ABORT.
   - **On fail**: staging kept at `{file}.staged` for user inspection; backup at `.gsd-backup/{file}.{original-ext}`.
   Applies to: CONTEXT.md (step 4), API-CONTRACTS.md (step 5), TEST-GOALS.md (step 6), PLAN.md (step 7).
3. **Idempotent** — running migrate twice on same phase produces same result. Skip already-converted artifacts.
4. **Config-driven** — all format decisions from vg.config.md (contract_format, scan_patterns, etc.)
5. **No hardcoded project values** — endpoint paths, file locations, domain names all from config or code scan.
6. **Profile enforcement** — `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "migrate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/migrate.done"` at end.
</rules>

<objective>
Convert a phase that was planned/built using GSD workflows into VG-native format.
Ensures all VG pipeline steps (review, test, accept) can run on the migrated phase.

When to use:
- Project previously used GSD, now switching to VG
- Phase has CONTEXT.md (GSD format) but no API-CONTRACTS.md or TEST-GOALS.md
- Phase has old-style PLAN.md without VG task attributes
- `/vg:next` shows phase as `legacy_gsd` type
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

<step name="1_parse_args">
Parse `$ARGUMENTS`: phase number (required, OR `--self-test`), optional flags:
- `--dry-run` — show what would be converted, don't write files
- `--force` — re-convert even if VG artifacts already exist (backup existing first)
- `--skip-contracts` — skip API-CONTRACTS.md generation (manual later)
- `--skip-goals` — skip TEST-GOALS.md generation (manual later)
- `--allow-semantic-gaps` — bypass step 9 VG semantic gates. Logs override-debt. NOT recommended.
- `--allow-hallucinated-eps` — bypass step 4 hallucination check. Logs override-debt.
- `--self-test` — run gate logic on shipped fixture `<vgflow>/fixtures/migrate/legacy-sample/expected/`, diff vs golden report. Deterministic, no AI spawn. Use to verify gate logic correctness after editing migrate.md.

### Self-test mode (deterministic, no AI)

If `--self-test` flag passed, run gate validator against shipped fixture, diff vs golden report, exit. Skip all other steps.

```bash
if [[ "$ARGUMENTS" =~ --self-test ]]; then
  # Locate fixture (relative to vgflow-repo install or .claude/commands/ in project)
  FIXTURE_DIR=""
  for candidate in \
    "${REPO_ROOT}/fixtures/migrate/legacy-sample" \
    "${REPO_ROOT}/.claude/fixtures/migrate/legacy-sample" \
    "$(dirname "${0}")/../../fixtures/migrate/legacy-sample"; do
    [ -d "$candidate" ] && FIXTURE_DIR="$candidate" && break
  done

  if [ -z "$FIXTURE_DIR" ]; then
    echo "⛔ Self-test: fixture not found in any expected location."
    echo "   Looked in: \${REPO_ROOT}/fixtures/, .claude/fixtures/, sibling to migrate.md"
    exit 1
  fi

  echo "Self-test: fixture at $FIXTURE_DIR"
  VERIFY_SCRIPT="${REPO_ROOT}/scripts/verify-migrate-output.py"
  [ -f "$VERIFY_SCRIPT" ] || VERIFY_SCRIPT="${REPO_ROOT}/.claude/scripts/verify-migrate-output.py"
  [ -f "$VERIFY_SCRIPT" ] || { echo "⛔ verify-migrate-output.py missing"; exit 1; }

  ACTUAL=$(${PYTHON_BIN:-python3} "$VERIFY_SCRIPT" "${FIXTURE_DIR}/expected/" 2>&1)
  ACTUAL_RC=$?
  EXPECTED_FILE="${FIXTURE_DIR}/expected/validation-report.txt"

  if [ "$ACTUAL_RC" != "0" ]; then
    echo "⛔ Self-test FAIL: validator exit ${ACTUAL_RC} on golden fixture"
    echo "$ACTUAL"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "migrate_self_test_fail" "self-test" "migrate.1" "validator_fail" "FAIL" "{\"rc\":${ACTUAL_RC}}"
    fi
    exit 1
  fi

  # Diff actual vs golden (CRLF-tolerant for Windows)
  DIFF_OUT=$(echo "$ACTUAL" | diff --strip-trailing-cr "$EXPECTED_FILE" - 2>&1)
  if [ -z "$DIFF_OUT" ]; then
    echo "✓ Self-test PASS: gate logic produces golden output"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "migrate_self_test_pass" "self-test" "migrate.1" "fixture_match" "PASS" "{}"
    fi
    exit 0
  else
    echo "⛔ Self-test FAIL: actual output differs from golden:"
    echo "$DIFF_OUT"
    echo ""
    echo "Either: (a) gate logic regressed — fix verify-migrate-output.py"
    echo "        (b) intentional change — update fixtures/migrate/legacy-sample/expected/validation-report.txt"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "migrate_self_test_fail" "self-test" "migrate.1" "golden_diff" "FAIL" "{}"
    fi
    exit 1
  fi
fi
```
</step>

<step name="2_detect_artifacts">
## Artifact Inventory

Scan `${PHASE_DIR}/` and classify every file:

```bash
echo "=== Phase ${PHASE_NUMBER} Artifact Inventory ==="

# GSD-era artifacts (may need conversion)
GSD_ARTIFACTS=()
VG_ARTIFACTS=()
MISSING_VG=()

# Check each expected file
for f in RESEARCH.md CONTEXT.md PLAN.md SUMMARY*.md DISCUSSION-LOG.md; do
  if ls "${PHASE_DIR}"/$f 2>/dev/null; then
    GSD_ARTIFACTS+=("$f")
  fi
done

# Check VG-native artifacts
for f in API-CONTRACTS.md TEST-GOALS.md FLOW-SPEC.md PIPELINE-STATE.json; do
  if [ -f "${PHASE_DIR}/$f" ]; then
    VG_ARTIFACTS+=("$f")
  else
    MISSING_VG+=("$f")
  fi
done

# Check CONTEXT.md format (enriched vs flat)
if [ -f "${PHASE_DIR}/CONTEXT.md" ]; then
  # VG enriched format has sub-sections per decision: Endpoints:, UI Components:, Test Scenarios:
  ENRICHED=$(grep -c "Endpoints:\|UI Components:\|Test Scenarios:" "${PHASE_DIR}/CONTEXT.md" 2>/dev/null || echo 0)
  if [ "$ENRICHED" -gt 0 ]; then
    CONTEXT_FORMAT="vg-enriched"
  else
    CONTEXT_FORMAT="gsd-flat"
  fi
fi

# Check PLAN.md format (VG attributes vs GSD plain)
if ls "${PHASE_DIR}"/PLAN*.md 2>/dev/null; then
  VG_ATTRS=$(grep -c "<file-path>\|<contract-ref>\|<goals-covered>" "${PHASE_DIR}"/PLAN*.md 2>/dev/null || echo 0)
  if [ "$VG_ATTRS" -gt 0 ]; then
    PLAN_FORMAT="vg-attributed"
  else
    PLAN_FORMAT="gsd-plain"
  fi
fi
```

**Display inventory:**

```
Phase {N} — Artifact Inventory
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GSD artifacts found:     {list}
VG artifacts found:      {list}
VG artifacts missing:    {list}

CONTEXT.md format:       {gsd-flat | vg-enriched | missing}
PLAN.md format:          {gsd-plain | vg-attributed | missing}

Migration needed:
  [ ] CONTEXT.md enrichment    {yes/no — yes if gsd-flat}
  [ ] PLAN.md attribution      {yes/no — yes if gsd-plain}
  [ ] API-CONTRACTS.md         {generate/exists/skip}
  [ ] TEST-GOALS.md            {generate/exists/skip}
```

If ALL artifacts already VG-native → print "Phase already VG-native. Nothing to migrate." → STOP.
If `--dry-run` → print migration plan → STOP.
</step>

<step name="3_backup_originals">
## Backup GSD Originals

```bash
BACKUP_DIR="${PHASE_DIR}/.gsd-backup"
mkdir -p "$BACKUP_DIR"

# Backup files that will be converted (not all files)
if [ "$CONTEXT_FORMAT" = "gsd-flat" ]; then
  cp "${PHASE_DIR}/CONTEXT.md" "$BACKUP_DIR/CONTEXT.md.gsd"
  echo "Backed up: CONTEXT.md → .gsd-backup/CONTEXT.md.gsd"
fi

if [ "$PLAN_FORMAT" = "gsd-plain" ]; then
  for plan in "${PHASE_DIR}"/PLAN*.md; do
    PLAN_NAME=$(basename "$plan")
    cp "$plan" "$BACKUP_DIR/${PLAN_NAME}.gsd"
    echo "Backed up: ${PLAN_NAME} → .gsd-backup/${PLAN_NAME}.gsd"
  done
fi

# If --force and VG artifacts exist, backup those too
if [[ "$FLAGS" =~ --force ]]; then
  for f in API-CONTRACTS.md TEST-GOALS.md; do
    if [ -f "${PHASE_DIR}/$f" ]; then
      cp "${PHASE_DIR}/$f" "$BACKUP_DIR/${f}.prev"
      echo "Backed up: ${f} → .gsd-backup/${f}.prev"
    fi
  done
fi
```
</step>

<step name="4_enrich_context">
## Convert CONTEXT.md: GSD flat → VG enriched

**Skip if:** CONTEXT_FORMAT already "vg-enriched" AND not --force.

**GSD flat format** (decisions only):
```
## D-01: Use MongoDB for storage
MongoDB chosen for flexibility...

## D-02: REST API with Fastify
Standard REST endpoints...
```

**VG enriched format** (decisions + structured sub-sections):
```
## D-01: Use MongoDB for storage
MongoDB chosen for flexibility...

**Endpoints:** none (infrastructure decision)
**UI Components:** none
**Test Scenarios:**
- Database connection established on startup
- Collections created with correct indexes
```

**Conversion process — spawn agent (model=sonnet for quality):**

```
Agent(model="sonnet", description="Enrich CONTEXT.md for phase ${PHASE_NUMBER}"):
  prompt: |
    Convert this GSD-format CONTEXT.md to VG enriched format.
    
    RULES:
    1. Keep ALL existing decision text EXACTLY as-is (do not rewrite prose)
    2. ADD 3 sub-sections after each decision: Endpoints, UI Components, Test Scenarios
    3. Derive sub-sections from decision text + code scan:
       - Endpoints: grep code for routes/handlers matching this decision's domain
       - UI Components: grep code for pages/components matching this decision
       - Test Scenarios: infer 2-3 testable scenarios from decision text
    4. If decision is pure infra/config (no API/UI): write "none" for Endpoints/UI
    5. Do NOT invent endpoints that don't exist in code — only document what's built
    
    Code patterns to scan:
      API routes: ${config.code_patterns.api_routes}
      Web pages: ${config.code_patterns.web_pages}
    
    <context_md>
    @${PHASE_DIR}/CONTEXT.md
    </context_md>
    
    <code_scan_hints>
    Grep existing endpoints in codebase related to this phase's domain.
    </code_scan_hints>
    
    Output: write enriched CONTEXT.md to ${PHASE_DIR}/CONTEXT.md.enriched (STAGING — NOT overwriting CONTEXT.md yet)
```

**⛔ CRITICAL: Agent writes to STAGING file, not CONTEXT.md directly.** Validation below must pass before promoting staging → CONTEXT.md.

**Post-conversion validation (tightened 2026-04-17 — decision preservation gate):**

```bash
STAGING="${PHASE_DIR}/CONTEXT.md.enriched"
ORIGINAL="${PHASE_DIR}/.gsd-backup/CONTEXT.md.gsd"

if [ ! -f "$STAGING" ]; then
  echo "⛔ Agent did not write staging file ${STAGING}. Aborting."
  exit 1
fi

if [ ! -f "$ORIGINAL" ]; then
  echo "⛔ Backup missing at ${ORIGINAL} — step 3 did not run? Aborting."
  exit 1
fi

# ─── Gate 1: Every D-XX in ORIGINAL must exist in STAGING ───────────
${PYTHON_BIN:-python3} - "$ORIGINAL" "$STAGING" <<'PY' || exit 1
import re, sys
orig_path, stage_path = sys.argv[1], sys.argv[2]
orig = open(orig_path, encoding='utf-8').read()
stage = open(stage_path, encoding='utf-8').read()

# Extract decision IDs (D-01, D-02, etc.) — flexible matching for ## or ### prefix
def ids(text):
    return set(re.findall(r'(?mi)^#+\s*(D-\d+)\s*:', text))

orig_ids = ids(orig)
stage_ids = ids(stage)

missing = sorted(orig_ids - stage_ids, key=lambda x: int(x.split('-')[1]))
extra = sorted(stage_ids - orig_ids, key=lambda x: int(x.split('-')[1]))

if missing:
    print(f"⛔ DECISIONS LOST: agent dropped {len(missing)} decision(s) from original:")
    for d in missing:
        print(f"    {d}")
    print(f"\n    Original had {len(orig_ids)} decisions: {sorted(orig_ids)}")
    print(f"    Staging has  {len(stage_ids)} decisions: {sorted(stage_ids)}")
    print("")
    print(f"    Staging file kept at: {stage_path} for inspection")
    print(f"    Original preserved:    {orig_path}")
    print(f"    CONTEXT.md NOT modified. Re-run with different agent prompt or manual migration.")
    sys.exit(1)

if extra:
    print(f"⚠ WARNING: staging has {len(extra)} decision(s) not in original: {extra}")
    print(f"  Agent may have invented decisions. Review staging before accepting.")
    # Not fatal but loud

print(f"✓ All {len(orig_ids)} decisions preserved: {sorted(orig_ids)}")
PY

# ─── Gate 2: Decision BODY preserved (fuzzy — must not be rewritten) ─
${PYTHON_BIN:-python3} - "$ORIGINAL" "$STAGING" <<'PY' || exit 1
import re, sys, difflib
orig = open(sys.argv[1], encoding='utf-8').read()
stage = open(sys.argv[2], encoding='utf-8').read()

def extract_bodies(text):
    """Return dict D-XX -> body text (between header and next header / sub-section)."""
    bodies = {}
    # Split by decision headers
    chunks = re.split(r'(?mi)^(#+\s*D-\d+\s*:[^\n]*)', text)
    # chunks: [preamble, header1, body1, header2, body2, ...]
    i = 1
    while i < len(chunks):
        header = chunks[i]
        body = chunks[i+1] if i+1 < len(chunks) else ""
        m = re.search(r'(D-\d+)', header)
        if m:
            did = m.group(1)
            # Strip VG sub-sections (**Endpoints:**, **UI Components:**, **Test Scenarios:**)
            body_clean = re.split(r'(?m)^\*\*(?:Endpoints|UI Components|Test Scenarios):\*\*', body)[0]
            bodies[did] = body_clean.strip()
        i += 2
    return bodies

orig_bodies = extract_bodies(orig)
stage_bodies = extract_bodies(stage)

drift_threshold = 0.80  # similarity ratio; < threshold = body was rewritten
rewrites = []
for did, orig_body in orig_bodies.items():
    stage_body = stage_bodies.get(did, "")
    if not orig_body.strip() and not stage_body.strip():
        continue
    ratio = difflib.SequenceMatcher(None, orig_body, stage_body).ratio()
    if ratio < drift_threshold:
        rewrites.append((did, ratio, orig_body[:100], stage_body[:100]))

if rewrites:
    print(f"⛔ DECISION BODY REWRITTEN: agent rewrote prose for {len(rewrites)} decision(s):")
    for did, ratio, orig_snip, stage_snip in rewrites:
        print(f"    {did}: similarity={ratio:.0%}")
        print(f"      ORIGINAL: {orig_snip!r}")
        print(f"      STAGING:  {stage_snip!r}")
    print("")
    print(f"    Rule #1 violated: 'Keep ALL existing decision text EXACTLY as-is'.")
    print(f"    CONTEXT.md NOT modified. Staging preserved for review: $STAGING")
    sys.exit(1)

print(f"✓ All decision bodies preserved (>= 80% similarity)")
PY

# ─── Gate 3: Sub-section coverage check (3 sub-sections required, v1.14.4+) ───
DECISIONS=$(grep -cE "^#+\s*D-[0-9]+" "$STAGING")
ENDPOINTS=$(grep -c "^\*\*Endpoints:\*\*" "$STAGING")
UI_COMPS=$(grep -c "^\*\*UI Components:\*\*" "$STAGING")
TEST_SCENS=$(grep -c "^\*\*Test Scenarios:\*\*" "$STAGING")

COVERAGE_FAIL=0
if [ "$DECISIONS" != "$ENDPOINTS" ]; then
  echo "⛔ Gate 3 FAIL: ${DECISIONS} decisions but ${ENDPOINTS} **Endpoints:** sub-sections"
  COVERAGE_FAIL=$((COVERAGE_FAIL + 1))
fi
if [ "$DECISIONS" != "$UI_COMPS" ]; then
  echo "⛔ Gate 3 FAIL: ${DECISIONS} decisions but ${UI_COMPS} **UI Components:** sub-sections"
  COVERAGE_FAIL=$((COVERAGE_FAIL + 1))
fi
if [ "$DECISIONS" != "$TEST_SCENS" ]; then
  echo "⛔ Gate 3 FAIL: ${DECISIONS} decisions but ${TEST_SCENS} **Test Scenarios:** sub-sections"
  echo "   Blueprint step 2a CONTEXT format validation will block downstream."
  COVERAGE_FAIL=$((COVERAGE_FAIL + 1))
fi

if [ "$COVERAGE_FAIL" -gt 0 ]; then
  echo "⛔ ${COVERAGE_FAIL} sub-section coverage gate(s) failed. Staging at $STAGING — re-run agent."
  exit 1
fi
echo "✓ Gate 3: all ${DECISIONS} decisions có 3 sub-sections (Endpoints/UI/Test Scenarios)"

# ─── All gates passed: promote staging → CONTEXT.md atomically ───
echo ""
echo "✓ Migration gates passed. Promoting staging → CONTEXT.md"
mv "$STAGING" "${PHASE_DIR}/CONTEXT.md"

# ⛔ Hallucination check (tightened 2026-04-17): enriched CONTEXT may hallucinate endpoints.
# For every endpoint mentioned in Endpoints sections, grep actual API route files
# to confirm it exists. Missing endpoints → fail (rewrite required).
API_ROUTES_GLOB="${config.code_patterns.api_routes:-apps/api/src/modules/**/*.routes.ts}"

HALLUCINATED=0
while IFS= read -r ep; do
  # Extract VERB + path, e.g., "POST /api/sites"
  METHOD=$(echo "$ep" | grep -oE "^(GET|POST|PUT|PATCH|DELETE)")
  PATH_PART=$(echo "$ep" | grep -oE '/[a-zA-Z0-9/_:{}.-]+')
  [ -z "$METHOD" ] || [ -z "$PATH_PART" ] && continue

  # Search for route registration — various frameworks
  if ! grep -rEq "(\.|@)(${METHOD,,}|route|Route).*['\"\`]${PATH_PART}['\"\`]" $API_ROUTES_GLOB 2>/dev/null \
     && ! grep -rEq "method.*['\"\`]${METHOD}['\"\`].*path.*['\"\`]${PATH_PART}['\"\`]" $API_ROUTES_GLOB 2>/dev/null; then
    echo "⚠ HALLUCINATED endpoint: ${METHOD} ${PATH_PART} — not found in ${API_ROUTES_GLOB}"
    HALLUCINATED=$((HALLUCINATED + 1))
  fi
done < <(grep -oE "(GET|POST|PUT|PATCH|DELETE)\s+/[a-zA-Z0-9/_:{}.-]+" "${PHASE_DIR}/CONTEXT.md" | sort -u)

if [ "$HALLUCINATED" -gt 0 ]; then
  TOTAL_EPS=$(grep -oE "(GET|POST|PUT|PATCH|DELETE)\s+/" "${PHASE_DIR}/CONTEXT.md" | wc -l | tr -d ' ')
  RATIO=$((HALLUCINATED * 100 / (TOTAL_EPS + 1)))
  echo "Hallucination ratio: ${HALLUCINATED}/${TOTAL_EPS} (${RATIO}%)"
  if [ "$RATIO" -gt 10 ]; then
    echo "⛔ Hallucination ratio > 10% — enrichment agent likely invented endpoints."
    echo "   Fix: rewrite CONTEXT.md manually OR ensure code has the referenced routes first."
    if [[ ! "$ARGUMENTS" =~ --allow-hallucinated-eps ]]; then
      exit 1
    fi
  fi
fi
```
</step>

<step name="5_generate_contracts">
## Generate API-CONTRACTS.md (if missing)

**Skip if:** API-CONTRACTS.md exists AND not --force. Also skip if --skip-contracts.

This reuses the existing blueprint contract generation logic, but targeted at an already-built phase.

**Key difference from blueprint:** blueprint generates contracts BEFORE code. Migrate generates contracts FROM existing code (reverse-engineering).

```
Agent(model="sonnet", description="Generate API-CONTRACTS.md from built code"):
  prompt: |
    Read skill: .claude/skills/api-contract/SKILL.md — Mode: Generate.
    
    Generate API-CONTRACTS.md for phase ${PHASE_NUMBER}.
    This phase was ALREADY BUILT — extract contracts from existing code, don't invent.
    
    Inputs:
    1. CONTEXT.md enriched decisions (Endpoints sub-sections)
    2. Actual route handler code at: ${config.code_patterns.api_routes}
    3. Contract format: ${config.contract_format.type}
    
    Process:
    1. Read CONTEXT.md → list endpoints mentioned in Endpoints sub-sections
    2. For each endpoint, grep actual route handler in codebase
    3. Extract: method, path, request schema (from validation), response shape, auth middleware, error codes
    4. Generate 4-block contract per endpoint (auth, schema, errors, sample)
    5. If code uses Zod: extract schema directly from code (don't reinvent)
    6. If code uses bare validation: create Zod schema matching the validation logic
    
    CRITICAL: This is REVERSE-ENGINEERING from code, not forward-design.
    Every field, every status code, every auth guard MUST match what's actually in the code.
    
    Output: write to ${PHASE_DIR}/API-CONTRACTS.md.staged (STAGING — not final).
```

**Preservation gate (tightened 2026-04-17):**

If `API-CONTRACTS.md` already exists (`--force` case), backup first then diff:

```bash
STAGING="${PHASE_DIR}/API-CONTRACTS.md.staged"
TARGET="${PHASE_DIR}/API-CONTRACTS.md"

[ -f "$STAGING" ] || { echo "⛔ Agent did not write staging ${STAGING}"; exit 1; }

# If overwriting existing file, backup + verify endpoint preservation
if [ -f "$TARGET" ]; then
  cp "$TARGET" "${PHASE_DIR}/.gsd-backup/API-CONTRACTS.md.pre-migrate"
  ${PYTHON_BIN:-python3} - "$TARGET" "$STAGING" <<'PY' || exit 1
import re, sys
orig = open(sys.argv[1], encoding='utf-8').read()
new = open(sys.argv[2], encoding='utf-8').read()
def paths(t): return set(re.findall(r'(?m)^[#\s]*(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s`]+)', t))
orig_eps, new_eps = paths(orig), paths(new)
missing = orig_eps - new_eps
if missing:
    print(f"⛔ CONTRACTS LOST: {len(missing)} endpoint(s) in existing file not in new:")
    for m, p in sorted(missing): print(f"    {m} {p}")
    print(f"    Existing API-CONTRACTS.md preserved. Staging kept at {sys.argv[2]}")
    sys.exit(1)
print(f"✓ All {len(orig_eps)} existing endpoints preserved (+{len(new_eps - orig_eps)} new)")
PY
fi

mv "$STAGING" "$TARGET"
echo "✓ API-CONTRACTS.md written"
```
</step>

<step name="6_generate_goals">
## Generate TEST-GOALS.md (if missing)

**Skip if:** TEST-GOALS.md exists AND not --force. Also skip if --skip-goals.

Reuses blueprint step 2b5 logic but from enriched CONTEXT.md.

```
Agent(model="sonnet", description="Generate TEST-GOALS.md from enriched CONTEXT"):
  prompt: |
    Generate TEST-GOALS.md for phase ${PHASE_NUMBER}.
    
    Inputs:
    1. CONTEXT.md enriched decisions (Test Scenarios sub-sections)
    2. API-CONTRACTS.md (if generated in step 5)
    3. Built code (verify goals are testable against actual implementation)
    
    Rules:
    1. Every decision with Test Scenarios → at least 1 goal
    2. Every endpoint in API-CONTRACTS.md → at least 1 goal
    3. Goals describe WHAT to verify, not HOW
    4. Priority assignment:
       - Auth/payment/security → critical
       - Data mutation (POST/PUT/DELETE) → important (min)
       - Read-only (GET) → important
       - Cosmetic/display → nice-to-have
    5. Each goal MUST have: success criteria, mutation evidence, dependencies
    6. Add `infra_deps` field if goal requires services not in this phase:
       ```
       **Infra deps:** [clickhouse, kafka, pixel-server, redis]
       ```
       Goals with unmet infra_deps auto-classify as INFRA_PENDING in review Phase 4.
    
    Output format: follow TEST-GOALS.md template from blueprint step 2b5.
    Write to: ${PHASE_DIR}/TEST-GOALS.md.staged (STAGING — not final).
    
    7. **MANDATORY for mutation goals (Rule 3b — blueprint enforcement):**
       Every goal có non-empty **Mutation evidence:** PHẢI có **Persistence check:** block:
       ```
       **Persistence check:**
       - Pre-submit: read <field/row/state> value
       - Action: <what user does>
       - Post-submit wait: API 2xx + toast
       - Refresh: page.reload() OR navigate away + back
       - Re-read: <where to re-read>
       - Assert: <field> = <new value> AND != <pre value>
       ```
       Skip Persistence check chỉ khi: read-only goal (no mutation), final-step wizard, file upload.
    
    8. **Surface classification REQUIRED** — mỗi goal có dòng `**Surface:** ui|api|data|integration|time-driven|custom`
       (review/test pipeline cần để pick runner — backend phase tránh deadlock browser scan)
```

**Preservation gate (tightened 2026-04-17):**

```bash
STAGING="${PHASE_DIR}/TEST-GOALS.md.staged"
TARGET="${PHASE_DIR}/TEST-GOALS.md"

[ -f "$STAGING" ] || { echo "⛔ Agent did not write staging ${STAGING}"; exit 1; }

# If overwriting existing file (--force), preserve G-XX IDs + bodies
if [ -f "$TARGET" ]; then
  cp "$TARGET" "${PHASE_DIR}/.gsd-backup/TEST-GOALS.md.pre-migrate"
  ${PYTHON_BIN:-python3} - "$TARGET" "$STAGING" <<'PY' || exit 1
import re, sys, difflib
orig = open(sys.argv[1], encoding='utf-8').read()
new = open(sys.argv[2], encoding='utf-8').read()

def extract(text):
    """Return dict G-XX -> body (between header and next ## or end)."""
    bodies = {}
    for m in re.finditer(r'(?mi)^#+\s*Goal\s+(G-\d+)[^\n]*\n(.*?)(?=^#+\s*Goal\s+G-|\Z)', text, re.S):
        bodies[m.group(1)] = m.group(2).strip()
    # Fallback: simpler pattern "## G-XX"
    if not bodies:
        for m in re.finditer(r'(?mi)^#+\s*(G-\d+)\b[^\n]*\n(.*?)(?=^#+\s*G-|\Z)', text, re.S):
            bodies[m.group(1)] = m.group(2).strip()
    return bodies

orig_g = extract(orig)
new_g = extract(new)

missing = sorted(set(orig_g) - set(new_g), key=lambda x: int(x.split('-')[1]))
if missing:
    print(f"⛔ GOALS LOST: {len(missing)} goal(s) in existing file not in new: {missing}")
    print(f"    Existing TEST-GOALS.md preserved. Staging kept at {sys.argv[2]}")
    sys.exit(1)

# Body preservation check — each G-XX body >= 80% similar
rewrites = []
for gid, orig_body in orig_g.items():
    new_body = new_g.get(gid, "")
    if not orig_body and not new_body: continue
    ratio = difflib.SequenceMatcher(None, orig_body, new_body).ratio()
    if ratio < 0.80:
        rewrites.append((gid, ratio))
if rewrites:
    print(f"⛔ GOAL BODY REWRITTEN: {len(rewrites)} goal(s) with < 80% similarity:")
    for gid, r in rewrites: print(f"    {gid}: {r:.0%}")
    print(f"    Staging kept at {sys.argv[2]}")
    sys.exit(1)

print(f"✓ All {len(orig_g)} existing goals preserved (+{len(set(new_g)-set(orig_g))} new)")
PY
fi

# ─── Persistence check gate (Rule 3b enforcement, v1.14.4+) ───
PYTHONIOENCODING=utf-8 ${PYTHON_BIN:-python3} - "$STAGING" <<'PY' || exit 1
import re, sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding='utf-8')

# Parse per-goal sections — support 2-4 hash levels + optional "Goal" prefix
goal_pat = re.compile(r'(^#{2,4}\s+(?:Goal\s+)?G-\d+[^\n]*)\n(.*?)(?=^#{2,4}\s+(?:Goal\s+)?G-\d+|\Z)', re.M | re.S)

mutation_missing_persist = []
no_surface = []
mutation_count = 0
persist_count = 0

for m in goal_pat.finditer(text):
    header = m.group(1).strip()
    body = m.group(2)
    gid_m = re.search(r'G-\d+', header)
    gid = gid_m.group(0) if gid_m else '?'

    # Mutation evidence non-empty
    mut = re.search(r'\*\*Mutation evidence:\*\*\s*(.+?)(?=\n\s*\n|\n\*\*|\Z)', body, re.S)
    has_mut = False
    if mut:
        v = mut.group(1).strip()
        if v and not re.match(r'^(N/A|none|—|-|_|read-?only)\s*$', v, re.I):
            has_mut = True
            mutation_count += 1

    has_persist = bool(re.search(r'\*\*Persistence check:\*\*', body))
    if has_persist: persist_count += 1
    if has_mut and not has_persist:
        mutation_missing_persist.append(gid)

    # Surface classification
    if not re.search(r'\*\*Surface:\*\*\s*(ui|api|data|integration|time-driven|custom)', body, re.I):
        no_surface.append(gid)

errors = 0
if mutation_missing_persist:
    print(f"⛔ Rule 3b: {len(mutation_missing_persist)} mutation goals missing Persistence check:")
    for g in mutation_missing_persist[:10]:
        print(f"   - {g}")
    errors += 1

if no_surface:
    print(f"⛔ Surface classification missing: {len(no_surface)} goals")
    for g in no_surface[:10]:
        print(f"   - {g}")
    print("   Add: **Surface:** ui|api|data|integration|time-driven|custom")
    errors += 1

if errors:
    print(f"\nStaging at $STAGING — re-run agent or manual fix")
    sys.exit(1)

print(f"✓ Rule 3b: {mutation_count} mutation goals, {persist_count} với Persistence check, surface classified")
PY

mv "$STAGING" "$TARGET"
echo "✓ TEST-GOALS.md written + Rule 3b enforced"
```
</step>

<step name="6_5_link_plan_goals">
## Step 6.5 — Bidirectional PLAN ↔ TEST-GOALS linkage (v1.14.4+)

Mirror blueprint step 2b5 post-gen linkage. Without this, build executor không know which goal a task implements → breaks `<goals-covered>` citation.

```bash
PLAN_GLOB="${PHASE_DIR}/PLAN*.md"
GOALS_FILE="${PHASE_DIR}/TEST-GOALS.md"

if [ ! -f "$GOALS_FILE" ]; then
  echo "⚠ Skip linkage: TEST-GOALS.md missing (--skip-goals?)"
else
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN:-python3} - "$PHASE_DIR" <<'PY'
import re, sys, glob
from pathlib import Path

phase_dir = Path(sys.argv[1])
goals_file = phase_dir / "TEST-GOALS.md"
plan_files = sorted(glob.glob(str(phase_dir / "PLAN*.md")))
if not plan_files:
    print("⚠ No PLAN*.md files — skip linkage")
    sys.exit(0)

# Extract goal endpoints + IDs from TEST-GOALS
goals_text = goals_file.read_text(encoding='utf-8')
goal_ep_map = {}
for m in re.finditer(r'(?ms)^#{2,3}\s+(?:Goal\s+)?(G-\d+)[^\n]*\n(.+?)(?=^#{2,3}\s+(?:Goal\s+)?G-\d+|\Z)', goals_text):
    gid = m.group(1)
    body = m.group(2)
    eps = set()
    for ep_m in re.finditer(r'\b(GET|POST|PUT|PATCH|DELETE)\s+(/\S+)', body):
        eps.add((ep_m.group(1), ep_m.group(2)))
    goal_ep_map[gid] = eps

# Annotate each plan task with <goals-covered>
linked_tasks = 0
orphan_tasks = 0
for plan_path in plan_files:
    p = Path(plan_path)
    text = p.read_text(encoding='utf-8')
    orig = text

    # Per-task: find endpoints mentioned, match to goals
    def annotate(task_match):
        nonlocal linked_tasks, orphan_tasks
        task_block = task_match.group(0)
        # Skip if already has <goals-covered>
        if re.search(r'<goals-covered>', task_block):
            return task_block
        task_eps = set()
        for ep_m in re.finditer(r'\b(GET|POST|PUT|PATCH|DELETE)\s+(/\S+)', task_block):
            task_eps.add((ep_m.group(1), ep_m.group(2)))
        matched = sorted({gid for gid, eps in goal_ep_map.items() if eps & task_eps})
        if matched:
            covered = f"<goals-covered>{', '.join(matched)}</goals-covered>"
            linked_tasks += 1
        else:
            covered = "<goals-covered>no-goal-impact</goals-covered>"
            orphan_tasks += 1
        # Insert after task header
        return re.sub(r'(^#{2,3}\s+Task\s+\d+[^\n]*\n)', r'\1' + covered + '\n', task_block, count=1, flags=re.M)

    text = re.sub(
        r'(?ms)^#{2,3}\s+Task\s+\d+.+?(?=^#{2,3}\s+Task\s+\d+|^#{2}\s+Wave|\Z)',
        annotate,
        text
    )
    if text != orig:
        p.write_text(text, encoding='utf-8')

print(f"✓ Linkage: {linked_tasks} tasks linked to goals, {orphan_tasks} marked no-goal-impact")
PY
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "6_5_link_plan_goals" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/6_5_link_plan_goals.done"
```
</step>

<step name="7_attribute_plans">
## Attribute PLAN.md tasks (if GSD-plain format)

**Skip if:** PLAN_FORMAT already "vg-attributed" AND not --force.

Add VG task attributes to existing GSD plan tasks WITHOUT rewriting task content.

```
Agent(model="sonnet", description="Add VG attributes to PLAN.md tasks"):
  prompt: |
    Add VG task attributes to existing PLAN.md tasks for phase ${PHASE_NUMBER}.
    
    DO NOT rewrite task descriptions. ONLY ADD attributes.
    
    For each task (## Task N or ### Task N):
    1. Add <file-path> — grep codebase for the file this task actually created/modified
       (check git log for phase commits if available)
    2. Add <contract-ref> — if task touches API endpoint, reference API-CONTRACTS.md section
    3. Add <goals-covered> — map task to G-XX from TEST-GOALS.md
    4. Add <design-ref> — if task builds UI page and design assets exist
    
    Read:
    - ${PHASE_DIR}/PLAN*.md (tasks to attribute)
    - ${PHASE_DIR}/API-CONTRACTS.md (for contract-ref mapping)
    - ${PHASE_DIR}/TEST-GOALS.md (for goals-covered mapping)
    
    Output: write to ${PHASE_DIR}/PLAN.md.staged per source file (STAGING — not final overwrite).
```

**Preservation gate (tightened 2026-04-17):**

Agent wrote to staging files (one per PLAN*.md source). Verify task preservation before promoting to target.

```bash
# Process each PLAN*.md that has a staging file
for PLAN_FILE in "${PHASE_DIR}"/PLAN*.md; do
  [ -f "$PLAN_FILE" ] || continue
  BASENAME=$(basename "$PLAN_FILE")
  STAGING="${PHASE_DIR}/${BASENAME}.staged"

  [ -f "$STAGING" ] || { echo "⚠ No staging for ${BASENAME} — agent skipped?"; continue; }

  BACKUP="${PHASE_DIR}/.gsd-backup/${BASENAME}.gsd"
  ORIG="${BACKUP:-$PLAN_FILE}"
  [ -f "$ORIG" ] || ORIG="$PLAN_FILE"

  ${PYTHON_BIN:-python3} - "$ORIG" "$STAGING" <<'PY' || exit 1
import re, sys, difflib
orig = open(sys.argv[1], encoding='utf-8').read()
stage = open(sys.argv[2], encoding='utf-8').read()

def tasks(text):
    """Return dict 'Task N' -> body (between header and next ## Task or end)."""
    bodies = {}
    # Match "## Task N" or "### Task N" — capture title + body
    for m in re.finditer(r'(?mi)^#+\s*Task\s+(\d+)([^\n]*)\n(.*?)(?=^#+\s*Task\s+\d+|\Z)', text, re.S):
        num = m.group(1)
        title = m.group(2).strip()
        body = m.group(3)
        # Strip VG attribute blocks (<file-path>, <contract-ref>, <goals-covered>, <design-ref>)
        body_clean = re.sub(r'<(?:file-path|contract-ref|goals-covered|design-ref|api-endpoint|edits-\w+)>.*?</\1>', '', body, flags=re.S)
        body_clean = re.sub(r'<(?:file-path|contract-ref|goals-covered|design-ref|api-endpoint|edits-\w+)[^/>]*/>', '', body_clean)
        bodies[num] = {'title': title, 'body': body_clean.strip()}
    return bodies

orig_t = tasks(orig)
stage_t = tasks(stage)

# Gate A: every task in original must exist in staging
missing = sorted(set(orig_t) - set(stage_t), key=int)
if missing:
    print(f"⛔ TASKS LOST: {len(missing)} task(s) in original not in staging: Task {missing}")
    print(f"    Staging kept at {sys.argv[2]}. PLAN.md NOT modified.")
    sys.exit(1)

# Gate B: title + body preservation >= 80% similar (attribute-stripped)
rewrites = []
for tnum, orig_data in orig_t.items():
    stage_data = stage_t.get(tnum, {})
    # Title comparison
    if orig_data['title'] and stage_data.get('title'):
        title_ratio = difflib.SequenceMatcher(None, orig_data['title'], stage_data['title']).ratio()
    else:
        title_ratio = 1.0
    # Body comparison (after stripping VG attrs)
    body_ratio = difflib.SequenceMatcher(None, orig_data['body'], stage_data.get('body', '')).ratio() if (orig_data['body'] or stage_data.get('body')) else 1.0
    if title_ratio < 0.85 or body_ratio < 0.80:
        rewrites.append((tnum, title_ratio, body_ratio))

if rewrites:
    print(f"⛔ TASK CONTENT REWRITTEN: {len(rewrites)} task(s) diverged beyond threshold:")
    for tnum, tr, br in rewrites:
        print(f"    Task {tnum}: title_similarity={tr:.0%} body_similarity={br:.0%}")
    print(f"    Rule violated: 'DO NOT rewrite task descriptions. ONLY ADD attributes.'")
    print(f"    Staging kept at {sys.argv[2]}. PLAN.md NOT modified.")
    sys.exit(1)

print(f"✓ {sys.argv[2]}: all {len(orig_t)} tasks preserved (titles + bodies)")
PY

  # Gates passed — promote staging to final
  mv "$STAGING" "$PLAN_FILE"
  echo "✓ Attributed: ${BASENAME}"
done
```
</step>

<step name="8_write_pipeline_state">
## Initialize VG Pipeline State

```bash
# Write PIPELINE-STATE.json if not exists
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
if [ ! -f "$PIPELINE_STATE" ]; then
  ${PYTHON_BIN} -c "
import json
from datetime import datetime
state = {
  'status': 'migrated',
  'pipeline_step': 'review',
  'migrated_from': 'gsd',
  'migrated_at': datetime.now().isoformat(),
  'updated_at': datetime.now().isoformat(),
  'artifacts': {
    'context': 'enriched',
    'contracts': 'generated' if not skip_contracts else 'skipped',
    'goals': 'generated' if not skip_goals else 'skipped',
    'plans': 'attributed' if plan_format == 'gsd-plain' else 'already_vg',
  }
}
with open('${PIPELINE_STATE}', 'w') as f:
  json.dump(state, f, indent=2)
print('PIPELINE-STATE.json written')
"
fi

# Update .recon-state.json for /vg:next routing
${PYTHON_BIN} .claude/scripts/phase-recon.py \
  --phase-dir "${PHASE_DIR}" --profile "${PROFILE}" --quiet 2>/dev/null || true
```
</step>

<step name="8b_backfill_infra">
## Backfill Project-Level Infra Registers (2026-04-17)

Runs ONCE per project (idempotent). If project has multiple phases being migrated, this step auto-skips after first run. Use `--force-infra` to re-run.

VG infra features (debt/telemetry/security/visual/graphify) depend on registers that don't exist in legacy projects. Scan historical artifacts to backfill.

**Skip if already done:**
```bash
INFRA_MARKER=".planning/.infra-backfill.done"
if [ -f "$INFRA_MARKER" ] && [[ ! "$FLAGS" =~ --force-infra ]]; then
  echo "Infra already backfilled (${INFRA_MARKER}). Use --force-infra to re-run."
else
```

**8b.1 — Debt register backfill** (if `CONFIG_DEBT_REGISTER_PATH` config present):
```bash
if [ -n "${CONFIG_DEBT_REGISTER_PATH}" ] && [ ! -f "${CONFIG_DEBT_REGISTER_PATH}" ]; then
  ${PYTHON_BIN} - "${CONFIG_DEBT_REGISTER_PATH}" <<'PY'
import os, re, sys, glob
from datetime import datetime, timezone
from pathlib import Path
register = Path(sys.argv[1])
register.parent.mkdir(parents=True, exist_ok=True)

patterns = {
  "--allow-missing-commits": "critical", "--override-reason": "critical",
  "--override-regressions": "critical", "--force-accept-with-debt": "critical",
  "--allow-no-tests": "high", "--skip-design-check": "high",
  "--allow-intermediate": "high", "--skip-context-rebuild": "high",
  "--skip-crossai": "medium", "--skip-research": "medium", "--allow-deferred": "medium",
}

rows, count = [], 0
for phase_dir in sorted(glob.glob(".planning/phases/*/")):
  phase = Path(phase_dir).name.split("-")[0] if "-" in Path(phase_dir).name else Path(phase_dir).name
  for fname in ("build-state.log", "SANDBOX-TEST.md", "UAT.md"):
    fpath = Path(phase_dir) / fname
    if not fpath.exists(): continue
    try: text = fpath.read_text(encoding='utf-8', errors='ignore')
    except Exception: continue
    mtime = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    for pat, sev in patterns.items():
      for line in text.splitlines():
        if pat in line:
          count += 1
          reason = (line.strip()[:100]).replace("|","\\|")
          rows.append(f"| DEBT-HIST-{count:03d} | {sev} | {phase} | historical-{fname} | `{pat}` | {reason} | {mtime} | RESOLVED | (backfill) |")
          break  # one match per file per pattern

with open(register, 'w', encoding='utf-8') as f:
  f.write("# Override Debt Register\n\nAuto-maintained by VG workflow. Backfilled from historical artifacts.\n\n## Entries\n\n")
  f.write("| ID | Severity | Phase | Step | Flag | Reason | Logged (UTC) | Status | Resolved |\n")
  f.write("|----|----------|-------|------|------|--------|--------------|--------|----------|\n")
  f.write("\n".join(rows) + "\n")
print(f"  Debt backfill: {count} historical entries")
PY
else
  echo "  Debt register exists or not configured — skip"
fi
```

**8b.2 — Security register consolidation** (if `CONFIG_SECURITY_REGISTER_PATH` config present):
```bash
if [ -n "${CONFIG_SECURITY_REGISTER_PATH}" ] && [ ! -f "${CONFIG_SECURITY_REGISTER_PATH}" ]; then
  ${PYTHON_BIN} - "${CONFIG_SECURITY_REGISTER_PATH}" <<'PY'
import os, re, sys, glob
from datetime import datetime, timezone
from pathlib import Path
register = Path(sys.argv[1])
register.parent.mkdir(parents=True, exist_ok=True)

sev_map = {"critical":"critical","high":"high","medium":"medium","low":"low","info":"info"}
status_map = {"open":"OPEN","mitigated":"MITIGATED","resolved":"MITIGATED","fixed":"MITIGATED","in_progress":"IN_PROGRESS"}
threats, count = [], 0

for sec_file in sorted(glob.glob(".planning/phases/*/SECURITY*.md")) + sorted(glob.glob(".planning/phases/*/security.md")):
  phase = Path(sec_file).parent.name.split("-")[0] if "-" in Path(sec_file).parent.name else Path(sec_file).parent.name
  text = open(sec_file, encoding='utf-8', errors='ignore').read()
  blocks = re.split(r'^##\s+(?:Finding|Issue|Threat)[\s:]', text, flags=re.M|re.I)[1:]
  for blk in blocks:
    lines = blk.splitlines()
    title = (lines[0].strip().lstrip(':').strip() if lines else "untitled")[:100]
    sev, status, evidence, tax = "medium", "OPEN", "-", "custom"
    for line in lines:
      l = line.lower().strip()
      m = re.search(r'severity:\s*(\w+)', l);   sev = sev_map.get(m.group(1), sev) if m else sev
      m = re.search(r'status:\s*(\w+)', l);     status = status_map.get(m.group(1), status.upper()) if m else status
      m = re.search(r'evidence:\s*(.+)', line, re.I); evidence = m.group(1).strip()[:80] if m else evidence
      if l.startswith("taxonomy:") or l.startswith("stride:") or l.startswith("owasp:"):
        tax = line.split(":",1)[1].strip()[:40] if ":" in line else tax
    count += 1
    ts = datetime.fromtimestamp(Path(sec_file).stat().st_mtime, tz=timezone.utc).date().isoformat()
    threats.append((f"SEC-{count:03d}", sev, phase, tax, title, status, evidence, ts))

milestone = os.environ.get("MILESTONE_ID", "legacy")
with open(register, 'w', encoding='utf-8') as f:
  f.write(f"# Security Register (Milestone: {milestone})\n\nCumulative threat ledger. Backfilled from per-phase SECURITY.md files.\n\n## Threats\n\n")
  f.write("| ID | Severity | Phase(s) | Taxonomy | Title | Mitigation Status | Evidence | Created | Last Updated |\n")
  f.write("|----|----------|----------|----------|-------|-------------------|----------|---------|--------------|\n")
  for t in threats: f.write("| " + " | ".join(t[:7]) + f" | {t[7]} | {t[7]} |\n")
  f.write("\n## Composite Threats (auto-correlated)\n\n| Composite ID | Component SEC-IDs | Phases | Combined Severity | Rule |\n|-------------|-------------------|--------|-------------------|------|\n")
  f.write(f"\n## Decay Log\n- {datetime.now(timezone.utc).date().isoformat()} Backfilled {count} threats via /vg:migrate\n")
  f.write(f"\n## Audit Trail\n- {datetime.now(timezone.utc).date().isoformat()} /vg:migrate infra backfill: +{count} threats\n")
print(f"  Security backfill: {count} threats from legacy SECURITY.md files")
PY
else
  echo "  Security register exists or not configured — skip"
fi
```

**8b.3 — Telemetry init + git-log phase reconstruction**:
```bash
if [ -n "${CONFIG_TELEMETRY_PATH}" ] && [ ! -f "${CONFIG_TELEMETRY_PATH}" ]; then
  mkdir -p "$(dirname "${CONFIG_TELEMETRY_PATH}")"
  TS=$(date -u +%FT%TZ); SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
  echo "{\"ts\":\"${TS}\",\"event\":\"bootstrap\",\"phase\":\"\",\"step\":\"migrate\",\"session_id\":\"migrate\",\"git_sha\":\"${SHA}\",\"meta\":{\"reason\":\"vg:migrate infra backfill\"}}" > "${CONFIG_TELEMETRY_PATH}"

  # Reconstruct phase timings from git log commits (feat(X.Y-NN): pattern)
  ${PYTHON_BIN} - "${CONFIG_TELEMETRY_PATH}" <<'PY'
import subprocess, json, re, sys
from datetime import datetime
from pathlib import Path
path = Path(sys.argv[1])
r = subprocess.run(["git","log","--pretty=format:%H|%cI|%s","--reverse"], capture_output=True, text=True)
first, last = {}, {}
for line in r.stdout.splitlines():
  parts = line.split("|",2)
  if len(parts) != 3: continue
  sha, ts, msg = parts
  m = re.match(r'^(feat|fix|chore|docs|test|refactor)\((\d+(?:\.\d+)*)-\d+\):', msg)
  if not m: continue
  phase = m.group(2)
  first.setdefault(phase, (sha, ts))
  last[phase] = (sha, ts)
with open(path, 'a', encoding='utf-8') as f:
  for phase in sorted(first):
    s_sha, s_ts = first[phase]; e_sha, e_ts = last[phase]
    dur = int((datetime.fromisoformat(e_ts) - datetime.fromisoformat(s_ts)).total_seconds())
    f.write(json.dumps({"ts":e_ts,"event":"phase_complete_backfill","phase":phase,"step":"bootstrap-from-git","session_id":"migrate","git_sha":e_sha[:8],"meta":{"duration_s":dur,"source":"git-log"}}) + "\n")
print(f"  Telemetry init + {len(first)} phase timing events reconstructed from git log")
PY
else
  echo "  Telemetry already initialized or not configured — skip"
fi
```

**8b.4 — Graphify rebuild marker** (assume current graph is fresh, so first `/vg:map` after migrate doesn't force full rebuild):
```bash
GRAPH_MARKER="${CONFIG_PATHS_PLANNING_DIR:-.planning}/.graphify-last-rebuild"
if [ ! -f "$GRAPH_MARKER" ] && [ -f .claude/scripts/graphify-incremental.py ]; then
  ${PYTHON_BIN} .claude/scripts/graphify-incremental.py mark --marker "$GRAPH_MARKER" 2>/dev/null && \
    echo "  Graphify marker initialized"
fi
```

**8b.5 — Visual baseline auto-promote** (only if `visual_regression.enabled`):
```bash
if [ "${CONFIG_VISUAL_REGRESSION_ENABLED:-false}" = "true" ] && [ -d "${CONFIG_VISUAL_REGRESSION_CURRENT_DIR}" ] && [ ! -d "${CONFIG_VISUAL_REGRESSION_BASELINE_DIR}" ]; then
  for sd in "${CONFIG_VISUAL_REGRESSION_CURRENT_DIR}"/*/; do
    [ -d "$sd" ] || continue
    phase=$(basename "$sd")
    ${PYTHON_BIN} .claude/scripts/visual-diff.py promote --from "$sd" --to "${CONFIG_VISUAL_REGRESSION_BASELINE_DIR}/${phase}" 2>/dev/null
  done
  echo "  Visual baseline promoted from existing screenshots"
fi
```

**Mark infra backfill done:**
```bash
mkdir -p .planning
touch "$INFRA_MARKER"
fi  # end "already done" skip guard
```
</step>

<step name="9_validate_and_report">
## Validation + Report

**Completeness checks:**

```bash
echo "=== Migration Validation ==="

PASS=0
WARN=0
FAIL=0

# Check CONTEXT.md enriched
if grep -q "^\*\*Endpoints:\*\*" "${PHASE_DIR}/CONTEXT.md" 2>/dev/null; then
  echo "  [PASS] CONTEXT.md enriched"
  ((PASS++))
else
  echo "  [FAIL] CONTEXT.md not enriched"
  ((FAIL++))
fi

# Check API-CONTRACTS.md
if [ -f "${PHASE_DIR}/API-CONTRACTS.md" ]; then
  BLOCKS=$(grep -c '```typescript\|```yaml\|```python' "${PHASE_DIR}/API-CONTRACTS.md" 2>/dev/null || echo 0)
  if [ "$BLOCKS" -gt 0 ]; then
    echo "  [PASS] API-CONTRACTS.md with ${BLOCKS} code blocks"
    ((PASS++))
  else
    echo "  [WARN] API-CONTRACTS.md exists but no code blocks"
    ((WARN++))
  fi
else
  if [[ "$FLAGS" =~ --skip-contracts ]]; then
    echo "  [SKIP] API-CONTRACTS.md (--skip-contracts)"
  else
    echo "  [FAIL] API-CONTRACTS.md missing"
    ((FAIL++))
  fi
fi

# Check TEST-GOALS.md
if [ -f "${PHASE_DIR}/TEST-GOALS.md" ]; then
  GOALS=$(grep -c "^## Goal G-" "${PHASE_DIR}/TEST-GOALS.md" 2>/dev/null || echo 0)
  echo "  [PASS] TEST-GOALS.md with ${GOALS} goals"
  ((PASS++))
else
  if [[ "$FLAGS" =~ --skip-goals ]]; then
    echo "  [SKIP] TEST-GOALS.md (--skip-goals)"
  else
    echo "  [FAIL] TEST-GOALS.md missing"
    ((FAIL++))
  fi
fi

# Check PLAN.md attributed
if ls "${PHASE_DIR}"/PLAN*.md 2>/dev/null; then
  ATTRS=$(grep -c "<file-path>" "${PHASE_DIR}"/PLAN*.md 2>/dev/null || echo 0)
  TASKS=$(grep -c "^##\{1,2\} Task" "${PHASE_DIR}"/PLAN*.md 2>/dev/null || echo 0)
  if [ "$ATTRS" -gt 0 ]; then
    echo "  [PASS] PLAN.md attributed (${ATTRS}/${TASKS} tasks have file-path)"
    ((PASS++))
  else
    echo "  [WARN] PLAN.md exists but no VG attributes"
    ((WARN++))
  fi
fi

# Check backups exist
BACKUPS=$(ls "${PHASE_DIR}/.gsd-backup/" 2>/dev/null | wc -l)
echo "  [INFO] ${BACKUPS} backup file(s) in .gsd-backup/"

# === VG semantic gates (v1.14.4+ — real downstream verify) ===
echo ""
echo "=== VG Semantic Gates (mirror downstream blueprint/build/test requirements) ==="

# Gate A: CONTEXT — 3 sub-sections per decision
if [ -f "${PHASE_DIR}/CONTEXT.md" ]; then
  D=$(grep -cE "^#+\s*D-[0-9]+" "${PHASE_DIR}/CONTEXT.md")
  E=$(grep -c "^\*\*Endpoints:\*\*" "${PHASE_DIR}/CONTEXT.md")
  U=$(grep -c "^\*\*UI Components:\*\*" "${PHASE_DIR}/CONTEXT.md")
  T=$(grep -c "^\*\*Test Scenarios:\*\*" "${PHASE_DIR}/CONTEXT.md")
  if [ "$D" = "$E" ] && [ "$D" = "$U" ] && [ "$D" = "$T" ] && [ "$D" -gt 0 ]; then
    echo "  [PASS] CONTEXT semantic: ${D} decisions × 3 sub-sections all match"
    ((PASS++))
  else
    echo "  [FAIL] CONTEXT semantic: D=${D} E=${E} U=${U} T=${T} (must all match)"
    ((FAIL++))
  fi
fi

# Gate B: TEST-GOALS — Persistence check coverage cho mutation goals
if [ -f "${PHASE_DIR}/TEST-GOALS.md" ]; then
  PERSIST_GAP=$(${PYTHON_BIN:-python3} - "${PHASE_DIR}/TEST-GOALS.md" <<'PY'
import re, sys
text = open(sys.argv[1], encoding='utf-8').read()
gp = re.compile(r'(?ms)^#{2,4}\s+(?:Goal\s+)?(G-\d+).+?(?=^#{2,4}\s+(?:Goal\s+)?G-\d+|\Z)')
gap = 0
for m in gp.finditer(text):
    body = m.group(0)
    mut = re.search(r'\*\*Mutation evidence:\*\*\s*(.+?)(?=\n\s*\n|\n\*\*|\Z)', body, re.S)
    if mut:
        v = mut.group(1).strip()
        has_mut = bool(v) and not re.match(r'^(N/A|none|—|_|read-?only|—\s*$|-\s*$)\s*$', v, re.I)
        has_persist = bool(re.search(r'\*\*Persistence check:\*\*', body))
        if has_mut and not has_persist:
            gap += 1
print(gap)
PY
)
  if [ "${PERSIST_GAP:-0}" -eq 0 ]; then
    echo "  [PASS] TEST-GOALS Rule 3b: all mutation goals có Persistence check"
    ((PASS++))
  else
    echo "  [FAIL] TEST-GOALS Rule 3b: ${PERSIST_GAP} mutation goals missing Persistence check"
    ((FAIL++))
  fi

  # Gate C: Surface classification coverage
  TOTAL_G=$(grep -cE "^#{2,4}\s+(Goal\s+)?G-[0-9]+" "${PHASE_DIR}/TEST-GOALS.md")
  WITH_SURFACE=$(grep -cE "^\*\*Surface:\*\*\s+(ui|api|data|integration|time-driven|custom)" "${PHASE_DIR}/TEST-GOALS.md")
  if [ "$WITH_SURFACE" -eq "$TOTAL_G" ] && [ "$TOTAL_G" -gt 0 ]; then
    echo "  [PASS] Surface classification: ${WITH_SURFACE}/${TOTAL_G} goals classified"
    ((PASS++))
  else
    echo "  [FAIL] Surface classification: ${WITH_SURFACE}/${TOTAL_G} goals classified"
    ((FAIL++))
  fi
fi

# Gate D: PLAN ↔ TEST-GOALS bidirectional linkage
if ls "${PHASE_DIR}"/PLAN*.md >/dev/null 2>&1 && [ -f "${PHASE_DIR}/TEST-GOALS.md" ]; then
  TASKS=$(grep -cE "^#{2,3}\s+Task\s+[0-9]+" "${PHASE_DIR}"/PLAN*.md | awk -F: '{s+=$2} END{print s}')
  WITH_GOALS=$(grep -c "<goals-covered>" "${PHASE_DIR}"/PLAN*.md | awk -F: '{s+=$2} END{print s}')
  if [ "${WITH_GOALS:-0}" -ge "${TASKS:-1}" ]; then
    echo "  [PASS] Plan-Goal linkage: ${WITH_GOALS}/${TASKS} tasks có <goals-covered>"
    ((PASS++))
  else
    echo "  [WARN] Plan-Goal linkage incomplete: ${WITH_GOALS}/${TASKS}"
    ((WARN++))
  fi
fi

echo ""
echo "Result: ${PASS} pass, ${WARN} warn, ${FAIL} fail"

# Final gate — fail nếu bất kỳ semantic gate FAIL
if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "⛔ VG semantic gates failed (${FAIL} fails). Phase NOT ready for /vg:blueprint."
  echo "   Re-run: /vg:migrate ${PHASE_NUMBER} --force"
  echo "   Or fix manually: edit CONTEXT.md/TEST-GOALS.md, then re-run validation"
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "migrate_semantic_fail" "${PHASE_NUMBER}" "migrate.9" "validation" "FAIL" \
      "{\"fails\":${FAIL},\"warns\":${WARN}}"
  fi
  if [[ ! "$ARGUMENTS" =~ --allow-semantic-gaps ]]; then
    exit 1
  fi
  if type -t log_override_debt >/dev/null 2>&1; then
    log_override_debt "migrate-semantic-gaps" "${PHASE_NUMBER}" "${FAIL} VG semantic gates failed" "$PHASE_DIR"
  fi
  echo "⚠ --allow-semantic-gaps set — proceeding, logged to debt"
fi

if type -t emit_telemetry_v2 >/dev/null 2>&1; then
  emit_telemetry_v2 "migrate_semantic_pass" "${PHASE_NUMBER}" "migrate.9" "validation" "PASS" \
    "{\"pass\":${PASS},\"warn\":${WARN}}"
fi
```

**Display migration report:**

```
━━━ Migration Complete — Phase {N} ━━━

Converted:
  CONTEXT.md:        gsd-flat → vg-enriched ({N} decisions enriched)
  PLAN.md:           gsd-plain → vg-attributed ({N}/{M} tasks attributed)
  API-CONTRACTS.md:  generated ({N} endpoints, {M} code blocks)
  TEST-GOALS.md:     generated ({N} goals: {c} critical, {i} important, {n} nice-to-have)

Backups:             .gsd-backup/ ({N} files)
Pipeline state:      migrated → ready for /vg:review

Next steps:
  1. Review generated artifacts: API-CONTRACTS.md and TEST-GOALS.md
  2. Run: /vg:review {phase}
  3. Or: /vg:next (auto-detects review as next step)
```

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "migrate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/migrate.done"`
</step>

</process>

<success_criteria>
- GSD originals backed up to .gsd-backup/
- CONTEXT.md enriched with Endpoints/UI/Test sub-sections per decision
- API-CONTRACTS.md generated from existing code (if not --skip-contracts)
- TEST-GOALS.md generated with goals + infra_deps field (if not --skip-goals)
- PLAN.md tasks attributed with VG task attributes
- PIPELINE-STATE.json written with migrated status
- Validation passes with 0 FAIL items
- Phase routable by /vg:next (shows as review-ready)
</success_criteria>
