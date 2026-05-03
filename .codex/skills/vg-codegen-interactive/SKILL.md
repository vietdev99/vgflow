---
name: "vg-codegen-interactive"
description: "Generate Playwright .spec.ts files for interactive_controls goals — deterministic test count per filter/sort/pagination/search, output piped through verify-codegen-output validator before write"
metadata:
  short-description: "Generate Playwright .spec.ts files for interactive_controls goals — deterministic test count per filter/sort/pagination/search, output piped through verify-codegen-output validator before write"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as `codex-inline` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Native Codex tasklist/plan projection + orchestrator step markers | Use `tasklist-contract.json` as source of truth. After projecting, emit `vg-orchestrator tasklist-projected --adapter codex`; if no native task UI is exposed, use `--adapter fallback` and `run-status --pretty`. |
| Playwright MCP | Main Codex orchestrator MCP tools, or smoke-tested subagents | If an MCP-using subagent cannot access tools in a target environment, fall back to orchestrator-driven/inline scanner flow. |
| Graphify MCP | Python/CLI graphify calls | VGFlow's build/review paths already use deterministic scripts where possible. |

<codex_runtime_contract>
### Provider/runtime parity contract

This generated skill must preserve the source command's artifacts, gates,
telemetry events, and step ordering on both Claude and Codex. Do not remove,
skip, or weaken a source workflow step because a Claude-only primitive appears
in the body below.

#### Provider mapping

| Source pattern | Claude path | Codex path |
|---|---|---|
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `commands/vg/_shared/lib/codex-spawn.sh --tier planner` |
| Build executor Agent | Use the source executor `Agent(...)` call | Use `codex-spawn.sh --tier executor --sandbox workspace-write` with explicit file ownership and expected artifact output |
| Adversarial/CrossAI reviewer | Use configured external CLIs and consensus validators | Use configured `codex exec`/Gemini/Claude commands from `.claude/vg.config.md`; fail if required CLI output is missing or unparsable |
| Haiku scanner / Playwright / Maestro / MCP-heavy work | Use Claude subagents where the source command requires them | Keep MCP-heavy work in the main Codex orchestrator unless child MCP access was smoke-tested; scanner work may run inline/sequential instead of parallel, but must write the same scan artifacts and events |
| Reflection / learning | Use `vg-reflector` workflow | Use the Codex `vg-reflector` adapter or `codex-spawn.sh --tier scanner`; candidates still require the same user gate |

### Codex hook parity

Claude Code and Codex now both have project-local hook substrates. VGFlow
`sync.sh`/`install.sh` installs `.codex/hooks.json` plus
`.codex/config.toml` with `[features].codex_hooks = true`. Codex hooks
wrap the same orchestrator that writes `.vg/events.db`, while command-body
guards remain mandatory because Codex hook coverage is still tool-path scoped:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Codex wrapper accepts both `/vg:cmd` and `$vg-cmd`; command-body `vg-orchestrator run-start` is still mandatory and must BLOCK if missing/failing |
| `PreToolUse` Bash -> `hooks/vg-pre-tool-use-bash.sh` | Blocks `vg-orchestrator step-active` until tasklist projection evidence is signed | Codex wrapper sets `CLAUDE_SESSION_ID`/`CLAUDE_HOOK_SESSION_ID` from Codex `session_id` and forwards to the same gate |
| `PreToolUse` Write/Edit -> `hooks/vg-pre-tool-use-write.sh` | Blocks direct writes to protected evidence, marker, and event paths | Codex `apply_patch` wrapper at `codex-hooks/vg-pre-tool-use-apply-patch.py` blocks the same protected paths before patch application |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Codex wrapper forwards Bash results to the same tracker; explicit `vg-orchestrator mark-step` lines remain required |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Codex wrapper runs the same verifier; command-body terminal `vg-orchestrator run-complete` is still required before claiming completion |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

Run fenced command-body shell snippets with Bash explicitly, for example
`/bin/bash -lc '<snippet>'`, instead of the user's login shell. VGFlow source
commands use Bash semantics such as `[[ ... ]]`, arrays, `BASH_SOURCE`, and
`set -u`; zsh can misinterpret those snippets and create false failures.

