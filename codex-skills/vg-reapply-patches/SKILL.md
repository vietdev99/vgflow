---
name: "vg-reapply-patches"
description: "Resolve conflicts parked by /vg:update — interactive per-conflict resolution with 4 options (add --verify-gates for T8 hard-gate integrity resolution)"
metadata:
  short-description: "Resolve conflicts parked by /vg:update — interactive per-conflict resolution with 4 options (add --verify-gates for T8 hard-gate integrity resolution)"
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

This skill is invoked by mentioning `$vg-reapply-patches`. Treat all user text after `$vg-reapply-patches` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
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

If `$ARGUMENTS` contains `--verify-gates`, drive interactive gate-integrity resolution over `.planning/vgflow-patches/gate-conflicts.md` (written by `/vg:update` v1.8.0+ when a 3-way merge (gộp) altered a hard gate block).

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
  CONFLICTS_MD="${REPO_ROOT}/.planning/vgflow-patches/gate-conflicts.md"
  DIFF_DIR="${REPO_ROOT}/.planning/vgflow-patches/gate-conflicts"

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

1. Read the per-gate unified diff from `.planning/vgflow-patches/gate-conflicts/{command}-{gate_id}.diff`.
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
")"

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
")
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
")"

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
