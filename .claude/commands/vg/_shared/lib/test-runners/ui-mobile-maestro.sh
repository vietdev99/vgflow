# shellcheck shell=bash
# VG v1.9.1 R1 — Surface runner: ui-mobile (Maestro)
# Delegates to project-installed Maestro CLI. Expects a flow YAML per goal at
# `${MAESTRO_FLOWS_DIR:-e2e/mobile/flows}/<phase>-<goal_id>.yaml` OR any flow
# whose front-matter references `@goal G-XX`.

run_goal() {
  local goal_id="$1" phase_dir="$2" fixture_dir="${3:-}"
  local flows_dir="${MAESTRO_FLOWS_DIR:-${CONFIG_PATHS_E2E_TESTS:-e2e/mobile/flows}}"
  local phase_id
  phase_id=$(basename "$phase_dir" | sed -E 's/^([0-9.]+).*/\1/')
  local maestro_bin="${MAESTRO_BIN:-maestro}"

  if ! command -v "$maestro_bin" >/dev/null 2>&1; then
    echo "STATUS=FAILED\tEVIDENCE=maestro-cli-missing\tSURFACE=ui-mobile"
    return 1
  fi

  local flow
  flow=$(ls -1 "${flows_dir}"/*"${goal_id}"*.yaml 2>/dev/null | head -n1)
  if [ -z "$flow" ]; then
    flow=$(grep -rl "@goal ${goal_id}" "${flows_dir}" 2>/dev/null | head -n1)
  fi
  if [ -z "$flow" ]; then
    echo "STATUS=PARTIAL\tEVIDENCE=no-maestro-flow:${goal_id}\tSURFACE=ui-mobile"
    return 2
  fi

  local log="${phase_dir}/test-runners/${goal_id}-mobile.log"
  mkdir -p "$(dirname "$log")" 2>/dev/null || true
  if "$maestro_bin" test "$flow" >"$log" 2>&1; then
    echo "STATUS=READY\tEVIDENCE=${log}\tSURFACE=ui-mobile"
    return 0
  fi
  echo "STATUS=FAILED\tEVIDENCE=${log}\tSURFACE=ui-mobile"
  return 1
}
