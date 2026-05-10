#!/usr/bin/env bash
# v2.83.0 Stage 8 — migrate existing v2.x project to v3 layout.
#
# What it does (idempotent + atomic):
#   1. Pre-flight: detect current state, refuse if working tree dirty.
#   2. Backup: copy .claude/{commands,skills,scripts} + settings.json to
#      .vg/.backup-<ts>/ before mutating.
#   3. Move root docs → .vg/:
#        ROADMAP.md       -> .vg/ROADMAP.md
#        FOUNDATION.md    -> .vg/FOUNDATION.md
#        vg.config.md     -> .vg/config.md
#        OVERRIDE-DEBT.md -> .vg/OVERRIDE-DEBT.md (if present)
#   4. Branch by --target:
#        global  → remove .claude/{commands/vg, skills/vg-*, scripts}; install
#                  hooks at ~/.claude/settings.json --mode global
#        project → keep .claude mirror; install hooks at .claude/settings.json
#                  --mode project
#   5. Append .vg/ whitelist to .gitignore via generate-gitignore-v3.py
#   6. Write .vg/.install-target marker
#   7. Smoke: run `vg doctor` (when on PATH) — non-fatal warning on issues
#   8. Stage all changes (caller commits manually unless --commit passed).
#
# USAGE
#   vg-migrate-v3.sh --target=<global|project> [--commit] [--dry-run]
#
# EXIT CODES
#   0  success
#   1  bad args / missing prereqs
#   2  dirty working tree (refuse)
#   3  backup failed
#   4  doc move failed
#   5  hook install failed
#   6  smoke failed (warning only — exit 0 with warning)

set -u
set -o pipefail

# ── arg parse ──────────────────────────────────────────────────────
TARGET=""
COMMIT=0
DRY_RUN=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --target=*)   TARGET="${arg#--target=}" ;;
    --commit)     COMMIT=1 ;;
    --dry-run)    DRY_RUN=1 ;;
    --yes|-y)     ASSUME_YES=1 ;;
    -h|--help)
      sed -n '1,40p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "vg-migrate-v3.sh: unknown arg '$arg'" >&2
      exit 1
      ;;
  esac
done

case "$TARGET" in
  global|project) ;;
  *)
    echo "vg-migrate-v3.sh: --target=global|project required (got '${TARGET}')" >&2
    exit 1
    ;;
esac

REPO_ROOT="$(pwd)"

# ── pre-flight ─────────────────────────────────────────────────────
echo "vg-migrate-v3 (target=${TARGET}, dry_run=${DRY_RUN})"
echo "  repo:        ${REPO_ROOT}"

if [ ! -d "${REPO_ROOT}/.git" ]; then
  echo "⛔ ${REPO_ROOT} is not a git repo — refuse to migrate" >&2
  exit 1
fi

if [ "$DRY_RUN" = "0" ]; then
  # Check for modified, staged, AND untracked files. Untracked files would
  # silently move to .vg/.backup-<ts>/ if they sat under .claude/, leaving a
  # confusing "where did my file go?" diff. Refuse fast.
  if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
    echo "⛔ working tree dirty — commit or stash before migrating" >&2
    git -C "$REPO_ROOT" status --short >&2
    exit 2
  fi
fi

EXISTING_MARKER=""
[ -f "${REPO_ROOT}/.vg/.install-target" ] && \
  EXISTING_MARKER="$(tr -d '[:space:]' < "${REPO_ROOT}/.vg/.install-target")"
echo "  marker:      ${EXISTING_MARKER:-(absent)}"
echo "  has .claude: $([ -d "${REPO_ROOT}/.claude" ] && echo yes || echo no)"
echo "  has legacy:  $([ -f "${REPO_ROOT}/ROADMAP.md" ] || [ -f "${REPO_ROOT}/FOUNDATION.md" ] || [ -f "${REPO_ROOT}/vg.config.md" ] && echo yes || echo no)"

if [ "$EXISTING_MARKER" = "$TARGET" ] && [ "$DRY_RUN" = "0" ]; then
  echo "✓ already at target=${TARGET}; nothing to do (use /vg:install --repair to re-apply hooks)"
  exit 0
fi

if [ "$ASSUME_YES" = "0" ] && [ "$DRY_RUN" = "0" ]; then
  printf "Proceed with migration to %s? [y/N] " "$TARGET"
  read -r reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *) echo "aborted"; exit 0 ;;
  esac
fi

# Helper: dry-run aware shell exec
run() {
  if [ "$DRY_RUN" = "1" ]; then
    echo "  [dry-run] $*"
  else
    "$@"
  fi
}

