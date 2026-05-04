# Review Phase 2.5: Visual Integrity Check — STAGING FILE

> **Purpose:** This file contains the `<step>` block to be manually inserted into `review.md`
> between `phase2_browser_discovery` and `phase3_fix_loop`. Also includes the vg.config.md
> extension YAML block.
>
> **Insert location in review.md:** After `</step>` closing of `phase2_browser_discovery`,
> before `<step name="phase3_fix_loop">`.

---

## Step block (copy into review.md)

```xml
<step name="phase2_5_visual_checks" profile="web-fullstack,web-frontend-only">
## Phase 2.5: VISUAL INTEGRITY CHECK

**Config gate:**
Read `visual_checks` from vg.config.md. If `visual_checks.enabled` != true → skip entire step.
Print: "Phase 2.5 skipped — visual_checks.enabled is false in vg.config.md"
Jump to Phase 3.

**Prereq:** Phase 2 browser discovery must have produced RUNTIME-MAP.json with at least 1 view.
Missing → skip with warning: "No RUNTIME-MAP.json — visual checks require browser discovery first."

**MCP Server:** Reuse the same `$PLAYWRIGHT_SERVER` claimed in Phase 2. Do NOT claim a new lock.

```bash
VISUAL_ISSUES=()
VISUAL_SCREENSHOTS_DIR="${PHASE_DIR}/visual-checks"
mkdir -p "$VISUAL_SCREENSHOTS_DIR"
```

For each view in RUNTIME-MAP.json (reuse existing browser session — already logged in per role):

### 1. FONT CHECK (if visual_checks.font_check = true)

Navigate to view URL. Wait for page load. Then:

```
browser_evaluate:
  JavaScript: |
    await document.fonts.ready;
    const failed = [...document.fonts].filter(f => f.status !== 'loaded');
    return failed.map(f => ({ family: f.family, weight: f.weight, style: f.style, status: f.status }));
```

**Evaluation:**
- Empty array → PASS (all fonts loaded)
- Non-empty → for each failed font:
  - `status === "error"` → issue: `{view, "font_load_failure", "MAJOR", font.family}`
  - `status === "unloaded"` → issue: `{view, "font_not_triggered", "MINOR", font.family}`

### 1.5. TEXT ENCODING CHECK (always ON — no config toggle, too critical to skip)

Detect garbled text (mojibake) — Vietnamese/CJK/Cyrillic showing as `???`, `â€™`, `Ã©`, replacement chars.
Root causes: missing `<meta charset="utf-8">`, API response without `Content-Type: charset=utf-8`, 
database storing wrong encoding, i18n JSON file saved as latin-1.

```
browser_evaluate:
  JavaScript: |
    // 1. Check <meta charset> exists
    const metaCharset = document.querySelector('meta[charset]');
    const metaContentType = document.querySelector('meta[http-equiv="Content-Type"]');
    const hasCharset = !!metaCharset || (metaContentType && metaContentType.content.includes('utf-8'));

    // 2. Scan visible text nodes for encoding artifacts
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const suspiciousPatterns = /[\uFFFD]|[\u00C0-\u00FF]{3,}|[\?]{3,}|â€|Ã[©¨¹»]|\\u[0-9a-f]{4}/gi;
    const garbled = [];
    let node;
    let checked = 0;
    while ((node = walker.nextNode()) && checked < 500) {
      const text = node.textContent.trim();
      if (!text || text.length < 2) continue;
      checked++;
      const match = text.match(suspiciousPatterns);
      if (match) {
        const parent = node.parentElement;
        const selector = parent ? parent.tagName.toLowerCase() +
          (parent.id ? '#' + parent.id : '') +
          (parent.className && typeof parent.className === 'string'
            ? '.' + parent.className.trim().split(/\s+/).slice(0,2).join('.') : '') : 'unknown';
        garbled.push({
          text: text.substring(0, 80),
          pattern: match[0],
          selector,
          rect: parent ? parent.getBoundingClientRect() : null
        });
      }
    }

    return { hasCharset, garbledCount: garbled.length, garbled: garbled.slice(0, 10), checkedNodes: checked };
