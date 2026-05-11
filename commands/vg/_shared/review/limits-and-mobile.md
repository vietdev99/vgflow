<step name="phase2_exploration_limits" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2-limit: EXPLORATION LIMIT CHECK (R8 enforcement — v1.14.4+)

Counts actions + views + wall-time sau Phase 2 để phát hiện runaway discovery (phát hiện quét vô kiểm soát). WARN (cảnh báo) only — không block (không chặn) vì discovery đã xong. Kết quả ghi vào PIPELINE-STATE.json metrics để test/accept biết RUNTIME-MAP có thể noisy (nhiễu).

**Thresholds (ngưỡng):**
- `config.review.max_actions_per_view` — default 50
- `config.review.max_actions_total` — default 200
- `config.review.max_wall_minutes` — default 30

```bash
RUNTIME_MAP="${PHASE_DIR}/RUNTIME-MAP.json"
if [ ! -f "$RUNTIME_MAP" ]; then
  echo "⚠ RUNTIME-MAP.json chưa tồn tại — bỏ qua limit check (Phase 2 có thể skipped hoặc failed)."
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_exploration_limits" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_exploration_limits.done"
  "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator mark-step review phase2_exploration_limits 2>/dev/null || true
else
  MAX_VIEW="${CONFIG_REVIEW_MAX_ACTIONS_PER_VIEW:-50}"
  MAX_TOTAL="${CONFIG_REVIEW_MAX_ACTIONS_TOTAL:-200}"
  MAX_WALL="${CONFIG_REVIEW_MAX_WALL_MINUTES:-30}"

  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$RUNTIME_MAP" "$MAX_VIEW" "$MAX_TOTAL" "$MAX_WALL" "${PHASE_DIR}" <<'PY'
import json, sys, time
from pathlib import Path
from datetime import datetime, timezone

rm_path = Path(sys.argv[1])
max_view = int(sys.argv[2])
max_total = int(sys.argv[3])
max_wall_min = int(sys.argv[4])
phase_dir = Path(sys.argv[5])

rm = json.loads(rm_path.read_text(encoding="utf-8"))
views = rm.get("views", {}) or {}
seqs = rm.get("goal_sequences", {}) or {}

per_view_actions = {}
total_actions = 0

# Count goal_sequences steps grouped by start_view
for gid, seq in seqs.items():
    start = seq.get("start_view") or "<unknown>"
    n = len(seq.get("steps", []) or [])
    per_view_actions[start] = per_view_actions.get(start, 0) + n
    total_actions += n

# Add free_exploration actions if tracked per view
for v_url, v in views.items():
    fe = (v.get("free_exploration") or {}).get("actions_count", 0) or 0
    per_view_actions[v_url] = per_view_actions.get(v_url, 0) + fe
    total_actions += fe

# Wall time — use session-start marker mtime as proxy for discovery start
marker = phase_dir / ".step-markers" / "00_session_lifecycle.done"
wall_min = None
if marker.exists():
    wall_min = (time.time() - marker.stat().st_mtime) / 60.0

# Evaluate
warnings = []
for v, n in per_view_actions.items():
    if n > max_view:
        warnings.append({"type": "view_overflow", "view": v, "count": n, "limit": max_view})
if total_actions > max_total:
    warnings.append({"type": "total_overflow", "count": total_actions, "limit": max_total})
if wall_min is not None and wall_min > max_wall_min:
    warnings.append({"type": "wall_overflow", "minutes": round(wall_min, 1), "limit": max_wall_min})

# Report
if warnings:
    print(f"⚠ R8 exploration limits exceeded ({len(warnings)} signal):")
    for w in warnings:
        if w["type"] == "view_overflow":
            print(f"   - view '{w['view']}' → {w['count']} actions vượt limit {w['limit']}")
        elif w["type"] == "total_overflow":
            print(f"   - total → {w['count']} actions vượt limit {w['limit']}")
        elif w["type"] == "wall_overflow":
            print(f"   - wall time (thời gian) → {w['minutes']} min vượt limit {w['limit']}")
    print("")
    print("Khuyến nghị (recommendation):")
    print("  - Review RUNTIME-MAP.json: có action lặp/vô ích không")
    print("  - Giảm views scanned hoặc tắt --full-scan (sidebar suppression giúp giảm action)")
    print("  - Nếu phase lớn thật, tăng config.review.max_actions_total")
else:
    wall_txt = f", {wall_min:.1f} min" if wall_min else ""
    print(f"✓ Exploration within limits: {total_actions} actions, {len(per_view_actions)} views{wall_txt}")

# Log to PIPELINE-STATE.json regardless
state_path = phase_dir / "PIPELINE-STATE.json"
state = {}
if state_path.exists():
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        state = {}
state.setdefault("metrics", {})["review_exploration"] = {
    "total_actions": total_actions,
    "views_scanned": len(per_view_actions),
    "wall_minutes": round(wall_min, 1) if wall_min is not None else None,
    "thresholds": {"per_view": max_view, "total": max_total, "wall_min": max_wall_min},
    "warnings": warnings,
    "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
PY

  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_exploration_limits" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_exploration_limits.done"

  "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator mark-step review phase2_exploration_limits 2>/dev/null || true
fi
```

