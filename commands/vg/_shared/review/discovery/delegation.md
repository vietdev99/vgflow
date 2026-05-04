# vg-review-browser-discoverer — input/output contract (delegation appendix, NOT a step)

This document is the contract between the slim entry / overview.md and the
`vg-review-browser-discoverer` subagent (Task 18). The orchestrator builds
the input capsule from environment variables and CLI flags resolved in
preflight, the subagent executes the workflow inside `.claude/agents/vg-review-browser-discoverer/SKILL.md`,
and returns the output schema below.

---

## Input capsule (orchestrator → subagent)

JSON document delivered as the `prompt` field of the `Agent(...)` spawn
call (per plan §C, the spawn tool is `Agent`, not `Task`).

```json
{
  "phase_number":  "<string>      e.g. \"7.12\"",
  "phase_dir":     "<absolute path to phase directory>",
  "phase_profile": "<feature|hotfix|bugfix|migration|infra|docs>",

  "scanner":       "<haiku-only|codex-inline|codex-supplement|gemini-supplement|council-all>",
  "method":        "<spawn|manual|hybrid>",
  "env":           "<local|sandbox|staging|prod>",
  "mode":          "<full|evaluate-only|retry-failed|re-scan-goals|dogfood>",
  "spawn_mode":    "<parallel|sequential|none>   # v1.9.4 R3.3 — mobile=sequential, cli=none",
  "max_haiku":     5,
  "full_scan":     false,
  "with_probes":   false,

  "retry_views":   ["<view_url>", ...]      # populated when mode=retry-failed
                                            # OR mode=re-scan-goals OR mode=dogfood
                                            # (resolved from goal_sequences[gid].start_view)

  "re_scan_goals": "<G-XX,G-YY,G-ZZ>",      # populated when mode=re-scan-goals OR dogfood

  "scope_paths":   ["<route_pattern>", ...] # from REVIEW-LENS-PLAN.json
                                            # (lens planner emits per-profile coverage list)

  "role_matrix":   {                        # from vg.config.md credentials_map
    "admin":     {"username": "...", "password_env": "VG_ADMIN_PW"},
    "publisher": {"username": "...", "password_env": "VG_PUB_PW"},
    "advertiser":{"username": "...", "password_env": "VG_ADV_PW"},
    "guest":     null
  },

  "vg_load_hint":  "use vg-load --phase ${PHASE_NUMBER} --artifact goals --goal G-NN for per-goal briefing instead of cat ${PHASE_DIR}/TEST-GOALS.md",

  "ripple_priority_views": [<from .ripple-browser-priorities.json if exists>]
}
```

---

## Subagent workflow (high-level — SKILL.md is authoritative)

1. Initialize Playwright via MCP slot allocation (slots `playwright1` … `playwright5`).
2. **2a — deploy + preflight** to `env` (health check, optional infra-auto-start, optional DB seed, optional auth bootstrap).
3. **2b-1 — navigator** (1 Haiku agent, login + sidebar walk) → `nav-discovery.json` listing every view.
4. **2b-2 — parallel/sequential workers** per `spawn_mode`:
   - up to `max_haiku` Haiku scanners (or `codex-inline` main orchestrator scan, or `manual` prompt-file emission).
   - Each worker follows `.claude/skills/vg-haiku-scanner/SKILL.md` verbatim.
   - Per-view atomic artifact: `${phase_dir}/scan-{view_slug}.json`.
   - vg-load: workers should call `vg-load --phase {phase_number} --artifact goals --goal {gid}` for per-goal briefing instead of loading the whole TEST-GOALS.md flat (~8K lines on large phases).
5. **2b-3 — goal sequence recording** — for each goal in TEST-GOALS, walk the sequence in browser, capture `goal_sequences[gid].steps[]` + mutation evidence into RUNTIME-MAP.json.
6. **Cleanup** — close browser tabs, release Playwright slots.

### Branching by `mode`

| mode | Skip | Run |
|---|---|---|
| `full` | nothing | 2a + 2b-1 + 2b-2 (all views) + 2b-3 (all goals) |
| `evaluate-only` | 2a + 2b-1 + 2b-2 | 2b-3 only (consume existing scan-*.json) |
| `retry-failed` | 2a (assume sandbox up) + 2b-1 (reuse nav-discovery.json) | 2b-2 on `retry_views` only + 2b-3 on failed goals |
| `re-scan-goals` | 2a + 2b-1 (matrix-bypass) | 2b-2 on `retry_views` + 2b-3 scoped to `re_scan_goals` |
| `dogfood` | 2a + 2b-1 | 2b-2 on `retry_views` (resolved from all mutation goals) + 2b-3 same scope |

---

## Output contract (subagent → orchestrator)

Subagent MUST return this JSON to the spawn caller:

```json
{
  "status":               "OK|PARTIAL|FAIL",
  "views_discovered":     [
    {
      "view_id":    "<slug>",
      "url":        "<absolute_url>",
      "role":       "<admin|publisher|advertiser|guest>",
      "scan_path":  "${phase_dir}/scan-{slug}.json",
      "issue_count":<int>,
      "duration_s": <float>
    }
  ],
  "scan_artifacts":       ["<absolute paths>"],
  "runtime_map_path":     "${phase_dir}/RUNTIME-MAP.json",
  "nav_discovery_path":   "${phase_dir}/nav-discovery.json",
  "playwright_slots_used":[1, 2, 3],
  "haiku_agents_spawned": <int>,
  "exploration_metrics":  {
    "actions_total":  <int>,
    "wall_minutes":   <float>,
    "stagnation_breaks": <int>
  },
  "errors":               [
    {"view": "<slug>", "code": "navigator_timeout|stagnation|element_missing|...", "msg": "..."}
  ]
}
```

The orchestrator validates:
- `runtime_map_path` exists and is valid JSON with non-empty `views`.
- `nav_discovery_path` exists.
- At least one `scan_artifacts` entry exists.
- `errors[]` length is reported but non-fatal (partial scans continue → fix loop).

---

## Allowed tools (subagent)

- `Read`, `Write`, `Bash`, `Glob`, `Grep`
- `Agent` (for Haiku worker spawn ≤ `max_haiku`)
- MCP Playwright (slot-allocated): `mcp__playwright1..5__browser_*`
- `mcp__pencil__*` / `mcp__penboard__*` are NOT in scope for review

## Forbidden

- DO NOT call other VG commands recursively (no `/vg:test`, `/vg:roam`, `/vg:scope` from within the subagent).
- DO NOT spawn non-Haiku subagents (Sonnet/Opus would burn budget).
- DO NOT exceed 5 Playwright slots (anti-DOS — system limit, not config).
- DO NOT emit RUNTIME-MAP without validation — incomplete map = downstream verdict reads stale entries.
- DO NOT skim TEST-GOALS.md flat-read for per-goal briefing on phases with > 20 goals — use `vg-load --goal G-NN` instead.

## Failure modes the orchestrator tolerates (PARTIAL)

- Up to 30% of views with `partial` scan status — fix loop will retry.
- Up to 2 worker timeouts on a non-critical view — recorded in `errors[]`.

## Failure modes that BLOCK (status=FAIL)

- Navigator (2b-1) fails → no view inventory → cannot proceed.
- Auth bootstrap fails for the role required by > 50% of goals.
- All scan-*.json missing or empty.
- RUNTIME-MAP.json malformed JSON.
- Playwright slot allocation fails 3x in a row (likely sandbox down).