```

**Evaluation:**
- `hasCharset === false` → issue: `{view, "missing_charset_meta", "MAJOR", "Add <meta charset=\"utf-8\"> to <head>"}`
- `garbledCount > 0` → for each garbled entry:
  - issue: `{view, "text_encoding_garbled", "CRITICAL", garbled.text, garbled.selector}`
  - Take screenshot of the garbled element region for evidence
  - **CRITICAL severity** because user sees broken text — worse than styling issues

**Common fixes (include in issue description for fix loop):**
- Missing `<meta charset="utf-8">` in HTML `<head>` → add it
- API response missing `charset=utf-8` → add `reply.header('Content-Type', 'application/json; charset=utf-8')`
- i18n JSON file wrong encoding → re-save as UTF-8 without BOM
- Database text column → verify connection string has `?charset=utf8mb4` (MySQL) or UTF-8 locale (Mongo default OK)

### 2. OVERFLOW CHECK (if visual_checks.overflow_check = true)

```
browser_evaluate:
  JavaScript: |
    const overflowed = [];
    document.querySelectorAll('*').forEach(el => {
      const style = getComputedStyle(el);
      const overflowY = style.overflowY;
      const overflowX = style.overflowX;
      // Skip elements with intentional scroll
      if (['scroll', 'auto'].includes(overflowY) || ['scroll', 'auto'].includes(overflowX)) return;
      // Skip hidden elements
      if (style.display === 'none' || style.visibility === 'hidden') return;
      // Check vertical overflow (2px tolerance for sub-pixel rendering)
      const vOverflow = el.scrollHeight > el.clientHeight + 2 && overflowY === 'hidden';
      // Check horizontal overflow
      const hOverflow = el.scrollWidth > el.clientWidth + 2 && overflowX === 'hidden';
      if (vOverflow || hOverflow) {
        const rect = el.getBoundingClientRect();
        // Skip off-screen elements
        if (rect.width === 0 || rect.height === 0) return;
        overflowed.push({
          selector: el.tagName.toLowerCase() +
            (el.id ? '#' + el.id : '') +
            (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : ''),
          type: vOverflow ? 'vertical' : 'horizontal',
          scrollH: el.scrollHeight,
          clientH: el.clientHeight,
          scrollW: el.scrollWidth,
          clientW: el.clientWidth,
          rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
        });
      }
    });
    return overflowed;
```

**Evaluation:**
- Empty → PASS
- Non-empty → for each element:
  - Located in main content area (rect.left > sidebar_width AND rect.top > header_height) → `"MAJOR"`
  - Located in sidebar/footer/nav → `"MINOR"`
  - Issue: `{view, "overflow_clipping", severity, element.selector}`

### 3. RESPONSIVE CHECK (per viewport in visual_checks.responsive_viewports)

Default viewports if not configured: `[1920, 1440, 1024, 768, 375]`

For each viewport width:

```
browser_resize: { width: viewport_width, height: 900 }
# Wait for layout reflow
browser_evaluate: "await new Promise(r => setTimeout(r, 500)); return null;"
browser_take_screenshot: { path: "${VISUAL_SCREENSHOTS_DIR}/${view_slug}-${viewport_width}w.png" }
```

Then check for horizontal scroll:

```
browser_evaluate:
  JavaScript: |
    return {
      bodyScrollWidth: document.body.scrollWidth,
      windowInnerWidth: window.innerWidth,
      hasHorizontalScroll: document.body.scrollWidth > window.innerWidth,
      clippedElements: (() => {
        const clipped = [];
        document.querySelectorAll('*').forEach(el => {
          const rect = el.getBoundingClientRect();
          if (rect.right > window.innerWidth + 5 && rect.width > 0 && rect.height > 0) {
            clipped.push({
              selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''),
              right: Math.round(rect.right),
              overflow: Math.round(rect.right - window.innerWidth)
            });
          }
        });
        return clipped.slice(0, 10); // limit to first 10
      })()
    };
```

**Evaluation:**
- `hasHorizontalScroll === false` AND `clippedElements.length === 0` → PASS
- `hasHorizontalScroll === true`:
  - viewport >= 1024 (desktop) → `{view, "horizontal_scroll", "MAJOR", viewport_width}`
  - viewport < 1024 (mobile/tablet) → `{view, "horizontal_scroll", "MINOR", viewport_width}`
- `clippedElements.length > 0` → `{view, "element_clipped_beyond_viewport", "MINOR", clippedElements[0].selector, viewport_width}`

After all viewports checked, reset to default:
```
browser_resize: { width: 1920, height: 900 }
```

### 4. Z-INDEX CHECK (only for views with modals in RUNTIME-MAP)

Filter RUNTIME-MAP.json → views where `modals` array is non-empty.

For each modal in the view:

```
# Trigger the modal open (use the trigger action recorded in RUNTIME-MAP)
browser_click: { selector: modal.trigger_selector }
browser_evaluate: "await new Promise(r => setTimeout(r, 300)); return null;"

