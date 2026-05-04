#!/usr/bin/env bash
# build-postmortem.sh — final sanity gate at end of /vg:build.
#
# Verifies that the build actually ran through the workflow (not bypassed via
# recovery/direct-edit path). Catches silent gate bypass that would otherwise
# ship untested code claiming "green build".
#
# Phase 10 audit (2026-04-19) found: 0 telemetry events for phase 10 despite
# full build completed + 0 graphify rebuild events + "(recovered)" commits
# suggested framework bypass. This gate catches future such cases.

# Main: assert build emitted expected telemetry events + gates ran.
# Call as last step of /vg:build.
vg_build_postmortem_check() {
  local phase_number="$1"
  local phase_dir="$2"
  local telemetry_file="${3:-.vg/telemetry.jsonl}"

  local issues=0
  local issue_list=""

  # Check 1: telemetry events for this phase
  if [ ! -f "$telemetry_file" ]; then
    issue_list="${issue_list}  - Telemetry file missing at ${telemetry_file}\n"
    issues=$((issues + 1))
  else
    local phase_events
    phase_events=$(grep -c "\"phase\":\s*\"${phase_number}\"" "$telemetry_file" 2>/dev/null || echo "0")
    # Some older events use "unknown" — also check for wave_start markers for phase
    local wave_events
    wave_events=$(grep -c "vg-build-${phase_number}-wave" "$telemetry_file" 2>/dev/null || echo "0")

    if [ "$phase_events" -eq 0 ] && [ "$wave_events" -eq 0 ]; then
      issue_list="${issue_list}  - Zero telemetry events for phase ${phase_number} — build may have bypassed workflow\n"
      issues=$((issues + 1))
    fi
  fi

  # Check 2: wave-start tags present
  local wave_tags
  wave_tags=$(git tag -l "vg-build-${phase_number}-wave-*-start" 2>/dev/null | wc -l | tr -d ' ')
  if [ "${wave_tags:-0}" -eq 0 ]; then
    issue_list="${issue_list}  - No wave-start tags found (vg-build-${phase_number}-wave-*-start) — gates couldn't anchor diffs\n"
    issues=$((issues + 1))
  fi

  # Check 3: recovered commits (suggest manual recovery path)
  local recovered_commits
  recovered_commits=$(git log --oneline --grep="(recovered)" --all | grep -cE "^[a-f0-9]+ (feat|fix)\(${phase_number}" 2>/dev/null || echo "0")
  if [ "${recovered_commits:-0}" -gt 0 ]; then
    issue_list="${issue_list}  - ${recovered_commits} (recovered) commits in phase ${phase_number} — manual recovery may have bypassed gates\n"
    issues=$((issues + 1))
  fi

  # Check 4: RUNTIME-MAP + GOAL-COVERAGE-MATRIX presence (promised by /vg:review, but checkable)
  if [ ! -f "${phase_dir}/RUNTIME-MAP.json" ]; then
    issue_list="${issue_list}  - RUNTIME-MAP.json missing — /vg:review hasn't run yet (informational, not a build gate fail)\n"
  fi

  # Check 5: key gates left fingerprints
  if [ -f "${phase_dir}/.step-markers" ] || [ -d "${phase_dir}/.step-markers" ]; then
    local markers
    markers=$(ls "${phase_dir}/.step-markers"/*.done 2>/dev/null | wc -l | tr -d ' ')
    if [ "${markers:-0}" -lt 3 ]; then
      issue_list="${issue_list}  - Only ${markers} step markers written — expected ≥ 3 for a complete build\n"
      issues=$((issues + 1))
    fi
  else
    issue_list="${issue_list}  - No .step-markers directory — profile enforcement didn't run\n"
    issues=$((issues + 1))
  fi

  # Report
  echo ""
  echo "━━━ Build Post-Mortem (phase ${phase_number}) ━━━"
  if [ "$issues" -eq 0 ]; then
    echo "✓ All sanity checks passed: telemetry present, tags anchored, gates ran."
    if type -t telemetry_emit >/dev/null 2>&1; then
      telemetry_emit "build_postmortem_ok" "{\"phase\":\"${phase_number}\"}"
    fi
    return 0
  fi

  echo "⚠ Post-mortem found ${issues} issue(s):"
  printf "%b" "$issue_list"
  echo ""
  echo "Likely causes:"
  echo "  (a) Build was recovered manually (git path) bypassing /vg:build skill"
  echo "  (b) Telemetry emit helper failed to source"
  echo "  (c) Individual gate scripts crashed silently"
  echo ""
  echo "Downstream consequence: workflow can't trust this phase's gate reports."
  echo "Fix: rerun /vg:build ${phase_number} --resume, OR /vg:review ${phase_number} will replay safety gates."
  echo ""

  if type -t telemetry_emit >/dev/null 2>&1; then
    telemetry_emit "build_postmortem_issues" \
      "{\"phase\":\"${phase_number}\",\"issue_count\":${issues}}"
  fi

  # Warn but don't block by default (non-zero issues = WARN, not FAIL).
  # Caller can check return and decide based on config.
  return 2
}

# Simpler alternative: just assert telemetry ≥ N events for phase.
vg_build_assert_telemetry_present() {
  local phase_number="$1"
  local min_events="${2:-5}"
  local telemetry_file="${3:-.vg/telemetry.jsonl}"

  if [ ! -f "$telemetry_file" ]; then
    echo "⛔ Telemetry file missing — cannot verify build ran through workflow"
    return 2
  fi

  local count
  count=$(grep -c "\"phase\":\s*\"${phase_number}\"" "$telemetry_file" 2>/dev/null || echo "0")
  if [ "${count:-0}" -lt "$min_events" ]; then
    echo "⚠ Only ${count} telemetry events for phase ${phase_number} (expected ≥ ${min_events})"
    echo "   Build may have bypassed workflow skill. Check recovery path."
    return 2
  fi

  echo "✓ Telemetry: ${count} events for phase ${phase_number}"
  return 0
}
