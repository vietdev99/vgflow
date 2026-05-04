# blueprint lens-walk (STEP 4 sub-step — `2b5e_a_lens_walk`)

Per-goal × per-applicable-lens iteration that auto-derives bug-class–specific
variant seeds from the canonical lens-prompts library
(`commands/vg/_shared/lens-prompts/lens-*.md`).

Runs **after `2b5_test_goals`** (need TEST-GOALS first) and **before
`2b5e_edge_cases`** (edge-cases consumes lens-walk seeds + profile template).

Output: `${PHASE_DIR}/LENS-WALK/G-NN.md` per-goal — a *seed* artifact, NOT
authoritative. `2b5e_edge_cases` ingests it and produces final EDGE-CASES with
both profile-driven categories (boundary, auth, concurrency, …) AND lens-driven
categories (idor, mass-assignment, business-logic, …) merged into one variant
table per goal.

---

## Why this step exists (motivation)

**Before lens-walk:** the AI saw only the profile template (10 categories for
web-fullstack: boundary, auth, concurrency, …) and wrote variants from
generic prompts. Bug-class–specific surfaces (IDOR, BFLA, mass-assignment, JWT
forgery, CSRF, SSRF, open-redirect) appeared inconsistently — depended on
which lens the AI happened to recall.

**After lens-walk:** every applicable lens contributes 2-4 deterministic
variant seeds per goal, derived from the lens's `Probe ideas` section. Result:
EDGE-CASES coverage tracks the canonical lens library instead of LLM
recall variance.

**Cost:** +1 subagent spawn per blueprint run (~30s wall-clock, ~5K tokens).
Skipped automatically when no_crud_reason set OR `--skip-lens-walk` /
`--skip-edge-cases` flags supplied.

---

## <HARD-GATE>

You MUST run this step UNLESS:
- Phase has `resources: []` in CRUD-SURFACES.md (no CRUD/resource behavior →
  lens-walk not applicable; emit `blueprint.lens_walk_skipped`)
- User passed `--skip-lens-walk` flag (paired with `--override-reason=<text>`,
  logs override-debt entry)
- User passed `--skip-edge-cases` (lens-walk is upstream of edge-cases — when
  edge-cases is skipped, lens-walk has no consumer)

Otherwise: missing LENS-WALK = edge-cases falls back to profile-template-only
coverage (works, just narrower). Severity is `warn` not `block`.

</HARD-GATE>

---

## STEP 4.5a (2b5e_a_lens_walk) — orchestration

> Numbered 4.5a to sit before STEP 4.5 (edge_cases) and after STEP 4.4 (codex
> lane). Lens-walk seeds → Edge-cases consumes → both authored by
> vg-blueprint-contracts subagent in distinct invocations.

