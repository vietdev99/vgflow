# Codex Spawn Contract

Use this contract at every VGFlow source spawn site when the current runtime is
Codex (`VG_RUNTIME=codex`, `$vg-*` invocation, or a generated Codex skill).
Claude keeps the native `Agent(...)` call. Codex does not execute Claude
`Agent(...)` syntax directly; it MUST run a bounded child process through
`codex-spawn.sh` or BLOCK before the step marker.

## Required Mapping

| Source spawn | Codex tier | Sandbox | Output handling |
|---|---|---|---|
| build task executor | executor | workspace-write | one output JSON per task |
| build post-executor | executor | workspace-write | one output JSON assigned to `SUBAGENT_OUTPUT` |
| test goal verifier | executor | workspace-write | one output JSON assigned to `SUBAGENT_OUTPUT` |
| test codegen | executor | workspace-write | one output JSON assigned to `SUBAGENT_OUTPUT` |
| accept UAT builder | executor | workspace-write | one output JSON assigned to `SUBAGENT_OUTPUT` |
| accept cleanup | executor | workspace-write | one output JSON assigned to `SUBAGENT_OUTPUT` |
| review scanner with MCP/browser/device work | inline main Codex orchestrator | n/a | same scan artifacts/events |
| read-only classifier over captured snapshots | scanner | read-only | compact JSON/markdown verdict |

## Mandatory Shell Shape

Render the exact delegation prompt to a file first. Then call:

```bash
CODEX_SPAWN="${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/codex-spawn.sh"
[ -x "$CODEX_SPAWN" ] || CODEX_SPAWN="${REPO_ROOT:-.}/commands/vg/_shared/lib/codex-spawn.sh"
[ -x "$CODEX_SPAWN" ] || {
  echo "⛔ codex-spawn.sh missing — cannot emulate required Agent spawn on Codex." >&2
  exit 1
}
command -v codex >/dev/null 2>&1 || {
  echo "⛔ codex CLI not found or not logged in — required for this Codex spawn." >&2
  exit 1
}

mkdir -p "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/codex-spawns"
"$CODEX_SPAWN" \
  --tier executor \
  --sandbox workspace-write \
  --timeout 900 \
  --cd "${REPO_ROOT:-.}" \
  --spawn-role "$SPAWN_ROLE" \
  --spawn-id "$SPAWN_ID" \
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE"
SUBAGENT_OUTPUT="$(cat "$OUT_FILE")"
```

The main orchestrator MUST run the same post-spawn validation that the Claude
path runs. A non-zero `codex-spawn.sh` exit, empty output file, malformed JSON,
or missing expected artifact is a hard block. Do not replace the spawn with
inline execution.

`codex-spawn.sh` writes evidence under
`.vg/runs/<run_id>/codex-spawns/` and appends
`.vg/runs/<run_id>/.codex-spawn-manifest.jsonl`. Codex PreToolUse Bash
hooks check that manifest before allowing heavy-step markers or
`wave-complete`.

## Parallel Build Waves

For build wave `parallel[]`, Codex may parallelize independent tasks with
background `codex-spawn.sh` processes and `wait`. It must still honor
`sequential_groups[][]` exactly. Each task gets:

- one prompt file rendered from `waves-delegation.md`
- one output file under `${VG_TMP}/codex-spawns/wave-${W}/task-${N}.json`
- one stdout log, stderr log, and exit file from `codex-spawn.sh`
- the same narration before/after as the Claude path
- `--spawn-role vg-build-task-executor --task-id task-${N} --wave ${W}`

After all task outputs exist, the main orchestrator continues with the normal
post-spawn aggregation and `wave-complete` gates.
