# shellcheck shell=bash
# Design System — DESIGN.md lifecycle + resolution for VG pipeline (v1.10.0 R4)
#
# Purpose: Workflow integrates brand design systems (Stripe, Linear, Vercel, Apple,
# Ferrari, BMW, Claude, Cursor, ~58 brands) via getdesign.md ecosystem. Each phase
# scope Round 4 (UI/UX) checks for DESIGN.md → inject into discussion/build/review.
#
# Multi-design support (user feedback 2026-04-18):
#   Project may have multiple roles/dashboards (SSP Admin, DSP Admin, Publisher,
#   Advertiser) with DIFFERENT design systems. Resolution order (highest priority first):
#     1. Phase-level:   ${PLANNING_DIR}/phases/XX/DESIGN.md
#     2. Role-level:    ${PLANNING_DIR}/design/{role}/DESIGN.md
#     3. Project-level: ${PLANNING_DIR}/design/DESIGN.md
#     4. None → scope Round 4 prompts user to pick/import/create
#
# Source repo: Meliwat/awesome-design-md-pre-paywall (user chose pre-paywall 2026-04-18)
# Official VoltAgent/awesome-design-md moved content behind getdesign.md paywall.
#
# Exposed functions:
#   - design_system_resolve PHASE_DIR [ROLE]
#   - design_system_browse
#   - design_system_fetch BRAND TARGET_PATH
#   - design_system_list_roles
#   - design_system_inject_context PHASE_DIR ROLE  (prints DESIGN.md content to stdout)
#   - design_system_validate_tokens PHASE_DIR PATH_TO_CSS
#
# Config keys (vg.config.md):
#   design_system:
#     enabled: true
#     source_repo: "Meliwat/awesome-design-md-pre-paywall"
#     project_level: "${PLANNING_DIR}/design/DESIGN.md"
#     role_dir: "${PLANNING_DIR}/design"
#     phase_override_pattern: "{phase_dir}/DESIGN.md"
#     inject_on_build: true
#     validate_on_review: true

DESIGN_SYSTEM_DEFAULT_REPO="Meliwat/awesome-design-md-pre-paywall"
DESIGN_SYSTEM_DEFAULT_PROJECT_PATH="${PLANNING_DIR}/design/DESIGN.md"
DESIGN_SYSTEM_DEFAULT_ROLE_DIR="${PLANNING_DIR}/design"

design_system_enabled() {
  [ "${CONFIG_DESIGN_SYSTEM_ENABLED:-true}" = "true" ] || return 1
  return 0
}

# Resolve applicable DESIGN.md for a phase/role.
# Echoes resolved path to stdout, "" if none found.
# Priority: phase override > role specific > project default.
design_system_resolve() {
  local phase_dir="$1"
  local role="${2:-}"
  local source_repo="${CONFIG_DESIGN_SYSTEM_SOURCE_REPO:-$DESIGN_SYSTEM_DEFAULT_REPO}"
  local project_path="${CONFIG_DESIGN_SYSTEM_PROJECT_LEVEL:-$DESIGN_SYSTEM_DEFAULT_PROJECT_PATH}"
  local role_dir="${CONFIG_DESIGN_SYSTEM_ROLE_DIR:-$DESIGN_SYSTEM_DEFAULT_ROLE_DIR}"

  # 1. Phase-level override
  if [ -n "$phase_dir" ] && [ -f "${phase_dir}/DESIGN.md" ]; then
    echo "${phase_dir}/DESIGN.md"
    return 0
  fi

  # 2. Role-specific (if role provided)
  if [ -n "$role" ]; then
    local role_path="${role_dir}/${role}/DESIGN.md"
    if [ -f "$role_path" ]; then
      echo "$role_path"
      return 0
    fi
  fi

  # 3. Project default
  if [ -f "$project_path" ]; then
    echo "$project_path"
    return 0
  fi

  # 4. Not found
  echo ""
  return 1
}

