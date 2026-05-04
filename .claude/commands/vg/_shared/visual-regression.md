---
name: vg:_shared:visual-regression
description: Visual Regression (Shared Reference) — pixel-level diff between current screenshots and baseline per phase, baseline promotion at accept
---

# Visual Regression — Shared Helper

Pixel-level screenshot diff catches UX regressions tests don't: off-pixel layouts, CSS overrides, unintended color changes. Baseline images stored per phase; promotion happens at `/vg:accept`.

## Config (add to `.claude/vg.config.md`)

```yaml
visual_regression:
  enabled: false                                 # opt-in per project
  tool: "auto"                                   # auto | pixelmatch | pil
  threshold_pct: 2.0                             # max allowed diff per view
  baseline_dir: "apps/web/e2e/screenshots/baseline"
  current_dir: "apps/web/e2e/screenshots"
  diff_output_dir: "${PLANNING_DIR}/phases/{phase}/visual-diffs"
  report_path: "${PLANNING_DIR}/phases/{phase}/visual-diff.json"
  ignore_regions: []                             # ["dashboard:1200,0,200,100"] — x,y,w,h per view
  auto_promote_on_first_run: true                # if no baseline exists, save current as baseline
```

## API

```bash
# Called from /vg:test (step 5g or similar) or /vg:regression --visual
run_visual_regression() {
  local phase="$1"
  [ "${CONFIG_VISUAL_REGRESSION_ENABLED:-false}" = "true" ] || return 0

  local current_dir="${CONFIG_VISUAL_REGRESSION_CURRENT_DIR}/${phase}"
  local baseline_dir="${CONFIG_VISUAL_REGRESSION_BASELINE_DIR}/${phase}"
  local report="${CONFIG_VISUAL_REGRESSION_REPORT_PATH//\{phase\}/$phase}"
  local diff_dir="${CONFIG_VISUAL_REGRESSION_DIFF_OUTPUT_DIR//\{phase\}/$phase}"
  local threshold="${CONFIG_VISUAL_REGRESSION_THRESHOLD_PCT:-2.0}"

  if [ ! -d "$current_dir" ]; then
    echo "No current screenshots at ${current_dir}. E2E likely not run yet. Skipping visual regression."
    return 0
  fi

  mkdir -p "$(dirname "$report")" "$diff_dir"

  ${PYTHON_BIN:-python3} .claude/scripts/visual-diff.py compare \
    --current "$current_dir" \
    --baseline "$baseline_dir" \
    --threshold "$threshold" \
    --output "$report" \
    --diff-dir "$diff_dir"
  local rc=$?

  # Emit telemetry per failed view
  if [ -f "$report" ] && type -t emit_telemetry >/dev/null 2>&1; then
    ${PYTHON_BIN:-python3} - "$report" "$phase" <<'PY'
import json, sys, os, subprocess
rep = json.load(open(sys.argv[1]))
phase = sys.argv[2]
for v in rep.get("views", []):
  if v.get("status") == "fail":
    meta = json.dumps({"view": v["view"], "diff_pct": v["diff_pct"], "threshold_pct": rep["threshold_pct"]})
    # Shell-out to helper via bash isn't clean — use environment flag approach
    print(f"TELEMETRY_PENDING:visual_regression_fail:{phase}:visual.diff:{meta}")
PY
    # Read pending telemetry lines and emit
    # (Helper pattern — caller handles this; keep script side pure)
  fi

  # Auto-promote if no baseline existed
  if [ "$rc" -eq 0 ] && [ ! -d "$baseline_dir" ] && [ "${CONFIG_VISUAL_REGRESSION_AUTO_PROMOTE_ON_FIRST_RUN:-true}" = "true" ]; then
    echo "No baseline existed — promoting current run as initial baseline."
    ${PYTHON_BIN:-python3} .claude/scripts/visual-diff.py promote \
      --from "$current_dir" --to "$baseline_dir"
  fi

  return $rc
}

# Called from /vg:accept — promote current → baseline after UAT pass
promote_visual_baseline() {
  local phase="$1"
  [ "${CONFIG_VISUAL_REGRESSION_ENABLED:-false}" = "true" ] || return 0

  local current_dir="${CONFIG_VISUAL_REGRESSION_CURRENT_DIR}/${phase}"
  local baseline_dir="${CONFIG_VISUAL_REGRESSION_BASELINE_DIR}/${phase}"

  [ -d "$current_dir" ] || { echo "No current screenshots — skip baseline promote."; return 0; }

  ${PYTHON_BIN:-python3} .claude/scripts/visual-diff.py promote \
    --from "$current_dir" --to "$baseline_dir"

  local count
  count=$(find "$baseline_dir" -name "*.png" 2>/dev/null | wc -l)
  if type -t t >/dev/null 2>&1; then
    t "visual_baseline_promoted" "count=$count" "path=$baseline_dir"
  fi

  # Stage baseline diff for commit (user will commit as part of accept)
  git add "$baseline_dir" 2>/dev/null || true
}
```

