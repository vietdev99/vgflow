---
name: "vg-project"
description: "Entry point — project identity + foundation + auto-init via 7-round adaptive discussion. Replaces standalone /vg:init."
metadata:
  short-description: "Entry point — project identity + foundation + auto-init via 7-round adaptive discussion. Replaces standalone /vg:init."
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

Codex hook processes cannot mutate the environment of later shell tool calls.
If a command-body shell lacks `CLAUDE_SESSION_ID`, `vg-orchestrator` recovers
the session from `.vg/.session-context.json` and the matching
`.vg/active-runs/<session>.json`. Do not create a fresh run when the
UserPromptSubmit hook already registered the same command/phase.

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

Run fenced command-body shell snippets with Bash explicitly, for example
`/bin/bash -lc '<snippet>'`, instead of the user's login shell. VGFlow source
commands use Bash semantics such as `[[ ... ]]`, arrays, `BASH_SOURCE`, and
`set -u`; zsh can misinterpret those snippets and create false failures.

Do not manually retype long command-body heredocs into nested shell strings.
Prefer deterministic Codex helpers shipped in `.claude/scripts/`. For
`/vg:blueprint` STEP 3.1, run `codex-vg-env.py` and
`codex-blueprint-plan-prep.py` exactly as documented in
`_shared/blueprint/plan-overview.md`; then spawn the planner from the prepared
prompt. This avoids zsh glob/quote expansion corrupting Python heredocs before
Bash executes them.

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

`vg-orchestrator` command shapes are positional. Use
`vg-orchestrator step-active <step_name>`,
`vg-orchestrator mark-step <namespace> <step_name>`, and
`vg-orchestrator emit-event <event_type> --payload '{...}'`. Do not use
`step-active <namespace> <step>`, `event --type`, or grouped helper calls
that mix tasklist projection with the first step marker.

For tasklist projection, Codex must write evidence as soon as
`tasklist-contract.json` exists: after `emit-tasklist.py`, run
`vg-orchestrator tasklist-projected --adapter codex` as its own tool call.
Do not group `tasklist-projected` and `step-active` in one shell command;
PreToolUse evaluates the entire command before the evidence file exists and
will block the grouped command. Some command preflights have bootstrap steps
before `emit-tasklist.py`; only those declared bootstrap steps may run before
the tasklist contract exists.

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

When creating prompt files for `codex-spawn.sh`, use a single-quoted heredoc
delimiter such as `cat > "$PROMPT_FILE" <<'EOF'` or write from an existing
template. Do not use unquoted `<<EOF` for prompts that contain backticks,
`$...`, command substitutions, or markdown code fences: the shell will
expand them before Codex sees the prompt and can corrupt the child contract.
If runtime variables must be injected, prefer a small controlled render step
that substitutes placeholders after the quoted template is written.

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

Invoke this skill as `$vg-project`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Use markdown headers in your text output between tool calls (e.g. `## ━━━ Round 3: Tech ambiguities ━━━`). Long Bash > 30s → `run_in_background: true` + `BashOutput` polls.

**Translate English terms (RULE)** — output có thuật ngữ tiếng Anh PHẢI thêm giải thích VN trong dấu ngoặc tại lần đầu xuất hiện. Tham khảo `_shared/term-glossary.md`. Ví dụ: `Foundation (nền tảng)`, `migrate (chuyển đổi)`, `merge (gộp) NOT overwrite (ghi đè)`, `legacy-v1 (định dạng cũ v1)`, `greenfield (dự án mới)`, `brownfield (dự án có codebase)`. Không áp dụng: file path (`PROJECT.md`), code identifier (`D-XX`, `pnpm`), config tag values (`web-saas`), lần lặp lại trong cùng message.
</NARRATION_POLICY>

<rules>
1. **Single entry point** — replaces `/vg:init`. `/vg:init` is now a soft alias for `/vg:project --init-only`.
2. **7-round adaptive discussion** — heavy by design (high-precision projects). Skip rounds where no ambiguity, but never skip Round 4 (high-cost gate).
3. **Three artifacts written atomically** — `PROJECT.md`, `FOUNDATION.md`, `vg.config.md`. All-or-nothing commit.
4. **Foundation = load-bearing** — drives roadmap/init/scope/add-phase. Drift detection ở downstream commands.
5. **MERGE NOT OVERWRITE** — re-runs preserve existing decisions. Only [w] Rewrite resets (with backup).
6. **Resumable** — `${PLANNING_DIR}/.project-draft.json` checkpoints every round. Interrupt-safe.
7. **Brownfield aware** — `--migrate` extracts foundation from existing PROJECT.md + codebase scan.
</rules>

<objective>
First command in VG pipeline. Captures project identity, derives foundation (8 platform/runtime/data/auth/hosting/distribution/scale/compliance dimensions), and auto-generates `vg.config.md` from foundation. All downstream commands (roadmap, scope, blueprint) consume FOUNDATION.md.

Pipeline: **project** → roadmap → map → prioritize → specs → scope → blueprint → build → review → test → accept
</objective>

<process>

<step name="0_parse_args">
## Step 0: Parse args + load config

```bash
PLANNING_DIR=".vg"
PROJECT_FILE="${PLANNING_DIR}/PROJECT.md"
FOUNDATION_FILE="${PLANNING_DIR}/FOUNDATION.md"
CONFIG_FILE=".claude/vg.config.md"
DRAFT_FILE="${PLANNING_DIR}/.project-draft.json"
ARCHIVE_DIR="${PLANNING_DIR}/.archive"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$PLANNING_DIR"

# Mode flags (mutually exclusive)
MODE=""
DOC_PATH=""
INLINE_DESC=""

for arg in $ARGUMENTS; do
  case "$arg" in
    --view)        MODE="view" ;;
    --update)      MODE="update" ;;
    --milestone)   MODE="milestone" ;;
    --rewrite)     MODE="rewrite" ;;
    --migrate)     MODE="migrate" ;;
    --init-only)   MODE="init_only" ;;
    --auto)        MODE="auto" ;;
    @*)            DOC_PATH="${arg#@}" ;;
    *)             INLINE_DESC="${INLINE_DESC} ${arg}" ;;
  esac
done

INLINE_DESC=$(echo "$INLINE_DESC" | sed 's/^ *//; s/ *$//')

PROJECT_EXISTS=false; [ -f "$PROJECT_FILE" ] && PROJECT_EXISTS=true
FOUNDATION_EXISTS=false; [ -f "$FOUNDATION_FILE" ] && FOUNDATION_EXISTS=true
CONFIG_EXISTS=false; [ -f "$CONFIG_FILE" ] && CONFIG_EXISTS=true
DRAFT_EXISTS=false; [ -f "$DRAFT_FILE" ] && DRAFT_EXISTS=true

HAS_CODE=false
for d in apps src packages lib; do
  [ -d "$d" ] && HAS_CODE=true && break
done

: # State printing happens in step 0b after collecting more context
```
</step>

<step name="0b_print_state_summary">
## Step 0b: ALWAYS print state summary first (UX — user không cần nhớ flag)

Mỗi lần `/vg:project` chạy, **bắt buộc** hiển thị state header trước khi làm gì khác. User type `/vg:project` (no args) → ngay lập tức biết hiện trạng + được đề xuất action recommended. Không cần đoán flag.

```bash
# Collect rich state info
PROJECT_AGE=""
[ -f "$PROJECT_FILE" ] && PROJECT_AGE=$(${PYTHON_BIN} -c "
import os, datetime
try:
  ts = os.path.getmtime('$PROJECT_FILE')
  age_days = (datetime.datetime.now().timestamp() - ts) / 86400
  print(f'{int(age_days)}d ago' if age_days >= 1 else 'today')
except Exception: print('?')
" 2>/dev/null)

FOUNDATION_AGE=""
[ -f "$FOUNDATION_FILE" ] && FOUNDATION_AGE=$(${PYTHON_BIN} -c "
import os, datetime
try:
  ts = os.path.getmtime('$FOUNDATION_FILE')
  age_days = (datetime.datetime.now().timestamp() - ts) / 86400
  print(f'{int(age_days)}d ago' if age_days >= 1 else 'today')
except Exception: print('?')
" 2>/dev/null)

CONFIG_AGE=""
[ -f "$CONFIG_FILE" ] && CONFIG_AGE=$(${PYTHON_BIN} -c "
import os, datetime
try:
  ts = os.path.getmtime('$CONFIG_FILE')
  age_days = (datetime.datetime.now().timestamp() - ts) / 86400
  print(f'{int(age_days)}d ago' if age_days >= 1 else 'today')
except Exception: print('?')
" 2>/dev/null)

# Detect codebase profile
CODEBASE_HINT=""
[ -d "apps" ] && CODEBASE_HINT="${CODEBASE_HINT}apps/ "
[ -d "packages" ] && CODEBASE_HINT="${CODEBASE_HINT}packages/ "
[ -d "src" ] && CODEBASE_HINT="${CODEBASE_HINT}src/ "
[ -f "package.json" ] && CODEBASE_HINT="${CODEBASE_HINT}package.json "
[ -f "Cargo.toml" ] && CODEBASE_HINT="${CODEBASE_HINT}Cargo.toml "
[ -f "go.mod" ] && CODEBASE_HINT="${CODEBASE_HINT}go.mod "
[ -f "pubspec.yaml" ] && CODEBASE_HINT="${CODEBASE_HINT}pubspec.yaml(Flutter) "
CODEBASE_HINT=$(echo "$CODEBASE_HINT" | sed 's/ *$//')

echo ""
echo "🔍 ━━━ /vg:project — Hiện trạng project ━━━"
echo ""
printf "  📁 %-32s %s\n" "${PLANNING_DIR}/PROJECT.md"      "$([ "$PROJECT_EXISTS" = "true" ]    && echo "✓ exists ($PROJECT_AGE)"    || echo "✗ missing")"
printf "  📁 %-32s %s\n" "${PLANNING_DIR}/FOUNDATION.md"   "$([ "$FOUNDATION_EXISTS" = "true" ] && echo "✓ exists ($FOUNDATION_AGE)" || echo "✗ missing")"
printf "  📁 %-32s %s\n" ".claude/vg.config.md"      "$([ "$CONFIG_EXISTS" = "true" ]     && echo "✓ exists ($CONFIG_AGE)"     || echo "✗ missing")"
printf "  📁 %-32s %s\n" "${PLANNING_DIR}/.project-draft.json" "$([ "$DRAFT_EXISTS" = "true" ]  && echo "⚠ draft in progress"        || echo "✗ none")"
printf "  🗂  %-32s %s\n" "Codebase"                  "$([ "$HAS_CODE" = "true" ]          && echo "✓ detected ($CODEBASE_HINT)" || echo "✗ none (greenfield)")"
echo ""

# Determine state category for routing + suggestion
STATE=""
if [ "$DRAFT_EXISTS" = "true" ]; then
  STATE="draft-in-progress"
elif [ "$PROJECT_EXISTS" = "true" ] && [ "$FOUNDATION_EXISTS" = "true" ]; then
  STATE="fully-initialized"
elif [ "$PROJECT_EXISTS" = "true" ] && [ "$FOUNDATION_EXISTS" = "false" ]; then
  STATE="legacy-v1"
elif [ "$PROJECT_EXISTS" = "false" ] && [ "$HAS_CODE" = "true" ]; then
  STATE="brownfield-fresh"
else
  STATE="greenfield"
fi
echo "  📊 State: ${STATE}"
echo ""
```
</step>

