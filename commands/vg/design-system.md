---
user-invocable: true
description: "Design system lifecycle — browse/import/create/view/edit DESIGN.md (58 brand variants from getdesign.md ecosystem)"
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "design_system.started"
    - event_type: "design_system.completed"
---

<rules>
1. **Multi-design support** — project may have multiple design systems per role (SSP admin, DSP admin, Publisher, Advertiser). Use `--role=<name>` to target role-specific design.
2. **Pre-paywall source** — fetches from `Meliwat/awesome-design-md-pre-paywall` (free). Official `VoltAgent/awesome-design-md` moved content behind getdesign.md paywall.
3. **File convention** — project-level: `${PLANNING_DIR}/design/DESIGN.md`. Role-level: `${PLANNING_DIR}/design/{role}/DESIGN.md`. Phase-override: `${PLANNING_DIR}/phases/XX/DESIGN.md`.
4. **Resolution priority (highest first)** — phase > role > project > none.
5. **Idempotent** — running `--import` twice downloads again (brand files may be updated upstream).
</rules>

<objective>
Manage DESIGN.md files for UI standardization. Integrates with scope Round 4 (UI discussion), build (inject into UI task prompts), review (token validation).

Modes:
- `--browse` — list available 58 brand design systems grouped by category
- `--import <brand>` — download brand DESIGN.md to project/role location
- `--create` — guided discussion to build custom DESIGN.md
- `--view [--role=<name>]` — print current DESIGN.md content
- `--edit [--role=<name>]` — open editor to modify (delegates to $EDITOR)
- `--validate [--scan=<path>]` — check code tokens vs DESIGN.md palette
</objective>

<process>

**Config:** Source `.claude/commands/vg/_shared/lib/design-system.sh` first.

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/design-system.sh"
```

<step name="0_parse_args">
## Step 0: Parse arguments

Parse flags from `$ARGUMENTS`:

```bash
MODE=""
BRAND=""
ROLE=""
SCAN_PATH="apps/web/src"

for arg in $ARGUMENTS; do
  case "$arg" in
    --browse)         MODE="browse" ;;
    --import=*|-i=*)  MODE="import"; BRAND="${arg#*=}" ;;
    --import|-i)      MODE="import" ;;  # followed by positional brand
    --create)         MODE="create" ;;
    --view)           MODE="view" ;;
    --edit)           MODE="edit" ;;
    --validate)       MODE="validate" ;;
    --role=*)         ROLE="${arg#*=}" ;;
    --scan=*)         SCAN_PATH="${arg#*=}" ;;
    *)
      # Positional: brand name after --import
      if [ "$MODE" = "import" ] && [ -z "$BRAND" ]; then
        BRAND="$arg"
      fi
      ;;
  esac
done

# Default mode if none specified
[ -z "$MODE" ] && MODE="browse"
```

**If mode unknown → BLOCK:**
```
Usage: /vg:design-system [--browse | --import <brand> | --create | --view | --edit | --validate] [--role=<name>]
```
</step>

<step name="1_dispatch">
## Step 1: Dispatch mode

### Mode: `browse`

List all 58 available brands, grouped by category. User can pick one to import next.

```bash
design_system_browse_grouped
echo ""
echo "To import a brand:"
echo "  /vg:design-system --import stripe              # → ${PLANNING_DIR}/design/DESIGN.md (project-level)"
echo "  /vg:design-system --import linear --role=ssp   # → ${PLANNING_DIR}/design/ssp/DESIGN.md (role-level)"
```

### Mode: `import`

Download brand DESIGN.md to target path.

```bash
if [ -z "$BRAND" ]; then
  echo "⛔ Brand not specified. Usage: /vg:design-system --import <brand>"
  echo "   Run /vg:design-system --browse to see available brands."
  exit 1
fi

# Determine target path
if [ -n "$ROLE" ]; then
  TARGET="${CONFIG_DESIGN_SYSTEM_ROLE_DIR:-${PLANNING_DIR}/design}/${ROLE}/DESIGN.md"
else
  TARGET="${CONFIG_DESIGN_SYSTEM_PROJECT_LEVEL:-${PLANNING_DIR}/design/DESIGN.md}"
fi