**Hành vi downstream:** nếu có warnings, step `crossai_review` cuối pipeline sẽ include "exploration noisy" flag vào context để CrossAI xem xét kỹ goals liên quan views overflow.
</step>

<step name="phase2_mobile_discovery" profile="mobile-*" mode="full">
## Phase 2 (mobile): DEVICE DISCOVERY (Maestro — equivalent of browser scan)

Fires when `profile ∈ {mobile-rn, mobile-flutter, mobile-native-ios,
mobile-native-android, mobile-hybrid}`. Web projects skip this step
because filter-steps.py resolves `mobile-*` to the 5 mobile profiles.

**⛔ Preflight gate.** Before any maestro call:

```bash
# 1. Verify wrapper present
WRAPPER="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/maestro-mcp.py"
if [ ! -f "$WRAPPER" ]; then
  echo "⛔ maestro-mcp.py missing. Run vgflow installer."
  exit 1
fi

# 2. Check tool availability per host
PREREQ=$(${PYTHON_BIN} "$WRAPPER" --json check-prereqs)
echo "$PREREQ" | jq . >/dev/null 2>&1 || { echo "$PREREQ"; echo "⛔ prereqs JSON malformed"; exit 1; }
CAN_ANDROID=$(echo "$PREREQ" | ${PYTHON_BIN} -c "import json,sys;print(json.load(sys.stdin)['capabilities']['android_flows'])")
CAN_IOS=$(echo "$PREREQ" | ${PYTHON_BIN} -c "import json,sys;print(json.load(sys.stdin)['capabilities']['ios_flows'])")
HOST_OS=$(echo "$PREREQ" | ${PYTHON_BIN} -c "import json,sys;print(json.load(sys.stdin)['host_os'])")

echo "Mobile discovery prereqs: host=${HOST_OS}, android=${CAN_ANDROID}, ios=${CAN_IOS}"
```

**Platform gating vs target_platforms:**

Config `mobile.target_platforms` is the user's intent (what the app
ships to). Host OS caps what this machine can actually discover on.
Combine:

```bash
TARGETS=$(${PYTHON_BIN} -c "
import re,pathlib
t = pathlib.Path('.claude/vg.config.md').read_text(encoding='utf-8')
m = re.search(r'^target_platforms:\s*\[([^\]]*)\]', t, re.MULTILINE)
print(m.group(1) if m else '')")

DISCOVERY_PLATFORMS=()
for plat in $(echo "$TARGETS" | tr ',' ' ' | tr -d '"' | tr -d "'"); do
  plat=$(echo "$plat" | xargs)
  case "$plat" in
    ios)
      if [ "$CAN_IOS" = "True" ]; then
        DISCOVERY_PLATFORMS+=("ios")
      else
        echo "⚠ target=ios but host cannot run iOS simulator — skipping iOS discovery"
        echo "  Use /vg:test --sandbox (cloud EAS) for iOS verification."
      fi ;;
    android)
      if [ "$CAN_ANDROID" = "True" ]; then
        DISCOVERY_PLATFORMS+=("android")
      else
        echo "⚠ target=android but adb/maestro missing — skipping Android discovery"
      fi ;;
    *)
      echo "  target '${plat}' not exercised by mobile discovery (web/macos defer to other phases)"
      ;;
  esac
done

if [ ${#DISCOVERY_PLATFORMS[@]} -eq 0 ]; then
  echo "⛔ No discoverable platforms on this host. Options:"
  echo "  (a) Install Android SDK platform-tools + Maestro (universal Linux/Mac/Win)"
  echo "  (b) Run /vg:review on a macOS host for iOS discovery"
  echo "  (c) Run /vg:test --sandbox to use cloud provider (skips local discovery)"
  exit 1
fi

echo "Will discover on: ${DISCOVERY_PLATFORMS[*]}"
```