<step name="0c_scan_existing_docs">
## Step 0c: Scan existing docs/code để auto-fill foundation (avoids treating projects with docs as "greenfield")

Trước khi route mode, **luôn** scan các nguồn document hiện có trong repo. Nếu tìm thấy đủ thông tin (README + manifest + ≥1 doc), chuyển state từ `greenfield` → `greenfield-with-docs` hoặc enrich existing state với pre-populated foundation. User KHÔNG phải gõ lại từ đầu những gì đã có trong README/CLAUDE.md/package.json.

**Skip scan nếu:** `STATE = fully-initialized` (đã có FOUNDATION.md authoritative) HOẶC `STATE = draft-in-progress` (đang resume).

```bash
SCAN_RESULTS_FILE="${PLANNING_DIR}/.project-scan.json"

if [ "$STATE" = "fully-initialized" ] || [ "$STATE" = "draft-in-progress" ]; then
  echo "  (scan skipped — authoritative artifacts exist)"
else
  echo "🔍 Scanning existing docs để extract foundation hints..."
  echo ""

  ${PYTHON_BIN} - "$SCAN_RESULTS_FILE" <<'PY'
import json, re, sys, glob
from pathlib import Path

out = Path(sys.argv[1])

scan = {
  "name": None, "description": None,
  "platform_hints": [], "frontend_hints": [], "backend_hints": [],
  "database_hints": [], "hosting_hints": [], "auth_hints": [],
  "monorepo_hints": [], "test_hints": [], "deploy_hints": [],
  "docs_found": [], "rich": False
}

# 1. README + multi-language variants
for readme in ["README.md", "README.vi.md", "readme.md", "Readme.md"]:
    p = Path(readme)
    if not p.exists(): continue
    text = p.read_text(encoding="utf-8", errors="ignore")[:8000]
    m = re.search(r'^#\s+(.+)$', text, re.M)
    if m and not scan["name"]:
        scan["name"] = m.group(1).strip()[:80]
    # First non-empty paragraph after title likely description
    paras = [p.strip() for p in text.split('\n\n') if p.strip() and not p.startswith('#')]
    if paras and not scan["description"]:
        scan["description"] = paras[0][:500]
    scan["docs_found"].append(readme)

# 2. package.json — primary tech stack signal
pkg_path = Path("package.json")
if pkg_path.exists():
    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        if not scan["name"]: scan["name"] = pkg.get("name")
        if not scan["description"]: scan["description"] = pkg.get("description")
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        # Frontend
        if "react" in deps: scan["frontend_hints"].append("React")
        if "vite" in deps: scan["frontend_hints"].append("Vite")
        if "next" in deps: scan["frontend_hints"].append("Next.js")
        if "vue" in deps: scan["frontend_hints"].append("Vue")
        if "svelte" in deps or "@sveltejs/kit" in deps: scan["frontend_hints"].append("Svelte/SvelteKit")
        if "@angular/core" in deps: scan["frontend_hints"].append("Angular")
        if "solid-js" in deps: scan["frontend_hints"].append("Solid")
        # Backend
        if "fastify" in deps: scan["backend_hints"].append("Fastify")
        if "express" in deps: scan["backend_hints"].append("Express")
        if "@nestjs/core" in deps: scan["backend_hints"].append("NestJS")
        if "hono" in deps: scan["backend_hints"].append("Hono")
        if "koa" in deps: scan["backend_hints"].append("Koa")
        # Database
        if "mongodb" in deps or "mongoose" in deps: scan["database_hints"].append("MongoDB")
        if "pg" in deps or "postgres" in deps: scan["database_hints"].append("Postgres")
        if "mysql2" in deps or "mysql" in deps: scan["database_hints"].append("MySQL")
        if "better-sqlite3" in deps or "sqlite3" in deps: scan["database_hints"].append("SQLite")
        if "redis" in deps or "ioredis" in deps: scan["database_hints"].append("Redis")
        if "prisma" in deps or "@prisma/client" in deps: scan["database_hints"].append("(Prisma ORM)")
        if "drizzle-orm" in deps: scan["database_hints"].append("(Drizzle ORM)")
        # Mobile / desktop
        if "expo" in deps: scan["platform_hints"].append("mobile-cross (Expo)")
        if "react-native" in deps and "expo" not in deps: scan["platform_hints"].append("mobile-cross (RN bare)")
        if "electron" in deps: scan["platform_hints"].append("desktop (Electron)")
        if "@tauri-apps/api" in deps: scan["platform_hints"].append("desktop (Tauri)")
        # Test
        if "playwright" in deps or "@playwright/test" in deps: scan["test_hints"].append("Playwright")
        if "vitest" in deps: scan["test_hints"].append("Vitest")
        if "jest" in deps: scan["test_hints"].append("Jest")
        if "cypress" in deps: scan["test_hints"].append("Cypress")
        # Auth libs
        if "passport" in deps or "@auth/core" in deps: scan["auth_hints"].append("custom (passport/auth)")
        if "next-auth" in deps: scan["auth_hints"].append("NextAuth.js")
        if "@clerk/nextjs" in deps or "@clerk/clerk-react" in deps: scan["auth_hints"].append("Clerk (3rd-party)")
        if "@auth0/" in str(deps): scan["auth_hints"].append("Auth0 (3rd-party)")
        scan["docs_found"].append("package.json")
    except Exception as e:
        pass

# 3. Other language manifests
if Path("Cargo.toml").exists():
    scan["backend_hints"].append("Rust")
    scan["docs_found"].append("Cargo.toml")
if Path("go.mod").exists():
    scan["backend_hints"].append("Go")
    scan["docs_found"].append("go.mod")
if Path("pubspec.yaml").exists():
    scan["frontend_hints"].append("Flutter")
    scan["platform_hints"].append("mobile-cross (Flutter)")
    scan["docs_found"].append("pubspec.yaml")
if Path("requirements.txt").exists() or Path("pyproject.toml").exists():
    scan["backend_hints"].append("Python")
    scan["docs_found"].append("requirements.txt or pyproject.toml")
if Path("Gemfile").exists():
    scan["backend_hints"].append("Ruby")
    scan["docs_found"].append("Gemfile")

# 4. Monorepo
if Path("pnpm-workspace.yaml").exists() or Path("turbo.json").exists():
    scan["monorepo_hints"].append("pnpm + Turborepo")
elif Path("nx.json").exists():
    scan["monorepo_hints"].append("Nx")
elif Path("lerna.json").exists():
    scan["monorepo_hints"].append("Lerna")
elif Path("rush.json").exists():
    scan["monorepo_hints"].append("Rush")

# 5. Infra / hosting / deploy
if Path("infra/ansible").is_dir() or Path("ansible").is_dir():
    scan["hosting_hints"].append("VPS (Ansible)")
    scan["deploy_hints"].append("Ansible playbooks")
if Path("Dockerfile").exists() or Path("docker-compose.yml").exists() or Path("docker-compose.yaml").exists():
    scan["hosting_hints"].append("Docker")
if Path("vercel.json").exists() or Path(".vercel").is_dir():
    scan["hosting_hints"].append("Vercel")
if Path("netlify.toml").exists():
    scan["hosting_hints"].append("Netlify")
if Path("fly.toml").exists():
    scan["hosting_hints"].append("Fly.io")
if Path("render.yaml").exists():
    scan["hosting_hints"].append("Render")
if Path("railway.json").exists() or Path("railway.toml").exists():
    scan["hosting_hints"].append("Railway")
if Path("serverless.yml").exists() or Path("serverless.yaml").exists():
    scan["hosting_hints"].append("Serverless Framework")
if Path("template.yaml").exists() or Path("samconfig.toml").exists():
    scan["hosting_hints"].append("AWS SAM")
if Path("wrangler.toml").exists():
    scan["hosting_hints"].append("Cloudflare Workers")
if Path(".github/workflows").is_dir():
    scan["deploy_hints"].append("GitHub Actions")
if Path(".gitlab-ci.yml").exists():
    scan["deploy_hints"].append("GitLab CI")

# 6. Auth code patterns
for auth_glob in ["apps/*/src/**/auth*", "src/**/auth*", "apps/*/src/modules/auth"]:
    if any(Path(p).exists() for p in glob.glob(auth_glob, recursive=True)[:1]):
        if not scan["auth_hints"]:
            scan["auth_hints"].append("custom (apps/*/auth code detected)")
        break

# 7. CLAUDE.md — often contains rich project description (per convention)
for claude_md in ["CLAUDE.md", ".claude/CLAUDE.md"]:
    p = Path(claude_md)
    if not p.exists(): continue
    text = p.read_text(encoding="utf-8", errors="ignore")
    # Look for "## Project" or "## Overview" section
    for header in [r'^##\s*Project\b', r'^##\s*Overview\b', r'^##\s*About\b']:
        m = re.search(header + r'[\s\S]*?(?=^##|\Z)', text, re.M)
        if m:
            section = m.group(0).strip()
            if not scan["description"] or len(scan["description"]) < 200:
                scan["description"] = section[:800]
            break
    scan["docs_found"].append(claude_md)

# 8. Brief / spec docs
for pattern in ["docs/**/*.md", "BRIEF.md", "SPEC.md", "RFC*.md", "*-brief.md", "*-spec.md"]:
    for f in glob.glob(pattern, recursive=True)[:3]:
        if f not in scan["docs_found"] and "vendor" not in f and "node_modules" not in f:
            scan["docs_found"].append(f)

# 9. ${PLANNING_DIR}/ deep scan — toàn bộ artifacts từ pipeline trước
planning_dir = Path(".vg")
if planning_dir.is_dir():
    # 9a. PROJECT.md (legacy or current)
    legacy_project = planning_dir / "PROJECT.md"
    if legacy_project.exists():
        text = legacy_project.read_text(encoding="utf-8", errors="ignore")
        if not scan["description"]:
            scan["description"] = text[:800]
        if not scan["name"]:
            m = re.search(r'^#\s+(.+)$', text, re.M)
            if m: scan["name"] = m.group(1).strip()[:80]
        scan["docs_found"].append("${PLANNING_DIR}/PROJECT.md (legacy)")

    # 9b. REQUIREMENTS.md — list of REQ-XX items
    req_file = planning_dir / "REQUIREMENTS.md"
    if req_file.exists():
        text = req_file.read_text(encoding="utf-8", errors="ignore")
        req_count = len(re.findall(r'\b(REQ|R)-?\d+\b', text))
        scan["docs_found"].append(f"${PLANNING_DIR}/REQUIREMENTS.md ({req_count} requirements)")

    # 9c. ROADMAP.md — phase plan
    roadmap_file = planning_dir / "ROADMAP.md"
    if roadmap_file.exists():
        text = roadmap_file.read_text(encoding="utf-8", errors="ignore")
        phase_count = len(re.findall(r'^##?\s*Phase\s+[\d.]+', text, re.M))
        scan["docs_found"].append(f"${PLANNING_DIR}/ROADMAP.md ({phase_count} phases)")

    # 9d. STATE.md — pipeline progress snapshot
    state_file = planning_dir / "STATE.md"
    if state_file.exists():
        scan["docs_found"].append("${PLANNING_DIR}/STATE.md (pipeline state snapshot)")

    # 9e. SCOPE.md / PROJECT-SCOPE.md
    for scope_name in ["SCOPE.md", "PROJECT-SCOPE.md"]:
        scope_file = planning_dir / scope_name
        if scope_file.exists():
            scan["docs_found"].append(f"${PLANNING_DIR}/{scope_name}")

    # 9f. phases/ directory — count + extract phase titles
    phases_dir = planning_dir / "phases"
    if phases_dir.is_dir():
        phase_dirs = sorted([p for p in phases_dir.iterdir() if p.is_dir()])
        if phase_dirs:
            # Count phases by status (look for SUMMARY.md, UAT.md as completion markers)
            completed = sum(1 for p in phase_dirs if (p / "UAT.md").exists())
            in_progress = sum(1 for p in phase_dirs if (p / "SUMMARY.md").exists() and not (p / "UAT.md").exists())
            scan["docs_found"].append(
                f"${PLANNING_DIR}/phases/ ({len(phase_dirs)} dirs: {completed} accepted, {in_progress} in-progress)"
            )
            # Extract titles of latest 3 phases for context
            for p in phase_dirs[-3:]:
                # phase name from dir like "07.10.1-user-drawer-tabs" → human title
                parts = p.name.split("-", 1)
                if len(parts) == 2:
                    scan["docs_found"].append(f"   • Phase {parts[0]}: {parts[1].replace('-', ' ')}")

    # 9g. intel/ — codebase intel files
    intel_dir = planning_dir / "intel"
    if intel_dir.is_dir():
        intel_count = len(list(intel_dir.glob("*.md")))
        if intel_count > 0:
            scan["docs_found"].append(f"${PLANNING_DIR}/intel/ ({intel_count} intel files)")

    # 9h. codebase/ — codebase mapping docs
    codebase_dir = planning_dir / "codebase"
    if codebase_dir.is_dir():
        codebase_count = len(list(codebase_dir.glob("*.md")))
        if codebase_count > 0:
            scan["docs_found"].append(f"${PLANNING_DIR}/codebase/ ({codebase_count} mapping docs)")

    # 9i. research/ — pre-roadmap research
    research_dir = planning_dir / "research"
    if research_dir.is_dir():
        research_count = len(list(research_dir.glob("*.md")))
        if research_count > 0:
            scan["docs_found"].append(f"${PLANNING_DIR}/research/ ({research_count} research docs)")

    # 9j. design refs — v2.30+ 2-tier (phase-scoped + project-shared) +
    # legacy compat. Sum design refs across all known locations.
    design_count = 0
    # Tier 2: project-shared (.vg/design-system/)
    shared_dir = planning_dir.parent / ".vg" / "design-system"
    if shared_dir.is_dir():
        design_count += len(list(shared_dir.rglob("*.md"))) + len(list(shared_dir.rglob("*.png")))
    # Tier 1: phase-scoped (.vg/phases/{N}/design/)
    phases_dir = planning_dir.parent / ".vg" / "phases"
    if phases_dir.is_dir():
        for ph in phases_dir.iterdir():
            phd = ph / "design"
            if phd.is_dir():
                design_count += len(list(phd.rglob("*.md"))) + len(list(phd.rglob("*.png")))
    # Tier 3: legacy (.planning/design-normalized/, .vg/design-normalized/)
    for legacy in (planning_dir / "design-normalized", planning_dir.parent / ".vg" / "design-normalized"):
        if legacy.is_dir():
            design_count += len(list(legacy.rglob("*.md"))) + len(list(legacy.rglob("*.png")))
    if design_count > 0:
        scan["docs_found"].append(f"design refs across phase/shared/legacy ({design_count} files)")

    # 9k. milestones/ — completed milestone archives
    milestones_dir = planning_dir / "milestones"
    if milestones_dir.is_dir():
        milestone_count = len(list(milestones_dir.iterdir()))
        if milestone_count > 0:
            scan["docs_found"].append(f"${PLANNING_DIR}/milestones/ ({milestone_count} archived milestones)")

    # 9l. Top-level loose docs in ${PLANNING_DIR}/
    for f in planning_dir.glob("*.md"):
        if f.name not in {"PROJECT.md", "FOUNDATION.md", "REQUIREMENTS.md", "ROADMAP.md", "STATE.md", "SCOPE.md", "PROJECT-SCOPE.md"}:
            scan["docs_found"].append(f"${PLANNING_DIR}/{f.name}")

# 10. Existing vg.config.md (already-confirmed config — highest trust)
if Path(".claude/vg.config.md").exists():
    scan["docs_found"].append(".claude/vg.config.md (existing config)")

# Determine "richness": if scan found enough info to skip pure-greenfield
non_empty_buckets = sum(1 for k in [
    "frontend_hints","backend_hints","database_hints","hosting_hints",
    "platform_hints","auth_hints","monorepo_hints"
] if scan[k])
scan["rich"] = (
    scan["name"] is not None and
    (scan["description"] is not None or non_empty_buckets >= 2) and
    len(scan["docs_found"]) >= 1
)

out.write_text(json.dumps(scan, indent=2, ensure_ascii=False), encoding="utf-8")

# Print human summary
print(f"  📄 Docs detected: {len(scan['docs_found'])}")
for d in scan["docs_found"][:8]:
    print(f"     • {d}")
if len(scan["docs_found"]) > 8:
    print(f"     • ...and {len(scan['docs_found']) - 8} more")
print()
print("  🤖 Foundation hints extracted:")
if scan["name"]:        print(f"     • Name:       {scan['name']}")
if scan["description"]: print(f"     • Description: {scan['description'][:80]}...")
if scan["platform_hints"]: print(f"     • Platform:   {', '.join(scan['platform_hints'])}")
if scan["frontend_hints"]: print(f"     • Frontend:   {', '.join(scan['frontend_hints'])}")
if scan["backend_hints"]:  print(f"     • Backend:    {', '.join(scan['backend_hints'])}")
if scan["database_hints"]: print(f"     • Database:   {', '.join(scan['database_hints'])}")
if scan["hosting_hints"]:  print(f"     • Hosting:    {', '.join(scan['hosting_hints'])}")
if scan["auth_hints"]:     print(f"     • Auth:       {', '.join(scan['auth_hints'])}")
if scan["monorepo_hints"]: print(f"     • Monorepo:   {', '.join(scan['monorepo_hints'])}")
if scan["test_hints"]:     print(f"     • Test:       {', '.join(scan['test_hints'])}")
if scan["deploy_hints"]:   print(f"     • Deploy:     {', '.join(scan['deploy_hints'])}")
print()
print(f"  Result: {'RICH (auto-fill ready)' if scan['rich'] else 'SPARSE (need user input)'}")
PY

  # Read result + upgrade STATE if scan was rich
  if [ -f "$SCAN_RESULTS_FILE" ]; then
    SCAN_RICH=$(${PYTHON_BIN} -c "import json; print(json.load(open('${SCAN_RESULTS_FILE}'))['rich'])" 2>/dev/null)
    if [ "$SCAN_RICH" = "True" ] && [ "$STATE" = "greenfield" ]; then
      STATE="greenfield-with-docs"
      echo "  📊 State upgraded: greenfield → greenfield-with-docs (scan results sufficient)"
    elif [ "$SCAN_RICH" = "True" ] && [ "$STATE" = "brownfield-fresh" ]; then
      STATE="brownfield-with-docs"
      echo "  📊 State upgraded: brownfield-fresh → brownfield-with-docs"
    fi
  fi
  echo ""
fi
```
</step>

