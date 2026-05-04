## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)

## Performance — recommended Claude Code invocation

**Recommended command for VG operators:**

```bash
claude --exclude-dynamic-system-prompt-sections
```

**Why:** per-machine sections (cwd, env info, memory paths, git status) are normally embedded in the Claude Code system prompt. Each session writes its own variant, busting cross-session **prompt-cache reuse**. The `--exclude-dynamic-system-prompt-sections` flag (Claude Code 2.0+) moves those sections into the first user message, leaving the system prompt cacheable. Estimated saving: ~10–20K tokens × ~90% cache hit rate ≈ **~30K tokens saved per session**.

**Operator-side only:** the flag is consumed by the Claude Code CLI at launch. The VG harness cannot enforce it from inside a running session (we ARE the running session). No automatic enforcement; this is a recommendation.

**Optional zsh alias** (add to `~/.zshrc`):

```bash
alias claude-vg='claude --exclude-dynamic-system-prompt-sections'
```

See `docs/audits/2026-05-05-tier1-107-exclude-dynamic.md` for adoption notes.

## Performance — `--max-budget-usd` runaway-cost safety net (Tier 2 C)

**Recommended pattern for batch flows:**

```bash
claude --print --max-budget-usd 5 --exclude-dynamic-system-prompt-sections
```

**Why:** the `--max-budget-usd <amount>` flag (Claude Code 2.0+, only works with `--print`) caps total dollar spend on API calls per session. R6 #7 caps retry iterations at the workflow layer, but a runaway loop in `/vg:review-batch` (10+ phases) or `/vg:regression` (full suite sweep with `--fix`) can still burn through $10+ if a phase hits an unexpected pathological pattern (e.g., flaky test → retry → re-fix → flaky again). The dollar cap is a hard ceiling that the harness cannot override.

**Recommended for batch flows specifically:**

```bash
# /vg:review-batch — sweeping multiple phases sequentially
claude --print --max-budget-usd 10 --exclude-dynamic-system-prompt-sections -p '/vg:review-batch --milestone M2'

# /vg:regression — full suite + --fix
claude --print --max-budget-usd 15 --exclude-dynamic-system-prompt-sections -p '/vg:regression --fix'
```

**Scope discipline:** this is operator-side flag adoption (like `--exclude-dynamic-system-prompt-sections` above). No harness enforcement — the VG harness IS the running session and cannot impose a budget cap on itself. Document, recommend, leave to the operator. Suggested defaults: `5` for single phase, `10` for batch sweep, `15` for full regression with fix loop.

**Optional zsh aliases** for unattended runs:

```bash
alias claude-vg-batch='claude --print --max-budget-usd 10 --exclude-dynamic-system-prompt-sections'
alias claude-vg-regression='claude --print --max-budget-usd 15 --exclude-dynamic-system-prompt-sections'
```

See `commands/vg/review-batch.md` + `commands/vg/regression.md` top-of-file recommendations.
