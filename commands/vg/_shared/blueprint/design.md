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

For every SLUG-form `<design-ref>` in PLAN.md tasks:

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

**Input (~750 lines agent context):**
- CONTEXT.md design decisions (~100 lines)
- Task file-paths of FE tasks + their `<design-ref>` attributes (~100 lines)
- `${DESIGN_OUTPUT_DIR}/manifest.json` (~50 lines)
- Sample design refs (2-3 representative `*.structural.html` + `*.interactions.md`) (~300 lines)
- **`${DESIGN_OUTPUT_DIR}/scans/{slug}.scan.json`** — per-slug Haiku Layer 2
  output (modals_discovered, forms_discovered, tabs_discovered, warnings)
  for EVERY slug in PLAN. Already produced by `/vg:design-extract` Layer 2 —
  consume as authoritative.

**Agent prompt:**
```
Generate UI-SPEC.md for phase {PHASE}. This is the design contract FE
executors copy verbatim.

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

Output format:

# UI Spec — Phase {PHASE}

Source: ${DESIGN_OUTPUT_DIR}/  (screenshots + structural + interactions)
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
- Markup: `<button class="btn btn-{variant}">...</button>` (from {slug}.structural.html#btn-primary)

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
- Submit endpoint: {API contract ref}
- Fields: {list from scan.json with type}
- Validation: {client-side rules}

## Responsive Breakpoints
(only if design has multiple viewport screenshots)

## Conflicts / Ambiguities
(flag anything where design refs disagree; include scan.json[].warnings verbatim)
```

Write `${PHASE_DIR}/UI-SPEC.md`. Build step 4/8c injects relevant section per FE task.

```bash
vg-orchestrator step-active 2b6_ui_spec

# (Agent spawn happens here — orchestrator dispatches per agent prompt above)

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

    (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b6b_ui_map" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b6b_ui_map.done"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6b_ui_map 2>/dev/null || true
  fi
fi
```

**Gate (chưa block, chỉ warn):** nếu phase có task FE nhưng UI-MAP.md không
có, in warning — step 2d validation sẽ escalate.

After all 4 markers touched, return to entry SKILL.md → STEP 3 (plan).
