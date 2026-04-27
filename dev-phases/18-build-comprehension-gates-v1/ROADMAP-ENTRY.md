# Phase 18 — Build Comprehension Gates — Roadmap Entry

```yaml
id: phase-18
slug: build-comprehension-gates-v1
title: "Build Comprehension Gates — pre-execution echo + prompt completeness audit + wave goal-coverage BLOCK"
estimated_hours: 6-9
priority: HIGH
risk: LOW  # add-only changes; no rewrite of hot path; piggybacks on P15 T11.2 + P16 T1.2 persistence
depends_on: [phase-15, phase-16]   # uses .build/wave-N/executor-prompts/ + .meta.json sidecar
unblocks: []                       # standalone safety; not gating other phases
created: 2026-04-27
status: planning
profile: any   # applies to every build profile (web-fullstack, backend-only, mobile, etc.)
deliverables:
  - "vg-executor-rules.md: pre-code comprehension echo step (D-01)"
  - "verify-prompt-completeness.py: spawned prompt block-content + ref resolution audit (D-02)"
  - "build.md step 8d: goal-coverage --block per-wave + verify-comprehension-echo wire (D-03)"
acceptance:
  - "Fixture wave: executor skips comprehension echo → wave 8d gate FAIL with 'echo missing'"
  - "Fixture wave: prompt persisted with empty <decision_context> → verify-prompt-completeness BLOCK before spawn"
  - "Fixture wave: 5/5 commits but 1 G-XX has zero file impl → BLOCK at wave 8d (not deferred to /vg:review)"
  - "All 3 new validators registered in registry.yaml + acceptance smoke pass"
notes:
  - "Source: AUDIT 2026-04-27 (this folder predecessor — Phase 17 audit conversation) → 3 P0 patches (LEAK 1, 2, 3)"
  - "Smaller scope vs Phase 16: 3 decisions, ~120 LOC Python total, single-day effort"
  - "Risk LOW: D-01 is doc + rule edit; D-02 is new script + 1 wire; D-03 is flag flip + position move"
  - "Compounds with Phase 16 task-fidelity-lock: P16 hashes the task body, P18 verifies the executor read it"
```
