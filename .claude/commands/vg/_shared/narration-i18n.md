---
name: vg:_shared:narration-i18n
description: Narration i18n (Shared Reference) — config-driven locale lookup for user-facing strings, fallback to "vi" default
---

# Narration i18n — Shared Helper

Every user-facing narration/echo string that workflow emits goes through `t()` lookup. Keeps workflow globally portable — VN default, EN fallback, future locales additive.

## Config (add to `.claude/vg.config.md`)

```yaml
narration:
  locale: "vi"                   # primary locale: vi | en | ja | ...
  fallback_locale: "en"          # if key missing in primary
  string_table_path: ".claude/commands/vg/_shared/narration-strings.yaml"
```

## String table (new file `.claude/commands/vg/_shared/narration-strings.yaml`)

```yaml
# Format: <key>: { <locale>: "<template with {placeholders}>" }
# Workflow calls t(key, {placeholders...}) → renders in config.narration.locale
# Add keys as needed; EN strings required, VN/others optional (fall back)

gate_blocked_intermediate:
  vi: "⛔ Review cannot exit — {count} intermediate goals (NOT_SCANNED/FAILED). Resolve trước khi exit."
  en: "⛔ Review cannot exit — {count} intermediate goals (NOT_SCANNED/FAILED). Resolve before exit."

gate_blocked_nottest:
  vi: "⛔ Test chỉ replay goals có status=READY + goal_sequence.steps[] ≥ 1. {count} intermediate blocked."
  en: "⛔ Test only replays goals with status=READY + goal_sequence.steps[] ≥ 1. {count} intermediate blocked."

override_logged:
  vi: "⚠ Override debt logged: {id} ({severity}). Review: {path}"
  en: "⚠ Override debt logged: {id} ({severity}). Review: {path}"

goal_start:
  vi: "🎯 Goal {goal_id}: {name}"
  en: "🎯 Goal {goal_id}: {name}"

goal_step:
  vi: "  → {step_num}/{total} {action}"
  en: "  → {step_num}/{total} {action}"

goal_end_ready:
  vi: "✅ {goal_id} READY ({steps} steps)"
  en: "✅ {goal_id} READY ({steps} steps)"

goal_end_blocked:
  vi: "❌ {goal_id} BLOCKED — {reason}"
  en: "❌ {goal_id} BLOCKED — {reason}"

phase_header:
  vi: "━━━ {phase_name} ━━━"
  en: "━━━ {phase_name} ━━━"

view_scan_start:
  vi: "🔍 Scanning view: {view_name}"
  en: "🔍 Scanning view: {view_name}"

view_scan_done:
  vi: "   ✓ {view_name} — {findings} findings"
  en: "   ✓ {view_name} — {findings} findings"

fix_routed_inline:
  vi: "🔧 [inline] {severity} — {bug}"
  en: "🔧 [inline] {severity} — {bug}"

fix_routed_spawn:
  vi: "🔧 [spawn {model}] {severity} — {bug}"
  en: "🔧 [spawn {model}] {severity} — {bug}"

fix_routed_escalated:
  vi: "🚨 [escalated] {severity} — {bug} → REVIEW-FEEDBACK.md"
  en: "🚨 [escalated] {severity} — {bug} → REVIEW-FEEDBACK.md"

debt_open_warning:
  vi: "⚠ Debt: {open} OPEN · {escalated} ESCALATED — see {path}"
  en: "⚠ Debt: {open} OPEN · {escalated} ESCALATED — see {path}"

telemetry_emit_fail:
  vi: "(telemetry disabled: {reason})"
  en: "(telemetry disabled: {reason})"

security_register_update:
  vi: "🔒 SECURITY-REGISTER updated: {added} added, {resolved} resolved, {open} open"
  en: "🔒 SECURITY-REGISTER updated: {added} added, {resolved} resolved, {open} open"

visual_diff_fail:
  vi: "🖼 Visual regression: {view} diff {pct}% > threshold {threshold}%"
  en: "🖼 Visual regression: {view} diff {pct}% > threshold {threshold}%"
```

## API

```bash
# Helper — call anywhere instead of echo for user-facing strings
t() {
  local key="$1"; shift
  local locale="${CONFIG_NARRATION_LOCALE:-vi}"
  local fallback="${CONFIG_NARRATION_FALLBACK_LOCALE:-en}"
  local table="${CONFIG_NARRATION_STRING_TABLE_PATH:-.claude/commands/vg/_shared/narration-strings.yaml}"

  [ -f "$table" ] || { echo "$key"; return; }   # degrade: print key if no table

  local rendered
  rendered=$(${PYTHON_BIN:-python3} - "$key" "$locale" "$fallback" "$table" "$@" <<'PY'
import sys, yaml, re
key, locale, fallback, table, *kv = sys.argv[1:]
try:
  data = yaml.safe_load(open(table, encoding='utf-8')) or {}
except Exception as e:
  print(key); sys.exit(0)
entry = data.get(key) or {}
tmpl = entry.get(locale) or entry.get(fallback) or key
# kv is list of "name=value" pairs
params = {}
for pair in kv:
  if '=' in pair:
    k, v = pair.split('=', 1); params[k] = v
try:
  print(tmpl.format(**params))
except KeyError as e:
  print(tmpl)  # missing placeholder → print template as-is
PY
)
  echo "$rendered"
}

# Usage examples:
#   t "gate_blocked_intermediate" "count=5"
#   t "goal_start" "goal_id=G-12" "name=create-campaign"
#   t "fix_routed_spawn" "model=sonnet" "severity=MODERATE" "bug=auth-leak"
```

## Migration pattern

Replace hardcoded narration in existing commands:

**Before:**
```bash
echo "⛔ ${COUNT} goals có status intermediate (NOT_SCANNED/FAILED)"
```

**After:**
```bash
t "gate_blocked_intermediate" "count=${COUNT}"
```

Commands to migrate (priority order):
1. `review.md` narrate_* helpers (phase 2b, 3c, 4c-pre)
2. `test.md` narrate_* helpers (0_parse, 5c-goal, 5d-codegen)
3. `build.md` narrate_wave
4. `accept.md` debt/regression messages
5. `_shared/env-commands.md` diagnose_dev_failure
6. `_shared/override-debt.md` log_override_debt return string
7. `_shared/telemetry.md` emit_telemetry fail message

## Adding new locales

1. Add locale key to entries in `narration-strings.yaml` (e.g., `ja: "..."`)
2. Set `config.narration.locale: "ja"`
3. No code changes needed — helper picks it up

## Success criteria

- All user-facing workflow strings go through `t()` — grep for `echo "⛔\|echo "✅\|echo "⚠"` in commands should only appear inside `t()` wrapper
- Adding a locale requires only YAML edit
- Missing keys degrade gracefully (print key name, not crash)
- Strings with missing placeholders degrade to raw template (no crash)