# ── 1. backup ──────────────────────────────────────────────────────
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${REPO_ROOT}/.vg/.backup-${TS}"
echo ""
echo "[1/7] Backup → ${BACKUP_DIR}"
run mkdir -p "$BACKUP_DIR"
for d in commands skills scripts; do
  if [ -d "${REPO_ROOT}/.claude/${d}" ]; then
    if [ "$DRY_RUN" = "0" ]; then
      cp -R "${REPO_ROOT}/.claude/${d}" "${BACKUP_DIR}/${d}" || {
        echo "⛔ backup failed for .claude/${d}" >&2
        exit 3
      }
    else
      echo "  [dry-run] cp -R .claude/${d} ${BACKUP_DIR}/${d}"
    fi
  fi
done
[ -f "${REPO_ROOT}/.claude/settings.json" ] && \
  run cp "${REPO_ROOT}/.claude/settings.json" "${BACKUP_DIR}/settings.json.bak"

# ── 2. move root docs → .vg/ ──────────────────────────────────────
echo ""
echo "[2/7] Move root docs → .vg/"
run mkdir -p "${REPO_ROOT}/.vg"
move_doc() {
  local src="$1"
  local dst="$2"
  if [ -f "${REPO_ROOT}/${src}" ]; then
    if [ "$DRY_RUN" = "0" ]; then
      git -C "$REPO_ROOT" mv "${src}" "${dst}" 2>/dev/null \
        || mv "${REPO_ROOT}/${src}" "${REPO_ROOT}/${dst}" \
        || { echo "⛔ failed to move ${src} → ${dst}" >&2; exit 4; }
      echo "  ${src} → ${dst}"
    else
      echo "  [dry-run] git mv ${src} ${dst}"
    fi
  fi
}
move_doc "ROADMAP.md"       ".vg/ROADMAP.md"
move_doc "FOUNDATION.md"    ".vg/FOUNDATION.md"
move_doc "vg.config.md"     ".vg/config.md"
move_doc "OVERRIDE-DEBT.md" ".vg/OVERRIDE-DEBT.md"

# ── 2.5. merge per-phase deploy state → project-level (v2.87.0) ──
echo ""
echo "[2.5] Merge per-phase DEPLOY-STATE.json → .vg/deploy/STATE.json"
MERGE_DEPLOY_PY=""
for candidate in \
  "${REPO_ROOT}/.claude/scripts/migrate/merge-deploy-states.py" \
  "${HOME}/.vgflow/scripts/migrate/merge-deploy-states.py" \
  "${VG_HOME:-}/scripts/migrate/merge-deploy-states.py"; do
  if [ -f "$candidate" ]; then
    MERGE_DEPLOY_PY="$candidate"
    break
  fi
done
if [ -n "$MERGE_DEPLOY_PY" ]; then
  if [ "$DRY_RUN" = "0" ]; then
    # rc 0 = wrote project STATE.json; rc 2 = no per-phase state found (fine,
    # nothing to merge). Any other rc → warn but continue (deploy state isn't
    # blocking for the rest of migration).
    set +e
    python3 "$MERGE_DEPLOY_PY" --project-root "$REPO_ROOT" --backup
    MERGE_RC=$?
    set -e
    case "$MERGE_RC" in
      0) echo "  ✓ deploy state merged → .vg/deploy/STATE.json" ;;
      2) echo "  (no per-phase DEPLOY-STATE.json — nothing to merge)" ;;
      *) echo "  ⚠ merge-deploy-states rc=${MERGE_RC} — continue, run manually if needed" ;;
    esac
  else
    echo "  [dry-run] python3 ${MERGE_DEPLOY_PY} --project-root ${REPO_ROOT} --backup"
  fi
else
  echo "  ⚠ merge-deploy-states.py not found — skipping (run manually if needed)"
fi

# ── 3. branch by target ───────────────────────────────────────────
echo ""
echo "[3/7] Apply target=${TARGET}"

# Resolve dispatcher (vg-cli-dispatcher.sh) — global, env, or local
DISPATCHER=""
for candidate in \
  "${HOME}/.vgflow/bin/vg-cli-dispatcher.sh" \
  "${VG_HOME:-}/bin/vg-cli-dispatcher.sh" \
  "${REPO_ROOT}/bin/vg-cli-dispatcher.sh"; do
  if [ -f "$candidate" ]; then
    DISPATCHER="$candidate"
    break
  fi
done

if [ -z "$DISPATCHER" ]; then
  echo "⛔ vg-cli-dispatcher.sh not found. Install vgflow first:" >&2
  echo "   npm install -g vgflow  OR  git clone https://github.com/vietdev99/vgflow ~/.vgflow" >&2
  exit 5
fi
echo "  dispatcher: ${DISPATCHER}"

if [ "$TARGET" = "global" ]; then
  # Global: remove project-local .claude/{commands/vg, skills/vg-*, scripts}
  # because hooks now load from ~/.vgflow/.
  for d in ".claude/commands/vg" ".claude/scripts" ".claude/schemas" ".claude/templates/vg"; do
    if [ -d "${REPO_ROOT}/${d}" ]; then
      run git -C "$REPO_ROOT" rm -rqf "$d" 2>/dev/null || run rm -rf "${REPO_ROOT}/${d}"
      echo "  removed ${d}"
    fi
  done
  for d in .claude/skills/vg-*; do
    [ -d "$d" ] || continue
    run git -C "$REPO_ROOT" rm -rqf "$d" 2>/dev/null || run rm -rf "$d"
    echo "  removed $d"
  done