<step name="1_route_mode">
## Step 1: Route to mode (state-aware suggestion if MODE not explicit)

If user passed an explicit flag (`--update`, `--migrate`, etc.), validate flag matches state — warn if mismatch but proceed. If NO flag, present **state-tailored menu** (different options shown based on STATE category — không cần user nhớ flag nào).

```bash
# Validate explicit flags against state — warn if mismatch
if [ -n "$MODE" ]; then
  case "${MODE}-${STATE}" in
    migrate-greenfield|migrate-fully-initialized)
      echo "⚠ --migrate yêu cầu PROJECT.md cũ tồn tại + FOUNDATION.md missing."
      echo "   Hiện trạng: ${STATE}. Migration không cần thiết."
      echo "   Bạn có thể đang muốn: $([ "$STATE" = "greenfield" ] && echo "/vg:project (first-time)" || echo "/vg:project --update")"
      exit 0
      ;;
    init_only-greenfield|init_only-legacy-v1)
      echo "⚠ --init-only yêu cầu FOUNDATION.md tồn tại."
      echo "   Hiện trạng: ${STATE}."
      echo "   Bạn có thể đang muốn: $([ "$STATE" = "legacy-v1" ] && echo "/vg:project --migrate" || echo "/vg:project (first-time)")"
      exit 0
      ;;
    update-greenfield|milestone-greenfield)
      echo "⚠ --${MODE} yêu cầu artifacts đã tồn tại. Hiện trạng: greenfield."
      echo "   Bạn có thể đang muốn: /vg:project (first-time)"
      exit 0
      ;;
  esac
fi

# Auto-detect mode based on state if no explicit flag
if [ -z "$MODE" ]; then
  case "$STATE" in
    draft-in-progress)    MODE="resume_check" ;;     # Always offer resume/discard first
    fully-initialized)    MODE="state_menu_full" ;;  # Show full re-run menu (view/update/milestone/rewrite)
    legacy-v1)            MODE="state_menu_legacy" ;;# Recommend migrate, offer alternatives
    brownfield-fresh)     MODE="state_menu_brown" ;; # Recommend first-time with codebase scan, or migrate hint
    greenfield)           MODE="first_time" ;;       # Direct to capture (Round 1)
  esac
fi
```

