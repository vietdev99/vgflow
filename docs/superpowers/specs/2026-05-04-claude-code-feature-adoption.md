# Claude Code feature adoption audit (2026-05-04)

**Trigger:** sếp Dũng asked to research full Claude Code CLI feature surface + identify adoption opportunities for cost optimization beyond what VG already uses (TodoWrite, AskUserQuestion, hooks).

**Sources:** docs.anthropic.com/en/docs/claude-code/* + `claude --help` local + Anthropic engineering blog 2026.

---

## Inventory — what VG ALREADY uses

| Feature | VG status | Notes |
|---|---|---|
| **Hooks** (PreToolUse, PostToolUse, UserPromptSubmit, SessionStart, Stop) | ✓ Heavy use | 7 scripts in `scripts/hooks/` |
| **Slash commands** | ✓ Comprehensive | 9 mainline + 14 utility commands |
| **Custom subagents** (`.claude/agents/<name>/SKILL.md`) | ✓ 8 subagents | vg-blueprint-{planner,contracts}, vg-build-executor, vg-review-browser-discoverer, vg-accept-{uat-builder,cleanup}, vg-test-{codegen,goal-verifier} |
| **TodoWrite** | ✓ Bug D universal enforcement | All 9 mainline cmds gate on it |
| **AskUserQuestion** | ✓ scope/accept/review/specs/debug | UAT + 3-axis preflights + interactive UAT |
| **Auto-memory** (`~/.claude/projects/.../memory/MEMORY.md`) | ✓ used | Em đang ghi user/feedback/project memories tự động |
| **MCP servers** | Partial | playwright MCP for review browser discovery |
| **CLAUDE.md** (per-project + global) | ✓ both | Project at `/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix/CLAUDE.md` + global `~/.claude/CLAUDE.md` |

---

## Inventory — what VG does NOT yet use (adoption opportunities)

| Feature | Cost impact | Adoption complexity | Recommendation |
|---|---|---|---|
| **Prompt caching** (`cache_control: ephemeral`, 5-min/1h TTL) | **Save up to 90% on cache hits** + 80% latency reduction | High (requires API-level integration; CLI may handle automatically — needs investigation) | **Tier 0** — investigate Claude Code's automatic cache behavior; add cache breakpoints if CLI exposes them |
| **`--exclude-dynamic-system-prompt-sections`** flag | Improves cross-session cache reuse (cwd/git_status moved out of system prompt) | Trivial — single CLI flag | **Tier 1** — adopt in default VG invocation pattern |
| **`hookSpecificOutput.additionalContext`** JSON (vs stderr legacy) | 10K char limit with auto-fallback to file+preview (stderr gets clipped silently) | Medium — refactor 7 hook scripts | **Tier 1** — migrate stderr → JSON for richer + safer injection |
| **`hookSpecificOutput.permissionDecision`** (allow/deny/ask) | More semantic than exit 2; supports `ask` mode (user prompt) | Medium | **Tier 2** — adopt for hooks that currently use `exit 2` |
| **`hookSpecificOutput.systemMessage`** (status injection) | Structured progress signals to model | Low | **Tier 2** — replace stderr "info" prints |
| **`--max-budget-usd`** | Hard cap per session (CI guard) | Trivial | **Tier 2** — add to CI runner / batch flows |
| **`--json-schema`** output validation | Forces subagent returns to be schema-compliant | Low — already have JSON contract | **Tier 2** — apply to vg-build-executor + vg-review-browser-discoverer |
| **`--effort` level** per subagent (low/medium/high/xhigh/max) | Match reasoning depth to task complexity → cheaper for routine tasks | Medium — per-subagent setting | **Tier 2** — `vg-test-codegen` could be `medium`, `vg-blueprint-planner` `xhigh` |
| **Checkpointing** (Esc-Esc, `/rewind`) | Restore code/conversation state without re-running | N/A — operator-driven | **Tier 3** — document for amend/debug recovery flows |
| **Background tasks** (long-running processes non-blocking) | Run dev server / validators in background | Medium | **Tier 3** — for `vg:test` E2E + perf gates |
| **MCP for GitHub / Supabase / DB** | Replace ad-hoc Bash subprocess with structured MCP tools | High | **Tier 3** — for projects where applicable |
| **`/skills` registry integration** | Expose VG slim entries as discoverable skills | Medium — frontmatter restructure | **Tier 3** — discovery/onboarding improvement |
| **Plugins** (`claude plugin install`) | Package VG harness as installable plugin | High | **Tier 4** — distribution channel |
| **`--include-hook-events`** for debugging | Stream hook lifecycle for observability | Trivial | Operator-side debug feature |

---

## Top 3 actionable fixes (highest cost-impact, lowest complexity)

### Fix 1 — Adopt `--exclude-dynamic-system-prompt-sections` (Tier 1)

**Problem:** Per-session info (cwd, env, memory paths, git status) is embedded in the system prompt. Each session writes its own variant, busting prompt-cache reuse across sessions.

**Fix:** Document in `CLAUDE.md` + invocation guides that VG operators should use:
```bash
claude --exclude-dynamic-system-prompt-sections
```
Or set as default in `.claude/settings.json` if supported. The dynamic section moves to the first user message; system prompt stays cacheable.

**Cost impact:** Cache hit rate improves significantly across sessions. With Claude Sonnet 4.5, system prompt is ~10-20K tokens; cache hit drops cost from full price to 10% per token.

---

### Fix 2 — Migrate hook stderr → JSON `additionalContext` (Tier 1)

**Problem:** Current VG hooks use `printf >&2` + `exit 2` pattern. Limitations:
1. Stderr text gets clipped silently on long messages — 10K char threshold from Claude Code dropped messages.
2. No structured `permissionDecision` semantics (just block via exit 2).
3. No `systemMessage` channel for status updates separate from blocks.

**Fix:** Refactor 7 hook scripts to emit structured JSON on success:
```bash
# OLD pattern:
printf "Block diagnostic — %s\n" "$gate_id" >&2
exit 2

# NEW pattern (richer + auto-handles 10K cap):
cat <<JSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Block diagnostic — ${gate_id}: ${cause}\nBlock file: ${block_file}",
    "additionalContext": "VG run blocked — see ${block_file} for full diagnostic + fix instructions"
  }
}
JSON
exit 0
```

**Cost impact:** Marginal token change (similar payload), but:
- Eliminates silent clipping on 10K+ char block diagnostics (current pre-bash hook can emit 200+ line block files)
- `permissionDecision: "ask"` enables future "soft block" flows (user confirms vs hard-deny)
- Existing `additionalContext` example already in VG `.claude/settings.json:graphify hook` — proven pattern

**Complexity:** ~3-4 hours per hook × 7 hooks. Some hooks (post-tool-use-todowrite) write evidence files — those don't need migration.

---

### Fix 3 — Add `--effort` level matching to subagent spawns (Tier 2)

**Problem:** All VG subagents currently use default effort (xhigh). For mechanical tasks (vg-test-codegen template generation, vg-accept-cleanup file moves, vg-build-progress.sh wraps), this is overkill.

**Fix:** Per-subagent effort declaration in SKILL.md frontmatter:
```yaml
---
name: vg-test-codegen
description: ...
tools: [Read, Write, Bash, Glob]
model: sonnet
effort: medium  # NEW — was implicit xhigh
---
```

Or pass `--effort medium` when spawning via Bash. Effort levels per task complexity:
- `low/medium`: codegen, file ops, JSON parsing (vg-test-codegen, vg-accept-cleanup)
- `high`: standard implementation (vg-build-executor, vg-review-browser-discoverer)
- `xhigh/max`: design + planning (vg-blueprint-planner, vg-blueprint-contracts, vg-accept-uat-builder)

**Cost impact:** Lower effort → fewer reasoning tokens → potentially 30-50% cost reduction on routine subagents. Anthropic prices reasoning tokens at standard input rate.

**Complexity:** Trivial — add 1 frontmatter field per subagent. 8 subagents to update.

---

## What we are NOT going to adopt (rationale)

| Feature | Skip rationale |
|---|---|
| Plugins distribution | VG is internal harness; no need to package as installable plugin yet |
| Checkpointing (Esc-Esc) | Operator-driven recovery; can't be automated by harness without confusing user |
| Background tasks for validators | Most validators complete in <30s; latency win marginal vs added complexity |
| MCP for GitHub | `gh` CLI already works fine via Bash; MCP adoption needs separate cost-benefit analysis |

---

## Sources

- [Hooks reference - Claude Code Docs](https://docs.anthropic.com/en/docs/claude-code/hooks)
- [Create custom subagents](https://docs.anthropic.com/en/docs/claude-code/sub-agents)
- [Prompt caching - Claude API Docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- [CLI reference](https://docs.anthropic.com/en/docs/claude-code/cli-reference)
- [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Enabling Claude Code to work more autonomously](https://www.anthropic.com/news/enabling-claude-code-to-work-more-autonomously)
- [Connect Claude Code to tools via MCP](https://docs.anthropic.com/en/docs/claude-code/mcp)
- Local: `claude --help` (CLI version 2026-05)

---

## Implementation tracking

- Fix 1 (`--exclude-dynamic-system-prompt-sections`): document + add to settings.json — see follow-up Task #107
- Fix 2 (hook JSON migration): per-hook plan needed — see follow-up Task #108
- Fix 3 (subagent effort levels): 1-line edit per SKILL.md — see follow-up Task #109
