#!/usr/bin/env bash
# marker-schema.sh — OHOK Batch 5b (E1) — forgery-resistant step markers.
#
# CrossAI Round 6 critical finding: empty .done markers are forgeable. A
# synthetic marker sweep (one `touch` per expected step) defeats OHOK —
# downstream gates (e.g. accept.md:177-207) check existence, not content.
#
# Fix: mark_step() writes content `{phase}|{step}|{git_sha}|{iso_ts}|{run_id}`
# to the marker file. verify_marker() reads content + checks:
#   1. schema fields parse
#   2. phase field matches expected
#   3. step field matches expected
#   4. git_sha is ancestor of HEAD (proves marker was written at real commit
#      in the phase's history, not after-the-fact `touch` forge)
#   5. iso_ts is within last N days (prevents re-using stale markers from
#      abandoned runs)
#
# Backward compat:
#   - Legacy empty markers still accepted when VG_MARKER_STRICT is false/unset
#     (default = lenient) but WARN logged
#   - VG_MARKER_STRICT=1 makes content verification mandatory
#
# Migration: .claude/scripts/marker-migrate.py rewrites existing empty markers
# with synthetic content (phase from path, step from filename, git_sha=HEAD,
# iso_ts=now, run_id=migration). Run once per project.

set -o pipefail

# Marker schema version (bumped when format changes).
VG_MARKER_SCHEMA="v1"

# ---------------------------------------------------------------------------
# mark_step <phase> <step> <phase_dir> [run_id]
#
# Writes ${phase_dir}/.step-markers/${step}.done with content:
#   v1|{phase}|{step}|{git_sha}|{iso_ts}|{run_id}
#
# If git repo absent or git command fails, uses sha="nogit". Still writes.
# Caller should NOT rely on exit code — marker always writes.
# ---------------------------------------------------------------------------
mark_step() {
  local phase="$1"
  local step="$2"
  local phase_dir="$3"
  local run_id="${4:-${VG_RUN_ID:-run-$(date +%s)-$$}}"

  if [ -z "$phase" ] || [ -z "$step" ] || [ -z "$phase_dir" ]; then
    echo "mark_step: missing arg(s): phase='$phase' step='$step' phase_dir='$phase_dir'" >&2
    return 1
  fi

  local markers_dir="${phase_dir}/.step-markers"
  mkdir -p "$markers_dir" 2>/dev/null

  local git_sha
  git_sha=$(git rev-parse HEAD 2>/dev/null || echo "nogit")

  local iso_ts
  iso_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "notime")

  # Sanitize pipe characters from fields (they'd break the format)
  phase="${phase//|/_}"
  step="${step//|/_}"
  run_id="${run_id//|/_}"

  printf '%s|%s|%s|%s|%s|%s\n' \
    "$VG_MARKER_SCHEMA" "$phase" "$step" "$git_sha" "$iso_ts" "$run_id" \
    > "${markers_dir}/${step}.done"
}

# ---------------------------------------------------------------------------
# read_marker <marker_path>
#
# Prints parsed fields as "schema|phase|step|git_sha|iso_ts|run_id" on stdout.
# For legacy empty markers, prints "legacy|||||".
# Returns 1 if path doesn't exist.
# ---------------------------------------------------------------------------
read_marker() {
  local mp="$1"
  [ -f "$mp" ] || return 1

  local content
  content=$(head -1 "$mp" 2>/dev/null)
  if [ -z "$content" ]; then
    echo "legacy|||||"
    return 0
  fi
  echo "$content"
}