# List available brands from source repo.
# Cached 1 hour in $VG_TMP/design-system-brands.txt
design_system_browse() {
  local cache="${VG_TMP:-/tmp}/design-system-brands.txt"
  local cache_age_sec=3600
  local source_repo="${CONFIG_DESIGN_SYSTEM_SOURCE_REPO:-$DESIGN_SYSTEM_DEFAULT_REPO}"

  if [ -f "$cache" ]; then
    local mtime age
    mtime=$(stat -c '%Y' "$cache" 2>/dev/null || stat -f '%m' "$cache" 2>/dev/null || echo 0)
    age=$(( $(date +%s) - mtime ))
    if [ "$age" -lt "$cache_age_sec" ]; then
      cat "$cache"
      return 0
    fi
  fi

  mkdir -p "$(dirname "$cache")" 2>/dev/null || true
  if command -v gh >/dev/null 2>&1; then
    gh api "repos/${source_repo}/contents/design-md" --jq '.[].name' > "$cache" 2>/dev/null
  else
    curl -sL "https://api.github.com/repos/${source_repo}/contents/design-md" 2>/dev/null | \
      ${PYTHON_BIN:-python3} -c "import json,sys; [print(x['name']) for x in json.loads(sys.stdin.read())]" > "$cache" 2>/dev/null || true
  fi

  if [ ! -s "$cache" ]; then
    echo "ERROR: Failed to fetch brands list from ${source_repo}" >&2
    return 1
  fi
  cat "$cache"
}

# Fetch a brand's DESIGN.md to target path.
# Usage: design_system_fetch "stripe" "${PLANNING_DIR}/design/DESIGN.md"
design_system_fetch() {
  local brand="$1"
  local target="$2"
  local source_repo="${CONFIG_DESIGN_SYSTEM_SOURCE_REPO:-$DESIGN_SYSTEM_DEFAULT_REPO}"

  if [ -z "$brand" ] || [ -z "$target" ]; then
    echo "Usage: design_system_fetch BRAND TARGET_PATH" >&2
    return 1
  fi

  local url="https://raw.githubusercontent.com/${source_repo}/main/design-md/${brand}/DESIGN.md"
  mkdir -p "$(dirname "$target")" 2>/dev/null || true

  if ! curl -sfL "$url" -o "$target"; then
    echo "ERROR: Failed to fetch $brand from $url" >&2
    rm -f "$target"
    return 1
  fi

  # Sanity check: file should start with "# Design System Inspiration of"
  if ! head -1 "$target" | grep -qE "Design System|Design Inspiration"; then
    echo "WARN: Fetched file doesn't look like DESIGN.md. Inspect: $target" >&2
  fi

  echo "✓ Fetched $brand → $target ($(wc -l < "$target") LOC)"
  return 0
}

# List configured roles (subdirectories under role_dir)
design_system_list_roles() {
  local role_dir="${CONFIG_DESIGN_SYSTEM_ROLE_DIR:-$DESIGN_SYSTEM_DEFAULT_ROLE_DIR}"
  [ -d "$role_dir" ] || return 0

  for d in "$role_dir"/*/; do
    [ -d "$d" ] || continue
    local name
    name=$(basename "$d")
    if [ -f "${d}DESIGN.md" ]; then
      echo "$name"
    fi
  done
}

# Inject resolved DESIGN.md content to stdout (for build task prompts or scope discussion).
# Wraps content in <design_system> tags with role metadata.
design_system_inject_context() {
  local phase_dir="$1"
  local role="${2:-}"
  local resolved
  resolved=$(design_system_resolve "$phase_dir" "$role")

  if [ -z "$resolved" ]; then
    echo "<design_system resolved=\"none\">"
    echo "No DESIGN.md resolved for phase=$phase_dir role=$role"
    echo "Task should use semantic defaults (shadcn/ui tokens)."
    echo "</design_system>"
    return 1
  fi

  local level
  case "$resolved" in
    *"/phases/"*)  level="phase-override" ;;
    *"/design/"*/DESIGN.md) level="role-specific" ;;
    *)             level="project-default" ;;
  esac

  echo "<design_system resolved=\"${resolved}\" level=\"${level}\" role=\"${role:-default}\">"
  cat "$resolved"
  echo ""
  echo "</design_system>"
  return 0
}

