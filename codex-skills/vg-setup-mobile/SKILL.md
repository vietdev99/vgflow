---
name: "vg-setup-mobile"
description: "Install mobile E2E tooling — adb, Maestro, Android SDK, AVD — cross-platform (macOS/Linux/Windows)"
metadata:
  short-description: "Install mobile E2E tooling — adb, Maestro, Android SDK, AVD — cross-platform (macOS/Linux/Windows)"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Markdown progress + step markers | Do not rely on Claude's persistent task tail UI. |
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

Claude Code has a project-local hook substrate; Codex skills do not receive
Claude `UserPromptSubmit`, `Stop`, or `PostToolUse` hooks automatically.
Therefore Codex must execute the lifecycle explicitly through the same
orchestrator that writes `.vg/events.db`:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Treat the command body's explicit `vg-orchestrator run-start` as mandatory; if missing or failing, BLOCK before doing work |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Run the command body's terminal `vg-orchestrator run-complete` before claiming completion; if it returns non-zero, fix evidence and retry |
| `PostToolUse` edit -> `vg-edit-warn.py` | Warns that command/skill edits require session reload | After editing VG workflow files on Codex, tell the user the current session may still use cached skill text |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Do not rely on the hook; call explicit `vg-orchestrator mark-step` lines in the skill and preserve marker/telemetry events |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Do NOT blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
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
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.

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

Invoke this skill as `$vg-setup-mobile`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **Idempotent** — re-running is safe. Tools already on PATH are detected and skipped.
2. **No admin required** — installs to `$HOME/mobile-env` (user scope).
3. **OS-aware** — different download URLs for macOS / Linux / Windows msys. iOS simulator unsupported outside macOS; script does NOT attempt it.
4. **No hardcoded device names** — AVD name/API/image all overridable via env (`VG_AVD_NAME`, `VG_AVD_API`, `VG_SDK_IMAGE_TAG`) or CLI args.
5. **Activate only, don't persist** — script emits `export PATH=...` lines for user to paste into shell profile. Never auto-modifies `~/.bashrc` / `~/.zshrc` (respects user autonomy).
6. **Profile-relevant** — intended for projects where `profile ∈ mobile-*`. Safe to run on web projects but wastes disk (~5GB Android SDK).
</rules>

<objective>
One-shot installer for the mobile toolchain VG workflow needs:

| Tool | Purpose | Size |
|------|---------|------|
| adb (platform-tools) | Talk to emulator/device | ~10MB |
| Maestro CLI | Drive Android/iOS UI for `phase2_mobile_discovery` + `5c_mobile_flow` | ~200MB |
| Android SDK cmdline-tools | `sdkmanager`, `avdmanager` | ~150MB |
| Emulator + system-image | Local Android runtime | ~3-5GB |
| AVD | Ready-made emulator device (default: Pixel 7 API 34) | — |

After success, `python maestro-mcp.py check-prereqs` reports `android_flows: true`.
iOS steps still require macOS or a cloud provider — see README "Mobile profiles (V1)" section.
</objective>

<process>

<step name="0_load_config">
Follow `.claude/commands/vg/_shared/config-loader.md` to resolve `$REPO_ROOT`, `$PYTHON_BIN`.

```bash
SCRIPT="${REPO_ROOT}/.claude/scripts/setup-mobile-env.sh"
if [ ! -x "$SCRIPT" ]; then
  # Fallback to vgflow canonical if .claude/ mirror missing (fresh install)
  SCRIPT="${REPO_ROOT}/vgflow/scripts/setup-mobile-env.sh"
fi
if [ ! -f "$SCRIPT" ]; then
  echo "⛔ setup-mobile-env.sh not found. Run install.sh first or update vgflow."
  exit 1
fi
```
</step>

<step name="1_parse_args">
Forward all slash-command args to the shell script:

```bash
# Args from the user — pass-through unchanged.
ARGS="$ARGUMENTS"
```

Common patterns:
- `/vg:setup-mobile` — install everything (default)
- `/vg:setup-mobile --tools=adb,maestro` — partial
- `/vg:setup-mobile --avd=Nexus_6P_API_33 --api=33` — custom device (via env prefix)
- `/vg:setup-mobile --help` — show full help
</step>

<step name="2_probe_current_state">
Before running the installer, show user what's currently missing so they know what to expect:

