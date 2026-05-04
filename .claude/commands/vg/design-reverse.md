---
name: vg:design-reverse
description: "Reverse-engineer mockups from a live URL — Playwright crawls deployed app, captures PNG per route into design_assets.paths/. Use case: project already has live UI but no design files."
argument-hint: "--base-url <URL> --routes <list> [--cookies <file>] [--viewport WxH] [--full-page]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - SlashCommand
  - AskUserQuestion
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "design_reverse.started"
    - event_type: "design_reverse.completed"
---

<rules>
1. **Reverse direction** — opposite of `/vg:design-scaffold`. Scaffold creates mockups for greenfield; reverse captures existing live UI as mockups.
2. **Migration use case** — project already deployed at a URL, has working UI, but lacks Pencil/Figma/HTML source files. Reverse captures current state → enables Phase 19 L1-L6 gates retroactively.
3. **Playwright required** — uses headless Chromium; auto-fail if `node` or `playwright` missing.
4. **Authentication via cookies** — for protected apps, user provides cookies.json (Playwright format). VG cannot login programmatically.
5. **Output convention** — drops PNGs at `${design_assets.paths[0]}/{slug}.png` so `/vg:design-extract` consumes via `passthrough` handler.
6. **NOT a replacement for design files** — captured PNGs are snapshots of CURRENT UI, which may itself be drifted. Use as baseline, not gospel.
</rules>

<objective>
Capture mockup PNGs from a live URL crawl. Output:
  ${design_assets.paths[0]}/{slug}.png            ← per route
  ${design_assets.paths[0]}/.reverse-evidence/{slug}.json  ← capture metadata
</objective>

<process>

<step name="0_validate_prereqs">
## Step 0: Validate prerequisites

```bash
if ! command -v node >/dev/null 2>&1; then
  echo "⛔ node not on PATH. Install: https://nodejs.org/"
  exit 1
fi
if ! npx playwright --version >/dev/null 2>&1; then
  echo "⚠ Playwright npm package missing. Run: npm i -D playwright && npx playwright install chromium"
  AskUserQuestion: "Install now? [y/N]"
fi
```
</step>

<step name="1_parse_args">
## Step 1: Parse args

```
/vg:design-reverse --base-url https://app.example.com --routes /,/sites,/users
/vg:design-reverse --base-url https://app.example.com --routes /admin --cookies session.json
/vg:design-reverse --base-url https://app.example.com --routes / --full-page --viewport 1920x1080
```

Required:
- `--base-url <URL>` — origin without trailing slash
- `--routes <comma-sep>` — paths to crawl

Optional:
- `--cookies <file>` — Playwright cookies JSON for authenticated routes
- `--viewport WxH` (default 1440x900)
- `--full-page` — capture full scrollable page (default: viewport only)
- `--output-dir` — override `design_assets.paths[0]`
</step>

<step name="2_resolve_output_dir">
```bash
DESIGN_ASSETS_DIR=$(vg_config_get design_assets.paths "" 2>/dev/null | head -1)
DESIGN_ASSETS_DIR="${DESIGN_ASSETS_DIR:-designs}"
mkdir -p "$DESIGN_ASSETS_DIR/.reverse-evidence"
```
</step>

<step name="3_capture">
## Step 3: Run Playwright capture

```bash
${PYTHON_BIN:-python3} .claude/scripts/design-reverse.py \
  --base-url "$BASE_URL" \
  --routes "$ROUTES" \
  --output-dir "$DESIGN_ASSETS_DIR" \
  ${COOKIES:+--cookies "$COOKIES"} \
  --viewport "$VIEWPORT" \
  ${FULL_PAGE:+--full-page} \
  --report "${PHASE_DIR:-.}/.tmp/reverse-report.json"
```

PARTIAL verdict (some routes failed) → continue with WARN, list failures.
PASS → all routes captured.
BLOCK → node/Playwright missing or invalid args.
</step>

<step name="4_auto_extract">
## Step 4: Auto-fire /vg:design-extract

```
SlashCommand: /vg:design-extract --auto
```

Verify `manifest.json` updated with all captured slugs.
</step>

<step name="5_resume">
```
Reverse capture complete.
  Base URL:         $BASE_URL
  Routes captured:  <N>/<TOTAL>
  Output dir:       $DESIGN_ASSETS_DIR
  Evidence:         $DESIGN_ASSETS_DIR/.reverse-evidence/

Next: /vg:design-extract đã chạy. Pages giờ có Form A <design-ref> slug.
      Phase 19 L1-L6 gates engage on next /vg:build.
```
</step>

</process>

<example_use_cases>
1. **Migration project**: RTB has live admin SPA at https://rtb.app/ with no Figma. Run reverse on /admin, /sites, /campaigns → 3 baseline PNGs → enable Phase 19 gates.
2. **Doc-as-design**: capture a competitor's site as reference for design discussion (NOT for L1-L6 ground truth — copyright concerns).
3. **Snapshot before refactor**: capture pre-refactor state → run scaffold for new design → diff side-by-side via `/vg:accept` Section D.
</example_use_cases>

<success_criteria>
- node + Playwright available
- All requested routes captured (or PARTIAL with documented failures)
- PNG files land at design_assets.paths
- Evidence written per slug
- /vg:design-extract auto-fired and manifest.json populated
- Telemetry events emitted
</success_criteria>
