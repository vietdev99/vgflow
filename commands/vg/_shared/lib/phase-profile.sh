# shellcheck shell=bash
# Phase Profile System — bash function library (v1.9.2 P5)
# Companion runtime for phase-type detection and per-profile artifact rules.
#
# Problem this solves:
#   v1.9.1 assumed every phase = feature (needs TEST-GOALS + API-CONTRACTS + full pipeline).
#   Reality: strategic apps have multiple phase types — infra hotfixes (Ansible-only),
#   bugfixes (regression-focused), migrations (schema-only), docs (markdown-only),
#   hotfixes (small patches reusing parent goals).
#
# Design:
#   - Pure function: detect_phase_profile PHASE_DIR → echo profile_name (+ rc)
#   - Idempotent: no side effects, no file writes, safe to call repeatedly
#   - Backward-compat: phase with no signal → "feature" (current v1.9.1 behavior)
#
# Exposed functions:
#   - detect_phase_profile PHASE_DIR                 → stdout: feature|infra|hotfix|bugfix|migration|docs|unknown
#   - phase_profile_required_artifacts PROFILE       → stdout: space-separated artifact list
#   - phase_profile_skip_artifacts PROFILE           → stdout: space-separated skip list
#   - phase_profile_review_mode PROFILE              → stdout: full|infra-smoke|delta|regression|schema-verify|link-check
#   - phase_profile_test_mode PROFILE                → same set
#   - phase_profile_goal_coverage_source PROFILE     → stdout: TEST-GOALS|SPECS.success_criteria|SPECS.fixes_bug|parent
#   - parse_success_criteria PHASE_DIR               → stdout: JSON array of {id, cmd, expected}
#   - phase_profile_summarize PHASE_DIR PROFILE      → stderr narration block (Vietnamese)
#
# Usage in review/test/blueprint/scope:
#   source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-profile.sh"
#   PHASE_PROFILE=$(detect_phase_profile "$PHASE_DIR")
#   REQUIRED=$(phase_profile_required_artifacts "$PHASE_PROFILE")
#   REVIEW_MODE=$(phase_profile_review_mode "$PHASE_PROFILE")
#   # ... use $REQUIRED to gate, $REVIEW_MODE to branch