**Discovery loop — per (platform × role):**

For each platform in `$DISCOVERY_PLATFORMS` and each role in
`config.credentials.{ENV}` (same role model as web):

```bash
# a) Launch app on the target device (name from config.mobile.devices)
if [ "$PLATFORM" = "ios" ]; then
  DEVICE=$(awk '/^\s+ios:/{f=1;next} /^\s+[a-z]+:/{f=0} f && /simulator_name:/{gsub(/["'"'"']/,"");print $2;exit}' .claude/vg.config.md)
elif [ "$PLATFORM" = "android" ]; then
  DEVICE=$(awk '/^\s+android:/{f=1;next} /^\s+[a-z]+:/{f=0} f && /emulator_name:/{gsub(/["'"'"']/,"");print $2;exit}' .claude/vg.config.md)
fi

if [ -z "$DEVICE" ]; then
  echo "⚠ Device name empty for $PLATFORM in config.mobile.devices — skipping"
  continue
fi

BUNDLE_ID=$(node -e "console.log(require('./app.json').expo?.ios?.bundleIdentifier || require('./app.json').expo?.android?.package || '')" 2>/dev/null)
[ -z "$BUNDLE_ID" ] && {
  echo "⚠ bundle_id not detectable from app.json — user must provide via MAESTRO_APP_ID env"
  BUNDLE_ID="${MAESTRO_APP_ID:-}"
}

${PYTHON_BIN} "$WRAPPER" --json launch-app --bundle-id "$BUNDLE_ID" --device "$DEVICE" > "${PHASE_DIR}/launch-${PLATFORM}.json"

# b) Discovery snapshot per goal from TEST-GOALS.md
for GOAL_ID in $(grep -oE 'G-[0-9]+' "${PHASE_DIR}/TEST-GOALS.md" | sort -u); do
  narrate_view_scan "${GOAL_ID}@${PLATFORM}" "" "" "${ROLE}" ""
  ${PYTHON_BIN} "$WRAPPER" --json discover \
    --flow "${GOAL_ID}-${PLATFORM}" \
    --device "$DEVICE" \
    --out-dir "${PHASE_DIR}/discover" \
    > "${PHASE_DIR}/discover/${GOAL_ID}-${PLATFORM}.json"

  # Output gets: { artifacts: { screenshot, hierarchy } }
  # Pass both to Haiku scanner (see step phase2_haiku_scan_mobile below)
done
```

**Haiku scanner — mobile variant:**

The scanner skill (`vg-haiku-scanner`) accepts either browser snapshot
(web path) or Maestro screenshot+hierarchy (mobile path). When mobile
artifacts are present, skill reads `hierarchy.json` (Maestro's view
hierarchy export) as element tree instead of DOM snapshot. See
`vgflow/skills/vg-haiku-scanner/SKILL.md` section "Mobile input mode".

Per goal, spawn a Haiku agent with prompt:

```
Context:
  Goal: {G-XX title + success criteria from TEST-GOALS.md}
  Platform: {ios|android}
  Screenshot: {PHASE_DIR}/discover/{G-XX}-{PLATFORM}.png
  Hierarchy: {PHASE_DIR}/discover/{G-XX}-{PLATFORM}.hierarchy.json
  Mode: mobile

Output: scan-{G-XX}-{PLATFORM}.json with findings per same schema as web
  (view_found, elements_count, issues[], goal_status).
```

