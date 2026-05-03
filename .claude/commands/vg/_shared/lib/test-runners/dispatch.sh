# shellcheck shell=bash
# VG v1.9.1 R1 — Test runner dispatcher
# Resolves `surface` → runner file from vg.config.md.test_strategy.surfaces[surface].runner
# and invokes `run_goal`. Fail-closed: unknown surface / missing runner file → FAILED.
#
# Contract:
#   dispatch_test_runner SURFACE GOAL_ID PHASE_DIR FIXTURE_DIR
#     Prints:   STATUS=<READY|FAILED|PARTIAL>\tEVIDENCE=<path-or-note>\tSURFACE=<resolved>
#     Returns:  0 on READY, 1 on FAILED, 2 on PARTIAL, 99 on dispatch error.

_dispatch_runner_for_surface() {
  local surface="$1"
  local cfg="${VG_CONFIG_PATH:-.claude/vg.config.md}"
  [ -f "$cfg" ] || { echo ""; return 0; }
  ${PYTHON_BIN:-python3} - "$cfg" "$surface" <<'PY'
import re, sys
cfg, want = sys.argv[1], sys.argv[2]
try: txt = open(cfg, encoding='utf-8').read()
except Exception: sys.exit(0)
m = re.search(r'^\s+' + re.escape(want) + r':\s*\n((?:\s{4,}.*\n?)+)', txt, re.M)
if not m: sys.exit(0)
r = re.search(r'runner:\s*"?([a-zA-Z0-9_\-/]+)"?', m.group(1))
if r: print(r.group(1))
PY
}

dispatch_test_runner() {
  local surface="$1" goal_id="$2" phase_dir="$3" fixture_dir="${4:-}"
  [ -z "$surface" ] || [ -z "$goal_id" ] || [ -z "$phase_dir" ] && {
    echo "STATUS=FAILED\tEVIDENCE=dispatch-args-missing\tSURFACE=${surface:-unknown}"
    return 99
  }

  local runner_name runner_path lib_dir
  runner_name=$(_dispatch_runner_for_surface "$surface")
  lib_dir="$(dirname "${BASH_SOURCE[0]}")"
  if [ -z "$runner_name" ]; then
    echo "STATUS=FAILED\tEVIDENCE=no-runner-mapped-for-surface-${surface}\tSURFACE=${surface}" >&2
    return 99
  fi
  runner_path="${lib_dir}/${runner_name}.sh"
  if [ ! -f "$runner_path" ]; then
    echo "STATUS=FAILED\tEVIDENCE=runner-file-missing:${runner_path}\tSURFACE=${surface}" >&2
    return 99
  fi

  # Source runner in a subshell so failures don't pollute caller's env
  (
    # shellcheck disable=SC1090
    . "$runner_path"
    if ! type -t run_goal >/dev/null 2>&1; then
      echo "STATUS=FAILED\tEVIDENCE=runner-missing-run_goal:${runner_name}\tSURFACE=${surface}"
      exit 99
    fi
    run_goal "$goal_id" "$phase_dir" "$fixture_dir"
  )
}

export -f dispatch_test_runner 2>/dev/null || true
