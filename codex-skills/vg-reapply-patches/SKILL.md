---
name: "vg-reapply-patches"
description: "Resolve conflicts parked by /vg:update — interactive per-conflict resolution with 4 options (add --verify-gates for T8 hard-gate integrity resolution)"
metadata:
  short-description: "Resolve conflicts parked by /vg:update — interactive per-conflict resolution with 4 options (add --verify-gates for T8 hard-gate integrity resolution)"
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

Invoke this skill as `$vg-reapply-patches`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **Non-destructive** — never overwrite a target file unless user explicitly chose edit/keep-upstream for that entry.
2. **Manifest is source of truth** — iterate `.claude/vgflow-patches/.patches-manifest.json` entries; don't glob patches dir directly.
3. **Validate edit result** — after `$EDITOR` closes, reject resolution if conflict markers (`<<<<<<<`) still present.
4. **Atomic per entry** — update manifest only after the filesystem side (mv / rm / write target) succeeds.
5. **All marker math in Python** — no sed/awk regex games on conflict markers; use the inline Python helpers.
6. **Cleanup last** — delete `.claude/vgflow-patches/` only after the manifest is fully drained.
</rules>

<objective>
Drive an interactive resolution loop over every entry recorded in
`.claude/vgflow-patches/.patches-manifest.json` (created by `/vg:update`).
Each entry corresponds to `.claude/vgflow-patches/{rel}.conflict` — a
merged file still carrying `<<<<<<<` / `=======` / `>>>>>>>` markers from
`git merge-file`. The target install path is `.claude/{rel}` and at the
point this command runs still contains the user's pre-merge version
(because `/vg:update` parked the merged-with-markers copy and never
clobbered the target on conflict).

For each entry offer 4 resolutions:

- **[e] edit**   — open conflict file in `$EDITOR`, require no markers remain, then `mv` to target.
- **[k] keep upstream** — extract upstream side of each conflict block, write to target, remove conflict file.
- **[r] restore local** — discard upstream change; target is already local, just drop conflict file.
- **[s] skip**   — leave entry in manifest for a later run.

After the loop, if manifest is empty → `rm -rf .claude/vgflow-patches/`.
</objective>

<process>

<step name="0_mode_router">
**Mode router — T8 gate (cổng) integrity resolution vs legacy patch-conflict resolution.**

If `$ARGUMENTS` contains `--verify-gates`, drive interactive gate-integrity resolution over `${PLANNING_DIR}/vgflow-patches/gate-conflicts.md` (written by `/vg:update` v1.8.0+ when a 3-way merge (gộp) altered a hard gate block).

Otherwise, fall through to the legacy manifest-based patch resolution below.

```bash
set -u
MODE="patches"
case " $ARGUMENTS " in
  *" --verify-gates "*) MODE="verify-gates" ;;
esac
echo "mode (chế độ)=${MODE}"
```
</step>

<step name="0b_verify_gates_mode">
**Active only when `MODE=verify-gates`.** This step reads `gate-conflicts.md` (patches directory), offers an interactive per-conflict resolution walkthrough (upstream / merged / skip+flag / cancel), applies the choice, and — when all resolved — deletes the file so hard gates can trust their own logic again.

Resolutions (glossed):
- `[u] use upstream (dùng bản gốc)` — restore the canonical upstream block content.
- `[m] keep merged (giữ bản đã gộp)` — accept the merged-result block as-is (will still be re-hashed; persisting only if you explicitly accept risk).
- `[s] skip + flag manual (bỏ qua, gắn cờ để người kiểm tra)` — leave unresolved; caller must inspect manually.
- `[c] cancel (hủy)` — abort, keep everything as-is.

```bash
if [ "$MODE" != "verify-gates" ]; then
  echo "(skip verify-gates — running patches mode)"
fi

if [ "$MODE" = "verify-gates" ]; then
  REPO_ROOT="$(pwd)"
  CONFLICTS_MD="${REPO_ROOT}/${PLANNING_DIR}/vgflow-patches/gate-conflicts.md"
  DIFF_DIR="${REPO_ROOT}/${PLANNING_DIR}/vgflow-patches/gate-conflicts"

  if [ ! -f "$CONFLICTS_MD" ]; then
    echo "No gate-conflicts (xung đột cổng) found at ${CONFLICTS_MD}. Nothing to verify."
    exit 0
  fi

  # List conflict headings (## {command} :: {gate_id}) for the prompt loop
  REPO_ROOT="$REPO_ROOT" CONFLICTS_MD="$CONFLICTS_MD" python3 - <<'PY'
import os, re, sys
md = open(os.environ["CONFLICTS_MD"], encoding="utf-8").read()
blocks = re.findall(r'^##\s+([^\n]+)\s*\n(.*?)(?=^##\s|\Z)', md, flags=re.M|re.S)
print("FOUND={}".format(len(blocks)))
for title, body in blocks:
    print("---")
    print("TITLE: {}".format(title))
    for line in body.strip().splitlines()[:6]:
        print(" | " + line)
PY
fi
```