### State menus (presented to user — proactive suggestion, no need to remember flags)

**state=fully-initialized → `state_menu_full`:**
```
✅ Project đã đầy đủ artifacts (PROJECT + FOUNDATION + config). Bạn muốn:

   [v] View      In hiện trạng, không đổi gì                  (default safe)
   [u] Update    Discussion bổ sung, MERGE giữ phần không touch
   [m] Milestone Append milestone mới (foundation untouched)
   [w] Rewrite   Reset toàn bộ (backup → .archive/{ts}/, full re-run)
   [c] Cancel    Exit, không làm gì

   Nhập 1 ký tự: [v/u/m/w/c]
```
Map answer to MODE: v→view, u→update, m→milestone, w→rewrite. Default if cancelled = view.

**state=legacy-v1 → `state_menu_legacy`:**
```
⚠ Project legacy v1 format — có PROJECT.md cũ nhưng chưa có FOUNDATION.md.

   Đề xuất: ⭐ [m] Migrate (RECOMMENDED)
            Tự extract FOUNDATION.md từ PROJECT.md + scan codebase + vg.config.md cũ
            Backup PROJECT.md v1 → ${PLANNING_DIR}/.archive/{ts}/PROJECT.v1.md
            → /vg:project --migrate

   Lựa chọn khác:
   [v] View    In PROJECT.md hiện có, không đổi
   [w] Rewrite Bỏ hết v1, làm lại từ đầu (backup v1)
   [c] Cancel  Exit

   Nhập 1 ký tự: [m/v/w/c]   (default: m)
```
Map: m→migrate, v→view, w→rewrite, c→exit.

**state=brownfield-fresh → `state_menu_brown`:**
```
🗂  Phát hiện codebase hiện có ($CODEBASE_HINT) nhưng chưa có planning artifacts.

   Đề xuất: ⭐ [f] First-time với codebase scan (RECOMMENDED)
            Bot sẽ scan codebase trước, suggest defaults cho 7-round discussion.
            User chỉ cần xác nhận / điều chỉnh.
            → /vg:project (sẽ auto detect codebase trong Round 2)

   Lựa chọn khác:
   [d] Describe — chỉ mô tả thuần text, bỏ qua scan codebase (greenfield-style)
   [c] Cancel   Exit

   Nhập 1 ký tự: [f/d/c]   (default: f)
```
Map: f→first_time (codebase-aware), d→first_time (no scan), c→exit.

**state=draft-in-progress → `resume_check`:** (same as before — offer resume/discard/view of draft)

**state=greenfield → `first_time` direct:** No menu, jump straight to Round 1 capture (most common new-project case).

### Pretty header before menu

Always print MODE chosen + brief explanation before invoking handler:
```
━━━ Mode: [view|update|milestone|rewrite|migrate|first_time|init_only] ━━━
{1-line description of what's about to happen}
```

User chỉ cần gõ `/vg:project` — toàn bộ logic tự dẫn dắt.
</step>

<step name="2a_resume_check">
## Step 2a: Resume draft check (if `.project-draft.json` exists)

Read draft, show progress, ask user:

```bash
if [ "$MODE" = "resume_check" ]; then
  ${PYTHON_BIN} - "$DRAFT_FILE" <<'PY'
import json, sys, datetime
from pathlib import Path
d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
ts = d.get("started_at", "?")
try:
  started = datetime.datetime.fromisoformat(ts)
  age_min = int((datetime.datetime.now(started.tzinfo) - started).total_seconds() / 60)
except Exception:
  age_min = "?"
print(f"Draft from {ts} (age {age_min}m), at Round {d.get('current_round','?')}/7")
print(f"Captured description: {d.get('captured', {}).get('description', '(none)')[:120]}...")
PY
fi
```

Use AskUserQuestion:
- "Resume draft from Round X?" → [r] Resume / [d] Discard + restart / [v] View draft only

If resume → load draft state → jump to current round.
If discard → `rm -f $DRAFT_FILE` → set `MODE=first_time`.
If view → pretty-print draft → exit.
</step>

<step name="2b_mode_menu">
## Step 2b: Mode menu (when artifacts exist, no explicit mode flag)

Use AskUserQuestion with exact wording:

```
"PROJECT.md + FOUNDATION.md đã tồn tại. Bạn muốn:
 [v] View          — In hiện trạng, không đổi gì (default safe)
 [u] Update        — Discussion bổ sung, MERGE giữ phần không touch
 [m] New milestone — Append milestone mới + mô tả mục tiêu
 [w] Rewrite       — Reset toàn bộ (backup → .archive/{ts}/, full re-run)"
```

Map answer to MODE: v→view, u→update, m→milestone, w→rewrite. Default if cancelled = view.
</step>

<step name="3_mode_view">
## Step 3 (mode=view): Pretty-print current state

```bash
if [ "$MODE" = "view" ]; then
  echo ""
  echo "## ━━━ Project Overview ━━━"
  echo ""
  if [ -f "$FOUNDATION_FILE" ]; then
    # Print Foundation table + Decisions section
    sed -n '/^## Platform/,/^## Open/p' "$FOUNDATION_FILE"
    echo ""
    sed -n '/^## Decisions/,/^## /p' "$FOUNDATION_FILE" | head -60
  else
    echo "(no FOUNDATION.md — run /vg:project --migrate to create)"
  fi
  echo ""
  echo "## ━━━ Project ━━━"
  [ -f "$PROJECT_FILE" ] && head -50 "$PROJECT_FILE"
  echo ""
  echo "## ━━━ Config (auto-derived) ━━━"
  [ -f "$CONFIG_FILE" ] && grep -E "^(name|dev_command|build_command|deploy|infra_markers):" "$CONFIG_FILE" | head -20
  echo ""
  echo "Modes: --update | --milestone | --rewrite | --migrate"
  exit 0
fi
```
</step>

<step name="4_mode_first_time">
## Step 4 (mode=first_time): 7-round adaptive discussion

This is the heart. Each round is a model-driven conversational step. Save draft after each round.

**Adversarial challenger (v1.9.1 R3):** Source `.claude/commands/vg/_shared/lib/answer-challenger.sh` at top of command. After EVERY user answer in Rounds 1, 3, 4, 5 (Round 2 = model presents table, no free answer; Round 6/7 = automated), invoke:

```bash
challenge_answer "$user_answer" "round-$ROUND" "project-foundation" "$accumulated_foundation_draft"
```

Orchestrator protocol (identical to scope.md):
1. Read subagent prompt file (path emitted on fd 3 + stderr)
2. Dispatch Task tool → model=`${config.scope.adversarial_model:-haiku}`, zero parent context
3. Parse stdout → one JSON line: `{has_issue, issue_kind, evidence, follow_up_question, proposed_alternative}`
4. Call `challenger_dispatch "$json" "round-$ROUND" "project-foundation" "project"` (phase=literal "project" for FOUNDATION rounds)
5. If `has_issue=true` → AskUserQuestion with 3 options:
   - **Address** → re-ask the round with revised prompt incorporating challenger's follow_up
   - **Acknowledge** → append to `FOUNDATION.md` draft under `## Acknowledged tradeoffs`
   - **Defer** → append under `## Open questions`
6. Call `challenger_record_user_choice "project" "round-$ROUND" "project-foundation" "$choice"`
7. Loop guard: helper auto-caps at `config.scope.adversarial_max_rounds` (default 3) per session

Skip when `config.scope.adversarial_check: false` or answer is trivial (helper auto-detects).

### Round 1: Capture description

If `$INLINE_DESC` non-empty → use as description, skip prompt.
If `$DOC_PATH` set → read file, use as description.
Else → AskUserQuestion:

```
"Mô tả dự án bằng ngôn ngữ tự nhiên. Càng chi tiết càng tốt — AI sẽ tự suy ra
 foundation và config. Có thể dán paragraph tự do hoặc trả lời theo template:

 - Tên / mục tiêu (vấn đề giải quyết):
 - Người dùng (ai sẽ dùng, bao nhiêu người):
 - Tech stack (nếu đã có ý kiến): 
 - Deploy target (VPS/cloud/app-store/...):
 - Constraint quan trọng (latency/scale/compliance/budget):
 - Brownfield? (có codebase sẵn không, đường dẫn ở đâu)"
```

