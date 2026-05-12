# Batch 7 — Idempotency check safety (H4 CRITICAL) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close H4 from audit — 5b-2 idempotency check pollutes target with real billing/payment/payout records using user's Bearer token. Auto-ON by default. Never cleans up duplicates.

**Source:** `docs/plans/2026-05-13-pipeline-flow-audit.md` Gap H4.

**Architecture:** Default OFF. Opt-in via `config.test.idempotency.enabled`. Production HARD-GATE (refuse non-dev/staging targets). Track created IDs in cleanup ledger. POST cleanup DELETE for each duplicate. Emit `test.idempotency_polluted` event when cleanup fails.

**Tech Stack:** Bash + Python embed. No new deps.

**Working directory:** `main`.

---

## Conventions

- Bash: `set -euo pipefail` where applicable
- Mirror byte-identical to `.claude/commands/`
- Regression sweep: `python -m pytest tests/ -q --tb=no -k "idempotency or runtime or critical_domain"`
- Commits use `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

---

## Task 1: Default OFF + config gate + production HARD-GATE

**Files:**
- Modify: `commands/vg/_shared/test/runtime.md` (5b-2 idempotency check)
- Modify: `vg.config.template.md` + mirrors (add `test.idempotency.*` block)
- Mirror: `.claude/commands/vg/_shared/test/runtime.md`
- Test: `tests/test_h4_idempotency_default_off.py`

**Step 1: Failing test**

```python
"""tests/test_h4_idempotency_default_off.py — Batch 7 H4 safety gates.

Verifies:
1. runtime.md 5b-2 is OFF unless config.test.idempotency.enabled=true.
2. runtime.md 5b-2 HARD-GATEs against production-like ENVIRONMENT values.
3. config templates document the test.idempotency.* block.
4. Skip behavior is observable (event/log line) so user knows why skipped.
"""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
RUNTIME = REPO / "commands" / "vg" / "_shared" / "test" / "runtime.md"
CONFIG = REPO / "vg.config.template.md"
MIRROR_CONFIG = REPO / ".claude" / "templates" / "vg" / "vg.config.template.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_idempotency_default_off():
    body = _read(RUNTIME)
    # Must check config.test.idempotency.enabled before running
    assert "test.idempotency.enabled" in body or "IDEMPOTENCY_ENABLED" in body, (
        "H4: 5b-2 must gate on config.test.idempotency.enabled (default false). "
        "Currently auto-ON for billing/auth/payment/payout/transaction domains."
    )
    # Must reference the gate location
    assert "Skip if" in body and "idempotency" in body.lower()


def test_idempotency_production_hard_gate():
    body = _read(RUNTIME)
    # Must refuse production-like ENVIRONMENT
    assert ("ENVIRONMENT" in body and "production" in body.lower()) or "PROD_GUARD" in body, (
        "H4: 5b-2 must HARD-GATE when ENVIRONMENT in (production, prod, live). "
        "Cannot pollute production with double-POSTs of real Bearer-token payloads."
    )


def test_config_documents_idempotency_block():
    body = _read(CONFIG)
    assert "idempotency" in body.lower(), (
        "H4: vg.config.template.md must document test.idempotency.{enabled,allowed_envs} block"
    )
    assert "enabled" in body and "allowed_envs" in body, (
        "H4: config block must expose enabled + allowed_envs keys"
    )


def test_skip_emits_observable_signal():
    body = _read(RUNTIME)
    # Skip path must echo a reason (not silent skip)
    skip_block_start = body.find("test.idempotency.enabled")
    if skip_block_start == -1:
        skip_block_start = body.find("IDEMPOTENCY_ENABLED")
    assert skip_block_start > 0
    skip_block = body[skip_block_start:skip_block_start + 600]
    assert "echo" in skip_block or "emit-event" in skip_block, (
        "H4: skip path must emit reason — silent skip hides safety behavior from user"
    )


def test_mirror_config():
    if MIRROR_CONFIG.is_file():
        assert _read(CONFIG) == _read(MIRROR_CONFIG)
```

**Step 2: Run** → 5 fail.

**Step 3: Implement**

Edit `commands/vg/_shared/test/runtime.md` 5b-2 block. Replace lines 54-105 with:

```markdown
### 5b-2: Idempotency check (DEFAULT OFF — opt-in safety gate)

> **H4 SAFETY (Batch 7):** This check double-submits POST/PUT/DELETE to live `$BASE_URL` with real `Bearer ${AUTH_TOKEN}`. **Default: OFF.** Opt-in via `config.test.idempotency.enabled: true`. Hard-gates against production-like environments. Failed cleanup emits `test.idempotency_polluted` event.