Then, for EACH conflict heading listed above, the Claude tool driver (not bash) should:

1. Read the per-gate unified diff from `${PLANNING_DIR}/vgflow-patches/gate-conflicts/{command}-{gate_id}.diff`.
2. Present the diff to the user via the `AskUserQuestion` tool with the 4 options `[u] use upstream` / `[m] keep merged` / `[s] skip+flag` / `[c] cancel`.
3. Apply the choice:
   - **`u`** — locate the gate block in `.claude/commands/vg/{command}.md` (using fingerprint from context), replace with the upstream block provided in the diff, emit telemetry `gate_integrity_conflict` with `outcome=RESOLVED_UPSTREAM`.
   - **`m`** — no file mutation; emit telemetry with `outcome=ACCEPTED_MERGED`, and append a `[manual-review]` marker line to `gate-conflicts.md` beside this entry so it stays visible in future `/vg:doctor` runs.
   - **`s`** — append `[skipped]` marker; do not clear the entry from `gate-conflicts.md`.
   - **`c`** — stop the loop; leave file untouched.
4. Record the resolution inline in `gate-conflicts.md` so the next run sees which entries are already handled.

When all entries carry one of {`[resolved-upstream]`, `[resolved-merged]`} markers (i.e. no `[skipped]` / unresolved headings remain), delete `gate-conflicts.md` and the sibling `gate-conflicts/` diff dir. Pipeline commands (`/vg:build`, `/vg:review`, `/vg:test`, `/vg:accept`) will unblock automatically.

```bash
if [ "$MODE" = "verify-gates" ]; then
  # Exit here — driver will loop via AskUserQuestion, then call this same
  # command again once all resolutions marked, and the file-exists check
  # naturally short-circuits.
  exit 0
fi
```
</step>

<step name="0_preflight">
```bash
set -u

REPO_ROOT="$(pwd)"
PATCHES_DIR="${REPO_ROOT}/.claude/vgflow-patches"
MANIFEST="${PATCHES_DIR}/.patches-manifest.json"
HELPER="${REPO_ROOT}/.claude/scripts/vg_update.py"

command -v python3 >/dev/null 2>&1 || { echo "python3 required"; exit 1; }

if [ ! -f "$HELPER" ]; then
  echo "vg_update.py missing at ${HELPER} — re-install vgflow first"
  exit 1
fi

if [ ! -f "$MANIFEST" ]; then
  echo "No patches manifest found. Nothing to resolve."
  # If the dir exists but manifest doesn't, clean up the stray dir too
  [ -d "$PATCHES_DIR" ] && rmdir "$PATCHES_DIR" 2>/dev/null || true
  exit 0
fi

COUNT="$(MANIFEST="$MANIFEST" REPO_ROOT="$REPO_ROOT" python3 -c "
import os, sys
sys.path.insert(0, os.path.join(os.environ['REPO_ROOT'], '.claude', 'scripts'))
from pathlib import Path
from vg_update import PatchesManifest
print(len(PatchesManifest(Path(os.environ['MANIFEST'])).list()))
" | tr -d '\r')"  # v2.41.3 (Issue #53 Bug #4) — strip Windows CR

if [ "$COUNT" = "0" ]; then
  echo "No patches to resolve."
  rm -rf "$PATCHES_DIR"
  exit 0
fi

echo "${COUNT} parked conflict(s) to resolve."
echo ""

# Pick an editor: explicit $EDITOR, else nano, else vi
EDITOR_CMD="${EDITOR:-}"
if [ -z "$EDITOR_CMD" ]; then
  if command -v nano >/dev/null 2>&1; then
    EDITOR_CMD="nano"
  elif command -v vi >/dev/null 2>&1; then
    EDITOR_CMD="vi"
  else
    EDITOR_CMD=""
  fi
fi
echo "editor=${EDITOR_CMD:-<none>}"
echo ""
```
</step>