```bash
vg-orchestrator step-active 2b5e_a_lens_walk

# ─── Skip conditions ───────────────────────────────────────────────────────
SKIP_REASON=""
if [[ "$ARGUMENTS" =~ --skip-lens-walk ]] || [[ "$ARGUMENTS" =~ --skip-edge-cases ]]; then
  if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
    echo "⛔ --skip-lens-walk / --skip-edge-cases requires --override-reason=<text>"
    exit 1
  fi
  SKIP_REASON="user override flag"
elif [ -f "${PHASE_DIR}/CRUD-SURFACES.md" ]; then
  if "${PYTHON_BIN:-python3}" -c "
import json, re, sys
src = open('${PHASE_DIR}/CRUD-SURFACES.md').read()
m = re.search(r'\`\`\`json\n(.*?)\n\`\`\`', src, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    if data.get('no_crud_reason') or not data.get('resources'):
        sys.exit(0)
sys.exit(1)
"; then
    SKIP_REASON="phase has no CRUD resources"
  fi
fi

if [ -n "$SKIP_REASON" ]; then
  vg-orchestrator emit-event "blueprint.lens_walk_skipped" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"${SKIP_REASON}\"}"
  echo "▸ Lens-walk skipped: $SKIP_REASON"
  vg-orchestrator mark-step blueprint 2b5e_a_lens_walk
  exit 0
fi

# ─── Determine applicable lenses ───────────────────────────────────────────
PROFILE=$(vg_config_get profile web-fullstack)

# Profile → applicable bug_classes mapping (heuristic, AI may extend per-goal)
case "$PROFILE" in
  web-fullstack)
    BUG_CLASSES="authz injection auth bizlogic state-coherence ui-mechanic server-side redirect"
    ;;
  web-frontend-only)
    BUG_CLASSES="authz auth bizlogic state-coherence ui-mechanic redirect"
    ;;
  web-backend-only)
    BUG_CLASSES="authz injection auth bizlogic state-coherence server-side redirect"
    ;;
  mobile-*|cli-tool|library)
    BUG_CLASSES="auth bizlogic state-coherence"
    ;;
  *)
    BUG_CLASSES="authz injection auth bizlogic state-coherence ui-mechanic server-side redirect"
    ;;
esac

LENS_DIR=".claude/commands/vg/_shared/lens-prompts"

# Collect candidate lenses by bug_class match
CANDIDATE_LENSES=()
for lens_file in "$LENS_DIR"/lens-*.md; do
  bc=$(grep -E "^bug_class:" "$lens_file" | head -1 | awk '{print $2}')
  if echo "$BUG_CLASSES" | grep -qw "$bc"; then
    CANDIDATE_LENSES+=("$lens_file")
  fi
done

if [ "${#CANDIDATE_LENSES[@]}" -lt 1 ]; then
  echo "⚠ No applicable lenses found for profile=$PROFILE — skipping lens-walk"
  vg-orchestrator emit-event "blueprint.lens_walk_skipped" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"no applicable lenses for profile\"}"
  vg-orchestrator mark-step blueprint 2b5e_a_lens_walk
  exit 0
fi

echo "▸ Lens-walk: ${#CANDIDATE_LENSES[@]} candidate lenses for profile=$PROFILE"

# ─── Spawn subagent ────────────────────────────────────────────────────────
# vg-blueprint-contracts handles lens-walk via Part 5 prompt.
# Input: TEST-GOALS/G-*.md + CRUD-SURFACES.md + candidate lens-*.md (READ-ONLY)
# Output: LENS-WALK/G-NN.md per-goal + LENS-WALK/index.md + telemetry payload

bash scripts/vg-narrate-spawn.sh vg-blueprint-contracts spawning \
  "lens-walk for ${PHASE_NUMBER} (${PROFILE}, ${#CANDIDATE_LENSES[@]} lenses)"

# Agent(subagent_type="vg-blueprint-contracts", prompt=<from contracts-delegation.md Part 5>):
#   reads:
#     - TEST-GOALS/G-*.md (each goal)
#     - CRUD-SURFACES.md (resource/action/element_class hints)
#     - lens-*.md (applicable lenses only — pass paths via vg-load --list)
#   writes:
#     - LENS-WALK/G-NN.md (per-goal)
#     - LENS-WALK/index.md (TOC: per-goal × applicable-lens matrix)
#   returns: {
#     lens_walk_path, lens_walk_sub_files,
#     applicable_lens_per_goal: {G-04: [lens-idor, lens-mass-assignment], ...},
#     total_seed_variants, goals_with_lenses_count
#   }

bash scripts/vg-narrate-spawn.sh vg-blueprint-contracts returned \
  "${TOTAL_SEED_VARIANTS:-?} seed variants across ${GOALS_WITH_LENSES_COUNT:-?} goals"

# ─── Validate output ───────────────────────────────────────────────────────
[ -f "${PHASE_DIR}/LENS-WALK/index.md" ] || {
  echo "⛔ LENS-WALK/index.md missing after subagent return"
  exit 1
}

LENS_WALK_GOALS=$(ls "${PHASE_DIR}/LENS-WALK/G-"*.md 2>/dev/null | wc -l | tr -d ' ')
if [ "$LENS_WALK_GOALS" -lt 1 ]; then
  echo "⛔ LENS-WALK/G-*.md per-goal split missing (${LENS_WALK_GOALS} files)"
  exit 1
fi

# ─── Emit telemetry ────────────────────────────────────────────────────────
TOTAL_SEEDS=$(grep -hE "^\| L-" "${PHASE_DIR}/LENS-WALK/G-"*.md 2>/dev/null | wc -l | tr -d ' ')
vg-orchestrator emit-event "blueprint.lens_walk_generated" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"goals_with_lenses\":${LENS_WALK_GOALS},\"total_seeds\":${TOTAL_SEEDS},\"profile\":\"${PROFILE}\"}"

echo "▸ Lens-walk: ${LENS_WALK_GOALS} goals × applicable lenses → ${TOTAL_SEEDS} seed variants"

vg-orchestrator mark-step blueprint 2b5e_a_lens_walk
```