Before running any command-body snippet that calls validators, orchestrator
helpers, or `${PYTHON_BIN:-python3}`, execute the Python detection block from
`.claude/commands/vg/_shared/config-loader.md` in that same Bash shell and
export the selected `PYTHON_BIN`. Do not reset `PYTHON_BIN=python3` after
detection: on macOS, bare `python3` is often an older interpreter without
PyYAML, which makes VG validators fail even though a valid Homebrew/Python.org
interpreter is installed.

Each Codex shell tool call starts with a fresh environment. If a later command
invokes `.claude/scripts/*`, validators, or `vg-orchestrator`, redetect
`PYTHON_BIN` or carry the previously detected absolute interpreter into that
same command. Do not run `python3 .claude/scripts/...` directly for VG
validators/orchestrator calls.

For tasklist projection, Codex must write evidence before any step marker call:
after `emit-tasklist.py`, run `vg-orchestrator tasklist-projected --adapter codex`
as its own tool call. Do not group `tasklist-projected` and `step-active` in
one shell command; PreToolUse evaluates the entire command before the evidence
file exists and will block the grouped command.

For top-level VG commands that include a mandatory `git commit` step, ensure
the parent Codex session can write Git metadata. Some Codex
`workspace-write` sandboxes deny `.git/index.lock`; when that happens,
BLOCK and ask the operator to rerun with a sandbox/profile that permits Git
metadata writes instead of skipping or forging the commit marker.

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Use `--scanner=codex-inline` by default. Do NOT ask to spawn Haiku or blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
| `/vg:review` fix agents and `/vg:test` codegen agents | Use `codex-spawn.sh --tier executor` because they edit code/tests | `VG_CODEX_MODEL_EXECUTOR` or explicit `--model` if the command selected a configured fix model | `workspace-write` | changed files, tests run, unresolved risks |
| Rationalization guard, reflector, gap hunters | Use `codex-spawn.sh --tier scanner` for read-only classification, or `--tier adversarial` for independent challenge/review | `VG_CODEX_MODEL_SCANNER` or `VG_CODEX_MODEL_ADVERSARIAL` | `read-only` by default | compact JSON/markdown verdict; fail closed on empty/unparseable output |

If a source sentence says "MUST spawn Haiku" and the step needs MCP/browser
tools, Codex interprets that as "MUST run the scanner protocol and emit the
same artifacts/events"; it does not require a child process unless child MCP
access was smoke-tested in the current environment.

#### Non-negotiable guarantees

- Never skip source workflow gates, validators, telemetry events, or must-write artifacts.
- If Codex cannot emulate a Claude primitive safely, BLOCK instead of silently degrading.
- UI/UX, security, and business-flow checks remain artifact/gate driven: follow the source command's DESIGN/UI-MAP/TEST-GOALS/security validator requirements exactly.
- A slower Codex inline path is acceptable; a weaker path that omits evidence is not.
</codex_runtime_contract>

### Model tier mapping

Model mapping is tier-based, not vendor-name-based.

VGFlow keeps tier names in `.claude/vg.config.md`; Codex subprocesses use
the user's Codex config model by default. Pin a tier only after smoke-testing
that model in the target account, via `VG_CODEX_MODEL_PLANNER`,
`VG_CODEX_MODEL_EXECUTOR`, `VG_CODEX_MODEL_SCANNER`, or
`VG_CODEX_MODEL_ADVERSARIAL`:

| VG tier | Claude-style role | Codex default | Fallback |
|---|---|---|---|
| planner | Opus-class planning/reasoning | Codex config default | Set `VG_CODEX_MODEL_PLANNER` only after smoke-testing |
| executor | Sonnet-class coding/review | Codex config default | Set `VG_CODEX_MODEL_EXECUTOR` only after smoke-testing |
| scanner | Haiku-class scan/classify | Codex config default | Set `VG_CODEX_MODEL_SCANNER` only after smoke-testing |
| adversarial | independent reviewer | Codex config default | Set `VG_CODEX_MODEL_ADVERSARIAL` only after smoke-testing |

### Spawn helper

For subprocess-based children, use:

