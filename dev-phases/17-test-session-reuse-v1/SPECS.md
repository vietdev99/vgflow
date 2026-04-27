# Phase 17 — Test Session Reuse — SPECS

**Version:** v1 (lock 2026-04-27)
**Total decisions:** 6 (D-01..D-06)
**Source:** `DECISIONS.md` (this folder)

Executable contract per decision. Each section: input contract,
output contract, validation criteria. Reference to BLUEPRINT.md task IDs
in `[T-X.Y]` brackets at the end.

---

## Existing infra audit (read FIRST — what's already there)

| Component | Current state | Phase 17 action |
|---|---|---|
| `commands/vg/_shared/templates/interactive-helpers.template.ts` | 295 lines; has applyFilter/applySort/applyPagination/applySearch/readUrlParams/readVisibleRows/expectAssertion. **NO loginAs**, NO storage state APIs. | EXTEND — add `loginOnce` + `useAuth` exports. Don't break existing 7 helpers. |
| `commands/vg/_shared/templates/playwright-global-setup.template.ts` | DOES NOT EXIST | CREATE new template. |
| `commands/vg/_shared/templates/playwright-config.partial.ts` | DOES NOT EXIST | CREATE new fragment for users to merge. |
| `vg.config.template.md` | Has `design_assets:`, `mcp_servers:`, `design_fidelity:` (Phase 15) blocks but NO `test:` block. | EXTEND — add `test:` block with 5 keys (D-05). |
| `commands/vg/init.md` | Existing init flow detects project type. | EXTEND — when Playwright detected, copy 2 new templates + show merge instruction. |
| Phase 15 D-16 templates (10 files) | All 10 use `test.beforeEach(loginAs(page, ROLE))` pattern (commit `fd60d56`). | UPDATE — replace pattern with `test.use(useAuth(ROLE))`. |
| `scripts/validators/registry.yaml` | Has 60+ entries; Phase 15 added 11. | APPEND 1 new entry: `test-session-reuse`. |

**Critical:** No project requires `loginAs` to exist in helpers TODAY (consumers write their own). Phase 17 ADDS `loginOnce` as the standardized path, gives consumers a migration target. DO NOT remove `loginAs` from existing consumer projects — backward compat.

---

## D-01 — Storage state lifecycle

### Input contract
- `vg.config.md` declares roles via `environments.local.accounts[]`:
  ```yaml
  environments:
    local:
      base_url: "http://localhost:5173"
      accounts:
        admin:
          email: "admin@example.test"
          password: "change-me"
        publisher:
          email: "publisher@example.test"
          password: "change-me"
  ```
- `vg.config.test.storage_state_path` (D-05) — directory path relative to project root, default `apps/web/e2e/.auth/`.
- `vg.config.test.storage_state_ttl_hours` (D-05) — integer, default 24.

### Output contract
- One file per role at `${storage_state_path}/<role>.json` containing Playwright `BrowserContext.storageState()` JSON shape:
  ```json
  {
    "cookies": [{"name": "session", "value": "...", "domain": "...", "path": "/", ...}],
    "origins": [{"origin": "http://localhost:5173", "localStorage": [...]}]
  }
  ```
- Sidecar `.meta.json` next to each:
  ```json
  {
    "role": "admin",
    "created_at": "2026-04-27T10:00:00Z",
    "config_hash": "sha256-of-account-block",
    "ttl_hours": 24
  }
  ```

### Validation criteria
- File age > `ttl_hours * 3600` seconds → considered stale, must regenerate.
- `config_hash` mismatch (account credentials changed) → regenerate.
- Missing file → regenerate.

### .gitignore enforcement
- `/vg:init` appends `apps/web/e2e/.auth/` to `.gitignore` if not present.
- WARN at install time if `.auth/` already tracked in git history.

### Acceptance
- Run `loginOnce("admin", { storagePath: ".auth/" })` on a fresh project → file created, cookies present.
- Re-run within TTL → returns same path, NO new login (skip log).
- Modify config password → re-run → regenerate (config_hash mismatch detected).

`[T-1.2 implements; T-2.1 verifies via fixture]`

---

## D-02 — Helper template: `loginOnce` + `useAuth`

### Input contract
- `loginOnce(role: string, opts?: LoginOnceOptions): Promise<string>`
  - `opts.storagePath?: string` — default reads from VG_STORAGE_STATE_PATH env var, fallback `apps/web/e2e/.auth/`
  - `opts.strategy?: 'auto' | 'api' | 'ui'` — default `auto`: try POST `/api/login` first, fallback to UI form.
- `useAuth(role: string): { storageState: string }` — sync function returning Playwright fixture override.

### Output contract
```typescript
// In a generated spec:
const ROLE = 'admin';
const ROUTE = '/admin/sites';

test.use(useAuth(ROLE));   // ← replaces test.beforeEach(loginAs)

test.beforeEach(async ({ page }) => {
  await page.goto(ROUTE);  // page already authenticated via storageState
});

test('Sites table renders', async ({ page }) => {
  // ...
});
```

