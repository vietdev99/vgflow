# shellcheck shell=bash
# VG v1.9.1 R1 — Surface runner: ui (Playwright)
# Thin orchestrator: delegates to existing /vg:test step 5d Playwright codegen
# output and invokes the generated spec for `goal_id` via the project-configured
# e2e runner. Project owns the actual spec file; this runner just orchestrates.

run_goal() {
  local goal_id="$1" phase_dir="$2" fixture_dir="${3:-}"
  local e2e_dir="${CONFIG_PATHS_E2E_TESTS:-${CONFIG_PATHS_GENERATED_TESTS:-apps/web/e2e/generated}}"
  local screenshots="${CONFIG_PATHS_SCREENSHOTS:-apps/web/e2e/screenshots}"
  local phase_id
  phase_id=$(basename "$phase_dir" | sed -E 's/^([0-9.]+).*/\1/')

  # Locate spec file: convention <phase>-<goal_id>.spec.ts or any spec tagged with goal_id
  local spec
  spec=$(ls -1 "${e2e_dir}"/*"${goal_id}"*.spec.ts 2>/dev/null | head -n1)
  if [ -z "$spec" ]; then
    spec=$(grep -rl "@goal ${goal_id}" "${e2e_dir}" 2>/dev/null | head -n1)
  fi

  if [ -z "$spec" ]; then
    echo "STATUS=PARTIAL\tEVIDENCE=no-spec-found:${goal_id}\tSURFACE=ui"
    return 2
  fi

  local test_cmd="${CONFIG_E2E_TEST_CMD:-pnpm --filter web exec playwright test}"
  local log="${phase_dir}/test-runners/${goal_id}-ui.log"
  mkdir -p "$(dirname "$log")" 2>/dev/null || true

  if eval "${test_cmd} \"${spec}\"" >"$log" 2>&1; then
    echo "STATUS=READY\tEVIDENCE=${log}\tSURFACE=ui"
    return 0
  fi
  echo "STATUS=FAILED\tEVIDENCE=${log}\tSURFACE=ui"
  return 1
}
