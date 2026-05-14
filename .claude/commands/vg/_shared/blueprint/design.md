# blueprint design (STEP 2)

UI/design steps: 2_fidelity_profile_lock, 2b6c_view_decomposition,
2b6_ui_spec, 2b6b_ui_map. Profile-aware (web-fullstack, web-frontend-only).

<HARD-GATE>
For backend-only / cli-tool / library profiles, this STEP is SKIPPED via
profile branch (filter-steps.py drops the markers). For web profiles, you
MUST execute all 4 sub-steps in order.

Each step wraps work with `vg-orchestrator step-active <step>` before and
`mark-step` after — required for hook gate enforcement.
</HARD-GATE>

---

## STEP 2.1 — design fidelity profile lock (2_fidelity_profile_lock)

**Mục tiêu:** Lock the per-phase visual-fidelity threshold profile BEFORE
planner writes PLAN. The profile (prototype / default / production) sets
the SSIM/structural-diff threshold the post-wave drift gate enforces in
`/vg:review` (D-12b/c/e). Locking at blueprint time prevents executor or
reviewer from quietly relaxing the bar mid-phase.

Profile defaults:
- `prototype`  → 0.70 (early exploration, large layout swings tolerated)
- `default`    → 0.85 (most product work — recommended default)
- `production` → 0.95 (visual-spec-grade, near pixel-perfect)

Resolution order (highest precedence first):
1. `--fidelity-profile <name>` CLI arg
2. Phase frontmatter `design_fidelity.profile: <name>` in CONTEXT.md
3. `vg.config.md` → `design_fidelity.default_profile`
4. Hardcoded fallback: `default` (0.85)

```bash
vg-orchestrator step-active 2_fidelity_profile_lock

# Skip if no design assets in scope (pure backend phase)
if [ ! -f "${PHASE_DIR}/design-normalized/_INDEX.md" ] \
   && ! grep -lE "(\.tsx|\.jsx|\.vue|\.svelte)" "${PHASE_DIR}"/PLAN*.md 2>/dev/null | head -1 >/dev/null; then
  echo "ℹ No design or FE work in phase — skip fidelity profile lock"
else
  PROFILE_LOCK_FILE="${PHASE_DIR}/.fidelity-profile.lock"

  if [ -f "$PROFILE_LOCK_FILE" ]; then
    LOCKED=$(cat "$PROFILE_LOCK_FILE")
    echo "ℹ Fidelity profile already locked: ${LOCKED} (delete .fidelity-profile.lock to relock)"
  else
    # Resolve via threshold-resolver helper.
    # Stdout = numeric threshold (e.g., "0.85"); stderr (with --verbose) =
    # `source=<src> profile=<name> threshold=<n>`.
    RESOLVED_ERR_FILE="${VG_TMP:-${PHASE_DIR}/.vg-tmp}/threshold-resolver.err"
    mkdir -p "$(dirname "$RESOLVED_ERR_FILE")" 2>/dev/null
    THRESHOLD=$(${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/lib/threshold-resolver.py" \
        --phase "${PHASE_NUMBER}" --verbose 2> "$RESOLVED_ERR_FILE")
    PROFILE=$(grep -oE 'profile=[a-z-]+' "$RESOLVED_ERR_FILE" | head -1 | cut -d= -f2)
    SOURCE=$(grep -oE 'source=[a-z._-]+' "$RESOLVED_ERR_FILE"  | head -1 | cut -d= -f2)
    PROFILE="${PROFILE:-default}"
    THRESHOLD="${THRESHOLD:-0.85}"

    echo "$PROFILE" > "$PROFILE_LOCK_FILE"
    echo "✓ Fidelity profile locked: ${PROFILE} (threshold=${THRESHOLD}, source=${SOURCE:-fallback})"
    echo "  → ${PROFILE_LOCK_FILE}"
    echo "  /vg:review post-wave drift gate (D-12b/c/e) will use threshold=${THRESHOLD}"
  fi

  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2_fidelity_profile_lock" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2_fidelity_profile_lock.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2_fidelity_profile_lock 2>/dev/null || true
fi
```

**Override path** (DEBT — recorded in override-debt register):
- `--fidelity-profile prototype` on a production phase is allowed but logged
  as `kind=fidelity-profile-relaxed` so reviewers see it during /vg:accept.

---

## STEP 2.2 — view decomposition (2b6c_view_decomposition)

**Purpose:** Force a vision-capable agent to Read each design PNG and emit
the canonical component list per slug. Output `VIEW-COMPONENTS.md` becomes
authoritative input for step 2b6 UI-SPEC, the L5 design-fidelity guard, and
fine-grained planner pass.

Closes the upstream gap where blueprint previously had only DOM tree (HTML
asset) or box-list (PNG/Pencil/Penboard) — never component-level decomposition
derived from actually looking at the PNG.

