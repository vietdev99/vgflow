# Stable Test Selectors — Build-time Strip Setup (v2.43.5)

This directory has scaffold snippets for stripping `data-testid` (and other
test-only attributes) from production builds. Per `vg.config.md > test_ids
.build_time_strip`, the attribute is present in dev/sandbox/staging but
removed in prod — keeping test specs stable while preventing crawlers from
mapping the UI in production.

## React + Vite

Install:
```bash
pnpm add -D babel-plugin-jsx-remove-data-test-id
```

Patch `apps/<app>/vite.config.ts`:
```ts
// vite.config.ts
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd());
  const isProd = env.NODE_ENV === "production" || mode === "production";

  return {
    plugins: [
      react({
        babel: {
          plugins: isProd
            ? [
                ["babel-plugin-jsx-remove-data-test-id", {
                  attributes: ["data-testid", "data-test"],
                }],
              ]
            : [],
        },
      }),
    ],
  };
});
```

## Next.js (SWC)

Add to `next.config.js`:
```js
module.exports = {
  compiler: {
    reactRemoveProperties:
      process.env.NODE_ENV === "production"
        ? { properties: ["^data-testid$", "^data-test$"] }
        : false,
  },
};
```

## Vue 3 + Vite

Use `vite-plugin-vue-attrs-strip` (or write a small custom Vite plugin):
```ts
// vite.config.ts
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const stripTestAttrs = () => ({
  name: "strip-data-testid",
  enforce: "pre" as const,
  transform(code: string, id: string) {
    if (process.env.NODE_ENV !== "production") return null;
    if (!/\.vue$/.test(id)) return null;
    return code.replace(/\sdata-testid\s*=\s*["'`][^"'`]*["'`]/g, "");
  },
});

export default defineConfig({
  plugins: [stripTestAttrs(), vue()],
});
```

## Svelte (vite-plugin-svelte)

```ts
// vite.config.ts — same custom plugin pattern
const stripTestAttrs = () => ({
  name: "strip-data-testid",
  transform(code: string, id: string) {
    if (process.env.NODE_ENV !== "production") return null;
    if (!/\.svelte$/.test(id)) return null;
    return code.replace(/\sdata-testid\s*=\s*["'`{][^"'`}]*["'`}]/g, "");
  },
});
```

## Verification

After setup, build production and grep — should be empty:
```bash
pnpm build && grep -r 'data-testid' apps/<app>/dist/ | head
```

Test specs run against dev/sandbox/staging (where the attribute IS present).
Production gets stripped HTML. Best of both worlds.

## Why this approach

- **One source of truth**: planner declares `<test_ids>` in PLAN.md → executor injects `data-testid` in source → codegen consumes via `getByTestId()`
- **i18n resilient**: text changes don't break specs because text isn't the selector
- **Crawl protection**: production HTML has no test IDs to scrape
- **Zero runtime cost**: build-time transform, no JS bundle bloat
- **Framework-agnostic**: same pattern works for React/Vue/Svelte/Next/Nuxt

## When NOT to enable

- If your test framework already has alt strategy (Playwright `page.locator('button:has-text(...)')` with hard-coded English aliases) — skip
- If you're shipping public-facing markup that benefits from testid for analytics tools (some dashboards use `data-test` as event tracking) — keep enabled in prod
- If your i18n library generates the same English fallback string consistently — text-matching may be acceptable
