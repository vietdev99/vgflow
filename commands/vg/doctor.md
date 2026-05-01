---
name: vg:doctor
description: Thin dispatcher for VG state inspection — routes to /vg:health, /vg:integrity, /vg:gate-stats, /vg:recover. Use sub-commands directly for clarity.
argument-hint: "[health|integrity|gate-stats|recover] [...args]"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
observation_only: true
contract_exempt_reason: "read-only: dispatcher routing to /vg:health, /vg:integrity, /vg:gate-stats, /vg:recover — no mutation itself"
---

<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Markdown headers for progress. This command is a thin router — actual work happens in sub-commands.

**Translate English terms (RULE)** — `dispatcher (điều phối)`, `sub-command (lệnh con)`, `legacy flag (cờ cũ)`. Không áp dụng: file path, code ID.
</NARRATION_POLICY>

<rules>
1. **Pure routing** — never does health/integrity/gate/recover work directly. Invokes sub-command via Skill tool.
2. **Positional verb** — first arg parsed as verb: `health | integrity | gate-stats | recover`. Unknown verb → print help.
3. **Legacy flag compat** — `--integrity`, `--gates`, `--recover` emit a DEPRECATED warn and route to new sub-command.
4. **No arg or `help`** — print the 4-sub-command menu and exit 0.
5. **Zero heavy work** — this file stays ≤80 LOC.
</rules>

<process>

<step name="0_parse_verb">
## Step 0: Parse verb + route

```bash
# Extract first positional token + capture remaining args for forwarding.
VERB=""
FWD_ARGS=""
for arg in $ARGUMENTS; do
  case "$arg" in
    health|integrity|gate-stats|recover|recovery|stack|wired|dist|ohok|help)
      [ -z "$VERB" ] && VERB="$arg" || FWD_ARGS="${FWD_ARGS} ${arg}"
      ;;
    --dist|--distribution)
      VERB="dist"
      ;;
    --wired)
      VERB="wired"
      ;;
    --integrity)
      echo "⚠ DEPRECATED: --integrity flag. Use /vg:integrity instead." >&2
      VERB="integrity"
      ;;
    --gates)
      echo "⚠ DEPRECATED: --gates flag. Use /vg:gate-stats instead." >&2
      VERB="gate-stats"
      ;;
    --recover)
      echo "⚠ DEPRECATED: --recover flag. Use /vg:recover {phase} instead." >&2
      VERB="recover"
      ;;
    *)
      FWD_ARGS="${FWD_ARGS} ${arg}"
      ;;
  esac
done

# Default to help when no verb resolved
if [ -z "$VERB" ]; then
  [ -n "$FWD_ARGS" ] && VERB="health"  # bare phase arg → health deep mode (back-compat)
fi
```
</step>

<step name="1_dispatch">
## Step 1: Dispatch (or print help)

The shell block above resolves `VERB` and `FWD_ARGS`. The outer model reads the resolved values and routes via the **Skill tool**:

| Resolved VERB | Skill invocation |
|---------------|------------------|
| `health`      | `Skill(skill="vg:health", args=FWD_ARGS)` |
| `integrity`   | `Skill(skill="vg:integrity", args=FWD_ARGS)` |
| `gate-stats`  | `Skill(skill="vg:gate-stats", args=FWD_ARGS)` |
| `recover`     | `Skill(skill="vg:recover", args=FWD_ARGS)` |
| `stack`       | run `python .claude/scripts/vg-stack-health.py` inline (no sub-skill) |
| `wired`       | run `python .claude/scripts/vg-wired-check.py ${FWD_ARGS}` inline — WIRED-OR-NOTHING 3-check for validators/hooks/commands (OHOK v2 Day 6) |
| `dist`        | run `python .claude/scripts/distribution-check.py --verify ${FWD_ARGS}` inline — compare script+validator hashes vs `.distribution-manifest.json` baseline (detects local drift / tampering). Use `--generate` to rewrite baseline after intentional edits. |
| `ohok`        | run `python .claude/scripts/vg-ohok-metrics.py ${FWD_ARGS}` inline — **behavioral truth measurement** (OHOK-4). Reads events.db, computes true OHOK rate (% runs finishing PASS with 0 overrides + 0 manual promotions), per-command breakdown, override pressure top-N, promote-manual quota usage, validator BLOCK distribution. Accepts `--since 30d`, `--command build`, `--json`. |
| `recovery`    | run `python .claude/scripts/vg-recovery.py ${FWD_ARGS}` inline — **recovery path picker** (v2.46-wave3). Reads latest run from events.db, detects validator BLOCKs, prints actionable recovery paths per violation. Closes UX dead-end where BLOCK gives generic options. Accepts `--phase 3.2` (filter), `--json` (machine-readable). |
| `help` / ""   | print menu below, exit 0 |

For `stack` verb: executes the v2.2 stack diagnostic — orchestrator reachable, events.db integrity, schemas valid, validators present, hooks wired, bootstrap consistent. Exit 0 healthy, 1 warnings, 2 blocking issues.

```bash
if [ -z "$VERB" ] || [ "$VERB" = "help" ]; then
  cat <<'HELP'

🩺 ━━━ /vg:doctor — VG state inspection router ━━━

This command is a thin dispatcher. Use the sub-commands directly for clarity:

  /vg:health [phase]              Project health summary, or phase deep inspect
  /vg:integrity [phase]           Hash-validate artifacts across all (or one) phase
  /vg:gate-stats [--gate-id=X]    Gate event counts + override pressure
  /vg:recover {phase} [--apply]   Classify corruption + print recovery commands
  /vg:doctor stack                v2.2 stack diagnostic (orch + DB + schemas)
  /vg:doctor wired                WIRED-OR-NOTHING validators/hooks/commands check
  /vg:doctor dist [--generate]    Distribution integrity (sha256 manifest drift)
  /vg:doctor ohok [--since 30d]   Behavioral OHOK rate from events.db
  /vg:doctor recovery [--phase X] Recovery path picker for current BLOCK

Legacy flags (DEPRECATED, still routed):
  /vg:doctor --integrity          → /vg:integrity
  /vg:doctor --gates              → /vg:gate-stats
  /vg:doctor --recover {phase}    → /vg:recover {phase}

HELP
  exit 0
fi

echo "→ Routing to /vg:${VERB}${FWD_ARGS}"

# Inline verbs (not Skill subroutes) — execute Python script directly
case "$VERB" in
  recovery)
    python3 .claude/scripts/vg-recovery.py ${FWD_ARGS}
    exit $?
    ;;
  stack|wired|dist|ohok)
    # Other inline verbs handled per matrix above (already in this file's older revisions)
    ;;
esac

# Model side: now invoke Skill(skill="vg:${VERB}", args="${FWD_ARGS}")
```
</step>

</process>

<success_criteria>
- ≤80 LOC, no direct health/integrity/gate/recover logic.
- Legacy `--integrity | --gates | --recover` flags emit DEPRECATED warn and still route correctly.
- Unknown verb or no verb → help menu, exit 0.
- Router prints chosen target; outer model invokes via Skill tool.
</success_criteria>
</content>
</invoke>