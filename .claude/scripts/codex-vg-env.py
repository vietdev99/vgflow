#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from codex_vg_env import build_env, dump_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve VGFlow Codex runtime environment.")
    parser.add_argument("--phase", required=True, help="Phase number, e.g. 1 or 07.12")
    parser.add_argument("--format", choices=("shell", "json"), default="shell")
    args = parser.parse_args()

    env = build_env(args.phase)
    if args.format == "json":
        print(dump_json(env))
    else:
        print(env.shell_exports())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
