---
name: vg:debug
description: Targeted bug-fix loop — analyze description, classify, fix, verify with user (no full review sweep)
argument-hint: '"<bug description>" [--phase=<N>] [--no-amend-trigger] [--resume=<debug-id>] [--isolate]'
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Task
  - SlashCommand
mutates_repo: true
runtime_contract:
  must_write:
    - .vg/debug/{debug_id}/DEBUG-LOG.md
  must_touch_markers:
    - 0_parse_and_classify
    - 1_discovery
    - 2_hypothesize_and_fix
    - 3_verify_and_loop
    - 4_complete
  must_emit_telemetry:
    - event_type: "debug.parsed"
    - event_type: "debug.classified"
    - event_type: "debug.fix_attempted"
    - event_type: "debug.user_confirmed"
    - event_type: "debug.completed"
    # gsd:debug ports — auto-emitted only when path triggers (severity=warn = optional)
    - event_type: "debug.resumed"
      severity: "warn"
    - event_type: "debug.checkpoint"
      severity: "warn"
    - event_type: "debug.paused"
      severity: "warn"
---


<LANGUAGE_POLICY>
You MUST follow `_shared/language-policy.md`. **NON-NEGOTIABLE.**

Mặc định trả lời bằng **tiếng Việt** (config: `language.primary` trong
`.claude/vg.config.md`, fallback `vi` nếu chưa set). Dùng ngôn ngữ con
người, không technical jargon. Mỗi thuật ngữ tiếng Anh xuất hiện lần đầu
trong narration: thêm giải thích VN trong dấu ngoặc (per
`_shared/term-glossary.md`).

Ví dụ:
- ❌ "Validator failed with 225 evidence count"
- ✅ "Validator báo 225 trường thiếu — chi tiết ở `[path]`. Mình sẽ sửa rồi chạy lại."

File paths, code identifiers (G-04, Wave 9, getUserById), commit messages,
CLI commands stay English. AskUserQuestion title + options + question prose:
ngôn ngữ config.
</LANGUAGE_POLICY>


<rules>
1. **Standalone session** — debug session lives in `.vg/debug/<id>/`, not phase-scoped (Q1 user choice).
2. **AskUserQuestion-driven loop** — no max iterations. Each loop end asks user: fixed / retry / more-info (Q2).
3. **Auto-classify** — AI picks discovery path (code-only / browser / network / infra / spec gap) without asking unless confidence < 80%.
4. **Spec gap → auto /vg:amend** — if classified as spec gap, auto-trigger `/vg:amend <phase>` (Q5=a).
5. **Browser MCP fallback** — if browser MCP unavailable + UI bug, write findings as amendment to phase (Q3) instead of blocking.
6. **Atomic commits per fix** — each fix attempt = 1 commit. Easy rollback if loop fails.
7. **No destructive actions** — fix code only. Don't drop tables, force-push, or delete branches.
</rules>

<objective>
Lightweight targeted bug-fix workflow. Use case: user gặp 1 bug cụ thể (ví dụ click /campaigns crash), thay vì chạy `/vg:review` (15-30 min full Haiku scan), chạy `/vg:debug "<mô tả>"` (3-5 min targeted) để:

1. Parse + classify bug từ natural language
2. Auto-pick discovery method
3. Generate hypothesis chain
4. Apply fix + commit atomic
5. Verify (reproduce)
6. AskUserQuestion loop until user confirms fixed

Output: `.vg/debug/<id>/DEBUG-LOG.md` + atomic commits. If detected spec gap → auto `/vg:amend`.
</objective>

<process>

**Config:** Read `.claude/commands/vg/_shared/config-loader.md` first.

### Preflight section (extracted v2.75.0 T6)

Read `_shared/debug/preflight.md` and follow it exactly.
Includes 1 step: 0_parse_and_classify.

Step coverage: 0_parse_and_classify.


### Discovery + hypothesize + fix (extracted v2.75.0 T7)

Read `_shared/debug/discovery-and-fix.md` and follow it exactly.
Includes 2 steps: 1_discovery, 2_hypothesize_and_fix.

Step coverage: 1_discovery, 2_hypothesize_and_fix.


### Verify + close (extracted v2.75.0 T8 — final)

Read `_shared/debug/verify-and-close.md` and follow it exactly.
Includes 2 steps: 3_verify_and_loop, 4_complete.

Step coverage: 3_verify_and_loop, 4_complete.


</process>

<success_criteria>
- Bug description parsed + classified
- Discovery completed (matching bug type)
- At least 1 fix iteration attempted
- User confirmed status via AskUserQuestion (fixed / retry / more)
- DEBUG-LOG.md written with full trace
- 5 telemetry events emitted (parsed, classified, fix_attempted, user_confirmed, completed)
- Atomic commits per fix (rollback-safe)
- Spec gap → auto-routed to /vg:amend (if detected)
</success_criteria>
