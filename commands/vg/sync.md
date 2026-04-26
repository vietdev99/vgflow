---
name: vg:sync
description: Sync VG workflow across source → mirror → installations (.claude/ → vgflow/ → ~/.codex/)
argument-hint: "[--check] [--verify] [--no-source] [--no-global]"
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
Keep VG workflow files consistent across 3 locations:
1. **Source**: `.claude/commands/vg/` (edit here trong dev repo)
2. **Mirror**: `vgflow/` (distribute this to other projects)
3. **Installations**:
   - `.codex/skills/vg-*/` (current project Codex)
   - `~/.codex/skills/vg-*/` (global Codex — dùng cho mọi project)

Script delegates to `vgflow/sync.sh`. Runs bidirectional sync: edit ở source → mirror về vgflow → deploy tới installations.
</objective>

<process>

<step name="0_detect">

**v1.11.0 R5 — `vgflow/` folder deprecated. Use external `vgflow-repo` clone:**

```bash
# Resolution priority (highest first):
SYNC_SH=""
for candidate in \
  "${VGFLOW_REPO:-}/sync.sh" \
  "../vgflow-repo/sync.sh" \
  "../../vgflow-repo/sync.sh" \
  "${HOME}/Workspace/Messi/Code/vgflow-repo/sync.sh" \
  "vgflow/sync.sh"  ; do
  if [ -f "$candidate" ]; then
    SYNC_SH="$candidate"
    break
  fi
done

if [ -z "$SYNC_SH" ]; then
  echo "⛔ vgflow-repo sync.sh not found."
  echo "   Setup options:"
  echo "   1. Set env: export VGFLOW_REPO=/path/to/vgflow-repo"
  echo "   2. Clone sibling: git clone https://github.com/vietdev99/vgflow ../vgflow-repo"
  echo "   Then re-run /vg:sync"
  exit 1
fi

echo "✓ Using sync script: $SYNC_SH"
export DEV_ROOT="$(pwd)"
```
</step>

<step name="1_run_sync">
Parse args: `--check` (dry-run), `--verify` (codex mirror equivalence), `--no-source` (skip source→mirror), `--no-global` (skip ~/.codex)

**`--verify` short-circuits the rest of the pipeline.** It hashes the
post-`</codex_skill_adapter>` content of every `.codex/skills/vg-*/SKILL.md`
mirror against the post-frontmatter content of its source
`.claude/commands/vg/<name>.md`. This catches functional drift that the
regular `sync.sh --check` line-level diff hides inside the ~80-line offset
introduced by the codex adapter block (N10 fix from build-vs-blueprint audit).

```bash
if echo " $ARGUMENTS " | grep -q ' --verify '; then
  "${PYTHON_BIN:-python3}" .claude/scripts/verify-codex-mirror-equivalence.py
  exit $?
fi

bash "$SYNC_SH" $ARGUMENTS
```

Output shows:
- Files changed (new/updated)
- Summary count
- Dry-run indication nếu --check
- Per-skill drift table nếu --verify

Exit code:
- 0: nothing to do OR sync applied OR --verify all-equivalent
- 1 (with --check): drift detected, needs sync
- 1 (with --verify): functional drift between source and codex mirror — re-run `/vg:sync` (without flag) to regenerate mirrors
</step>

<step name="2_report">
After apply (not --check), surface:
- Số files synced
- Locations touched
- Nếu có global deploy: remind user Codex sessions hiện tại cần restart để load skills mới

Nếu --check báo drift:
- Suggest: `/vg:sync` (without --check) để apply
- Hoặc `/vg:sync --no-global` nếu không muốn deploy global
</step>

</process>

<success_criteria>
- `.claude/commands/vg/*.md` ↔ `vgflow/commands/vg/*.md` identical
- `.claude/skills/{api-contract,vg-*}/` ↔ `vgflow/skills/` identical
- `.claude/scripts/*.py` ↔ `vgflow/scripts/*.py` identical
- `vgflow/codex-skills/*/SKILL.md` deployed to both `.codex/skills/` và `~/.codex/skills/`
- Report accurate file count delta
- Zero data loss (no silent overwrites khi src missing)
- `/vg:sync --verify` reports zero drift between `.claude/commands/vg/<name>.md` and `.codex/skills/vg-<name>/SKILL.md` (post-adapter SHA256 match)
</success_criteria>
