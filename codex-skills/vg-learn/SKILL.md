---
name: "vg-learn"
description: "Review, promote, reject, or retract bootstrap candidates — user-gate for AI-proposed learnings"
metadata:
  short-description: "Review, promote, reject, or retract bootstrap candidates — user-gate for AI-proposed learnings"
---

<codex_skill_adapter>
## Codex ⇆ Claude Code tool mapping

This skill was originally designed for Claude Code. When running in Codex CLI, translate tool calls using the table + patterns below.

### Tool mapping table

| Claude tool | Codex equivalent | Notes |
|---|---|---|
| AskUserQuestion | request_user_input (free-form text, or number-prefix choices) | For multi-select, format as "1. Option / 2. Option" and parse reply |
| Task (agent spawn) | `codex exec --model <model> "<prompt>"` subprocess | Foreground: `codex exec ... > /tmp/out.txt`. Parallel: launch N subprocesses + `wait`. See "Agent spawn" below |
| TaskCreate/TaskUpdate/TodoWrite | N/A — use inline markdown headers + status narration | Codex does not have a persistent task tail UI. Write `## ━━━ Phase X: step ━━━` in stdout instead |
| Monitor | Bash loop with `echo` + `sleep 3` polling | Codex streams stdout directly, no separate monitor channel |
| ScheduleWakeup | N/A — Codex is one-shot; user must re-invoke | Skill must tolerate single-execution model; no sleeping |
| WebFetch | `curl -sfL <url>` or `gh api <path>` | For GitHub URLs prefer `gh` for auth handling |
| mcp__playwright{1-5}__* | See "Playwright MCP" below | Playwright MCP tools ARE available in Codex's main orchestrator |
| mcp__graphify__* | `python -c "from graphify import ..."` inline | Graphify CLI/module works identically in Codex |
| mcp__context7__*, mcp__exa__*, mcp__firecrawl__* | Skip or fall back to WebFetch | Only available via SDK; not bundled in Codex CLI |
| Bash/Read/Write/Edit/Glob/Grep | Same — Codex supports these natively | No adapter needed |

### Agent spawn (Task → codex exec)

Claude Code spawns isolated agents via `Task(subagent_type=..., prompt=...)`. Codex equivalent:

```bash
# Single agent, foreground (wait for completion + read output)
codex exec --model gpt-5 "<full isolated prompt>" > /tmp/agent-result.txt 2>&1
RESULT=$(cat /tmp/agent-result.txt)

# Multiple agents, parallel (Claude's pattern of 1 message with N Task calls)
codex exec --model gpt-5 "<prompt 1>" > /tmp/agent-1.txt 2>&1 &
PID1=$!
codex exec --model gpt-5 "<prompt 2>" > /tmp/agent-2.txt 2>&1 &
PID2=$!
wait $PID1 $PID2
R1=$(cat /tmp/agent-1.txt); R2=$(cat /tmp/agent-2.txt)
```

**Critical constraints when spawning:**
- Subagent inherits working directory + env vars, but **no MCP server access** (Codex exec spawns fresh CLI instance without `--mcp` wired). Subagent CANNOT call `mcp__playwright*__`, `mcp__graphify__`, etc.
- Model mapping for this project: `models.planner` opus → `gpt-5`, `models.executor` sonnet → `gpt-4o`, `models.scanner` haiku → `gpt-4o-mini` (or project-configured equivalent). Check `.claude/vg.config.md` `models` section for actual values and adapt.
- Timeout: wrap in `timeout 600s codex exec ...` to prevent hung subagents.
- Return schema: if skill expects structured JSON back, prompt subagent with "Return ONLY a single JSON object with keys: {...}". Parse with `jq` or `python -c "import json,sys; ..."`.

### Playwright MCP — orchestrator-only rule

Playwright MCP tools (`mcp__playwright1__browser_navigate`, `_snapshot`, `_click`, etc.) ARE available to the main Codex orchestrator (same MCP servers as Claude Code). **BUT subagents spawned via `codex exec` do NOT inherit MCP access** — they are fresh CLI instances.

Implication for skills using Haiku scanner pattern (scanner spawns → uses Playwright):
- **Claude model:** spawn haiku agent with prompt → agent calls `mcp__playwright__` tools directly
- **Codex model:** TWO options:
  1. **Orchestrator-driven:** main orchestrator calls Playwright tools + passes snapshots/results to subagent as text → subagent returns instructions/analysis only (no tool calls). Slower but preserves parallelism benefit.
  2. **Single-agent:** orchestrator runs scanner workflow inline (no spawn). Simpler but no parallelism; suitable for 1-2 view scans but slow for 14+ views.

