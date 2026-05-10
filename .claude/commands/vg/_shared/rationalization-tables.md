---
name: vg:_shared:rationalization-tables
description: Static reference of common AI rationalizations encountered when running VG pipeline steps, with concrete rebuttals. Augments runtime rationalization-guard.md (which spawns isolated Haiku for novel cases) by capturing the recurring patterns up front.
---

# Rationalization Tables — Common Excuses vs Reality

Inspired by [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)' "anti-rationalization tables" pattern (38k stars validates the approach). VG extends it with VG-specific gate / artifact / runtime patterns.

When the executing agent is tempted to skip a step, the temptation is almost always one of these patterns. **Read the pattern, find the rebuttal, run the gate.**

For novel justifications not in this table, runtime spawns a separate Haiku via `_shared/rationalization-guard.md` for adjudication.

---

## A. Test / verification skips

| Excuse | Reality |
|---|---|
| "Test pass rồi, không cần edge cases nữa" | Edge cases là nơi sản phẩm chết. Happy path test = không có evidence cho 90% real-world failures |
| "User chỉ cần feature work, test sau cũng được" | Untested behavior = tech debt that compounds. v2.79.1 fixed 6 issues all tied to "skipped test" patterns |
| "Bug fix simple, không cần repro test" | Fix without repro test = no proof fix solves the actual bug. 30% of bug fixes regress without repro test |
| "Test này flaky, skip một lần thôi" | Flaky test → fix flakiness or delete. "Skip một lần" becomes "always skip" within 2 weeks |
| "Manual test passed, automated optional" | Manual tests don't persist. Next regression = nobody remembers to re-run |
| "Coverage giảm 1% chấp nhận được" | Coverage ratchet: monotonic increase only. 1% drift × 12 months = 12% lost |

## B. Gate / contract skips

| Excuse | Reality |
|---|---|
| "Marker này tôi biết rồi không cần emit" | Hook checks marker file existence, not your knowledge. No marker = step not done = run incomplete |
| "Step skip vì command-line nói là optional" | "Optional" trong VG = profile-dependent (web vs mobile). Profile chưa filter ra → step REQUIRED for current profile |
| "Telemetry event missed, fake nó vào events.db" | Hash-chained events.db. Manual insert breaks chain → audit fails. Fix root cause, never forge |
| "Override reason 'should work now' đủ rồi" | Rationalization-guard subagent rejects vague reasons. ESCALATE → block. Be concrete: cite commit SHA + symptom + remediation plan |
| "/vg:scope discussion 5 rounds quá nhiều, skip 3-4" | Round 4 (UI) + 5 (tests) là where 60% scope creep gets caught. Skip = budget overrun next phase |

## C. Code change skips

| Excuse | Reality |
|---|---|
| "Refactor nhỏ, không cần plan/blueprint" | "Nhỏ" thường mask scope creep. /vg:blueprint catches the edge cases your eye missed |
| "Ripple analysis không cần, change isolated" | Hyrum's Law: every observable behavior has a consumer. "Isolated" = consumer unknown to you |
| "Test goal coverage matrix optional vì tôi đã test mental" | Mental test isn't reproducible. v2.79.1 #170 was caused by mental "PASS" assumed |
| "Skip code review vì tôi viết code, tôi review" | Author bias is structural — different runtime (CrossAI / Codex review) catches what author misses |
| "API contract optional cho internal endpoint" | "Internal" today = "external integration partner asks for it" 6 months later. Contract upfront cost = 1h; retrofit = 3 days |

## D. Migration / breaking change skips

| Excuse | Reality |
|---|---|
| "Backwards compat shim, viết sau cũng được" | Without shim, downstream projects break the moment they pull. Ship dual-mode FIRST, deprecate gradually (3 minor cycles minimum) |
| "Migration script tự AI viết được, không cần helper" | One-shot migration = unrepeatable. Dedicated helper = idempotent + tested + auditable |
| "Schema bump v1→v2, không cần version field" | Schema_version field = forward-compat. Without it, v2 readers can't detect v1 docs → silent corruption |
| "Breaking change announced trong commit message đủ rồi" | Commits get squashed. CHANGELOG.md + UPGRADE-NOTES.md persist. Both required for major bumps |

## E. Deploy / production skips

| Excuse | Reality |
|---|---|
| "Deploy to staging skipped, prod work giống staging" | Staging catches infra drift. Skipping = 30% chance prod-only bug |
| "Health check pass thì rollback target không quan trọng" | Rollback target IS the next deploy's safety net. Without it, post-deploy bug = manual `git log` archaeology |
| "Lock file unnecessary, tôi là người duy nhất deploy" | "Là duy nhất" today, "team scaled to 5" next quarter. Lock now = $0 cost; race condition later = incident |
| "Phase context optional cho deploy state" | phase_context = audit trail for "which phase introduced this regression". Drop it = blame analysis impossible |

## F. Documentation skips

| Excuse | Reality |
|---|---|
| "Code self-documenting, comment redundant" | Self-documenting code conveys WHAT, not WHY. Why-comments are non-redundant; what-comments are |
| "ADR cho decision này quá small" | "Small" decisions accumulate. Without ADR, 6-months-later 'Why did we choose X?' = code archaeology |
| "Update README sau khi feature ship" | README + CHANGELOG ship together with code, or never. "Sau" = forgotten |
| "Comments không cần, test name đủ rõ" | Test name describes EXPECTATION. Code comment captures CONSTRAINT (Hyrum invariant, race window, timeout reason) |

---

## How to use this table

1. **Before** invoking `--allow-*` / `--skip-*` / `--override-reason`: scan this table for matching pattern.
2. If matched → don't override; run the gate or fix the underlying gap.
3. If no match → runtime guard (`_shared/rationalization-guard.md`) spawns Haiku subagent for novel adjudication.
4. **Add new patterns here** when a new common rationalization shows up across 2+ phases. Edit + commit; the table self-evolves.

## Cross-references

- Runtime adjudicator: `_shared/rationalization-guard.md`
- Engineering principles: `_shared/eng-principles.md` (cites Hyrum's Law, Shift Left, etc.)
- Skill discovery: `_shared/discovery-flowchart.md`
- Pipeline taxonomy: `commands/vg/LIFECYCLE.md`