# ═══════════════════════════════════════════════════════════════════════
# detect_phase_profile — pure detection rules
# ═══════════════════════════════════════════════════════════════════════
# Rules (stop at FIRST match):
#   1. NO SPECS.md               → "unknown" rc=1
#   2. only .md files touched    → "docs"
#   3. SPECS has parent_phase:   → "hotfix"
#   4. SPECS has issue_id: / bug_ref: → "bugfix"
#   5. SPECS mentions "migration" + touches schema/migrations → "migration"
#   6. SPECS has `## Success criteria` with bash cmd patterns AND no TEST-GOALS → "infra"
#   7. default                   → "feature"
detect_phase_profile() {
  local phase_dir="${1:-}"
  if [ -z "$phase_dir" ] || [ ! -d "$phase_dir" ]; then
    echo "unknown"
    return 1
  fi

  local specs="${phase_dir}/SPECS.md"
  if [ ! -f "$specs" ]; then
    # ─── Rule 1b: legacy feature fallback (v1.9.2.1) ─────────────────
    # Phase without SPECS.md but WITH feature artifacts (PLAN + TEST-GOALS + API-CONTRACTS)
    # was built before VG required SPECS. Treat as feature (legacy) — review works off
    # existing artifacts. Downstream steps (required_artifacts) MUST exclude SPECS.
    if [ -f "${phase_dir}/PLAN.md" ] && [ -f "${phase_dir}/TEST-GOALS.md" ] && [ -f "${phase_dir}/API-CONTRACTS.md" ]; then
      echo "feature-legacy"
      return 0
    fi
    echo "unknown"
    return 1
  fi

  # ─── Rule 2: docs-only (all touched files are .md) ──────────────
  # Heuristic: the phase dir has only *.md files AND any task file-paths in PLAN.md
  # reference only .md files. We do not call git here — pure function, so we
  # rely on PLAN file-path extraction. If PLAN missing, fall through.
  local plan="${phase_dir}/PLAN.md"
  if [ -f "$plan" ]; then
    local non_md_paths
    non_md_paths=$(grep -oE '<file-path>[^<]+</file-path>' "$plan" 2>/dev/null | \
                   sed -E 's/<\/?file-path>//g' | \
                   grep -vE '\.md$' | \
                   head -5)
    if [ -z "$non_md_paths" ] && grep -qE '<file-path>[^<]+\.md</file-path>' "$plan" 2>/dev/null; then
      # Only .md file-paths in plan → docs phase
      echo "docs"
      return 0
    fi
  fi

  # ─── Rule 3: hotfix (SPECS has parent_phase: field) ─────────────
  # Nuance: if hotfix ALSO has strong infra bash-smoke signal in success_criteria
  # (≥3 commands using infra tooling), treat as "infra" — phase's actual work is
  # provisioning, parent_phase is informational. Use infra review mode.
  if grep -qE '^\*\*Parent phase:\*\*|^parent_phase:|^\*\*parent_phase\*\*:' "$specs" 2>/dev/null; then
    local hotfix_infra_cmd_count
    hotfix_infra_cmd_count=$(awk '
      /^##[[:space:]]*Success criteria/ { in_sec=1; next }
      /^##[[:space:]]/ && in_sec { exit }
      in_sec && /`[^`]*(curl|ssh|pm2|systemctl|ansible|kubectl|docker|sqlite|psql|clickhouse-client|clickhouse|kafka-topics|kafka|mongosh|redis-cli)[^`]*`/ { c++ }
      END { print c+0 }
    ' "$specs" 2>/dev/null)
    local test_goals_hotfix="${phase_dir}/TEST-GOALS.md"
    if [ -n "$hotfix_infra_cmd_count" ] && [ "$hotfix_infra_cmd_count" -ge 3 ] && [ ! -f "$test_goals_hotfix" ]; then
      echo "infra"
      return 0
    fi
    echo "hotfix"
    return 0
  fi

  # ─── Rule 4: bugfix (SPECS has issue_id: / bug_ref:) ────────────
  if grep -qE '^\*\*issue_id\*\*:|^issue_id:|^\*\*bug_ref\*\*:|^bug_ref:|^\*\*Fixes bug\*\*:' "$specs" 2>/dev/null; then
    echo "bugfix"
    return 0
  fi

  # ─── Rule 5: migration (SPECS mentions migration + touches schema) ──
  if grep -qiE '\b(migration|migrate|schema change|db migration)\b' "$specs" 2>/dev/null; then
    # Also must touch schema/migrations paths — check PLAN if present
    if [ -f "$plan" ]; then
      if grep -qE '<file-path>[^<]*(migrations|schema|\.sql)[^<]*</file-path>' "$plan" 2>/dev/null; then
        echo "migration"
        return 0
      fi
    fi
    # Weaker signal — SPECS itself mentions migration directory
    if grep -qiE '(migrations/|\.sql|prisma/schema|sqlx migrate|knex migrate)' "$specs" 2>/dev/null; then
      echo "migration"
      return 0
    fi
  fi

  # ─── Rule 6: infra (Success criteria bash checklist + no TEST-GOALS) ──
  local test_goals="${phase_dir}/TEST-GOALS.md"
  if [ ! -f "$test_goals" ]; then
    # Parse `## Success criteria` section, count bash command patterns
    # Patterns that indicate infra: curl|ssh|pm2|systemctl|ansible|kubectl|docker|sqlite|psql|clickhouse|kafka
    local infra_cmd_count
    infra_cmd_count=$(awk '
      /^##[[:space:]]*Success criteria/ { in_sec=1; next }
      /^##[[:space:]]/ && in_sec { exit }
      in_sec && /`[^`]*(curl|ssh|pm2|systemctl|ansible|kubectl|docker|sqlite|psql|clickhouse-client|clickhouse|kafka-topics|kafka|mongosh|redis-cli)[^`]*`/ { c++ }
      END { print c+0 }
    ' "$specs" 2>/dev/null)

    if [ -n "$infra_cmd_count" ] && [ "$infra_cmd_count" -ge 1 ]; then
      echo "infra"
      return 0
    fi
  fi

  # ─── Rule 7: default — feature ───────────────────────────────────
  echo "feature"
  return 0
}

# ═══════════════════════════════════════════════════════════════════════
# Profile rules (static table — mirrors vg.config.md.phase_profiles)
# ═══════════════════════════════════════════════════════════════════════
# Kept in sync with .claude/vg.config.md phase_profiles section.
# When config ≠ code: code defaults win (safer), warn in stderr.

phase_profile_required_artifacts() {
  case "${1:-feature}" in
    feature)        echo "SPECS.md CONTEXT.md PLAN.md API-CONTRACTS.md TEST-GOALS.md SUMMARY.md" ;;
    feature-legacy) echo "CONTEXT.md PLAN.md API-CONTRACTS.md TEST-GOALS.md SUMMARY.md" ;;  # v1.9.2.1 — pre-SPECS phases
    infra)          echo "SPECS.md PLAN.md SUMMARY.md" ;;
    hotfix)         echo "SPECS.md PLAN.md SUMMARY.md" ;;
    bugfix)         echo "SPECS.md PLAN.md SUMMARY.md" ;;
    migration)      echo "SPECS.md PLAN.md SUMMARY.md ROLLBACK.md" ;;
    docs)           echo "SPECS.md" ;;
    unknown)        echo "SPECS.md" ;;
    *)              echo "SPECS.md PLAN.md SUMMARY.md" ;;
  esac
}

