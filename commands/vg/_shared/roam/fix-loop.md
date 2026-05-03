# roam fix-loop (STEP 7)

<HARD-GATE>
`7_optional_fix_loop` runs ONLY when `--auto-fix` is set; default path is
report-only. Marker is `severity: warn` with `required_unless_flag:
"--auto-fix"` — Stop hook tolerates absence on default path.
NO new subagents introduced (R3.5 decomposition-only); existing auto-fix
agent preserved as-is.
</HARD-GATE>

**Marker:** `7_optional_fix_loop`
**Severity:** `warn` (not `error`) — gate is gated by `--auto-fix` flag.
The runtime contract has `required_unless_flag: "--auto-fix"`, meaning
the marker is only mandatory when `--auto-fix` is **NOT** set (default
report-only path).

If `--auto-fix` flag set, for each top-N bug: spawn fix subagent
(Sonnet/Opus), apply fix → atomic commit → re-roam affected surface only
→ verify resolved. Max 5 fixes per session. Default: report only (per Q1).

**No new subagent introduced in R3.5** — the existing auto-fix loop
subagent is preserved as-is. This ref documents the spawn site with
narrate-spawn calls for UX.

---

## Branch

```bash
vg-orchestrator step-active 7_optional_fix_loop

if [[ ! "$ARGUMENTS" =~ --auto-fix ]]; then
  echo "ℹ Skipping fix loop (default). Pass --auto-fix to enable."
else
  echo "▸ Running auto-fix loop on top 5 bugs..."

  # NARRATION: spawning auto-fix subagent (UX courtesy).
  bash scripts/vg-narrate-spawn.sh "auto-fix-loop" spawning "top-5 bugs from ROAM-BUGS.md" 2>/dev/null || true

  # Implementation: read ROAM-BUGS.md, dispatch fix tasks via Agent tool with
  # the existing auto-fix subagent (Sonnet/Opus). After each fix re-run roam
  # on affected surface only. Max 5 fixes per session.
  #
  # Per-fix loop (commander pseudo-code):
  #   for bug in top_n_bugs(ROAM-BUGS.md, n=5):
  #     spawn auto-fix subagent with bug context
  #     wait for atomic commit
  #     re-run /vg:roam --resume --refresh-spawn for affected surface only
  #     check observe-{S}-{lens}.jsonl for resolution
  #     if not resolved → halt loop, report partial fix
  #
  # See ROAM-RFC-v1.md section 6 for full state machine.

  bash scripts/vg-narrate-spawn.sh "auto-fix-loop" returned "fix loop complete" 2>/dev/null || true
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "7_optional_fix_loop" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/7_optional_fix_loop.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step roam 7_optional_fix_loop 2>/dev/null || true
```

## Why preserved as-is

Per R3.5 plan §4.2: NO new subagents introduced. The R3.5 refactor is
**decomposition-only** — it splits the monolithic `roam.md` into a slim
entry + 7 refs + 1 nested config-gate dir. The auto-fix subagent (already
implemented in `agents/<existing-name>/`) has well-tested fix behavior;
re-extracting or modifying it would invalidate prior dogfood data.

If a future R-series wants to refactor the auto-fix subagent (e.g. to add
verification gates, cost caps, or parallel fix dispatch), that's a
separate scope.
