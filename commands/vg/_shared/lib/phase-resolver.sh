# shellcheck shell=bash
# Phase Directory Resolver — bash function library (v1.9.2.2)
#
# Problem this solves:
#   Naive pattern `ls -d ${PLANNING_DIR}/phases/${PHASE_NUMBER}*` fails when:
#   - User types `7.12` but dir is `07.12-*` (zero-padded)
#   - User types `07.12` and wants main phase but `07.12.1-*` sub-phase also matches
#   - User types phase with no directory yet (greenfield)
#
# Design:
#   - Try EXACT match first (phase-name with dash suffix: `07.12-*`)
#   - Normalize integer part to 2-digit zero-pad: `7.12` → `07.12`
#   - Fall back to prefix match if exact fails
#   - Clear error message with suggestions if still not found
#
# Exposed function:
#   - resolve_phase_dir PHASE_NUMBER → stdout: directory path, rc=0
#                                    → rc=1 if not found (prints suggestions to stderr)
#
# Usage in commands:
#   source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-resolver.sh"
#   PHASE_DIR=$(resolve_phase_dir "$PHASE_NUMBER") || exit 1
#
# Replaces this buggy one-liner (found in 10+ files pre-v1.9.2.2):
#   PHASE_DIR=$(ls -d ${PLANNING_DIR}/phases/${PHASE_NUMBER}* 2>/dev/null | head -1)

resolve_phase_dir() {
  local input="${1:-}"
  if [ -z "$input" ]; then
    echo "resolve_phase_dir: empty phase number" >&2
    return 1
  fi

  local phases_dir="${PHASES_DIR:-${PLANNING_DIR}/phases}"
  if [ ! -d "$phases_dir" ]; then
    echo "resolve_phase_dir: phases directory missing at '$phases_dir'" >&2
    return 1
  fi

  # ─── Step 1: exact match with dash suffix (prevents 07.12 matching 07.12.1) ──
  local exact
  exact=$(ls -d "${phases_dir}/${input}-"* 2>/dev/null | head -1)
  if [ -n "$exact" ]; then
    echo "$exact"
    return 0
  fi

  # ─── Step 1b: exact bare-dir match (legacy phases like `00/`, `01/`) ──
  # OHOK v2 Day 5 — migrations from GSD produced bare dir names without `-task`
  # suffix. Prior state: resolver only tried `${input}-*` pattern → bare dirs
  # never matched → "no unique directory for phase '00'" error.
  if [ -d "${phases_dir}/${input}" ]; then
    echo "${phases_dir}/${input}/"
    return 0
  fi

  # ─── Step 2: normalize integer part to 2-digit zero-pad ──────────────
  local major rest normalized
  major="${input%%.*}"
  rest="${input#*.}"
  [ "$major" = "$input" ] && rest=""

  # Only zero-pad if major is numeric and < 10
  if [ -n "$major" ] && [ "$major" -lt 10 ] 2>/dev/null; then
    normalized=$(printf '%02d' "$major" 2>/dev/null)
    [ -n "$rest" ] && [ "$rest" != "$major" ] && normalized="${normalized}.${rest}"

    # Try exact match with dash suffix on normalized
    exact=$(ls -d "${phases_dir}/${normalized}-"* 2>/dev/null | head -1)
    if [ -n "$exact" ]; then
      echo "$exact"
      return 0
    fi
  fi

  # ─── Step 3: boundary-aware prefix match (last resort) ──────────────
  # Only match if next char after number is dash or dot — prevents 99 matching 999.1-*
  local candidates=""
  for prefix in "$input" "$normalized"; do
    [ -z "$prefix" ] && continue
    for dir in "${phases_dir}/${prefix}-"* "${phases_dir}/${prefix}."*; do
      [ -d "$dir" ] && candidates="${candidates}${dir}"$'\n'
    done
  done

  # Deduplicate + drop blanks
  candidates=$(echo "$candidates" | sort -u | grep -v '^$' || true)

  local count
  count=$(echo "$candidates" | grep -c . || true)

  if [ "${count:-0}" = "1" ]; then
    echo "$candidates"
    return 0
  fi

  # ─── Step 4: not found OR ambiguous — clear error to stderr ──────────
  echo "resolve_phase_dir: no unique directory for phase '${input}'" >&2

  if [ "${count:-0}" = "0" ]; then
    echo "  Available phases (top 10):" >&2
    for d in "${phases_dir}"/*/; do
      [ -d "$d" ] && basename "$d" | sed 's/^/    /' >&2
    done | head -10 >&2
    echo "  Tip: use phase number as it appears in directory name (e.g., '07.12' or '7.12 → 07.12')." >&2
  else
    echo "  Multiple candidates matched — please be more specific:" >&2
    while IFS= read -r c; do
      [ -n "$c" ] && basename "$c" | sed 's/^/    /' >&2
    done <<< "$candidates"
  fi
  return 1
}

# Backward-compat shim: callers using `${PHASE_NUMBER}*` pattern directly can
# migrate by replacing with `$(resolve_phase_dir "$PHASE_NUMBER")`.
