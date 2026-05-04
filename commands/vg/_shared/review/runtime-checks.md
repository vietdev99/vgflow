# review runtime checks (STEP 4.5 — phase2 exploration + visual + URL-state + UX runtime)

7 sub-steps in this ref group. Web-profile runs all; mobile profile substitutes
mobile_discovery + mobile_visual_checks variants.

This file is the slim index for the 7 sub-steps. Content is split across
sibling refs by axis:

- **Static / declaration checks** → see `runtime-checks-static.md`
  - `phase2_exploration_limits` — boundary enforcement (no infinite-crawl)
  - `phase2_7_url_state_sync` — URL ↔ component-state sync declaration check (file-scan)
- **Dynamic / browser+device checks** → see `runtime-checks-dynamic.md`
  - `phase2_mobile_discovery` — mobile profile discovery (Maestro)
  - `phase2_5_visual_checks` — visual regression vs design fingerprints (web)
  - `phase2_5_mobile_visual_checks` — mobile-specific visual gates
  - `phase2_8_url_state_runtime` — runtime URL state coherence (Playwright)
  - `phase2_9_error_message_runtime` — error message UX validation (Playwright)

<HARD-GATE>
You MUST execute every applicable sub-step before proceeding to STEP 5
(findings collect). Profile-aware:
- web-fullstack / web-frontend-only: run ALL applicable sub-steps in BOTH
  static and dynamic refs (skip mobile-only sub-steps)
- mobile-*: run mobile_discovery + mobile_visual_checks instead of
  phase2_5_visual_checks; static refs (limits + URL decl) still apply
- web-backend-only: SKIP all (no UI to check)

Each sub-step exits non-zero on critical fail; warn-severity steps
emit telemetry but don't block. Skipping silently detected by Stop
hook (markers in must_touch_markers contract are severity=warn —
emit telemetry but don't block run).

Read the matching sibling ref BEFORE running each sub-step. Do NOT
inline the heavy bash/Python from there into this file — the split is
the Anthropic Skill progressive-disclosure baseline (body < 200 lines
per ref).
</HARD-GATE>

---

## Step ID enumeration (preserved across split)

The Stop hook reads `must_touch_markers` from `commands/vg/review.md`
runtime contract. These IDs MUST exist somewhere in the sub-refs:

| Step ID                           | Profile                          | Sub-ref                       |
| --------------------------------- | -------------------------------- | ----------------------------- |
| `phase2_exploration_limits`       | web-fullstack/web-frontend-only  | runtime-checks-static.md      |
| `phase2_mobile_discovery`         | mobile-*                         | runtime-checks-dynamic.md     |
| `phase2_5_visual_checks`          | web-fullstack/web-frontend-only  | runtime-checks-dynamic.md     |
| `phase2_5_mobile_visual_checks`   | mobile-*                         | runtime-checks-dynamic.md     |
| `phase2_7_url_state_sync`         | web-fullstack/web-frontend-only  | runtime-checks-static.md      |
| `phase2_8_url_state_runtime`      | web-fullstack/web-frontend-only  | runtime-checks-dynamic.md     |
| `phase2_9_error_message_runtime`  | web-fullstack/web-frontend-only  | runtime-checks-dynamic.md     |

After each sub-step, the responsible bash block writes
`${PHASE_DIR}/.step-markers/<step_id>.done` AND calls
`vg-orchestrator mark-step review <step_id>`. Both lifecycle calls are
part of the verbatim copy-over to the sub-refs — do NOT add a layer of
indirection here.

---

## Routing

`commands/vg/review.md` routes to this file at STEP 4.5:

```
### STEP 4.5 — runtime checks (web/mobile profile)
Read `_shared/review/runtime-checks.md` and follow it exactly.
```

After reading this slim entry, descend into the sibling refs in the
order they appear in the section map above. Static refs first
(declarations), then dynamic refs (runtime probes) — this ordering
matches the original 1033-line file's natural flow and keeps
phase2_7 (declaration) before phase2_8 (runtime drift catch).