# Validate CSS/TSX tokens against DESIGN.md color palette.
# Reports drift (hex codes in code NOT listed in DESIGN.md).
# Returns 0 if clean, 1 if drift detected.
design_system_validate_tokens() {
  local phase_dir="$1"
  local scan_path="${2:-apps/web/src}"
  local role="${3:-}"

  local design_md
  design_md=$(design_system_resolve "$phase_dir" "$role")
  if [ -z "$design_md" ]; then
    echo "N/A — no DESIGN.md resolved, skipping validation"
    return 0
  fi

  # Extract hex codes from DESIGN.md (allowed palette)
  local allowed_hex
  allowed_hex=$(grep -oiE '#[0-9a-f]{3,8}' "$design_md" | tr '[:upper:]' '[:lower:]' | sort -u)

  # Scan code for hex codes actually used
  local used_hex
  used_hex=$(grep -rhoiE '#[0-9a-f]{3,8}' "$scan_path" 2>/dev/null | tr '[:upper:]' '[:lower:]' | sort -u)

  if [ -z "$used_hex" ]; then
    echo "No hex codes in code — nothing to validate"
    return 0
  fi

  # Find drift: hex codes in code NOT in allowed palette
  local drift
  drift=$(comm -23 <(echo "$used_hex") <(echo "$allowed_hex") 2>/dev/null)

  if [ -z "$drift" ]; then
    echo "✓ Token validation PASS — all hex codes match DESIGN.md palette"
    return 0
  fi

  echo "⚠ Token drift detected — hex codes in code not in DESIGN.md:"
  echo "$drift" | head -10 | sed 's/^/  - /'
  local drift_count
  drift_count=$(echo "$drift" | wc -l)
  echo "Total drift: $drift_count hex codes"
  return 1
}

# Pretty-print available brands organized by category (uses hardcoded taxonomy)
design_system_browse_grouped() {
  local brands
  brands=$(design_system_browse)
  [ -z "$brands" ] && return 1

  echo "═══════════════════════════════════════════════════════════════"
  echo "  Available Design Systems (from getdesign.md pre-paywall fork)"
  echo "═══════════════════════════════════════════════════════════════"
  echo ""
  echo "📱 AI & LLM Platforms:"
  echo "$brands" | grep -iE "^(claude|cohere|elevenlabs|minimax|mistral\.ai|ollama|opencode\.ai|replicate|together\.ai|voltagent|x\.ai)$" | sed 's/^/  - /'
  echo ""
  echo "🛠 Developer Tools & IDEs:"
  echo "$brands" | grep -iE "^(cursor|expo|framer|lovable|raycast|warp)$" | sed 's/^/  - /'
  echo ""
  echo "🗄 Backend, Database & DevOps:"
  echo "$brands" | grep -iE "^(clickhouse|hashicorp|mongodb|posthog|sanity|sentry|supabase|vercel)$" | sed 's/^/  - /'
  echo ""
  echo "⚡ Productivity & SaaS:"
  echo "$brands" | grep -iE "^(airtable|cal|intercom|linear\.app|miro|notion|superhuman|zapier)$" | sed 's/^/  - /'
  echo ""
  echo "🎨 Design & Creative:"
  echo "$brands" | grep -iE "^(figma|mintlify|pinterest|resend|runwayml|webflow)$" | sed 's/^/  - /'
  echo ""
  echo "💰 Fintech & Crypto:"
  echo "$brands" | grep -iE "^(coinbase|kraken|revolut|stripe|wise)$" | sed 's/^/  - /'
  echo ""
  echo "🛍 E-commerce & Retail:"
  echo "$brands" | grep -iE "^(airbnb|clay|composio)$" | sed 's/^/  - /'
  echo ""
  echo "📺 Media & Consumer:"
  echo "$brands" | grep -iE "^(apple|ibm|nvidia|spacex|spotify|uber)$" | sed 's/^/  - /'
  echo ""
  echo "🚗 Automotive:"
  echo "$brands" | grep -iE "^(bmw|ferrari|lamborghini|renault|tesla)$" | sed 's/^/  - /'
  echo ""
  echo "Other / unclassified:"
  local classified
  classified=$(echo "$brands" | grep -iE "^(claude|cohere|elevenlabs|minimax|mistral\.ai|ollama|opencode\.ai|replicate|together\.ai|voltagent|x\.ai|cursor|expo|framer|lovable|raycast|warp|clickhouse|hashicorp|mongodb|posthog|sanity|sentry|supabase|vercel|airtable|cal|intercom|linear\.app|miro|notion|superhuman|zapier|figma|mintlify|pinterest|resend|runwayml|webflow|coinbase|kraken|revolut|stripe|wise|airbnb|clay|composio|apple|ibm|nvidia|spacex|spotify|uber|bmw|ferrari|lamborghini|renault|tesla)$")
  echo "$brands" | grep -v -F "$(echo "$classified")" 2>/dev/null | sed 's/^/  - /'
}
