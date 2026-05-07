#!/usr/bin/env bash
# Idempotently merge VG hook entries into target Claude Code settings.json.
# Preserves user's existing hook entries.

set -euo pipefail

target=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target) target="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$target" ]; then
  echo "usage: install-hooks.sh --target <path-to-settings.json>" >&2
  exit 1
fi

# Plugin root: directory containing this script's parent (e.g., scripts/hooks/.. = scripts/..).
PLUGIN_ROOT="${VG_PLUGIN_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/scripts/hooks"

# Hook path template emitted into settings.json. Set VG_HOOKS_PATH_MODE=absolute
# to use legacy behavior (bake $HOOKS_DIR absolute path at install time —
# breaks across machines). Default `placeholder` writes
# `bash "${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/<name>"` so Claude Code
# expands per-machine at execution time. Issue #105 followup: PR #104 shipped
# .claude/settings.json baked with one developer's macOS path, breaking every
# other machine; placeholder mode prevents that recurrence.
HOOKS_PATH_MODE="${VG_HOOKS_PATH_MODE:-placeholder}"
PYTHON_CMD="${PYTHON_BIN:-}"
if [ -z "$PYTHON_CMD" ]; then
  for cand in python3 python py; do
    if command -v "$cand" >/dev/null 2>&1; then
      PYTHON_CMD="$cand"
      break
    fi
  done
fi
PYTHON_CMD="${PYTHON_CMD:-python3}"

python3 - "$target" "$HOOKS_DIR" "$HOOKS_PATH_MODE" "$PYTHON_CMD" <<'PY'
import json, os, shlex, sys
from pathlib import Path

target = Path(sys.argv[1])
hooks_dir = sys.argv[2]
mode = sys.argv[3]
python_cmd = sys.argv[4]

if target.exists():
    settings = json.loads(target.read_text())
else:
    settings = {}
settings.setdefault("hooks", {})

# Path emission strategy:
#   placeholder (default) — emit ${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/<name>
#                           wrapped in double quotes so the shell expands the
#                           env var at execution time. Survives moves between
#                           machines, OS, and project paths with spaces.
#   absolute              — bake hooks_dir absolute path at install time
#                           (legacy/escape hatch via VG_HOOKS_PATH_MODE=absolute).
def _cmd(script_name: str) -> str:
    runner_name = "vg-run-bash-hook.py"
    # Issue #129: on Windows, Claude Code spawns hooks via `bash <argv>`
    # without `-c`. Bash treats argv[0] as a script file path. When argv[0]
    # is "python" / "python3" (binary), bash opens python.exe, reads PE
    # header bytes, and rejects with "cannot execute binary file" — every
    # hook fails on the first message after install. Empirically verified
    # on find_location + super_com_hub, 2026-05-07; substituting `python3`
    # → `python` does NOT help (both are binaries).
    #
    # On Windows, emit the .sh path directly. argv[0] becomes a shell
    # script — bash reads its shebang and runs it. The python wrapper's
    # WSL-bash protection is sacrificed; modern Claude Code on Windows
    # already prefers Git Bash, and users with WSL-only bash are rare.
    if os.name == "nt":
        if mode == "absolute":
            return shlex.quote(f"{hooks_dir}/{script_name}")
        return f'"${{CLAUDE_PROJECT_DIR}}/.claude/scripts/hooks/{script_name}"'

    if mode == "absolute":
        # CRITICAL: hooks_dir may contain spaces (e.g., "Vibe Code") — shell word-splits
        # unquoted command. Use shlex.quote to wrap each path.
        return (
            f"{python_cmd} {shlex.quote(f'{hooks_dir}/{runner_name}')} "
            f"{shlex.quote(f'{hooks_dir}/{script_name}')}"
        )
    return (
        f'{python_cmd} "${{CLAUDE_PROJECT_DIR}}/.claude/scripts/hooks/{runner_name}" '
        f'"${{CLAUDE_PROJECT_DIR}}/.claude/scripts/hooks/{script_name}"'
    )

VG_ENTRIES = {
    "UserPromptSubmit": [{"matcher": "", "hooks": [{"type": "command", "command": _cmd("vg-user-prompt-submit.sh")}]}],
    "SessionStart": [{"matcher": "startup|resume|clear|compact", "hooks": [{"type": "command", "command": _cmd("vg-session-start.sh")}]}],
    "PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": _cmd("vg-pre-tool-use-bash.sh")}]},
        {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": _cmd("vg-pre-tool-use-write.sh")}]},
        {"matcher": "Agent", "hooks": [{"type": "command", "command": _cmd("vg-pre-tool-use-agent.sh")}]},
    ],
    "PostToolUse": [{"matcher": "TodoWrite|TaskCreate|TaskUpdate", "hooks": [{"type": "command", "command": _cmd("vg-post-tool-use-todowrite.sh")}]}],
    "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": _cmd("vg-stop.sh")}]}],
}

def is_vg_hook(entry):
    return any("vg-" in h.get("command", "") for h in entry.get("hooks", []))

for event, vg_entries in VG_ENTRIES.items():
    existing = settings["hooks"].setdefault(event, [])
    # Drop any prior VG entries (signature: contains "vg-") then re-add fresh.
    existing[:] = [e for e in existing if not is_vg_hook(e)]
    existing.extend(vg_entries)

target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(settings, indent=2, sort_keys=True))
print(f"installed VG hooks into {target}")
PY
