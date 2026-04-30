#!/usr/bin/env python3
"""review_batch.py — multi-phase /vg:review orchestrator (v2.40 Task 26d).

Runs Phase-2b-2.5 review across multiple phases sequentially (parallelism=1
default, see review.batch.parallelism in vg.config). Per-phase failure is
logged + the batch continues; aggregate findings written to
``BATCH-FINDINGS-{ISO-date}.json`` at the repo root.

Phase selection (one of):
  --phases 1,2,3                 explicit comma-separated list
  --milestone M2                 read ROADMAP.md, pick all "Phase N" under "## Milestone M2"
  --since <git-sha>              git diff --name-only <sha>...HEAD → unique .vg/phases/<N> dirs

Common flags forwarded per phase:
  --recursion={light,deep,exhaustive}
  --probe-mode={auto,manual,hybrid}
  --target-env={local,sandbox,staging,prod}
  --non-interactive

Per-phase entry point:
  Defaults to ``python -m vg.review --phase <N>``. Override via env
  ``VG_REVIEW_CMD`` for tests / non-default installs (the env value is the
  absolute path to a python script that accepts --phase + the forwarded
  flags).

Exit codes:
  0  all phases succeeded
  1  one or more phases failed (see BATCH-FINDINGS-*.json)
  2  argument / config error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def resolve_review_cmd() -> list[str]:
    """Resolve the per-phase /vg:review entry command.

    Resolution priority (first match wins):
      1. ``VG_REVIEW_CMD`` env var — explicit override (tests/CI). When the
         value is a single token that resolves to an existing file, treat it
         as a script path and prepend ``sys.executable``. Otherwise pass the
         tokens verbatim (shlex-split) so callers can inject e.g.
         ``"node my-shim.js"``.
      2. ``claude`` CLI on PATH — invoke ``/vg:review`` slash command.
      3. ``python -m vg.review`` — only if the ``vg.review`` module imports
         (canonical install).
      4. Hard-fail with an actionable error message — the previous silent
         ``ModuleNotFoundError`` from production users prompted this whole
         multi-fallback chain.
    """
    override = os.environ.get("VG_REVIEW_CMD")
    if override:
        # Fast-path: if the entire env value is an existing file (handles
        # paths with spaces, especially on Windows where shlex POSIX mode
        # mangles backslashes), treat it as a single script path.
        if Path(override).is_file():
            return [sys.executable, override]
        # Otherwise shlex-split (POSIX mode) so callers can compose multi-token
        # commands like ``"node my-shim.js --quiet"``.
        tokens = shlex.split(override, posix=(os.name != "nt"))
        if len(tokens) == 1 and Path(tokens[0]).is_file():
            return [sys.executable, tokens[0]]
        return tokens

    if shutil.which("claude"):
        return ["claude", "-p", "/vg:review"]

    try:
        import importlib.util  # local import — keeps module-load fast
        if importlib.util.find_spec("vg.review") is not None:
            return [sys.executable, "-m", "vg.review"]
    except (ImportError, ValueError):
        pass

    raise SystemExit(
        "⛔ Cannot resolve /vg:review entry command.\n"
        "   Tried (in priority order):\n"
        "     1. VG_REVIEW_CMD env var          — not set\n"
        "     2. `claude` CLI on PATH           — not found\n"
        "     3. `python -m vg.review` module   — not importable\n"
        "   Fix: install Claude CLI, or set VG_REVIEW_CMD to a script path.\n"
    )


def _resolve_phases_explicit(spec: str) -> list[str]:
    return [p.strip() for p in spec.split(",") if p.strip()]


def _resolve_phases_milestone(repo: Path, milestone: str) -> list[str]:
    roadmap = repo / "ROADMAP.md"
    if not roadmap.is_file():
        sys.stderr.write(f"ROADMAP.md not found at {roadmap}\n")
        return []
    text = roadmap.read_text(encoding="utf-8")
    # Locate the milestone section + grab everything until the next ## heading.
    m = re.search(rf"##\s+Milestone\s+{re.escape(milestone)}\b(.+?)(?=\n##\s|\Z)",
                  text, re.S)
    if not m:
        sys.stderr.write(f"milestone {milestone!r} not found in ROADMAP.md\n")
        return []
    phases: list[str] = []
    for line in m.group(1).splitlines():
        pm = re.match(r"\s*[-*]\s*Phase\s+([0-9]+(?:\.[0-9]+)?)\b", line)
        if pm:
            phases.append(pm.group(1))
    return phases


def _resolve_phases_since(repo: Path, sha: str) -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo), "diff", "--name-only", f"{sha}...HEAD"],
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"git diff failed (rc={exc.returncode})\n")
        return []
    seen: list[str] = []
    pattern = re.compile(r"\.vg/phases/([^/]+)/")
    for line in out.splitlines():
        m = pattern.search(line)
        if m and m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def _per_phase_cmd(phase: str, args: argparse.Namespace) -> list[str]:
    """Build the per-phase command. Multi-fallback per resolve_review_cmd()."""
    cmd = list(resolve_review_cmd())
    cmd += ["--phase", str(phase)]
    if args.recursion:
        cmd += ["--recursion", args.recursion]
    if args.probe_mode:
        cmd += ["--probe-mode", args.probe_mode]
    if args.target_env:
        cmd += ["--target-env", args.target_env]
    if args.non_interactive:
        cmd += ["--non-interactive"]
    return cmd


def _run_phase(phase: str, args: argparse.Namespace,
               repo: Path) -> dict[str, Any]:
    cmd = _per_phase_cmd(phase, args)
    started = _dt.datetime.now(_dt.timezone.utc).isoformat()
    try:
        result = subprocess.run(
            cmd, cwd=str(repo), capture_output=True, text=True,
        )
        return {
            "phase": phase,
            "started_at": started,
            "finished_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "exit_code": result.returncode,
            "stdout_tail": result.stdout[-2000:],
            "stderr_tail": result.stderr[-2000:],
            "cmd": cmd,
        }
    except FileNotFoundError as exc:
        return {
            "phase": phase,
            "started_at": started,
            "finished_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "exit_code": -1,
            "error": str(exc),
            "cmd": cmd,
        }


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="review_batch.py",
        description="Multi-phase /vg:review orchestrator (v2.40 Task 26d).",
    )
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument("--phases", help="Comma-separated list of phase IDs.")
    sel.add_argument("--milestone", help="Milestone label (e.g. M2) — reads ROADMAP.md.")
    sel.add_argument("--since", help="Git sha — diff sha...HEAD to derive phase list.")

    ap.add_argument("--recursion", choices=["light", "deep", "exhaustive"], default=None)
    ap.add_argument("--probe-mode", choices=["auto", "manual", "hybrid"], default=None)
    ap.add_argument("--target-env", choices=["local", "sandbox", "staging", "prod"],
                    default=None)
    ap.add_argument("--non-interactive", action="store_true",
                    help="Forward to per-phase review entry; CI uses this.")
    ap.add_argument("--findings-path", default=None,
                    help="Override BATCH-FINDINGS path (default repo-root + ISO date).")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    repo = REPO_ROOT

    if args.phases:
        phase_ids = _resolve_phases_explicit(args.phases)
    elif args.milestone:
        phase_ids = _resolve_phases_milestone(repo, args.milestone)
    else:
        phase_ids = _resolve_phases_since(repo, args.since)

    if not phase_ids:
        sys.stderr.write("no phases resolved; nothing to do\n")
        return 2

    started_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    results: list[dict[str, Any]] = []
    for pid in phase_ids:
        results.append(_run_phase(pid, args, repo))

    finished_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    aggregate: dict[str, Any] = {
        "started_at": started_at,
        "finished_at": finished_at,
        "selector": (
            {"phases": args.phases} if args.phases
            else {"milestone": args.milestone} if args.milestone
            else {"since": args.since}
        ),
        "forwarded": {
            "recursion": args.recursion,
            "probe_mode": args.probe_mode,
            "target_env": args.target_env,
            "non_interactive": args.non_interactive,
        },
        "phases": results,
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r["exit_code"] == 0),
            "failed": sum(1 for r in results if r["exit_code"] != 0),
        },
    }

    if args.findings_path:
        out_path = Path(args.findings_path).resolve()
    else:
        date = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        out_path = repo / f"BATCH-FINDINGS-{date}.json"

    out_path.write_text(json.dumps(aggregate, indent=2), encoding="utf-8")
    print(f"BATCH-FINDINGS written: {out_path}")
    print(f"  passed={aggregate['summary']['passed']} "
          f"failed={aggregate['summary']['failed']} "
          f"total={aggregate['summary']['total']}")

    return 0 if aggregate["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