---

## Output schema

### Layer 1 — `${PHASE_DIR}/LENS-WALK/G-NN.md` (per-goal, primary)

```markdown
# Lens Walk — G-04: User creates site with custom domain

**Goal source**: `${PHASE_DIR}/TEST-GOALS/G-04.md`
**Resource**: sites (POST /api/sites)
**Profile**: web-fullstack
**Applicable lenses**: lens-idor, lens-mass-assignment, lens-business-logic,
  lens-input-injection, lens-tenant-boundary

## Seed variants (per applicable lens × probe-idea)

| seed_id | lens | probe-idea source | proposed variant_id (for edge-cases step) | priority hint |
|---|---|---|---|---|
| L-04-IDOR-1 | lens-idor | "Replay POST with peer tenant token" | G-04-a3 | critical |
| L-04-IDOR-2 | lens-idor | "Sequential ID enumeration on /api/sites/{id}" | G-04-a4 | high |
| L-04-MA-1 | lens-mass-assignment | "POST body contains owner_id, tenant_id, is_admin extras" | G-04-d1 | critical |
| L-04-MA-2 | lens-mass-assignment | "PATCH body extends to flags not in OpenAPI" | G-04-d2 | high |
| L-04-BL-1 | lens-business-logic | "Domain already taken by peer-tenant — should 409 not silently rebind" | G-04-e1 | high |
| L-04-II-1 | lens-input-injection | "domain=\"; DROP TABLE sites;--\" in body" | G-04-b4 | medium |
| L-04-TB-1 | lens-tenant-boundary | "X-Tenant header tampered to peer tenant id" | G-04-a5 | critical |

## Lens applicability rationale (per lens)

- **lens-idor**: G-04 mutates a tenant-scoped resource — applicable.
- **lens-mass-assignment**: POST body accepts JSON object — applicable.
- **lens-business-logic**: domain has uniqueness constraint — applicable.
- **lens-input-injection**: free-text input field — applicable.
- **lens-tenant-boundary**: resource is tenant-scoped — applicable.

## Lenses considered but skipped

- **lens-csrf**: API-only endpoint with `Authorization: Bearer` (no cookie) — NOT applicable.
- **lens-file-upload**: no multipart/form-data — NOT applicable.
- **lens-ssrf**: domain field is opaque label, server does not fetch it — NOT applicable.

## How edge-cases step consumes this

`2b5e_edge_cases` reads this file and merges seeds into the final EDGE-CASES
table. Each `seed_id` becomes 1 row in the appropriate category section
(auth → category `a`, mass-assignment → category `d`, etc.). The proposed
`variant_id` column is a hint; edge-cases step renumbers if conflicts.
```

### Layer 2 — `${PHASE_DIR}/LENS-WALK/index.md` (TOC matrix)