**Bounded parallelism:**

Same as web — cap at 5 concurrent Haiku agents to avoid rate-limit.
Device concurrency is 1 per physical/simulator instance (maestro holds
exclusive connection), so platforms run sequentially per device but
multiple devices (iOS sim + Android emu) can run parallel.

**Artifact contract (MUST match web schema):**

Every mobile scan writes `scan-{G-XX}-{PLATFORM}.json` identical in
shape to web `scan-{G-XX}.json`. Downstream steps (`phase3_fix_loop`,
`phase4_goal_comparison`, `/vg:test` codegen) do not branch on profile
at artifact-read level — they read scan-*.json agnostic of source.

This keeps Phase 3/4 code zero-touch in the mobile rollout.
</step>

<step name="phase2_5_visual_checks" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.5: VISUAL INTEGRITY CHECK

**Config gate:** Read `visual_checks` from vg.config.md. If `visual_checks.enabled` != true → skip.

**Prereq:** Phase 2 must have produced RUNTIME-MAP.json with at least 1 view. Missing → skip.

**MCP Server:** Reuse same `$PLAYWRIGHT_SERVER` from Phase 2. Do NOT claim new lock.

```bash
VISUAL_ISSUES=()
VISUAL_SCREENSHOTS_DIR="${PHASE_DIR}/visual-checks"
mkdir -p "$VISUAL_SCREENSHOTS_DIR"
```

For each view in RUNTIME-MAP.json:

### 1. FONT CHECK (if visual_checks.font_check = true)

```
browser_evaluate:
  JavaScript: |
    await document.fonts.ready;
    const failed = [...document.fonts].filter(f => f.status !== 'loaded');
    return failed.map(f => ({ family: f.family, weight: f.weight, style: f.style, status: f.status }));
```

- Empty → PASS. Non-empty with status "error" → MAJOR. Status "unloaded" → MINOR.

### 2. OVERFLOW CHECK (if visual_checks.overflow_check = true)

```
browser_evaluate:
  JavaScript: |
    const overflowed = [];
    document.querySelectorAll('*').forEach(el => {
      const style = getComputedStyle(el);
      if (['scroll','auto'].includes(style.overflowY) || ['scroll','auto'].includes(style.overflowX)) return;
      if (style.display === 'none' || style.visibility === 'hidden') return;
      const vO = el.scrollHeight > el.clientHeight + 2 && style.overflowY === 'hidden';
      const hO = el.scrollWidth > el.clientWidth + 2 && style.overflowX === 'hidden';
      if (vO || hO) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        overflowed.push({
          selector: el.tagName.toLowerCase() + (el.id ? '#'+el.id : '') +
            (el.className && typeof el.className === 'string' ? '.'+el.className.trim().split(/\s+/).join('.') : ''),
          type: vO ? 'vertical' : 'horizontal',
          rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
        });
      }
    });
    return overflowed;
```

- Main content (rect.left > config sidebar_width) → MAJOR. Sidebar/nav → MINOR.

### 3. RESPONSIVE CHECK (per viewport in visual_checks.responsive_viewports, default [1920, 375])

```
browser_resize: { width: viewport_width, height: 900 }
browser_evaluate: "await new Promise(r => setTimeout(r, 500)); return null;"
browser_take_screenshot: { path: "${VISUAL_SCREENSHOTS_DIR}/${view_slug}-${viewport_width}w.png" }
browser_evaluate:
  JavaScript: |
    return {
      hasHorizontalScroll: document.body.scrollWidth > window.innerWidth,
      clippedElements: [...document.querySelectorAll('*')]
        .filter(el => { const r = el.getBoundingClientRect(); return r.right > window.innerWidth + 5 && r.width > 0 && r.height > 0; })
        .slice(0, 10)
        .map(el => ({ selector: el.tagName + (el.id ? '#'+el.id : ''), overflow: Math.round(el.getBoundingClientRect().right - window.innerWidth) }))
    };
```

- Desktop (>=1024) horizontal scroll → MAJOR. Mobile (<1024) → MINOR.