fi

# Run dispatcher install. The dispatcher itself handles --mode + marker write.
if [ "$DRY_RUN" = "0" ]; then
  VG_HOME="$(dirname "$(dirname "$DISPATCHER")")" \
    bash "$DISPATCHER" install "--${TARGET}" || {
      echo "⛔ dispatcher install --${TARGET} failed" >&2
      exit 5
    }
else
  echo "  [dry-run] bash ${DISPATCHER} install --${TARGET}"
fi

# ── 4. .gitignore whitelist ───────────────────────────────────────
echo ""
echo "[4/7] Append .vg/ whitelist to .gitignore"
GITIGNORE_GEN=""
for candidate in \
  "${REPO_ROOT}/.claude/scripts/migrate/generate-gitignore-v3.py" \
  "${HOME}/.vgflow/scripts/migrate/generate-gitignore-v3.py" \
  "${VG_HOME:-}/scripts/migrate/generate-gitignore-v3.py"; do
  if [ -f "$candidate" ]; then
    GITIGNORE_GEN="$candidate"
    break
  fi
done

if [ -n "$GITIGNORE_GEN" ]; then
  GITIGNORE_PATH="${REPO_ROOT}/.gitignore"
  if [ "$DRY_RUN" = "0" ]; then
    if [ ! -f "$GITIGNORE_PATH" ] || ! grep -q "VGFlow v3 layout" "$GITIGNORE_PATH" 2>/dev/null; then
      printf '\n' >> "$GITIGNORE_PATH"
      python3 "$GITIGNORE_GEN" >> "$GITIGNORE_PATH"
      echo "  appended whitelist to .gitignore"
    else
      echo "  .gitignore already has VGFlow v3 marker — skipping"
    fi
  else
    echo "  [dry-run] python3 ${GITIGNORE_GEN} >> .gitignore"
  fi
else
  echo "  ⚠ generate-gitignore-v3.py not found — manual update required"
fi

# ── 5. marker (defensive — dispatcher should have written it) ─────
echo ""
echo "[5/7] Verify .vg/.install-target marker"
MARKER="${REPO_ROOT}/.vg/.install-target"
if [ "$DRY_RUN" = "0" ]; then
  CURRENT="$(tr -d '[:space:]' < "$MARKER" 2>/dev/null || true)"
  if [ "$CURRENT" != "$TARGET" ]; then
    echo "  marker mismatch (expected ${TARGET}, got ${CURRENT:-absent}); writing directly"
    mkdir -p "$(dirname "$MARKER")"
    printf '%s\n' "$TARGET" > "$MARKER"
  fi
  echo "  ✓ marker = ${TARGET}"
else
  echo "  [dry-run] verify/write .vg/.install-target=${TARGET}"
fi

# ── 6. smoke test ─────────────────────────────────────────────────
echo ""
echo "[6/7] Smoke test"
if command -v vg >/dev/null 2>&1 && [ "$DRY_RUN" = "0" ]; then
  if vg doctor >/dev/null 2>&1; then
    echo "  ✓ vg doctor PASS"
  else
    echo "  ⚠ vg doctor reported issues — review output"
    vg doctor || true
  fi
else
  echo "  vg CLI not on PATH; skipping smoke test"
fi

# ── 7. stage / optional commit ────────────────────────────────────
echo ""
echo "[7/7] Stage changes"
if [ "$DRY_RUN" = "0" ]; then
  git -C "$REPO_ROOT" add -A .vg .gitignore || true
  if [ -d "${REPO_ROOT}/.claude" ]; then
    git -C "$REPO_ROOT" add -A .claude || true
  fi
  if [ "$COMMIT" = "1" ]; then
    git -C "$REPO_ROOT" commit -m "chore(vg): migrate to v3 layout (target=${TARGET})

Migrated by vg-migrate-v3.sh:
- Backed up .claude/ to .vg/.backup-${TS}/
- Moved root docs → .vg/ (ROADMAP, FOUNDATION, config, OVERRIDE-DEBT)
- Wrote .vg/.install-target=${TARGET}
- Installed hooks via vg-cli-dispatcher
- Appended .vg/ whitelist to .gitignore" || {
      echo "⛔ commit failed — review staged changes manually" >&2
      exit 1
    }
    echo "  ✓ committed migration"
  else
    echo "  staged (run 'git commit' to seal)"
  fi
else
  echo "  [dry-run] git add -A .vg .gitignore .claude"
fi

echo ""
echo "✓ vg-migrate-v3 complete (target=${TARGET})"
[ -d "$BACKUP_DIR" ] && echo "  backup: ${BACKUP_DIR}"
echo "  Restart Claude Code / Codex session to load updated hooks."
