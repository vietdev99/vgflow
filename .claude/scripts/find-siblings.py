#!/usr/bin/env python3
"""
find-siblings.py — find peer modules for a target file.

Used by /vg:build step 4c (sibling_context injection). Hybrid: filesystem walk
for peer directory discovery + optional graphify signals for ranking + AST/grep
for signature extraction. Stack-agnostic output.

INPUT
  --file PATH              Target file (e.g., apps/api/src/modules/sites/routes.ts)
  --config PATH            vg.config.md path (default .claude/vg.config.md)
  --graphify-graph PATH    Optional — use graphify graph.json for extra ranking signal
  --top-n N                Return top N siblings (default 3)
  --output PATH            Output JSON path (default: ./.siblings.json)

OUTPUT (JSON)
  {
    "generated_at": "ISO timestamp",
    "target": "apps/api/src/modules/sites/routes.ts",
    "parent_dir": "apps/api/src/modules/sites",
    "search_scope": "apps/api/src/modules",
    "tools_used": ["fs", "git", "graphify"?],
    "siblings": [
      {
        "module_dir": "apps/api/src/modules/users",
        "entry_file": "apps/api/src/modules/users/routes.ts",
        "exports": [
          {"name": "listUsers", "kind": "function", "line": 12},
          ...
        ],
        "source": "fs+grep"
      }
    ]
  }

ALGORITHM
  1. parent = dirname(target)           # e.g., apps/api/src/modules/sites
  2. scope = dirname(parent)            # e.g., apps/api/src/modules
  3. List immediate subdirs of scope that aren't the target's parent.
  4. Rank by maturity:
       - file count in subdir (deep scan)
       - recent commit count (git log --since=30d)
       - optional: graphify community overlap with target (if graph provided)
  5. Pick top-N. For each, find entry file matching target's basename.
  6. Extract exports from entry file (stack-agnostic regex, same as ripple mode).
  7. Output JSON.

DESIGN NOTE
  Filesystem walk + git is deterministic and doesn't suffer from graphify's
  TS-alias blind spot. Graphify contributes extra community-overlap signal
  (optional; nice-to-have, not required).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


EXPORT_PATTERNS = [
    # JS/TS: export function|const|class|interface|type|enum + name
    (r"^\s*export\s+(?:async\s+)?(?:function|const|let|var|class|interface|type|enum)\s+(\w+)", "export"),
    (r"^\s*export\s+default\s+function\s+(\w+)", "export-default"),
    (r"^\s*export\s+\{\s*([^}]+)\s*\}", "re-export"),
    # Rust: pub fn|struct|const|enum|trait|type|mod
    (r"^\s*pub\s+(?:async\s+)?(?:fn|struct|const|enum|trait|type|mod)\s+(\w+)", "pub"),
    # Python: module-level def|class
    (r"^(?:async\s+)?def\s+(\w+)", "def"),
    (r"^class\s+(\w+)", "class"),
    # Go: func + capitalized name (exported)
    (r"^\s*func\s+(?:\([^)]*\)\s+)?([A-Z]\w*)", "go-func"),
]


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 30) -> str:
    try:
        out = subprocess.run(
            cmd, cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout
        )
        return out.stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def get_repo_root() -> Path:
    out = run(["git", "rev-parse", "--show-toplevel"])
    return Path(out.strip()) if out else Path.cwd()


def parse_config_scope_apps(config_path: Path) -> list[str]:
    """Read config.semantic_regression.scope_apps for filtering scope."""
    if not config_path.is_file():
        return ["apps", "packages"]
    in_block = False
    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("semantic_regression:"):
            in_block = True
            continue
        if in_block:
            if line and not line[0].isspace() and not stripped.startswith("#"):
                break
            if stripped.startswith("scope_apps:"):
                val = stripped.split(":", 1)[1].strip()
                if val.startswith("[") and val.endswith("]"):
                    return [i.strip().strip('"').strip("'") for i in val[1:-1].split(",") if i.strip()]
    return ["apps", "packages"]


def count_files_in_dir(d: Path) -> int:
    """Quick file count for maturity ranking (excludes hidden, common garbage)."""
    if not d.is_dir():
        return 0
    count = 0
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if not x.startswith((".", "__")) and x not in ("node_modules", "dist", "build", "target")]
        count += sum(1 for f in files if not f.startswith(".") and f != "index.ts")
    return count


def recent_commit_count(d: Path, repo_root: Path, days: int = 30) -> int:
    """Count commits touching this dir in last N days."""
    try:
        rel = d.relative_to(repo_root).as_posix()
    except ValueError:
        return 0
    out = run(
        ["git", "log", f"--since={days} days ago", "--oneline", "--", rel],
        cwd=repo_root,
    )
    return len([line for line in out.splitlines() if line.strip()])


def load_graphify_communities(graph_path: Path) -> dict[str, int]:
    """Load graph → return {source_file (posix): community_id}.

    Allows ranking siblings by same-community as target.
    """
    if not graph_path.is_file():
        return {}
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    communities: dict[str, int] = {}
    for n in data.get("nodes", []):
        sf = n.get("source_file", "")
        c = n.get("community")
        if sf and c is not None:
            sf_posix = sf.replace("\\", "/")
            if sf_posix not in communities:
                communities[sf_posix] = c
    return communities


def extract_exports(file_path: Path) -> list[dict]:
    """Stack-agnostic export extraction. Returns [{name, kind, line}, ...]."""
    if not file_path.is_file():
        return []
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    results: list[dict] = []
    seen: set[str] = set()
    for line_no, line in enumerate(text.splitlines(), 1):
        # Skip deeply indented lines (not top-level)
        if line and line[0] in " \t":
            # Allow leading spaces for multi-line export statements but skip body internals
            if not line.lstrip().startswith(("export", "pub")):
                continue
        for pat, kind in EXPORT_PATTERNS:
            m = re.match(pat, line)
            if m:
                raw = m.group(1)
                # Handle `export { a, b as c }` → extract final identifier of each
                for part in raw.split(","):
                    sym = part.strip().split(" as ")[-1].strip()
                    if sym and sym.isidentifier() and not sym.startswith("_") and sym not in seen:
                        seen.add(sym)
                        results.append({"name": sym, "kind": kind, "line": line_no})
                break
        if len(results) >= 50:
            break  # cap per file to avoid massive dumps
    return results


def find_entry_file(module_dir: Path, target_basename: str) -> Path | None:
    """Find the sibling's entry file matching target's purpose (e.g., "routes", "schemas").

    Preference order:
      1. Exact basename match (e.g., routes.ts → routes.ts)
      2. Type-suffix match: if target is `X.routes.ts` or `routes.ts`, find `*routes*.{ext}`
      3. index.* file as fallback
      4. Main entry by language convention (mod.rs, __init__.py, package main go)
    """
    # 1. Exact basename match
    direct = module_dir / target_basename
    if direct.is_file():
        return direct

    # 2. Type-suffix match — extract "role" word from target basename
    stem, _, ext = target_basename.rpartition(".")
    if not ext:
        stem, ext = target_basename, ""
    # Extract the role keyword: "audience.routes" → "routes"; "routes" → "routes"
    role = stem.split(".")[-1]

    if role and ext:
        # Try recursive glob for *role*.ext (excludes test/spec dirs)
        for p in module_dir.rglob(f"*{role}*.{ext}"):
            # Skip tests
            parts = {q.lower() for q in p.parts}
            if "__tests__" in parts or "tests" in parts or "test" in parts:
                continue
            if p.is_file():
                return p

    # 3. index.* fallback
    for fallback_ext in (ext, "ts", "tsx", "js", "jsx", "py", "rs", "go"):
        if not fallback_ext:
            continue
        idx = module_dir / f"index.{fallback_ext}"
        if idx.is_file():
            return idx

    # 4. Language convention entry points
    for name in ("mod.rs", "lib.rs", "__init__.py", "main.go"):
        p = module_dir / name
        if p.is_file():
            return p

    # 5. Last resort: first .ts/.js/.py/.rs file at top of module
    for p in sorted(module_dir.glob("*.*")):
        if p.is_file() and p.suffix.lstrip(".") in ("ts", "tsx", "js", "jsx", "py", "rs", "go"):
            return p

    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True, help="Target file (task's file-path)")
    ap.add_argument("--config", default=".claude/vg.config.md")
    ap.add_argument("--graphify-graph", default=None, help="Optional graphify-out/graph.json for community signal")
    ap.add_argument("--top-n", type=int, default=3)
    ap.add_argument("--output", default="./.siblings.json")
    args = ap.parse_args()

    repo_root = get_repo_root()
    target = Path(args.file)
    if not target.is_absolute():
        target = (repo_root / target).resolve()

    parent = target.parent
    scope = parent.parent

    # Validate target's parent is within scope_apps (avoid walking too high)
    scope_apps = parse_config_scope_apps(Path(args.config))
    try:
        rel_scope = scope.relative_to(repo_root).as_posix()
    except ValueError:
        print(f"ERROR: target file outside repo: {target}", file=sys.stderr)
        return 1

    if not any(rel_scope.startswith(app) or rel_scope == app for app in scope_apps):
        print(f"WARN: search scope ({rel_scope}) is not inside config.scope_apps ({scope_apps}) — proceeding anyway", file=sys.stderr)

    # List immediate subdirs of scope (candidate siblings)
    if not scope.is_dir():
        print(f"ERROR: scope dir not found: {scope}", file=sys.stderr)
        return 1

    candidates: list[dict] = []
    for child in scope.iterdir():
        if not child.is_dir():
            continue
        if child == parent:  # skip target's own parent
            continue
        if child.name.startswith((".", "__")) or child.name in ("node_modules", "dist", "build", "target"):
            continue
        candidates.append({
            "module_dir": child,
            "rel_path": child.relative_to(repo_root).as_posix(),
            "file_count": count_files_in_dir(child),
            "recent_commits": recent_commit_count(child, repo_root),
        })

    if not candidates:
        # No siblings — write empty result
        Path(args.output).write_text(
            json.dumps({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "target": target.relative_to(repo_root).as_posix(),
                "parent_dir": parent.relative_to(repo_root).as_posix(),
                "search_scope": rel_scope,
                "tools_used": ["fs"],
                "siblings": [],
                "note": "No peer modules found at this directory level — new architectural area or first module.",
            }, indent=2),
            encoding="utf-8",
        )
        print("No siblings found (scope empty) — wrote empty result", file=sys.stderr)
        return 0

    # Optional graphify community signal
    tools_used = ["fs", "git"]
    target_community: int | None = None
    graphify_comms: dict[str, int] = {}
    if args.graphify_graph:
        graphify_comms = load_graphify_communities(Path(args.graphify_graph))
        if graphify_comms:
            tools_used.append("graphify")
            # Look up target's community via any file in target's parent dir
            for sf, c in graphify_comms.items():
                if sf.startswith(parent.relative_to(repo_root).as_posix() + "/"):
                    target_community = c
                    break

    # Rank candidates
    def rank_score(cand: dict) -> tuple:
        comm_match = 0
        if target_community is not None and graphify_comms:
            # Any file in this candidate dir has matching community?
            for sf, c in graphify_comms.items():
                if sf.startswith(cand["rel_path"] + "/") and c == target_community:
                    comm_match = 1
                    break
        return (comm_match, cand["recent_commits"], cand["file_count"])

    candidates.sort(key=rank_score, reverse=True)
    top_candidates = candidates[: args.top_n]

    # Extract exports from each top candidate's entry file
    target_basename = target.name
    siblings_out: list[dict] = []
    for cand in top_candidates:
        entry = find_entry_file(cand["module_dir"], target_basename)
        if not entry:
            continue
        exports = extract_exports(entry)
        siblings_out.append({
            "module_dir": cand["rel_path"],
            "entry_file": entry.relative_to(repo_root).as_posix(),
            "exports": exports,
            "source": "fs+regex" + ("+graphify" if target_community is not None else ""),
            "ranking": {
                "file_count": cand["file_count"],
                "recent_commits": cand["recent_commits"],
                "community_match": bool(target_community is not None and rank_score(cand)[0] == 1),
            },
        })

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": target.relative_to(repo_root).as_posix(),
        "parent_dir": parent.relative_to(repo_root).as_posix(),
        "search_scope": rel_scope,
        "tools_used": tools_used,
        "siblings": siblings_out,
    }
    Path(args.output).write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Found {len(siblings_out)} siblings → {args.output}")
    for s in siblings_out:
        print(f"  {s['module_dir']}: {len(s['exports'])} exports (entry: {s['entry_file']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