<step name="1_iterate_manifest">
```bash
# Enumerate rel_paths via process substitution so the while-loop stays in
# the parent shell (counter vars below survive).
RESOLVED=0
SKIPPED=0
STUCK=0

while IFS= read -r REL; do
  [ -z "$REL" ] && continue

  CONFLICT_FILE="${PATCHES_DIR}/${REL}.conflict"
  TARGET="${REPO_ROOT}/.claude/${REL}"

  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  ${REL}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  if [ ! -f "$CONFLICT_FILE" ]; then
    echo "  (conflict file missing: ${CONFLICT_FILE})"
    echo "  Removing stale manifest entry."
    REL="$REL" MANIFEST="$MANIFEST" REPO_ROOT="$REPO_ROOT" python3 -c "
import os, sys
sys.path.insert(0, os.path.join(os.environ['REPO_ROOT'], '.claude', 'scripts'))
from pathlib import Path
from vg_update import PatchesManifest
PatchesManifest(Path(os.environ['MANIFEST'])).remove(os.environ['REL'])
"
    RESOLVED=$((RESOLVED + 1))
    echo ""
    continue
  fi

  MARKERS="$(grep -c '^<<<<<<<' "$CONFLICT_FILE" || true)"
  echo "  Conflict blocks: ${MARKERS:-0}"
  echo "  Target:          .claude/${REL}"
  echo ""
  echo "  [e] Edit in ${EDITOR_CMD:-editor}"
  echo "  [k] Keep upstream  (discard your local edits)"
  echo "  [r] Restore local  (discard upstream changes)"
  echo "  [s] Skip for now"
  echo ""

  # Prompt (read from controlling terminal so it works inside harness)
  CHOICE=""
  if [ -r /dev/tty ]; then
    read -r -p "Choice [e/k/r/s]: " CHOICE </dev/tty || CHOICE="s"
  else
    read -r -p "Choice [e/k/r/s]: " CHOICE || CHOICE="s"
  fi
  CHOICE="$(printf '%s' "$CHOICE" | tr '[:upper:]' '[:lower:]' | head -c1)"

  case "$CHOICE" in
    e)
      if [ -z "$EDITOR_CMD" ]; then
        echo "  ! No editor available (set \$EDITOR, or install nano/vi). Skipping."
        SKIPPED=$((SKIPPED + 1))
        echo ""
        continue
      fi
      "$EDITOR_CMD" "$CONFLICT_FILE" </dev/tty >/dev/tty 2>&1 || true
      if grep -q '^<<<<<<<' "$CONFLICT_FILE"; then
        echo "  ! Conflict markers still present. Leaving in patches/ for next run."
        STUCK=$((STUCK + 1))
        echo ""
        continue
      fi
      mkdir -p "$(dirname "$TARGET")"
      mv "$CONFLICT_FILE" "$TARGET"
      REL="$REL" MANIFEST="$MANIFEST" REPO_ROOT="$REPO_ROOT" python3 -c "
import os, sys
sys.path.insert(0, os.path.join(os.environ['REPO_ROOT'], '.claude', 'scripts'))
from pathlib import Path
from vg_update import PatchesManifest
PatchesManifest(Path(os.environ['MANIFEST'])).remove(os.environ['REL'])
"
      RESOLVED=$((RESOLVED + 1))
      echo "  ✓ Resolved via edit."
      ;;

    k)
      # Extract upstream side of every conflict block.
      # Block layout:
      #   <<<<<<< ours
      #   ...ours lines...       (skip)
      #   =======
      #   ...theirs lines...     (keep = upstream)
      #   >>>>>>> theirs
      # Everything outside a block is kept as-is.
      mkdir -p "$(dirname "$TARGET")"
      CONFLICT_FILE="$CONFLICT_FILE" TARGET="$TARGET" python3 - <<'PY'
import os, sys
src = os.environ["CONFLICT_FILE"]
dst = os.environ["TARGET"]
with open(src, encoding="utf-8") as f:
    text = f.read()
out = []
in_local = False  # inside the "ours" half of a conflict block
for line in text.splitlines(keepends=True):
    if line.startswith("<<<<<<<"):
        in_local = True
        continue
    if line.startswith("======="):
        in_local = False
        continue
    if line.startswith(">>>>>>>"):
        # end of block; already outside "ours"
        continue
    if not in_local:
        out.append(line)
with open(dst, "w", encoding="utf-8") as f:
    f.writelines(out)
PY
      RC=$?
      if [ $RC -ne 0 ]; then
        echo "  ! Marker extraction failed (rc=$RC). Leaving entry parked."
        STUCK=$((STUCK + 1))
        echo ""
        continue
      fi
      # Verify no markers leaked through
      if grep -q '^<<<<<<<' "$TARGET"; then
        echo "  ! Output still has markers. Rolling back target and keeping parked."
        # Target was only just written; we can't restore to pre-write content,
        # but we also never wrote it before this command — so removing it is safer.
        rm -f "$TARGET"
        STUCK=$((STUCK + 1))
        echo ""
        continue
      fi
      rm -f "$CONFLICT_FILE"
      REL="$REL" MANIFEST="$MANIFEST" REPO_ROOT="$REPO_ROOT" python3 -c "
import os, sys
sys.path.insert(0, os.path.join(os.environ['REPO_ROOT'], '.claude', 'scripts'))
from pathlib import Path
from vg_update import PatchesManifest
PatchesManifest(Path(os.environ['MANIFEST'])).remove(os.environ['REL'])
"
      RESOLVED=$((RESOLVED + 1))
      echo "  ✓ Upstream applied."
      ;;

    r)
      # /vg:update parked the merged-with-markers copy and did NOT touch the
      # target on conflict. So the target is already the user's local pre-merge
      # version. Dropping the conflict file + manifest entry completes the
      # "restore local" choice.
      rm -f "$CONFLICT_FILE"
      REL="$REL" MANIFEST="$MANIFEST" REPO_ROOT="$REPO_ROOT" python3 -c "
import os, sys
sys.path.insert(0, os.path.join(os.environ['REPO_ROOT'], '.claude', 'scripts'))
from pathlib import Path
from vg_update import PatchesManifest
PatchesManifest(Path(os.environ['MANIFEST'])).remove(os.environ['REL'])
"
      RESOLVED=$((RESOLVED + 1))
      echo "  ✓ Local kept (target unchanged)."
      ;;

    s)
      echo "  - Skipped."
      SKIPPED=$((SKIPPED + 1))
      ;;

    *)
      echo "  ? Invalid choice '${CHOICE}'. Treating as skip."
      SKIPPED=$((SKIPPED + 1))
      ;;
  esac
  echo ""
done < <(MANIFEST="$MANIFEST" REPO_ROOT="$REPO_ROOT" python3 -c "
import os, sys
sys.path.insert(0, os.path.join(os.environ['REPO_ROOT'], '.claude', 'scripts'))
from pathlib import Path
from vg_update import PatchesManifest
for e in PatchesManifest(Path(os.environ['MANIFEST'])).list():
    print(e['path'])
" | tr -d '\r')
# v2.41.3 (Issue #53 Bug #4) — Python on Windows emits CRLF; bash `read -r REL`
# keeps the trailing \r, so CONFLICT_FILE="${PATCHES_DIR}/${REL}\r.conflict"
# never exists → every entry is reported STALE, manifest never drains.
# `tr -d '\r'` strips at the consumer side — works regardless of producer encoding.
```
</step>