# Confirm if target exists
if [ -f "$TARGET" ]; then
  echo "⚠ Target exists: $TARGET"
  # Orchestrator should AskUserQuestion: overwrite / backup+replace / cancel
fi

design_system_fetch "$BRAND" "$TARGET"
echo ""
echo "✓ Imported $BRAND design system."
echo "  Next: /vg:design-system --view${ROLE:+ --role=$ROLE}"
echo "  Or:   /vg:scope {phase}  (Round 4 will auto-detect this DESIGN.md)"
```

### Mode: `create`

Guided discussion to build custom DESIGN.md. Orchestrator asks user 8 questions covering:

1. **Brand personality** — adjectives (modern/classic/playful/technical/luxurious/...) + 2-3 brand references
2. **Primary color** — hex code OR description ("deep purple like Stripe")
3. **Typography** — serif/sans/mono primary, optional secondary
4. **Border radius style** — sharp (0-2px) / subtle (4-6px) / rounded (8-12px) / pill (full)
5. **Shadow style** — flat / layered / colored / none
6. **Spacing scale** — compact (4/8/12/16) / standard (4/8/16/24/32) / generous (8/16/32/48/64)
7. **Motion** — instant / subtle (150ms) / smooth (300ms) / theatrical (500ms+)
8. **Component style** — minimal / standard / decorated

After Q&A, orchestrator generates DESIGN.md via template with 5 sections (Visual Theme, Color Palette, Typography, Spacing, Components) populated from user answers. Writes to target path based on `$ROLE`.

### Mode: `view`

Print current DESIGN.md content. Resolve via priority order.

```bash
# Phase not specified → resolve project/role level only
DESIGN_PATH=$(design_system_resolve "" "$ROLE")

if [ -z "$DESIGN_PATH" ]; then
  echo "⚠ No DESIGN.md found for role='${ROLE:-<project>}'"
  echo "  Import one: /vg:design-system --import <brand>${ROLE:+ --role=$ROLE}"
  echo "  Or browse:  /vg:design-system --browse"
  exit 0
fi

echo "═══════════════════════════════════════════════════════════════"
echo "  DESIGN.md at: $DESIGN_PATH"
echo "═══════════════════════════════════════════════════════════════"
cat "$DESIGN_PATH"
```

### Mode: `edit`

Open file in editor. Fallback: print path for user to edit manually.

```bash
DESIGN_PATH=$(design_system_resolve "" "$ROLE")
if [ -z "$DESIGN_PATH" ]; then
  echo "⛔ No DESIGN.md to edit. Import first: /vg:design-system --import <brand>${ROLE:+ --role=$ROLE}"
  exit 1
fi

if [ -n "$EDITOR" ]; then
  "$EDITOR" "$DESIGN_PATH"
else
  echo "Edit manually: $DESIGN_PATH"
  echo "After edit, run: /vg:design-system --validate  (to check tokens match code)"
fi
```

### Mode: `validate`

Scan code for hex codes, compare against DESIGN.md palette. Report drift.

```bash
design_system_validate_tokens "" "$SCAN_PATH" "$ROLE"
```

Non-blocking — warns but doesn't exit 1. Invoked during `/vg:review` Phase 2.5.
</step>

<step name="2_config_loader">
## Step 2: Auto-populate config on first run

If `.claude/vg.config.md` lacks `design_system:` section, emit hint:

```bash
if ! grep -qE "^design_system:" .claude/vg.config.md; then
  echo ""
  echo "⚠ design_system: section missing from vg.config.md"
  echo "  Add this block to enable full integration:"
  cat <<'EOF'

design_system:
  enabled: true
  source_repo: "Meliwat/awesome-design-md-pre-paywall"
  project_level: "${PLANNING_DIR}/design/DESIGN.md"
  role_dir: "${PLANNING_DIR}/design"
  phase_override_pattern: "{phase_dir}/DESIGN.md"
  inject_on_build: true
  validate_on_review: true

EOF
fi
```
</step>

</process>

<success_criteria>
- `--browse` lists 58 brands grouped into 9 categories
- `--import <brand>` downloads to correct path (phase/role/project)
- `--view` resolves correctly by priority (phase > role > project)
- `--validate` scans CSS/TSX, reports hex drift vs DESIGN.md
- Config section auto-hinted if missing
- All operations idempotent (re-running safe)
</success_criteria>