**Skip conditions:**
- `config.design_assets.paths` empty (pure backend phase)
- No `<design-ref>` SLUG in PLAN (only `no-asset:` Form B refs)
- `${DESIGN_OUTPUT_DIR}/manifest.json` missing → skip with WARN
- `${PHASE_DIR}/VIEW-COMPONENTS.md` newer than every referenced PNG (cache hit)
- Config `design_assets.view_decomposition.enabled: false` (default OFF)

**Per-slug agent flow:**

For every SLUG-form `<design-ref>` in PLAN.md tasks, wrap each spawn
with narration so the user sees subagent lifecycle in chat:

```bash
# Narrate spawn (renders as colored chip in Claude Code / Codex CLI).
bash scripts/vg-narrate-spawn.sh vg-blueprint-view-decomposer spawning "view decomposition for ${slug} (phase ${PHASE_NUMBER})"
```

```
Agent(subagent_type="general-purpose", model="${MODEL_VIEW_DECOMP:-claude-opus-4-7}"):
  prompt: |
    You are a design view decomposer. Use Read tool on PNG path FIRST —
    vision-capable models see the image directly. Do NOT invent components.
    Do NOT use generic names ("div", "Container", "Wrapper", "Section").

    PNG: ${DESIGN_OUTPUT_DIR}/screenshots/{slug}.default.png
    Structural ref (if available): ${DESIGN_OUTPUT_DIR}/refs/{slug}.structural.{html|json}

    Output STRICT single-line JSON, no prose, no code fences:

    {"slug":"{slug}","components":[
      {"name":"AppShell|Sidebar|TopBar|...","type":"layout|navigation|content|card|form|modal|table|...","parent":"<parent name or null>","position":"<x,y,w,h percentages>","child_count":<int>,"evidence":"<short phrase from PNG>"}
    ]}

    Rules:
    - Min 3 components per slug. If <3 → emit `{"components":[],"reason":"only N regions visible"}`.
    - Semantic names: Sidebar, TopBar, MainContent, AppShell, KPICard.
    - Position field is x,y,w,h as percent of viewport (0-100). "(root)" for outermost layout.
    - parent is null for root container.
    - evidence is 5-15 char description ("blue button top-right") — proves you saw pixels.

  output_file: ${PHASE_DIR}/.tmp/view-{slug}.json
```

```bash
# After Agent return: narrate result (or failure).
if [ -s "${PHASE_DIR}/.tmp/view-${slug}.json" ]; then
  bash scripts/vg-narrate-spawn.sh vg-blueprint-view-decomposer returned "view-${slug}.json written"
else
  bash scripts/vg-narrate-spawn.sh vg-blueprint-view-decomposer failed "no output for ${slug}"
fi
```

**Aggregation (orchestrator):**

```bash
vg-orchestrator step-active 2b6c_view_decomposition

mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
{
  echo "# View Components — Phase ${PHASE_NUMBER}"
  echo ""
  echo "Generated by /vg:blueprint step 2b6c."
  echo "Source: vision-Read of \${DESIGN_OUTPUT_DIR}/screenshots/{slug}.default.png"
  echo "Derived: $(date -u +%FT%TZ)"
  echo ""
  for view_file in "${PHASE_DIR}"/.tmp/view-*.json; do
    [ -f "$view_file" ] || continue
    slug=$(basename "$view_file" .json | sed 's/^view-//')
    echo "## ${slug}"
    echo ""
    echo "| Component | Type | Parent | Position (x,y,w,h%) | Children |"
    echo "|---|---|---|---|---|"
    "${PYTHON_BIN:-python3}" -c "
import json
data = json.load(open('${view_file}', encoding='utf-8'))
for c in (data.get('components') or []):
    name = c.get('name',''); typ = c.get('type','')
    parent = c.get('parent') or ''; pos = c.get('position','')
    children = c.get('child_count', 0)
    print(f'| {name} | {typ} | {parent} | {pos} | {children} |')
"
    echo ""
  done
} > "${PHASE_DIR}/VIEW-COMPONENTS.md"
```

**Gate (verify-view-decomposition.py):**

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-view-decomposition.py \
  --phase-dir "${PHASE_DIR}" \
  --output "${PHASE_DIR}/.tmp/view-decomposition.json"
