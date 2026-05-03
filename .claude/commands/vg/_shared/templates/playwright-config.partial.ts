// =============================================================================
// PLAYWRIGHT CONFIG MERGE FRAGMENT — Phase 17 D-04
// =============================================================================
//
// This file is NOT meant to be run as-is. It documents the lines you must
// merge into your existing `playwright.config.ts` so Phase 17 global setup
// (e2e/global-setup.ts) wires correctly.
//
// =============================================================================
//
// 1) ADD THESE FIELDS to your `defineConfig({...})` block:
//
//    export default defineConfig({
//      testDir: './e2e',
//      fullyParallel: true,                       // ← P17 D-05: parallel workers
//      workers: process.env.CI ? 2 : 4,           // ← P17 D-05: per-host workers
//      reuseExistingServer: !process.env.CI,      // ← P17 D-05: dev server reuse
//      globalSetup: require.resolve('./e2e/global-setup'),  // ← P17 D-04: WIRES auth
//      use: {
//        baseURL: process.env.VG_BASE_URL ?? 'http://localhost:5173',
//        // Storage state DEFAULT — individual specs override via test.use(useAuth(ROLE))
//        // (P17 D-02 helper). Leave default unset; specs declare per-role state.
//      },
//      // ... existing projects, reporter, etc.
//    });
//
// =============================================================================
//
// 2) APPEND TO .gitignore (if not already):
//
//    # Phase 17 — Playwright auth storage state (do NOT commit)
//    apps/web/e2e/.auth/
//    e2e/.auth/
//
// =============================================================================
//
// 3) (OPTIONAL) Set per-CI roles via VG_ROLES env var:
//
//    # All roles (slow first run, fast subsequent within TTL):
//    VG_ROLES=admin,publisher,advertiser npx playwright test
//
//    # Smoke subset (CI fast path):
//    VG_ROLES=admin npx playwright test --grep '@smoke'
//
// =============================================================================
//
// HOW VG USES THIS
// ----------------
//   * /vg:init detects existing playwright.config.ts and prints the
//     diff-style merge hint above (does NOT auto-edit your config — too
//     project-specific).
//   * /vg:test step 5d-pre verifies the lines are present and warns if not.
//   * verify-test-session-reuse.py (P17 D-06) catches generated specs
//     drifting back to legacy beforeEach(loginAs) pattern.
