#!/usr/bin/env python3
"""verify-utility-duplication.py — post-wave AST scan to detect duplicate
helper declarations across the repo (root cause of tsc OOM + graphify god-node
noise seen in Phase 10 audit).

Runs from `/vg:build` step 8d (after commit count verification). If a helper
was introduced in this wave's commits AND the same name exists elsewhere in
the repo above the duplication threshold → emit BLOCK/WARN findings.

Strategy:
  1. Get files changed since --since-tag (git diff).
  2. For each changed .ts/.tsx/.js/.jsx file, extract helper DECLARATIONS
     (function X, const X = arrow, export function X, export const X).
  3. For each declared helper name:
       a. Skip if name is in the canonical utility contract (those ARE supposed
          to be declared only there — contract check handles ownership).
       b. Skip if name starts with uppercase (React component or class).
       c. Skip if it's in a test file or packages/utils/ itself.
       d. Grep the repo for same-name declarations; count distinct files.
  4. If count >= --threshold-block → BLOCK
     If count >= --threshold-warn → WARN
     Else → OK

Output:
  Text summary + exit code (0=clean, 1=block, 2=warn-only).

Usage:
  python3 verify-utility-duplication.py \
    --since-tag vg-build-10-wave-6-start \
    --project .vg/PROJECT.md \
    --threshold-block 3 --threshold-warn 2
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, NamedTuple, Set


SOURCE_EXTS = {".ts", ".tsx", ".js", ".jsx"}


class DupFinding(NamedTuple):
    severity: str          # "BLOCK" | "WARN"
    helper_name: str
    introduced_in: str     # file path where this wave introduced it
    all_copies: List[str]  # file paths of all declarations


DECL_PATTERNS = [
    # export function X(
    re.compile(r"^\s*export\s+(?:async\s+)?function\s+([a-z][A-Za-z0-9_]*)\s*[<(]", re.M),
    # export const X = (...)=> | export const X = function
    re.compile(r"^\s*export\s+const\s+([a-z][A-Za-z0-9_]*)\s*[:=]\s*(?:async\s+)?(?:\(|function)", re.M),
    # local function X(
    re.compile(r"^\s*(?:async\s+)?function\s+([a-z][A-Za-z0-9_]*)\s*[<(]", re.M),
    # local const X = (...) => arrow (with typed annotation optional)
    re.compile(r"^\s*const\s+([a-z][A-Za-z0-9_]*)\s*[:=]\s*(?:async\s+)?\(", re.M),
]


# Names that are intentionally declared in many places (not duplication):
SKIP_NAMES: Set[str] = {
    "handler", "middleware", "builder", "resolver", "getter", "setter",
    "loader", "validator", "guard", "plugin", "factory",
    "beforeAll", "afterAll", "beforeEach", "afterEach",
    "it", "test", "describe", "expect",
    "use", "useEffect", "useState", "useMemo", "useCallback",  # React hooks prefix
}

# Name prefixes that are inherently per-component/per-module event/handler patterns
# (not shared utilities). These are false-positive magnets.
SKIP_NAME_PREFIXES = (
    "handle",    # handleSubmit, handleChange, handleClick — React event handlers
    "on",        # onClick, onSubmit — prop handlers
    "render",    # renderRow, renderItem — local render helpers
    "get",       # getXxx — repository/service method, not a shared util
    "set",       # setXxx — state setter convention
    "fetch",     # fetchData — query-specific
    "load",      # loadData — page-specific load
    "build",     # buildQuery — local builder
    "make",      # makeXxx — local factory
    "with",      # withAuth — HOC pattern
    "create",    # createSession — command creators
    "to",        # toPayload — serialization per-entity
    "from",      # fromAPI — deserialization per-entity
    "map",       # mapXxx — local mappers
    "parse",     # parseRequest — local parsers (too broad to share)
    "validate",  # validateForm — per-schema validators
    "transform", # transformData — local ETL
    "normalize", # normalizeXxx — per-entity
    "serialize", # serializeXxx — per-entity
    "deserialize",
    "is",        # isValid — local predicate
    "has",       # hasPermission — local predicate
    "can",       # canEdit — local predicate
    "should",    # shouldShow — local predicate
)


def _is_skippable_name(name: str) -> bool:
    if name in SKIP_NAMES:
        return True
    for prefix in SKIP_NAME_PREFIXES:
        if name.startswith(prefix) and len(name) > len(prefix) and name[len(prefix)].isupper():
            return True
    return False


def parse_contract(project_md: Path) -> Set[str]:
    """Return set of canonical utility names from PROJECT.md."""
    if not project_md.exists():
        return set()
    txt = project_md.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^##\s+Shared Utility Contract\s*$(.+?)^##\s+", txt, re.M | re.S)
    if not m:
        return set()
    names: Set[str] = set()
    for row in re.finditer(r"^\|\s*`([A-Za-z_][A-Za-z0-9_]*)`\s*\|", m.group(1), re.M):
        names.add(row.group(1))
    return names


def changed_files_since(tag: str, repo_root: Path) -> List[Path]:
    """Return list of source files changed since the given tag."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{tag}..HEAD"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        return []
    out: List[Path] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        p = repo_root / line
        if p.suffix in SOURCE_EXTS and p.exists():
            # Skip test files + utils themselves (canonical OK)
            if "__tests__" in p.parts or p.name.endswith(".test.ts") or p.name.endswith(".test.tsx"):
                continue
            if p.name.endswith(".spec.ts") or p.name.endswith(".spec.tsx"):
                continue
            out.append(p)
    return out