### Implementation strategy
- `loginOnce` reads credentials from `${VG_REPO_ROOT}/vg.config.md` via lightweight YAML parser (same as `build-uat-narrative.py` Phase 15).
- Strategy `auto`:
  1. Try `request.post(${baseUrl}/api/login, { data: { email, password } })`
  2. If response.ok && Set-Cookie present → use this context for storageState
  3. Else fallback to UI: `page.goto('/login')` + `page.fill` + `page.click`
- Idempotency check at start: read `.meta.json`, if fresh + matching config_hash → return path immediately, skip work.

### Validation criteria
- TypeScript compiles cleanly when added to helper file.
- `interactive-helpers.template.ts` total LOC ≤ 500 (was 295, allow +200 for new exports + types).
- Existing 7 helpers UNCHANGED (regression test diff against pre-Phase17 file).

### Acceptance
- Consumer copies new helper template → TypeScript build passes.
- Sample spec using `test.use(useAuth('admin'))` → loads with cookie pre-populated.
- Removing `.auth/admin.json` → `loginOnce` recreates.

`[T-1.1 + T-1.2 implement; T-2.1 verifies]`

---

## D-03 — Update Phase 15 D-16 templates

### Input contract
- 10 templates in `commands/vg/_shared/templates/`:
  - `filter-coverage.test.tmpl`, `filter-stress.test.tmpl`, `filter-state-integrity.test.tmpl`, `filter-edge.test.tmpl`
  - `pagination-navigation.test.tmpl`, `pagination-url-sync.test.tmpl`, `pagination-envelope.test.tmpl`, `pagination-display.test.tmpl`, `pagination-stress.test.tmpl`, `pagination-edge.test.tmpl`

### Required changes per template
**REMOVE:**
```typescript
test.beforeEach(async ({ page }) => {
  await loginAs(page, ROLE);
  await page.goto(ROUTE);
});
```

**REPLACE WITH:**
```typescript
test.use(useAuth(ROLE));

test.beforeEach(async ({ page }) => {
  await page.goto(ROUTE);
});
```

**IMPORT line update** in each template:
```typescript
// BEFORE:
import { loginAs } from '../helpers';
import { applyFilter, ... } from '../helpers/interactive';

// AFTER:
import { useAuth } from '../helpers/interactive';   // ← useAuth lives in interactive
import { applyFilter, ... } from '../helpers/interactive';
```

### Backward compat
- Old generated specs (pre-Phase 17 regen) keep working until consumer re-runs `/vg:test --recodegen-interactive`.
- `loginAs` legacy export STAYS in helper template (D-02) so old specs don't break.

### Acceptance
- `node skills/vg-codegen-interactive/filter-test-matrix.mjs` smoke test renders 10 files; grep shows ZERO `loginAs(` calls; grep shows 10 `test.use(useAuth(` calls (one per file).
- Phase 15 acceptance test `test_phase15_acceptance.py::TestPhase15Templates` extended: assert each template contains `useAuth` AND does NOT contain `loginAs`.

`[T-3.1 implements; T-5.1 acceptance test extends]`

---

## D-04 — Playwright global-setup template

### Input contract
- 2 new template files at `commands/vg/_shared/templates/`:
  1. `playwright-global-setup.template.ts` — full module
  2. `playwright-config.partial.ts` — fragment with `globalSetup` + `globalTeardown` lines for user to merge

### Output contract — `playwright-global-setup.template.ts`
```typescript
// AUTO-INSTALLED by /vg:init when Playwright detected.
// Customize freely; VG never overwrites unless --force.
import { chromium, FullConfig } from '@playwright/test';
import { loginOnce } from './helpers/interactive';

async function globalSetup(config: FullConfig) {
  const roles = process.env.VG_ROLES?.split(',') ?? ['admin'];
  for (const role of roles) {
    await loginOnce(role.trim());
  }
}

export default globalSetup;
```

### Output contract — `playwright-config.partial.ts`
```typescript
// Add this line to your playwright.config.ts:
//
//   globalSetup: require.resolve('./e2e/global-setup'),
//
// And ensure your project entry in `projects` includes:
//
//   use: { baseURL: 'http://localhost:5173' }
//
// The global setup populates apps/web/e2e/.auth/<role>.json files
// before any test runs. Tests then use test.use(useAuth(ROLE)) to
// pre-load that storage state.
```

### Implementation hooks
- `/vg:init` (init.md) extends step "detect Playwright" branch:
  - Check `playwright.config.{ts,js}` exists in project root or `apps/web/`
  - Copy `playwright-global-setup.template.ts` → `${E2E_DIR}/global-setup.ts` (skip if exists)
  - Show merge instructions from `playwright-config.partial.ts` to user

### Acceptance
- Sample consumer with Playwright detected → init writes `e2e/global-setup.ts` + shows merge hint.
- Consumer manually merges → `npx playwright test --list` shows globalSetup wired.

`[T-4.1 + T-4.2 implement]`

---

## D-05 — vg.config defaults

### Input contract
Append to `vg.config.template.md` (after existing `design_fidelity:` block, before `# === Bug Reporting ===` section):

