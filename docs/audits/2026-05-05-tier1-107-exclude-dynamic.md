# Tier 1 #107 — Adopt `--exclude-dynamic-system-prompt-sections`

**Date**: 2026-05-05
**Status**: ADOPTED (operator-side recommendation; no harness enforcement)
**Source spec**: `docs/superpowers/specs/2026-05-04-claude-code-feature-adoption.md` (Fix 1)

## What

Claude Code 2.0+ ships a launch flag `--exclude-dynamic-system-prompt-sections`
that relocates per-machine sections (cwd, env info, memory paths, git status)
out of the system prompt and into the first user message. This makes the
system prompt invariant across sessions, so prompt-cache hits survive
cross-session and cross-cwd boundaries.

Verified `claude --help` output (2026-05-05):

```
--exclude-dynamic-system-prompt-sections
    Move per-machine sections (cwd, env info, memory paths, git status) from
    the system prompt into the first user message. Improves cross-user
    prompt-cache reuse. Only applies with the default system prompt
    (ignored with --system-prompt). (default: false)
```

## Why

VG sessions repeatedly start with the same system prompt content but vary
on per-machine fields. Without the flag, the cache key changes every
session → cache miss → full re-tokenization of ~10–20K dynamic-section
tokens. With the flag, the system-prompt cache persists; estimated
saving **~30K tokens per session** at typical ~90% cache-hit rate.

## Adoption guidance

**Operators run:**

```bash
claude --exclude-dynamic-system-prompt-sections
```

**Optional permanent alias** (`~/.zshrc` or `~/.bashrc`):

```bash
alias claude-vg='claude --exclude-dynamic-system-prompt-sections'
```

Then invoke `claude-vg` in any VG project directory.

## Why this is operator-side only

The flag is consumed by the Claude Code CLI at launch. A running session
(this one, for instance) cannot retroactively re-flag itself. VG harness
options considered and rejected:

- **`.claude/settings.json` injection** — settings.json schema (as of
  2026-05-05) has no `flags` or `cli_args` field for launch arguments.
  Hooks (`PreToolUse`, `Stop`, etc.) only fire mid-session.
- **`install.sh` wrapper** — would require intercepting the user's
  `claude` binary path, which is a hostile-modification of the user's
  shell environment. Out of scope.
- **Pre-tool-use detection of missing flag** — there is no way for a
  hook to inspect the parent CLI's argv. Even if there were, the flag
  affects prompt construction, not tool invocation, so the hook would
  fire too late.

Conclusion: documentation + recommendation is the correct intervention.

## Verification

- `claude --help 2>&1 | grep exclude-dynamic` — confirms the flag exists.
- `scripts/tests/test_tier1_107_doc_exists.py` — asserts CLAUDE.md
  documents the flag and explains why (cache / token).

## Related

- `docs/superpowers/specs/2026-05-04-claude-code-feature-adoption.md` — full
  feature-adoption matrix (Tier 1 / Tier 2 / Tier 3 fixes).
- Tier 2 #109 (`45e4369`) — opus → sonnet downgrade, complementary cost
  reduction (subagent model selection, also operator-touchable but already
  enforced via subagent frontmatter).
