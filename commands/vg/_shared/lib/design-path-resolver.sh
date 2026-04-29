#!/bin/bash
# design-path-resolver.sh — 2-tier resolver for design refs (v2.30.0).
#
# Issue (raised 2026-04-29): pre-v2.30 stored ALL design refs in a single
# project-level `${PLANNING_DIR}/design-normalized/` directory. Phase 1
# mockups, phase 2 mockups, design-system tokens, brand assets — all flat,
# all shared. Hệ quả: cross-phase contamination, naming collisions, orphan
# refs after phase archive, build phase 5 "seeing" mockups of phase 2.
#
# Fix: 2-tier resolution. Phase-scoped first, project-shared fallback.
#
#   Tier 1 — phase-scoped:   ${PHASE_DIR}/design/{slug}.{kind}
#   Tier 2 — project-shared: ${SHARED_DIR}/{slug}.{kind}     (design-system,
#                                                            brand foundations)
#   Tier 3 — legacy fallback: ${LEGACY_DIR}/{slug}.{kind}    (.vg/design-normalized;
#                                                            soft-deprecated for
#                                                            2 releases)
#
# Functions:
#   vg_design_phase_dir <phase_dir>       → echo "$phase_dir/design"
#   vg_design_shared_dir                  → echo from config or default
#   vg_design_legacy_dir                  → echo from config or default
#   vg_resolve_design_ref <slug> <kind> [phase_dir]
#                                         → echo first existing path or empty
#   vg_resolve_design_dir [phase_dir] [scope]
#                                         → for write-target dispatch in
#                                           /vg:design-extract / scaffold:
#                                           scope=phase → phase dir,
#                                           scope=shared → shared dir,
#                                           default → phase dir if phase_dir
#                                           non-empty else shared.
#
# `kind` examples:
#   screenshots/{slug}.default.png
#   refs/{slug}.structural.html
#   refs/{slug}.interactions.md
#   scans/{slug}.scan.json
#
# Pass `kind` as the relative path inside the design dir (e.g.
# "screenshots/home.default.png") — resolver concatenates with the tier root.
#
# Source from skills:
#   source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/design-path-resolver.sh"
#
# Depends on config-loader.sh having loaded vg.config.md (vg_config_get
# function must be in scope). Falls back to bare defaults if config-loader
# wasn't sourced.

# Phase-scoped directory: each phase owns its design refs.
vg_design_phase_dir() {
  local phase_dir="${1:?phase_dir required}"
  echo "${phase_dir}/design"
}

# Project-shared directory: design system, brand, cross-phase components.
vg_design_shared_dir() {
  if type -t vg_config_get >/dev/null 2>&1; then
    # New canonical key: design_assets.shared_dir
    # Backward-compat key: design_assets.output_dir (now alias)
    local v
    v=$(vg_config_get design_assets.shared_dir "" 2>/dev/null)
    if [ -z "$v" ]; then
      v=$(vg_config_get design_assets.output_dir "" 2>/dev/null)
    fi
    if [ -z "$v" ]; then
      v=".vg/design-system"
    fi
    echo "$v"
    return 0
  fi
  echo ".vg/design-system"
}

# Legacy directory: pre-v2.30 single-tier path. Read-only fallback during
# soft-deprecation window. Auto-resolves from old default if config still
# points there.
vg_design_legacy_dir() {
  if type -t vg_config_get >/dev/null 2>&1; then
    local v
    v=$(vg_config_get design_assets.output_dir "" 2>/dev/null)
    if [ -n "$v" ] && [ "$v" != "$(vg_design_shared_dir)" ]; then
      echo "$v"
      return 0
    fi
  fi
  # Default legacy location — only echo if it actually exists, else empty
  if [ -d ".vg/design-normalized" ]; then
    echo ".vg/design-normalized"
    return 0
  fi
  if [ -d ".planning/design-normalized" ]; then
    echo ".planning/design-normalized"
    return 0
  fi
  echo ""
}

# Resolve a design ref by slug+kind. Searches in tier order.
# Returns first existing path on stdout, or empty string + rc=1 if none.
#
# Usage:
#   path=$(vg_resolve_design_ref "home" "screenshots/home.default.png" "$PHASE_DIR")
#   [ -n "$path" ] || { echo "ref missing"; exit 1; }
vg_resolve_design_ref() {
  local slug="${1:?slug required}"
  local kind="${2:?kind required}"   # e.g. "screenshots/home.default.png"
  local phase_dir="${3:-}"
  local candidate

  # Tier 1 — phase-scoped
  if [ -n "$phase_dir" ]; then
    candidate="$(vg_design_phase_dir "$phase_dir")/${kind}"
    if [ -f "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  fi

  # Tier 2 — project-shared
  candidate="$(vg_design_shared_dir)/${kind}"
  if [ -f "$candidate" ]; then
    echo "$candidate"
    return 0
  fi

  # Tier 3 — legacy fallback
  local legacy
  legacy=$(vg_design_legacy_dir)
  if [ -n "$legacy" ]; then
    candidate="${legacy}/${kind}"
    if [ -f "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  fi

  echo ""
  return 1
}

# Pick the write-target directory for /vg:design-extract / scaffold.
# scope: "phase" → ${phase_dir}/design (requires phase_dir)
#        "shared" → shared dir
#        "" or "auto" → phase dir if phase_dir non-empty else shared dir
vg_resolve_design_dir() {
  local phase_dir="${1:-}"
  local scope="${2:-auto}"

  case "$scope" in
    phase)
      if [ -z "$phase_dir" ]; then
        echo "⛔ vg_resolve_design_dir: scope=phase requires phase_dir" >&2
        return 1
      fi
      vg_design_phase_dir "$phase_dir"
      ;;
    shared)
      vg_design_shared_dir
      ;;
    auto|"")
      # If invoking command knows phase context → write phase-scoped (default
      # behavior in v2.30+). User must `--shared` to write project-shared.
      if [ -n "$phase_dir" ]; then
        vg_design_phase_dir "$phase_dir"
      else
        vg_design_shared_dir
      fi
      ;;
    *)
      echo "⛔ vg_resolve_design_dir: unknown scope=$scope (expected phase|shared|auto)" >&2
      return 1
      ;;
  esac
}

# Diagnostic: print all design dirs the resolver knows about.
vg_design_dirs_status() {
  local phase_dir="${1:-}"
  echo "Design path resolver — dirs:"
  if [ -n "$phase_dir" ]; then
    local pd
    pd="$(vg_design_phase_dir "$phase_dir")"
    echo "  Tier 1 (phase): $pd $([ -d "$pd" ] && echo '[exists]' || echo '[missing]')"
  else
    echo "  Tier 1 (phase): n/a (no phase_dir passed)"
  fi
  local sd
  sd="$(vg_design_shared_dir)"
  echo "  Tier 2 (shared): $sd $([ -d "$sd" ] && echo '[exists]' || echo '[missing]')"
  local ld
  ld="$(vg_design_legacy_dir)"
  if [ -n "$ld" ]; then
    echo "  Tier 3 (legacy): $ld [exists, soft-deprecated]"
  else
    echo "  Tier 3 (legacy): n/a"
  fi
}
