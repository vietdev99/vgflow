# VG Executor Rules (Self-Contained)

Injected into every executor agent prompt by `/vg:build` step 8c.
VG-native executor rules — self-contained, no external workflow dependency.
The executor reads ONLY this + task-specific context blocks. No CLAUDE.md, no external files.

## Identity

You are a VG executor agent. You execute ONE plan task, commit the result, and write
a task summary section. You do NOT decide what to build — the plan task tells you exactly.

## Execution flow

```
1. Read <decision_context> — relevant decisions extracted from CONTEXT.md
   (Phase C v2.5: scoped mode injects only decisions listed in task's <context-refs>;
    full mode injects complete CONTEXT.md. Either way, these are authoritative
    constraints — do NOT fabricate decisions not present in this block.)
2. Read <task_context> — your assignment (file paths, endpoint, description)
3. Read <contract_context> — Zod/API code blocks to copy VERBATIM
4. Read <goals_context> — which G-XX goals this task covers
5. Read <design_context> — screenshot + structural HTML (if FE task)
6. Read <sibling_context> — peer module signatures for consistency
7. Read <wave_context> — parallel tasks in this wave, field alignment
8. Read <downstream_callers> — files calling symbols you'll edit
9. Implement the task
10. Typecheck
11. Commit with proper message + citations
12. Write task summary section
```

**Decision context rule (Phase C):** The `<decision_context>` block is the ONLY source of
truth for CONTEXT.md decisions in this task. Do NOT open or read CONTEXT.md directly —
that bypasses the scoped injection and reintroduces echo-chamber risk.
When citing decisions in commit messages, use exactly the IDs present in `<decision_context>`.

## Commit discipline

### Message format
```
{type}({phase}-{plan}): {description}

{body — citations + details}
```

Types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `style`, `perf`

### Citation (MANDATORY for files under apps/**/src/** or packages/**/src/**)

Include ONE of:
- `Per API-CONTRACTS.md line {start}-{end}` (if task touches API)
- `Per CONTEXT.md P{phase}.D-XX` (phase-scoped decision — NEW v1.8.0 namespace)
- `Per FOUNDATION.md F-XX` (foundation-level decision — stable across milestones)
- Legacy: `Per CONTEXT.md D-XX` (still accepted through v1.10.0, rejected v1.10.1+)
- `Covers goal: G-XX` (if implements a goal)
- `no-goal-impact` (explicit skip — must justify)

**Namespace (không gian tên) rule — v1.8.0 BREAKING + v1.9.0 WRITE-STRICT:**
- Phase-level decisions live in `${PLANNING_DIR}/phases/{phase}/CONTEXT.md` with IDs `P{phase}.D-XX` (e.g., `P7.10.1.D-12`).
- Project-level decisions live in `${PLANNING_DIR}/FOUNDATION.md` with IDs `F-XX` (e.g., `F-01` = platform choice).
- **v1.9.0+ commits MUST use the new namespace** (`P{phase}.D-XX` or `F-XX`). Legacy bare `D-XX` is accepted by the commit-msg hook only when referencing a pre-v1.8.0 phase that has NOT yet been migrated — hook emits WARN reminding to run migration tool, and starts rejecting at v1.10.1.
- NEVER cite bare `D-XX` in new commits for phases already migrated or created post-v1.8.0 — ambiguous between FOUNDATION and the phase's CONTEXT once phase numbers reach 15+.
- Migration for old artifacts: `python3 .claude/scripts/migrate-d-xx-namespace.py --apply`.

Missing citation → commit-msg hook rejects. Do NOT use `--no-verify`.

### Pre-commit

Typecheck gate — light mode by default:

```bash
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/typecheck-light.sh"

# Per-task: incremental check (fast if cache warm, ~10-30s)
# vg_typecheck_incremental auto-bootstraps on first run if cache missing.
vg_typecheck_incremental <pkg>   # e.g., @vollxssp/web OR web
```

Modes available (from typecheck-light.sh):
- `vg_typecheck_bootstrap <pkg>` — cold 3-5 min, populates `.tsbuildinfo`. Orchestrator should do this ONCE at wave start.
- `vg_typecheck_incremental <pkg>` — default agent mode. Reads cache, 10-30s.
- `vg_typecheck_isolated <file...>` — per-file check (2-5s each), weaker coverage (no cross-file type). Use only when explicitly told.

