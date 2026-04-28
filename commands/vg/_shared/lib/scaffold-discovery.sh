#!/bin/bash
# scaffold-discovery.sh — Phase 20 D-12 helper
#
# Detect FE work in PLAN + check if mockups exist. Used by:
#   - /vg:specs D-05 (proactive suggestion)
#   - /vg:blueprint D-12 step 0_design_discovery (hard gate)
#   - /vg:design-scaffold step 2_check_existing_assets

# scaffold_detect_fe_work — returns 0 if PLAN has FE files, 1 otherwise
# Args:
#   $1 — phase dir (defaults to $PHASE_DIR)
scaffold_detect_fe_work() {
  local phase_dir="${1:-${PHASE_DIR}}"
  [ -z "$phase_dir" ] && return 1
  local plan_files
  plan_files=$(find "$phase_dir" -maxdepth 1 -name "*PLAN*.md" 2>/dev/null)
  [ -z "$plan_files" ] && return 1

  # Match FE patterns in any PLAN file
  if grep -lE "(apps/(admin|merchant|vendor|web)/|packages/ui/src/(components|theme)/|\.(tsx|jsx|vue|svelte))" $plan_files >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

# scaffold_count_existing_mockups — print count of mockup files in design_assets.paths
# Args: $1 — design_assets.paths[0]
scaffold_count_existing_mockups() {
  local dir="${1:-designs}"
  [ -d "$dir" ] || { echo 0; return; }
  find "$dir" -maxdepth 2 -type f \
    \( -name "*.pen" -o -name "*.penboard" -o -name "*.flow" \
       -o -name "*.html" -o -name "*.htm" \
       -o -name "*.png" -o -name "*.jpg" -o -name "*.jpeg" \
       -o -name "*.fig" -o -name "*.xml" -o -name "*.pb" \) 2>/dev/null | wc -l | tr -d ' '
}

# scaffold_design_md_present — return 0 if any DESIGN.md found in resolution chain
# (project/role/phase). Args: $1 — phase dir.
scaffold_design_md_present() {
  local phase_dir="${1:-${PHASE_DIR}}"
  local planning_dir="${PLANNING_DIR:-.vg}"
  if [ -f "$phase_dir/DESIGN.md" ]; then return 0; fi
  if [ -f "$planning_dir/design/DESIGN.md" ]; then return 0; fi
  # Role-level (loop over potential roles)
  if compgen -G "$planning_dir/design/*/DESIGN.md" >/dev/null 2>&1; then return 0; fi
  return 1
}

# scaffold_emit_status — print one-line status for telemetry / log
# Args: $1 — phase dir, $2 — design_assets.paths[0]
scaffold_emit_status() {
  local phase_dir="${1:-${PHASE_DIR}}"
  local assets_dir="${2:-designs}"
  local has_fe="no"
  scaffold_detect_fe_work "$phase_dir" && has_fe="yes"
  local mockup_count
  mockup_count=$(scaffold_count_existing_mockups "$assets_dir")
  local has_design_md="no"
  scaffold_design_md_present "$phase_dir" && has_design_md="yes"
  printf 'fe_work=%s mockups=%s design_md=%s\n' "$has_fe" "$mockup_count" "$has_design_md"
}

# scaffold_should_block_blueprint — return 0 (true, BLOCK) when:
#   FE work present AND zero mockups
# Args: same as scaffold_emit_status
scaffold_should_block_blueprint() {
  local phase_dir="${1:-${PHASE_DIR}}"
  local assets_dir="${2:-designs}"
  scaffold_detect_fe_work "$phase_dir" || return 1
  local mockup_count
  mockup_count=$(scaffold_count_existing_mockups "$assets_dir")
  [ "$mockup_count" = "0" ]
}