## Integration points

### `/vg:regression --visual`
Add new flag `--visual` → run visual sweep across all accepted phases:
```bash
if [[ "$ARGUMENTS" =~ --visual ]]; then
  for phase in $(list_accepted_phases); do
    run_visual_regression "$phase"
    [ $? -ne 0 ] && FAIL_COUNT=$((FAIL_COUNT+1))
  done

  if [ "$FAIL_COUNT" -gt 0 ]; then
    echo "⛔ Visual regression: ${FAIL_COUNT} phases have visual drift."
    echo "   Investigate diffs in ${diff_output_dir}"
    echo "   If intentional: /vg:regression --visual --promote {phase}  (updates baseline)"
    exit 1
  fi
fi
```

### `/vg:test` step 5g (after all E2E passes)
```bash
if [ "${CONFIG_VISUAL_REGRESSION_ENABLED}" = "true" ]; then
  run_visual_regression "$PHASE_NUMBER"
  VISUAL_RC=$?
  [ "$VISUAL_RC" -ne 0 ] && echo "⚠ Visual diff detected — review before accept."
fi
```

### `/vg:accept` (after UAT pass, before marking accepted)
```bash
if [ "${CONFIG_VISUAL_REGRESSION_ENABLED}" = "true" ]; then
  # Interactive: if visual diff exists at current_dir, ask user
  if [ -f "${report_path}" ]; then
    FAILED=$(jq -r '.summary.failed' "$report_path" 2>/dev/null || echo 0)
    if [ "$FAILED" -gt 0 ]; then
      echo ""
      echo "Visual diff pending: ${FAILED} views differ from baseline."
      echo "  (1) Accept + promote current → baseline"
      echo "  (2) Reject — investigate diffs"
      read -p "Choice: " choice
      case "$choice" in
        1) promote_visual_baseline "$PHASE_NUMBER" ;;
        2) exit 1 ;;
      esac
    fi
  fi
fi
```

## Dependencies

Install once per project:
```bash
pip install pixelmatch pillow
```

Fallback: PIL-only grayscale diff if pixelmatch not installed (less accurate but works).

## Ignore regions (dynamic content masking)

Timestamps, live data, animations cause false positives. Mask via config:
```yaml
visual_regression:
  ignore_regions:
    - "dashboard:1200,0,200,40"       # top-right timestamp
    - "reports:0,100,100,20"          # date picker
```

Script reads these and fills rects with black before diff (equal on both sides).

## Success criteria

- First run per phase: auto-promotes baseline (no comparison possible)
- Subsequent runs: compare current vs baseline, fail if diff % > threshold
- Baseline update gated through `/vg:accept` or explicit `--promote` flag
- Per-view diff image written for visual inspection
- Telemetry event `visual_regression_fail` per failing view
- Zero cost if disabled (config gate at helper entry)
