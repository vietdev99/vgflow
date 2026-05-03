#!/usr/bin/env bash
# vg-detect-final-wave — determine if a given wave number is the FINAL wave
# of a phase's plan, by counting waves declared in PLAN/index.md.
#
# USAGE
#   vg-detect-final-wave.sh --phase <N> --wave <M> [--phases-dir DIR]
#   vg-detect-final-wave.sh --phase <N> --max-wave        (just print max)
#
# OUTPUT (stdout, single line JSON)
#   {"phase":"<N>","wave":M,"max_wave":K,"is_final":true|false}
#
# EXIT CODES
#   0  ok (use is_final field to branch)
#   1  bad args
#   2  PLAN/index.md not found
#   3  no waves declared in index (phase has zero-wave plan)
#
# WAVE FORMAT EXPECTED in PLAN/index.md
#   `- Wave 1 (after none): tasks 01, 02`
#   `- Wave 2 (after 1): tasks 03`
#   `- Wave 3 (after 2): tasks 04, 05`
# (Same format consumed by `vg-load --artifact plan --wave N`.)
#
# CALLERS
#   - commands/vg/_shared/build/waves-overview.md (post-wave gate before
#     proceeding to STEP 5 post-execution).
#   - commands/vg/build.md slim entry STEP 4 → STEP 5 transition guard.
#   - scripts/vg-orchestrator/__main__.py is_partial_wave logic (Python
#     reimpl — orchestrator imports same parse function for contract
#     validator's exemption decision).

set -euo pipefail

phase=""
wave=""
phases_dir="${PHASES_DIR:-.vg/phases}"
mode="check"  # check | max

while [ $# -gt 0 ]; do
  case "$1" in
    --phase)       phase="$2"; shift 2 ;;
    --wave)        wave="$2"; shift 2 ;;
    --phases-dir)  phases_dir="$2"; shift 2 ;;
    --max-wave)    mode="max"; shift ;;
    -h|--help)     sed -n '1,30p' "$0" | sed 's/^# \{0,1\}//' ; exit 0 ;;
    *)             echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

[ -z "$phase" ] && { echo "ERROR: --phase required" >&2; exit 1; }
[ "$mode" = "check" ] && [ -z "$wave" ] && { echo "ERROR: --wave required (or --max-wave)" >&2; exit 1; }

# Resolve phase_dir — accept "7", "7.14", "01-foo", or full path
phase_dir=""
if [ -d "$phase" ]; then
  phase_dir="$phase"
elif [ -d "${phases_dir}/${phase}" ]; then
  phase_dir="${phases_dir}/${phase}"
else
  match=$(find "$phases_dir" -maxdepth 1 -type d -name "${phase}*" 2>/dev/null | head -1)
  [ -n "$match" ] && phase_dir="$match"
fi

[ -z "$phase_dir" ] || [ ! -d "$phase_dir" ] && {
  echo "ERROR: phase dir not found for '$phase' (searched $phases_dir)" >&2
  exit 2
}

index="${phase_dir}/PLAN/index.md"
[ -f "$index" ] || { echo "ERROR: PLAN/index.md not found at $index" >&2; exit 2; }

# Parse wave numbers from "- Wave N ..." lines
max_wave=$(grep -E '^- Wave [0-9]+ ' "$index" 2>/dev/null \
           | sed -E 's/^- Wave ([0-9]+) .*/\1/' \
           | sort -n | tail -1)

if [ -z "$max_wave" ]; then
  echo "ERROR: no waves declared in $index (zero-wave plan?)" >&2
  exit 3
fi

if [ "$mode" = "max" ]; then
  printf '{"phase":"%s","max_wave":%d}\n' "$phase" "$max_wave"
  exit 0
fi

# is_final = (wave == max_wave)
is_final="false"
if [ "$wave" = "$max_wave" ]; then
  is_final="true"
fi

printf '{"phase":"%s","wave":%d,"max_wave":%d,"is_final":%s}\n' \
       "$phase" "$wave" "$max_wave" "$is_final"