# Check modal is topmost visible
browser_evaluate:
  JavaScript: |
    const modal = document.querySelector('${modal.selector}');
    if (!modal) return { found: false };
    const rect = modal.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const topElement = document.elementFromPoint(centerX, centerY);
    const isTopmost = modal.contains(topElement);
    // Also check modal corners
    const corners = [
      [rect.left + 10, rect.top + 10],
      [rect.right - 10, rect.top + 10],
      [rect.left + 10, rect.bottom - 10],
      [rect.right - 10, rect.bottom - 10]
    ].filter(([x, y]) => x > 0 && y > 0 && x < window.innerWidth && y < window.innerHeight);
    const cornersVisible = corners.filter(([x, y]) => {
      const el = document.elementFromPoint(x, y);
      return modal.contains(el);
    });
    return {
      found: true,
      isTopmost,
      cornersVisible: cornersVisible.length,
      cornersTotal: corners.length,
      zIndex: getComputedStyle(modal).zIndex,
      rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
    };
```

```
browser_take_screenshot: { path: "${VISUAL_SCREENSHOTS_DIR}/${view_slug}-modal-${modal_index}.png" }
```

Close modal (Escape key or close button).

**Evaluation:**
- `found === false` → `{view, "modal_not_found", "MAJOR", modal.selector}`
- `isTopmost === false` OR `cornersVisible < cornersTotal * 0.75` → `{view, "z_index_stacking", "MAJOR", modal.selector}`
- All corners visible AND topmost → PASS

### 5. Write visual-issues.json

```bash
# Write collected issues to JSON
cat > "${PHASE_DIR}/visual-issues.json" << 'JSONEOF'
${JSON.stringify(VISUAL_ISSUES, null, 2)}
JSONEOF
```

Output format:
```json
[
  {
    "view": "dashboard",
    "check_type": "font_load_failure",
    "severity": "MAJOR",
    "element": "Inter (400 normal)",
    "screenshot_path": "visual-checks/dashboard-font-error.png",
    "viewport": null
  },
  {
    "view": "campaigns",
    "check_type": "horizontal_scroll",
    "severity": "MINOR",
    "element": null,
    "screenshot_path": "visual-checks/campaigns-375w.png",
    "viewport": 375
  },
  {
    "view": "settings",
    "check_type": "z_index_stacking",
    "severity": "MAJOR",
    "element": "#edit-profile-modal",
    "screenshot_path": "visual-checks/settings-modal-0.png",
    "viewport": null
  }
]
```

### Severity classification (feeds into Phase 3 fix loop triage):

| Check Type | Condition | Severity |
|---|---|---|
| `font_load_failure` | font status = "error" | MAJOR |
| `font_not_triggered` | font status = "unloaded" | MINOR |
| `overflow_clipping` | main content area | MAJOR |
| `overflow_clipping` | sidebar/footer/nav | MINOR |
| `horizontal_scroll` | desktop viewport (>= 1024) | MAJOR |
| `horizontal_scroll` | mobile/tablet viewport (< 1024) | MINOR |
| `element_clipped_beyond_viewport` | any | MINOR |
| `z_index_stacking` | modal partially hidden | MAJOR |
| `modal_not_found` | modal selector invalid | MAJOR |

### Summary display:

```
Phase 2.5 Visual Integrity:
  Views checked: {N}
  Font checks: {pass}/{total} ({fail_count} issues)
  Overflow checks: {pass}/{total} ({fail_count} issues)
  Responsive checks: {viewports_count} viewports x {views_count} views ({fail_count} issues)
  Z-index checks: {modals_checked} modals ({fail_count} issues)
  
  MAJOR issues: {count} → will enter Phase 3 fix loop
  MINOR issues: {count} → logged, fix if time permits
  
  visual-issues.json written ({total_issues} issues)
  Screenshots: ${VISUAL_SCREENSHOTS_DIR}/ ({screenshot_count} files)
```

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_5_visual_checks" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_5_visual_checks.done"`
</step>
```

---

## vg.config.md extension (add to config file)

```yaml
# === Visual Integrity Checks (Phase 2.5 in /vg:review) ===
# Automated checks for font loading, overflow clipping, responsive layout, z-index stacking.
# Runs after browser discovery (Phase 2), before fix loop (Phase 3).
visual_checks:
  enabled: true                          # false = skip Phase 2.5 entirely
  font_check: true                       # check document.fonts.ready for failed loads
  overflow_check: true                   # find elements with hidden overflow clipping
  responsive_viewports: [1920, 1440, 1024, 768, 375]   # viewport widths to test
  z_index_check: true                    # verify modals are topmost when opened
  # Geometry thresholds for overflow classification
  sidebar_width: 256                     # pixels — elements left of this = sidebar (MINOR)
  header_height: 64                      # pixels — elements above this = header (MINOR)
```
