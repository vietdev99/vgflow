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
