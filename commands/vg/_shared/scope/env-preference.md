# Env preference (STEP 3 — `1b_env_preference`)

> Suggestion-only. Captures sandbox/staging/prod target for downstream review/test/roam/accept. User can SKIP.

## Skip conditions

- `${ARGUMENTS}` contains `--skip-env-preference` OR `--non-interactive`
- `${PHASE_DIR}/DEPLOY-STATE.json` already has `preferred_env_for` filled (don't overwrite without `--reset-env-preference`)

## AskUserQuestion (1 question, 5 preset options)

```
header: "Env pref"
question: |
  Phase này khi review / test / roam / accept chạy nên ưu tiên env nào?

  GỢI Ý THÔI — runtime AskUserQuestion vẫn fire, đây chỉ là pre-fill option
  "Recommended". Không lưu = AI auto-pick theo profile heuristic mỗi lần.
options:
  - label: "auto — không lưu preference (Recommended cho phase mới)"
    description: "Skip step này. Helper enrich-env-question.py dùng profile heuristic mỗi lần (feature/bugfix/hotfix → sandbox; docs → local; accept → prod)."
  - label: "all sandbox — review/test/roam/accept đều prefer sandbox"
    description: "Phase chưa ship lên prod, dogfood sâu trên sandbox."
  - label: "review+test+roam=sandbox, accept=prod — phổ biến nhất"
    description: "Production-ready phase. UAT (accept) trên prod thật, mọi check khác trên sandbox."
  - label: "review+test=sandbox, roam=staging, accept=prod — paranoid"
    description: "Tách roam riêng sang staging (multi-tenant + prod-like data). Phù hợp ship-critical."
  - label: "all local — phase nội bộ / dogfood"
    description: "Không deploy. Backend/internal tooling — chạy đâu cũng OK."
```

## Apply answer + persist

```bash
# Skip if non-interactive OR --skip-env-preference
if [[ "$ARGUMENTS" =~ --skip-env-preference ]] || [[ "$ARGUMENTS" =~ --non-interactive ]]; then
  echo "▸ Skipping env preference step (flag set)"
  vg-orchestrator mark-step scope 1b_env_preference 2>/dev/null || true
  return 0
fi

# Skip if preference already set + no --reset-env-preference
DEPLOY_STATE="${PHASE_DIR}/DEPLOY-STATE.json"
if [ -f "$DEPLOY_STATE" ] && [[ ! "$ARGUMENTS" =~ --reset-env-preference ]]; then
  HAS_PREF=$(${PYTHON_BIN:-python3} -c "import json; d=json.load(open('$DEPLOY_STATE')); print('1' if d.get('preferred_env_for') else '0')" 2>/dev/null || echo 0)
  if [ "$HAS_PREF" = "1" ]; then
    EXISTING=$(${PYTHON_BIN:-python3} -c "import json; print(json.dumps(json.load(open('$DEPLOY_STATE')).get('preferred_env_for', {})))" 2>/dev/null)
    echo "▸ preferred_env_for đã set: $EXISTING — skip (re-set bằng --reset-env-preference)"
    vg-orchestrator mark-step scope 1b_env_preference 2>/dev/null || true
    return 0
  fi
fi

# AI: invoke AskUserQuestion above, capture answer into ENV_PREF_CHOICE
${PYTHON_BIN:-python3} -c "
import json, os, sys
from pathlib import Path
choice = os.environ.get('ENV_PREF_CHOICE', 'auto').lower()
mapping = None
if 'all sandbox' in choice:
  mapping = {'review': 'sandbox', 'test': 'sandbox', 'roam': 'sandbox', 'accept': 'sandbox'}
elif 'review+test+roam=sandbox' in choice and 'accept=prod' in choice:
  mapping = {'review': 'sandbox', 'test': 'sandbox', 'roam': 'sandbox', 'accept': 'prod'}
elif 'roam=staging' in choice and 'accept=prod' in choice:
  mapping = {'review': 'sandbox', 'test': 'sandbox', 'roam': 'staging', 'accept': 'prod'}
elif 'all local' in choice:
  mapping = {'review': 'local', 'test': 'local', 'roam': 'local', 'accept': 'local'}
elif 'auto' in choice:
  mapping = None
else:
  print(f'[scope-1b] WARN: unrecognized choice {choice!r} — treating as auto', file=sys.stderr)

if mapping is None:
  print('[scope-1b] auto — DEPLOY-STATE.json not modified')
  sys.exit(0)

deploy_state_path = Path('$DEPLOY_STATE')
state = json.loads(deploy_state_path.read_text(encoding='utf-8')) if deploy_state_path.exists() else {'phase': '${PHASE_NUMBER}'}
state['preferred_env_for'] = mapping
deploy_state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
print(f'[scope-1b] preferred_env_for saved: {json.dumps(mapping)}')"

vg-orchestrator mark-step scope 1b_env_preference 2>/dev/null || true
```

## Override flags

- `--skip-env-preference` — explicit skip (alias of `--non-interactive` for this step)
- `--reset-env-preference` — re-prompt even if already set
- `--env-preference=auto|sandbox|review-sandbox-accept-prod|paranoid|local` — non-interactive shortcut

## Consumers

- `${PHASE_DIR}/DEPLOY-STATE.json` `preferred_env_for.{review|test|roam|accept}` is read by:
  - `.claude/scripts/enrich-env-question.py` — decorates AskUserQuestion options at runtime env gate
  - Future `/vg:deploy` — pre-selects deploy targets when phase ready

User can edit `DEPLOY-STATE.json` manually to fine-tune.

## Advance

Read `_shared/scope/artifact-write.md` next.