User responds (1 paragraph or template-filled). Save raw to draft.

```bash
${PYTHON_BIN} - <<PY
import json, datetime
from pathlib import Path
draft = {
  "started_at": datetime.datetime.now().isoformat(),
  "current_round": 1,
  "captured": {"description": """<USER_RESPONSE_HERE>"""},
  "derived": {},
  "decisions": [],
  "status": "in_progress"
}
Path("${DRAFT_FILE}").write_text(json.dumps(draft, indent=2), encoding="utf-8")
PY
```

### Round 2: Parse + present overview

Model parses description into 8 dimensions. Present as table with status flags:
- ✓ derived (clearly stated in description)
- ? ambiguous (mentioned but not specific — "React" without Vite/Next)
- ⚠ missing (not mentioned, default applied)
- 🔒 high-cost (always require Round 4 confirm regardless of source)

```
## Foundation derived (Round 2)

| # | Dimension | Value | Status | Notes |
|---|-----------|-------|--------|-------|
| 1 | Platform | web-saas | ✓🔒 | "SaaS quản lý nhân sự" |
| 2 | Frontend runtime | browser | ✓ | implied |
| 3 | Frontend framework | React | ?🔒 | Vite vs Next.js? |
| 4 | Backend topology | monolith | ✓🔒 | Fastify mentioned |
| 5 | Data layer | SQL (Postgres?) | ✓🔒 | Postgres mentioned |
| 6 | Auth model | own | ⚠ | not mentioned, default |
| 7 | Hosting | VPS | ✓🔒 | "deploy lên VPS" |
| 8 | Distribution | URL | ✓ | implied web |
| 9 | Scale | small (50 users) | ✓ | mentioned |
| 10| Compliance | none | ⚠ | not mentioned |

Routing:
- ? items → Round 3 (targeted dialog)
- 🔒 items → Round 4 (high-cost gate, mandatory confirm)
- ⚠ items → Round 5 (constraints fill-in)
- ✓ + non-🔒 → no further dialog
```

Save draft with `current_round=2, derived.foundation_v1=<table>`.

Ask AskUserQuestion: "OK với suy luận này? [y] Yes proceed / [a] Adjust dimension / [d] Discuss deeper from start"

### Round 3: Targeted dialog (skip if no `?` items)

For EACH `?` dimension, model presents OPTIONS with TRADE-OFFS, asks user:

```
"Dimension {N}: Frontend framework
 Bạn nhắc 'React' nhưng có nhiều route đi:

 - Vite + React Router    — SPA thuần, simple, không SEO. Phù hợp internal tool.
 - Next.js (app router)   — SSR + SEO + RSC. Phù hợp public-facing có search.
 - Remix                  — SSR + nested routing tốt. Ít user hơn Next.js.

 Mình đề xuất: Vite (vì internal tool 50 users, SEO không cần).
 [v] Vite (recommended) [n] Next.js [r] Remix [s] Skip — quyết sau"
```

User answers → record F-XX trong decisions array.

**Namespace (không gian tên) note — BREAKING CHANGE v1.8.0:**
- FOUNDATION.md decisions use `F-XX` (project-level, stable across milestones). Ví dụ: `F-01` = Platform decision.
- Per-phase CONTEXT.md decisions use `P{phase}.D-XX` (scoped to phase). Ví dụ: `P7.10.1.D-12` = decision 12 of phase 7.10.1.
- Bare `D-XX` is LEGACY (còn chấp nhận bởi commit-msg hook tới v1.10.0, sau đó reject).
- Rationale: ngăn collision (xung đột) khi phase 15+ có `D-12` trùng với FOUNDATION `D-12` → AI agents cite sai source.
- Migration (chuyển đổi) tool: `.claude/scripts/migrate-d-xx-namespace.py` — tự động rename trong mọi artifact.

### Round 4: High-cost confirmation gate (MANDATORY — never skip)

Model presents ALL `🔒` decisions as a single confirm gate (using new F-XX namespace):

```
"⚠ HIGH-COST DECISIONS (irreversible — confirm explicit trước khi lock):

  🔒 F-01 Platform: web-saas
     Đổi sau = rewrite ~80% UI (sang mobile/desktop). 

  🔒 F-03 Frontend framework: Vite
     Đổi sang Next.js sau = re-architect routing + data fetching.

  🔒 F-04 Backend topology: monolith Fastify
     Đổi sang serverless = re-architect deploy + state management.

  🔒 F-05 Database: Postgres
     Đổi sang NoSQL = data layer rewrite + migration script.

  🔒 F-07 Hosting: VPS
     Đổi sang Vercel/cloud = redeploy infra + CI/CD redo.

 Confirm tất cả? [y] Yes / [r] Revisit dimension cụ thể / [a] Abort"
```

NEVER auto-skip Round 4. Even with `--auto` mode, must confirm. All IDs here are `F-XX` (FOUNDATION namespace).

### Round 5: Constraints fill-in (skip if all answered)

For each `⚠` dimension still missing or default-applied, ask (record as F-XX):

```
"Constraint: Compliance (F-10)
 Bạn không nhắc — default 'none'. Có cần GDPR/HIPAA/SOC2 không?
 [n] None [g] GDPR [h] HIPAA [s] SOC2 [m] Multiple (specify)"
```

Cover: scale (precise users), latency budget, compliance, team size, budget tier. All foundation-scope constraints → F-XX.

### Round 6: Auto-derive vg.config.md from foundation

Model derives config tự động dựa trên foundation. Show preview:

```
## vg.config.md preview (auto-derived from FOUNDATION)

```yaml
project:
  name: <from PROJECT description>
  type: web-saas

frontend:
  framework: vite
  port: 5173
  dev_command: pnpm dev --filter web

backend:
  framework: fastify
  port: 3001
  dev_command: pnpm dev --filter api
  health_endpoint: /health

build_gates:
  typecheck_cmd: pnpm turbo typecheck
  test_cmd: pnpm turbo test
  e2e_cmd: pnpm turbo e2e

deploy:
  target: vps
  ssh_alias: <NEED_USER_INPUT>     ← chỉ field này cần hỏi
  health_url: https://<your-domain>/health  ← cần xác nhận

models:
  executor: sonnet
  planner: opus

(... các field khác auto-fill từ foundation)
```

Hỏi user chỉ những field có `<NEED_USER_INPUT>` placeholder. Không hỏi gì thêm nếu foundation đủ rõ.
```

### Round 7: Architecture Lock (v2.5 Phase D)

**Purpose:** Lock the 8 architectural subsections that govern every future phase. Without this, executors drift across models — FE naming conventions diverge between phases, security baseline degrades, performance budgets get reinvented each phase. This is the single most important section for cross-model code consistency.

The 8 subsections are appended to `FOUNDATION.md` as `## 9. Architecture Lock` and get injected into every blueprint planner prompt as `<architecture_context>`.

**Flow (each subsection = 1 Q with dimension-appropriate depth):**

```
"9.1 Tech stack matrix — xác nhận stack cụ thể:
 [tự-fill từ F-01..F-08 discovered in rounds 1-5]
 - Lang: {FE: React+TS, BE: Node+TS, RTB: Rust}
 - DB: {primary: MongoDB, analytics: ClickHouse, cache: Redis}
 - Auth: {session-cookie SameSite=Strict + argon2id}
 - Deploy: {rsync+PM2 for Node, systemctl for Rust, ansible provisioning}
 - CI: {GitHub Actions with turbo cache}

 Confirm?  [y] keep  [e] edit specific field  [a] add alternative considered"

"9.2 Module boundary — how do apps/packages/shared depend?
 Example: apps/web → packages/ui-kit (allowed), apps/api → packages/schemas (allowed),
 apps/web → apps/api (BANNED — go through HTTP only), packages/* → apps/* (BANNED).
 Apply same pattern? Or project has specific boundaries?
 [y] standard (apps→packages→shared) [e] custom rules [n] skip"

"9.3 Folder convention — route layout + test colocation + asset org
 Typical: apps/api/src/modules/{feature}/{routes,schemas,services}.ts
          apps/web/src/features/{feature}/{components,hooks,pages}.tsx
          tests colocated (.test.ts next to impl) + e2e in apps/web/e2e/
 [y] adopt standard  [e] describe custom convention  [s] skip if existing codebase"

"9.4 Cross-cutting concerns — logging, error handling, async pattern, i18n
 Logging: {pino structured JSON? or winston? or console wrapper?}
 Error handling: {throw + global error handler? Result<T,E>? both?}
 Async: {async/await consistently | callbacks never | worker queues for long jobs}
 i18n: {project has multi-locale? vi+en? keys format?}
 Answer each or 'skip' for unused"

"9.5 Security baseline (LOCK ONCE, applies to all phases):
 Đây là tầng 2 (identity/session) + tầng 3 (server hardening).
 - Session token: {JWT RS256 | opaque session cookie | both?}
 - Lifetime: access ≤ 15min, refresh ≤ 7 days rotated
 - Cookie flags: Secure + HttpOnly + SameSite=Strict
 - CORS: whitelist origins (không wildcard với credentials)
 - OAuth: PKCE mandatory cho public clients (SPA, mobile)
 - Password: argon2id work factor min, length ≥ 12
 - 2FA: {TOTP | SMS | none based on risk profile}
 - Audit log events: {login/logout/role-change/data-export logged with user_id + IP}
 - TLS: version ≥ 1.2, HSTS max-age ≥ 31536000 + includeSubDomains
 - Security headers: CSP default-src 'self', X-Frame-Options DENY, X-Content-Type-Options nosniff
 - Secret management: {Vault | SOPS | KMS | .env + never commit}
 - Dependency: lockfile + CVE scan (deps-security-scan validator)
 - Backup: encrypted at rest (AES-256), {daily|weekly} offsite copy
 - Compliance flags: {GDPR|HIPAA|SOC2|PCI-DSS|none} applicability

 Quan trọng: những giá trị này sẽ đi vào verify-security-baseline gate.
 Nếu không sure, dùng default sensible — sau vẫn /vg:project --update được.
 [f] fill template [q] quick defaults [s] skip (phase chỉ có demo/prototype)"

"9.6 Performance baseline — p95 per tier + cache + bundle + CDN
 - API tier default: read p95 ≤ 250ms, write p95 ≤ 500ms
 - RTB tier (low-latency): p99 ≤ 50ms (OpenRTB constraint)
 - Cache strategy: {Redis 5min TTL + tag-invalidate | in-memory LRU | none}
 - Bundle budget FE route: 250KB default (adjust per project)
 - n_plus_one_max query count per endpoint: 3 (triggers warning)
 - CDN: {Cloudflare | Fastly | none}
 [y] adopt defaults [e] custom per-tier"

"9.7 Testing baseline — runner, E2E framework, coverage, mock strategy
 - Unit runner: {vitest | jest | pytest | cargo test}
 - E2E framework: {Playwright | Cypress | native selenium}
 - Coverage threshold: {80%/70%/60% per app?}
 - Mock strategy: {MSW for API | never mock DB | fixtures for ClickHouse}
 - Fixture location: apps/*/e2e/fixtures/
 [y] standard [e] custom]"

"9.8 Model-portable code style — rules that transcend Claude/GPT/Gemini
 - Imports: explicit (no wildcard * imports)
 - Exports: named > default (default export only cho React.lazy)
 - Type annotations: mandatory function signatures (params + return)
 - Comment density: 1 per ~10 SLOC khi có WHY (no WHAT comments)
 - Import ordering: external → internal packages → relative
 - File naming: {kebab-case.ts | camelCase.ts | PascalCase.tsx for components}
 - Error handling idiom: {throw + narrow catches | Result<T,E> | neither}
 Cross-model validation: CrossAI 2d-6 will diff code style across AI outputs.
 [y] standard [e] project-specific]"

"9.9 UI state conventions — list view URL synchronization (v2.8.4 Phase J)
 Áp dụng cho mọi list/table/grid view trong dashboard. Mục tiêu: refresh
 giữ filter/sort/page, share link giữ state, browser back/forward navigate
 đúng các state thay đổi. Đây là dashboard UX baseline modern (Linear,
 Stripe, GitHub, ProductHunt — tất cả default thế).
 - list_view_state_in_url: {true (default) | false (local-only state, hiếm)}
 - url_param_naming: {kebab (status, sort-by, page-size) | camel (status, sortBy, pageSize)}
 - array_format: {csv (?tags=a,b,c) | repeat (?tag=a&tag=b)}
 - debounce_search_ms: {300 default | adjust per UX}
 - default_page_size: {20 | adjust}
 Override per-goal: TEST-GOALS interactive_controls.url_sync: false
 với url_sync_waive_reason (logged as soft debt).
 verify-url-state-sync.py validator runs at /vg:review phase 2.7.
 [y] standard (kebab + csv + 300ms + 20) [e] custom [s] skip nếu project no list views]"
```