RC=$?
if [ "$RC" != "0" ] && [[ ! "$ARGUMENTS" =~ --skip-view-decomposition ]]; then
  echo "⛔ View decomposition validation BLOCKED — see ${PHASE_DIR}/.tmp/view-decomposition.json"
  echo "   Override: --skip-view-decomposition (logs override-debt)"
  type -t emit_telemetry_v2 >/dev/null 2>&1 && \
    emit_telemetry_v2 "blueprint_view_decomposition" "${PHASE_NUMBER}" "blueprint.2b6c" \
      "view_decomposition" "BLOCK" "{}"
  exit 1
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b6c_view_decomposition" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b6c_view_decomposition.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6c_view_decomposition 2>/dev/null || true
```

**Cross-AI gap-hunt (different-model adversarial pass):**

After Layer 1 emits VIEW-COMPONENTS.md, run a second-pass adversarial scan
with a DIFFERENT model to catch components Layer 1 missed (background overlays,
sticky FABs, hidden tabs, footer dividers).

```bash
GAP_HUNT_CLI="$(vg_config_get crossai_clis.gap_hunt codex 2>/dev/null || echo codex)"
if [ "${CONFIG_CROSSAI_CLIS_COUNT:-0}" -ge 1 ] \
   && [ -f "${PHASE_DIR}/VIEW-COMPONENTS.md" ] \
   && [[ ! "$ARGUMENTS" =~ --skip-view-decomp-gap-hunt ]]; then
  for view_file in "${PHASE_DIR}"/.tmp/view-*.json; do
    [ -f "$view_file" ] || continue
    slug=$(basename "$view_file" .json | sed 's/^view-//')
    GAP_REPORT="${PHASE_DIR}/.tmp/view-${slug}.gaps.json"

    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/crossai-invoke.sh" 2>/dev/null || true
    if type -t crossai_run_query >/dev/null 2>&1; then
      crossai_run_query "${GAP_HUNT_CLI}" \
        "Read PNG at ${DESIGN_OUTPUT_DIR}/screenshots/${slug}.default.png. Layer 1 listed: $(cat "${view_file}"). Find components Layer 1 MISSED (overlays, FABs, tabs, dividers). Output JSON: {\"missed\":[{\"name\":\"...\",\"position\":\"...\",\"reason\":\"...\"}],\"misnamed\":[{\"old\":\"...\",\"new\":\"...\",\"reason\":\"...\"}]}" \
        > "${GAP_REPORT}" 2>/dev/null || true
    fi

    if [ -f "${GAP_REPORT}" ]; then
      MISSED_COUNT=$("${PYTHON_BIN:-python3}" -c "
import json
try:
    d = json.load(open('${GAP_REPORT}', encoding='utf-8'))
    print(len(d.get('missed') or []))
except Exception:
    print(0)
" 2>/dev/null)
      if [ "${MISSED_COUNT:-0}" -ge 2 ]; then
        echo "ℹ Gap-hunt found ${MISSED_COUNT} missed component(s) in ${slug}; max 1 retry"
        type -t emit_telemetry_v2 >/dev/null 2>&1 && \
          emit_telemetry_v2 "blueprint_view_decomp_gap" "${PHASE_NUMBER}" "blueprint.2b6c" \
            "view_decomp_gap_hunt" "WARN" "{\"slug\":\"${slug}\",\"missed\":${MISSED_COUNT}}"
      fi
    fi
  done
fi
```

**Behaviour:**
- 0 CrossAI CLIs → gap-hunt skipped.
- <2 missed → continue, log debt.
- ≥2 missed → re-spawn Layer 1 with reminder, max 1 retry.

**Cost note:** ~$0.05-0.10 per slug with Opus vision. 5 slugs ≈ $0.50.

---

## STEP 2.3 — UI spec (2b6_ui_spec)

**Skip conditions:**
- No task `file-path` matching `config.code_patterns.web_pages`
- `config.design_assets.paths` empty
- `${PHASE_DIR}/UI-SPEC.md` already newer than all PLAN*.md + design manifest

**Purpose:** Produce UI contract executor reads alongside API-CONTRACTS.
Answers: layout, component set, spacing tokens, interaction states,
responsive breakpoints.

**Input (per-slug, scales linearly with slug count):**
- CONTEXT.md design decisions (~100 lines)
- Task file-paths of FE tasks + their `<design-ref>` attributes (~100 lines)
- `${DESIGN_OUTPUT_DIR}/manifest.json` (~50 lines)
- For EACH slug in PLAN `<design-ref>` tags: `*.structural.html` +
  `*.interactions.md` for that specific slug. (Previously v2.62.0 and earlier:
  "Sample 2-3 representative refs (~300 lines)" — superseded by D1 v2.63.0
  per-slug split. The old sampling cap left pages 4+ in a phase with no markup
  evidence, causing build executors to write forms from imagination.)
- **`${DESIGN_OUTPUT_DIR}/scans/{slug}.scan.json`** — per-slug Haiku Layer 2
  output (modals_discovered, forms_discovered, tabs_discovered, warnings)
  for EVERY slug in PLAN. Already produced by `/vg:design-extract` Layer 2 —
  consume as authoritative.

**Output (3-layer split — matches API-CONTRACTS / PLAN / TEST-GOALS pattern):**

For every slug in PLAN.md `<design-ref>` tags, emit `${PHASE_DIR}/UI-SPEC/<slug>.md`. Each per-slug file:
  - Layout (grid/flex), sections, states (from scan.json + structural.html for that slug)
  - Per-form verbatim markup (top-5 forms from F1 cap; this slug's forms only)
  - Component variants in this slug (button/modal/datatable canonical markup)
  - Interaction patterns from interactions.md

Also emit `${PHASE_DIR}/UI-SPEC/index.md` listing all per-slug files with one-line summary.

The flat `${PHASE_DIR}/UI-SPEC.md` is built post-agent by the orchestrator concatenating per-slug files. Agents do NOT write the flat file directly.

Per-slug context budget: ~50 lines each. Total context for UI-SPEC writing scales linearly with slug count, no sampling needed. This supersedes the previously deprecated "Sample 2-3 representative" architectural drift (D1) where pages 4+ in a phase had no markup evidence in UI-SPEC.

**Agent prompt:**
```
Generate UI-SPEC per-slug files for phase {PHASE}. This is the design contract
FE executors copy verbatim. Emit `${PHASE_DIR}/UI-SPEC/<slug>.md` for EVERY
slug in PLAN.md `<design-ref>` tags, plus `${PHASE_DIR}/UI-SPEC/index.md` as
the table of contents.

DO NOT write the flat `${PHASE_DIR}/UI-SPEC.md` — orchestrator builds it
post-agent by concatenating per-slug files.

RULES:
1. Extract visible patterns from design-normalized refs — do NOT invent.
2. For each component: name, markup structure (from structural.html),
   states (from interactions.md).
3. Spacing/color tokens only if consistent across refs. If conflict, flag.
4. Per-page section: layout (grid/flex), slots (header/sidebar/main),
   interaction patterns.
5. Reference screenshots by slug — executor opens for pixel truth.
6. **scan.json is authoritative for component inventory.** For every slug:
   - Every `scan.json.modals_discovered[]` MUST appear in `## Modals`.
   - Every `scan.json.forms_discovered[]` MUST appear in `## Forms`.
   - Every `scan.json.tabs_discovered[]` MUST appear as `Tabs:` line in
     `## Per-Page Layout`.
   - `scan.json.warnings[]` MUST be quoted in `## Conflicts / Ambiguities`.
   Do NOT silently drop scan.json findings — re-introduces L-002 silent skip.
7. **Verbatim markup for forms + interactive components (top-N by reference count):**
   For each `<form>` discovered in `scan.json[].forms_discovered`, paste the FULL
   markup block VERBATIM from `{slug}.structural.html`. Do NOT summarize. Do NOT
   replace attribute values with placeholders. Copy `<form>...</form>` byte-for-byte
   including hidden inputs, CSRF tokens, ARIA attrs, and validation patterns.
   NEVER use `...` ellipsis inside the markup block. NO ELLIPSIS.

   Limit: top 5 forms by task reference count (count occurrences in PLAN.md tasks)
   WITHIN THIS SLUG. Remaining forms keep path-reference style. The 5-form cap
   controls per-slug file size while ensuring high-traffic forms are byte-accurate
   for build executors.
8. **Verbatim markup for interactive components (buttons, modals, fields):**
   Where multiple variants exist (primary/secondary/ghost button), paste markup for
   ONE canonical variant per component verbatim, then list other variants as text
   deltas. NEVER use `...` ellipsis in markup blocks. NO ELLIPSIS.
9. **Per-slug emission (D1 v2.63.0):** Write each slug's UI spec to its own file at
   `${PHASE_DIR}/UI-SPEC/<slug>.md`. Do NOT bundle multiple slugs into one file.
   Build executors load only what they need via
   `vg-load --artifact ui-spec --slug <slug>`.

Output format (each `${PHASE_DIR}/UI-SPEC/<slug>.md`):

# UI Spec — {slug} (Phase {PHASE})

Source: ${DESIGN_OUTPUT_DIR}/  (screenshots + structural + interactions for this slug)
Derived: {YYYY-MM-DD}

## Design Tokens
| Token | Value | Source |
|---|---|---|
| color.primary | #6366f1 | consistent across {slug-a}, {slug-b} |
| spacing.lg | 24px | ... |

## Component Library (observed in design)
### Button
- Variants: primary | secondary | ghost
- States: default | hover | disabled
- Markup (verbatim, primary variant):

  ```html
  <button class="btn btn-primary" type="submit" data-action="save">
    Save
  </button>
  ```

  Other variants delta-listed: secondary class swap (`btn-primary` → `btn-secondary`),
  ghost variant adds `btn-ghost` class.

### Modal
- Pattern: overlay + centered card
- Open/close: `data-modal-open="{id}"` / `data-modal-close` (from {slug}.interactions.md)

## Per-Page Layout
### /publisher/sites (Task 07)
- Screenshot: ${DESIGN_OUTPUT_DIR}/screenshots/sites-list.default.png
- Layout: sidebar (fixed 240px) + main (flex-1)
- Sections: toolbar (search + Add button), table (5 cols), pagination footer
- States needed: empty | loading | populated | error
- Interactions: row click → detail drawer; Add button → modal

## Modals
(enumerate every modal from scan.json[].modals_discovered)
### {modal-name} (from {slug})
- Trigger: {selector or button label}
- Fields: {list from scan.json}
- States: open | closed | submitting | error

## Forms
(enumerate every form from scan.json[].forms_discovered)
### {form-name} (from {slug})

**Submit endpoint:** {API contract ref}

**Markup (verbatim from {slug}.structural.html):**

```html
<form id="..." action="..." method="..." novalidate>
  <input type="hidden" name="_csrf" value="...">
  <input name="user_email" type="email" required pattern="[^\s@]+@[^\s@]+">
  <!-- COPY EVERY input/select/textarea/button verbatim. NO ELLIPSIS. -->
</form>
```

**Field summary (derived from markup above):**

| name attr | type | required | pattern / max |
|---|---|---|---|
| user_email | email | yes | regex above |
| ... | ... | ... | ... |

## Verbatim Cap

Per-slug paste cap: top **5 forms** + **3 interactive components** (button/modal/datatable
canonical variants) verbatim WITHIN THIS SLUG. Remaining forms/components reference by path
(`{slug}.structural.html#anchor`). User can opt-out via `vg.config.md →
blueprint.ui_spec_verbatim_cap: <int>`. Default 5/3.

**Why caps:** Per-slug UI-SPEC files are loaded selectively by build executors
via `vg-load --artifact ui-spec --slug <slug>`. Unbounded paste per slug →
context budget overflow → executor truncate. 5 forms × 50 lines avg = 250 lines.

## Responsive Breakpoints
(only if design has multiple viewport screenshots)

## Conflicts / Ambiguities
(flag anything where design refs disagree; include scan.json[].warnings verbatim)
```

**Index file format (`${PHASE_DIR}/UI-SPEC/index.md`):**

```markdown
# UI-SPEC Index — Phase {PHASE}

Generated: {YYYY-MM-DD}
3-layer split (D1 v2.63.0): per-slug files + this index + flat concat (UI-SPEC.md).

## Per-slug files

- [{slug-a}](./{slug-a}.md) — one-line summary (e.g., "publisher sites list with toolbar + 5-col table")
- [{slug-b}](./{slug-b}.md) — one-line summary
- ... (one entry per slug emitted)

## Loading

Build executors:
  vg-load --phase {PHASE} --artifact ui-spec --slug <slug>

Falls back to flat UI-SPEC.md if per-slug file missing (legacy phase pre-D1).
```

Write per-slug files to `${PHASE_DIR}/UI-SPEC/<slug>.md` and index to
`${PHASE_DIR}/UI-SPEC/index.md`. Build step 4/8c loads per-slug via vg-load.

```bash
vg-orchestrator step-active 2b6_ui_spec

# ─── F9 Batch 16: --skip-ui-spec escape hatch ──────────────────────────────
# blueprint.md runtime_contract declares UI-SPEC as required_unless_flag:
# --skip-ui-spec. When skipped, must emit vg-orchestrator override so the
# forbidden_without_override contract validator can detect the intentional skip.
if [[ "${ARGUMENTS:-}" =~ --skip-ui-spec ]]; then
  OVERRIDE_REASON=$(echo "${ARGUMENTS}" | sed -nE 's/.*--override-reason=([^ ]+).*/\1/p' | head -1)
  if [ -z "$OVERRIDE_REASON" ]; then
    echo "⛔ F9: --skip-ui-spec requires --override-reason=<text> on the command line" >&2
    exit 1
  fi
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
    --flag "--skip-ui-spec" \
    --reason "${OVERRIDE_REASON}" || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "blueprint-skip-ui-spec" "${PHASE_NUMBER}" "UI-SPEC generation skipped" "${PHASE_DIR}"
  echo "⚠ --skip-ui-spec set (override logged) — skipping UI-SPEC generation"
  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b6_ui_spec" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b6_ui_spec.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6_ui_spec 2>/dev/null || true
else

# ─── F9 Batch 16: --skip-form-api-map escape hatch ─────────────────────────
# blueprint.md runtime_contract declares FORM-API-MAP.md as required_unless_flag:
# --skip-form-api-map. When skipped, must emit vg-orchestrator override so the
# forbidden_without_override contract validator can detect the intentional skip.
if [[ "${ARGUMENTS:-}" =~ --skip-form-api-map ]]; then
  OVERRIDE_REASON_FORM=$(echo "${ARGUMENTS}" | sed -nE 's/.*--override-reason=([^ ]+).*/\1/p' | head -1)
  if [ -z "$OVERRIDE_REASON_FORM" ]; then
    echo "⛔ F9: --skip-form-api-map requires --override-reason=<text> on the command line" >&2
    exit 1
  fi
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
    --flag "--skip-form-api-map" \
    --reason "${OVERRIDE_REASON_FORM}" || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "blueprint-skip-form-api-map" "${PHASE_NUMBER}" "FORM-API-MAP generation skipped" "${PHASE_DIR}"
  echo "⚠ --skip-form-api-map set (override logged) — FORM-API-MAP.md will not be generated"
fi

# (Agent spawn happens here — orchestrator dispatches per agent prompt above.
#  Agent writes ${PHASE_DIR}/UI-SPEC/<slug>.md per slug + UI-SPEC/index.md.)

# D1 v2.63.0 — Post-agent: concat per-slug UI-SPEC into flat for legacy compat.
# Agents emit per-slug files; orchestrator builds the flat UI-SPEC.md by
# concatenating them. Existing grep validators that scan UI-SPEC.md keep working.
mkdir -p "${PHASE_DIR}/UI-SPEC" 2>/dev/null
{
  echo "# UI Spec — Phase ${PHASE_NUMBER}"
  echo ""
  echo "Generated: $(date -u +%FT%TZ)"
  echo "Layered split: see UI-SPEC/index.md for per-slug files."
  echo ""
  for f in "${PHASE_DIR}/UI-SPEC/"*.md; do
    [ -f "$f" ] || continue
    base=$(basename "$f" .md)
    [ "$base" = "index" ] && continue
    echo "---"
    echo ""
    echo "## (slug: ${base})"
    echo ""
    cat "$f"
    echo ""
  done
} > "${PHASE_DIR}/UI-SPEC.md"

# F7 Batch 17: UI-SPEC existence gate — Agent MUST have written index + per-slug files.
# Skip gate when --skip-ui-spec was set (handled above via override emit).
# For FE phases, BLOCK if Agent left UI-SPEC dir empty.
FE_TASKS_COUNT=$(grep -cE "(\.tsx|\.jsx|\.vue|\.svelte)" "${PHASE_DIR}"/PLAN*.md 2>/dev/null || echo "0")
if [ "${FE_TASKS_COUNT:-0}" -gt 0 ]; then
  if [ ! -f "${PHASE_DIR}/UI-SPEC/index.md" ]; then
    echo "⛔ F7 BLOCK: UI-SPEC/index.md missing — Agent did not write spec output." >&2
    echo "   FE phase requires UI-SPEC. Re-run blueprint or pass --skip-ui-spec --override-reason=<text>." >&2
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "blueprint.ui_spec_missing" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  # Per-slug coverage check: count <design-ref> slugs in PLAN.md, count files in UI-SPEC/
  SLUG_COUNT=$(grep -oE '<design-ref[^>]*slug="[^"]+"' "${PHASE_DIR}"/PLAN*.md 2>/dev/null | wc -l | tr -d ' ')
  SPEC_FILE_COUNT=$(find "${PHASE_DIR}/UI-SPEC" -maxdepth 1 -name "*.md" -not -name "index.md" 2>/dev/null | wc -l | tr -d ' ')
  if [ "${SLUG_COUNT:-0}" -gt 0 ] && [ "${SPEC_FILE_COUNT:-0}" -lt "${SLUG_COUNT}" ]; then
    echo "⚠ F7: UI-SPEC coverage gap — ${SPEC_FILE_COUNT}/${SLUG_COUNT} slugs have per-slug spec files" >&2
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "blueprint.ui_spec_partial" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"slugs\":${SLUG_COUNT},\"specs\":${SPEC_FILE_COUNT}}" >/dev/null 2>&1 || true
  fi
fi

fi  # end --skip-ui-spec else branch

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b6_ui_spec" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b6_ui_spec.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6_ui_spec 2>/dev/null || true
```

---

## STEP 2.4 — UI map (2b6b_ui_map)

**Mục tiêu:** Tạo `UI-MAP.md` chứa cây component đích (to-be blueprint) cho
view mới/sửa. Executor bám cây này khi viết code, verify-ui-structure.py so
sánh post-wave để phát hiện lệch hướng (drift).

**Khác biệt với 2b6_ui_spec:**
- `UI-SPEC.md` = spec cấp cao (design tokens, typography, interactions) — toàn phase.
- `UI-MAP.md` = cây component cụ thể từng view — executor bám từng dòng.

**Skip khi:**
- Phase không có task UI (profile backend-only)
- Config `ui_map.enabled: false`

```bash
vg-orchestrator step-active 2b6b_ui_map

UI_MAP_ENABLED=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /enabled:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "true")

