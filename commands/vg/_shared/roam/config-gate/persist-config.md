# Config gate sub-step 5 — resolve, validate, persist

**Marker:** `0a_persist_config`
**Source:** After-answers branch (91 lines) of original `0a_env_model_mode_gate`.

Final sub-step of the decomposed config gate. Resolves env/model/mode from
AskUserQuestion answers OR CLI flags OR defaults, validates, computes
target URL + per-model output dirs, writes ROAM-CONFIG.json + the
`.tmp/0a-confirmed.marker` HARD GATE token, and emits `roam.config_confirmed`.

## Resolve + validate

```bash
vg-orchestrator step-active 0a_persist_config

# Resolve from AskUserQuestion answers OR CLI flags OR defaults
ROAM_ENV="${ROAM_ENV:-${CONFIG_STEP_ENV_VERIFY:-local}}"
ROAM_MODEL="${ROAM_MODEL:-codex}"
ROAM_MODE="${ROAM_MODE:-spawn}"

# CLI override path
if [[ "$ARGUMENTS" =~ --target-env=([a-z]+) ]]; then ROAM_ENV="${BASH_REMATCH[1]}"; fi
[[ "$ARGUMENTS" =~ --local ]]   && ROAM_ENV="local"
[[ "$ARGUMENTS" =~ --sandbox ]] && ROAM_ENV="sandbox"
[[ "$ARGUMENTS" =~ --staging ]] && ROAM_ENV="staging"
[[ "$ARGUMENTS" =~ --prod ]]    && ROAM_ENV="prod"
if [[ "$ARGUMENTS" =~ --model=([a-z-]+) ]]; then ROAM_MODEL="${BASH_REMATCH[1]}"; fi
if [[ "$ARGUMENTS" =~ --mode=([a-z]+) ]];   then ROAM_MODE="${BASH_REMATCH[1]}";  fi

# Validate
case "$ROAM_ENV"   in local|sandbox|staging|prod) ;; *) echo "⛔ invalid env '$ROAM_ENV'";    exit 1 ;; esac
case "$ROAM_MODEL" in codex|gemini|council)        ;; *) echo "⛔ invalid model '$ROAM_MODEL'"; exit 1 ;; esac
case "$ROAM_MODE"  in self|spawn|manual)           ;; *) echo "⛔ invalid mode '$ROAM_MODE' (allowed: self|spawn|manual)"; exit 1 ;; esac

export ROAM_ENV ROAM_MODEL ROAM_MODE
```

## Compute target URL from vg.config.md credentials block

```bash
# Anchor on `credentials:` block first — vg.config.md has multiple `local:` sections
# (environments.local, services.local, credentials.local) that must not be confused.
ROAM_TARGET_DOMAIN=$(${PYTHON_BIN:-python3} - <<PY
import re, sys
text = open('.claude/vg.config.md', encoding='utf-8').read()
m = re.search(r'^\s*${ROAM_ENV}:\s*$', text, re.M)
if not m: print(''); sys.exit(0)
section = text[m.end():m.end()+2000]
dm = re.search(r'domain:\s*"([^"]+)"', section)
print(dm.group(1) if dm else '')
PY
)
ROAM_TARGET_PROTOCOL="https"
[[ "$ROAM_TARGET_DOMAIN" =~ localhost|127\. ]] && ROAM_TARGET_PROTOCOL="http"
ROAM_TARGET_URL="${ROAM_TARGET_PROTOCOL}://${ROAM_TARGET_DOMAIN}"
export ROAM_TARGET_URL

# Per-model output directory(ies)
if [ "$ROAM_MODEL" = "council" ]; then
  ROAM_MODEL_DIRS=("${ROAM_DIR}/codex" "${ROAM_DIR}/gemini")
else
  ROAM_MODEL_DIRS=("${ROAM_DIR}/${ROAM_MODEL}")
fi
for d in "${ROAM_MODEL_DIRS[@]}"; do mkdir -p "$d"; done

# Banner
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  /vg:roam configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Phase:       ${PHASE_NUMBER}"
echo "  Env:         ${ROAM_ENV} (target: ${ROAM_TARGET_URL})"
echo "  Model:       ${ROAM_MODEL}"
echo "  Mode:        ${ROAM_MODE}"
echo "  Output dirs: ${ROAM_MODEL_DIRS[*]}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
```

## Persist ROAM-CONFIG.json + telemetry + HARD GATE marker

```bash
${PYTHON_BIN:-python3} -c "
import json, datetime
from pathlib import Path
p = Path('${ROAM_DIR}/ROAM-CONFIG.json')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps({
  'phase': '${PHASE_NUMBER}',
  'env': '${ROAM_ENV}',
  'model': '${ROAM_MODEL}',
  'mode': '${ROAM_MODE}',
  'target_url': '${ROAM_TARGET_URL}',
  'output_dirs': '${ROAM_MODEL_DIRS[*]}'.split(),
  'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, indent=2))
"

${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
  "roam.config_confirmed" \
  --actor "orchestrator" --outcome "INFO" \
  --payload "{\"env\":\"${ROAM_ENV}\",\"model\":\"${ROAM_MODEL}\",\"mode\":\"${ROAM_MODE}\"}" 2>/dev/null || true

# v2.42.9 HARD GATE: write env/model/mode marker. Step 1 entry refuses to
# proceed unless this marker exists (or --non-interactive set). Marker
# value embeds env+model+mode so downstream gates can verify non-empty.
mkdir -p "${ROAM_DIR}/.tmp"
echo "$(date +%s)|${ROAM_ENV}|${ROAM_MODEL}|${ROAM_MODE}" > "${ROAM_DIR}/.tmp/0a-confirmed.marker"

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "0a_persist_config" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0a_persist_config.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step roam 0a_persist_config 2>/dev/null || true
```

After this sub-step, the config gate is complete. Next: `discovery.md`.