**Skip conditions (any one skips):**
- `config.test.idempotency.enabled` not `true` (default)
- `ENVIRONMENT` in `config.test.idempotency.blocked_envs` (default: `production,prod,live`)
- `$BASE_URL` unset
- `config.critical_domains` empty
- No matching endpoints in vg-load index

```bash
# H4 Batch 7: production-pollution safety gates
IDEM_ENABLED=$(vg_config_get test.idempotency.enabled "false" 2>/dev/null || echo "false")
if [ "${IDEM_ENABLED}" != "true" ]; then
  echo "5b-2 idempotency: SKIPPED (config.test.idempotency.enabled=false)"
  echo "  Set 'test.idempotency.enabled: true' in vg.config.md to opt in (NON-PROD only)."
  IDEMPOTENCY_SKIPPED=1
fi

if [ "${IDEMPOTENCY_SKIPPED:-0}" != "1" ]; then
  BLOCKED_ENVS=$(vg_config_get test.idempotency.blocked_envs "production,prod,live" 2>/dev/null || echo "production,prod,live")
  CUR_ENV="${ENVIRONMENT:-${VG_ENV:-unknown}}"
  for blocked in $(echo "$BLOCKED_ENVS" | tr ',' ' '); do
    if [ "${CUR_ENV,,}" = "${blocked,,}" ]; then
      echo "⛔ 5b-2 idempotency BLOCKED: ENVIRONMENT='${CUR_ENV}' in blocked list."
      echo "  Idempotency probe creates real records via double-POST — refuse production."
      echo "  Override via test.idempotency.blocked_envs config (NOT recommended)."
      "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event "test.idempotency_blocked_production" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\",\"env\":\"${CUR_ENV}\"}" >/dev/null 2>&1 || true
      IDEMPOTENCY_SKIPPED=1
      break
    fi
  done
fi

if [ "${IDEMPOTENCY_SKIPPED:-0}" != "1" ]; then
CRITICAL_DOMAINS="${config.critical_domains:-billing,auth,payout,payment,transaction}"
IDEMPOTENCY_FAILS=0
IDEM_CLEANUP_LEDGER="${VG_TMP}/idempotency-cleanup.json"
echo "[]" > "$IDEM_CLEANUP_LEDGER"

# Phase F Task 30 — endpoint enumeration via vg-load index
echo "$CONTRACTS_INDEX" | ${PYTHON_BIN:-python3} -c "
import json, sys
idx = json.load(sys.stdin)
domains = '${CRITICAL_DOMAINS}'.split(',')
for ep in idx.get('endpoints', []):
    m, p = ep.get('method',''), ep.get('path','')
    if m not in ('POST','PUT','DELETE'): continue
    if any(d.strip() in p.lower() for d in domains):
        print(f'{m}\t{p}\t{ep.get(\"sample_payload\",\"{}\")}')
" 2>/dev/null > "${VG_TMP}/critical-payloads.txt"

CRITICAL_COUNT=$(wc -l < "${VG_TMP}/critical-payloads.txt" | tr -d ' ')

if [ "$CRITICAL_COUNT" -gt 0 ] && [ -n "$BASE_URL" ]; then
  echo "Idempotency check: ${CRITICAL_COUNT} critical-domain mutation endpoints (env=${CUR_ENV})"
  while IFS=$'\t' read -r METHOD ENDPOINT PAYLOAD; do
    [ -z "$ENDPOINT" ] && continue
    [ -z "$PAYLOAD" ] && PAYLOAD='{}'
    RESP1=$(curl -sf -X "$METHOD" "${BASE_URL}${ENDPOINT}" \
      -H "Authorization: Bearer ${AUTH_TOKEN}" -H "Content-Type: application/json" \
      -d "$PAYLOAD" -w "\n%{http_code}" 2>/dev/null)
    STATUS1=$(echo "$RESP1" | tail -1)
    RESP2=$(curl -sf -X "$METHOD" "${BASE_URL}${ENDPOINT}" \
      -H "Authorization: Bearer ${AUTH_TOKEN}" -H "Content-Type: application/json" \
      -d "$PAYLOAD" -w "\n%{http_code}" 2>/dev/null)
    STATUS2=$(echo "$RESP2" | tail -1)
    if [ "$STATUS1" = "201" ] && [ "$STATUS2" = "201" ]; then
      ID1=$(echo "$RESP1" | sed '$d' | ${PYTHON_BIN:-python3} -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
      ID2=$(echo "$RESP2" | head -1 | ${PYTHON_BIN:-python3} -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
      # H4 Batch 7: Track BOTH created IDs for cleanup — even when idempotency passes (server returned same ID twice = no dup, ID2 may still be a real new record on PUT)
      for created_id in "$ID1" "$ID2"; do
        [ -n "$created_id" ] || continue
        ${PYTHON_BIN:-python3} -c "
import json
with open('${IDEM_CLEANUP_LEDGER}', encoding='utf-8') as f: data = json.load(f)
data.append({'method': '${METHOD}', 'path': '${ENDPOINT}', 'id': '${created_id}'})
with open('${IDEM_CLEANUP_LEDGER}', 'w', encoding='utf-8') as f: json.dump(data, f)
" 2>/dev/null
      done
      if [ -n "$ID1" ] && [ -n "$ID2" ] && [ "$ID1" != "$ID2" ]; then
        echo "  CRITICAL: ${METHOD} ${ENDPOINT} — double-submit created 2 records (${ID1} vs ${ID2})"
        IDEMPOTENCY_FAILS=$((IDEMPOTENCY_FAILS + 1))
      fi
    elif [ "$STATUS1" = "400" ]; then
      echo "  SKIP: ${METHOD} ${ENDPOINT} — schema validation rejected payload (400)"
    fi
  done < "${VG_TMP}/critical-payloads.txt"
  [ "$IDEMPOTENCY_FAILS" -gt 0 ] \
    && echo "  ⛔ ${IDEMPOTENCY_FAILS} idempotency failures" \
    || echo "  ✓ All critical-domain endpoints pass idempotency check"

  # H4 Batch 7: Cleanup pass — DELETE every created record
  CLEANUP_FAILS=0
  CLEANUP_COUNT=0
  while IFS= read -r entry; do
    METHOD=$(echo "$entry" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('method',''))" 2>/dev/null)
    PATH_TPL=$(echo "$entry" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('path',''))" 2>/dev/null)
    REC_ID=$(echo "$entry" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('id',''))" 2>/dev/null)
    [ -z "$REC_ID" ] && continue
    # Best-effort DELETE — only attempt if base path resembles a resource collection (POST /xs → DELETE /xs/$id)
    if [ "$METHOD" = "POST" ]; then
      DEL_URL="${BASE_URL}${PATH_TPL%/}/${REC_ID}"
      DEL_CODE=$(curl -sf -X DELETE "$DEL_URL" \
        -H "Authorization: Bearer ${AUTH_TOKEN}" \
        -w "%{http_code}" -o /dev/null 2>/dev/null || echo "000")
      CLEANUP_COUNT=$((CLEANUP_COUNT + 1))
      if [ "$DEL_CODE" != "204" ] && [ "$DEL_CODE" != "200" ] && [ "$DEL_CODE" != "404" ]; then
        echo "  ⚠ idempotency cleanup DELETE ${DEL_URL} → ${DEL_CODE}"
        CLEANUP_FAILS=$((CLEANUP_FAILS + 1))
      fi
    fi
  done < <(${PYTHON_BIN:-python3} -c "
import json
data = json.load(open('${IDEM_CLEANUP_LEDGER}', encoding='utf-8'))
for e in data: print(json.dumps(e))
" 2>/dev/null)

  if [ "$CLEANUP_FAILS" -gt 0 ]; then
    echo "  ⚠ ${CLEANUP_FAILS}/${CLEANUP_COUNT} idempotency cleanup DELETE attempts failed — review ${IDEM_CLEANUP_LEDGER}"
    "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event "test.idempotency_polluted" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"cleanup_fails\":${CLEANUP_FAILS},\"cleanup_total\":${CLEANUP_COUNT},\"ledger\":\"${IDEM_CLEANUP_LEDGER}\"}" >/dev/null 2>&1 || true
  else
    [ "$CLEANUP_COUNT" -gt 0 ] && echo "  ✓ idempotency cleanup: ${CLEANUP_COUNT} records DELETE'd"
  fi
fi
fi
```

