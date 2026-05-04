---
name: sandbox-test
description: VPS sandbox testing gate — deploy, unit/API via CLI agents, E2E via MCP Playwright (visible browser), auto-fix loop max 3 iterations
user-invocable: true
---

# Skill: Sandbox Test

Opus-orchestrated VPS testing gate.

**Pipeline position:** After build, before accept.

```
/vg:blueprint {X}        <- Plan + contracts
        |
/vg:build {X}            <- Execute plans
        |
/vg:test {X}             <- THIS: goal verify + test + fix loop
        |
/vg:accept {X}           <- Human UAT
```

## Usage
```
/sandbox-test 7.1                -- Full: deploy + test + fix loop
/sandbox-test 7.1 --skip-deploy  -- Code already on VPS
/sandbox-test 7.1 --fix-only     -- Retry fixes for known failures
```

## How It Works

1. **Load context** — TEST-GOALS, SUMMARY, CONTEXT, previous SANDBOX-TEST results
2. **Preflight** — verify services (config.services.{env})
3. **Deploy** — config.environments.{env}.deploy (build + restart)
4. **Pre-checks** — API<>UI field contract, i18n keys, TypeScript
5. **Plan** — identify test groups, assign CLIs for unit/API
6. **Unit/API** — CLI agents run vitest + curl via config.environments.{env}.run_prefix
7. **E2E browser** — Opus drives MCP Playwright directly (visible browser)
7.5. **Flow E2E** — If FLOW-SPEC.md exists: codegen -> run with checkpoint-resume
8. **Analyze + fix** — categorize failures, fix loop max 3 iterations
9. **Report** — generate SANDBOX-TEST.md with verdict

## Testing Model

| Type | Where | Driver |
|------|-------|--------|
| Unit tests (vitest) | Target env via run_prefix | CLI agents (crossai_clis) |
| API integration (curl) | Target env via run_prefix | CLI agents (crossai_clis) |
| E2E browser | Live domains | Opus via MCP Playwright |

## Rules

1. Unit/API on target env via run_prefix. E2E via MCP Playwright (visible browser).
2. NEVER use `npx playwright test` or delegate E2E to CLI agents — they run headless/invisible.
3. slowMo 800ms between browser actions — remote domains have network latency.
4. Login via browser form (NOT API cookie injection) — avoids cross-domain SameSite issues.
5. Console monitoring after every browser action — errors = test failure even if UI looks OK.
6. Content depth over existence — tab/modal must show content, not just exist.
7. Wide-view on every page — h1, KPI, table, toolbar, pagination, CTA.
8. CLIs fix source code, not test assertions.
9. E2E is NOT optional — if MCP Playwright unavailable, STOP (don't silently skip).
10. Paths from config: `config.environments.{env}.project_path`, `config.environments.{env}.run_prefix`.

## Files

| File | Purpose |
|------|---------|
| `.claude/skills/flow-scan/SKILL.md` | State machine extraction |
| `.claude/skills/flow-spec/SKILL.md` | Flow test specification |
| `.claude/skills/flow-codegen/SKILL.md` | Playwright flow test generation |
| `.claude/skills/flow-runner/SKILL.md` | Flow test execution + checkpoint |

## Output
`{config.paths.phases}/{phase}/SANDBOX-TEST.md` with verdict: PASSED / GAPS_FOUND / FAILED
