#!/usr/bin/env python3
"""
verify-review-loop-evidence.py — Phase R of v2.5.2 hardening.

Problem closed (v2.5.1 Codex finding):
  v2.5.1's review-loop "evidence" was AI narrating iterations in its log
  ("Iteration 2: fixed XSS issue"). No deterministic proof the fix
  actually modified source. AI could silently defer fix-promotion and
  narrate success.

This validator is BEHAVIORAL:
  1. Read review state from .vg/phases/<N>/review-iter-<M>.json files
     (produced by /vg:review iterations — NOT AI narration, orchestrator
     writes them as state transitions)
  2. For consecutive iter pairs (M, M+1), ASSERT via git:
     - At least one source file (under apps/** or packages/**) changed
       between the commits referenced by each iter
     OR
     - `resolution: "no_fix_needed"` explicitly set in iter M+1 manifest
  3. Empty diff + no explicit no-fix = forged iteration → BLOCK

Exit codes:
  0 = all iterations have verifiable progress
  1 = empty iteration (no source delta, no explicit no-fix)
  2 = config error (no iter files, git not available)

Usage:
  verify-review-loop-evidence.py --phase-dir .vg/phases/7.14
  verify-review-loop-evidence.py --phase-dir X --require-diff-paths "apps/**,packages/**"
  verify-review-loop-evidence.py --phase-dir X --json
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def _load_iter_files(phase_dir: Path) -> list[dict]:
    """Return iter records sorted by iter_number."""
    out = []
    for fp in sorted(phase_dir.glob("review-iter-*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        data.setdefault("_file", str(fp))
        out.append(data)

    out.sort(key=lambda d: d.get("iter_number", 0))
    return out


def _git_diff_files(commit_from: str, commit_to: str) -> list[str]:
    """Return list of file paths changed between the two commits."""
    if not commit_from or not commit_to:
        return []
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{commit_from}..{commit_to}"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT), timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return []

    if result.returncode != 0:
        return []
    return [p.strip() for p in result.stdout.splitlines() if p.strip()]


def _match_any(path: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    for p in patterns:
        # Support glob + recursive ** pattern
        if fnmatch.fnmatch(path, p):
            return True
        # Also try if path starts with pattern root before **
        if p.endswith("/**"):
            prefix = p[:-3]
            if path.startswith(prefix):
                return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--phase-dir", required=True,
                    help="Phase directory containing review-iter-*.json")
    ap.add_argument("--require-diff-paths",
                    default="apps/**,packages/**,src/**",
                    help="Comma-separated glob patterns (files outside these "
                         "ignored when counting iteration progress)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--phase", help="(orchestrator-injected; ignored by this validator)")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    if not phase_dir.is_absolute():
        phase_dir = REPO_ROOT / phase_dir
    if not phase_dir.exists():
        msg = f"Phase dir not found: {phase_dir}"
        if args.json:
            print(json.dumps({"error": msg}))
        else:
            print(f"⛔ {msg}", file=sys.stderr)
        return 2

    iters = _load_iter_files(phase_dir)
    if len(iters) < 2:
        msg = (f"Need >= 2 review iterations to verify progress, "
               f"found {len(iters)}")
        if args.json:
            print(json.dumps({
                "phase_dir": str(phase_dir),
                "iterations_found": len(iters),
                "pairs_checked": 0,
                "failures": [],
            }))
        elif not args.quiet:
            print(f"✓ {msg} — nothing to verify")
        return 0

    paths = [p.strip() for p in args.require_diff_paths.split(",") if p.strip()]

    pair_reports = []
    failures = []

    for prev, curr in zip(iters, iters[1:]):
        prev_commit = prev.get("commit_sha") or prev.get("commit") or ""
        curr_commit = curr.get("commit_sha") or curr.get("commit") or ""
        resolution = curr.get("resolution", "")

        all_changed = _git_diff_files(prev_commit, curr_commit)
        relevant = [p for p in all_changed if _match_any(p, paths)]

        record = {
            "iter_from": prev.get("iter_number"),
            "iter_to": curr.get("iter_number"),
            "prev_commit": prev_commit[:10],
            "curr_commit": curr_commit[:10],
            "resolution": resolution,
            "total_files_changed": len(all_changed),
            "relevant_files_changed": len(relevant),
            "sample_paths": relevant[:5],
        }

        if not relevant and resolution != "no_fix_needed":
            record["status"] = "empty_iteration"
            failures.append(record)
        else:
            record["status"] = "ok"

        pair_reports.append(record)

    result = {
        "phase_dir": str(phase_dir),
        "iterations_found": len(iters),
        "pairs_checked": len(iters) - 1,
        "pair_reports": pair_reports,
        "failures": failures,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if failures:
            print(f"⛔ Review loop evidence: {len(failures)}/"
                  f"{len(pair_reports)} iteration pair(s) empty\n")
            for f in failures:
                print(f"  iter {f['iter_from']} → {f['iter_to']}: "
                      f"no source delta, no explicit 'no_fix_needed'")
        elif not args.quiet:
            print(f"✓ Review loop evidence OK — {len(pair_reports)} iteration "
                  f"pair(s) all show progress")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