```bash
echo "=== Current mobile tooling state ==="
for tool in java adb maestro emulator sdkmanager avdmanager; do
  path=$(command -v "$tool" 2>/dev/null || true)
  if [ -n "$path" ]; then
    echo "  ✓ $tool  ($path)"
  else
    echo "  ✗ $tool  (not on PATH)"
  fi
done

# Also consult the VG wrapper's view
if [ -f "${REPO_ROOT}/.claude/scripts/maestro-mcp.py" ]; then
  echo ""
  echo "=== VG wrapper view ==="
  ${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/maestro-mcp.py" --json check-prereqs \
    | ${PYTHON_BIN} -c "import json,sys;d=json.load(sys.stdin);print(f'  host_os: {d[\"host_os\"]}');print(f'  android_flows: {d[\"capabilities\"][\"android_flows\"]}');print(f'  ios_flows: {d[\"capabilities\"][\"ios_flows\"]}')"
fi
echo ""
```
</step>

<step name="3_run_installer">
Invoke the script with user args. The script itself:
- Detects host OS (darwin/linux/windows-msys)
- Checks `java` (bails out with install hint if missing — user must handle manually)
- Downloads adb + Maestro + SDK cmdline-tools to `~/mobile-env/`
- Accepts SDK licenses (`yes | sdkmanager --licenses`)
- Installs `emulator`, `platform-tools`, `platforms;android-N`, `system-images;android-N;google_apis;x86_64`
- Creates AVD `${VG_AVD_NAME}` (default `Pixel_7_API_34`)
- Emits activation hint (`export PATH=...`) at the end

```bash
bash "$SCRIPT" $ARGS
RC=$?
if [ $RC -ne 0 ]; then
  echo ""
  echo "⛔ Setup failed. Re-run with --help for tool-specific subset flags."
  exit $RC
fi
```

**Expected download size**: 150MB (cmdline-tools) → extract → then sdkmanager pulls ~3-5GB system-image. **Budget 5-15 minutes** depending on network.
</step>

<step name="4_verify">
Activate the newly-installed tooling for this shell session and re-probe:

```bash
VG_MOBILE_DIR="${VG_MOBILE_DIR:-$HOME/mobile-env}"
export ANDROID_HOME="$VG_MOBILE_DIR/android-sdk"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/emulator:$VG_MOBILE_DIR/platform-tools:$VG_MOBILE_DIR/maestro/bin:$PATH"

echo ""
echo "=== Post-install verification ==="
adb --version     2>&1 | head -1 || echo "  ⚠ adb not active in this shell"
maestro --version 2>&1 | head -1 || echo "  ⚠ maestro not active"
emulator -list-avds 2>&1 | head -5

echo ""
echo "=== VG wrapper re-check ==="
${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/maestro-mcp.py" --json check-prereqs \
  | ${PYTHON_BIN} -m json.tool
```

Show user the final `android_flows: true` state — that's the green light for `/vg:review` mobile discovery + `/vg:test` Maestro flows.
</step>

<step name="5_next_steps">
Print a short playbook of what to do next:

```
Mobile tooling ready. Next:

  1. Activate PATH persistently (copy the 2 export lines above into ~/.bashrc / ~/.zshrc)
  2. Boot the emulator:
        emulator -avd ${VG_AVD_NAME:-Pixel_7_API_34} &
  3. Confirm it's online:
        adb devices
  4. Install your app (one of):
        npx expo start --android          # Expo RN — installs Expo Go
        adb install path/to/app-debug.apk # pre-built APK
  5. Smoke-test Maestro:
        maestro test path/to/flow.maestro.yaml

For the full VG mobile pipeline, see vgflow/README.md section "Mobile profiles (V1)".
```
</step>

</process>

<success_criteria>
- adb, maestro, emulator, sdkmanager, avdmanager all on PATH after activation
- `maestro-mcp.py check-prereqs` → `android_flows: true`
- AVD `${VG_AVD_NAME}` listed by `emulator -list-avds`
- Installer is idempotent — re-running skips already-present tools
- No `~/.bashrc` / `~/.zshrc` modified by the installer (user does it manually)
- Works on macOS, Linux, Windows msys/Git Bash without code branching in VG workflow files
</success_criteria>
