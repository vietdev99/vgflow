# review runtime checks — dynamic (browser + device probes)

Sub-refs of `runtime-checks.md`. These sub-steps drive the live MCP
Playwright (web) or Maestro (mobile) session captured in Phase 2 to
verify visual fidelity, URL ↔ state coherence, and error-message UX.

Sub-steps in this file (in dispatch order):
- `phase2_mobile_discovery` (mobile-*) — Maestro launch + per-goal hierarchy snapshot, Haiku scanner mobile variant
- `phase2_5_visual_checks` (web) — font / overflow / responsive / z-index / D-12 wave drift / D-12e holistic / L4 SSIM
- `phase2_5_mobile_visual_checks` (mobile-*) — font render / off-screen / multi-device / z-index parsed from `*.hierarchy.json`
- `phase2_8_url_state_runtime` (web) — drive every declared `interactive_controls` and verify URL params drift
- `phase2_9_error_message_runtime` (web) — trigger negative API paths, prove toast/form errors expose the API body, not statusText

All sub-steps emit `mark_step` + `vg-orchestrator mark-step` lifecycle
calls — preserved verbatim from the pre-split file. None of the bash
heredocs span sub-step boundaries; each `<step>...</step>` block is
self-contained and copy-paste-safe.

Browser/device pre-conditions:
- web sub-steps require Phase 2 to have produced RUNTIME-MAP.json with ≥ 1 view.
- mobile sub-steps require `phase2_mobile_discovery` to have written `${PHASE_DIR}/discover/*.hierarchy.json`.

---

<step name="phase2_mobile_discovery" profile="mobile-*" mode="full">
## Phase 2 (mobile): DEVICE DISCOVERY (Maestro — equivalent of browser scan)

Fires when `profile ∈ {mobile-rn, mobile-flutter, mobile-native-ios,
mobile-native-android, mobile-hybrid}`. Web projects skip this step
because filter-steps.py resolves `mobile-*` to the 5 mobile profiles.

**⛔ Preflight gate.** Before any maestro call:

