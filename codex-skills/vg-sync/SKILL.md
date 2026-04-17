---
name: "vg-sync"
description: "Sync VG workflow across source → mirror → installations (.claude/ → vgflow/ → ~/.codex/)"
metadata:
  short-description: "Sync VG workflow across source → mirror → installations (.claude/ → vgflow/ → ~/.codex/)"
---

<codex_skill_adapter>
## Codex ⇆ Claude Code tool mapping

This skill was originally designed for Claude Code. When running in Codex CLI:

| Claude tool | Codex equivalent |
|------|------------------|
| AskUserQuestion | request_user_input (free-form text, or number-prefix choices) |
| Task (agent spawn) | Use `codex exec --model <model>` subprocess with isolated prompt |
| TaskCreate/TaskUpdate | N/A — use inline markdown headers and status narration |
| WebFetch | `curl -sfL` or `gh api` for GitHub URLs |
| Bash/Read/Write/Edit/Glob/Grep | Same — Codex supports these natively |

## Invocation

This skill is invoked by mentioning `$vg-sync`. Treat all user text after `$vg-sync` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


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
```bash
if [ ! -f "vgflow/sync.sh" ]; then
  echo "⛔ vgflow/sync.sh không tồn tại. VG chưa được install vào repo này?"
  echo "   Run: bash path/to/vgflow/install.sh ."
  exit 1
fi
```
</step>

<step name="1_run_sync">
Parse args: `--check` (dry-run), `--no-source` (skip source→mirror), `--no-global` (skip ~/.codex)

```bash
bash vgflow/sync.sh $ARGUMENTS
```

Output shows:
- Files changed (new/updated)
- Summary count
- Dry-run indication nếu --check

Exit code:
- 0: nothing to do OR sync applied
- 1 (with --check): drift detected, needs sync
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
</success_criteria>