Result: `IDEMPOTENCY_FAILS > 0` → FAIL (same severity as contract mismatch). Cleanup failure emits `test.idempotency_polluted` event (advisory, does NOT fail step on its own — user must inspect ledger).
```

Edit `vg.config.template.md` + mirrors. Append:

```yaml
# H4 Batch 7: idempotency probe safety (5b-2 in /vg:test)
test:
  idempotency:
    enabled: false                                    # default OFF — opt-in only
    blocked_envs: production,prod,live                # HARD-GATE refuses these envs
    # Note: when enabled+non-blocked env, probe double-POSTs to $BASE_URL with
    # real Bearer token. Cleanup DELETE attempted on each created record.
    # Cleanup failures emit test.idempotency_polluted event — inspect ledger
    # at ${VG_TMP}/idempotency-cleanup.json.
```

**Step 4: Run tests** → 5 pass.

**Step 5: Mirror byte-identical**

```bash
cp commands/vg/_shared/test/runtime.md .claude/commands/vg/_shared/test/runtime.md
cp vg.config.template.md .claude/templates/vg/vg.config.template.md
cp vg.config.template.md templates/vg/vg.config.template.md
```

**Step 6: Commit**

```bash
git add commands/vg/_shared/test/runtime.md \
        .claude/commands/vg/_shared/test/runtime.md \
        vg.config.template.md \
        .claude/templates/vg/vg.config.template.md \
        templates/vg/vg.config.template.md \
        tests/test_h4_idempotency_default_off.py