```bash
# 1. Verify wrapper present
WRAPPER="${REPO_ROOT}/.claude/scripts/maestro-mcp.py"
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
if [ -x "${REPO_ROOT}/.claude/scripts/validators/verify-phase-ui-flag.py" ]; then
  ${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/validators/verify-phase-ui-flag.py" \
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
   && [ -x "${REPO_ROOT}/.claude/scripts/verify-ui-structure.py" ]; then
  THRESHOLD=$(${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/lib/threshold-resolver.py" \
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
    ${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/verify-ui-structure.py" \
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
if [ -x "${REPO_ROOT}/.claude/scripts/verify-holistic-drift.py" ] \
   && [ -f "${PHASE_DIR}/UI-MAP.md" ]; then
  ${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/verify-holistic-drift.py" \
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
  DF_PAIRS=$(PYTHONPATH="${REPO_ROOT}/.claude/scripts/lib:${REPO_ROOT}/scripts/lib:${PYTHONPATH:-}" ${PYTHON_BIN} - "${PHASE_DIR}/RUNTIME-MAP.json" "${PHASE_DIR}" "${REPO_ROOT}" "${REPO_ROOT}/.claude/vg.config.md" <<'PY'
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
WRAPPER="${REPO_ROOT}/.claude/scripts/maestro-mcp.py"
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

<step name="phase2_8_url_state_runtime" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.8: URL state runtime probe (v2.7 Phase A)

→ `narrate_phase "Phase 2.8 — URL state runtime probe" "Click từng control + snapshot URL để verify declaration vs implementation"`

**Purpose:** verify that the static `interactive_controls` declarations
(checked at phase 2.7) match actual application behaviour. AI drives MCP
Playwright through every declared control, captures URL params before/after
each interaction, writes the result to
`${PHASE_DIR}/url-runtime-probe.json`. Validator reads that artifact and
flags coverage gaps (WARN) or declaration drift (BLOCK).

**Why:** static declarations close ~50% of URL-state bugs; runtime probe
catches the remaining drift class — declaration says `?status=...` but
the route handler ships `?state=...`, or the filter pretends to sync but
no `pushState` actually fires.

**Skip conditions:**
- No goal in TEST-GOALS.md has `interactive_controls.url_sync: true` → skip silently.
- `${RUN_ARGS}` contains `--skip-runtime` → run validator with the same flag (logs OD debt).
- Browser environment unavailable (no MCP Playwright) → invoke validator with `--skip-runtime`.

### 2.8a Drive the probe (AI agent task)

For every goal in `${PHASE_DIR}/TEST-GOALS.md` that declares
`interactive_controls.url_sync: true`:

1. Determine the goal's route from `${PHASE_DIR}/RUNTIME-MAP.json` (key
   matching the goal id) or, when the goal frontmatter carries an explicit
   `route:` field, prefer that.
2. Authenticate as `goal.actor` (default `admin`) using the standard
   review-phase auth helper.
3. Navigate to the route. Wait for the list/table/grid to be visible.
4. For every entry in the goal's `interactive_controls`:
   - **filter** — pick the first declared `values[0]`, click the filter
     control, snapshot URL, then prove visible rows and/or network response
     match the selected value. Example: `status=pending` must not show flagged,
     approved, rejected, or failed rows unless the contract explicitly says
     flagged is an orthogonal boolean.
   - **sort** — apply the first declared column, snapshot URL, then prove row
     order matches the declared direction.
   - **pagination** — click page 2 (or scroll once for `infinite-scroll`),
     snapshot URL, then prove the result window changed without duplicated
     first-page rows.
   - **search** — type a representative query, wait `debounce_ms + 100ms`,
     snapshot URL, then prove returned rows contain/match the query.
5. Also compare the observed route against `${PHASE_DIR}/CRUD-SURFACES.md`
   `platforms.web.list`: heading/description presence, declared table columns,
   row actions, empty/loading/error/unauthorized states where reachable, and
   delete confirmation if a delete action is declared.
6. Append one entry per goal to `url-runtime-probe.json`.

**Artifact schema** (`${PHASE_DIR}/url-runtime-probe.json`):

```json
{
  "generated_at": "2026-04-26T10:30:00Z",
  "goals": [
    {
      "goal_id": "G-01",
      "url": "/admin/campaigns",
      "controls": [
        {
          "kind": "filter",
          "name": "status",
          "value": "active",
          "url_before": "https://app.local:5173/admin/campaigns",
          "url_after": "https://app.local:5173/admin/campaigns?status=active",
          "url_params_after": {"status": "active"},
          "result_semantics": {
            "passed": true,
            "rows_checked": 20,
            "violations": []
          }
        }
      ]
    }
  ]
}
```

`kind` is one of `filter | sort | pagination | search`. `name` matches the
declared control name (or normalised — `page` for pagination, `search` for
search, `sort` for sort). `url_params_after` is the parsed search-param
dict. For filters, `result_semantics` is mandatory; URL-only success is not
enough because it misses the class where a Pending tab still renders Flagged
records.

### 2.8b Run validator

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"

EXTRA_FLAGS=""
if [[ "${RUN_ARGS:-}" == *"--skip-runtime"* ]] || [[ -z "${VG_BROWSER_AVAILABLE:-1}" ]]; then
  EXTRA_FLAGS="--skip-runtime"
fi

"${PYTHON_BIN}" .claude/scripts/validators/verify-url-state-runtime.py \
  --phase "${PHASE_NUMBER}" ${EXTRA_FLAGS} \
  > "${PHASE_DIR}/.tmp/url-state-runtime.json" 2>&1
URL_RUNTIME_RC=$?

if [ "${URL_RUNTIME_RC}" != "0" ]; then
  if [[ "${RUN_ARGS:-}" == *"--allow-runtime-drift"* ]]; then
    "${PYTHON_BIN}" .claude/scripts/vg-orchestrator override \
      --flag skip-url-state-runtime \
      --reason "URL state runtime drift waived for ${PHASE_NUMBER} via --allow-runtime-drift (soft debt logged)"
    echo "⚠ URL state runtime drift waived via --allow-runtime-drift"
  else
    echo "⛔ URL state runtime drift detected — see ${PHASE_DIR}/.tmp/url-state-runtime.json"
    cat "${PHASE_DIR}/.tmp/url-state-runtime.json"
    DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.url_state_runtime" \
        --phase-dir "$PHASE_DIR" \
        --input "${PHASE_DIR}/.tmp/url-state-runtime.json" \
        --out-md "${PHASE_DIR}/.tmp/url-state-runtime-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/url-state-runtime-diagnostic.md" 2>/dev/null || true
    fi
    echo ""
    echo "Fix options:"
    echo "  1. Implementation drift — fix the route handler / UI so declared url_param actually appears in URL after interaction."
    echo "  2. Declaration drift — declared url_param is wrong; update TEST-GOALS.md interactive_controls block."
    echo "  3. Override (last resort): re-run with --allow-runtime-drift (logs soft OD debt)."
    exit 2
  fi
fi
```

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_8_url_state_runtime" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_8_url_state_runtime.done"`
</step>

<step name="phase2_9_error_message_runtime" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.9: API error-message runtime lens

→ `narrate_phase "Phase 2.9 — API error-message runtime lens" "Trigger API error paths and prove toast/form errors show API body messages, not HTTP transport text"`

**Purpose:** catch the P3.2 class of bug where the backend returns a useful
domain/validation message but the frontend toast shows `Request failed with
status 403`, `statusText`, or another generic transport message.

This is a plugin/lens inside review, not a second full browser discovery pass.
Reuse the authenticated browser session and routes already discovered by
Phase 2. For each API+UI mutation or protected action that can safely fail,
drive one negative path and record API body + visible UI message.

### 2.9a Drive the probe

For API+UI phases:

1. Read `${PHASE_DIR}/INTERFACE-STANDARDS.md`, `${PHASE_DIR}/API-DOCS.md`,
   `${PHASE_DIR}/API-CONTRACTS.md`, and `${PHASE_DIR}/RUNTIME-MAP.json`.
2. Pick safe negative paths in this order:
   - validation error on create/update form
   - unauthorized/forbidden path for a role-gated action
   - domain rule error that does not mutate durable data
3. Capture the network response JSON for the failed request.
4. Capture visible toast/banner/form error text from the UI.
5. Compare using the standard message priority:
   `error.user_message -> error.message -> message -> network_fallback`.
6. Write `${PHASE_DIR}/error-message-probe.json`.

**Artifact schema**:

```json
{
  "generated_at": "2026-05-02T10:30:00Z",
  "checks": [
    {
      "goal_id": "G-01",
      "route": "/admin/billing/topup-queue",
      "action": "submit invalid filter or mutation",
      "request": {"method": "POST", "path": "/api/example"},
      "status": 400,
      "api_error": {
        "code": "VALIDATION_ERROR",
        "message": "Amount is required",
        "user_message": "Amount is required"
      },
      "api_user_message": "Amount is required",
      "visible_message": "Amount is required",
      "passed": true
    }
  ]
}
```

If a phase has API contracts and UI goals but no reachable negative path, write
the artifact with `checks: []` plus `blocked_reason`, then run the diagnostic.
Do not silently skip.

### 2.9b Run validator

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null

"${PYTHON_BIN}" .claude/scripts/validators/verify-error-message-runtime.py \
  --phase "${PHASE_NUMBER}" \
  > "${PHASE_DIR}/.tmp/error-message-runtime.json" 2>&1
ERROR_MESSAGE_RC=$?

if [ "${ERROR_MESSAGE_RC}" != "0" ]; then
  echo "⛔ API error-message runtime lens failed — see ${PHASE_DIR}/.tmp/error-message-runtime.json"
  cat "${PHASE_DIR}/.tmp/error-message-runtime.json"
  DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
  if [ -f "$DIAG_SCRIPT" ]; then
    "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
      --gate-id "review.error_message_runtime" \
      --phase-dir "$PHASE_DIR" \
      --input "${PHASE_DIR}/.tmp/error-message-runtime.json" \
      --out-md "${PHASE_DIR}/.tmp/error-message-runtime-diagnostic.md" \
      >/dev/null 2>&1 || true
    cat "${PHASE_DIR}/.tmp/error-message-runtime-diagnostic.md" 2>/dev/null || true
  fi
  echo ""
  echo "Fix options:"
  echo "  1. Backend drift — return the standard API error envelope from INTERFACE-STANDARDS.md."
  echo "  2. Frontend drift — use shared error adapter: error.user_message || error.message, never statusText/AxiosError.message."
  echo "  3. Probe gap — rerun full review with a safe negative path and write error-message-probe.json."
  exit 2
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_9_error_message_runtime" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_9_error_message_runtime.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2_9_error_message_runtime 2>/dev/null || true
```
</step>