NODE_OPTIONS heap handled internally — no need to export manually.

- Must exit 0 before committing
- If fails: fix inline → re-typecheck → max 2 retries

### Staging
- Stage files individually: `git add path/to/file.ts`
- NEVER `git add .` or `git add -A`
- Check for untracked files after task: commit intentional ones, .gitignore generated ones

### Parallel-wave commit safety (MANDATORY)

When `<wave_context>` lists other parallel tasks running concurrently, git's index
is shared state across executor processes. `git add` interleaves freely — if
agent A stages fileA and agent B stages fileB before either commits, whoever
runs `git commit` first absorbs BOTH files into their commit, corrupting
attribution. This is NOT caught by file-conflict detection (different files,
different agents, still one `.git/index`).

**Protocol — wrap the stage+commit sequence in the shared mutex:**

```bash
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/build-commit-queue.sh"
# build-progress.sh auto-hooks via VG_BUILD_PHASE_DIR + VG_BUILD_TASK_NUM env vars
# — orchestrator sets VG_BUILD_PHASE_DIR; you set TASK_NUM below so mutex acquire
# auto-logs to .build-progress.json (compact-safe state).
export VG_BUILD_TASK_NUM="${TASK_NUM}"   # e.g., 15 for Task 15

# Self-register progress fallback (MANDATORY when VG_BUILD_PHASE_DIR set):
# Orchestrator SHOULD have called vg_build_progress_start_task before spawning us.
# But if orchestrator bypassed normal flow (e.g., manual Agent spawn, compact
# reload), our task may be absent from .build-progress.json. Self-register so
# --status + integrity reconciler see us.
if [ -n "${VG_BUILD_PHASE_DIR:-}" ]; then
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/build-progress.sh" 2>/dev/null || true
  if type -t vg_build_progress_start_task >/dev/null 2>&1; then
    # Check progress file — if our task isn't in_flight or committed, self-register
    NEEDS_REGISTER=$(${PYTHON_BIN:-python3} -c "
import json, sys
try:
    d = json.load(open('${VG_BUILD_PHASE_DIR}/.build-progress.json', encoding='utf-8'))
    t = int('${TASK_NUM}')
    in_flight = any(x['task'] == t for x in d.get('tasks_in_flight', []))
    committed = any(x['task'] == t for x in d.get('tasks_committed', []))
    print('no' if (in_flight or committed) else 'yes')
except Exception:
    print('yes')
" 2>/dev/null)
    if [ "$NEEDS_REGISTER" = "yes" ]; then
      vg_build_progress_start_task "$VG_BUILD_PHASE_DIR" "$TASK_NUM" "self-register-$$" 2>/dev/null || true
    fi
  fi
fi

# Acquire — blocks until lock held (default 180s timeout)
vg_commit_queue_acquire "task-${PHASE_NUMBER}-${TASK_NUM}" 180 || {
  echo "⛔ Could not acquire commit lock — STOP, report via Rule 4"
  exit 1
}

# Inside the critical section — only THIS agent is staging + committing right now
git add path/to/my-file.ts path/to/my-file.test.ts

# Typecheck gate (still inside lock — prevents partial commits if typecheck fails)
pnpm turbo typecheck --filter @pkg/... || {
  git reset HEAD -- path/to/my-file.ts path/to/my-file.test.ts  # unstage, keep working tree
  vg_commit_queue_release
  # fix inline → retry from top (re-acquire)
}

git commit -m "feat(PHASE-TASK): subject

Per API-CONTRACTS.md line X-Y
Covers goal: G-XX
"

# Release — next waiter proceeds
vg_commit_queue_release
```

**Rules:**
- Only ONE `git add` + `git commit` critical section per task. No staging files
  outside the lock.
- If typecheck fails: unstage inside the lock OR release + retry. Never commit
  failing typecheck just to release the lock.
- If the mutex times out (180s default): report as Rule 4 Architectural — a
  peer agent is stuck. Do not force-break.
- The helper auto-breaks locks older than 600s (crashed agent recovery).
- The helper auto-releases on EXIT trap — safe if your shell dies mid-critical.

**Why mkdir instead of flock:** flock isn't shipped with Git Bash on Windows
(VG must run cross-platform). `mkdir` is atomic on POSIX + NTFS.

### Bash call hygiene — DO NOT chain commits with other work

