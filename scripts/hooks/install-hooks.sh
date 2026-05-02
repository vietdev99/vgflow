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

python3 - "$target" "$HOOKS_DIR" <<'PY'
import json, os, sys
from pathlib import Path

target = Path(sys.argv[1])
hooks_dir = sys.argv[2]

if target.exists():
    settings = json.loads(target.read_text())
else:
    settings = {}
settings.setdefault("hooks", {})

VG_ENTRIES = {
    "UserPromptSubmit": [{"matcher": "", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-user-prompt-submit.sh"}]}],
    "SessionStart": [{"matcher": "startup|resume|clear|compact", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-session-start.sh"}]}],
    "PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-pre-tool-use-bash.sh"}]},
        {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-pre-tool-use-write.sh"}]},
        {"matcher": "Agent", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-pre-tool-use-agent.sh"}]},
    ],
    "PostToolUse": [{"matcher": "TodoWrite", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-post-tool-use-todowrite.sh"}]}],
    "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": f"bash {hooks_dir}/vg-stop.sh"}]}],
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
