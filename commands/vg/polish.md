---
name: vg:polish
description: "Optional code-cleanup pass — strip console.log, trailing whitespace, empty blocks. Atomic commit per fix. NOT a pipeline gate; user invokes when ready."
argument-hint: "[--scan | --apply] [--scope=phase-N|--since=<sha>|--file=<path>] [--level=light|deep] [--dry-run]"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "polish.started"
    - event_type: "polish.completed"
---

<rules>
1. **Optional, not a gate** — pipeline (specs → scope → blueprint → build → review → test → accept) does NOT depend on `/vg:polish` running. User invokes when satisfied with feature work and wants a tidy-up pass.
2. **Atomic per fix** — each fix is ONE commit. Failure reverts that fix only; other fixes survive.
3. **Light is safe** — light mode only touches code that can never affect runtime (console.log, trailing whitespace, empty blocks). No typecheck loop needed.
4. **Deep is gated** — deep mode requires test re-run after each fix; revert on regression.
5. **Read-only by default** — `--scan` (default) shows candidates without writing. `--apply` is the only mode that commits.
6. **Telemetry over judgement** — every applied / reverted fix emits an event. Decide ROI from `/vg:telemetry --command=vg:polish` after a few months of dogfood, then promote (or kill) features.
</rules>

<objective>
Surface and (optionally) auto-fix low-risk code-cleanliness issues that pile up across build / fix loops:
- `console.log` / `console.debug` / `console.info` / `console.warn` left over from debugging
- trailing whitespace
- empty `if {}` / `else {}` / `catch {}` / function bodies (refactor leftovers)

Modes:
- `--scan` (default) — print ranked candidates, write nothing
- `--apply` — apply fixes one-by-one, atomic commit per fix
- `--level=light` (default) — only the 3 categories above. Safe on production code (TS/JS/Python).
- `--level=deep` — light + warn on long functions (>80 lines). v1: warn-only, no auto-refactor.

Pipeline position: anytime after a code-touching step (`/vg:build`, `/vg:review`, `/vg:test`). NOT wired into accept gate.
</objective>

<process>

**Config:** Read `.claude/commands/vg/_shared/config-loader.md` first.

<step name="0_validate_prereqs">
## Step 0: Validate

```bash
set -euo pipefail
source .claude/commands/vg/_shared/config-loader.md 2>/dev/null || true
source .claude/commands/vg/_shared/telemetry.md 2>/dev/null || true
export VG_CURRENT_COMMAND="vg:polish"

# Engine script must exist
POLISH_PY="${REPO_ROOT:-.}/.claude/scripts/vg_polish.py"
[ -f "$POLISH_PY" ] || POLISH_PY="${REPO_ROOT:-.}/scripts/vg_polish.py"
if [ ! -f "$POLISH_PY" ]; then
  echo "⛔ vg_polish.py engine not found. Reinstall vgflow."
  exit 1
fi

# Inside a git repo
git rev-parse --show-toplevel >/dev/null 2>&1 || {
  echo "⛔ Not in a git repository. /vg:polish needs git for atomic commits."
  exit 1
}

# Working tree must be clean — atomic-commit semantics break with dirty tree
if [ -n "$(git status --porcelain)" ]; then
  echo "⚠ Working tree dirty. Either commit/stash first, or run with explicit --allow-dirty."
  echo "  (--allow-dirty makes commits include your in-flight changes — usually not what you want.)"
  case " ${ARGUMENTS:-} " in
    *" --allow-dirty "*) echo "  Continuing with --allow-dirty …" ;;
    *) exit 1 ;;
  esac
fi
```
</step>

<step name="1_parse_args">
## Step 1: Parse args

```bash
MODE="scan"
LEVEL="light"
SCOPE=""
DRY_RUN=""
ALLOW_DIRTY=""

for arg in ${ARGUMENTS}; do
  case "$arg" in
    --scan)         MODE="scan" ;;
    --apply)        MODE="apply" ;;
    --level=*)      LEVEL="${arg#--level=}" ;;
    --scope=*)      SCOPE="${arg#--scope=}" ;;
    --since=*)      SCOPE="since:${arg#--since=}" ;;
    --file=*)       SCOPE="file:${arg#--file=}" ;;
    --dry-run)      DRY_RUN="--dry-run" ;;
    --allow-dirty)  ALLOW_DIRTY="--allow-dirty" ;;
    *) ;;
  esac
done

case "$LEVEL" in
  light|deep) ;;
  *)
    echo "⛔ Invalid --level=${LEVEL}. Expected: light | deep"
    exit 1
    ;;
esac

echo "Mode: $MODE | Level: $LEVEL | Scope: ${SCOPE:-<repo>}"
```
</step>

