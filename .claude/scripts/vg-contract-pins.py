#!/usr/bin/env python3
"""
vg-contract-pins.py — Per-phase runtime_contract pin manager (Tier B).

Problem closed
==============
Every VG harness upgrade can change the runtime_contract of a skill
(must_touch_markers, must_emit_telemetry). Phases that already ran the
OLD contract then fail validation because /vg:accept enforces the
CURRENT skill's contract — a moving target.

Solution: lock the contract per (phase, command) at first execution.
Subsequent runs validate against the pinned contract, not the current
skill body. New phases auto-pick the current contract.

File: .vg/phases/{phase}/.contract-pins.json
Schema:
{
  "schema_version": 1,
  "pinned_at": "<ISO8601>",
  "harness_version": "<VGFLOW-VERSION>",
  "git_sha": "<short head sha>",
  "commands": {
    "vg:scope": {
      "must_touch_markers": [...],
      "must_emit_telemetry": [...],
      "skill_sha256": "<hex digest of post-frontmatter skill body>",
      "pinned_at": "<ISO8601>"
    },
    ...
  }
}

CLI
===
    vg-contract-pins.py status {phase}
    vg-contract-pins.py write {phase} [--command vg:X]   # all commands if no --command
    vg-contract-pins.py read {phase} --command vg:X      # JSON to stdout
    vg-contract-pins.py extract --command vg:X           # current skill contract (no pin write)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands" / "vg"
PHASES_DIR = REPO_ROOT / ".vg" / "phases"
VGFLOW_VERSION_FILE = REPO_ROOT / ".claude" / "VGFLOW-VERSION"

PIN_FILENAME = ".contract-pins.json"
SCHEMA_VERSION = 1

TRACKED_COMMANDS = ("scope", "blueprint", "build", "review", "test", "accept")

# Frontmatter delimiters
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
STEP_NAME_RE = re.compile(r'<step name="([A-Za-z0-9_][A-Za-z0-9_-]*)"')

# YAML extraction for runtime_contract block — simple regex parser since the
# block has predictable shape (no nested complex YAML).
RUNTIME_CONTRACT_RE = re.compile(
    r"^runtime_contract:\s*\n((?:[ \t].*\n)+)", re.MULTILINE
)
# `must_touch_markers:` block continues until a sibling top-level key (4 spaces +
# `key:` at indent <= 4) or end of frontmatter.
MUST_TOUCH_BLOCK_RE = re.compile(
    r"^\s*must_touch_markers:\s*\n((?:[ \t].*\n)+?)"
    r"(?=^[ \t]{0,4}[a-z_]+:|\Z)",
    re.MULTILINE,
)
MUST_EMIT_BLOCK_RE = re.compile(
    r"^\s*must_emit_telemetry:\s*\n((?:[ \t].*\n)+?)"
    r"(?=^[ \t]{0,4}[a-z_]+:|\Z)",
    re.MULTILINE,
)
# Top-level list-item line: `- value` OR `- "value"` OR `- name: value` /
# `- event_type: value`. Continuation lines (e.g. `  severity: warn`) start
# with whitespace + a key without `-`, so we filter those out.
LIST_ITEM_LINE_RE = re.compile(r"^\s*-\s+(.*?)\s*$")
KEY_VALUE_RE = re.compile(r"^([a-z_]+):\s*\"?([^\"#\n]+?)\"?\s*(?:#.*)?$")


# ---------------------------------------------------------------------------
# Skill parsing
# ---------------------------------------------------------------------------


def _read_skill(command: str) -> tuple[str, str] | None:
    """Return (frontmatter_yaml, body_post_frontmatter) for a skill, or None
    if the file is missing. Frontmatter is guaranteed to end with `\\n` so
    line-anchored regexes (e.g. `(?:[ \\t].*\\n)+`) match the last line.
    """
    skill = COMMANDS_DIR / f"{command}.md"
    if not skill.exists():
        return None
    text = skill.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        return ("", text)
    fm = m.group(1)
    if not fm.endswith("\n"):
        fm += "\n"
    return (fm, text[m.end():])


def _parse_yaml_list_value(block_text: str, value_key: str) -> list[Any]:
    """Parse a YAML list under a single key, accepting both shorthand
    (`- "marker"`) and structured (`- name: "marker" / severity: warn`)
    forms. `value_key` is which field name to extract from structured
    items (e.g. "name" for must_touch_markers, "event_type" for telemetry).

    Returns ordered, deduped list. Plain items stay strings; structured items
    with extra keys stay dicts so `severity`, `required_unless_flag`, and other
    non-blocking contract metadata survive pinning.
    """
    out: list[Any] = []
    seen: set[str] = set()
    pending: dict[str, str] | None = None

    def _flush() -> None:
        nonlocal pending
        if pending is None:
            return
        value = pending.get("__shorthand__") or pending.get(value_key)
        if value and value not in seen:
            seen.add(value)
            if "__shorthand__" in pending:
                out.append(value)
            else:
                extra = {k: v for k, v in pending.items() if k != value_key}
                out.append(dict(pending) if extra else value)
        pending = None

    for line in block_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        item_match = LIST_ITEM_LINE_RE.match(line)
        if item_match:
            _flush()  # close previous item
            pending = {}
            content = item_match.group(1).strip()
            if not content:
                continue
            # Structured `- key: value`
            kv = KEY_VALUE_RE.match(content)
            if kv:
                pending[kv.group(1)] = kv.group(2).strip()
            else:
                # Shorthand: `- "marker"` or `- marker`
                pending["__shorthand__"] = content.strip('"').strip("'")
        else:
            # Continuation line: `  severity: warn`, `  phase: ...`
            kv = KEY_VALUE_RE.match(line.strip())
            if kv and pending is not None:
                pending[kv.group(1)] = kv.group(2).strip()
    _flush()
    return out


def _parse_must_touch_markers(frontmatter: str, body: str) -> list[Any]:
    """Extract must_touch_markers list, falling back to all `<step>` names
    from the body when the frontmatter doesn't enumerate them.
    """
    rc = RUNTIME_CONTRACT_RE.search(frontmatter)
    if rc:
        mt = MUST_TOUCH_BLOCK_RE.search(rc.group(1))
        if mt:
            items = _parse_yaml_list_value(mt.group(1), "name")
            if items:
                return items
    # Fallback: every <step> in the body. Preserve order, dedupe.
    seen: set[str] = set()
    ordered: list[str] = []
    for m in STEP_NAME_RE.finditer(body):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _parse_must_emit_telemetry(frontmatter: str) -> list[Any]:
    """Extract must_emit_telemetry event_type list from frontmatter."""
    rc = RUNTIME_CONTRACT_RE.search(frontmatter)
    if not rc:
        return []
    me = MUST_EMIT_BLOCK_RE.search(rc.group(1))
    if not me:
        return []
    return _parse_yaml_list_value(me.group(1), "event_type")


def extract_contract_for_command(command: str) -> dict[str, Any] | None:
    """Snapshot the current skill's contract block. Returns None if skill
    file is missing.
    """
    skill_short = command.replace("vg:", "")
    parts = _read_skill(skill_short)
    if parts is None:
        return None
    frontmatter, body = parts
    skill_text = (COMMANDS_DIR / f"{skill_short}.md").read_text(encoding="utf-8")
    sha = hashlib.sha256(skill_text.encode("utf-8")).hexdigest()
    return {
        "must_touch_markers": _parse_must_touch_markers(frontmatter, body),
        "must_emit_telemetry": _parse_must_emit_telemetry(frontmatter),
        "skill_sha256": sha,
        "pinned_at": _iso_now(),
    }


# ---------------------------------------------------------------------------
# Pin file IO
# ---------------------------------------------------------------------------


def _git_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _harness_version() -> str:
    if VGFLOW_VERSION_FILE.exists():
        return VGFLOW_VERSION_FILE.read_text(encoding="utf-8").strip()
    return "unknown"


def _resolve_phase_dir(phase: str) -> Path | None:
    if not PHASES_DIR.is_dir():
        return None
    direct = PHASES_DIR / phase
    if direct.is_dir():
        return direct
    matches = [p for p in PHASES_DIR.iterdir()
               if p.is_dir() and (p.name == phase
                                  or p.name.startswith(phase + "-"))]
    if len(matches) == 1:
        return matches[0]
    return None


def pin_path(phase_dir: Path) -> Path:
    return phase_dir / PIN_FILENAME


def read_pin(phase_dir: Path) -> dict[str, Any] | None:
    pin = pin_path(phase_dir)
    if not pin.exists():
        return None
    try:
        return json.loads(pin.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def get_pinned_contract(phase_dir: Path, command: str) -> dict[str, Any] | None:
    """Return the pinned contract for (phase, command), or None if no pin
    exists for this command.
    """
    data = read_pin(phase_dir)
    if not data:
        return None
    return data.get("commands", {}).get(command)


def write_pin(
    phase_dir: Path,
    *,
    command: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write or update the pin file. If `command` is None, pin all tracked
    commands. Existing per-command pins are preserved unless `overwrite=True`.
    """
    phase_dir.mkdir(parents=True, exist_ok=True)
    existing = read_pin(phase_dir) or {
        "schema_version": SCHEMA_VERSION,
        "pinned_at": _iso_now(),
        "harness_version": _harness_version(),
        "git_sha": _git_sha(),
        "commands": {},
    }

    targets: list[str] = []
    if command:
        targets = [command]
    else:
        targets = [f"vg:{c}" for c in TRACKED_COMMANDS]

    for cmd in targets:
        if cmd in existing["commands"] and not overwrite:
            continue
        contract = extract_contract_for_command(cmd)
        if contract is None:
            continue
        existing["commands"][cmd] = contract

    pin_path(phase_dir).write_text(
        json.dumps(existing, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return existing


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_extract(args: argparse.Namespace) -> int:
    contract = extract_contract_for_command(args.command)
    if contract is None:
        print(f"\033[38;5;208mUnknown command or missing skill: {args.command}\033[0m",
              file=sys.stderr)
        return 2
    print(json.dumps(contract, indent=2))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    phase_dir = _resolve_phase_dir(args.phase)
    if not phase_dir:
        print(f"\033[38;5;208mPhase not found: {args.phase}\033[0m", file=sys.stderr)
        return 2
    pin = read_pin(phase_dir)
    if pin is None:
        print(f"no-pin   {phase_dir.name}")
        return 1
    cmds = sorted(pin.get("commands", {}).keys())
    print(f"pinned   {phase_dir.name}  harness={pin.get('harness_version')}  "
          f"commands={','.join(cmds) or 'none'}")
    return 0


def _cmd_write(args: argparse.Namespace) -> int:
    phase_dir = _resolve_phase_dir(args.phase)
    if not phase_dir:
        print(f"\033[38;5;208mPhase not found: {args.phase}\033[0m", file=sys.stderr)
        return 2
    data = write_pin(phase_dir, command=args.command, overwrite=args.overwrite)
    cmds = sorted(data.get("commands", {}).keys())
    print(f"✓ pinned {phase_dir.name}  commands={','.join(cmds)}")
    return 0


def _cmd_read(args: argparse.Namespace) -> int:
    phase_dir = _resolve_phase_dir(args.phase)
    if not phase_dir:
        print(f"\033[38;5;208mPhase not found: {args.phase}\033[0m", file=sys.stderr)
        return 2
    contract = get_pinned_contract(phase_dir, args.command)
    if contract is None:
        print(f"\033[38;5;208mNo pin for {args.command} in {phase_dir.name}\033[0m",
              file=sys.stderr)
        return 1
    print(json.dumps(contract, indent=2))
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="action", required=True)

    s_status = sp.add_parser("status", help="show pin state for a phase")
    s_status.add_argument("phase")
    s_status.set_defaults(func=_cmd_status)

    s_write = sp.add_parser("write", help="write pin (lock contract from current skill)")
    s_write.add_argument("phase")
    s_write.add_argument("--command", help="single command (default: all 6 tracked)")
    s_write.add_argument("--overwrite", action="store_true",
                         help="overwrite existing per-command pin (rare; default: skip)")
    s_write.set_defaults(func=_cmd_write)

    s_read = sp.add_parser("read", help="dump pinned contract as JSON")
    s_read.add_argument("phase")
    s_read.add_argument("--command", required=True)
    s_read.set_defaults(func=_cmd_read)

    s_extract = sp.add_parser("extract",
                              help="show current skill's contract (no pin write)")
    s_extract.add_argument("--command", required=True)
    s_extract.set_defaults(func=_cmd_extract)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
