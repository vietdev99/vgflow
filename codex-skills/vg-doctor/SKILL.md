---
name: "vg-doctor"
description: "Thin dispatcher for VG state inspection — routes to /vg:health, /vg:integrity, /vg:gate-stats, /vg:recover. Use sub-commands directly for clarity."
metadata:
  short-description: "Thin dispatcher for VG state inspection — routes to /vg:health, /vg:integrity, /vg:gate-stats, /vg:recover. Use sub-commands directly for clarity."
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

This skill is invoked by mentioning `$vg-doctor`. Treat all user text after `$vg-doctor` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


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
    health|integrity|gate-stats|recover|help)
      [ -z "$VERB" ] && VERB="$arg" || FWD_ARGS="${FWD_ARGS} ${arg}"
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
| `help` / ""   | print menu below, exit 0 |

```bash
if [ -z "$VERB" ] || [ "$VERB" = "help" ]; then
  cat <<'HELP'

🩺 ━━━ /vg:doctor — VG state inspection router ━━━

This command is a thin dispatcher. Use the sub-commands directly for clarity:

  /vg:health [phase]              Project health summary, or phase deep inspect
  /vg:integrity [phase]           Hash-validate artifacts across all (or one) phase
  /vg:gate-stats [--gate-id=X]    Gate event counts + override pressure
  /vg:recover {phase} [--apply]   Classify corruption + print recovery commands

Legacy flags (DEPRECATED, still routed):
  /vg:doctor --integrity          → /vg:integrity
  /vg:doctor --gates              → /vg:gate-stats
  /vg:doctor --recover {phase}    → /vg:recover {phase}

HELP
  exit 0
fi

echo "→ Routing to /vg:${VERB}${FWD_ARGS}"
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