After all viewports: `browser_resize: { width: 1920, height: 900 }`

### 4. Z-INDEX CHECK (only views with modals in RUNTIME-MAP)

For each modal: trigger open → check topmost via `document.elementFromPoint` at center + corners → screenshot → close.
- Modal not topmost OR <75% corners visible → MAJOR.

### 5. Write visual-issues.json

```json
[{"view":"...","check_type":"font_load_failure","severity":"MAJOR","element":"Inter","viewport":null}]
```

Issues feed into Phase 3 fix loop: MAJOR = priority fix, MINOR = logged.

```
Phase 2.5 Visual Integrity:
  Views: {N}, Font: {pass}/{total}, Overflow: {pass}/{total}
  Responsive: {viewports} x {views} ({issues} issues)
  Z-index: {modals} modals ({issues} issues)
  MAJOR: {N} → Phase 3 fix loop | MINOR: {N} → logged
```

### 6. Phase 15 D-12 — Wave-scoped + Holistic Drift Gates (NEW, 2026-04-27)

After the legacy visual checks (font/overflow/responsive/z-index), run the
Phase 15 visual-fidelity gates. Threshold comes from `.fidelity-profile.lock`
written by `/vg:blueprint` step 2_fidelity_profile_lock (D-08).

**6a. D-12c — UI flag presence (cheap precondition, runs first):**

```bash
if [ -x "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/verify-phase-ui-flag.py" ]; then
  ${PYTHON_BIN} "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/verify-phase-ui-flag.py" \
      --phase "${PHASE_NUMBER}" > "${VG_TMP}/ui-flag.json" 2>&1
  UIF=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open('${VG_TMP}/ui-flag.json')).get('verdict','SKIP'))" 2>/dev/null)
  case "$UIF" in
    PASS|WARN) echo "✓ D-12c UI-flag check: $UIF" ;;
    BLOCK) echo "⛔ D-12c UI-flag check: BLOCK — phase declared UI work but UI-MAP.md/design assets missing" >&2; exit 1 ;;
    *) echo "ℹ D-12c UI-flag check: $UIF — phase has no UI declaration" ;;
  esac
fi
```

**6b. D-12b — Wave-scoped structural drift (per wave that has owned UI subtree):**

```bash
if [ -f "${PHASE_DIR}/UI-MAP.md" ] \
   && [ -x "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/verify-ui-structure.py" ]; then
  THRESHOLD=$(${PYTHON_BIN} "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/lib/threshold-resolver.py" \
      --phase "${PHASE_NUMBER}" 2>/dev/null || echo "0.85")

  # Discover waves with owned subtrees by inspecting planner UI-MAP for owner_wave_id values.
  WAVES=$(${PYTHON_BIN} -c "
import json, re
text = open('${PHASE_DIR}/UI-MAP.md', encoding='utf-8').read()
m = re.search(r'\`\`\`json\s*\n([\s\S]*?)\n\`\`\`', text)
if not m:
    raise SystemExit
data = json.loads(m.group(1))
seen = set()
def walk(n):
    if isinstance(n, dict):
        if n.get('owner_wave_id'):
            seen.add(n['owner_wave_id'])
        for c in n.get('children', []) or []:
            walk(c)
walk(data.get('root', data))
print(' '.join(sorted(seen)))
" 2>/dev/null)

  WAVE_BLOCK=0
  for WAVE_ID in $WAVES; do
    ${PYTHON_BIN} "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/verify-ui-structure.py" \
        --phase "${PHASE_NUMBER}" \
        --scope "owner-wave-id=${WAVE_ID}" \
        --threshold "${THRESHOLD}" \
        > "${VG_TMP}/drift-${WAVE_ID}.json" 2>&1 || true
    V=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open('${VG_TMP}/drift-${WAVE_ID}.json')).get('verdict','SKIP'))" 2>/dev/null)
    case "$V" in
      PASS|WARN) echo "✓ D-12b drift ${WAVE_ID}: $V (threshold=${THRESHOLD})" ;;
      BLOCK)
        echo "⛔ D-12b drift ${WAVE_ID}: BLOCK — see ${VG_TMP}/drift-${WAVE_ID}.json" >&2
        WAVE_BLOCK=1
        ;;
      *) echo "ℹ D-12b drift ${WAVE_ID}: $V" ;;
    esac
  done
  if [ "$WAVE_BLOCK" = "1" ] && [[ ! "$ARGUMENTS" =~ --allow-wave-drift ]]; then
    echo "  Override: --allow-wave-drift (logs override-debt as kind=wave-drift-relaxed)" >&2
    exit 1
  fi
fi
```