**Append to draft.foundation_md_content:**
```python
foundation_section_9 = f'''

---

## 9. Architecture Lock

> Locked {iso_timestamp} via `/vg:project` round 7.
> Section 9 is authoritative — every blueprint planner prompt injects this as <architecture_context>.
> Changes here require `/vg:project --update` + re-running affected phases' scope (CONTEXT drift detection).

### 9.1 Tech stack matrix
{tech_stack_block}

### 9.2 Module boundary
{module_boundary_block}

### 9.3 Folder convention
{folder_convention_block}

### 9.4 Cross-cutting concerns
{cross_cutting_block}

### 9.5 Security baseline
{security_baseline_block}

### 9.6 Performance baseline
{perf_baseline_block}

### 9.7 Testing baseline
{testing_baseline_block}

### 9.8 Model-portable code style
{code_style_block}

### 9.9 UI state conventions (v2.8.4 Phase J)
{ui_state_conventions_block}
'''
draft["foundation_md_content"] += foundation_section_9
```

The `ui_state_conventions_block` MUST contain the locked values:
```yaml
list_view_state_in_url: true              # MANDATORY default — override per-goal only
url_param_naming: kebab                   # status, sort-by, page-size
array_format: csv                         # ?tags=a,b,c
debounce_search_ms: 300
default_page_size: 20
```
These flow into vg.config.md `ui_state_conventions` block + executor R7
+ verify-url-state-sync.py severity matrix.

**Migration:** For projects running `/vg:project --migrate` (extracting FOUNDATION from legacy PROJECT.md), auto-scan codebase to pre-fill §9 where possible (tech_stack from package.json, folder convention from existing dirs, testing baseline from existing test scripts). Mark any unresolved fields with `<NEED_USER_INPUT>` — user must fill before section 9 locks.

### Round 8: Security Testing Strategy (v2.5 Phase D)

**Purpose:** After FOUNDATION §9.5 locks security baseline (implementation rules), Round 8 locks security testing strategy — who tests, how often, what framework. This is a separate artifact `.vg/SECURITY-TEST-PLAN.md` that drives DAST severity gate (Phase B.5/B.6) and pentest checklist gen (Phase I).

4 questions, each with config consequences:

```
"10.1 Risk profile classification
 Determines DAST severity gate + pen-test frequency:

 [c] critical — payment/PII/healthcare/auth-SaaS-multi-tenant
     → High DAST finding = BLOCK, pen-test annual external, SOC2-equivalent
 [m] moderate — internal tool with external users
     → High = WARN, pen-test quarterly internal, compliance as needed
 [l] low — read-only dashboard, marketing site, blog
     → all DAST advisory, no pen-test required

 Select:"

"10.2 DAST tool choice (dynamic scan at /vg:test step 5h)
 [z] OWASP ZAP — docker-based, full HTTP active scan (recommended web)
 [n] Nuclei — binary-based, CVE templates (lightweight, fast)
 [c] Custom — describe tool
 [x] None — read-only project, no HTTP endpoints

 Select:"

"10.3 Pen-test strategy (manual tier, cannot automate)
 [e] external-vendor-annual — budget-heavy, highest quality
 [i] internal-team-quarterly — in-house pen-test rotation
 [b] bug-bounty-continuous — HackerOne/Bugcrowd public/private
 [n] none — low-risk project OR pre-launch

 Select:"

"10.4 Compliance framework mapping
 Drives audit artifact requirements + control coverage check:

 [s] SOC2 Type II
 [i] ISO 27001
 [p1] PCI-DSS Level 1 (millions of tx/year)
 [p4] PCI-DSS Level 4 (small merchant)
 [h] HIPAA (healthcare/PHI)
 [g] GDPR only (EU user data)
 [n] none

 Select (can pick multiple, comma-separated):"
```

**Write SECURITY-TEST-PLAN.md.staged:**
```bash
# Fill template from template file
cp .claude/commands/vg/_shared/templates/SECURITY-TEST-PLAN-template.md "${STP_FILE}.staged"

# Substitute answers (sed or Python script reading DRAFT_FILE)
${PYTHON_BIN} - <<'PY'
import json, os, re
from pathlib import Path
from datetime import datetime, timezone

draft = json.loads(Path(os.environ["DRAFT_FILE"]).read_text(encoding="utf-8"))
stp = Path(os.environ["STP_FILE"] + ".staged")
text = stp.read_text(encoding="utf-8")

# Placeholders: {PROJECT_NAME}, {ISO_TIMESTAMP}, {FOUNDATION_PATH},
# {CRITICAL|MODERATE|LOW}, {ZAP|Nuclei|Custom|None}, etc.
text = text.replace("{PROJECT_NAME}", draft["project_name"])
text = text.replace("{ISO_TIMESTAMP}", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
text = text.replace("{FOUNDATION_PATH}", os.environ["FOUNDATION_FILE"])
# ... answers from round 8
text = text.replace("{CRITICAL|MODERATE|LOW}", draft["security"]["risk_profile"])
# ...
stp.write_text(text, encoding="utf-8")
print(f"✓ SECURITY-TEST-PLAN.md.staged written")
PY
```

**Side-effect on `.claude/vg.config.md`:** Round 8 answers also update config:
- `project.risk_profile: {critical|moderate|low}` (drives DAST severity)
- `security_testing.dast_tool: {ZAP|Nuclei|Custom|None}`
- `security_testing.payload_profile: owasp-top10-2021` (default)
- `security_testing.dast_cascade: [zap,nuclei,grep-only]` (if dast_tool empty → cascade auto-detect)

These get written via `vg_generate_config.py` in Round 9 (was Round 7) atomic step.

### Round 9: Atomic write + commit

Write all 4 files trong 1 transaction.

**v1.13.0 (2026-04-18) — template-based config generation.**
The old inline placeholder heredoc is gone. Config rendering is delegated to
`.claude/scripts/vg_generate_config.py`, which reads the full-schema template
at `.claude/templates/vg/vg.config.template.md` (~700 lines, 100% coverage of
every field workflow commands read) and substitutes only foundation-derived
fields. Previously the heredoc covered ~25% of schema so 75% of config was
best-guess by AI — caused missing fields like `db_name`, `i18n`,
`ports.database`, `rationalization_guard.model`, `surfaces.web` etc. Audit
history lives in `.vg/CONFIG-AUDIT.md`.