if [ "$UI_MAP_ENABLED" != "true" ]; then
  echo "ℹ ui_map disabled in config — skipping UI-MAP generation"
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b6b_ui_map" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b6b_ui_map.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6b_ui_map 2>/dev/null || true
else
  FE_TASKS=$(grep -cE "(\.tsx|\.jsx|\.vue|\.svelte)" "${PHASE_DIR}"/PLAN*.md 2>/dev/null || echo "0")

  if [ "${FE_TASKS:-0}" -eq 0 ]; then
    echo "ℹ Phase không có task FE — skip UI-MAP"
    (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b6b_ui_map" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b6b_ui_map.done"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6b_ui_map 2>/dev/null || true
  else
    echo "Phase có ${FE_TASKS} dòng task FE. Chuẩn bị UI-MAP.md..."

    # Bước 1: Sinh as-is map nếu phase sửa view cũ
    EXISTING_UI_FILES=$(grep -hE "^\s*-\s*(Edit|Modify):" "${PHASE_DIR}"/PLAN*.md 2>/dev/null | \
                        grep -oE "[a-z_-]+\.(tsx|jsx|vue|svelte)" | sort -u)

    if [ -n "$EXISTING_UI_FILES" ]; then
      echo "Phát hiện task sửa view cũ — sinh UI-MAP-AS-IS.md để planner hiểu cấu trúc hiện tại"
      UI_MAP_SRC=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /src:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"')
      UI_MAP_ENTRY=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /entry:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"')

      if [ -n "$UI_MAP_SRC" ] && [ -n "$UI_MAP_ENTRY" ]; then
        node .claude/scripts/generate-ui-map.mjs \
          --src "$UI_MAP_SRC" --entry "$UI_MAP_ENTRY" \
          --format both --output "${PHASE_DIR}/UI-MAP-AS-IS.md" 2>&1 | tail -3
      else
        echo "⚠ ui_map.src / ui_map.entry chưa cấu hình — bỏ qua as-is scan"
      fi
    fi

    # Bước 2: Planner viết UI-MAP.md (to-be blueprint)
    # Orchestrator spawn planner agent với CONTEXT.md + PLAN*.md + UI-SPEC.md +
    # UI-MAP-AS-IS.md (nếu có) + Design refs từ design-normalized/
    # Output: ${PHASE_DIR}/UI-MAP.md với:
    #   - Cây ASCII cho mỗi view mới/sửa
    #   - JSON tree (machine-readable, cho verify-ui-structure.py diff)
    #   - Layout notes (class layout + style keys)
    # Template: ${REPO_ROOT}/.claude/commands/vg/_shared/templates/UI-MAP-template.md

    if [ ! -f "${PHASE_DIR}/UI-MAP.md" ]; then
      echo "▸ Orchestrator spawn planner agent (model=${MODEL_PLANNER:-opus}) viết UI-MAP.md"
      echo "   Input: CONTEXT.md + PLAN*.md + UI-SPEC.md + UI-MAP-AS-IS.md (nếu có)"
      echo "   Output: ${PHASE_DIR}/UI-MAP.md"
      echo ""
      echo "   Schema lock + ownership tags:"
      echo "    - JSON tree MUST validate against schemas/ui-map.v1.json (5 fields per node:"
      echo "        tag, classes, children_count_order, props_bound, text_content_static)."
      echo "    - Each node MUST carry owner_wave_id (and owner_task_id when finer scope helps)."
      echo "    - Children inherit ownership unless override."
      echo "    - extract-subtree-haiku.mjs reads tags during /vg:build step 8c — missing tags ="
      echo "        no deterministic injection, executor falls back to full UI-MAP (cost spike)."
    else
      echo "ℹ UI-MAP.md đã có — skip regeneration. Xoá file để regenerate."
      if [ -x "${REPO_ROOT}/.claude/scripts/validators/verify-uimap-schema.py" ]; then
        ${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/validators/verify-uimap-schema.py" \
            --phase "${PHASE_NUMBER}" 2>&1 | tail -5
      fi
    fi

    # F8 Batch 17: UI-MAP existence gate — planner Agent MUST have written UI-MAP.md.
    # This complements F7 (UI-SPEC gate). Marker only fires when output exists.
    if [ ! -f "${PHASE_DIR}/UI-MAP.md" ]; then
      echo "⛔ F8 BLOCK: UI-MAP.md missing after planner spawn — Agent did not write." >&2
      echo "   FE phase requires UI-MAP. Re-run blueprint or set config 'ui_map.enabled: false' to bypass." >&2
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "blueprint.ui_map_missing" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\",\"fe_tasks\":${FE_TASKS}}" >/dev/null 2>&1 || true
      exit 1
    fi
    # Schema validation: run uimap validator if present
    UIMAP_VAL="${REPO_ROOT:-.}/.claude/scripts/validators/verify-uimap-schema.py"
    [ -x "$UIMAP_VAL" ] || UIMAP_VAL="${REPO_ROOT:-.}/scripts/validators/verify-uimap-schema.py"
    if [ -f "$UIMAP_VAL" ]; then
      ${PYTHON_BIN:-python3} "$UIMAP_VAL" --phase "${PHASE_NUMBER}" 2>&1 | tail -5
      UIMAP_RC=$?
      if [ "$UIMAP_RC" -ne 0 ]; then
        echo "⚠ F8: UI-MAP.md schema validation failed (rc=$UIMAP_RC) — advisory at v4.20.0, will flip to BLOCK in v4.21+" >&2
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "blueprint.ui_map_schema_invalid" \
          --payload "{\"phase\":\"${PHASE_NUMBER}\",\"rc\":${UIMAP_RC}}" >/dev/null 2>&1 || true
      fi
    fi

    (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b6b_ui_map" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b6b_ui_map.done"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6b_ui_map 2>/dev/null || true
  fi
fi
```

**Gate (chưa block, chỉ warn):** nếu phase có task FE nhưng UI-MAP.md không
có, in warning — step 2d validation sẽ escalate.

---

## STEP 2.5 — UI runtime contract (2b6d_ui_runtime_contract)

**Mục tiêu (v3.2.0 / #173 Stage 2):** Emit `${PHASE_DIR}/UI-RUNTIME-CONTRACT.md` + `.json` capturing
the runtime invariants design demands. Closes Issue #173 root cause: UI-heavy phases passed
build/review with Tailwind token drift and missing Playwright lifecycle specs because no
contract listed the design's runtime requirements. Build/review will consume this contract:

- `/vg:build` pre-test-gate (Stage 3) greps generated CSS for `required_tailwind_tokens[].class_name`.
- `/vg:build` pre-test-gate (Stage 3) asserts ≥ `min_spec_count.count` Playwright spec files.
- `/vg:review` hard-blocks (Stage 4) if discovered routes diverge from `route_inventory[]`.
- `/vg:review` uses `env_contract.cookie_domain` / `auth_host` to classify ENV_MISMATCH
  (Stage 1 #173 taxonomy — landed in v3.1.0).

**Skip conditions (`.phase-profile` + PLAN heuristic):**
- `phase_profile ∈ {backend-only, cli-tool, library}` → exit 0, no contract written.
- PLAN*.md has zero `.tsx`/`.jsx`/`.vue`/`.svelte`/`.css` references → exit 0, no contract written.
- VIEW-COMPONENTS.md AND UI-SPEC/ both missing → write stub contract with `skip_reason` populated.

```bash
vg-orchestrator step-active 2b6d_ui_runtime_contract

EMITTER="${REPO_ROOT}/.claude/scripts/blueprint/emit-ui-runtime-contract.py"
[ -f "$EMITTER" ] || EMITTER="${REPO_ROOT}/scripts/blueprint/emit-ui-runtime-contract.py"

if [ ! -f "$EMITTER" ]; then
  echo "⚠ emit-ui-runtime-contract.py missing — skip UI runtime contract (v3.2.0 #173 Stage 2)"
else
  "${PYTHON_BIN:-python3}" "$EMITTER" --phase-dir "${PHASE_DIR}" 2>&1 | sed 's/^/▸ /'
  RC=$?
  if [ "$RC" -ne 0 ]; then
    echo "⚠ emit-ui-runtime-contract.py exit=${RC} — continuing (contract is informational at Stage 2; Stages 3-4 will harden gates)"
  fi
  if [ -f "${PHASE_DIR}/UI-RUNTIME-CONTRACT.json" ]; then
    TOKEN_COUNT=$("${PYTHON_BIN:-python3}" -c "
import json
try:
    d = json.load(open('${PHASE_DIR}/UI-RUNTIME-CONTRACT.json', encoding='utf-8'))
    print(len(d.get('required_tailwind_tokens') or []))
except Exception:
    print(0)
" 2>/dev/null)
    ROUTE_COUNT=$("${PYTHON_BIN:-python3}" -c "
import json
try:
    d = json.load(open('${PHASE_DIR}/UI-RUNTIME-CONTRACT.json', encoding='utf-8'))
    print(len(d.get('route_inventory') or []))
except Exception:
    print(0)
" 2>/dev/null)
    MIN_SPEC=$("${PYTHON_BIN:-python3}" -c "
import json
try:
    d = json.load(open('${PHASE_DIR}/UI-RUNTIME-CONTRACT.json', encoding='utf-8'))
    print((d.get('min_spec_count') or {}).get('count', 0))
except Exception:
    print(0)
" 2>/dev/null)
    echo "✓ UI-RUNTIME-CONTRACT emitted — tokens=${TOKEN_COUNT}, routes=${ROUTE_COUNT}, min_specs=${MIN_SPEC}"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "blueprint.ui_runtime_contract_emitted" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"tokens\":${TOKEN_COUNT:-0},\"routes\":${ROUTE_COUNT:-0},\"min_specs\":${MIN_SPEC:-0}}" \
      >/dev/null 2>&1 || true
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b6d_ui_runtime_contract" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b6d_ui_runtime_contract.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6d_ui_runtime_contract 2>/dev/null || true
```

**Hardening roadmap (deferred to later stages):**
- Stage 3 (build): pre-test-gate greps `apps/*/dist/**/*.css` for each `required_tailwind_tokens[].class_name`; missing → BLOCK.
- Stage 3/4 (build → review): spec-count/lifecycle gate checks post-build test-spec contract coverage; missing → matrix Status=TEST_SPEC_MISSING + route to `/vg:test-spec --regen`, then rerun `/vg:review`.
- Stage 4 (review): runtime route discovery diffed against `route_inventory[]`; divergence → hard-block.
- Stage 4 (review): env preflight matches `env_contract.cookie_domain` against actual browser context; mismatch → ENV_MISMATCH (taxonomy lives in v3.1.0).

At Stage 2 the contract is **informational**: present in the phase directory, consumed by downstream stages
as they ship. Pre-Stage 3 callers ignoring the contract will not break.

---

After all 5 markers touched, return to entry SKILL.md → STEP 3 (plan).