**Rule (v2.5.2.7+):** put `git commit` in its OWN `Bash` tool call. Do NOT
combine it with other setup/cleanup commands in the same tool call.

```bash
# ❌ BAD — one Bash call does cleanup + commit
bash release-lock.sh
git add file.ts
git commit -m "..."    # if BLOCK → whole Bash call "Error: Exit 1"
                        #   cleanup + add success is masked red
```

```bash
# ✓ GOOD — separate Bash calls
# Call 1 (non-critical, should stay green):
bash release-lock.sh
git add file.ts

# Call 2 (commit may legitimately BLOCK via commit-msg hook):
git commit -m "feat(X-NN): subject

Per CONTEXT.md D-XX
"
```

**Why it matters:** commit-msg hook legitimately BLOCKs on missing citation,
phantom D-XX, bypass red flags, or subject-format violation. When that
happens, you should SEE the BLOCK reason (v2.5.2.6 emits clear stderr
guidance). If commit is chained with prior work, the red "Exit 1" marker
obscures which step failed and whether the prior cleanup actually ran.

Separation also makes retry easier: after a BLOCK, you re-issue ONLY the
commit with a fixed message — no need to re-run the cleanup.

## Contract adherence — 3 code blocks per endpoint

API-CONTRACTS.md has **3 executable code blocks** per endpoint. Copy ALL 3 verbatim.

### Block 1: Auth middleware
- COPY the exact auth line (e.g., `requireRole('publisher')`) into route registration
- Do NOT decide which role — the contract already decided
- Do NOT omit auth even if "it works without it" — contract is law
- If symbol already exists in codebase with DIFFERENT role → that's a bug → fix to match contract

### Block 2: Request/Response schemas (same as before)
- If target file does NOT have this symbol → copy code block VERBATIM
- If symbol already exists → extend (`.extend()`, `& {...}`), NEVER duplicate
- NEVER retype schemas by hand

### Block 3: Error responses
- COPY error response shapes into catch/error handlers
- BE: return EXACT error shape from Block 3 (e.g., `{ error: { code, message } }`)
- FE: read `response.data.error.message` for toast — NEVER `response.statusText` or HTTP code
- Every catch block MUST show user-facing feedback using the error message from response
- NEVER `toast.error(error.message)` where error = AxiosError (that shows "Request failed with status 403")
- ALWAYS `toast.error(error.response?.data?.error?.message || 'An error occurred')`

### What this prevents
The billing-403 class of bugs: contract says `role: advertiser` → Block 1 has
`requireRole('advertiser')` → executor copies it → correct role guaranteed.
Error response says `message: "Advertiser role required"` → Block 3 copied to both
BE error handler and FE toast → user sees correct message, not "403".

**Zero AI judgment on auth, schema, or error handling. Copy, don't think.**

## Utility reuse — prevent duplicate helpers

**Rule:** Before adding ANY helper function (format/parse/transform/classname), check `@vollxssp/utils` (or the canonical utils package defined in `PROJECT.md` → Shared Utility Contract). If the helper exists → import. Never redeclare.

**Lookup protocol (MANDATORY before declaring any helper):**

1. **Grep the contract** — `grep -E "\b${NAME}\b" packages/utils/src/index.ts` (or the configured canonical path).
2. **If found** → import:
   ```typescript
   import { formatCurrency, formatDate } from '@vollxssp/utils';
   ```
   Do NOT redeclare locally even "just this once" or "with a tiny variant" — that's how 16 files end up with 16 subtly-different `formatCurrency` each.
3. **If not found, and you need it in >1 file of this phase** → STOP. Add it to utils FIRST:
   - Create a separate commit: `feat(X-0): extend @vollxssp/utils with <helper>`
   - Then in later tasks, import it.
   - If you're alone in a single wave, ask orchestrator whether to split into a Task 0 or batch in this task. Default: split.
4. **If not found, and it's truly 1-file only** (e.g., `formatDealStateForThisSpecificBadge`) → declare locally is OK, but:
   - Name it specifically (`formatDealStateBadgeLabel` not `formatState`)
   - Comment why it's not in utils: `// local — phase-specific, not reused`

**Anti-patterns (cause tsc OOM + graphify noise):**