**6c. D-12e — Holistic phase-wide drift (runs once at phase end):**

```bash
if [ -x "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/verify-holistic-drift.py" ] \
   && [ -f "${PHASE_DIR}/UI-MAP.md" ]; then
  ${PYTHON_BIN} "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/verify-holistic-drift.py" \
      --phase "${PHASE_NUMBER}" \
      > "${VG_TMP}/holistic-drift.json" 2>&1 || true
  HV=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open('${VG_TMP}/holistic-drift.json')).get('verdict','SKIP'))" 2>/dev/null)
  case "$HV" in
    PASS|WARN) echo "✓ D-12e holistic drift: $HV" ;;
    BLOCK)
      echo "⛔ D-12e holistic drift: BLOCK — see ${VG_TMP}/holistic-drift.json" >&2
      echo "  Wave gates passed but phase-wide composition drifted (e.g., layout fight between waves)." >&2
      echo "  Override: --allow-holistic-drift" >&2
      if [[ ! "$ARGUMENTS" =~ --allow-holistic-drift ]]; then exit 1; fi
      ;;
    *) echo "ℹ D-12e holistic drift: $HV" ;;
  esac
fi
```

**6e. L4 — Design-fidelity SSIM gate (NEW, 2026-04-28):**

Final safety net for the 4-layer pixel pipeline. L1 (executor reads PNG) +
L2 (LAYOUT-FINGERPRINT) + L3 (build-time render vs baseline) all run
during /vg:build. This gate runs during /vg:review using the live browser
session — if any of the upstream layers were skipped or overridden, this
catches the drift before it leaves the phase. **Severity = BLOCK** by
design; override `--allow-design-drift` consumes a rationalization-guard
slot and logs override-debt.

