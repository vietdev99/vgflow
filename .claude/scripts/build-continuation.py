#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from build_continuation import clear_token, resolve_context, token_path, write_token  # type: ignore


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("write")
    p.add_argument("--phase-dir", required=True)
    p.add_argument("--phase", required=True)
    p.add_argument("--current-wave", required=True, type=int)
    p.add_argument("--max-wave", required=True, type=int)
    p.add_argument("--run-id", default="")
    p.add_argument("--session-id", default="")

    p = sub.add_parser("clear")
    p.add_argument("--phase-dir", required=True)

    p = sub.add_parser("show")
    p.add_argument("--phase-dir", required=True)
    p.add_argument("--field", default="canonical_command")

    p = sub.add_parser("resolve")
    p.add_argument("--root", default=".")
    p.add_argument("--prompt", required=True)
    p.add_argument("--adapter", default="auto")

    args = parser.parse_args()
    if args.cmd == "write":
        payload = write_token(
            phase_dir=Path(args.phase_dir),
            phase=args.phase,
            current_wave=args.current_wave,
            max_wave=args.max_wave,
            run_id=args.run_id,
            session_id=args.session_id,
        )
        if payload:
            print(payload["canonical_command"])
        return 0
    if args.cmd == "clear":
        changed = clear_token(phase_dir=Path(args.phase_dir))
        print("cleared" if changed else "absent")
        return 0
    if args.cmd == "show":
        import json

        path = token_path(Path(args.phase_dir))
        if not path.exists():
            return 1
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get(args.field)
        if value is None:
            return 1
        print(value)
        return 0
    if args.cmd == "resolve":
        context = resolve_context(root=Path(args.root), prompt=args.prompt, adapter=args.adapter)
        if not context:
            return 1
        print(context)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