def extract_decls(path: Path) -> Set[str]:
    """Extract helper function names declared in this file."""
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return set()
    names: Set[str] = set()
    for pat in DECL_PATTERNS:
        for m in pat.finditer(txt):
            name = m.group(1)
            if _is_skippable_name(name) or len(name) < 3:
                continue
            names.add(name)
    return names


_ALL_SOURCE_FILES_CACHE: List[Path] = []


def _list_all_source_files(repo_root: Path) -> List[Path]:
    """git ls-files cached — returns every tracked .ts/.tsx/.js/.jsx (sans tests/dist)."""
    global _ALL_SOURCE_FILES_CACHE
    if _ALL_SOURCE_FILES_CACHE:
        return _ALL_SOURCE_FILES_CACHE
    try:
        result = subprocess.run(
            ["git", "ls-files", "*.ts", "*.tsx", "*.js", "*.jsx"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    files: List[Path] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if "__tests__" in line or line.endswith(".test.ts") or line.endswith(".test.tsx"):
            continue
        if line.endswith(".spec.ts") or line.endswith(".spec.tsx"):
            continue
        if "node_modules/" in line or "/dist/" in line or line.startswith("dist/"):
            continue
        # Skip legacy HTML prototype JS (not production, not part of current type graph)
        if line.startswith("html/") or line.startswith("html\\"):
            continue
        files.append(repo_root / line)
    _ALL_SOURCE_FILES_CACHE = files
    return files


def repo_declaration_count(name: str, repo_root: Path, exclude_utils: bool = False) -> List[Path]:
    """Python-native grep for declarations (avoids git-grep regex dialect issues)."""
    name_esc = re.escape(name)
    patterns = [
        re.compile(rf"^\s*export\s+(?:async\s+)?function\s+{name_esc}\b", re.M),
        re.compile(rf"^\s*export\s+const\s+{name_esc}\s*[:=]", re.M),
        re.compile(rf"^\s*(?:async\s+)?function\s+{name_esc}\s*[<(]", re.M),
        re.compile(rf"^\s*const\s+{name_esc}\s*[:=]\s*(?:async\s+)?\(", re.M),
    ]
    found: List[Path] = []
    for f in _list_all_source_files(repo_root):
        if exclude_utils and "packages/utils" in str(f).replace("\\", "/"):
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in patterns:
            if pat.search(txt):
                found.append(f)
                break
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since-tag", required=True, help="Git tag marking wave start")
    ap.add_argument("--project", required=True, help="Path to PROJECT.md")
    ap.add_argument("--repo-root", default=".", help="Repo root")
    ap.add_argument("--threshold-block", type=int, default=3, help="Copies ≥ this = BLOCK")
    ap.add_argument("--threshold-warn", type=int, default=2, help="Copies ≥ this = WARN")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    project_md = Path(args.project)

    contract_names = parse_contract(project_md)
    changed = changed_files_since(args.since_tag, repo_root)

    if not changed:
        print(f"✓ No source files changed since {args.since_tag} — skipping duplication check.")
        return 0

    # Collect helpers introduced in this wave
    wave_helpers: Dict[str, List[Path]] = defaultdict(list)
    for f in changed:
        for name in extract_decls(f):
            wave_helpers[name].append(f)

    findings: List[DupFinding] = []
    for name, introducing_files in wave_helpers.items():
        # Canonical in contract — declaration there is CORRECT (don't flag)
        if name in contract_names:
            # But if this wave declared it OUTSIDE packages/utils/, flag WARN
            outside_utils = [f for f in introducing_files if "packages/utils" not in str(f)]
            if outside_utils:
                all_copies = repo_declaration_count(name, repo_root)
                findings.append(DupFinding(
                    severity="BLOCK",
                    helper_name=name,
                    introduced_in=str(outside_utils[0].relative_to(repo_root)),
                    all_copies=[str(p.relative_to(repo_root)) for p in all_copies],
                ))
            continue

        # Non-contract helper. Count total copies in repo.
        all_copies = repo_declaration_count(name, repo_root)
        count = len(all_copies)
        if count >= args.threshold_block:
            findings.append(DupFinding(
                severity="BLOCK",
                helper_name=name,
                introduced_in=str(introducing_files[0].relative_to(repo_root)),
                all_copies=[str(p.relative_to(repo_root)) for p in all_copies],
            ))
        elif count >= args.threshold_warn:
            findings.append(DupFinding(
                severity="WARN",
                helper_name=name,
                introduced_in=str(introducing_files[0].relative_to(repo_root)),
                all_copies=[str(p.relative_to(repo_root)) for p in all_copies],
            ))

    blocks = [f for f in findings if f.severity == "BLOCK"]
    warns = [f for f in findings if f.severity == "WARN"]

    if args.json:
        import json
        print(json.dumps({
            "since_tag": args.since_tag,
            "changed_files": len(changed),
            "helpers_introduced": len(wave_helpers),
            "blocks": [f._asdict() for f in blocks],
            "warns": [f._asdict() for f in warns],
        }, indent=2))
    else:
        print(f"━━━ Wave Duplication Check ━━━")
        print(f"Since tag:         {args.since_tag}")
        print(f"Files changed:     {len(changed)}")
        print(f"Helpers declared:  {len(wave_helpers)}")
        print(f"BLOCK findings:    {len(blocks)} (copies >= {args.threshold_block})")
        print(f"WARN findings:     {len(warns)} (copies >= {args.threshold_warn})")
        print()
        for f in blocks:
            print(f"\033[38;5;208mBLOCK `{f.helper_name}` — {len(f.all_copies)} copies across repo\033[0m")
            print(f"   Introduced here: {f.introduced_in}")
            print(f"   All copies:")
            for p in f.all_copies[:10]:
                print(f"     - {p}")
            if len(f.all_copies) > 10:
                print(f"     ... and {len(f.all_copies) - 10} more")
            print(f"   Fix: extract to packages/utils/ + rewrite imports.")
            print()
        for f in warns:
            print(f"\033[33mWARN `{f.helper_name}` — {len(f.all_copies)} copies\033[0m")
            print(f"   Introduced here: {f.introduced_in}")
            for p in f.all_copies:
                print(f"     - {p}")
            print()

    if blocks:
        return 1
    if warns:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
