# scope env-preference (STEP 3)

> Marker: `1b_env_preference` (kept for emit-tasklist.py compat — see scope.md
> entry comment on Nit #2).
> Suggestion-only. Captures sandbox/staging/prod target for downstream review/test/roam/accept. User can SKIP.

<HARD-GATE>
You MUST execute the bash block in §"Apply answer + persist" — it calls
`vg-orchestrator step-active 1b_env_preference` BEFORE any skip path,
then `mark-step` after. Skipping the step-active call leaves the marker
untracked and the Stop hook will fail.
</HARD-GATE>

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
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 1b_env_preference

# Important-2 r2 fix: replace `return 0` (only valid inside sourced functions —
# Bash tool snippets are NOT guaranteed to run sourced) with a guarded
# `ENV_PREF_SKIP` flag + single fall-through path. mark-step always fires at
# the end regardless of skip path.
ENV_PREF_SKIP=""
DEPLOY_STATE="${PHASE_DIR}/DEPLOY-STATE.json"

# Skip if non-interactive OR --skip-env-preference
if [[ "$ARGUMENTS" =~ --skip-env-preference ]] || [[ "$ARGUMENTS" =~ --non-interactive ]]; then
  echo "▸ Skipping env preference step (flag set)"
  ENV_PREF_SKIP="flag"
fi

# Skip if preference already set + no --reset-env-preference
if [ -z "$ENV_PREF_SKIP" ] && [ -f "$DEPLOY_STATE" ] && [[ ! "$ARGUMENTS" =~ --reset-env-preference ]]; then
  HAS_PREF=$(${PYTHON_BIN:-python3} -c "import json; d=json.load(open('$DEPLOY_STATE')); print('1' if d.get('preferred_env_for') else '0')" 2>/dev/null || echo 0)
  if [ "$HAS_PREF" = "1" ]; then
    EXISTING=$(${PYTHON_BIN:-python3} -c "import json; print(json.dumps(json.load(open('$DEPLOY_STATE')).get('preferred_env_for', {})))" 2>/dev/null)
    echo "▸ preferred_env_for đã set: $EXISTING — skip (re-set bằng --reset-env-preference)"
    ENV_PREF_SKIP="already-set"
  fi
fi

if [ -z "$ENV_PREF_SKIP" ]; then

# Important-1 r2 fix: --env-preference=<mode> inline flag is now honored.
# Precedence:
#   1. ENV_PREF_INLINE (from preflight parser, --env-preference=<token>)
#   2. ENV_PREF_CHOICE (from AskUserQuestion in interactive mode)
#   3. default 'auto'
# Inline tokens: auto | sandbox | review-sandbox-accept-prod | paranoid | local
${PYTHON_BIN:-python3} - "$DEPLOY_STATE" "${PHASE_NUMBER}" <<'PY'
import json, os, sys
from pathlib import Path

deploy_state_path, phase_number = sys.argv[1], sys.argv[2]
inline = (os.environ.get('ENV_PREF_INLINE') or '').strip().lower()
choice = (os.environ.get('ENV_PREF_CHOICE') or '').strip().lower()

# Token map for inline form (canonical short tokens documented in §"Override flags")
INLINE_MAP = {
    'auto': None,
    'sandbox': {'review': 'sandbox', 'test': 'sandbox', 'roam': 'sandbox', 'accept': 'sandbox'},
    'all-sandbox': {'review': 'sandbox', 'test': 'sandbox', 'roam': 'sandbox', 'accept': 'sandbox'},
    'review-sandbox-accept-prod': {'review': 'sandbox', 'test': 'sandbox', 'roam': 'sandbox', 'accept': 'prod'},
    'paranoid': {'review': 'sandbox', 'test': 'sandbox', 'roam': 'staging', 'accept': 'prod'},
    'local': {'review': 'local', 'test': 'local', 'roam': 'local', 'accept': 'local'},
    'all-local': {'review': 'local', 'test': 'local', 'roam': 'local', 'accept': 'local'},
}

source = None
mapping = None
if inline:
    if inline in INLINE_MAP:
        mapping = INLINE_MAP[inline]
        source = f'inline(--env-preference={inline})'
    else:
        print(f'[scope-1b] WARN: unrecognized --env-preference={inline!r}; '
              f'falling back to auto. Accepted: {sorted(INLINE_MAP)}', file=sys.stderr)
        source = 'inline-invalid-fallback'
elif choice:
    if 'all sandbox' in choice:
        mapping = INLINE_MAP['sandbox']
    elif 'review+test+roam=sandbox' in choice and 'accept=prod' in choice:
        mapping = INLINE_MAP['review-sandbox-accept-prod']
    elif 'roam=staging' in choice and 'accept=prod' in choice:
        mapping = INLINE_MAP['paranoid']
    elif 'all local' in choice:
        mapping = INLINE_MAP['local']
    elif 'auto' in choice:
        mapping = None
    else:
        print(f'[scope-1b] WARN: unrecognized ENV_PREF_CHOICE {choice!r} — treating as auto', file=sys.stderr)
    source = f'interactive({choice})'
else:
    source = 'default-auto'

if mapping is None:
    print(f'[scope-1b] auto ({source}) — DEPLOY-STATE.json not modified')
    sys.exit(0)

p = Path(deploy_state_path)
state = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'phase': phase_number}
state['preferred_env_for'] = mapping
p.write_text(json.dumps(state, indent=2, ensure_ascii=False))
print(f'[scope-1b] preferred_env_for saved ({source}): {json.dumps(mapping)}')
PY

fi  # end ENV_PREF_SKIP guard (Important-2 r2 fix)

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