phase_profile_skip_artifacts() {
  case "${1:-feature}" in
    feature)        echo "" ;;
    feature-legacy) echo "SPECS.md" ;;  # v1.9.2.1 — treat SPECS as optional for legacy phases
    infra)          echo "TEST-GOALS.md API-CONTRACTS.md CONTEXT.md RUNTIME-MAP.json" ;;
    hotfix)         echo "TEST-GOALS.md API-CONTRACTS.md CONTEXT.md" ;;
    bugfix)         echo "API-CONTRACTS.md CONTEXT.md" ;;
    migration)      echo "API-CONTRACTS.md TEST-GOALS.md RUNTIME-MAP.json" ;;
    docs)           echo "CONTEXT.md PLAN.md API-CONTRACTS.md TEST-GOALS.md RUNTIME-MAP.json SUMMARY.md" ;;
    *)              echo "" ;;
  esac
}

phase_profile_review_mode() {
  case "${1:-feature}" in
    feature|feature-legacy) echo "full" ;;
    infra)                  echo "infra-smoke" ;;
    hotfix)                 echo "delta" ;;
    bugfix)                 echo "regression" ;;
    migration)              echo "schema-verify" ;;
    docs)                   echo "link-check" ;;
    *)                      echo "full" ;;
  esac
}

phase_profile_test_mode() {
  case "${1:-feature}" in
    feature|feature-legacy) echo "full" ;;
    infra)                  echo "infra-smoke" ;;
    hotfix)                 echo "parent-goals-regression" ;;
    bugfix)                 echo "issue-specific" ;;
    migration)              echo "schema-roundtrip" ;;
    docs)                   echo "markdown-lint" ;;
    *)                      echo "full" ;;
  esac
}

phase_profile_goal_coverage_source() {
  case "${1:-feature}" in
    feature|feature-legacy) echo "TEST-GOALS" ;;
    infra)                  echo "SPECS.success_criteria" ;;
    hotfix)                 echo "parent_phase.TEST-GOALS" ;;
    bugfix)                 echo "SPECS.fixes_bug" ;;
    migration)              echo "SPECS.migration_plan" ;;
    docs)                   echo "SPECS.doc_targets" ;;
    *)                      echo "TEST-GOALS" ;;
  esac
}

# ═══════════════════════════════════════════════════════════════════════
# parse_success_criteria — extract bash commands from SPECS `## Success criteria`
# ═══════════════════════════════════════════════════════════════════════
# Output (stdout): JSON array — one entry per checkbox bullet
#   [{"id":"S-01","raw":"<full bullet text>","cmd":"<bash>","expected":"<expected pattern>"}, ...]
#
# Parsing rules:
#   - Bullet format: `- [ ] <raw>` (markdown checklist)
#   - cmd extracted from first ` backtick-quoted ` segment
#   - expected extracted from `→ <expected>` suffix (if present)
#   - Numbering: S-01, S-02, ... in order of appearance
#
# Fallback: if `## Success criteria` section missing or empty → `[]`
parse_success_criteria() {
  local phase_dir="${1:-}"
  local specs="${phase_dir}/SPECS.md"

  if [ ! -f "$specs" ]; then
    echo "[]"
    return 1
  fi

  ${PYTHON_BIN:-python3} - "$specs" <<'PY'
import json, re, sys
from pathlib import Path

specs_path = Path(sys.argv[1])
text = specs_path.read_text(encoding='utf-8', errors='ignore')

# Find "## Success criteria" section (case-insensitive)
in_section = False
bullets = []
for line in text.splitlines():
    if re.match(r'^##\s*Success criteria', line, re.IGNORECASE):
        in_section = True
        continue
    if in_section and re.match(r'^##\s', line):
        break
    if in_section:
        # Markdown checklist bullet: - [ ] or - [x]
        m = re.match(r'^\s*-\s*\[[\sx]\]\s+(.+)$', line, re.IGNORECASE)
        if m:
            bullets.append(m.group(1).strip())

out = []
for i, raw in enumerate(bullets, start=1):
    # Extract first backtick-quoted command
    cmd_m = re.search(r'`([^`]+)`', raw)
    cmd = cmd_m.group(1) if cmd_m else ''

    # Extract expected (after → or =>)
    expected = ''
    exp_m = re.search(r'[→=]>\s*(.+?)(?:\s*$|\s+\()', raw)
    if exp_m:
        expected = exp_m.group(1).strip()
        # Strip trailing backticks from expected
        expected = re.sub(r'`+$', '', expected).strip()

    out.append({
        "id": f"S-{i:02d}",
        "raw": raw,
        "cmd": cmd,
        "expected": expected
    })

print(json.dumps(out, ensure_ascii=False))
PY
}