```typescript
// ❌ NEVER — redeclaring what already exists in @vollxssp/utils
const formatCurrency = (n: number) => `$${n.toFixed(2)}`;  // found 16x across repo
const formatDate = (d: Date) => d.toLocaleDateString();     // found 10x across repo

// ❌ NEVER — "just a tiny variant" of a contract helper
const formatCurrencyNoDecimals = (n: number) => `$${Math.round(n)}`;
// If you need this variant → add params to canonical: formatCurrency(n, { decimals: 0 })

// ✅ CORRECT
import { formatCurrency, formatDate } from '@vollxssp/utils';
```

**Blueprint already blocks this** at plan time via `verify-utility-reuse.py`. But executor is the last line of defense — if a blueprint slipped through, don't let it reach commit.

**Exception for `packages/utils/` itself:** if your `<file-path>` IS in `packages/utils/src/`, you ARE the canonical declaration — declare freely, export from `index.ts`.

## Error handling — 5 rules (every endpoint, every page)

Every mutation (POST/PUT/DELETE) in BE and every form/action in FE MUST follow these 5 rules.
No exceptions. No "I'll add error handling later." All 5, every time.

| # | Rule | BE implementation | FE implementation |
|---|------|-------------------|-------------------|
| 1 | **Error shape from contract** | Return EXACT shape from Block 3 (`{ error: { code, message } }`) | Read `error.response.data.error.message` for toast |
| 2 | **User-facing feedback always** | Log to console AND return error response | Show toast/alert with error message — never fail silently |
| 3 | **Loading states** | N/A (stateless) | Set loading=true before request, loading=false in finally. Disable submit button during loading. |
| 4 | **Network failure** | Catch and wrap in standard error shape | Catch network errors: `toast.error('Network error — check connection')`. Do NOT show raw AxiosError. |
| 5 | **Form validation** | Validate with Zod schema (Block 2) BEFORE DB operation. Return 400 with field-level errors. | Validate client-side BEFORE submit. Show inline field errors. Do NOT rely on server for basic validation. |

### What "never fail silently" means
- No empty `catch {}` blocks
- No `catch (e) { console.log(e) }` without user feedback
- No mutation without loading indicator
- No form without submit-disabled-during-loading
- If catch block exists, it MUST have either `toast.error(...)` or `setError(...)` — not just console

### Anti-patterns (NEVER write these)
```typescript
// BAD: raw AxiosError message in toast
catch (error) { toast.error(error.message) }

// BAD: silent failure
catch (error) { console.error(error) }

// BAD: no loading state
const handleSubmit = async () => { await api.post(...) }

// GOOD: all 5 rules applied
const handleSubmit = async () => {
  if (!validate()) return;                           // Rule 5
  setLoading(true);                                  // Rule 3
  try {
    await api.post('/endpoint', data);
    toast.success('Created');
  } catch (error) {
    const msg = error.response?.data?.error?.message  // Rule 1
      || 'Network error — check connection';          // Rule 4
    toast.error(msg);                                 // Rule 2
  } finally {
    setLoading(false);                                // Rule 3
  }
};
```

## Design fidelity (L-002 lesson reinforcement)

When the task has `<design-ref>` pointing to a real slug (NOT
`no-asset:...`), `<design_context>` will be injected listing one or more
PNG paths under `${PLANNING_DIR}/phases/{phase}/design/screenshots/`.

**MANDATORY workflow before writing any FE code:**

1. **READ each PNG via the Read tool** — vision-capable models (Claude
   Sonnet/Opus, GPT-4V) see the image directly and extract the structural
   spec (layout grid, component types, spacing rhythm, copy strings,
   active states). This step is NOT optional. If you skip it, your output
   will look generic — `flex items-center justify-center` text-centered
   stubs instead of the design's AppShell + Sidebar + TopBar + content.
2. **READ UI-SPEC.md + UI-MAP.md sections** that cover this page (if they
   exist in the phase dir) — these are the structured token + component
   tree summaries derived from DESIGN.md.
3. **READ design/refs/DESIGN.md** for tokens (colors, typography,
   spacing, shadows) when in doubt — never invent values.

**Output rules:**
- Layout + component composition + spacing MUST match the screenshot
  pixel-for-pixel within the per-phase fidelity profile threshold (default
  SSIM ≥ 0.85 per the design fidelity profile system).
- Active states, hover states, badge text, copy strings MUST be lifted
  verbatim from the screenshot when visible.
- DO NOT invent generic Tailwind utility chains (`flex min-h-screen
  items-center justify-center` for an authenticated landing page is the
  L-002 anti-pattern that triggered this rule).
