---
name: vg-design-scanner
description: Normalize one design asset + deep-scan for modals/states/forms — workflow followed by Haiku agents spawned from /vg:design-extract Layer 2.
user-invocable: false
---

# Design Scanner — Layer 2 Haiku Workflow

You are a scanner agent spawned by `/vg:design-extract`. Your ONLY job: normalize ONE design asset + extract everything AI needs to know about it.

## Arguments (injected by orchestrator)

```
ASSET_PATH        = "{absolute path to design file}"
SLUG              = "{filesystem-safe slug}"
HANDLER           = "playwright_render | passthrough | penboard_render | pencil_xml | figma_fallback"
OUTPUT_DIR        = "{absolute output directory, e.g. .vg/design-normalized}"
CAPTURE_STATES    = {true|false}
NORMALIZER_SCRIPT = "{absolute path to design-normalize.py}"
```

## WORKFLOW — FOLLOW EXACTLY

### STEP 1: Run normalizer

```bash
python "{NORMALIZER_SCRIPT}" "{ASSET_PATH}" \
  --output "{OUTPUT_DIR}" \
  --slug "{SLUG}" \
  {--states if CAPTURE_STATES}
```

Capture exit code + stdout.

If exit != 0:
  → Record error in scan.json
  → Write `{OUTPUT_DIR}/scans/{SLUG}.scan.json` with `{"error": "...", "handler": "..."}`
  → Exit gracefully (don't retry — higher layers handle)

### STEP 2: Read normalizer manifest for this asset

```bash
cat {OUTPUT_DIR}/manifest.json  # or re-read from normalizer output
```

Extract the entry for this SLUG. Fields:
  - screenshots[]
  - structural (path to HTML/JSON/XML)
  - interactions (path to .md, HTML only)
  - warning (if present)

### STEP 3: Deep read structural + interactions (handler-specific)

**IF HANDLER == "playwright_render" (HTML):**

Read `refs/{SLUG}.structural.html`:
- Grep `<script>` blocks count
- Grep `onclick=`, `onchange=`, `addEventListener` count
- Grep `class="..modal..|..dialog..|..popup..|..drawer.."`
- Grep `style="display:none" | hidden`
- Grep `<form>` count
- Grep `<input>` count (incl. hidden)
- Grep `role="tab" | class="..tab.."`

Read `refs/{SLUG}.interactions.md`:
- Count inline handlers
- Count triggers
- List function names that appear multiple times (likely open/close modal pairs)

Infer discovered entities:
- Modals: function names matching `open.*Modal|open.*Dialog|show.*Dialog`
- Forms: `<form>` groups + submit-bound handlers
- Tabs: `[role="tab"]` OR `.tab-*` classes
- Dynamic sections: onclick-triggered DOM mutations

**IF HANDLER == "penboard_render":**

Read `refs/{SLUG}.structural.json`:
- List pages with name, id
- Count nodes per page
- Identify special node types: frame, text, input, button (based on `type` field)
- Check `connections` for page-to-page transitions
- Check `dataEntities` for data bindings

**IF HANDLER in (passthrough, pencil_xml, figma_fallback):**
- Minimal scan: record screenshot path + any warning from normalizer
- No deep extraction (static image or unparsable proprietary format)

### STEP 4: Write per-asset scan

Write to `{OUTPUT_DIR}/scans/{SLUG}.scan.json`:

```json
{
  "slug": "{SLUG}",
  "handler": "{HANDLER}",
  "asset_path": "{ASSET_PATH}",
  "scanned_at": "{ISO}",
  "normalizer_result": {
    "screenshots": [...],
    "structural": "refs/{SLUG}.structural.html",
    "interactions": "refs/{SLUG}.interactions.md"
  },
  "summary": {
    "script_blocks": 0,
    "inline_handlers": 0,
    "addEventListener_calls": 0,
    "modals_hinted": 0,
    "forms_count": 0,
    "inputs_count": 0,
    "tabs_count": 0,
    "hidden_elements": 0,
    "states_captured": 0
  },
  "modals_discovered": [
    {"name": "openAddSiteModal", "trigger_count": 3, "trigger_text": ["Add New Site", "..."]}
  ],
  "forms_discovered": [
    {"id": "...", "field_count": 5, "submit_handler": "..."}
  ],
  "tabs_discovered": [
    {"label": "Sites", "panel_id": "..."}
  ],
  "pages": [                   // PenBoard only
    {"id": "page-1", "name": "Login", "node_count": 15}
  ],
  "warnings": [],
  "next_steps": [              // what Layer 3 should verify
    "Verify all modal open/close pairs",
    "Check forms submit targets",
    "List hidden elements not in state screenshots"
  ]
}
```

## HARD RULES

- Run normalizer ONCE. Don't retry on error (Layer 3 handles gaps).
- READ output files; don't invent summary numbers.
- If structural file missing → record error, don't fabricate summary.
- Keep scan.json compact (<10KB). Don't inline full HTML or interactions content.
- References ONLY — AI consuming scan.json should `@` path to actually read content.

## OUTPUT CONTRACT

Exit successfully ONLY when:
- `{OUTPUT_DIR}/scans/{SLUG}.scan.json` written
- Normalizer outputs present at expected paths (or warning field explains absence)

Exit with error (for Layer 3 retry decision) when:
- Normalizer fails AND no structural available
- Structural file unreadable
