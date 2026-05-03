#!/usr/bin/env python3
"""Verify/repair VGFlow Playwright MCP worker configuration.

VG uses five named Playwright MCP workers (playwright1..playwright5) plus a
lock manager so parallel Claude/Codex sessions do not fight over one browser
profile. This validator is intentionally environment-level: it checks the user
CLI settings, not only files inside the project.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path
from typing import Any


WORKERS = range(1, 6)
MCP_PACKAGE = "@playwright/mcp@latest"


def _path_from_cli(value: str | None) -> Path:
    raw = value or os.environ.get("HOME") or os.environ.get("USERPROFILE") or str(Path.home())
    raw = os.path.expandvars(raw)

    # Windows Python invoked from Git Bash receives HOME like /c/Users/name.
    if os.name == "nt":
        m = re.match(r"^/([a-zA-Z])/(.*)$", raw)
        if m:
            raw = f"{m.group(1).upper()}:/{m.group(2)}"
        m = re.match(r"^/mnt/([a-zA-Z])/(.*)$", raw)
        if m:
            raw = f"{m.group(1).upper()}:/{m.group(2)}"
        m = re.match(r"^/cygdrive/([a-zA-Z])/(.*)$", raw)
        if m:
            raw = f"{m.group(1).upper()}:/{m.group(2)}"

    return Path(raw).expanduser()


def _display_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _same_path(left: str | None, right: Path) -> bool:
    if not left:
        return False
    left_path = _path_from_cli(left)
    right_path = right.expanduser()
    return os.path.normcase(os.path.normpath(str(left_path))) == os.path.normcase(
        os.path.normpath(str(right_path))
    )


def _playwright_entry(profile_dir: Path) -> dict[str, Any]:
    # --no-headless: keep browser window visible for human-watchable scans.
    # @playwright/mcp v0.0.71+ supports both default-headed and explicit
    # --no-headless; flag is durable across releases. Removed = scans go
    # invisible, breaking VG /vg:review headed-mode contract.
    return {
        "command": "npx",
        "args": [MCP_PACKAGE, "--no-headless", "--user-data-dir", _display_path(profile_dir)],
    }


def _user_data_dir(args: Any) -> str | None:
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        return None
    try:
        index = args.index("--user-data-dir")
    except ValueError:
        return None
    if index + 1 >= len(args):
        return None
    return args[index + 1]


def _valid_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("command") != "npx":
        return False
    args = entry.get("args")
    if not isinstance(args, list) or MCP_PACKAGE not in args:
        return False
    return _user_data_dir(args) is not None


def _valid_profile_entry(entry: Any, expected_profile: Path, allow_custom: bool) -> bool:
    if not _valid_entry(entry):
        return False
    if allow_custom:
        return True
    return _same_path(_user_data_dir(entry.get("args")), expected_profile)


def _json_payload(ok: bool, changed: bool, checks: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "ok": ok,
            "changed": changed,
            "checks": checks,
        },
        indent=2,
    )


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists() or path.stat().st_size == 0:
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "top-level JSON is not an object"
    return data, None


def check_claude(home: Path, repair: bool, allow_custom_profiles: bool) -> dict[str, Any]:
    path = home / ".claude" / "settings.json"
    data, error = _load_json(path)
    changed = False
    issues: list[str] = []

    if error:
        return {"name": "claude-settings", "path": _display_path(path), "ok": False, "changed": False, "issues": [error]}

    assert data is not None
    mcp_servers = data.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        if repair:
            data["mcpServers"] = {}
            mcp_servers = data["mcpServers"]
            changed = True
        else:
            issues.append("missing mcpServers object")
            mcp_servers = {}

    for i in WORKERS:
        key = f"playwright{i}"
        expected = _playwright_entry(home / ".claude" / f"playwright-profile-{i}")
        if not _valid_profile_entry(
            mcp_servers.get(key),
            home / ".claude" / f"playwright-profile-{i}",
            allow_custom_profiles,
        ):
            issues.append(f"{key} missing or invalid")
            if repair:
                mcp_servers[key] = expected
                changed = True

    dirs = [
        _user_data_dir(mcp_servers.get(f"playwright{i}", {}).get("args"))
        for i in WORKERS
        if _valid_entry(mcp_servers.get(f"playwright{i}"))
    ]
    if len(dirs) == 5 and len(set(dirs)) != 5:
        issues.append("playwright workers must use five unique --user-data-dir values")
        if repair:
            for i in WORKERS:
                mcp_servers[f"playwright{i}"] = _playwright_entry(home / ".claude" / f"playwright-profile-{i}")
            changed = True

    if repair and changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return check_claude(home, repair=False, allow_custom_profiles=allow_custom_profiles) | {"changed": True}

    ok = not issues
    return {"name": "claude-settings", "path": _display_path(path), "ok": ok, "changed": changed, "issues": issues}


def _parse_toml_strings(value: str) -> list[str]:
    strings: list[str] = []
    for match in re.finditer(r'"((?:\\.|[^"\\])*)"|\'([^\']*)\'', value):
        raw = match.group(1) if match.group(1) is not None else match.group(2)
        strings.append(raw.replace('\\"', '"').replace("\\\\", "\\"))
    return strings


def _parse_codex_sections(text: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    sections: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    current: str | None = None

    for line in text.splitlines():
        header = re.match(r"\s*\[([^\]]+)\]\s*(?:#.*)?$", line)
        if header:
            name = header.group(1).strip()
            match = re.fullmatch(r"mcp_servers\.playwright([1-5])", name)
            if match:
                key = f"playwright{match.group(1)}"
                if key in sections:
                    duplicates.append(key)
                sections.setdefault(key, {})
                current = key
            else:
                current = None
            continue

        if current is None:
            continue

        command = re.match(r'\s*command\s*=\s*["\']([^"\']+)["\']\s*(?:#.*)?$', line)
        if command:
            sections[current]["command"] = command.group(1)
            continue

        args = re.match(r"\s*args\s*=\s*\[(.*)\]\s*(?:#.*)?$", line)
        if args:
            sections[current]["args"] = _parse_toml_strings(args.group(1))

    return sections, duplicates


def _strip_codex_playwright_sections(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    i = 0
    while i < len(lines):
        if re.match(r"\s*\[mcp_servers\.playwright[1-5]\]\s*(?:#.*)?$", lines[i]):
            i += 1
            while i < len(lines) and not re.match(r"\s*\[[^\]]+\]\s*(?:#.*)?$", lines[i]):
                i += 1
            continue
        kept.append(lines[i])
        i += 1
    return "\n".join(kept).rstrip()


def _render_codex_sections(codex_home: Path) -> str:
    chunks: list[str] = []
    for i in WORKERS:
        profile = _display_path(codex_home / f"playwright-profile-{i}")
        chunks.append(
            "\n".join(
                [
                    f"[mcp_servers.playwright{i}]",
                    'command = "npx"',
                    f'args = ["{MCP_PACKAGE}", "--no-headless", "--user-data-dir", "{profile}"]',
                ]
            )
        )
    return "\n\n".join(chunks)


def check_codex(home: Path, repair: bool, allow_custom_profiles: bool) -> dict[str, Any]:
    codex_home_raw = os.environ.get("CODEX_HOME")
    codex_home = _path_from_cli(codex_home_raw) if codex_home_raw else home / ".codex"
    path = codex_home / "config.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    sections, duplicates = _parse_codex_sections(text)
    issues: list[str] = []

    for duplicate in duplicates:
        issues.append(f"{duplicate} has duplicate TOML sections")

    for i in WORKERS:
        key = f"playwright{i}"
        if not _valid_profile_entry(
            sections.get(key),
            codex_home / f"playwright-profile-{i}",
            allow_custom_profiles,
        ):
            issues.append(f"{key} missing or invalid")

    dirs = [
        _user_data_dir(sections.get(f"playwright{i}", {}).get("args"))
        for i in WORKERS
        if _valid_entry(sections.get(f"playwright{i}"))
    ]
    if len(dirs) == 5 and len(set(dirs)) != 5:
        issues.append("playwright workers must use five unique --user-data-dir values")

    changed = False
    if repair and issues:
        body = _strip_codex_playwright_sections(text)
        rendered = _render_codex_sections(codex_home)
        new_text = (body + "\n\n" + rendered + "\n") if body else (rendered + "\n")
        path.parent.mkdir(parents=True, exist_ok=True)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed = True
        repaired = check_codex(home, repair=False, allow_custom_profiles=allow_custom_profiles)
        repaired["changed"] = changed
        return repaired

    ok = not issues
    return {"name": "codex-settings", "path": _display_path(path), "ok": ok, "changed": changed, "issues": issues}


def check_lock_manager(home: Path, lock_source: Path | None, repair: bool) -> dict[str, Any]:
    path = home / ".claude" / "playwright-locks" / "playwright-lock.sh"
    issues: list[str] = []
    changed = False

    needs_copy = False
    if not path.exists():
        issues.append("lock manager missing")
        needs_copy = True
    elif "VG_PLAYWRIGHT_LOCK_DIR" not in path.read_text(encoding="utf-8", errors="ignore"):
        issues.append("lock manager is stale or hardcoded")
        needs_copy = True

    if repair and needs_copy and lock_source and lock_source.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lock_source, path)
        changed = True

    if path.exists():
        try:
            mode = path.stat().st_mode
            path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass

    if repair and changed:
        repaired = check_lock_manager(home, lock_source, repair=False)
        repaired["changed"] = True
        return repaired

    if not path.exists() and repair and (not lock_source or not lock_source.exists()):
        issues.append("lock source unavailable")

    ok = path.exists() and not issues
    return {"name": "playwright-lock-manager", "path": _display_path(path), "ok": ok, "changed": changed, "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair", action="store_true", help="Create or repair missing/invalid MCP entries.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable status.")
    parser.add_argument("--quiet", action="store_true", help="Suppress human-readable output.")
    parser.add_argument("--home", help="Override user home directory. Defaults to HOME/USERPROFILE.")
    parser.add_argument("--lock-source", help="Source playwright-lock.sh to copy during --repair.")
    parser.add_argument("--phase", help=argparse.SUPPRESS)
    parser.add_argument(
        "--allow-custom-profile-dirs",
        action="store_true",
        default=os.environ.get("VG_PLAYWRIGHT_MCP_ALLOW_CUSTOM_DIRS", "").lower()
        in {"1", "true", "yes"},
        help="Accept existing profile dirs outside the current CLI home.",
    )
    args = parser.parse_args(argv)

    home = _path_from_cli(args.home)
    lock_source = Path(args.lock_source) if args.lock_source else None

    checks = [
        check_claude(home, args.repair, args.allow_custom_profile_dirs),
        check_codex(home, args.repair, args.allow_custom_profile_dirs),
        check_lock_manager(home, lock_source, args.repair),
    ]
    ok = all(check["ok"] for check in checks)
    changed = any(check["changed"] for check in checks)

    if args.phase is not None and not args.json and not args.quiet:
        print(
            json.dumps(
                {
                    "validator": "verify-playwright-mcp-config",
                    "verdict": "PASS" if ok else "BLOCK",
                    "ok": ok,
                    "changed": changed,
                    "checks": checks,
                },
                indent=2,
            )
        )
    elif args.json:
        print(_json_payload(ok, changed, checks))
    elif not args.quiet:
        for check in checks:
            status = "OK" if check["ok"] else "FAIL"
            suffix = " (repaired)" if check["changed"] else ""
            print(f"{status}: {check['name']} -> {check['path']}{suffix}")
            for issue in check["issues"]:
                print(f"  - {issue}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
