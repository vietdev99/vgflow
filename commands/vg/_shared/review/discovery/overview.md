# review browser discovery — overview (STEP 3 — HEAVY, subagent)

Single step `phase2_browser_discovery` covers Phase 2a deploy +
infra-auto-start + 2b-1 navigator + 2b-2 parallel scanners + 2b-3 goal
sequence recording. Source step body in review.md.r3-backup spans 947
lines (lines 2906-3853) — too dense for inline orchestration without
skim. Plan §10 splits the load:

- **overview.md** (this file) — pre-spawn narration, run `vg-review-browser-discoverer`, post-spawn validation, marker write.
- **delegation.md** — full input/output contract (consumed by subagent at spawn time).

The Haiku worker scanners that the subagent ultimately spawns continue to
follow `.claude/skills/vg-haiku-scanner/SKILL.md` (already split, fixed
protocol, zero discretion).

<HARD-GATE>
DO NOT crawl inline. You MUST spawn the `vg-review-browser-discoverer`
subagent for this step. The phase has 947 lines of discovery logic + 5
narration helpers + 7 conditional branches (--skip-discovery /
--evaluate-only / --retry-failed / --re-scan-goals / --dogfood / -- mobile-
profile / SPAWN_MODE) — inline execution will skim and emit a falsely
clean RUNTIME-MAP.

The Tool name for spawning is `Agent` (not `Task`) per plan §C — Codex
correction. Agent prompt MUST embed the JSON capsule from `delegation.md`
verbatim.