```bash
bash .claude/commands/vg/_shared/lib/codex-spawn.sh \
  --tier executor \
  --spawn-role "<vg-subagent-role>" \
  --spawn-id "<stable-spawn-id>" \
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.
When `--spawn-role` is set, it also writes Codex spawn evidence to
`.vg/runs/<run_id>/codex-spawns/` and appends
`.vg/runs/<run_id>/.codex-spawn-manifest.jsonl`. Codex Bash hooks block
heavy-step markers and `wave-complete` when required spawn evidence or
build wave `.spawn-count.json` is missing.

### Known Codex caveats to design around

- Do not trust inline model selection for native subagents unless verified in the current Codex version; use TOML-pinned agents or `codex exec --model`.
- Do not combine structured `--output-schema` with MCP-heavy runs until the target Codex version is smoke-tested. Prefer plain text + post-parse for MCP flows.
- Recursive `codex exec` runs inherit sandbox constraints. Use the least sandbox that still allows the child to write expected artifacts.

### Support-skill MCP pattern

Pattern A: INLINE ORCHESTRATOR. For MCP-heavy support skills such as
`vg-haiku-scanner`, Codex keeps Playwright/Maestro actions in the main
orchestrator and only delegates read-only classification after snapshots are
captured. This preserves MCP access and avoids false confidence from a child
process that cannot see browser tools.

## Invocation

Invoke this skill as `$vg-codegen-interactive`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



# vg-codegen-interactive — Interactive controls codegen sub-skill

## 1. Purpose

Generate one `apps/web/e2e/generated/{goal_id_slug}.url-state.spec.ts` file
per TEST-GOALS goal whose frontmatter declares
`interactive_controls.url_sync: true`. This replaces hand-written codegen
of URL-state / filter / sort / pagination / search tests with a
Sonnet-driven, deterministic-count generator.

Manual codegen (forms, mutations, navigation, multi-step flows) stays
in `/vg:test` step `5d_codegen`'s main path. This skill handles ONLY
the list-view interactive control class.

## 2. When invoked

By `/vg:test` step `5d_codegen` for each goal that has
`interactive_controls.url_sync: true`. One Sonnet call per goal. Output
is piped through `verify-codegen-output.py` BEFORE the orchestrator
writes the spec to its final path.

## 3. Input contract

The caller (test.md step 5d_codegen branch) provides:

| Field | Source | Example |
|-------|--------|---------|
| `goal_id` | TEST-GOALS frontmatter `id:` | `G-CAMPAIGN-LIST` |
| `route` | `RUNTIME-MAP.json.views[start_view].url` or goal `route:` | `/admin/campaigns` |
| `actor` | TEST-GOALS frontmatter `actor:` (default `admin`) | `admin` |
| `interactive_controls` | verbatim YAML block from goal frontmatter | (see § 4) |
| `output_path` | `${GENERATED_TESTS_DIR}/${slug}.url-state.spec.ts` | `apps/web/e2e/generated/g-campaign-list.url-state.spec.ts` |

**Slug rule:** `slug = goal_id.lower()`. Example: `G-CAMPAIGN-LIST` →
`g-campaign-list`. The validator BLOCKs on filename mismatch.

## 4. Output requirements (verbatim from SPEC-B § 3)

One file per goal at `${GENERATED_TESTS_DIR}/{goal_id_slug}.url-state.spec.ts`.

**Mandatory shape:**

- **First line** is the `// AUTO-GENERATED by /vg:test step 5d_codegen — DO NOT EDIT BY HAND.` header (a leading source-comment block is allowed but the header MUST be the first non-blank line).
- **Imports** must include all 7 helpers from `helpers/interactive` and `test, expect` from `@playwright/test`. Login helper is allowed (e.g. `loginAs` from `../helpers`).
- **Constants** `ROUTE` and `ROLE` declared at module scope. `ROUTE` MUST exactly equal the input `route`.
- **Test count** equals the deterministic formula:
  ```
  N = sum(len(filter.values) for filter in filters)        # one per value
    + len(filters)                                         # one reload-persists per filter
    + sum(len(sort.directions) for sort in sort_blocks)    # one per direction
    + (1 if pagination else 0)
    + (1 if search else 0)
  ```
  Codegen MUST emit exactly N tests. Validator BLOCKs on drift.
- **Selectors** come ONLY through helpers — NEVER hand-roll `page.locator(`
  in test bodies. Helpers internally encapsulate all `[data-testid="..."]`
  conventions.
- **Assertions** use `expectAssertion(rows, '<expr>', ctx)` with one of the
  5 grammar forms in § 8.

**Reference shape (illustrative — DO NOT free-write, fill placeholders):**