git commit -m "fix(safety): H4 — idempotency probe default OFF + cleanup + prod gate (Batch 7)

Audit Gap H4 (CRITICAL): 5b-2 idempotency check auto-ON for billing/auth/
payout/payment/transaction domains by default. Double-POSTs real Bearer-token
payloads to live \$BASE_URL. Never cleans up the duplicate records. Real
billing/payment rows committed in target env on every test run.

Fix:
1. Default OFF — gates on config.test.idempotency.enabled (default false).
   Skipped with explanatory log line so user sees why.
2. Production HARD-GATE — refuses ENVIRONMENT in
   config.test.idempotency.blocked_envs (default: production,prod,live).
   Emits test.idempotency_blocked_production event.
3. Cleanup pass — tracks every created record ID in
   \${VG_TMP}/idempotency-cleanup.json. After probe, attempts DELETE for
   each. Cleanup failures emit test.idempotency_polluted advisory event.
4. Config template documents test.idempotency.{enabled,blocked_envs}.

Tests: tests/test_h4_idempotency_default_off.py (5 tests).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Regression sweep + release v4.4.0

**Step 1:** Sweep:

```bash
python -m pytest tests/ -q --tb=no -k "idempotency or runtime or critical_domain or h4"
```

All must pass. Pre-existing tests pinned old auto-ON behavior should NOT exist (idempotency check was prose-only previously); if any exist, update to assert new opt-in model.

**Step 2:** Bump VERSION `4.3.0` → `4.4.0`. Update `package.json`.

**Step 3:** CHANGELOG entry:

```markdown
## v4.4.0 — Test safety: idempotency probe default OFF + cleanup (Batch 7 / H4 CRITICAL) (2026-05-XX)

Audit (Codex GPT-5.5 + manual) Gap H4: 5b-2 idempotency check inside
runtime.md was auto-ON for critical_domains (billing/auth/payout/payment/
transaction). Double-POSTed real Bearer-token payloads to live BASE_URL.
Never cleaned up the duplicates. Production pollution on every test run.

Fix:
- Default OFF — opt-in via `config.test.idempotency.enabled: true`.
- Production HARD-GATE — refuses `ENVIRONMENT` in
  `config.test.idempotency.blocked_envs` (default: production,prod,live).
- Cleanup pass — tracks created IDs in `idempotency-cleanup.json`. After
  probe runs DELETE for each. Failed cleanup emits
  `test.idempotency_polluted` event.
- Skipped state observable — explanatory log line, never silent.

Audit reference: `docs/plans/2026-05-13-pipeline-flow-audit.md` H4.
```

**Step 4:** Commit + tag + push:

```bash
git add VERSION package.json CHANGELOG.md
git commit -m "release: v4.4.0 — Batch 7 H4 idempotency safety (CRITICAL)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git tag v4.4.0 -m "v4.4.0 — Batch 7 H4 idempotency safety"
git push origin main v4.4.0
```

**Step 5:** Re-sync global install:

```bash
cp commands/vg/_shared/test/runtime.md ~/.vgflow/commands/vg/_shared/test/runtime.md
cp vg.config.template.md ~/.vgflow/templates/vg/vg.config.template.md 2>/dev/null || true
```

---

End of Batch 7 plan. Estimated 2 hours engineering wall-clock.

## Risk register

| Risk | Mitigation |
|---|---|
| Existing projects relying on auto-ON behavior break silently | Skip path emits explanatory log line + suggests opt-in flag |
| Cleanup DELETE attempts on PUT-modified records produce wrong rows | Cleanup only fires for `METHOD=POST` — leaves PUT/DELETE alone (they don't create new records anyway) |
| Cleanup DELETE returns 404 (record auto-cleaned by app) | Treat 404 as success — common when app has its own TTL/dedup |
| blocked_envs default too strict for dev shops using `production` as dev name | Document in config block + override via `blocked_envs: ""` (empty disables HARD-GATE) |
| Idempotency probe still pollutes when dev/staging env names differ | Document recommended dev/staging env naming (NOT production/prod/live) |

## Out of scope (Batch 7)

- Per-endpoint cleanup strategy (PUT rollback, transaction-based) — defer to v4.5+
- Pre-probe snapshot/restore — too complex for v4.4