<step name="2_cleanup_and_report">
```bash
REMAINING="$(MANIFEST="$MANIFEST" REPO_ROOT="$REPO_ROOT" python3 -c "
import os, sys
sys.path.insert(0, os.path.join(os.environ['REPO_ROOT'], '.claude', 'scripts'))
from pathlib import Path
from vg_update import PatchesManifest
print(len(PatchesManifest(Path(os.environ['MANIFEST'])).list()))
" | tr -d '\r')"  # v2.41.3 (Issue #53 Bug #4) — strip Windows CR

echo "════════════════════════════════════════════"
echo "  reapply-patches complete"
echo "  resolved=${RESOLVED} skipped=${SKIPPED} stuck=${STUCK} remaining=${REMAINING}"
echo "════════════════════════════════════════════"

if [ "$REMAINING" = "0" ]; then
  rm -rf "$PATCHES_DIR"
  echo ""
  echo "All conflicts resolved. Cleaned up .claude/vgflow-patches/."
  echo "NOTE: Restart Claude Code session if any resolved file is a command/skill."
else
  echo ""
  echo "${REMAINING} conflict(s) remain. Re-run /vg:reapply-patches when ready."
fi
```
</step>

</process>

<success_criteria>
- Exits cleanly with "No patches to resolve" when manifest missing or empty; stray dir removed.
- Iterates every manifest entry, showing relative path + marker block count + 4 options.
- `[e]` edit path: rejects resolution if markers remain, otherwise moves file to `.claude/{rel}` and drops manifest entry.
- `[k]` keep upstream: writes upstream-only content to `.claude/{rel}`, removes `.conflict` + manifest entry.
- `[r]` restore local: removes `.conflict` + manifest entry; target file untouched (already local).
- `[s]` skip / invalid: manifest entry preserved.
- Patches dir removed iff manifest ends up empty.
- Final report shows resolved / skipped / stuck / remaining counts.
</success_criteria>