Pre-spawn narration is REQUIRED (UX req 2). Post-spawn validation is
REQUIRED (subagent must return RUNTIME-MAP.json + scan-*.json or this
ref's marker MUST NOT be written).

vg-load convention: where the subagent loads PLAN / API-CONTRACTS / TEST-
GOALS into AI context for view briefing, prefer `vg-load --phase
${PHASE_NUMBER} --artifact <plan|contracts|goals> --task NN/--endpoint
slug/--goal G-NN` over flat reads of the whole artifact. The capsule in
delegation.md tells the subagent which slug/IDs to load.
</HARD-GATE>

---

## STEP 3.1 — phase2_browser_discovery (spawn site)

<step name="phase2_browser_discovery" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2: BROWSER DISCOVERY (MCP Playwright — organic, subagent-delegated)

**🎬 Live narration protocol (tightened 2026-04-17 — user theo dõi flow):**

Orchestrator PHẢI in dòng tiếng người BEFORE spawn + AFTER subagent
returns. The subagent itself emits per-view narration via `description`
updates surfaced in the main terminal.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2_browser_discovery >/dev/null 2>&1 || true
```

### Branching short-circuits (evaluated BEFORE spawn)

**If --skip-discovery, skip to Phase 4** (RUNTIME-MAP must already exist).

**If --evaluate-only, skip Phase 1 + 2a-2b-1, run only 2b-3 (collect + merge):**
- Validate: `${PHASE_DIR}/nav-discovery.json` AND at least 1 `scan-*.json` exist.
- Missing → BLOCK: "Run discovery first: `$vg-review {phase} --discovery-only` in Codex/Gemini."
- Spawn subagent with `mode=evaluate-only` capsule field.

**If --retry-failed:**
- Validate: `${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md` AND `${PHASE_DIR}/RUNTIME-MAP.json` exist.
- Missing → BLOCK: "Run `/vg:review {phase}` first to generate initial artifacts."
- Parse GOAL-COVERAGE-MATRIX.md → collect all goals where status NOT IN (READY, INFRA_PENDING, DEFERRED, MANUAL).
  This includes: BLOCKED, UNREACHABLE, FAILED, PARTIAL, NOT_SCANNED, **and SUSPECTED** (v2.46-wave3.2 — matrix=READY but no submit/2xx evidence; flagged by `verify-matrix-staleness.py` at preflight `0_parse_and_validate` and folded in here).
- If none found → "All goals already READY. Nothing to retry." → skip to Phase 4.
- Parse RUNTIME-MAP.json → for each failed goal_id: `start_view = goal_sequences[goal_id].start_view`.
- `RETRY_VIEWS[]` = unique(all start_views), with roles from `RUNTIME-MAP views[start_view].role`.
- Spawn subagent with `mode=retry-failed` + `retry_views=[...]` capsule fields.

**If --re-scan-goals=G-XX,G-YY,G-ZZ:**
- Validate: `${PHASE_DIR}/RUNTIME-MAP.json` exists (matrix not required — bypasses status filter).
- Missing → BLOCK: "Run `/vg:review {phase}` first to generate RUNTIME-MAP.json."
- Each goal ID was validated at preflight `0_parse_and_validate` (unknown IDs → exit 1 there).
- Parse RUNTIME-MAP.json → for each goal_id in $RE_SCAN_GOALS: `start_view = goal_sequences[goal_id].start_view`.
- `RETRY_VIEWS[]` = unique(all start_views).
- Marker: write `${PHASE_DIR}/.re-scan-goals.txt` with the list (consumed by 2b-3 to scope sequence recording to just these goals).
- Spawn subagent with `mode=re-scan-goals` + explicit goal list capsule field.

**If --dogfood:**
- Validate: `${PHASE_DIR}/TEST-GOALS.md` AND `${PHASE_DIR}/RUNTIME-MAP.json` exist.
- Parse TEST-GOALS.md → all goals with non-empty `**Mutation evidence:**` field (use `verify-matrix-staleness.py parse_goals` parser, NOT inline regex).
- `RE_SCAN_GOALS` := comma-join(those goal_ids), then proceed exactly as `--re-scan-goals` branch above.
- Spawn subagent with `mode=dogfood` capsule field.

### Pre-spawn narration

```bash
bash scripts/vg-narrate-spawn.sh vg-review-browser-discoverer spawning \
  "phase 2 browser discovery (mode=${BROWSER_MODE:-full}, retry_views=${#RETRY_VIEWS[@]})"
```

### Spawn

Read `delegation.md` for the full input contract, then build the capsule
JSON and call `Agent`:

```
Agent(
  subagent_type="vg-review-browser-discoverer",
  prompt="""
You are the vg-review-browser-discoverer subagent. Read the input
capsule below, then follow `.claude/agents/vg-review-browser-discoverer/SKILL.md`
verbatim. Return the output schema documented there.

INPUT CAPSULE:
{
  "phase_number": "${PHASE_NUMBER}",
  "phase_dir":    "${PHASE_DIR}",
  "phase_profile":"${PHASE_PROFILE}",
  "scanner":      "${VG_SCANNER:-haiku-only}",
  "method":       "${VG_METHOD:-spawn}",
  "env":          "${VG_ENV}",
  "mode":         "${BROWSER_MODE:-full}",
  "spawn_mode":   "${SPAWN_MODE:-parallel}",
  "max_haiku":    5,
  "full_scan":    ${FULL_SCAN:-false},
  "with_probes":  ${WITH_PROBES:-false},
  "retry_views":  $(printf '%s\n' "${RETRY_VIEWS[@]}" | jq -R . | jq -s .),
  "re_scan_goals":"${RE_SCAN_GOALS:-}",
  "scope_paths":  "from REVIEW-LENS-PLAN.json",
  "role_matrix":  "from .claude/vg.config.md credentials_map",
  "vg_load_hint": "use vg-load --phase ${PHASE_NUMBER} --artifact goals --goal G-NN for per-goal briefing"
}

PROGRESS PROTOCOL: update `description` per view processed:
- `[{idx}/{total}] {role}@{view} — verify {N} goals: {G-list}` lúc spawn
- `[{idx}/{total}] {role}@{view} — G-03/5 filling form...` trong lúc chạy
- `[{idx}/{total}] {role}@{view} — ✓ 4/5 goals, 1 regression` khi xong

OUTPUT: write artifacts to ${PHASE_DIR}/. Return JSON per delegation.md
output schema (views_discovered, scan_artifacts, errors, playwright_slots_used).
"""
)
```

### Post-spawn validation

```bash
# Validate subagent wrote required artifacts
REQUIRED_OUTPUTS=("RUNTIME-MAP.json" "nav-discovery.json")
for f in "${REQUIRED_OUTPUTS[@]}"; do
  if [ ! -f "${PHASE_DIR}/${f}" ]; then
    echo "⛔ vg-review-browser-discoverer did not produce ${f} — cannot proceed" >&2
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "review.browser_discovery_incomplete" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"missing\":\"${f}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
done

# At least 1 scan-*.json must exist (per-view atomic artifacts)
SCAN_COUNT=$(ls "${PHASE_DIR}"/scan-*.json 2>/dev/null | wc -l | tr -d ' ')
if [ "${SCAN_COUNT:-0}" -eq 0 ]; then
  echo "⛔ vg-review-browser-discoverer produced no scan-*.json — view scanners returned no evidence" >&2
  exit 1
fi
```

### Post-spawn narration

```bash
VIEWS_COUNT=$("${PYTHON_BIN:-python3}" -c "
import json
try:
    rt = json.load(open('${PHASE_DIR}/RUNTIME-MAP.json'))
    print(len(rt.get('views', {})))
except: print(0)
")
bash scripts/vg-narrate-spawn.sh vg-review-browser-discoverer returned \
  "${VIEWS_COUNT} views discovered, ${SCAN_COUNT} scan artifacts"
```

### Step-end markers

```bash
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_browser_discovery" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_browser_discovery.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2_browser_discovery 2>/dev/null || true
```

**Limits (per Haiku worker, enforced by subagent):**
- Max 200 actions per view (prevents runaway on huge pages)
- Max 10 min wall time per agent
- Stagnation: same state 3x = stuck, move on
- **Concurrency (v1.9.4 R3.3 SPAWN_MODE aware):**
  - `parallel` mode: up to 5 Haiku agents concurrent (Playwright slot cap)
  - `sequential` mode: exactly 1 Haiku agent at a time (mobile safety)
  - `none` mode: no Haiku agents spawned (cli-tool/library)

These limits are encoded in the subagent SKILL.md, not in this overview.
The orchestrator's job at this layer is: spawn → wait → validate.
</step>
