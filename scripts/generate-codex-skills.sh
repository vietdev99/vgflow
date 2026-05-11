#!/bin/bash
# Generate Codex skills from the canonical VGFlow source tree.
#
# Source of truth:
#   - commands/vg/*.md          -> codex-skills/vg-*/SKILL.md
#   - skills/*/SKILL.md         -> codex-skills/*/SKILL.md
#
# Usage:
#   scripts/generate-codex-skills.sh [--force]
#
# This repo is now the canonical VGFlow source. DEV_ROOT/RTB source probing is
# intentionally gone; use sync.sh to deploy this repo's generated artifacts to
# global ~/.codex/ and prune project-local VG-owned .codex/.claude copies.

set -euo pipefail

FORCE=false
FORCE_OVERWRITE_CURATED=false
ONLY_SKILLS=()
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=true ;;
    --force-overwrite-curated)
      # v3.6.2 — explicit opt-in to overwrite Codex-curated content
      # (HARD-GATE-CODEX blocks, manual mark-step enumerations). Default
      # --force regen preserves curated content to prevent CI failures.
      FORCE=true
      FORCE_OVERWRITE_CURATED=true
      ;;
    --skill=*)
      ONLY_SKILLS+=("${arg#--skill=}")
      ;;
    -h|--help)
      sed -n '1,24p' "$0" | sed 's/^# \{0,1\}//'
      echo "  --skill=<name>          Regenerate only one skill (e.g. test, vg-test)"
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done
export FORCE_OVERWRITE_CURATED

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMMANDS_DIR="$REPO_ROOT/commands/vg"
SHARED_SKILLS_DIR="$REPO_ROOT/skills"
TARGET_DIR="$REPO_ROOT/codex-skills"

if [ ! -d "$COMMANDS_DIR" ]; then
  echo "ERROR: canonical commands directory missing: $COMMANDS_DIR" >&2
  exit 2
fi

mkdir -p "$TARGET_DIR"

