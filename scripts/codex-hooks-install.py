#!/usr/bin/env python3
"""Install VGFlow Codex hooks into global ~/.codex config."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

VG_HOOK_SCRIPT_MARKERS = (
    "vg-entry-hook.py",
    "vg-verify-claim.py",
    "vg-step-tracker.py",
    "vg-edit-warn.py",
    "codex-hooks/vg-user-prompt-submit.py",
    "codex-hooks/vg-pre-tool-use-bash.py",
    "codex-hooks/vg-pre-tool-use-apply-patch.py",
    "codex-hooks/vg-post-tool-use-bash.py",
    "codex-hooks/vg-stop.py",
)


def _detect_python_cmd() -> str:
    """Pick the python interpreter name to bake into hook commands."""
    import shutil
    if shutil.which("python3"):
        return "python3"
    if shutil.which("python"):
        return "python"
    return "python3"


PYTHON_CMD = _detect_python_cmd()


def _default_vg_home() -> Path:
    env = os.environ.get("VG_HOME")
    if env:
        return Path(env).expanduser().absolute()
    # scripts/codex-hooks-install.py -> VGFlow repo/package root.
    return Path(__file__).resolve().parents[1]


def _command(vg_home: Path, script_name: str) -> str:
    script = (vg_home / "scripts" / script_name).absolute()
    # Use absolute global paths. Project-local .codex/.claude VG files are
    # pruned in global-only mode, so hook commands must not depend on cwd.
    return f'{PYTHON_CMD} "{script}"'


def desired_hooks(vg_home: Path) -> dict[str, Any]:
    return {
        "hooks": {
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": _command(vg_home, "codex-hooks/vg-user-prompt-submit.py"),
                            "timeout": 30,
                            "statusMessage": "VGFlow: starting run",
                        }
                    ]
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": _command(vg_home, "codex-hooks/vg-pre-tool-use-bash.py"),
                            "timeout": 30,
                            "statusMessage": "VGFlow: checking Bash gate",
                        }
                    ],
                },
                {
                    "matcher": "^(apply_patch|Edit|Write)$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": _command(vg_home, "codex-hooks/vg-pre-tool-use-apply-patch.py"),
                            "timeout": 30,
                            "statusMessage": "VGFlow: checking protected paths",
                        }
                    ],
                },
            ],
            "PostToolUse": [
                {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": _command(vg_home, "codex-hooks/vg-post-tool-use-bash.py"),
                            "timeout": 30,
                            "statusMessage": "VGFlow: tracking step marker",
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": _command(vg_home, "codex-hooks/vg-stop.py"),
                            "timeout": 90,
                            "statusMessage": "VGFlow: verifying runtime contract",
                        }
                    ]
                }
            ],
        }
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: invalid JSON in {path}: {exc}") from exc


def _is_vg_hook(hook: dict[str, Any]) -> bool:
    command = str(hook.get("command") or "").replace("\\", "/")
    return any(marker in command for marker in VG_HOOK_SCRIPT_MARKERS)


def _strip_vg_hooks_from_group(group: dict[str, Any]) -> dict[str, Any] | None:
    hooks = [hook for hook in group.get("hooks", []) if not _is_vg_hook(hook)]
    if not hooks:
        return None
    copied = dict(group)
    copied["hooks"] = hooks
    return copied


def merge_hooks(existing: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    merged_hooks: dict[str, Any] = {}
    existing_hooks = existing.get("hooks", {})
    if isinstance(existing_hooks, dict):
        for event, groups in existing_hooks.items():
            if not isinstance(groups, list):
                merged_hooks[event] = groups
                continue
            kept = []
            for group in groups:
                if not isinstance(group, dict):
                    kept.append(group)
                    continue
                stripped = _strip_vg_hooks_from_group(group)
                if stripped is not None:
                    kept.append(stripped)
            if kept:
                merged_hooks[event] = kept

    for event, groups in desired.get("hooks", {}).items():
        merged_hooks.setdefault(event, [])
        merged_hooks[event].extend(groups)

    merged["hooks"] = merged_hooks
    return merged


def ensure_codex_hooks_feature_text(text: str) -> str:
    if not text.strip():
        return "[features]\ncodex_hooks = true\n"

    lines = text.splitlines()
    section_re = re.compile(r"^\s*\[([^\]]+)\]\s*$")
    features_start: int | None = None
    features_end = len(lines)
    for idx, line in enumerate(lines):
        match = section_re.match(line)
        if not match:
            continue
        if match.group(1).strip() == "features":
            features_start = idx
            features_end = len(lines)
            continue
        if features_start is not None and idx > features_start:
            features_end = idx
            break

    if features_start is None:
        suffix = "" if text.endswith("\n") else "\n"
        return f"{text}{suffix}\n[features]\ncodex_hooks = true\n"

    key_re = re.compile(r"^(\s*codex_hooks\s*=\s*)(.+?)(\s*(?:#.*)?)$")
    for idx in range(features_start + 1, features_end):
        match = key_re.match(lines[idx])
        if match:
            lines[idx] = f"{match.group(1)}true{match.group(3)}"
            return "\n".join(lines) + "\n"

    lines.insert(features_start + 1, "codex_hooks = true")
    return "\n".join(lines) + "\n"


def _write_if_changed(path: Path, text: str) -> bool:
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def install(codex_home: Path, *, vg_home: Path, check: bool = False) -> bool:
    codex_dir = codex_home
    hooks_path = codex_dir / "hooks.json"
    config_path = codex_dir / "config.toml"

    existing_hooks = _load_json(hooks_path)
    merged_hooks = merge_hooks(existing_hooks, desired_hooks(vg_home))
    hooks_text = json.dumps(merged_hooks, indent=2, sort_keys=True) + "\n"

    config_old = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    config_text = ensure_codex_hooks_feature_text(config_old)

    hooks_changed = (hooks_path.read_text(encoding="utf-8") if hooks_path.exists() else "") != hooks_text
    config_changed = config_old != config_text
    changed = hooks_changed or config_changed
    if check:
        return changed

    if hooks_changed:
        _write_if_changed(hooks_path, hooks_text)
    if config_changed:
        _write_if_changed(config_path, config_text)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--codex-home",
        default=str(Path.home() / ".codex"),
        help="Codex config directory to update (default: ~/.codex)",
    )
    parser.add_argument(
        "--vg-home",
        default=str(_default_vg_home()),
        help="VGFlow global root containing scripts/codex-hooks",
    )
    parser.add_argument(
        "--root",
        help="deprecated project root; writes hooks under <root>/.codex",
    )
    parser.add_argument("--check", action="store_true", help="exit 1 if hooks/config need repair")
    args = parser.parse_args()

    if args.root:
        codex_home = Path(args.root).expanduser().absolute() / ".codex"
    else:
        codex_home = Path(args.codex_home).expanduser().absolute()
    vg_home = Path(args.vg_home).expanduser().absolute()
    changed = install(codex_home, vg_home=vg_home, check=args.check)
    if args.check:
        return 1 if changed else 0
    if changed:
        print(f"OK: Codex hooks installed/repaired in {codex_home}/hooks.json and {codex_home}/config.toml")
    else:
        print("OK: Codex hooks already in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