```bash
DF_THRESHOLD="$(vg_config_get visual_checks.design_fidelity_threshold_pct 5.0 2>/dev/null || echo 5.0)"

if [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ]; then
  DF_PAIRS=$(PYTHONPATH="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/lib:${REPO_ROOT}/scripts/lib:${PYTHONPATH:-}" ${PYTHON_BIN} - "${PHASE_DIR}/RUNTIME-MAP.json" "${PHASE_DIR}" "${REPO_ROOT}" "${REPO_ROOT}/.claude/vg.config.md" <<'PY'
import json, sys
from pathlib import Path
from design_ref_resolver import first_screenshot, parse_config_file, resolve_design_assets

rt = json.load(open(sys.argv[1], encoding="utf-8"))
phase_dir = Path(sys.argv[2])
repo_root = Path(sys.argv[3])
config = parse_config_file(Path(sys.argv[4]))
views = rt.get("views") or rt.get("routes") or []
for v in views:
    slug = v.get("design_ref") or v.get("design_slug") or v.get("slug")
    if not slug:
        continue
    png = first_screenshot(resolve_design_assets(slug, repo_root=repo_root, phase_dir=phase_dir, config=config))
    if not png:
        continue
    label = v.get("label") or v.get("path") or v.get("url") or slug
    url = v.get("url") or v.get("path") or "/"
    print(f"{slug}\t{url}\t{png}\t{label}")
PY
  )

  DF_ISSUES=()
  DF_CHECKS=0
  if [ -n "$DF_PAIRS" ]; then
    mkdir -p "${PHASE_DIR}/visual-fidelity" 2>/dev/null
    while IFS=$'\t' read -r DF_SLUG DF_URL DF_BASELINE DF_LABEL; do
      [ -z "$DF_SLUG" ] && continue
      DF_CHECKS=$((DF_CHECKS + 1))
      DF_CURRENT="${PHASE_DIR}/visual-fidelity/${DF_SLUG}.current.png"
      DF_DIFF="${PHASE_DIR}/visual-fidelity/${DF_SLUG}.diff.png"

      # Reuse the Phase 2 browser session — already navigated + logged in.
      # MCP step (orchestrator runs in-context):
      #   browser_navigate { url: $DF_URL }
      #   browser_evaluate "await new Promise(r => setTimeout(r, 500))"
      #   browser_take_screenshot { path: $DF_CURRENT }
      # If an MCP step is unavailable, the diff falls back to SKIP and the
      # next phase 2.5 sweep will pick the slug up.

      if [ ! -f "$DF_CURRENT" ]; then
        echo "ℹ L4 fidelity ${DF_SLUG}: SKIP — current screenshot not produced (MCP browser step missing)"
        continue
      fi

      DF_PCT=$(${PYTHON_BIN} - "$DF_CURRENT" "$DF_BASELINE" "$DF_DIFF" <<'PY'
import sys
try:
    from PIL import Image
    from pixelmatch.contrib.PIL import pixelmatch
except ImportError:
    print("-1")
    sys.exit(0)
a = Image.open(sys.argv[1]).convert("RGBA")
b = Image.open(sys.argv[2]).convert("RGBA")
if a.size != b.size:
    b = b.resize(a.size)
diff = Image.new("RGBA", a.size)
mismatch = pixelmatch(a, b, diff, threshold=0.1)
total = a.size[0] * a.size[1]
pct = (mismatch / total) * 100 if total else 0
diff.save(sys.argv[3])
print(f"{pct:.3f}")
PY
      )

      if [ "$DF_PCT" = "-1" ]; then
        echo "ℹ L4 fidelity ${DF_SLUG}: SKIP — pixelmatch+PIL not installed"
        continue
      fi

      DF_VERDICT=$(${PYTHON_BIN} -c "import sys; print('PASS' if float(sys.argv[1]) <= float(sys.argv[2]) else 'BLOCK')" "$DF_PCT" "$DF_THRESHOLD")
      cat > "${PHASE_DIR}/visual-fidelity/${DF_SLUG}.json" <<JSON
{"slug":"${DF_SLUG}","url":"${DF_URL}","label":"${DF_LABEL}","diff_pct":${DF_PCT},"threshold_pct":${DF_THRESHOLD},"verdict":"${DF_VERDICT}","current":"${DF_CURRENT}","baseline":"${DF_BASELINE}","diff":"${DF_DIFF}"}
JSON
      if [ "$DF_VERDICT" = "BLOCK" ]; then
        DF_ISSUES+=("${DF_SLUG} (${DF_PCT}% > ${DF_THRESHOLD}%)")
        echo "⛔ L4 fidelity ${DF_SLUG}: ${DF_PCT}% drift > ${DF_THRESHOLD}% → see ${DF_DIFF}"
      else
        echo "✓ L4 fidelity ${DF_SLUG}: ${DF_PCT}% (≤ ${DF_THRESHOLD}%)"
      fi
    done <<< "$DF_PAIRS"
  fi

  if [ ${#DF_ISSUES[@]} -gt 0 ]; then
    echo "⛔ L4 design-fidelity gate: ${#DF_ISSUES[@]} view(s) drift past ${DF_THRESHOLD}%:"
    for i in "${DF_ISSUES[@]}"; do echo "    - $i"; done
    echo "   Diffs: ${PHASE_DIR}/visual-fidelity/*.diff.png"
    echo "   Override: --allow-design-drift (rationalization-guard + override-debt)"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "review_l4_fidelity" "${PHASE_NUMBER}" "review.phase2_5" \
        "design_fidelity" "BLOCK" "{\"count\":${#DF_ISSUES[@]},\"threshold\":${DF_THRESHOLD}}"
    fi
    if [[ ! "$ARGUMENTS" =~ --allow-design-drift ]]; then exit 1; fi
    echo "⚠ --allow-design-drift set — drift accepted; override-debt logged."
  elif [ "${DF_CHECKS:-0}" -gt 0 ]; then
    echo "✓ L4 design-fidelity gate: ${DF_CHECKS} view(s) within ${DF_THRESHOLD}% of baseline"
  fi
fi
```

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_5_visual_checks" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_5_visual_checks.done"`
</step>

<step name="phase2_5_mobile_visual_checks" profile="mobile-*" mode="full">
## Phase 2.5 (mobile): VISUAL INTEGRITY CHECK

**Config gate:**
Read `visual_checks.enabled` from vg.config.md. If not true → skip with message
and jump to Phase 3.

**Prereq:** phase2_mobile_discovery produced screenshots in `${PHASE_DIR}/discover/`.
Missing → skip + warn: "No mobile discovery artifacts — visual checks require device snapshot first."

**Why this step differs from web:** mobile devices have fixed viewports per
model (an iPhone 15 Pro IS its viewport). There's no browser resize loop.
Instead we capture multi-device if user listed multiple emulators/simulators
in `config.mobile.devices.<plat>[]`, or re-check the already-captured
screenshots against per-platform sanity rules.

```bash
VISUAL_ISSUES=()
VIS_DIR="${PHASE_DIR}/visual-checks"
mkdir -p "$VIS_DIR"
WRAPPER="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/maestro-mcp.py"
```

### Check 1: Font / text rendering (per captured screenshot)

Parse each `${PHASE_DIR}/discover/*.hierarchy.json`. For every text node
with non-empty `text`, verify corresponding element has `frame.height > 0`
(i.e. rendered, not invisible font). Missing → MINOR (font not loaded or
style override hiding text).

```bash
for HIER in "${PHASE_DIR}"/discover/*.hierarchy.json; do
  [ -f "$HIER" ] || continue
  MISSING=$(${PYTHON_BIN} - "$HIER" <<'PY'
import json, sys
from pathlib import Path
h = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
def walk(node, out):
    if isinstance(node, dict):
        text = (node.get('text') or node.get('attributes', {}).get('text') or '').strip()
        frame = node.get('frame') or node.get('bounds') or {}
        hgt = frame.get('height') if isinstance(frame, dict) else None
        if text and isinstance(hgt, (int, float)) and hgt <= 0:
            out.append({'text': text[:40], 'height': hgt})
        for c in (node.get('children') or []):
            walk(c, out)
    elif isinstance(node, list):
        for c in node:
            walk(c, out)
out = []
walk(h, out)
print(json.dumps(out))
PY
  )
  echo "$MISSING" > "$VIS_DIR/font-missing-$(basename "$HIER" .hierarchy.json).json"
done
```

Severity: any text-with-zero-height = MINOR (log in VISUAL_ISSUES).

### Check 2: Off-screen content (mobile equivalent of overflow check)

Parse frame coordinates. For each element with `frame.y + frame.height > device_height`
or `frame.x + frame.width > device_width`, flag as MAJOR if it's in main
content area, MINOR if near navigation bar.

Device dimensions come from screenshot metadata (PIL image size) — no
hardcoded per-device map needed.

### Check 3: Multi-device sanity (if config lists multiple emulator/simulator names)

If `config.mobile.devices.android.emulator_name` lists N values (as array
rather than single string), capture a screenshot on each and compare:
- Do text labels fit without truncation (`...` or ellipsis heuristic)?
- Do tap targets have ≥44pt minimum size (iOS HIG) or ≥48dp (Material)?

Single-device setups skip this check.

### Check 4: Z-index / modal occlusion

If any hierarchy shows a node with `role=Modal` or `accessibilityTrait=modal`,
verify its frame covers the center of the screen AND no sibling has higher
z-order. Maestro hierarchy exposes sibling order via array index; elements
later in array are on top.

### Reporting

```bash
cat > "${PHASE_DIR}/visual-issues.json" <<EOF
{
  "platform_coverage": $(ls "${PHASE_DIR}"/discover/*.hierarchy.json 2>/dev/null | wc -l),
  "issues": [ /* MINOR/MAJOR items collected */ ],
  "summary": {"major": N, "minor": N}
}
EOF
```

MAJOR → handled in Phase 3 fix loop. MINOR → logged only.

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_5_mobile_visual_checks" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_5_mobile_visual_checks.done"`
</step>