extract_description() {
  local src="$1"
  awk '
    /^description:/ {
      sub(/^description:[[:space:]]*"?/, "")
      sub(/"?[[:space:]]*$/, "")
      print
      exit
    }
  ' "$src"
}

strip_frontmatter() {
  local src="$1"
  awk '
    BEGIN { in_fm = 0; past_fm = 0 }
    /^---$/ {
      if (in_fm == 0 && past_fm == 0) { in_fm = 1; next }
      if (in_fm == 1) { in_fm = 0; past_fm = 1; next }
    }
    past_fm == 1 { print }
  ' "$src"
}

skill_selected() {
  local name="$1"
  local skill_name="$2"
  if [ "${#ONLY_SKILLS[@]}" -eq 0 ]; then
    return 0
  fi
  local wanted
  for wanted in "${ONLY_SKILLS[@]}"; do
    case "$wanted" in
      "$name"|"$skill_name"|"vg-$name")
        return 0
        ;;
    esac
  done
  return 1
}

extract_hard_markers() {
  local src="$1"
  python - "$src" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
if not match:
    raise SystemExit(0)
frontmatter = match.group(1)
markers = re.search(
    r"^  must_touch_markers:\s*\n(.*?)(?=^  [a-zA-Z_]+:|\Z)",
    frontmatter,
    re.S | re.M,
)
if not markers:
    markers = re.search(
        r"^must_touch_markers:\s*\n(.*?)(?=^[a-zA-Z_]+:|\Z)",
        frontmatter,
        re.S | re.M,
    )
if not markers:
    raise SystemExit(0)
for marker in re.findall(r'^\s+-\s*"([^"]+)"\s*$', markers.group(1), re.M):
    print(marker)
PY
}

write_codex_marker_block() {
  local src="$1"
  local cmd_name="$2"
  local markers
  markers="$(extract_hard_markers "$src" || true)"
  [ -n "$markers" ] || return 0

  cat <<EOF

<HARD-GATE-CODEX>
Codex has no Claude PreToolUse/PostToolUse hook substrate. Claude hooks may
auto-emit step markers, but Codex MUST emit the same hard markers explicitly
after each matching STEP primary action.

Use global VGFlow paths so global-only installs work without project-local
\`.claude/scripts\` or \`.claude/commands\`:

\`\`\`bash
VG_HOME="\${VG_HOME:-\$HOME/.vgflow}"
VG_SCRIPT_ROOT="\${VG_SCRIPT_ROOT:-\${VG_HOME}/scripts}"
EOF
  while IFS= read -r marker; do
    [ -n "$marker" ] || continue
    printf '"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/vg-orchestrator" mark-step %s %s\n' "$cmd_name" "$marker"
  done <<< "$markers"
  cat <<'EOF'
```

Hook/spawn mechanics may differ by provider, but marker names, order, gates,
must-write artifacts, and telemetry contract stay identical to the Claude
command source.
</HARD-GATE-CODEX>
EOF
}

write_generic_adapter() {
  local invocation_name="$1"
  cat <<EOF
<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Runtime lock

When this skill is running inside Codex, DO NOT switch to Claude CLI to execute
the workflow entrypoint. Keep the current Codex runtime, export
\`VG_RUNTIME=codex\`, use Codex \`update_plan\` for the compact visible task
window, and bind it with \`vg-orchestrator tasklist-projected --adapter codex\`.

VGFlow source paths are resolved through global \`VG_HOME\` (default:
\`~/.vgflow\`). Project-local Claude workflow files may be absent in
global-only installs; Codex must use
\`\${VG_SCRIPT_ROOT:-\${VG_HOME:-\$HOME/.vgflow}/scripts}\` and
\`\${VG_COMMAND_ROOT:-\${VG_HOME:-\$HOME/.vgflow}/commands/vg}\` for workflow
helpers. References below to "Claude CLI", \`TodoWrite\`, or Haiku describe
the Claude adapter only. Codex must map them through this adapter contract
instead of aborting the current run and relaunching Claude.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as \`codex-inline\` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer \`\${VG_COMMAND_ROOT:-\${VG_HOME:-\$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh\` or native Codex subagents | Use \`codex exec\` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Compact Codex plan window + orchestrator step markers | Use \`tasklist-contract.json\` as source of truth. Do not paste the full hierarchy into Codex \`update_plan\`. Show at most 6 rows: active group/step first, next 2-3 pending steps, completed groups collapsed, and \`+N pending\`. After projecting, emit \`vg-orchestrator tasklist-projected --adapter codex\`. |
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
| Planner/research/checker Agent | Use the source \`Agent(...)\` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call \`\${VG_COMMAND_ROOT:-\${VG_HOME:-\$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh --tier planner\` |
| Build executor Agent | Use the source executor \`Agent(...)\` call | Use \`codex-spawn.sh --tier executor --sandbox workspace-write\` with explicit file ownership and expected artifact output |
| Adversarial/CrossAI reviewer | Use configured external CLIs and consensus validators | Use configured \`codex exec\`/Gemini/Claude commands from \`.claude/vg.config.md\`; fail if required CLI output is missing or unparsable |
| Haiku scanner / Playwright / Maestro / MCP-heavy work | Use Claude subagents where the source command requires them | Keep MCP-heavy work in the main Codex orchestrator unless child MCP access was smoke-tested; scanner work may run inline/sequential instead of parallel, but must write the same scan artifacts and events |
| Reflection / learning | Use \`vg-reflector\` workflow | Use the Codex \`vg-reflector\` adapter or \`codex-spawn.sh --tier scanner\`; candidates still require the same user gate |

### Codex hook parity

Claude Code has a project-local hook substrate; Codex skills do not receive
Claude \`UserPromptSubmit\`, \`Stop\`, or \`PostToolUse\` hooks automatically.
Therefore Codex must execute the lifecycle explicitly through the same
orchestrator that writes \`.vg/events.db\`:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| \`UserPromptSubmit\` -> \`vg-entry-hook.py\` | Pre-seeds \`vg-orchestrator run-start\` and \`.vg/.session-context.json\` before the skill loads | Treat the command body's explicit \`vg-orchestrator run-start\` as mandatory; if missing or failing, BLOCK before doing work |
| \`Stop\` -> \`vg-verify-claim.py\` | Runs \`vg-orchestrator run-complete\` and blocks false done claims | Run the command body's terminal \`vg-orchestrator run-complete\` before claiming completion; if it returns non-zero, fix evidence and retry |
| \`PostToolUse\` edit -> \`vg-edit-warn.py\` | Warns that command/skill edits require session reload | After editing VG workflow files on Codex, tell the user the current session may still use cached skill text |
| \`PostToolUse\` Bash -> \`vg-step-tracker.py\` | Tracks marker commands and emits \`hook.step_active\` telemetry | Do not rely on the hook; call explicit \`vg-orchestrator mark-step\` lines in the skill and preserve marker/telemetry events |

Codex hook parity is evidence-based: \`.vg/events.db\`, step markers,
\`must_emit_telemetry\`, and \`run-complete\` output are authoritative. A Codex
run is not complete just because the model says it is complete.

Before executing command bash blocks from a Codex skill, export
\`VG_RUNTIME=codex\`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical \`AskUserQuestion\` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as \`codex-inline\`.

### Codex spawn precedence

When the source workflow below says \`Agent(...)\` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| \`/vg:build\` wave executor, \`model="\${MODEL_EXECUTOR}"\` | Write one prompt file per task, run \`codex-spawn.sh --tier executor\`; parallelize independent tasks with background processes and \`wait\`, serialize dependency groups | \`VG_CODEX_MODEL_EXECUTOR\`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | \`workspace-write\` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| \`/vg:blueprint\`, \`/vg:scope\`, planner/checker agents | Run \`codex-spawn.sh --tier planner\` or inline in the main orchestrator if the step needs interactive user answers | \`VG_CODEX_MODEL_PLANNER\` | \`workspace-write\` for artifact-writing planners, \`read-only\` for pure checks | requested artifacts or JSON verdict |
| \`/vg:review\` navigator/scanner, \`Agent(model="haiku")\` | Use \`--scanner=codex-inline\` by default. Do NOT ask to spawn Haiku or blindly spawn \`codex exec\` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use \`codex-spawn.sh --tier scanner --sandbox read-only\` only for non-MCP classification over captured snapshots/artifacts. | \`VG_CODEX_MODEL_SCANNER\`; set this to a cheap/fast model for review map/scanner work | \`read-only\` unless explicitly generating scan files from supplied evidence | same \`scan-*.json\`, \`RUNTIME-MAP.json\`, \`GOAL-COVERAGE-MATRIX.md\`, and \`review.haiku_scanner_spawned\` telemetry event semantics |
| \`/vg:review\` fix agents and \`/vg:test\` codegen agents | Use \`codex-spawn.sh --tier executor\` because they edit code/tests | \`VG_CODEX_MODEL_EXECUTOR\` or explicit \`--model\` if the command selected a configured fix model | \`workspace-write\` | changed files, tests run, unresolved risks |
| Rationalization guard, reflector, gap hunters | Use \`codex-spawn.sh --tier scanner\` for read-only classification, or \`--tier adversarial\` for independent challenge/review | \`VG_CODEX_MODEL_SCANNER\` or \`VG_CODEX_MODEL_ADVERSARIAL\` | \`read-only\` by default | compact JSON/markdown verdict; fail closed on empty/unparseable output |

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

VGFlow keeps tier names in \`.claude/vg.config.md\`; Codex subprocesses use
the user's Codex config model by default. Pin a tier only after smoke-testing
that model in the target account, via \`VG_CODEX_MODEL_PLANNER\`,
\`VG_CODEX_MODEL_EXECUTOR\`, \`VG_CODEX_MODEL_SCANNER\`, or
\`VG_CODEX_MODEL_ADVERSARIAL\`:

| VG tier | Claude-style role | Codex default | Fallback |
|---|---|---|---|
| planner | Opus-class planning/reasoning | Codex config default | Set \`VG_CODEX_MODEL_PLANNER\` only after smoke-testing |
| executor | Sonnet-class coding/review | Codex config default | Set \`VG_CODEX_MODEL_EXECUTOR\` only after smoke-testing |
| scanner | Haiku-class scan/classify | Codex config default | Set \`VG_CODEX_MODEL_SCANNER\` only after smoke-testing |
| adversarial | independent reviewer | Codex config default | Set \`VG_CODEX_MODEL_ADVERSARIAL\` only after smoke-testing |

### Spawn helper

For subprocess-based children, use:

\`\`\`bash
bash "\${VG_COMMAND_ROOT:-\${VG_HOME:-\$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh" \\
  --tier executor \\
  --prompt-file "\$PROMPT_FILE" \\
  --out "\$OUT_FILE" \\
  --timeout 900 \\
  --sandbox workspace-write
\`\`\`

The helper wraps \`codex exec\`, writes the final message to \`--out\`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.

### Known Codex caveats to design around

- Do not trust inline model selection for native subagents unless verified in the current Codex version; use TOML-pinned agents or \`codex exec --model\`.
- Do not combine structured \`--output-schema\` with MCP-heavy runs until the target Codex version is smoke-tested. Prefer plain text + post-parse for MCP flows.
- Recursive \`codex exec\` runs inherit sandbox constraints. Use the least sandbox that still allows the child to write expected artifacts.

### Support-skill MCP pattern

Pattern A: INLINE ORCHESTRATOR. For MCP-heavy support skills such as
\`vg-haiku-scanner\`, Codex keeps Playwright/Maestro actions in the main
orchestrator and only delegates read-only classification after snapshots are
captured. This preserves MCP access and avoids false confidence from a child
process that cannot see browser tools.

## Invocation

Invoke this skill as \`\$${invocation_name}\`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>
EOF
}

preserve_existing_adapter() {
  local target="$1"
  if [ ! -f "$target" ]; then
    return 1
  fi
  python - "$target" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r"<codex_skill_adapter>.*?</codex_skill_adapter>", text, re.S)
if not match:
    sys.exit(1)
print(match.group(0))
PY
}

# v3.6.2 — detect Codex-curated content that --force regeneration must NOT
# clobber. Specifically: HARD-GATE-CODEX reminder blocks and explicit
# `mark-step` enumerations added in 765e9e5 (A9) for Codex parity.
# When detected, force adapter_mode=preserve so the curated section survives.
target_has_curated_codex_content() {
  local target="$1"
  if [ ! -f "$target" ]; then
    return 1
  fi
  if grep -q "HARD-GATE-CODEX" "$target" 2>/dev/null; then
    return 0
  fi
  # Heuristic: skill body explicitly lists `vg-orchestrator mark-step <ns> <step>`
  # lines (8+ occurrences = clearly the A9 manual-mark enumeration).
  local count
  count=$(grep -c "vg-orchestrator mark-step" "$target" 2>/dev/null || echo 0)
  if [ "${count:-0}" -ge 8 ]; then
    return 0
  fi
  return 1
}

target_skill_frontmatter_invalid() {
  local target="$1"
  if [ ! -f "$target" ]; then
    return 1
  fi
  python - "$target" <<'PY'
from pathlib import Path
import re
import sys

try:
    import yaml
except Exception:
    # If PyYAML is absent, do not guess. The generator can still emit valid
    # YAML for newly written files; this guard only repairs existing targets.
    sys.exit(1)

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
match = re.match(r"^---\n(.*?)\n---(?:\n|\Z)", text, re.S)
if not match:
    sys.exit(0)

try:
    front = yaml.safe_load(match.group(1)) or {}
except yaml.YAMLError:
    sys.exit(0)

if not isinstance(front, dict):
    sys.exit(0)
if not front.get("name") or not front.get("description"):
    sys.exit(0)
sys.exit(1)
PY
}

repair_codex_skill_frontmatter() {
  local target="$1"
  local skill_name="$2"
  local description_yaml="$3"

  python - "$target" "$skill_name" "$description_yaml" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
name = sys.argv[2]
description = sys.argv[3]
text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

match = re.match(r"^---\n.*?\n---(?:\n|\Z)", text, re.S)
body = text[match.end():] if match else text
frontmatter = (
    "---\n"
    f'name: "{name}"\n'
    f'description: "{description}"\n'
    "metadata:\n"
    f'  short-description: "{description}"\n'
    "---\n\n"
)
path.write_text(frontmatter + body.lstrip("\n"), encoding="utf-8")
PY
}

write_codex_skill() {
  local src="$1"
  local target="$2"
  local skill_name="$3"
  local description="$4"
  local adapter_mode="${5:-generic}"
  local command_marker_name="${6:-}"
  local preserved_adapter=""
  local target_invalid_yaml="false"

  if [ -z "$description" ]; then
    description="VGFlow skill generated from ${src#$REPO_ROOT/}"
  fi

  # v3.6.1 — escape double-quote and backslash in description before
  # emitting into a YAML double-quoted string. Without this, source
  # descriptions containing embedded `"..."` (e.g. LIFECYCLE.md cites
  # `"where am I in the pipeline"`) produce invalid frontmatter that
  # Codex CLI rejects with `did not find expected key` at SKILL load.
  local description_yaml
  description_yaml="${description//\\/\\\\}"
  description_yaml="${description_yaml//\"/\\\"}"

  if target_skill_frontmatter_invalid "$target"; then
    target_invalid_yaml="true"
  fi

  if [ -f "$target" ] && [ "$FORCE" = "false" ]; then
    if [ "$target_invalid_yaml" = "true" ]; then
      repair_codex_skill_frontmatter "$target" "$skill_name" "$description_yaml"
      REPAIRED=$((REPAIRED + 1))
      echo "Repaired invalid YAML frontmatter: ${skill_name}"
      return
    fi
    SKIPPED=$((SKIPPED + 1))
    return
  fi

  # v3.6.2 — refuse to clobber Codex-curated content even with --force.
  # HARD-GATE-CODEX reminder blocks + explicit mark-step enumerations
  # (765e9e5 A9 work) live OUTSIDE the <codex_skill_adapter> block, so
  # preserve_existing_adapter cannot save them. Default --force regen
  # therefore wipes the curated section and CI fails with "missing
  # <HARD-GATE-CODEX> reminder block" (run 25637574359 fail).
  #
  # When curated content is detected:
  #   - Default behavior: skip the regen (treat target as authoritative).
  #     Operator must use --force-overwrite-curated to intentionally rewrite.
  #   - Force adapter_mode=preserve so the codex_skill_adapter block also
  #     survives, in case it carries provider-mapping customizations.
  if target_has_curated_codex_content "$target"; then
    if [ "${FORCE_OVERWRITE_CURATED:-false}" != "true" ]; then
      if [ "$target_invalid_yaml" = "true" ]; then
        repair_codex_skill_frontmatter "$target" "$skill_name" "$description_yaml"
        REPAIRED=$((REPAIRED + 1))
        echo "Repaired invalid YAML frontmatter (curated content preserved): ${skill_name}"
        return
      fi
      SKIPPED=$((SKIPPED + 1))
      echo "Skipped (curated content detected): ${skill_name} — use --force-overwrite-curated to override"
      return
    fi
    adapter_mode="generic"
  fi

  mkdir -p "$(dirname "$target")"
  if [ "$adapter_mode" = "preserve" ] && [ -f "$target" ]; then
    preserved_adapter="$(preserve_existing_adapter "$target" || true)"
  fi

  {
    cat <<EOF
---
name: "${skill_name}"
description: "${description_yaml}"
metadata:
  short-description: "${description_yaml}"
---

EOF
    if [ -n "$preserved_adapter" ]; then
      printf '%s\n' "$preserved_adapter"
    else
      write_generic_adapter "$skill_name"
    fi
    if [ -n "$command_marker_name" ]; then
      write_codex_marker_block "$src" "$command_marker_name"
    fi
    echo ""
    echo ""
    strip_frontmatter "$src"
  } > "$target"

  GENERATED=$((GENERATED + 1))
  echo "Generated: ${skill_name}"
}

copy_support_assets() {
  local src_dir="$1"
  local target_dir="$2"

  [ -d "$src_dir" ] || return
  [ -d "$target_dir" ] || return

  # Support skills may ship helper modules/templates beside SKILL.md. Keep the
  # Codex mirror usable as a real skill package, not just a markdown body.
  find "$target_dir" -mindepth 1 -type f ! -name SKILL.md -delete 2>/dev/null || true

  while IFS= read -r rel; do
    rel="${rel#./}"
    mkdir -p "$target_dir/$(dirname "$rel")"
    cp "$src_dir/$rel" "$target_dir/$rel"
  done < <(cd "$src_dir" && find . -type f ! -name SKILL.md 2>/dev/null | sort)
}

GENERATED=0
SKIPPED=0
REPAIRED=0

for src in "$COMMANDS_DIR"/*.md; do
  [ -f "$src" ] || continue
  name="$(basename "$src" .md)"
  case "$name" in _*|*-insert) continue ;; esac
  if ! skill_selected "$name" "vg-${name}"; then
    continue
  fi

  target="$TARGET_DIR/vg-${name}/SKILL.md"
  description="$(extract_description "$src")"
  write_codex_skill "$src" "$target" "vg-${name}" "$description" "generic" "$name"
done

# Support skills invoked by workflow commands. Codex does not have Claude's
# Skill tool semantics, so install every helper skill as a first-class Codex
# skill with the same current runtime adapter contract as command skills.
for src in "$SHARED_SKILLS_DIR"/*/SKILL.md; do
  [ -f "$src" ] || continue
  support="$(basename "$(dirname "$src")")"
  if ! skill_selected "$support" "$support"; then
    continue
  fi
  target="$TARGET_DIR/$support/SKILL.md"
  description="$(extract_description "$src")"
  write_codex_skill "$src" "$target" "$support" "$description" "generic"
  copy_support_assets "$(dirname "$src")" "$(dirname "$target")"
done

echo ""
echo "Summary: ${GENERATED} generated, ${SKIPPED} skipped, ${REPAIRED} repaired (use --force to overwrite)"
