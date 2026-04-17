---
user-invocable: true
description: "Migrate .planning/ → .vg/ (VG canonical path). Idempotent — re-run scans + updates. Skips GSD-owned files."
---

<rules>
1. **Idempotent** — safe to re-run. Compares hashes, only updates changed files.
2. **Comprehensive** — walks ALL files in .planning/. Doesn't silently skip unknowns.
3. **GSD-aware** — auto-classifies and SKIPS GSD-owned files (debug/, quick/, research/, codebase/, *.gsd, gsd-* paths).
4. **User-edit safe** — if target file in .vg/ has been user-edited since last migration, creates `.user-edit.<ts>` backup before overwriting.
5. **Default keep-original** — `.planning/` preserved by default. Use `--no-keep` to delete after successful migration.
6. **Dry-run first** — always preview before applying when in doubt.
</rules>

<objective>
Migrate VG-owned artifacts từ legacy `.planning/` → canonical `.vg/`. GSD continues using `.planning/`. After migration, all VG commands read/write `.vg/` (per `paths.planning_dir` config).

Modes:
- `--dry-run` — preview classification + actions, no files written
- `--no-keep` — delete `.planning/` after successful migration (default: keep)
- `--source=<path>` — override source (default `.planning`)
- `--target=<path>` — override target (default `.vg`)

Idempotent — running multiple times is SAFE and EXPECTED:
- New files in source → copied to target
- Changed files in source → updated in target (with backup if user edited)
- Already-synced files → no-op
- GSD files → skipped consistently
</objective>

<process>

**Source:**
```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/planning-migrator.sh"
```

<step name="0_parse">
Parse flags from `$ARGUMENTS`:
```bash
ARGS=""
for arg in $ARGUMENTS; do
  case "$arg" in
    --dry-run|--no-keep|--source=*|--target=*) ARGS="$ARGS $arg" ;;
  esac
done
```
</step>

<step name="1_run">
```bash
planning_migrator_run $ARGS
```

Output shows per-file classification + final summary table.
</step>

<step name="2_post_migration_config">
After successful migration, update vg.config.md to point at `.vg`:

```bash
if [ ! -f ".claude/vg.config.md" ]; then
  echo "⚠ No vg.config.md — skipping config update"
  exit 0
fi

if grep -qE "^\s*planning_dir:\s*\".vg\"" .claude/vg.config.md; then
  echo "✓ Config already points at .vg"
else
  ${PYTHON_BIN:-python3} -c "
import re
p = '.claude/vg.config.md'
txt = open(p, encoding='utf-8').read()
# Update or insert paths.planning_dir
if re.search(r'^paths:\s*\n', txt, re.M):
    if re.search(r'planning_dir:', txt):
        txt = re.sub(r'(planning_dir:)\s*\"[^\"]*\"', r'\1 \".vg\"', txt)
    else:
        txt = re.sub(r'(^paths:\s*\n)', r'\\1  planning_dir: \".vg\"\\n', txt, flags=re.M)
else:
    txt += '\\n# v1.12.0 — paths.planning_dir set via /vg:migrate-planning-vg\\npaths:\\n  planning_dir: \".vg\"\\n'
open(p, 'w', encoding='utf-8').write(txt)
print('✓ vg.config.md updated: paths.planning_dir = .vg')
"
fi
```
</step>

<step name="3_summary">
Display next-steps:
```
Migration complete. .vg/ is now canonical for VG workflow.

Next:
- All VG commands now read .vg/ (auto-detected via config)
- .planning/ preserved (used by GSD if installed)
- Re-run /vg:migrate-planning-vg anytime to sync new .planning/ → .vg/
- After confirming .vg/ is correct, optionally delete .planning/:
    /vg:migrate-planning-vg --no-keep
```
</step>

</process>

<success_criteria>
- All non-GSD files in .planning/ present in .vg/
- GSD files (*.gsd, debug/, quick/, research/, codebase/) skipped
- Hash equality between corresponding source/target files
- Re-run produces 0 NEW + 0 UPDATED (idempotent)
- vg.config.md `paths.planning_dir: ".vg"` set
- User edits in .vg/ preserved via .user-edit.<ts> backup
</success_criteria>
