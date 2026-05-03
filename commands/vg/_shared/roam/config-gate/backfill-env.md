# Config gate sub-step 1 — backfill `preferred_env_for`

<HARD-GATE>
`0a_backfill_env_pref` MUST emit its own `step-active` + canonical
`mark-step roam` pair. Skipping this sub-step leaves DEPLOY-STATE
without a `preferred_env_for` for older phases — the runtime env gate
then silently re-fires the 5-option preset every roam invocation.
</HARD-GATE>

**Marker:** `0a_backfill_env_pref`
**Source:** Pre-prompt 1 (90 lines, v2.42.7+) of original `0a_env_model_mode_gate`.

Phases scoped before `/vg:scope` step 1b landed have `CONTEXT.md` but no
`DEPLOY-STATE.json` `preferred_env_for` block. Without backfill, the runtime
env gate falls back to profile heuristic forever — user never gets to set the
preference. This pre-prompt closes that gap by asking the same 5-option preset
once and persisting into DEPLOY-STATE.json so it never re-fires.

## Skip conditions

- `${ARGUMENTS}` contains `--skip-env-preference` OR `--non-interactive`
- `${PHASE_DIR}/DEPLOY-STATE.json` already has `preferred_env_for` set
- `${PHASE_DIR}/DEPLOY-STATE.json` has `preferred_env_for_skipped: true`
  (user previously chose "auto" — don't re-ask)

## Detection

```bash
vg-orchestrator step-active 0a_backfill_env_pref

DEPLOY_STATE="${PHASE_DIR}/DEPLOY-STATE.json"
NEED_PREF_PROMPT="false"
if [[ ! "$ARGUMENTS" =~ --skip-env-preference ]] && [[ ! "$ARGUMENTS" =~ --non-interactive ]]; then
  if [ ! -f "$DEPLOY_STATE" ]; then
    NEED_PREF_PROMPT="true"
  else
    HAS_PREF=$(${PYTHON_BIN:-python3} -c "
import json
try:
  d = json.load(open('$DEPLOY_STATE'))
  print('1' if d.get('preferred_env_for') or d.get('preferred_env_for_skipped') else '0')
except Exception:
  print('0')" 2>/dev/null)
    [ "$HAS_PREF" = "0" ] && NEED_PREF_PROMPT="true"
  fi
fi

if [ "$NEED_PREF_PROMPT" = "true" ]; then
  echo "▸ DEPLOY-STATE.json chưa có preferred_env_for — fire one-time backfill prompt"
  echo "  AI: AskUserQuestion với 5-option preset trước khi vào env+model+mode gate."
fi
```

## AskUserQuestion (fires only when `$NEED_PREF_PROMPT=true`)

```
question: |
  Phase này khi review/test/roam/accept chạy nên ưu tiên env nào?
  GỢI Ý THÔI — runtime AskUserQuestion vẫn fire, đây chỉ là pre-fill recommendation.
  Hỏi 1 lần thôi, lưu vào DEPLOY-STATE.json. Re-set bằng /vg:scope <phase> --reset-env-preference.
header: "Env pref"
multiSelect: false
options:
  - label: "auto — không lưu preference (Recommended cho phase mới)"
    description: "Lưu cờ skipped để không hỏi lại. Helper enrich-env-question.py dùng profile heuristic mỗi lần."
  - label: "all sandbox — review/test/roam/accept đều prefer sandbox"
    description: "Phase chưa ship lên prod; dogfood sâu trên sandbox."
  - label: "review+test+roam=sandbox, accept=prod — phổ biến nhất"
    description: "Production-ready phase. UAT trên prod thật, mọi check khác trên sandbox."
  - label: "review+test=sandbox, roam=staging, accept=prod — paranoid"
    description: "Tách roam riêng sang staging để soi env gần prod hơn. Phù hợp ship-critical."
  - label: "all local — phase nội bộ / dogfood"
    description: "Pure-backend hoặc internal tooling, không cần deploy."
```

## After answer — persist + mark

```bash
if [ "$NEED_PREF_PROMPT" = "true" ]; then
  ${PYTHON_BIN:-python3} -c "
import json, os, sys
from pathlib import Path
choice = os.environ.get('ENV_PREF_BACKFILL_CHOICE', 'auto').lower()
mapping = None
if 'all sandbox' in choice:
  mapping = {'review': 'sandbox', 'test': 'sandbox', 'roam': 'sandbox', 'accept': 'sandbox'}
elif 'review+test+roam=sandbox' in choice and 'accept=prod' in choice:
  mapping = {'review': 'sandbox', 'test': 'sandbox', 'roam': 'sandbox', 'accept': 'prod'}
elif 'roam=staging' in choice and 'accept=prod' in choice:
  mapping = {'review': 'sandbox', 'test': 'sandbox', 'roam': 'staging', 'accept': 'prod'}
elif 'all local' in choice:
  mapping = {'review': 'local', 'test': 'local', 'roam': 'local', 'accept': 'local'}

p = Path('$DEPLOY_STATE')
state = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'phase': '${PHASE_NUMBER}'}
if mapping is None:
  state['preferred_env_for_skipped'] = True
  print('[roam-backfill] auto — skipped flag saved (won\\'t re-ask)')
else:
  state['preferred_env_for'] = mapping
  print(f'[roam-backfill] saved: {json.dumps(mapping)}')
p.write_text(json.dumps(state, indent=2, ensure_ascii=False))
"
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "0a_backfill_env_pref" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0a_backfill_env_pref.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step roam 0a_backfill_env_pref 2>/dev/null || true
```

Next: read `detect-platform.md`.