```markdown
# Lens Walk — Phase ${PHASE_NUMBER} (Index)

**Profile**: web-fullstack
**Total candidate lenses**: 19
**Applicable lenses (matrix below)**: 12

## Matrix: goals × applicable lenses

| Goal | idor | bfla | tenant | mass-asgn | input-inj | bizlogic | csrf | jwt | … |
|---|---|---|---|---|---|---|---|---|---|
| G-04 | ✓ | – | ✓ | ✓ | ✓ | ✓ | – | – | … |
| G-12 | ✓ | ✓ | ✓ | – | – | – | – | – | … |
| G-99 | – | – | – | – | – | – | – | – | … (skipped: read-only health) |

**Total seed variants**: 47 across 8 goals
```

### (No Layer 3 flat) — lens-walk is intermediate; edge-cases is final.

---

## Lens applicability rules (heuristic, AI may extend)

The subagent decides per-goal which lenses apply, using:

| Goal property (read from TEST-GOALS/G-NN.md + CRUD-SURFACES) | Triggers lens |
|---|---|
| `resource.action ∈ {POST, PATCH, PUT}` mutates server state | idor, mass-assignment, bizlogic, dup-submit |
| `resource.scope == tenant` | tenant-boundary |
| `resource.action == GET` returns object by id | idor, info-disclosure, bfla |
| Body contains free-text fields | input-injection, path-traversal |
| Body contains URL field | open-redirect, ssrf |
| Body contains file/multipart | file-upload |
| Modal / wizard / multi-step in UI spec | modal-state, form-lifecycle |
| Table / list / paginated UI | table-interaction |
| Authentication endpoint | auth-jwt, csrf |

Profile filter still applies on top — `web-backend-only` skips ui-mechanic
lenses (modal-state, form-lifecycle, table-interaction) regardless.

---

## Variant-id naming (for downstream edge-cases consumption)

`<goal_id>-<category_letter><N>` where category_letter follows
edge-cases template categories — but with these lens→category mappings to
avoid collision:

- lens-idor / lens-bfla / lens-tenant-boundary → category `a` (auth boundaries)
- lens-mass-assignment → category `d` (data validity / mass-assignment)
- lens-business-logic / lens-business-coherence → category `e` (error_propagation / state)
- lens-input-injection / lens-path-traversal → category `b` (boundary inputs)
- lens-duplicate-submit → category `c` (concurrency / race)
- lens-modal-state / lens-form-lifecycle → category `s` (state) — frontend profiles
- lens-table-interaction → category `t` (table) — frontend profiles
- lens-csrf / lens-auth-jwt → category `j` (JWT/CSRF auth-token attacks)
- lens-ssrf / lens-open-redirect / lens-info-disclosure → category `r` (server-side)
- lens-file-upload → category `u` (upload)

Edge-cases step is authoritative on final numbering; lens-walk hints are
preserved as `// vg-lens-source: lens-idor` comments in EDGE-CASES rows.

---

## Downstream consumers

1. **`2b5e_edge_cases`** (next step — primary consumer):
   - Reads `LENS-WALK/G-NN.md` for each goal
   - Merges seed variants into EDGE-CASES/G-NN.md table
   - Annotates each merged row with lens-source comment
   - Final variant_id assignment authoritative here

2. **`/vg:test`** codegen indirect (via EDGE-CASES):
   - Tests gain lens-derived coverage automatically through edge-cases pipeline

3. **`/vg:roam`** lens probes (cross-reference):
   - When roam runs lens probes, it cross-references LENS-WALK to know which
     goals expected coverage from each lens — gap detection

---

## Performance budget

- Subagent wall-clock: ~30-60s (reads ~12 lens prompts + N goals + writes N+1 files)
- Token budget: ~5-10K input (lens prompts loaded only by `--list` paths,
  not full content; subagent reads selectively per goal)
- File count: 1 + GOAL_COUNT files written

---

## Backward compat (legacy phases pre-v2.50)

- Phase blueprint without LENS-WALK/ → `2b5e_edge_cases` falls back to
  profile-template-only (existing behavior). Severity: warn.
- Validator (`verify-edge-cases-contract.py`) does NOT check for LENS-WALK
  presence — lens-walk is advisory upstream, edge-cases is the contract.
