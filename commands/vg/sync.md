---
name: vg:sync
description: Sync VGFlow global-only workflow for Claude Code and Codex
argument-hint: "[--check] [--verify] [--no-global] [--global-codex] [--no-source]"
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
Refresh the canonical VGFlow workflow in global-only mode.

Single source of truth:
1. VGFlow source: `~/.vgflow` (or the developer clone that owns `sync.sh`).
2. Claude Code hooks: `~/.claude/settings.json`, with commands pointing at `$HOME/.vgflow/scripts/hooks`.
3. Codex skills/agents: `~/.codex/skills` and `~/.codex/agents`.
4. Codex hooks: `~/.codex/hooks.json`, with `codex_hooks = true` in `~/.codex/config.toml`.
5. Current project: cleanup target only. Project-local VG-owned `.claude/` and `.codex/` workflow surfaces are pruned, then `.vg/.install-target=global` is written.

`/vg:sync` MUST NOT copy `commands/vg`, `skills`, `scripts`, `schemas`,
`templates/vg`, `codex-skills`, or Codex agents into the current project.

Deprecated flags are accepted only for compatibility:
- `--no-global` is a no-op; global deploy is mandatory.
- `--global-codex` is a no-op; global Codex deploy is mandatory.
- `--no-source` is a no-op; this repository/global install is the source.
</objective>

<process>

<step name="0_detect">

Resolve `sync.sh` from the global/source VGFlow install:

```bash
SYNC_SH=""
for candidate in \
  "${VGFLOW_REPO:-}/sync.sh" \
  "${VG_HOME:-}/sync.sh" \
  "${HOME}/.vgflow/sync.sh" \
  "../vgflow-repo/sync.sh" \
  "../../vgflow-repo/sync.sh" \
  "vgflow/sync.sh"; do
  if [ -f "$candidate" ]; then
    SYNC_SH="$candidate"
    break
  fi
done

if [ -z "$SYNC_SH" ]; then
  echo "VGFlow sync.sh not found."
  echo "Set VGFLOW_REPO=/path/to/vgflow or install global VGFlow at ~/.vgflow."
  exit 1
fi

export DEV_ROOT="$(pwd)"
echo "Using sync script: $SYNC_SH"
```
</step>

<step name="1_run">

Parse args:
- `--check`: dry-run, no writes; exits 1 if global hooks/skills are missing or project-local VG surfaces remain
- `--verify`: run functional Codex mirror equivalence and exit
- `--no-global`: deprecated no-op
- `--global-codex`: deprecated no-op
- `--no-source`: deprecated no-op

```bash
bash "$SYNC_SH" ${ARGUMENTS}
```

`sync.sh` regenerates `codex-skills` from canonical `commands/vg` and support
skills before installing global surfaces. Then it delegates to:

```bash
VG_HOME="<sync-source-root>" bash "<sync-source-root>/bin/vg-cli-dispatcher.sh" install --global
```

The dispatcher is responsible for:
- refreshing global Codex skills/agents
- installing Codex hooks at `~/.codex/hooks.json`
- installing Claude Code hooks at `~/.claude/settings.json`
- pruning project-local VG-owned `.claude/` and `.codex/` files with backup
- writing `.vg/.install-target=global`
</step>

<step name="2_report">

Surface:
- source root used for sync
- target project used for cleanup/marker
- stale project-local VG surfaces, if any
- global Claude/Codex hook locations
- functional Codex mirror result, when `--verify` is used

If `--check` reports drift, suggest:

```bash
/vg:sync
```

or direct source invocation:

```bash
DEV_ROOT=/path/to/project bash ~/.vgflow/sync.sh
```
</step>

</process>

<success_criteria>
- `~/.vgflow` exists and is the active VGFlow source.
- `~/.claude/settings.json` contains VG hook entries that point at `$HOME/.vgflow/scripts/hooks`.
- `~/.codex/skills` contains generated VGFlow Codex skills.
- `~/.codex/agents` contains VGFlow Codex agent templates.
- `~/.codex/hooks.json` contains VGFlow hook entries and `~/.codex/config.toml` has `codex_hooks = true`.
- Project-local VG-owned `.claude/commands/vg`, `.claude/scripts`, `.claude/skills/vg-*`, `.claude/agents/vg-*`, `.codex/skills/vg-*`, and `.codex/agents/vgflow-*` are absent after sync.
- Project `.vg/.install-target` is `global` when sync is run from a git project or a project with an existing marker.
- `/vg:sync --verify` reports zero functional drift between command sources and Codex skill mirrors after adapter stripping.
</success_criteria>
