---
runtime_contract:
  must_emit_telemetry:
    - event_type: "meta_memory.mode_changed"
      severity: "info"
---

# /vg:meta-memory — Meta-memory mode control

User-facing helper for the meta-memory v1.1 dogfood rollout flag.

## Usage

```
/vg:meta-memory enable           # set inject-as-advice (full loop)
/vg:meta-memory disable          # set disabled (default, vanilla pipeline)
/vg:meta-memory reflect-only     # reflector drafts candidates; inject sites skip
/vg:meta-memory status           # print current value
```

## Mode meanings

| Mode | Reflector spawns? | Inject sites apply? |
|---|---|---|
| disabled | no | no |
| reflect-only | yes | no |
| inject-as-advice | yes | yes (as advisory rules) |
| default | (alias for inject-as-advice) | (alias for inject-as-advice) |

## Implementation

```bash
case "${ARGUMENTS:-status}" in
  enable)        MODE="inject-as-advice" ;;
  disable)       MODE="disabled" ;;
  reflect-only)  MODE="reflect-only" ;;
  status)        MODE="status" ;;
  *)
    echo "⛔ Unknown subcommand: ${ARGUMENTS}" >&2
    echo "Usage: /vg:meta-memory enable|disable|reflect-only|status" >&2
    exit 1
    ;;
esac

HELPER="${REPO_ROOT:-.}/.claude/scripts/vg-meta-memory-set.py"
[ -f "$HELPER" ] || HELPER="${REPO_ROOT:-.}/scripts/vg-meta-memory-set.py"

"${PYTHON_BIN:-python3}" "$HELPER" --mode "$MODE"
```

See `docs/plans/2026-05-08-meta-memory-design.md` for the rollout design.
