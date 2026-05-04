<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 12: Forward-dep disposition gate in /vg:scope

**Files:**
- Modify: `commands/vg/scope.md`

- [ ] **Step 1: Find scope STEP 0 / preflight**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
grep -nE "^### STEP|^## STEP|preflight|FORWARD-DEPS" commands/vg/scope.md commands/vg/_shared/scope/preflight.md 2>/dev/null | head -20
```

Locate the preflight ref (likely `commands/vg/_shared/scope/preflight.md`).

- [ ] **Step 2: Add disposition gate to scope preflight**

Edit `commands/vg/_shared/scope/preflight.md`. Append a new section:

```markdown
## Step 1.5 — Forward-deps disposition gate (Codex feedback)

If `.vg/FORWARD-DEPS.md` exists with unresolved entries from prior phases,
this scope run MUST disposition each before proceeding. Codex review
(2026-05-03): "must handle should not mean must implement now."

Disposition options per entry (AskUserQuestion):
- `[a] accepted_into_phase` — work folds into this phase's scope
- `[d] deferred_to_phase X` — deferred (requires X target phase + rationale)
- `[b] converted_to_backlog` — moved to milestone backlog
- `[i] invalid/stale` — no longer relevant

```bash
FWD="${PLANNING_DIR:-.vg}/FORWARD-DEPS.md"
if [ -f "$FWD" ]; then
  UNRESOLVED=$(grep -c "^- \[" "$FWD" 2>/dev/null || echo 0)
  if [ "$UNRESOLVED" -gt 0 ]; then
    echo "▸ ${UNRESOLVED} unresolved forward-deps from prior phases — must disposition before scope"
    # Loop AskUserQuestion per entry; on each answer, append disposition log:
    #   ## Disposition log ($(date))
    #   - <entry> → accepted_into_phase / deferred_to_phase 5.0 / converted_to_backlog / invalid
    # Strip the entry from "## Forward deps" section once dispositioned.
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "scope.forward_deps_dispositioned" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"count\":${UNRESOLVED}}" \
      2>/dev/null || true
  fi
fi
```

Block scope if user dismisses without dispositioning ANY entry. The gate
fires on `disposition recorded`, not on `entry resolved`.
```

- [ ] **Step 3: Update scope.md frontmatter**

Edit `commands/vg/scope.md`. Add to `must_emit_telemetry:`:

```yaml
    - event_type: "scope.forward_deps_dispositioned"
      severity: "warn"
      required_unless_flag: "--no-forward-deps"
```

Add to `forbidden_without_override:`:

```yaml
    - "--no-forward-deps"
```

- [ ] **Step 4: Commit**

```bash
git add commands/vg/scope.md commands/vg/_shared/scope/preflight.md
git commit -m "feat(scope,build-fix-loop): forward-deps disposition gate (no silent forward)"
```

---

