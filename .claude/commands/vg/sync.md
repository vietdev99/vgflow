---
name: vg:sync
description: Sync VG workflow from canonical vgflow-repo into Claude/Codex installations
argument-hint: "[--check] [--verify] [--no-global] [--no-source]"
allowed-tools:
  - Bash
  - Read
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "sync.started"
    - event_type: "sync.completed"
---

<objective>
Deploy the canonical VGFlow workflow from `vgflow-repo` into the current project
and Codex global skill/agent directories.

Canonical source of truth:
1. `commands/vg/` -> `.claude/commands/vg/`
2. `skills/` -> `.claude/skills/`
3. `scripts/` + `schemas/` + `templates/vg/` -> `.claude/`
4. `codex-skills/` -> `.codex/skills/` and `~/.codex/skills/`
5. `templates/codex-agents/` -> `.codex/agents/` and `~/.codex/agents/`
6. `vg-hooks-install.py` repairs project-local Claude hooks in `.claude/settings.local.json`

`--no-source` is accepted only for backward compatibility. It is a no-op
because this repository is now the source of truth; RTB/.claude source probing
is intentionally removed.
</objective>

<process>

<step name="0_detect">

Resolve `vgflow-repo/sync.sh`:

```bash
SYNC_SH=""
for candidate in \
  "${VGFLOW_REPO:-}/sync.sh" \
  "../vgflow-repo/sync.sh" \
  "../../vgflow-repo/sync.sh" \
  "${HOME}/Workspace/Messi/Code/vgflow-repo/sync.sh" \
  "vgflow/sync.sh"; do
  if [ -f "$candidate" ]; then
    SYNC_SH="$candidate"
    break
  fi
done

if [ -z "$SYNC_SH" ]; then
  echo "vgflow-repo sync.sh not found."
  echo "Set VGFLOW_REPO=/path/to/vgflow-repo or clone it beside this project."
  exit 1
fi

export DEV_ROOT="$(pwd)"
echo "Using sync script: $SYNC_SH"
```
</step>

<step name="1_run">

Parse args:
- `--check`: dry-run, no writes, exits 1 if drift exists
- `--verify`: short-circuit and run functional Codex mirror equivalence
- `--no-global`: skip `~/.codex` deploy
- `--no-source`: deprecated no-op, passed through for compatibility

```bash
bash "$SYNC_SH" $ARGUMENTS
```

`--verify` delegates to `scripts/verify-codex-mirror-equivalence.py` inside
`vgflow-repo`. Installed projects receive the same script at
`.claude/scripts/verify-codex-mirror-equivalence.py`.

The script regenerates `codex-skills` from `commands/vg` and support skills
before deployment unless `--check` is set.

It also installs/repairs Claude Code enforcement hooks after copying scripts:
- `UserPromptSubmit`: pre-seeds `vg-orchestrator run-start`.
- `Stop`: verifies `runtime_contract` evidence before the agent can claim done.
- `PostToolUse` edit warning: warns when VG command/skill files were edited in-session.
- `PostToolUse` Bash step tracker: writes step activity telemetry into `.vg/events.db`.
</step>

<step name="2_report">

Surface:
- files changed or would change
- target project path
- whether global Codex deploy was skipped
- functional Codex mirror check result

If `--check` reports drift, suggest:

```bash
/vg:sync
```

or:

```bash
/vg:sync --no-global
```
</step>

</process>

<success_criteria>
- Project `.claude/commands/vg` matches `vgflow-repo/commands/vg`.
- Project `.claude/skills`, `.claude/scripts`, `.claude/schemas`, and `.claude/templates/vg` match repo source.
- Project `.codex/skills` matches `vgflow-repo/codex-skills`.
- Project `.codex/agents` contains VGFlow Codex agent templates.
- If not `--no-global`, `~/.codex/skills` and `~/.codex/agents` are refreshed.
- Project `.claude/settings.local.json` contains VG enforcement hooks for `UserPromptSubmit`, `Stop`, and both `PostToolUse` paths.
- `/vg:sync --verify` reports zero functional drift between command sources and Codex skill mirrors after adapter stripping.
</success_criteria>
