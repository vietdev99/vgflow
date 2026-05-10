---
name: vg:_shared:discovery-flowchart
description: Visual decision tree mapping user intent → which VG slash command to invoke. Inspired by addyosmani/agent-skills meta-skill flowchart pattern. /vg:next does runtime routing; this doc visualizes the static map.
---

# VG Skill Discovery Flowchart

User has an intent. Which `/vg:*` command applies? Below is the static map. For runtime routing (read project state, find next pending step), use `/vg:next`.

---

## Top-level decision tree

```mermaid
flowchart TD
    Start[User has intent] --> Q1{Project<br/>initialized?}
    Q1 -->|No / never| ProjInit[/vg:project<br/>or /vg:init]
    Q1 -->|Yes| Q2{Have ROADMAP.md<br/>+ phase planned?}

    Q2 -->|No phases yet| Roadmap[/vg:roadmap]
    Q2 -->|Add new phase| AddPhase[/vg:add-phase]
    Q2 -->|Yes| Q3{Specs exist for<br/>current phase?}

    Q3 -->|No| Specs[/vg:specs]
    Q3 -->|Yes| Q4{Scope discussed?<br/>CONTEXT.md exists?}

    Q4 -->|No| Scope[/vg:scope]
    Q4 -->|Yes| Q5{Plan + API<br/>contracts done?}

    Q5 -->|No| Blueprint[/vg:blueprint]
    Q5 -->|Yes| Q6{Code implemented?<br/>SUMMARY.md exists?}

    Q6 -->|No| Build[/vg:build]
    Q6 -->|Yes| Q7{Code reviewed?<br/>RUNTIME-MAP exists?}

    Q7 -->|No| Review[/vg:review]
    Q7 -->|Yes| Q8{Tests written<br/>+ goal verified?}

    Q8 -->|No| Test[/vg:test]
    Q8 -->|Yes| Q9{Phase accepted<br/>by user?}

    Q9 -->|No| Accept[/vg:accept]
    Q9 -->|Yes — deploy needed| Deploy[/vg:deploy]
    Q9 -->|Yes — done| Done([Phase complete])

    style ProjInit fill:#e1f5ff
    style Done fill:#c8e6c9
```

---

## By intent (alphabetical lookup)

| User says... | Run |
|---|---|
| "Bắt đầu project mới" | `/vg:project` (or legacy `/vg:init`) |
| "Thêm phase mới" | `/vg:add-phase` |
| "Bug ở phase X, fix" | `/vg:debug` (focused fix loop, no full review) |
| "Bị lỗi gì đó, không biết do đâu" | `/vg:debug` |
| "Cần specs cho phase" | `/vg:specs` |
| "Specs xong rồi, cần thảo luận sâu" | `/vg:scope` (5 rounds) |
| "Plan + API contract" | `/vg:blueprint` |
| "Build code theo plan" | `/vg:build` |
| "Review code đã build" | `/vg:review` |
| "Test goals" | `/vg:test` |
| "User UAT" | `/vg:accept` |
| "Deploy lên env" | `/vg:deploy` |
| "Browse codebase tổng quát" | `/vg:roam` |
| "Stage tiếp theo là gì?" | `/vg:next` (auto-detect) |
| "Show progress all phases" | `/vg:progress` |
| "Health check + diagnose" | `/vg:doctor` (routes to health/integrity/recover) |
| "Update VG to latest" | `/vg:update` |
| "Install / re-install hooks" | `/vg:install` (v3 marker-driven) |
| "Sync codex skills mirror" | `/vg:sync` |
| "Phase được accept rồi, đóng milestone" | `/vg:complete-milestone` |
| "Plan changed, cập nhật phase" | `/vg:amend` |
| "Decision X cần đảo ngược" | `/vg:override-resolve` |
| "View bootstrap rules + memory" | `/vg:bootstrap` |
| "Promote / reject AI-proposed learning" | `/vg:learn` |
| "Auto-detect bug + push GitHub issue" | `/vg:bug-report` |
| "Statistics on gate overrides" | `/vg:gate-stats` |
| "Refresh graphify knowledge graph" | `/vg:map` |

---

## By lifecycle phase

| Phase | Commands |
|---|---|
| **Define** | `/vg:project`, `/vg:specs`, `/vg:scope`, `/vg:scope-review` |
| **Plan** | `/vg:blueprint`, `/vg:roadmap`, `/vg:add-phase`, `/vg:prioritize` |
| **Build** | `/vg:build`, `/vg:debug`, `/vg:amend` |
| **Verify** | `/vg:review`, `/vg:test`, `/vg:roam` |
| **Ship** | `/vg:accept`, `/vg:deploy`, `/vg:complete-milestone` |
| **Meta** | `/vg:doctor`, `/vg:health`, `/vg:integrity`, `/vg:recover`, `/vg:next`, `/vg:progress` |
| **Learn** | `/vg:bootstrap`, `/vg:learn`, `/vg:rule`, `/vg:lesson`, `/vg:reflector` |

---

## Adversarial detection

When user says "skip step X" or "do quickly":

| Symptom | Recommended action |
|---|---|
| "Skip /vg:scope, simple change" | Run `/vg:scope` anyway — round 4 (UI) + 5 (tests) catch 60% scope creep |
| "Test sau cũng được, build trước" | Pre-test gate blocks `/vg:test` if `/vg:review` failed; sequential matters |
| "Override gate với --skip-X" | Runtime guard (`_shared/rationalization-guard.md`) spawns Haiku adjudicator |
| "Có shortcut gì không" | Run `/vg:next` — it tells you the cheapest legitimate next step |

For full pattern catalogue: `_shared/rationalization-tables.md`.

---

## Cross-references

- Runtime routing: `commands/vg/next.md`
- Pipeline taxonomy: `commands/vg/LIFECYCLE.md`
- Engineering principles: `_shared/eng-principles.md`
- Anti-rationalization tables: `_shared/rationalization-tables.md`
