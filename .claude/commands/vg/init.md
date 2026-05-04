---
name: vg:init
description: "[DEPRECATED — soft alias] Re-derive vg.config.md from existing FOUNDATION.md. Equivalent to /vg:project --init-only."
allowed-tools:
  - Read
  - Write
  - Bash
  - AskUserQuestion
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "init.started"
    - event_type: "init.completed"
---

<rules>
1. **Soft alias** — `/vg:init` is preserved for backward compatibility but redirects to `/vg:project --init-only` (or `/vg:project` for first-time / `/vg:project --migrate` for legacy).
2. **No discussion** — this command never asks foundation questions. For first-time setup or foundation discussion, use `/vg:project`.
3. **FOUNDATION.md required** for redirect to `--init-only`. If missing → suggest `/vg:project` or `/vg:project --migrate`.
</rules>

<objective>
Backward-compat alias for users who learned the old workflow (`/vg:init` first). Auto-detects state and points to correct `/vg:project` invocation.

**Migration note (v1.6.0+):** `/vg:init` no longer creates `vg.config.md` from scratch. Foundation discussion moved to `/vg:project`. Config is now derived from foundation, not the other way around.
</objective>

<process>

<step name="0_alias_redirect">
## Soft alias execution

```bash
PLANNING_DIR=".vg"
FOUNDATION_FILE="${PLANNING_DIR}/FOUNDATION.md"
PROJECT_FILE="${PLANNING_DIR}/PROJECT.md"

echo ""
echo "ℹ  /vg:init is now a soft alias (v1.6.0+)."
echo "   Foundation discussion moved to /vg:project — see CLAUDE.md VG Pipeline."
echo ""

if [ ! -f "$FOUNDATION_FILE" ] && [ ! -f "$PROJECT_FILE" ]; then
  echo "⛔ No PROJECT.md or FOUNDATION.md detected (first-time setup)."
  echo ""
  echo "Run instead:"
  echo "  /vg:project              ← first-time 7-round discussion"
  echo "  /vg:project @brief.md    ← parse from a brief document"
  echo ""
  echo "These will create PROJECT.md + FOUNDATION.md + vg.config.md atomically."
  exit 0
fi

if [ -f "$PROJECT_FILE" ] && [ ! -f "$FOUNDATION_FILE" ]; then
  echo "⚠ PROJECT.md exists but FOUNDATION.md missing (legacy v1 format)."
  echo ""
  echo "Run instead:"
  echo "  /vg:project --migrate    ← extract FOUNDATION.md from existing PROJECT.md + codebase"
  echo ""
  echo "After migration, /vg:init will redirect to --init-only as expected."
  exit 0
fi

# FOUNDATION.md exists → confirm + redirect
echo "✓ FOUNDATION.md found."
echo ""
```

Use AskUserQuestion:
```
"Re-derive vg.config.md from FOUNDATION.md?
 (No discussion, no foundation changes — chỉ refresh config.)

 [y] Yes — run /vg:project --init-only ngay
 [n] No — exit (run /vg:project --init-only manually later)"
```

If [y] → emit text "Redirecting to /vg:project --init-only..." and **invoke `/vg:project --init-only` as next action in same session**.

If [n] → exit with reminder text.
</step>

</process>

## Why this changed (v1.6.0 migration note)

Previously `/vg:init` was the entry point — it asked many config questions before the project was even defined (chicken-and-egg: config requires knowing the tech stack, but tech stack requires deciding the project).

In v1.6.0, the entry point is `/vg:project`. It captures project description, derives foundation (8 dimensions: platform/runtime/data/auth/hosting/distribution/scale/compliance), and **auto-generates `vg.config.md` from foundation** as a final step. Config is downstream of foundation, not upstream.

`/vg:init` is preserved as a soft alias for users with muscle memory. State-based redirect:

| State | `/vg:init` action |
|-------|-------------------|
| No artifacts | Suggest `/vg:project` (first-time) |
| PROJECT.md only (legacy) | Suggest `/vg:project --migrate` |
| Foundation present | Confirm + redirect to `/vg:project --init-only` |

## Success criteria

- `/vg:init` never crashes regardless of project state
- Always points user to correct `/vg:project` invocation
- Never overwrites artifacts — purely advisory + redirect
- Auto-chain into `/vg:project --init-only` if user confirms (foundation present)