<step name="2_emit_started">
## Step 2: Emit polish.started telemetry

```bash
if type -t emit_telemetry_v2 >/dev/null 2>&1; then
  emit_telemetry_v2 "polish.started" "" "" "" "INFO" \
    "{\"mode\":\"$MODE\",\"level\":\"$LEVEL\",\"scope\":\"${SCOPE:-repo}\"}" \
    >/dev/null 2>&1 || true
fi
```
</step>

<step name="3_run_engine">
## Step 3: Run engine

`vg_polish.py` does the actual scan + apply. Slash command is a thin wrapper that adds telemetry + arg parsing + git-state guards. Engine handles per-fix atomic commit, typecheck (deep mode), and revert.

```bash
SCAN_OUT=$(mktemp)

${PYTHON_BIN:-python3} "$POLISH_PY" \
  --mode "$MODE" \
  --level "$LEVEL" \
  ${SCOPE:+--scope "$SCOPE"} \
  ${DRY_RUN} \
  ${ALLOW_DIRTY} \
  --report "$SCAN_OUT"

ENGINE_EXIT=$?
```

The engine prints human-readable progress to stdout and writes a structured JSON report to `$SCAN_OUT` for telemetry consumption.
</step>

<step name="4_emit_completed">
## Step 4: Emit polish.completed telemetry

Read engine report and emit summary event.

```bash
if [ -s "$SCAN_OUT" ]; then
  PAYLOAD=$(${PYTHON_BIN:-python3} -c "
import json, sys
with open('$SCAN_OUT', 'r', encoding='utf-8') as f:
  r = json.load(f)
summary = {
  'candidates': r.get('candidates_count', 0),
  'applied': r.get('applied_count', 0),
  'reverted': r.get('reverted_count', 0),
  'mode': r.get('mode', 'scan'),
  'level': r.get('level', 'light'),
  'exit_code': $ENGINE_EXIT,
}
print(json.dumps(summary))
")

  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    OUTCOME="PASS"
    [ "$ENGINE_EXIT" -ne 0 ] && OUTCOME="FAIL"
    emit_telemetry_v2 "polish.completed" "" "" "" "$OUTCOME" "$PAYLOAD" \
      >/dev/null 2>&1 || true
  fi
fi

rm -f "$SCAN_OUT" 2>/dev/null
exit $ENGINE_EXIT
```
</step>

<step name="5_resume">
```
Polish complete.

  Mode:        $MODE
  Level:       $LEVEL
  Scope:       ${SCOPE:-<repo>}

Next:
  - Review commits:  git log --oneline -<applied_count>
  - Re-run scan:     /vg:polish --scope=$SCOPE
  - View telemetry:  /vg:telemetry --command=vg:polish
```
</step>

</process>

<example_use_cases>
1. **After /vg:build wave finishes**: `/vg:polish --scope=phase-7` to strip debug logs accumulated during build.
2. **Pre-PR cleanup**: `/vg:polish --since=main --apply` to clean up the branch before merge.
3. **Single-file targeted clean**: `/vg:polish --file=apps/web/src/components/Foo.tsx --apply`.
4. **Dry-run inspection**: `/vg:polish --apply --dry-run` to preview applies without committing.
5. **Deep pass after major fix loop**: `/vg:polish --level=deep --scope=phase-7` to surface long-function warnings (no auto-refactor in v1).
</example_use_cases>

<success_criteria>
- `--scan` mode lists ranked candidates per file, writes nothing.
- `--apply` produces N atomic commits, one per fix. Commits have the same author as user's git config.
- Each commit message: `polish: {fix_type} in {file}` with body citing scope.
- Engine emits `polish.fix_applied` per success and `polish.fix_reverted` per revert.
- Working tree clean after run (no leftover staging).
- Telemetry: `/vg:telemetry --command=vg:polish` shows aggregated counts.
- Skip-if-empty-tree guard rejects dirty working tree unless `--allow-dirty`.
</success_criteria>
