# Config gate sub-step 3 — enrich env options from DEPLOY-STATE

**Marker:** `0a_enrich_env_options`
**Source:** Pre-prompt 2 (32 lines, B2 wiring v2.42.5+) of original `0a_env_model_mode_gate`.

After backfill (or if skipped), run the helper to read DEPLOY-STATE + emit
decorated labels/descriptions. **Suggestion-only** — user still picks; AI
decorates options with evidence ("deployed 2min ago, sha abc1234", "phase
prefers this env", "chưa deploy phase này", etc.) so the AskUserQuestion
batch in `confirm-env-model-mode.md` is well-informed.

## Run

```bash
mkdir -p "${PHASE_DIR}/.tmp"
${PYTHON_BIN:-python3} .claude/scripts/enrich-env-question.py \
  --phase-dir "${PHASE_DIR}" --command roam \
  > "${PHASE_DIR}/.tmp/env-options.roam.json" 2>/dev/null || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "0a_enrich_env_options" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0a_enrich_env_options.done"
```

## Output schema

After this runs, `.tmp/env-options.roam.json` contains:

```json
{
  "deploy_state_present": true,
  "preferred_env": "sandbox",
  "recommended_env": "sandbox",
  "envs": {
    "local":   {"decorated_label": "...", "decorated_description": "...", "is_recommended": false},
    "sandbox": {"decorated_label": "... (Recommended)", "decorated_description": "... [phase prefers this env]"},
    "staging": {"decorated_label": "...", "decorated_description": "...", "is_recommended": false},
    "prod":    {"decorated_label": "...", "decorated_description": "...", "is_recommended": false}
  }
}
```

## Downstream usage

When building the env question's `options` array in `confirm-env-model-mode.md`,
AI MUST read this JSON and use `envs.{key}.decorated_label` +
`envs.{key}.decorated_description` verbatim instead of the hardcoded labels.
If the JSON is missing or malformed, fall back to the hardcoded options and
proceed (graceful degrade — script may not yet be installed in legacy projects).

## Why this is its own sub-step

Splitting from confirm-env-model-mode.md gives a precise marker for the
"enrichment ran" event. If env options look stale or wrong in the
AskUserQuestion batch, the marker pinpoints whether enrichment fired at all
vs. fired-but-stale. Without a marker here the question becomes "did the
helper script run?" which costs ~30s of debug per occurrence.

Next: read `confirm-env-model-mode.md`.
