#!/usr/bin/env python3
"""VGFlow project uninstall helper.

Removes VGFlow-owned workflow surfaces from a target project while preserving
project source code. Default is dry-run; pass --apply to mutate.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

LEGACY_HOOK_SCRIPTS = (
    "vg-verify-claim.py",
    "vg-edit-warn.py",
    "vg-entry-hook.py",
    "vg-step-tracker.py",
    "vg-agent-spawn-guard.py",
)

HOOK_SCRIPT_MARKERS = (
    "vg-run-bash-hook.py",
    "vg-user-prompt-submit.sh",
    "vg-session-start.sh",
    "vg-pre-tool-use-bash.sh",
    "vg-pre-tool-use-write.sh",
    "vg-pre-tool-use-agent.sh",
    "vg-post-tool-use-todowrite.sh",
    "vg-stop.sh",
    ".claude/scripts/hooks/",
    ".claude/scripts/codex-hooks/",
    "VG_RUNTIME=codex",
)

CLAUDE_PATHS = (
    ".claude/commands/vg",
    ".claude/scripts",
    ".claude/schemas",
    ".claude/templates/vg",
    ".claude/catalog",
    ".claude/vgflow-ancestor",
    ".claude/vgflow-patches",
    ".claude/VGFLOW-VERSION",
)

CODEX_PATHS = (
    ".codex/config.template.toml",
)

CODEX_SKILL_PREFIXES = (
    "vg-",
    "flow-",
    "test-",
)

CODEX_SKILL_EXACT = {
    "api-contract",
    "sandbox-test",
    "write-test-spec",
}

CLAUDE_SKILL_PREFIXES = CODEX_SKILL_PREFIXES
CLAUDE_SKILL_EXACT = CODEX_SKILL_EXACT

CODEX_AGENT_PREFIXES = (
    "vgflow-",
)

ROOT_FILES = (
    "vg-ext",
)

LEGACY_CONFIG = ".claude/vg.config.md"
MODERN_CONFIG = ".vg/config.md"


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _is_vg_hook_command(command: str) -> bool:
    return any(marker in command for marker in (*LEGACY_HOOK_SCRIPTS, *HOOK_SCRIPT_MARKERS))


def prune_hooks_file(settings_path: Path, *, apply: bool) -> bool:
    """Remove VG-owned hooks from one Claude/Codex settings file.

    Returns True when the file would change.
    """
    data = _read_json(settings_path)
    if not isinstance(data, dict):
        return False
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False

    changed = False
    new_hooks: dict = {}
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            new_hooks[event] = entries
            continue
        kept_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                kept_entries.append(entry)
                continue
            hook_list = entry.get("hooks")
            if not isinstance(hook_list, list):
                kept_entries.append(entry)
                continue
            kept_hooks = []
            for hook in hook_list:
                command = str(hook.get("command", "")) if isinstance(hook, dict) else ""
                if _is_vg_hook_command(command):
                    changed = True
                else:
                    kept_hooks.append(hook)
            if kept_hooks:
                updated = dict(entry)
                updated["hooks"] = kept_hooks
                kept_entries.append(updated)
            elif hook_list:
                changed = True
        if kept_entries:
            new_hooks[event] = kept_entries
        elif entries:
            changed = True

    if changed and apply:
        if new_hooks:
            data["hooks"] = new_hooks
        else:
            data.pop("hooks", None)
        _write_json(settings_path, data)
    return changed


def _remove_agent_entries_from_toml(config_path: Path, *, apply: bool) -> bool:
    if not config_path.exists():
        return False
    lines = config_path.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    changed = False
    skip_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[agents.vgflow-"):
            skip_block = True
            changed = True
            continue
        if skip_block and stripped.startswith("[") and stripped.endswith("]"):
            skip_block = False
        if skip_block:
            continue
        if "codex_hooks" in stripped and "vg" in stripped.lower():
            changed = True
            continue
        out.append(line)
    if changed and apply:
        text = "\n".join(out).strip()
        if text:
            config_path.write_text(text + "\n", encoding="utf-8")
        else:
            config_path.unlink()
    return changed


def _same_file_bytes(left: Path, right: Path) -> bool:
    try:
        return left.read_bytes() == right.read_bytes()
    except OSError:
        return False


def _plan_config_migration(root: Path, purge_state: bool) -> tuple[str, Path | None, Path | None]:
    """Plan legacy config migration for global-only project cleanup."""
    if purge_state:
        return ("none", None, None)

    legacy = root / LEGACY_CONFIG
    modern = root / MODERN_CONFIG
    if not legacy.exists():
        return ("none", None, None)
    if not modern.exists():
        return ("migrate", legacy, modern)
    if _same_file_bytes(legacy, modern):
        return ("remove_legacy", legacy, modern)
    return ("conflict", legacy, modern)


def _collect_paths(root: Path, purge_state: bool, extra_paths: Iterable[Path] = ()) -> list[Path]:
    paths = [root / rel for rel in (*CLAUDE_PATHS, *CODEX_PATHS, *ROOT_FILES)]
    paths.extend(extra_paths)

    claude_skills = root / ".claude" / "skills"
    if claude_skills.exists():
        for child in claude_skills.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if name in CLAUDE_SKILL_EXACT or any(name.startswith(p) for p in CLAUDE_SKILL_PREFIXES):
                paths.append(child)

    claude_agents = root / ".claude" / "agents"
    if claude_agents.exists():
        paths.extend(claude_agents.glob("vg-*.md"))
        paths.extend(claude_agents.glob("vgflow-*.md"))

    codex_skills = root / ".codex" / "skills"
    if codex_skills.exists():
        for child in codex_skills.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if name in CODEX_SKILL_EXACT or any(name.startswith(p) for p in CODEX_SKILL_PREFIXES):
                paths.append(child)

    codex_agents = root / ".codex" / "agents"
    if codex_agents.exists():
        for child in codex_agents.iterdir():
            if child.is_file() and any(child.name.startswith(p) for p in CODEX_AGENT_PREFIXES):
                paths.append(child)

    if purge_state:
        paths.extend(
            [
                root / ".vg",
                root / ".planning",
            ]
        )

    # Keep stable order and avoid nested duplicate removals.
    # Issue #188 (v4.51.2): also filter paths outside root. p.resolve()
    # follows symlinks; if .claude/scripts is symlinked to a sibling
    # project clone, resolve() returns the target path which is OUTSIDE
    # root → downstream relative_to() raises ValueError. Defensive filter
    # at collection time (in addition to per-path guard in _backup_then_remove).
    root_resolved = root.resolve()
    unique = sorted({p.resolve() for p in paths if p.exists()}, key=lambda p: len(p.parts))
    filtered: list[Path] = []
    for path in unique:
        try:
            path.relative_to(root_resolved)
        except ValueError:
            print(
                f"⚠ vg-uninstall: skip path outside root: {path} (likely symlink to sibling clone)",
                file=sys.stderr,
            )
            continue
        if any(parent in path.parents for parent in filtered):
            continue
        filtered.append(path)
    return filtered


def _backup_then_remove(path: Path, root: Path, backup_root: Path) -> None:
    # Issue #188 fix (v4.51.2): guard sibling-project leak. When user has
    # multiple VGFlow clones (e.g. ~/Code/foo + ~/Code/vgflow-bugfix), the
    # removal candidate list may include paths OUTSIDE `root`. relative_to()
    # raises ValueError on those — crashes mid-cleanup, exit !=0 confuses
    # downstream gates. Skip + warn instead.
    try:
        rel = path.relative_to(root)
    except ValueError:
        print(
            f"⚠ vg-uninstall: skip path outside root: {path} (root={root})",
            file=sys.stderr,
        )
        return
    backup_path = backup_root / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(backup_path))


def _prune_empty_dirs(paths: Iterable[Path]) -> None:
    for path in sorted({p for p in paths}, key=lambda p: len(p.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass


def cmd_prune_hooks(args: argparse.Namespace) -> int:
    changed = prune_hooks_file(Path(args.settings), apply=args.apply)
    print("changed" if changed else "clean")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not root.exists():
        print(f"root not found: {root}")
        return 2

    changed_hooks = []
    for rel in (
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".codex/hooks.json",
    ):
        path = root / rel
        if path.exists() and prune_hooks_file(path, apply=args.apply):
            changed_hooks.append(path)

    changed_toml = []
    for rel in (".codex/config.toml",):
        path = root / rel
        if path.exists() and _remove_agent_entries_from_toml(path, apply=args.apply):
            changed_toml.append(path)

    config_action, legacy_config, modern_config = _plan_config_migration(root, args.purge_state)
    extra_remove_paths: list[Path] = []
    if config_action in {"migrate", "remove_legacy"} and legacy_config is not None:
        extra_remove_paths.append(legacy_config)
    remove_paths = _collect_paths(root, args.purge_state, extra_remove_paths)
    backup_root = root / ".vgflow-uninstall-backup" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print("VGFlow uninstall")
    print(f"  root: {root}")
    print(f"  mode: {'apply' if args.apply else 'dry-run'}")
    if args.apply and remove_paths:
        print(f"  backup: {backup_root}")
    print("")

    for path in changed_hooks:
        print(f"PRUNE hooks: {path}")
    for path in changed_toml:
        print(f"PRUNE codex config: {path}")
    if config_action == "migrate" and legacy_config is not None and modern_config is not None:
        print(f"MIGRATE config: {legacy_config} -> {modern_config}")
    elif config_action == "remove_legacy" and legacy_config is not None and modern_config is not None:
        print(f"REMOVE duplicate legacy config: {legacy_config} (canonical: {modern_config})")
    elif config_action == "conflict" and legacy_config is not None and modern_config is not None:
        print(f"KEEP legacy config: {legacy_config} differs from {modern_config}")
    for path in remove_paths:
        print(f"REMOVE: {path}")

    if not args.apply:
        print("")
        print("Dry-run only. Re-run with --apply to remove. Add --purge-state to remove .vg/.planning data.")
        return 0

    if config_action == "migrate" and legacy_config is not None and modern_config is not None:
        modern_config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_config, modern_config)

    for path in remove_paths:
        if path.exists():
            _backup_then_remove(path, root, backup_root)

    _prune_empty_dirs(
        [
            root / ".claude" / "agents",
            root / ".claude",
            root / ".codex" / "skills",
            root / ".codex" / "agents",
            root / ".codex",
        ]
    )
    print("")
    print("Uninstall applied. Removed VGFlow-owned files were moved to backup.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="vg-uninstall")
    sub = parser.add_subparsers(dest="cmd")

    prune = sub.add_parser("prune-hooks", help="remove VG-owned hook entries from one settings JSON")
    prune.add_argument("--settings", required=True)
    prune.add_argument("--apply", action="store_true")
    prune.set_defaults(func=cmd_prune_hooks)

    parser.add_argument("--root", default=".", help="project root")
    parser.add_argument("--apply", action="store_true", help="mutate filesystem; default is dry-run")
    parser.add_argument("--purge-state", action="store_true", help="also remove .vg and .planning project state")

    args = parser.parse_args()
    if hasattr(args, "func"):
        return args.func(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
