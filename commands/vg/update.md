---
name: vg:update
description: Pull latest VG release from GitHub, 3-way merge with local, park conflicts for /vg:reapply-patches
argument-hint: "[--check] [--accept-breaking] [--repo=vietdev99/vgflow]"
allowed-tools:
  - Bash
  - Read
  - Write
  - AskUserQuestion
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "update.started"
    - event_type: "update.completed"
---

<rules>
1. **Atomic** — VERSION file + ancestor dir rotated only after all merges complete.
2. **Non-destructive on conflict** — conflicted files are parked under `.claude/vgflow-patches/`, never clobber user edits.
3. **All logic in Python** — this markdown wraps `.claude/scripts/vg_update.py`; no version math / SHA / merge logic in bash.
4. **Honor repo override** — `--repo=owner/name` flag flows through to `vg_update.py`.
5. **Honor args literally** — use `${ARGUMENTS}`, never `$*`/`$@` to avoid arg splitting.
</rules>

<objective>
Sync local VG install (`.claude/commands/vg/`, `.claude/skills/`, `.claude/scripts/`, `.claude/templates/`)
to latest GitHub release of `vietdev99/vgflow`. Logic lives in `.claude/scripts/vg_update.py`.
High-level flow:

1. Preflight: verify `git`, `curl`, `python3`, helper script present.
2. `--check` mode → just print version state + exit.
3. Query `GET /repos/{repo}/releases/latest` via helper → compare with `.claude/VGFLOW-VERSION`.
4. Show changelog preview for versions `> installed, <= latest`.
5. Ask user to confirm.
6. Breaking-change gate: major bump requires `--accept-breaking` + shows migration doc.
7. Download tarball + verify SHA256 + extract to `.vgflow-cache/v{ver}/`.
8. Walk extracted tree, 3-way merge each file against `.claude/vgflow-ancestor/v{installed}/`.
9. Clean merges → apply; conflicts → `.claude/vgflow-patches/{rel}.conflict` + manifest entry.
10. Rotate ancestor dir + bump `.claude/VGFLOW-VERSION`.
11. Sync Codex mirrors directly from the updated release assets.
12. Verify/repair Claude + Codex Playwright MCP workers (`playwright1`..`playwright5`).
13. Verify/install Graphify tooling when `graphify.enabled=true`.
14. Report counts + restart reminder.
</objective>

<process>

### Preflight section (extracted v2.73.0 T6)

Read `_shared/update/preflight.md` and follow it exactly.
Includes 2 steps: 0_preflight, 1_check_only_mode.

Step coverage: 0_preflight, 1_check_only_mode.


### Version + changelog (extracted v2.73.0 T7)

Read `_shared/update/version-and-changelog.md` and follow it exactly.
Includes 3 steps: 2_version_compare, 3_changelog_preview, 4_breaking_gate.

Step coverage: 2_version_compare, 3_changelog_preview, 4_breaking_gate.


### Fetch + merge (extracted v2.73.0 T8)

Read `_shared/update/fetch-and-merge.md` and follow it exactly.
Includes 3 steps: 5_fetch_tarball, 6_three_way_merge_per_file, 6b_verify_gate_integrity.

Step coverage: 5_fetch_tarball, 6_three_way_merge_per_file, 6b_verify_gate_integrity.


### Rotate + repair (extracted v2.73.0 T9)

Read `_shared/update/rotate-and-repair.md` and follow it exactly.
Includes 2 steps: 7_rotate_ancestor_and_version, 7b_repair_hooks.

Step coverage: 7_rotate_ancestor_and_version, 7b_repair_hooks.


### Sync + report (extracted v2.73.0 T10 — final)

Read `_shared/update/sync-and-report.md` and follow it exactly.
Includes 4 steps: 8_sync_codex, 8b_repair_playwright_mcp, 8c_ensure_graphify, 9_report.

Step coverage: 8_sync_codex, 8b_repair_playwright_mcp, 8c_ensure_graphify, 9_report.


</process>

<success_criteria>
- `/vg:update --check` prints `current=... latest=... state=...` and exits cleanly.
- Non-check run: shows changelog preview, asks confirmation, either applies or exits on cancel.
- Clean merges applied silently; conflicts parked to `.claude/vgflow-patches/{rel}.conflict` with manifest entry.
- Major-version bump blocked unless `--accept-breaking` is passed AND migration doc displayed.
- `.claude/VGFLOW-VERSION` bumped to `${LATEST}`; old `vgflow-ancestor/v{INSTALLED}` removed; new `vgflow-ancestor/v{LATEST}` populated.
- Claude Code hooks are installed/repaired after update (`UserPromptSubmit`, `Stop`, `PostToolUse` edit warning, `PostToolUse` Bash step tracker).
- Project-local Codex mirrors in `.codex/skills` and `.codex/agents` follow `VG_UPDATE_PROJECT_CODEX`: `auto` means auto-detect prior project install, `1` forces deploy, `0` skips. Global `~/.codex` mirrors follow `VG_UPDATE_GLOBAL_CODEX` with the same auto-detect prior install semantics.
- Functional Codex mirror equivalence is verified after update; drift without merge conflicts fails the update.
- Playwright MCP workers are verified/repaired after update for both Claude and Codex (`playwright1`..`playwright5`) and stale hardcoded lock scripts are replaced.
- Graphify tooling is verified/repaired after update when `graphify.enabled=true`; missing package installs `graphifyy[mcp]`, `.mcp.json` is repaired, and `.graphifyignore` / `.gitignore` are maintained.
- Final report lists updated / new / conflict counts. When `CONFLICTS > 0` OR `gate-conflicts.md` exists, the report emits a runtime-agnostic AI directive (`▶ NEXT_ACTION=/vg:reapply-patches[ --verify-gates]`) instructing the assistant to chain into `/vg:reapply-patches` in the next turn without waiting for a fresh user prompt. Applies to Claude Code and Codex.
- Meta files (VERSION, CHANGELOG.md, README.md, LICENSE, install.sh, sync.sh, vg.config.template.md) never written to `.claude/`.
</success_criteria>