# ═══════════════════════════════════════════════════════════════════════
# phase_profile_summarize — Vietnamese narration (stderr)
# ═══════════════════════════════════════════════════════════════════════
# Called by review/test step 0 right after detection so user sees reasoning.
phase_profile_summarize() {
  local phase_dir="$1"
  local profile="$2"
  local required review_mode test_mode coverage_src skip_list

  required=$(phase_profile_required_artifacts "$profile")
  review_mode=$(phase_profile_review_mode "$profile")
  test_mode=$(phase_profile_test_mode "$profile")
  coverage_src=$(phase_profile_goal_coverage_source "$profile")
  skip_list=$(phase_profile_skip_artifacts "$profile")

  {
    echo "┌─ Hồ sơ pha (phase profile) đã phát hiện ───────────────────────"
    echo "│ Profile       : ${profile}"
    echo "│ Artifacts bắt buộc : ${required}"
    [ -n "$skip_list" ] && echo "│ Bỏ qua        : ${skip_list}"
    echo "│ Review mode   : ${review_mode}"
    echo "│ Test mode     : ${test_mode}"
    echo "│ Nguồn mục tiêu  : ${coverage_src}"
    echo "└─────────────────────────────────────────────────────────────────"

    case "$profile" in
      infra)
        echo "ℹ Pha hạ tầng (infrastructure) — kiểm thử hạ tầng (infra-smoke) thay cho browser discovery."
        echo "  Goals implicit = mỗi checkbox trong '## Success criteria' của SPECS."
        ;;
      hotfix)
        local parent
        parent=$(grep -E '^\*\*Parent phase:\*\*' "${phase_dir}/SPECS.md" 2>/dev/null | \
                 sed -E 's/.*Parent phase:\*\*\s*//' | head -1)
        [ -n "$parent" ] && echo "ℹ Hotfix của pha cha: ${parent} — sẽ tái dùng TEST-GOALS của pha cha."
        ;;
      bugfix)
        echo "ℹ Pha bugfix — review ở chế độ regression (hồi quy), test tập trung ở issue cụ thể."
        ;;
      migration)
        echo "ℹ Pha migration — kiểm chứng schema (schema-verify), yêu cầu ROLLBACK.md."
        ;;
      docs)
        echo "ℹ Pha docs-only — chỉ kiểm link, không cần browser/test-goals."
        ;;
      feature-legacy)
        echo "ℹ Pha feature legacy (tạo trước khi VG yêu cầu SPECS) — review dùng các artifact hiện có (PLAN + TEST-GOALS + API-CONTRACTS), bỏ qua SPECS."
        echo "  Khuyến nghị: nếu phase này vẫn active, cân nhắc tạo SPECS.md retrospective (hồi tố) cho audit trail."
        ;;
      feature|*)
        # default — no extra narration
        ;;
    esac
  } >&2
}

# ═══════════════════════════════════════════════════════════════════════
# phase_profile_check_required — gate helper for review/test prerequisites
# ═══════════════════════════════════════════════════════════════════════
# Given PHASE_DIR + PROFILE, check each required artifact exists.
# Returns 0 if all present, 1 if any missing.
# Prints missing list to stdout (space-separated).
phase_profile_check_required() {
  local phase_dir="$1"
  local profile="$2"
  local required missing=""
  required=$(phase_profile_required_artifacts "$profile")

  for artifact in $required; do
    if [ ! -f "${phase_dir}/${artifact}" ]; then
      missing="${missing} ${artifact}"
    fi
  done

  missing=$(echo "$missing" | xargs)  # trim leading space
  if [ -n "$missing" ]; then
    echo "$missing"
    return 1
  fi
  return 0
}