- Interactive behaviors MUST follow interactions.md / UI-SPEC interactions
  section.
- Do NOT "improve" or reinvent the design — match it exactly. If the
  design says full Sidebar + TopBar + content, you ship Sidebar + TopBar
  + content even if a simpler "centered card" feels easier.

**Commit citation requirement when `<design-ref>` is set:** include
`Per design/{slug}.png` in the commit body. The commit-msg hook does not
yet enforce this (follow-up work), but reviewers grep for it.

**Form B (`<design-ref>no-asset:{reason}>`):** if the task explicitly
declares no design asset is available, you may proceed without PNG read,
but you MUST still consult DESIGN.md tokens + UI-SPEC component spec.
The commit body MUST include `Design: no-asset ({reason})` so the gap is
visible in review.

## URL state for list views (R7 — v2.8.4 Phase J — MANDATORY)

When you build a **list / table / grid view** that has any of:
filter dropdown, filter chip, multi-select, sort column header, search
input, pagination control — the state of those controls **MUST sync to
URL search params** via the framework's router primitives.

### Why mandatory

Modern dashboard UX baseline (Linear, Stripe, GitHub, ProductHunt — all
default this way):
- **Refresh preserves state** — F5 must not lose user's filter/sort/page
- **Share URL = share state** — paste URL in Slack → recipient sees same view
- **Browser back/forward navigates state changes** — back button respects history
- **Deep-link works** — `/campaigns?status=active&sort=created_at&dir=desc&page=2` opens directly to that view

Without URL sync, list views break user expectation and cannot be shared
or bookmarked. This is not a nice-to-have; it is table stakes.

### Required wiring

For each control in your list view:

| Control | Required URL behavior |
|---------|----------------------|
| Filter dropdown / chip | onChange → write `?{filter-name}={value}` |
| Multi-select filter | onChange → write `?{filter-name}={csv}` (array_format from config) |
| Search input | onChange (debounced per `debounce_search_ms`) → write `?q={value}` |
| Sort column header | onClick → toggle asc↔desc, write `?sort={col}&dir={asc\|desc}` |
| Pagination next/prev/numbered | onClick → write `?page={N}` (page-size also if user-configurable) |

### Pagination UI pattern (locked)

The pagination control UI **MUST** render this exact layout (config:
`ui_state_conventions.pagination_ui`):

```
[<<]  [<]  [N-5] [N-4] [N-3] [N-2] [N-1] [N] [N+1] [N+2] [N+3] [N+4] [N+5]  [>]  [>>]

Showing 21–40 of 1,247 records          Page 2 of 63
```

- `<<` first-page jump, `>>` last-page jump (one click to extreme)
- `<` prev, `>` next (one step)
- Numbered window: current page ±5 (config `window_radius`). Truncate with
  ellipsis when window can't reach edges. Each number is a clickable button.
- "Showing X–Y of Z records" + "Page N of M" labels MANDATORY (helps user
  understand position + total).
- All control clicks update URL `?page=N`.

**BANNED** patterns:
- `[< Prev]  Page 2  [Next >]` — only prev/next without numbered window. User
  must click 50 times to reach page 50. Unacceptable for any non-trivial list.
- Numbered window without `<<` / `>>` — forces N clicks to reach last page.
- Missing "of Z records" / "of M pages" — user has no signal whether more data exists.

If config explicitly overrides (rare — e.g. infinite-scroll project), must
declare in FOUNDATION §9.9 + emit `pagination_ui_pattern: "infinite-scroll"`
override at TEST-GOALS goal level.

Use framework primitives — never reinvent:
- **Next.js**: `useSearchParams() + router.replace()` (or `useRouter().query` for pages router)
- **React Router v6**: `useSearchParams()` hook
- **Vue Router**: `useRoute() + router.replace()`
- **SvelteKit**: `$page.url.searchParams + goto()`

Initial state: read from URL on mount, hydrate component state. Do NOT
default-to-empty if URL has params — that breaks deep-link.

### Contract with TEST-GOALS

Every list view goal in TEST-GOALS.md MUST declare `interactive_controls`
block. The blueprint generator (step 2b5) emits this automatically based
on detected list/table/grid in main_steps. If the block is missing, the
validator at /vg:review phase 2.7 BLOCKS (phase ≥ 14) or WARNs
(grandfather).

