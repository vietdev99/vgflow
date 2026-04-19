#!/usr/bin/env python3
"""
graphify-incremental.py — Smart rebuild gate for /vg:map.

Logic:
  1. If no graph exists → full rebuild needed
  2. If graph exists, git diff since last rebuild marker:
     - Only markdown/planning/doc files changed → SKIP rebuild
     - Code files changed → incremental rebuild (delegate to graphify.watch for affected files)
     - Structural changes (tsconfig, package.json, imports) → full rebuild

Called from .claude/commands/vg/map.md to gate graphify rebuild cost.

USAGE
  python graphify-incremental.py decide \
      --graph graphify-out/graph.json \
      --marker .vg/.graphify-last-rebuild \
      --config .claude/vg.config.md

  # Exit code:
  #   0 = skip rebuild (print "skip: reason")
  #   1 = full rebuild needed (print "full: reason")
  #   2 = incremental feasible (print "incremental: N files changed")

  python graphify-incremental.py mark \
      --marker .vg/.graphify-last-rebuild
"""
import argparse
import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

# File patterns that trigger full rebuild (structural changes)
STRUCTURAL_PATTERNS = [
    "package.json", "package-lock.json", "pnpm-lock.yaml",
    "tsconfig.json", "tsconfig.*.json",
    "Cargo.toml", "Cargo.lock",
    "requirements.txt", "pyproject.toml", "poetry.lock",
    "go.mod", "go.sum",
    ".claude/vg.config.md",   # config changes → semantic shift
]

# Non-code extensions (skip rebuild)
NON_CODE_EXTENSIONS = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml",  # docs/config (overridden by STRUCTURAL above)
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",  # images
    ".csv", ".tsv", ".log",
}

# Planning dirs — never code, always skip
PLANNING_DIR_PREFIXES = [
    ".vg/",         # VG canonical planning path (v1.14.1+)
    ".planning/",   # legacy path (tolerate if GSD still present)
    "docs/",
    "CHANGELOG",
    "README",
]


def git_changed_files(since_ref_or_time):
    """Return list of changed files since ref (commit SHA or ISO timestamp)."""
    try:
        if since_ref_or_time.startswith("20") and "T" in since_ref_or_time:
            # Timestamp — use git log
            result = subprocess.run(
                ["git", "log", "--name-only", f"--since={since_ref_or_time}",
                 "--pretty=format:", "HEAD"],
                capture_output=True, text=True, check=True,
            )
            files = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        else:
            # Commit SHA
            result = subprocess.run(
                ["git", "diff", "--name-only", since_ref_or_time, "HEAD"],
                capture_output=True, text=True, check=True,
            )
            files = [l.strip() for l in result.stdout.splitlines() if l.strip()]

        # Also include uncommitted changes (working tree)
        wt = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, check=False,
        )
        for l in wt.stdout.splitlines():
            if l.strip() and l.strip() not in files:
                files.append(l.strip())

        return list(set(files))
    except subprocess.CalledProcessError:
        return None


def classify_change(path):
    """Return one of: 'structural', 'non_code', 'planning', 'code'."""
    p = Path(path)
    name = p.name

    # Structural
    for pat in STRUCTURAL_PATTERNS:
        if "*" in pat:
            # Simple wildcard
            prefix, _, suffix = pat.partition("*")
            if name.startswith(prefix) and name.endswith(suffix):
                return "structural"
        elif name == pat or str(p) == pat:
            return "structural"

    # Planning dirs
    s = str(p).replace("\\", "/")
    for prefix in PLANNING_DIR_PREFIXES:
        if s.startswith(prefix):
            return "planning"

    # Non-code extensions
    if p.suffix.lower() in NON_CODE_EXTENSIONS:
        return "non_code"

    return "code"


def cmd_decide(args):
    graph = Path(args.graph)
    marker = Path(args.marker)

    # 1. No graph → full rebuild
    if not graph.exists():
        print("full: no graph exists")
        return 1

    # 2. No marker → full rebuild (conservative)
    if not marker.exists():
        print("full: no rebuild marker (unknown staleness)")
        return 1

    # 3. Git diff since marker
    since = marker.read_text().strip()
    changed = git_changed_files(since)
    if changed is None:
        print("full: git diff failed (not a repo or error)")
        return 1

    if not changed:
        print("skip: no files changed since last rebuild")
        return 0

    # 4. Classify changes
    classes = {}
    for f in changed:
        c = classify_change(f)
        classes.setdefault(c, []).append(f)

    structural = len(classes.get("structural", []))
    code = len(classes.get("code", []))
    non_code = len(classes.get("non_code", []))
    planning = len(classes.get("planning", []))

    if structural > 0:
        print(f"full: {structural} structural files changed (package/config/lockfile)")
        for f in classes["structural"][:5]:
            print(f"  {f}", file=sys.stderr)
        return 1

    if code == 0:
        print(f"skip: only {planning} planning + {non_code} non-code files changed")
        return 0

    # Code changes → incremental feasible
    print(f"incremental: {code} code files changed ({non_code} non-code, {planning} planning also changed)")
    # Write changed files list to stderr for caller to consume
    for f in classes["code"]:
        print(f"CODE_FILE:{f}", file=sys.stderr)
    return 2


def cmd_mark(args):
    """Write current git SHA or timestamp to marker."""
    marker = Path(args.marker)
    marker.parent.mkdir(parents=True, exist_ok=True)

    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        marker.write_text(sha)
        print(f"marked: {sha}")
    except subprocess.CalledProcessError:
        ts = datetime.now(timezone.utc).isoformat()
        marker.write_text(ts)
        print(f"marked: {ts} (no git)")

    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("decide", help="Decide skip/incremental/full")
    d.add_argument("--graph", required=True, help="Path to graphify-out/graph.json")
    d.add_argument("--marker", required=True, help="Path to last-rebuild marker file")
    d.add_argument("--config", help="Path to vg.config.md (for future tuning)")
    d.set_defaults(func=cmd_decide)

    m = sub.add_parser("mark", help="Write current HEAD/time to marker (after successful rebuild)")
    m.add_argument("--marker", required=True)
    m.set_defaults(func=cmd_mark)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