```bash
# 1. Write PROJECT.md.staged + FOUNDATION.md.staged from discussion (small, direct)
${PYTHON_BIN} - <<'PY'
import json, os
from pathlib import Path

draft = json.loads(Path(os.environ["DRAFT_FILE"]).read_text(encoding="utf-8"))

# PROJECT.md ← identity + milestones
project_md = Path(os.environ["PROJECT_FILE"] + ".staged")
project_md.write_text(draft["project_md_content"], encoding="utf-8")

# FOUNDATION.md ← 8 dimensions + F-XX decisions
foundation_md = Path(os.environ["FOUNDATION_FILE"] + ".staged")
foundation_md.write_text(draft["foundation_md_content"], encoding="utf-8")

# Export foundation subset as JSON for config generator (next step)
foundation_json = Path(os.environ["PLANNING_DIR"]) / ".foundation-for-config.json"
foundation_json.write_text(json.dumps(draft["foundation_for_config"], indent=2), encoding="utf-8")
print(f"✓ PROJECT.md.staged + FOUNDATION.md.staged + foundation-for-config.json written")
PY

# 2. Render vg.config.md.staged via generator (the v1.13.0 swap-in)
${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/vg_generate_config.py" \
  --foundation "${PLANNING_DIR}/.foundation-for-config.json" \
  --template   "${REPO_ROOT}/.claude/templates/vg/vg.config.template.md" \
  --output     "${CONFIG_FILE}.staged"

if [ $? -ne 0 ] || [ ! -s "${CONFIG_FILE}.staged" ]; then
  echo "⛔ vg_generate_config.py failed — cannot promote staged artifacts."
  echo "   Run manually to debug:"
  echo "     ${PYTHON_BIN} .claude/scripts/vg_generate_config.py \\"
  echo "       --foundation ${PLANNING_DIR}/.foundation-for-config.json \\"
  echo "       --template   .claude/templates/vg/vg.config.template.md \\"
  echo "       --output     /tmp/config.test.md --strict"
  exit 1
fi

# 3. Cleanup temp JSON (keeps repo tidy — foundation lives in FOUNDATION.md now)
rm -f "${PLANNING_DIR}/.foundation-for-config.json"

# Write-strict gate (v1.9.0 T5): FOUNDATION.md MUST use F-XX, never bare D-XX
# (D-XX is reserved for phase CONTEXT.md as P{phase}.D-XX).
# shellcheck disable=SC1091
source .claude/commands/vg/_shared/lib/namespace-validator.sh
if ! validate_d_xx_namespace "${FOUNDATION_FILE}.staged" "foundation"; then
  echo ""
  echo "⛔ Foundation gate chặn: FOUNDATION.md.staged chứa bare D-XX — phải dùng F-XX."
  echo "   Sửa staging file xong chạy lại /vg:project (resume from draft)."
  exit 1
fi

# v2.5 Phase D: also promote SECURITY-TEST-PLAN.md if Round 8 wrote it
STP_FILE="${PLANNING_DIR:-.vg}/SECURITY-TEST-PLAN.md"

# Atomic promote (mv all-or-nothing — now 4 files)
mv "${PROJECT_FILE}.staged"     "$PROJECT_FILE"
mv "${FOUNDATION_FILE}.staged" "$FOUNDATION_FILE"
mv "${CONFIG_FILE}.staged"     "$CONFIG_FILE"
[ -f "${STP_FILE}.staged" ] && mv "${STP_FILE}.staged" "$STP_FILE"

# Remove draft
rm -f "$DRAFT_FILE"

# Commit
git add "$PROJECT_FILE" "$FOUNDATION_FILE" "$CONFIG_FILE"
[ -f "$STP_FILE" ] && git add "$STP_FILE"
git commit -m "project: foundation locked

Per discussion rounds 1-7. See FOUNDATION.md for F-XX decisions (F = Foundation namespace, stable across milestones; per-phase decisions use P{phase}.D-XX).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

Print summary + next steps:
```
✅ Foundation locked. Artifacts:
  - PROJECT.md (project identity + milestones)
  - FOUNDATION.md (8 dimensions + N decisions)
  - vg.config.md (auto-derived from foundation)

Next: /vg:roadmap  (derive phases from project + foundation)
```
</step>

<step name="5_mode_update">
## Step 5 (mode=update): Targeted update preserving existing data

Load existing FOUNDATION.md + PROJECT.md vào context.

AskUserQuestion: "Bạn muốn update phần nào?
- 'general' (mô tả tự nhiên thay đổi) → AI tự detect dimensions liên quan
- Hoặc chọn dimension cụ thể: platform / frontend / backend / data / auth / host / scale / compliance / requirements / milestone-N"

User answers + nói rõ thay đổi.

Model:
1. Identify affected dimensions (parse user input)
2. Load existing decisions F-XX cho dimensions đó (FOUNDATION namespace — không gian tên project-level)
3. Run mini-dialog (1-3 rounds) chỉ trên dimensions affected
4. Generate new F-(N+1) marked "supersedes F-XX"
5. **Preservation gate** (MERGE NOT OVERWRITE):
   - Write `FOUNDATION.md.staged` với chỉ dimensions changed updated
   - Other dimensions: copy verbatim từ existing
   - Run `difflib.SequenceMatcher` ≥ 80% similarity gate trên untouched sections
   - Fail gate → abort, original untouched, staged kept for review
6. If gate pass → atomic promote + commit

Cascade impact:
- If frontend/backend/build dimension changed → **⛔ forced user pause (destructive config change)**:
  Invoke `AskUserQuestion`:
    - header: "Re-derive config?"
    - question: "Tech stack đã thay đổi. Có muốn re-derive vg.config.md không? Nếu Yes, tôi sẽ chạy Round 6 để cập nhật model selection / port / crossai CLI cho fields vừa đổi. Nếu No, vg.config.md giữ nguyên (có thể drift sau này)."
    - options: ["Yes — re-derive affected fields", "No — keep current vg.config.md"]
  Không auto-advance trên silence. Chỉ chạy Round 6 khi user chọn Yes.
- Commit message: `project(update): <dimension(s)> changed — F-XX supersedes F-YY`
</step>

<step name="6_mode_milestone">
## Step 6 (mode=milestone): Append new milestone

Load existing PROJECT.md. Detect highest milestone number (search for `## Milestone X` headings).

AskUserQuestion: "Mô tả milestone mới (1-2 câu mục tiêu):"

User responds. Required field — không skip.

Model:
1. Parse description for **drift signals**:
   - Keywords: mobile/iOS/Android/native/desktop/Electron/serverless/lambda/embedded
   - If any match AND foundation.platform != matched type → **⛔ forced user pause (foundation drift risk)**:
     ```
     ⚠ Milestone description hint shift platform: 'mobile app' nhưng foundation = 'web-saas'.
        Đây có thể là foundation drift — workflow downstream sẽ nhầm platform target.
        Recommend: /vg:project --update foundation TRƯỚC khi tiếp tục.
     ```
     Invoke `AskUserQuestion`:
       - header: "Platform drift detected"
       - question: "Foundation hiện tại là 'web-saas' nhưng milestone mô tả nhắc đến 'mobile'. Bạn muốn làm gì?"
       - options:
         - "Stop — chạy /vg:project --update foundation trước (recommended)"
         - "Continue — milestone vẫn thuộc web-saas, từ 'mobile' chỉ là reference"
     Không auto-proceed. Chỉ append milestone khi user explicit chọn Continue.
2. If user chọn Continue → append `## Milestone {N+1}` section to PROJECT.md
3. FOUNDATION.md untouched (foundation = stable across milestones)
4. vg.config.md untouched
5. Commit: `project(milestone): add milestone {N+1} — {short title}`

Output: pointer to next step "Run /vg:roadmap để add phases cho milestone mới"
</step>

<step name="7_mode_rewrite">
## Step 7 (mode=rewrite): Destructive reset

Double confirm via AskUserQuestion:
```
"⛔ REWRITE = destructive. Existing PROJECT.md + FOUNDATION.md + vg.config.md sẽ được:
 - Backup → ${PLANNING_DIR}/.archive/{timestamp}/
 - Replaced với artifacts mới sau full re-run

 Confirm? [y] Yes — proceed / [n] No — abort"
```

If yes → second confirm:
```
"Last chance. Type 'rewrite-confirmed' để proceed."
```

If matched → execute:
```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="${ARCHIVE_DIR}/${TS}"
mkdir -p "$BACKUP_DIR"
[ -f "$PROJECT_FILE" ]    && cp "$PROJECT_FILE"    "$BACKUP_DIR/"
[ -f "$FOUNDATION_FILE" ] && cp "$FOUNDATION_FILE" "$BACKUP_DIR/"
[ -f "$CONFIG_FILE" ]     && cp "$CONFIG_FILE"     "$BACKUP_DIR/"

echo "🗄  Backed up to: ${BACKUP_DIR}"
rm -f "$PROJECT_FILE" "$FOUNDATION_FILE"
# Keep config but mark invalidated
[ -f "$CONFIG_FILE" ] && mv "$CONFIG_FILE" "$BACKUP_DIR/vg.config.md.pre-rewrite"
```

Then `MODE="first_time"` and re-enter step 4 (full 7-round flow).
</step>

<step name="8_mode_migrate">
## Step 8 (mode=migrate): Extract foundation từ existing artifacts

Use case: project có sẵn PROJECT.md + vg.config.md cũ (no FOUNDATION.md). Cần slim PROJECT.md, sinh FOUNDATION.md từ data có sẵn.

```bash
# Confirm intent
echo "Migration: extract FOUNDATION.md từ existing PROJECT.md + scan codebase + vg.config.md"
echo "Backup PROJECT.md cũ → .archive/{ts}/PROJECT.v1.md"
```

Steps:
1. Read existing PROJECT.md, extract sections related to foundation (Tech Stack, Constraints, Architecture)
2. Scan codebase: `package.json`, `tsconfig.json`, framework manifests, `infra/`, `docker-compose.yml`, `.github/workflows/*.yml`
3. Read existing vg.config.md for already-confirmed config
4. Auto-derive 8 foundation dimensions (high confidence — codebase ground truth)
5. Show diff to user:
   ```
   ## Migration preview

   Will create: FOUNDATION.md (extracted)
   | Dimension | Source | Value |
   |-----------|--------|-------|
   | Platform | scan: apps/web/ React | web-saas |
   | Frontend | package.json: vite | React + Vite |
   | Backend | scan: apps/api/ Fastify | Fastify monolith |
   | ...

   PROJECT.md sẽ được slim down — di chuyển foundation fields ra FOUNDATION.md.
   Backup PROJECT.md cũ → ${PLANNING_DIR}/.archive/{ts}/PROJECT.v1.md
   ```
6. **⛔ forced user pause (destructive: rewrites PROJECT.md + creates FOUNDATION.md).**
   Invoke `AskUserQuestion`:
     - header: "Confirm migration"
     - question: "Tôi sẽ backup PROJECT.md hiện tại vào archive, tạo FOUNDATION.md mới, và slim down PROJECT.md (bỏ tech stack/architecture fields sang FOUNDATION). vg.config.md không đổi. Proceed?"
     - options:
       - "Yes — migrate (backup sẽ được giữ ở .archive/)"
       - "No — abort, PROJECT.md giữ nguyên"
   Không auto-proceed trên silence. Chỉ thực hiện migration khi user chọn Yes.
