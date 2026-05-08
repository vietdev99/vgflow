---
description: Review, promote, reject, or retract bootstrap candidates — user-gate for AI-proposed learnings
argument-hint: "[--auto-surface|--review [id]|--review --all|--promote <id> --reason '...'|--reject <id> --reason '...'|--retract <id> --reason '...'|--consolidate [--apply]]"
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "learn.started"
    - event_type: "learn.completed"
    - event_type: "learn.promoted"  # on successful promote
    - event_type: "learn.rejected"  # on successful reject
    - event_type: "learn.promote_attempt_unauthenticated"  # blocked attempt
---

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

### `/vg:learn --consolidate [--apply]` (meta-memory v1.1, Task 5.6)

Run Anthropic Auto Dream-style 4-phase consolidation over `.vg/bootstrap/`.
Default mode is **dry-run** — pass `--apply` to actually merge.

#### Trigger gate (Anthropic Dreams pattern, design Section 13.1)

Consolidation only runs if BOTH conditions hold:

- 24+ hours since last `--consolidate --apply` (override `VG_DREAMS_GATE_HOURS`)
- &gt;5 sessions since last apply (override `VG_DREAMS_GATE_SESSIONS`)

If gate closed → exit 0 with `{"status":"gate_closed","reason":"..."}`; no work done.
This is intentionally a no-op, not an error — the orchestrator runs cheaply
on every session start.

#### 4 phases (run sequentially, atomic)

1. **Orient** — read `.vg/bootstrap/` directory; snapshot rule counts +
   storage health (oversized + orphan files, MEMORY.md line count).
2. **Gather Signal** — query `.vg/events.db` (last 30d / 5000 events,
   whichever smaller); narrow-grep transcripts for user corrections +
   recurring themes. **Codex #9 attribution gate** drops procedural rule
   outcomes WITHOUT non-empty `attribution.executed_step_ids` —
   cargo-cult prevention.
3. **Consolidate** — MERGE in-place per Anthropic Dreams pattern (NOT
   side-by-side):
   - Recurrence (≥3 attributed PASS, 0 FAIL) → tier-A confirmed in
     `overlay.yml` + ACCEPTED.md entry + CONSOLIDATION-LOG.md line
   - Contradiction (≥3 PASS streak then ≥3 FAIL) → warning in
     `CONSOLIDATION-LOG.md` (NEVER auto-retract; humans decide via
     `--retract`)
   - Drift (no fire ≥30d) → archive proposal in log
4. **Prune & Index** — rebuild `MEMORY.md` ≤ 200 lines (Anthropic cap),
   demote verbose entries to `topics/{slug}.md`.

#### Critical invariants (per design Section 13.4 + Codex #9)

- Procedural rule outcomes WITHOUT `attribution.executed_step_ids`
  (non-empty) are dropped at gather stage. Cargo-cult prevention.
- Default mode dry-run — `rules/*.md`, `overlay.yml`, `MEMORY.md` files
  NEVER modified without `--apply`.
- Lock file `.vg/bootstrap/.consolidation.lock` blocks concurrent runs.
- Lock is **ALWAYS** released via `try/finally` even on mid-phase
  exception — a stranded lock would block every future dream.
- NEVER auto-retract on contradiction (warn-only). `/vg:learn --retract`
  remains the only path to remove an ACCEPTED rule.

#### Invocation

The orchestrator subcommand `--consolidate-all` runs gate → lock → 4
phases → state update (if `--apply`) → release-lock atomically:

```bash
# Dry-run (default — no file changes, safe to run anytime)
"${PYTHON_BIN:-python3}" .claude/scripts/bootstrap-consolidate.py --consolidate-all

# Apply (real merge — writes to overlay.yml, MEMORY.md, CONSOLIDATION-LOG.md)
"${PYTHON_BIN:-python3}" .claude/scripts/bootstrap-consolidate.py --consolidate-all --apply

# Just check the gate (no work, returns rc=0 open / rc=1 closed)
"${PYTHON_BIN:-python3}" .claude/scripts/bootstrap-consolidate.py --check-gate
```

Individual phases remain available for debugging:

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/bootstrap-consolidate.py --phase orient --json
"${PYTHON_BIN:-python3}" .claude/scripts/bootstrap-consolidate.py --phase gather --json
"${PYTHON_BIN:-python3}" .claude/scripts/bootstrap-consolidate.py --phase consolidate [--apply]
"${PYTHON_BIN:-python3}" .claude/scripts/bootstrap-consolidate.py --phase prune [--apply]
```

#### Output

Pass `--json` for a machine-readable combined report on stdout:

```json
{
  "status": "ok",
  "apply": false,
  "state_dir": ".../.vg/bootstrap",
  "orient": { "rule_count": 12, "memory_md_lines": 187, ... },
  "gather": { "events_processed": 142, "rule_signals": { ... } },
  "consolidate": { "promotions": [...], "contradictions": [...], "files_modified": [...] },
  "prune": { "rules_total": 12, "demoted_count": 2, ... }
}
```

If gate closed: `{"status":"gate_closed","reason":"<24h since last run (3.2h elapsed)"}`.
If lock busy: `{"status":"lock_busy","reason":"concurrent dream already running"}`.
If a phase raises: `{"status":"phase_error","error":"..."}` and the lock is
released before exit.

Exit codes:
- `0` — gate closed (no-op) or success
- `1` — lock busy or phase error

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
- `--consolidate` → JSON / human-readable report (gate decision + 4-phase results)

## Safety

- Every promote = 1 git commit (atomic, revertable)
- Every reject has reason (REJECTED.md audit)
- Every retract has reason + stats snapshot (RETRACTED.md audit)
- Schema validation blocks AI invent fake keys
- Conflict detection blocks incompatible rules
- Dedupe blocks redundant rules
- Dry-run mandatory — no way to promote without seeing impact preview first