```yaml
# ─── Test session reuse (Phase 17 D-05) ──────────────────────────────
# Cache login state per role so /vg:test runs don't re-login per spec.
# storage_state_path: relative to project root; created by global-setup.ts.
# ttl_hours: regenerate auth files older than this; 24 = once per day.
# playwright.workers: parallel test runners; 4 is comfortable on dev laptop.
# playwright.fully_parallel: run files in parallel within workers.
# playwright.reuse_existing_server: don't restart dev server between runs.
test:
  storage_state_path: "apps/web/e2e/.auth/"
  storage_state_ttl_hours: 24
  playwright:
    workers: 4
    fully_parallel: true
    reuse_existing_server: true
  login_strategy: "auto"  # auto | api | ui
```

### Implementation hooks
- `/vg:test` step 5d-pre reads these 5 keys via existing config parser, exports as env vars (`VG_STORAGE_STATE_PATH`, `VG_STORAGE_STATE_TTL_HOURS`, etc.) consumed by global-setup + helpers.
- `/vg:doctor` (existing skill) extends checks: warn if user's `playwright.config.ts` has `workers: 1` while `vg.config.test.playwright.workers > 1` (config drift).

### Acceptance
- Fresh `vg.config.md` from template has `test:` block.
- `/vg:test` log shows resolved values: `ℹ Test session reuse: storage=apps/web/e2e/.auth/, workers=4, ttl=24h, strategy=auto`.

`[T-4.3 implements vg.config; T-5.1 acceptance verifies]`

---

## D-06 — Validator `verify-test-session-reuse.py`

### Input contract
- `--phase <id>` REQUIRED — phase to scan
- `--tests-glob <pattern>` OPTIONAL — default scans `apps/web/e2e/generated/*.spec.{ts,js}` and `apps/*/e2e/generated/*.spec.{ts,js}`
- `--strict` OPTIONAL — escalate WARN to BLOCK (used after 2 release cycles per D-06 plan)

### Logic
1. Find all generated spec files under tests-glob.
2. For each spec file:
   - Count occurrences of `loginAs(` outside comment lines.
   - Count occurrences of `test.use(useAuth(` calls.
   - Detect: file uses `test.beforeEach` AND contains `loginAs` → flag as "stale codegen pattern".
3. Aggregate:
   - 0 stale specs → PASS
   - ≥1 stale + non-strict → WARN with per-file breakdown
   - ≥1 stale + strict → BLOCK

### Output contract
Standard `vg.validator-output` JSON shape (matches `_common.Output`):
```json
{
  "validator": "test-session-reuse",
  "verdict": "WARN",
  "evidence": [
    {
      "type": "stale_codegen_pattern",
      "message": "Spec uses beforeEach(loginAs) — expected test.use(useAuth)",
      "file": "apps/web/e2e/generated/g-campaign-list-status-filter-coverage.spec.ts",
      "line": 16,
      "fix_hint": "Re-run /vg:test {phase} --recodegen-interactive after Phase 17 install."
    }
  ],
  "duration_ms": 42
}
```

### Wiring
- Registered in `scripts/validators/registry.yaml`:
  ```yaml
  - id: test-session-reuse
    path: .claude/scripts/validators/verify-test-session-reuse.py
    severity: warn
    phases_active: [test]
    domain: test
    runtime_target_ms: 1000
    added_in: v2.11.0-phase-17
    description: "Detect generated specs still using legacy beforeEach(loginAs) pattern"
  ```
- Wired into `commands/vg/test.md` step 5d-r7 (existing console monitoring gate position):
  ```bash
  TSR_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-test-session-reuse.py"
  if [ -x "$TSR_VAL" ]; then
    ${PYTHON_BIN} "$TSR_VAL" --phase "${PHASE_NUMBER}" \
      > "${VG_TMP}/test-session-reuse.json" 2>&1 || true
    TSR_V=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" "${VG_TMP}/test-session-reuse.json" 2>/dev/null)
    case "$TSR_V" in
      PASS) echo "✓ D-06 test session reuse: PASS — all generated specs use useAuth" ;;
      WARN) echo "⚠ D-06 test session reuse: WARN — see ${VG_TMP}/test-session-reuse.json" ;;
      *)    echo "ℹ D-06 test session reuse: $TSR_V" ;;
    esac
  fi
  ```

### Acceptance
- Test fixture: `useAuth`-style spec → PASS.
- Test fixture: `beforeEach(loginAs)` spec → WARN.
- Same fixture with `--strict` → BLOCK.

`[T-3.2 implements; T-5.1 unit tests]`

---

## Cross-decision dependencies

```
D-01 storage lifecycle
   │
   ▼
D-02 loginOnce + useAuth helper      D-04 global-setup template
   │                                    │
   └─────────┬──────────────────────────┘
             │
             ▼
D-03 update 10 P15 templates
             │
             ▼
D-05 vg.config defaults  ←  D-06 validator (catches drift)
```

- D-01 + D-02 are parallel-able (same helper file but different exports).
- D-03 strictly depends on D-02 export shape.
- D-04 strictly depends on D-02 (uses `loginOnce`).
- D-06 validator is independent of all others (pure file scan).
- D-05 config additions are independent.

`[See BLUEPRINT.md for execution order + parallelism plan]`