7. Nếu user chọn Yes:
   - Backup PROJECT.md → archive
   - Write FOUNDATION.md (new file)
   - Rewrite PROJECT.md (slim — keep identity/users/requirements/milestones, remove tech stack/architecture)
   - vg.config.md untouched (already exists, foundation matches)
   - Commit: `project(migrate): extract FOUNDATION.md from v1 PROJECT.md + codebase scan`
</step>

<step name="9_mode_init_only">
## Step 9 (mode=init_only): Re-derive vg.config.md from existing FOUNDATION.md

Use case: foundation OK nhưng vg.config.md outdated (vd: thêm crossai CLI, đổi model selection, port shift).

Required: FOUNDATION.md exists. If not → error: "FOUNDATION.md missing. Run /vg:project (no flag) trước."

```bash
if [ ! -f "$FOUNDATION_FILE" ]; then
  echo "⛔ FOUNDATION.md không tồn tại."
  echo "   /vg:project --init-only chỉ chạy được khi đã có foundation."
  echo "   Run /vg:project (first time) hoặc /vg:project --migrate trước."
  exit 1
fi
```

Re-run Round 6 only (config derivation). Show diff vs current vg.config.md.

**⛔ forced user pause (overwrites vg.config.md).**
Invoke `AskUserQuestion`:
  - header: "Apply config changes?"
  - question: "Đã diff xong vg.config.md cũ vs mới. Nếu Apply, tôi sẽ atomic overwrite vg.config.md và commit. Downstream commands sẽ dùng config mới ngay. Proceed?"
  - options:
    - "Apply — overwrite + commit"
    - "Abort — vg.config.md giữ nguyên"
Không auto-advance. Chỉ overwrite khi user chọn Apply.
</step>

<step name="10_complete">
## Step 10: Pipeline-state + next-step pointer

```bash
# Update PIPELINE-STATE.json at root level (not phase-specific)
PIPELINE_STATE="${PLANNING_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} - <<PY 2>/dev/null
import json
from pathlib import Path
import datetime
p = Path("${PIPELINE_STATE}")
s = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
s["project_status"] = "ready"
s["foundation_locked_at"] = datetime.datetime.now().isoformat()
s["last_mode"] = "${MODE}"
p.write_text(json.dumps(s, indent=2), encoding="utf-8")
PY
```

Print next-step pointer based on mode:
- first_time / migrate / rewrite → "Next: /vg:roadmap"
- update / init_only → "Foundation/config updated. Re-check: /vg:progress"
- milestone → "Next: /vg:roadmap để add phases cho milestone"
- view → (no next step)
</step>

</process>

## FOUNDATION.md template

```markdown
# Foundation — {Project Name}

**Locked:** {ISO timestamp}
**Source:** {first-time | --update | --migrate | --rewrite}
**Source description:** {first 200 chars of user description}

## 1. Platform & Topology (8 dimensions)

**Namespace:** All FOUNDATION decisions use `F-XX` (project-level, stable across milestones). Per-phase decisions live in `${PLANNING_DIR}/phases/*/CONTEXT.md` as `P{phase}.D-XX`.

| # | Dimension | Value | Decision | Confidence |
|---|-----------|-------|----------|------------|
| 1 | Platform type | web-saas / mobile-native / mobile-cross / desktop / cli / hybrid | F-01 | derived/confirmed |
| 2 | Frontend runtime | browser / iOS / Android / Electron / none | F-02 | ... |
| 3 | Frontend framework | React+Vite / Next.js / Vue+Vite / Svelte / Flutter / RN / native-iOS / native-Android | F-03 | ... |
| 4 | Backend topology | none / monolith / microservices / serverless / edge / BaaS | F-04 | ... |
| 5 | Data layer | none / Postgres / MySQL / SQLite / MongoDB / Redis / blob / hybrid | F-05 | ... |
| 6 | Auth model | none / own / OAuth / SSO / passwordless / 3rd-party (Auth0/Clerk) | F-06 | ... |
| 7 | Hosting | VPS / AWS / GCP / Vercel / Netlify / on-prem / app-store / hybrid | F-07 | ... |
| 8 | Distribution | URL / app-store / npm / docker-hub / physical-device | F-08 | ... |

## 2. Tech Stack (concrete choices, derived from above)

- Frontend: {framework + key libs} (F-XX)
- Backend: {framework + key libs} (F-XX)
- Database: {engine + version} (F-XX)
- Build/monorepo: {pnpm+turborepo / npm / cargo / go-mod / ...} (F-XX)
- Test: {vitest / jest / pytest / playwright / maestro / ...} (F-XX)
- Deploy: {SSH+PM2 / git-push / docker / Ansible / ...} (F-XX)

## 3. Constraints

- **Scale:** ~{N users, X QPS}
- **Latency budget:** {p50/p99 targets}
- **Compliance:** {none / GDPR / HIPAA / SOC2 / multiple}
- **Team size:** {solo / 2-5 / 6-20 / 20+}
- **Budget tier:** {hobbyist / bootstrapped / funded / enterprise}

## 4. Decisions

### F-01: Platform = {value}
**Reasoning:** {derivation/discussion summary}
**Reverse cost:** HIGH/MEDIUM/LOW — {what breaks if reversed}
**Confirmed:** {date} by user
**Source:** {description / Round 4 confirm / scan / migration}

(F-02 ... F-N — same structure)

**Namespace rule:** These IDs are `F-XX` (Foundation-scope). Do NOT reuse `D-XX` — that's reserved for per-phase CONTEXT.md as `P{phase}.D-XX`.

## 5. Open Questions

{none if all locked, else list of Q-XX with proposed defaults}

## 6. Drift Check

**Last check:** {date}  
**Status:** ✅ no drift / ⚠ drift detected (see below)  
**Drift entries:** {none, or phase {X} introduced keyword 'mobile' — review platform decision}
```

## vg.config.md derivation rules (Round 6 logic)

**v1.13.0+ (2026-04-18):** Logic lives in `.claude/scripts/vg_generate_config.py`.
This markdown table is reference-only — the authoritative derivation tables
(`FRAMEWORK_PORT`, `BACKEND_PORT`, `BACKEND_HEALTH`, `DATA_PORT`,
`HOSTING_DEPLOY_PROFILE`, `TEST_RUNNER_BY_STACK`) are constants at the top
of `vg_generate_config.py`. Update there, not here.

The generator also emits dynamic blocks: `crossai_clis` / `models` scale with
`team_size`; `services` + `credentials` + `apps` + `infra_deps.services`
derive from `data` / `auth.roles` / `monorepo.apps` / etc. Template:
`.claude/templates/vg/vg.config.template.md` (~700 lines, full schema).

Reference table (indicative — check script for current values):

| Foundation field | → vg.config.md fields |
|------------------|----------------------|
| `frontend.framework: vite` | `worktree_ports.base.web: 5173`, `dev_command: {pm} dev` |
| `frontend.framework: next` | `worktree_ports.base.web: 3000` |
| `backend.framework: fastify` | `worktree_ports.base.api: 3001`, `health: /health` |
| `backend.framework: express` | `worktree_ports.base.api: 3000` |
| `hosting: vps` | `deploy_profile: pm2`, `run_prefix: ssh {{ssh_alias}}` |
| `hosting: vercel` | `deploy_profile: git_push` |
| `data.primary: postgres` | `ports.database: 5432`, `services.local.postgres check` |
| `data.primary: mongodb` | `ports.database: 27017`, `services.local.mongodb check` |
| `monorepo: turborepo` | `build_gates.typecheck_cmd: pnpm turbo typecheck` |
| `team_size: solo` | `models.executor: sonnet`, `models.planner: opus` (cost-aware) |
| `team_size: 6-20+` | `models.executor: opus`, `crossai_clis: [codex, gemini]` (quality-priority) |

User only asked về fields marked `<ASK>` (typically: ssh_alias, deploy.path, domain, secrets). Other fields auto-fill silent.

## Resumable draft format

`${PLANNING_DIR}/.project-draft.json`:
```json
{
  "started_at": "2026-04-17T...",
  "current_round": 4,
  "captured": {
    "description": "<user free-form>",
    "template_responses": {...}
  },
  "derived": {
    "foundation_v1": {
      "platform": "web-saas",
      "frontend_framework": "vite",
      ...
    },
    "ambiguities": [
      {"dim": "auth", "options": ["own", "oauth"], "default": "own"}
    ]
  },
  "decisions": [
    {"id": "F-01", "dim": "platform", "value": "web-saas", "confirmed": true, "round": 4}
  ],
  "status": "in_progress"
}
```

Atomic write after every round (write to `.project-draft.json.tmp` → rename).

## Telemetry

Each `/vg:project` invocation logs to telemetry:
```jsonl
{"ts": "...", "cmd": "vg:project", "mode": "first_time|update|...", "rounds_completed": N, "foundation_changed": true|false, "config_changed": true|false}
```

## Success criteria

- First-time run produces 3 atomic artifacts: PROJECT.md + FOUNDATION.md + vg.config.md
- Re-run with no flag → mode menu (View default)
- `--update`, `--milestone`, `--rewrite`, `--migrate`, `--init-only`, `--view` all routable
- Draft checkpointed every round, resumable on interrupt
- High-cost confirm gate (Round 4) NEVER skipped
- Existing decisions F-XX preserved across `--update` (MERGE NOT OVERWRITE)
- **Namespace enforcement:** FOUNDATION.md uses `F-XX`; phase CONTEXT.md uses `P{phase}.D-XX`. Legacy bare `D-XX` accepted until v1.10.0, then rejected. Migration tool: `.claude/scripts/migrate-d-xx-namespace.py`
- `--rewrite` always backs up to `.archive/{ts}/`
- vg.config.md auto-derived 80-90%, only `<ASK>` fields prompt user
- Foundation drift detection in roadmap/add-phase/scope (separate commands)
