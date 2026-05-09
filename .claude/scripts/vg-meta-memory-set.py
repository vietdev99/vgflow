#!/usr/bin/env python3
"""Atomic edit of meta_memory_mode in vg.config.md.

Subcommands:
  --mode <disabled|reflect-only|inject-as-advice|default>  set the flag
  --status                                                 print current value + path

Atomic write via tempfile.replace to avoid partial-write corruption.

Exit codes:
  0 — success (or no-op when already set)
  1 — invalid mode / unknown error
  2 — config file not found AND no template available
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

VALID_MODES = {"disabled", "reflect-only", "inject-as-advice", "default"}


def _resolve_config(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    # Project-level vg.config.md inside .claude/
    return Path(".claude/vg.config.md")


def _resolve_template() -> Path | None:
    candidates = [
        Path(".claude/templates/vg/vg.config.template.md"),
        Path("templates/vg/vg.config.template.md"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def cmd_status(cfg: Path) -> int:
    if not cfg.exists():
        print(f"meta_memory_mode: <not set> (config not found at {cfg})")
        return 0
    body = cfg.read_text(encoding="utf-8")
    m = re.search(r"^meta_memory_mode:\s*(\S+)", body, re.MULTILINE)
    if m:
        print(f"meta_memory_mode: {m.group(1)} (from {cfg})")
    else:
        print(f"meta_memory_mode: <not declared> (defaults to 'disabled') in {cfg}")
    return 0


def cmd_set(cfg: Path, mode: str) -> int:
    if mode not in VALID_MODES:
        print(f"⛔ Invalid mode '{mode}'. Valid: {sorted(VALID_MODES)}", file=sys.stderr)
        return 1

    if not cfg.exists():
        tpl = _resolve_template()
        if tpl is None:
            print(f"⛔ Config not found at {cfg} and no template available.", file=sys.stderr)
            return 2
        cfg.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tpl, cfg)
        print(f"ℹ Initialized {cfg} from template {tpl}")

    body = cfg.read_text(encoding="utf-8")
    new_body, count = re.subn(
        r"^meta_memory_mode:\s*\S+",
        f"meta_memory_mode: {mode}",
        body,
        count=1,
        flags=re.MULTILINE,
    )
    if count == 0:
        # Field absent — append at end of file
        if not body.endswith("\n"):
            body = body + "\n"
        new_body = body + f"\nmeta_memory_mode: {mode}\n"

    if new_body == body:
        print(f"meta_memory_mode already set to {mode} in {cfg}")
        return 0

    # Atomic write: tempfile in same dir + replace
    fd, tmp_path = tempfile.mkstemp(dir=cfg.parent, prefix=".vg.config.", suffix=".tmp")
    tmp = Path(tmp_path)
    try:
        with open(fd, "w", encoding="utf-8", newline="") as f:
            f.write(new_body)
        tmp.replace(cfg)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    print(f"✓ meta_memory_mode → {mode} in {cfg}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Set meta_memory_mode in vg.config.md")
    p.add_argument("--mode", choices=sorted(VALID_MODES) + ["status"], required=True,
                   help="Mode to set, or 'status' to print current value")
    p.add_argument("--config", default=None, help="Override config path (default: .claude/vg.config.md)")
    args = p.parse_args(argv)

    cfg = _resolve_config(args.config)
    if args.mode == "status":
        return cmd_status(cfg)
    return cmd_set(cfg, args.mode)


if __name__ == "__main__":
    sys.exit(main())