```ts
// AUTO-GENERATED by /vg:test step 5d_codegen — DO NOT EDIT BY HAND.
// Regenerate via: /vg:test {phase} --recodegen-interactive
// Source: TEST-GOALS.md goal G-CAMPAIGN-LIST interactive_controls block

import { test, expect } from '@playwright/test';
import { loginAs } from '../helpers';
import {
  applyFilter, applySort, applyPagination, applySearch,
  readUrlParams, readVisibleRows, expectAssertion,
} from '../helpers/interactive';

const ROUTE = '/admin/campaigns';
const ROLE  = 'admin';

test.describe('G-CAMPAIGN-LIST · interactive_controls', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, ROLE);
    await page.goto(ROUTE);
  });

  // ─── filters ─────────────────────────────────────────────
  for (const value of ['draft','active','paused','archived']) {
    test(`filter status=${value} syncs to URL + filters rows`, async ({ page }) => {
      await applyFilter(page, 'status', value);
      const params = readUrlParams(page);
      expect(params.status).toBe(value);
      const rows = await readVisibleRows(page);
      await expectAssertion(rows, 'rows[*].status === param', { param: value });
    });
  }

  test('filter status reload-persists', async ({ page }) => {
    await page.goto(`${ROUTE}?status=active`);
    await page.reload();
    expect(readUrlParams(page).status).toBe('active');
    const rows = await readVisibleRows(page);
    await expectAssertion(rows, 'rows[*].status === param', { param: 'active' });
  });

  // ─── sort / pagination / search ─────────────────────────
  // (one test per direction / pagination / search per § 4 deterministic count)
});
```

## 5. Codegen prompt template (sent to Sonnet, temperature 0)

```
You are generating Playwright tests for one TEST-GOALS goal.

Goal:  {goal_id}
Route: {route}                    (from RUNTIME-MAP)
Actor: {actor}                    (from goal frontmatter)
Interactive controls (frozen YAML):
  {paste interactive_controls block verbatim}

Output requirements:
- File path: {output_path}
- Use ONLY helpers from ../helpers/interactive (no raw selectors)
- Emit deterministic test count per § 4 of SKILL.md / SPEC-B § 3:
    filter_value_tests   = sum(len(filter.values) for filter in filters)
    filter_reload_tests  = len(filters)
    sort_dir_tests       = sum(len(sort.directions) for sort in sort_blocks)
    pagination_tests     = 1 if pagination else 0
    search_tests         = 1 if search else 0
    total                = sum of the above
- Test names match the pattern:
    "filter <name>=<value> syncs to URL + filters rows"
    "filter <name> reload-persists"
    "sort <name>:<dir> syncs to URL + orders rows"
    "pagination <type> nav syncs to URL + caps row count"
    "search <name> debounces + syncs + filters rows"

Forbidden:
- waitForLoadState('networkidle')   — SPA polls forever, never settles
- page.evaluate() to read state     — must come from DOM via helpers
- Inline page.locator(...)          — must use helpers
- waitForTimeout > debounce_ms+100  — caller responsible

Return ONLY the .spec.ts content. No prose. No markdown fences.
```

## 6. Helper library reference

Generated specs assume the helper library at
`apps/web/e2e/helpers/interactive.ts` exists in the consumer project. The
reference template ships at
`.claude/commands/vg/_shared/templates/interactive-helpers.template.ts`
— projects MUST copy the template into their e2e helpers folder before
running `/vg:test`. VG itself stays project-agnostic; the helper
implementation is consumer-owned.

The contract (helper names + signatures + DSL grammar) is owned by VG;
internals (retry logic, custom waits) can be extended by the project as
long as the public API is preserved.

Required exports:

| Helper | Used in generated spec for |
|--------|----------------------------|
| `applyFilter(page, name, value)` | filter tests (per filter × per value) |
| `applySort(page, name, dir)` | sort tests (per column × per direction) |
| `applyPagination(page, opts)` | pagination test |
| `applySearch(page, name, value)` | search test |
| `readUrlParams(page)` | URL sync assertions |
| `readVisibleRows(page)` | row data assertions |
| `expectAssertion(rows, expr, ctx)` | DSL-driven row assertions |

## 7. Validation + retry loop

After Sonnet returns content, the orchestrator:

