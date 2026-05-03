// =============================================================================
// PLAYWRIGHT GLOBAL SETUP — Phase 17 D-04 reference template
// =============================================================================
//
// HOW TO USE
// ----------
//   1. /vg:init copies this file to your e2e dir (default e2e/global-setup.ts).
//      If `/vg:init` didn't run, copy manually from
//      `.claude/commands/vg/_shared/templates/playwright-global-setup.template.ts`.
//
//   2. Wire into playwright.config.ts. Add the line shown in
//      playwright-config.partial.ts (sibling template) — merge instructions
//      printed by /vg:init.
//
//   3. Each role declared in vg.config.md
//      (environments.local.accounts.<role>) gets one .auth/<role>.json file
//      populated before any test runs. Tests then use:
//        test.use(useAuth(ROLE));
//      (Phase 17 D-02 helper — see commands/vg/_shared/templates/interactive-helpers.template.ts)
//
// CUSTOMIZATION
// -------------
//   * Override the role list per CI job: VG_ROLES=admin,publisher npm test
//   * Override storage path: VG_STORAGE_STATE_PATH=apps/web/e2e/.auth-ci/
//   * Override TTL: VG_STORAGE_STATE_TTL_HOURS=8 (default 24)
//   * Skip global setup entirely: VG_SKIP_GLOBAL_SETUP=1 (debug only)
//
// VG never overwrites this file unless --force passed to /vg:init.
// =============================================================================

import type { FullConfig } from '@playwright/test';
import { loginOnce } from './helpers/interactive';

async function globalSetup(_config: FullConfig): Promise<void> {
  if (process.env.VG_SKIP_GLOBAL_SETUP === '1') {
    console.log('[vg/global-setup] VG_SKIP_GLOBAL_SETUP=1 — skipping');
    return;
  }

  // Roles default to 'admin'. Override via VG_ROLES env var
  // (comma-separated, e.g. VG_ROLES=admin,publisher,advertiser).
  const roles = (process.env.VG_ROLES ?? 'admin')
    .split(',')
    .map((r) => r.trim())
    .filter(Boolean);

  console.log(`[vg/global-setup] preparing storage state for ${roles.length} role(s): ${roles.join(', ')}`);

  for (const role of roles) {
    try {
      const start = Date.now();
      const path = await loginOnce(role);
      const elapsedMs = Date.now() - start;
      console.log(
        `[vg/global-setup]   ✓ ${role} → ${path} (${elapsedMs}ms; cache hit if <50ms)`,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`[vg/global-setup]   ⛔ ${role}: ${msg}`);
      // Re-throw so Playwright aborts the test run (better than silently
      // running tests against missing auth state which would cascade-fail).
      throw err;
    }
  }
}

export default globalSetup;