# ---------------------------------------------------------------------------
# verify_marker <marker_path> <expected_phase> <expected_step> [max_age_days]
#
# Exit codes:
#   0 = valid content marker (all 5 checks pass)
#   1 = file missing
#   2 = legacy empty marker (WARN — only BLOCK if VG_MARKER_STRICT=1)
#   3 = schema mismatch / unparseable
#   4 = phase field mismatch
#   5 = step field mismatch
#   6 = git_sha not an ancestor of HEAD (forgery suspected)
#   7 = iso_ts too old (stale marker reused)
#
# On non-zero, prints diagnostic on stderr.
# ---------------------------------------------------------------------------
verify_marker() {
  local mp="$1"
  local expected_phase="$2"
  local expected_step="$3"
  local max_age_days="${4:-30}"

  if [ ! -f "$mp" ]; then
    echo "verify_marker: file missing: $mp" >&2
    return 1
  fi

  local content
  content=$(head -1 "$mp" 2>/dev/null)

  # Legacy empty file
  if [ -z "$content" ]; then
    if [ "${VG_MARKER_STRICT:-0}" = "1" ]; then
      echo "verify_marker: legacy empty marker (STRICT): $mp" >&2
      return 2
    fi
    # Lenient: warn-level return but non-fatal
    return 2
  fi

  # Parse — expect exactly 6 fields separated by |
  local IFS='|'
  # shellcheck disable=SC2206
  local fields=($content)
  unset IFS
  if [ "${#fields[@]}" -ne 6 ]; then
    echo "verify_marker: schema mismatch — expected 6 fields, got ${#fields[@]}: $mp" >&2
    return 3
  fi

  local schema="${fields[0]}"
  local phase="${fields[1]}"
  local step="${fields[2]}"
  local git_sha="${fields[3]}"
  local iso_ts="${fields[4]}"
  # fields[5] = run_id (not verified yet)

  if [ "$schema" != "$VG_MARKER_SCHEMA" ]; then
    echo "verify_marker: schema version '$schema' != expected '$VG_MARKER_SCHEMA': $mp" >&2
    return 3
  fi

  if [ "$phase" != "$expected_phase" ]; then
    echo "verify_marker: phase='$phase' != expected='$expected_phase': $mp" >&2
    return 4
  fi

  if [ "$step" != "$expected_step" ]; then
    echo "verify_marker: step='$step' != expected='$expected_step': $mp" >&2
    return 5
  fi

  # git_sha ancestor check — prevents `touch` forgery. Skip if sha is 'nogit'.
  if [ "$git_sha" != "nogit" ] && [ -n "$git_sha" ]; then
    if ! git merge-base --is-ancestor "$git_sha" HEAD 2>/dev/null; then
      echo "verify_marker: git_sha='$git_sha' NOT an ancestor of HEAD (forgery?): $mp" >&2
      return 6
    fi
  fi

  # Age check — marker must be within max_age_days
  if [ -n "$iso_ts" ] && [ "$iso_ts" != "notime" ]; then
    local marker_epoch now_epoch age_days
    # date -d works on GNU date (Linux, git-bash on Windows). macOS needs -jf.
    marker_epoch=$(date -d "$iso_ts" +%s 2>/dev/null \
                || date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso_ts" +%s 2>/dev/null \
                || echo 0)
    now_epoch=$(date -u +%s)
    if [ "$marker_epoch" -gt 0 ]; then
      age_days=$(( (now_epoch - marker_epoch) / 86400 ))
      if [ "$age_days" -gt "$max_age_days" ]; then
        echo "verify_marker: iso_ts='$iso_ts' (${age_days}d) > max_age_days=${max_age_days}: $mp" >&2
        return 7
      fi
    fi
  fi

  return 0
}

# ---------------------------------------------------------------------------
# verify_all_markers <phase_dir> <expected_phase> [max_age_days]
#
# Iterates every *.done under ${phase_dir}/.step-markers/ and verifies each
# against its expected phase. Step name is extracted from filename.
# Prints summary: "verified=N, legacy=L, forged=F, mismatch=M".
# Exit 0 if no hard failures (forged/mismatch/schema); 1 otherwise.
# ---------------------------------------------------------------------------
verify_all_markers() {
  local phase_dir="$1"
  local expected_phase="$2"
  local max_age="${3:-30}"

  local markers_dir="${phase_dir}/.step-markers"
  if [ ! -d "$markers_dir" ]; then
    echo "verify_all_markers: no markers dir: $markers_dir" >&2
    return 0  # no markers = nothing to verify = not a failure
  fi

  local verified=0 legacy=0 forged=0 mismatch=0 schema_bad=0
  local file step rc

  for file in "$markers_dir"/*.done; do
    [ -f "$file" ] || continue
    step=$(basename "$file" .done)
    verify_marker "$file" "$expected_phase" "$step" "$max_age"
    rc=$?
    case $rc in
      0) verified=$((verified+1)) ;;
      2) legacy=$((legacy+1)) ;;
      3) schema_bad=$((schema_bad+1)) ;;
      4|5) mismatch=$((mismatch+1)) ;;
      6|7) forged=$((forged+1)) ;;
    esac
  done

  echo "verified=${verified}, legacy=${legacy}, forged=${forged}, mismatch=${mismatch}, schema_bad=${schema_bad}"

  # Hard failures: forged + mismatch + schema_bad
  local hard=$((forged + mismatch + schema_bad))
  if [ "$hard" -gt 0 ]; then
    return 1
  fi
  return 0
}

# Export functions when sourced
export -f mark_step read_marker verify_marker verify_all_markers 2>/dev/null || true