1. Writes the content to a SCRATCH path (NOT the final output_path).
2. Invokes `.claude/scripts/validators/verify-codegen-output.py` with:
   - `--spec-path <scratch>`
   - `--goal-id <goal_id>`
   - `--route <route>`
   - `--interactive-controls-yaml <tmp.yaml>` (the verbatim YAML block written to a temp file)
3. On `PASS` or `WARN` → move scratch to `output_path`, done.
4. On `BLOCK` → re-prompt Sonnet up to **2 retries** (3 attempts total)
   with the validator's evidence diff appended. Re-prompt template:

   ```
   The previous output failed verify-codegen-output with the following evidence:
     {paste validator JSON evidence}
   Re-emit the spec correcting these issues. Same input contract applies.
   ```

5. After 3 consecutive BLOCKs → log a debt entry to the override-debt
   register (kind=`codegen_interactive_giveup`) and fall through to the
   manual codegen path for this goal only. Other goals continue normally.

## 8. DSL grammar (verbatim from SPEC-B § 4)

`expectAssertion` understands exactly these 5 forms (regex-dispatch, NOT eval):

```
rows[*].<field> === param         → every row[field] === ctx.param
rows[*].<field>.includes(param)   → every row[field].toLowerCase().includes(ctx.param.toLowerCase())
rows[*].<field> in [<list>]       → every row[field] is in list
rows monotonically ordered by <f> → array sorted (asc/desc per ctx.dir)
rows.length <= <N>                → length cap
```

Anything else → helper throws `unsupported assertion: ${expr}` at runtime
and validator BLOCKs at codegen-time. If the goal needs an assertion
outside this grammar, the author opts out per-control by setting
`assertion: manual` in the YAML — codegen MAY skip that control entirely.

## 9. Determinism

- Sonnet call uses `temperature: 0`.
- Same input YAML → identical output spec (byte-for-byte).
- Test name patterns are fixed strings (no LLM phrasing variation).
- Slug derivation is deterministic (`goal_id.lower()`).

## 10. Output

The skill returns the .spec.ts content as a string. The orchestrator
handles file write + validator invocation. No side effects from this
skill itself — pure transform.

## 11. Filter + Pagination Test Rigor Pack (Phase 15 D-16, T6.1)

The interactive_controls path delegates `filters[*]` and `pagination` to
a deterministic matrix renderer instead of free-form Sonnet output.

**Matrix module:** `filter-test-matrix.mjs` (this skill dir)
- `FILTER_GROUPS` — 4 groups × 13 sub-cases (coverage 4 + stress 3 +
  state-integrity 3 + edge 3); 14th slot reserved for future additions.
- `PAGINATION_GROUPS` — 6 groups × 18 mandatory sub-cases (+2 optional
  edge: cursor / negative-page).
- Helpers: `enumerateFilterFiles(goal, filter, opts)`,
  `enumeratePaginationFiles(goal, pagination, opts)`,
  `renderTemplate(path, vars)`.

**Templates:** `commands/vg/_shared/templates/{filter|pagination}-<group>.test.tmpl`
(10 files total — 4 filter + 6 pagination). Each template emits ONE
spec file per (control × group) pair, containing N source-level
`test(...)` blocks (one per sub-case). Mustache-lite placeholders:
`{{var.X}}` and `{{#vars.flag}}…{{/vars.flag}}` sections.

**Naming convention** (so validator regex can grep):
- Filter test name: `` `filter <control_name> · <group> · <sub_case>` ``
  (cardinality_enum is loop-driven — single source block × N runtime tests)
- Pagination test name: `` `pagination <control_name> · <group> · <sub_case>` ``

**Validator:** `scripts/validators/verify-filter-test-coverage.py` counts
`test(...)` source blocks whose name contains the control slug AND the
kind keyword (`filter`/`pagination`). Per-control thresholds:
- `EXPECTED_FILTER_CASES = 13`
- `EXPECTED_PAGINATION_CASES = 18`

**Orchestrator flow** (test.md step 5d_codegen branch):
1. For each TEST-GOALS goal with `interactive_controls.filters` or
   `pagination`:
2. Call `enumerateFilterFiles(goal, filter)` and/or
   `enumeratePaginationFiles(goal, pagination)`.
3. For each file descriptor returned, call `renderTemplate(template_path, vars)`.
4. Write rendered string to `${output_dir}/${descriptor.slug}.spec.ts`.
5. Pipe through `verify-filter-test-coverage.py --phase <id>` after all
   files written; BLOCK on shortfall.