Default: **single-agent inline** unless skill explicitly documents the orchestrator-driven pattern for that step.

### Persistence probe (Layer 4) — execution model

For review/test skills that verify mutation persistence:
- Main orchestrator holds Playwright session (claimed via lock manager)
- Pre-snapshot + submit + refresh + re-read all run in orchestrator Playwright calls (not spawned)
- If skill delegates analysis to subagent, orchestrator must capture snapshots + pass text to subagent; subagent returns verdict JSON `{persisted: bool, pre: ..., post: ...}`

### Lock manager (Playwright)

Same as Claude:
```bash
SESSION_ID="codex-${skill}-${phase}-$$"
PLAYWRIGHT_SERVER=$(bash "${HOME}/.claude/playwright-locks/playwright-lock.sh" claim "$SESSION_ID")
trap "bash '${HOME}/.claude/playwright-locks/playwright-lock.sh' release \"$SESSION_ID\" 2>/dev/null" EXIT INT TERM
```

Pool name in Codex: `codex` (separate from Claude's `claude` pool). Lock manager handles both without collision.

## Invocation

This skill is invoked by mentioning `$vg-learn`. Treat all user text after `$vg-learn` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


# /vg:learn

User gate for bootstrap overlay changes. Primary entry point: **end-of-step reflection** auto-drafts candidates into `.vg/bootstrap/CANDIDATES.md`. This command reviews them.

## Authentication (harness v2.6 Phase G, 2026-04-26)

Mutating actions (`--promote`, `--reject`) write to the bootstrap rule
set, which is injected into every subsequent executor prompt. A
fabricated candidate self-promoted by an AI subagent would silently
alter platform behaviour across phases. Same authentication surface as
`/vg:override-resolve` and `/vg:calibrate apply`:

| Action | Auth required | --reason required |
|---|---|---|
| `--auto-surface` | no | per-prompt y/n |
| `--review [id]` | no | no |
| `--review --all` | no | no |
| `--promote <id>` | **TTY OR HMAC token** | **min 50 chars** |
| `--reject <id>` | **TTY OR HMAC token** | **min 50 chars** |
| `--retract <id>` | **TTY OR HMAC token** | **min 50 chars** |

The orchestrator subcommand `learn promote/reject` enforces the gate via
`verify_human_operator()`. Two valid auth paths:

1. **TTY (interactive shell)** — auto-approved when run from a real
   terminal. Approver recorded as `$USER` / `$USERNAME`.
2. **HMAC-signed token (CI / automation escape hatch)** — mint via
   `python3 .claude/scripts/vg-auth.py approve --flag learn-promote`,
   then `export VG_HUMAN_OPERATOR=<token>`. Token is HMAC-signed against
   `~/.vg/.approver-key` (mode 0600 on POSIX).

Failed authentication paths emit
`learn.{promote,reject}_attempt_unauthenticated` events for the forensic
trail. Successful applies emit `learn.{promoted,rejected}` with
`{candidate_id, tier, reason, operator_token, auth_method}` payload —
auditors can reconstruct who/when/why for every rule-set mutation.

**The `--reason` flag is mandatory for promote/reject/retract and must
be ≥50 characters.** Audit text must justify the decision concretely:
evidence count, phases observed, conflict assessment. Placeholder reasons
(`"approved"`, `"obvious"`, `"per Claude"`) are filtered by the same
length gate as `--override-reason`.

## v2.5 Phase H: tiered auto-surface (fixes UX fatigue)

Problem before v2.5: user had to remember `/vg:learn --review` + sort through 10+ candidates → fatigue → "all-defer" → promotion loop never closed. Fix: automatic tier classification + silent auto-promote for high-confidence + hard cap on Tier B per phase.

**Tier A** (confidence ≥ 0.85 + impact=critical): auto-promote after N=3 phase confirms (configured via `bootstrap.tier_a_auto_promote_after_confirms`). User sees 1-line notification only.

**Tier B** (confidence 0.6-0.85 OR impact=important): surfaced at end of `/vg:accept` via `--auto-surface` mode, MAX 2 per phase (config `bootstrap.tier_b_max_per_phase`). 3 lines per candidate: rule + evidence count + target. Prompt: `y/n/e/s`.

**Tier C** (confidence < 0.6 or impact=nice): silent parking. Access via `/vg:learn --review --all` (user initiates when willing).

**Retirement**: candidate rejected ≥ 2 times → marked RETIRED, never surfaced again.

**Dedupe**: before surfacing, candidates with title similarity ≥ 0.8 are merged (evidence combined, one ID kept).

## Load config

Read `.claude/commands/vg/_shared/config-loader.md` first. Sets `${PLANNING_DIR}`, `${PYTHON_BIN}`, etc.

## Subcommands

### `/vg:learn --auto-surface` (v2.5 Phase H)

Invoked automatically at end of `/vg:accept` (unless `bootstrap.auto_surface_at_accept: false`).

**Flow:**
1. Run `learn-dedupe.py` — merge title-similar candidates (threshold 0.8) in-place into CANDIDATES.md
2. Run `learn-tier-classify.py --all` to tier every pending candidate
3. Auto-promote Tier A candidates with ≥ N confirms (config `tier_a_auto_promote_after_confirms`, default 3) — silent 1-line log
4. Surface first `tier_b_max_per_phase` (default 2) Tier B candidates interactively, 3 lines each:
   ```
   L-042 — "Playwright required for UI phases when surfaces contains 'web'" (tier B, 8 evidence)
     Target: review.step-2 (discovery)
     Action: must_run before skip
   Promote? [y]es / [n]o / [e]dit / [s]kip-rest → _
   ```
5. If user hits 's' → defer remaining Tier B candidates this phase (resurfaced next phase)
6. Tier C is silent (not mentioned) — access via `/vg:learn --review --all`

**Telemetry per candidate:**
- `bootstrap.candidate_surfaced` when shown to user
- `bootstrap.rule_promoted` when user approves
- `bootstrap.rule_retired` when reject count hits threshold

**Transparency after promote:** show 1-line "injected into next phase executor prompt at section R{N}" — so user knows rule is live, not just "y but did anything happen?"

### `/vg:learn --review [id]`

List pending candidates (legacy interface, still supported). With `<id>`, show full evidence + dry-run preview.

**Without `<id>`** — list all:
```bash
# Candidates are fenced ```yaml blocks starting with `id: L-XXX` at column 0
# (top-level mapping, not list-style — list-style would collide with YAML
# sequence semantics inside the fence).
grep -nE '^id: L-' .vg/bootstrap/CANDIDATES.md | head -20
```

For each candidate, show: id, title, type, scope, confidence, created_at.

**With `<id>`** — show full detail:
1. Parse candidate block from `.vg/bootstrap/CANDIDATES.md`
2. Show all evidence entries (file:line, user message, telemetry event_id)
3. **Dry-run preview:**
   - For `config_override`: diff current vanilla config vs proposed
   - For `rule`: evaluate scope against last 10 phases, report which would have matched
   - Impact: "rule would fire in N future phases with current metadata"
   - Conflict check: list any active ACCEPTED rules with overlapping scope + opposite action

Display with mandatory confirm prompt:
```
Promote? [y/n/edit]
```

### `/vg:learn --promote <id> --reason "..."`

Apply candidate to bootstrap zone.

**MANDATORY auth gate (harness v2.6 Phase G):** Before any pre-check
runs, the orchestrator subcommand `learn promote` requires:
- TTY OR HMAC-signed `VG_HUMAN_OPERATOR` token (see Authentication
  section above), AND
- `--reason "..."` ≥ 50 characters citing concrete evidence

Failed auth → BLOCK with rc=2 + `learn.promote_attempt_unauthenticated`
audit event. AI subagents cannot self-promote.

**MANDATORY pre-check (after auth passes):**
1. Schema validate (for `config_override`): target key must be in `schema/overlay.schema.yml` allowlist
   - If not in allowlist → offer fallback: "convert to prose rule?"
2. Scope syntax validate via `scope-evaluator.py --context-json <empty> --scope-json <scope>` → exit 2 = malformed
3. **Conflict detect** vs active ACCEPTED rules (same target key, opposite value/action) — MUST call `bootstrap-conflict.py`:
   ```bash
   # Write candidate block to tempfile then call conflict detector
   CAND_YAML=$(mktemp -t vg-candidate-XXXXXX.yml)
   # AI extracts candidate YAML block from CANDIDATES.md for L-XXX into $CAND_YAML
   RESULT=$("${PYTHON_BIN:-python3}" .claude/scripts/bootstrap-conflict.py \
     --candidate "$CAND_YAML" --emit json)
   CONFLICT_RC=$?
   rm -f "$CAND_YAML"
   if [ "$CONFLICT_RC" -ne 0 ]; then
     echo "⛔ Conflict detected — cannot promote L-XXX:" >&2
     echo "$RESULT" | ${PYTHON_BIN:-python3} -c "import json,sys; [print(f'  - {c}') for c in json.load(sys.stdin).get('conflicts', [])]"
     echo "   Resolve: retract conflicting rule OR adjust candidate scope." >&2
     exit 1
   fi
   ```
4. Dedupe check vs ACCEPTED (semantic equivalence) → block if duplicate
5. Dry-run REQUIRED (shows impact preview)

**If all pass:**
1. For `config_override` → update `.vg/bootstrap/overlay.yml` (deep-merge)
2. For `rule` → write `.vg/bootstrap/rules/{slug-from-title}.md` with full frontmatter
3. For `patch` → write `.vg/bootstrap/patches/{command}.{anchor}.md`, validate anchor in `anchors.yml`
4. Remove candidate from `CANDIDATES.md`
5. Append to `ACCEPTED.md` with git_sha placeholder
6. **Git commit atomic:**
   ```
   chore(bootstrap): promote L-XXX — {reason}

   Type: {type}
   Target: {target}
   Origin: {origin_incident or user.lesson}
   Confidence: {confidence}
   ```
7. Update ACCEPTED.md entry with real SHA
8. Emit telemetry:
   ```
   emit_telemetry "bootstrap.candidate_promoted" PASS \
     "{\"id\":\"L-XXX\",\"type\":\"...\",\"target\":\"...\"}"
   ```

### `/vg:learn --reject <id> --reason "..."`

Decline candidate. Reason is REQUIRED — same auth gate as promote
(harness v2.6 Phase G):
- TTY OR HMAC-signed token, AND
- `--reason "..."` ≥ 50 characters

Why same gate as promote? An AI subagent rejecting a candidate that
flags its own corner-cutting pattern is just as much a self-mutation —
the rule never gets reconsidered. Symmetric defense: both directions
require human accountability.

1. Move candidate block from `CANDIDATES.md` to `REJECTED.md`
2. Append rejection metadata: user, timestamp, reason, dedupe_key
3. Emit telemetry `learn.rejected` (success) or
   `learn.reject_attempt_unauthenticated` (auth fail)

Reflector checks `REJECTED.md` dedupe_key before future drafts — 2+ rejects of same key → silent skip forever.

### `/vg:learn --retract <id> --reason "..."`

**Emergency rollback** — remove an ACCEPTED rule immediately. Reason REQUIRED.

Use when:
- Rule caused regression discovered after promote
- Rule obsolete after refactor
- Manual cleanup

1. Locate rule in bootstrap zone (overlay.yml key / rules/*.md / patches/*.md)
2. Remove / set status=retracted
3. Append to `RETRACTED.md` with stats snapshot (hits, success/fail counts)
4. Git commit atomic:
   ```
   chore(bootstrap): retract L-XXX — {reason}
   ```
5. Emit `bootstrap.rule_retracted` telemetry

## Interactive inline-edit (`e` option during --review)

Not an external editor — prompt loop:
```
Editing L-042:
  [1] title:    "Playwright required for UI phases"
  [2] scope:    any_of: [...]
  [3] action:   must_run
  [4] prose:    "..."
  [5] target_step: review
  [done] finish editing

Field to edit? [1/2/3/4/5/done]: _
```

User picks field, inline-prompt shows current value, user types new value, save.
When `done` → re-validate schema + scope syntax, then proceed to promote.

## Output

- `--review` → terminal listing + optional full-detail block
- `--promote/--reject/--retract` → confirmation message + git SHA

## Safety

- Every promote = 1 git commit (atomic, revertable)
- Every reject has reason (REJECTED.md audit)
- Every retract has reason + stats snapshot (RETRACTED.md audit)
- Schema validation blocks AI invent fake keys
- Conflict detection blocks incompatible rules
- Dedupe blocks redundant rules
- Dry-run mandatory — no way to promote without seeing impact preview first