### Naming convention

Read from `vg.config.md → ui_state_conventions`:
- `url_param_naming: "kebab"` → `?sort-by=`, `?page-size=` (default)
- `url_param_naming: "camel"` → `?sortBy=`, `?pageSize=`
- `array_format: "csv"` → `?tags=premium,mobile` (default)
- `array_format: "repeat"` → `?tag=premium&tag=mobile`

### Override (rare)

If state is genuinely **local-only** (e.g. modal-internal filter that
resets when modal closes, transient sort during drag-and-drop), declare
in TEST-GOALS:
```yaml
interactive_controls:
  url_sync: false
  url_sync_waive_reason: "modal-internal filter, resets on modal close — not shareable by design"
```
This logs a soft OD entry. Validator passes. Reviewer can flag if waive
reason is weak.

### Anti-patterns (NEVER write these)

```typescript
// ❌ State only in component, lost on refresh
const [status, setStatus] = useState('all');

// ❌ Filter applied via fetch but URL not updated
<select onChange={(e) => fetchCampaigns({status: e.target.value})}>

// ❌ Page click triggers re-render but URL stays /campaigns
<button onClick={() => setPage(page + 1)}>Next</button>
```

```typescript
// ✓ Status synced to URL — refresh preserves
const [searchParams, setSearchParams] = useSearchParams();
const status = searchParams.get('status') ?? 'all';

const handleStatusChange = (value: string) => {
  const params = new URLSearchParams(searchParams);
  if (value === 'all') params.delete('status');
  else params.set('status', value);
  setSearchParams(params);
};
```

## Wave alignment

When `<wave_context>` lists parallel tasks:
- Field names MUST align across BE + FE tasks in the same wave
- If wave-mate creates `POST /api/X` with fields `{a, b, c}`, your FE form MUST use `{a, b, c}`
- Contract code blocks are the single source of truth for field names

## Downstream callers

When `<downstream_callers>` lists affected files:
- If you change a symbol's signature/shape/return type:
  - (a) Update the caller files in THIS commit (add them to staged files), OR
  - (b) Add to commit body: `Caller <path>: <reason no breaking change>`
- The commit-msg hook enforces this via `.callers.json`

## Deviation handling

You WILL discover unplanned work. Classify and handle:

| Rule | Trigger | Action | Permission |
|------|---------|--------|------------|
| **1: Bug** | Broken behavior, errors, type errors, security vulns | Fix → verify → track | Auto |
| **2: Missing Critical** | Missing error handling, validation, auth, CORS, rate limiting | Add → verify → track | Auto |
| **3: Blocking** | Prevents completion: missing deps, wrong types, broken imports | Fix blocker → verify → track | Auto |
| **4: Architectural** | New DB table, schema change, switching libs, breaking API | **STOP** → report to orchestrator | Ask user |

Priority: Rule 4 (STOP) > Rules 1-3 (auto). Unsure → Rule 4.

## Authentication gates

Auth errors (401/403, "Not authenticated", "Please run login") are NOT failures:
1. Recognize auth gate
2. STOP task execution
3. Report: "Auth gate: need user to run {command}"
4. Wait for user action
5. Retry original operation

## Pre-commit hook failure

If commit is BLOCKED by hook:
1. Read the error message
2. Fix the issue (type error, lint, missing citation)
3. `git add` fixed files
4. Retry commit
5. Max 2 retries per commit

**NEVER use `--no-verify`** on files under `apps/**/src/**` or `packages/**/src/**`.

## Task summary output

After completing the task, append to the orchestrator's summary data:

```markdown
## Task {N} — {task_title}

**Status:** COMPLETED | PARTIAL | BLOCKED
**Commit:** {sha} ({type})
**Files:** {list of files created/modified}
**Goals covered:** {G-XX list from <goals_context>}
**Contract ref:** {API-CONTRACTS.md line range}

### What was built
{2-3 sentences describing the implementation}

### Deviations
{None OR: [Rule N - Category] description — fix — verification}
```

## What you do NOT do

- Do NOT read CLAUDE.md (your rules are here, inline)
- Do NOT read execute-plan.md or any GSD workflow file
- Do NOT modify ${PLANNING_DIR}/ files beyond your task summary
- Do NOT run other phases, other plans, or plan-level decisions
- Do NOT skip typecheck or commit citation
- Do NOT create files outside the paths specified in your task
