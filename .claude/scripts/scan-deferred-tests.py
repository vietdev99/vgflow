#!/usr/bin/env python3
"""scan-deferred-tests.py — read `it.skip(..., '@deferred <reason>')` markers
from test source files and emit TS-id → defer_reason JSON for review matrix.

Problem:
  Executor sometimes writes `it.skip('TS-16 ...', '@deferred /vg:test codegen')`
  in tests when a scenario can't run in unit/vitest context (e.g., needs
  Playwright UI flow, real faketime, or depends on another phase). These
  deferral reasons never reach GOAL-COVERAGE-MATRIX.md if CONTEXT.md doesn't
  also have a `depends_on_phase` / `verification_strategy` scope tag.

  Result: /vg:review classifies the goal BLOCKED (test missing or flaky) when
  it SHOULD be DEFERRED (legitimate skip with known reason).

Fix:
  Pre-review scanner reads test files touched by this phase, extracts
  `@deferred` markers, outputs JSON consumed by unreachable-triage.sh as an
  additional deferral source alongside scope tags.

Patterns recognized:
  it.skip("TS-16 ...", async () => { ... })
  it.skip("TS-16 title", "@deferred /vg:test codegen", async () => { ... })
  it.skip(
    "TS-16 title",
    // @deferred depends_on_phase 7.9
    async () => { ... }
  )

  Also Python/pytest conventions if project uses them:
  @pytest.mark.skip(reason="@deferred depends_on_phase 7.9")

TS-id extraction:
  Regex finds `\bTS-(\d+)` inside the test title (first positional arg).

Output JSON:
  {
    "phase": "10",
    "scanned_files": 5,
    "deferred_tests": [
      {
        "ts_id": "TS-16",
        "goal_id": null,
        "defer_reason": "/vg:test codegen — Playwright UI flow",
        "defer_kind": "test-codegen",
        "source_file": "apps/api/.../deal-integration.test.ts",
        "test_title": "TS-16 admin creates deal via wizard"
      }
    ]
  }

  defer_kind classification:
    - "depends_on_phase"     — reason matches "depends_on_phase X.Y" → DEFERRED
    - "test-codegen"         — reason mentions codegen/Playwright   → DEFERRED
    - "manual"               — reason mentions manual verification  → MANUAL
    - "faketime"             — reason mentions faketime             → MANUAL
    - "unknown"              — no canonical pattern                  → warning

Usage:
  python3 scan-deferred-tests.py \
    --phase-dir .vg/phases/10-deal-management-dsp-partners \
    --output .vg/phases/10-deal-management-dsp-partners/.deferred-tests.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional


TEST_GLOBS = [
    "*.test.ts", "*.test.tsx", "*.test.js", "*.test.jsx",
    "*.spec.ts", "*.spec.tsx", "*.spec.js", "*.spec.jsx",
    "test_*.py", "*_test.py",
    "*.rs",  # for cargo tests that have #[test] with descriptions
]


def find_phase_test_files(phase_dir: Path, repo_root: Path) -> List[Path]:
    """Find test files changed/added during this phase's build.

    Uses git log against the earliest wave-start tag to find the commit range
    that introduced the phase, then diff to get all changed test files.
    """
    phase_num = ""
    # Extract phase number from dir name (e.g., "10-deal..." → "10")
    m = re.match(r"(\d+(?:\.\d+)*)", phase_dir.name)
    if m:
        phase_num = m.group(1)
    if not phase_num:
        return []

    try:
        tags = subprocess.run(
            ["git", "tag", "-l", f"vg-build-{phase_num}-wave-1-start"],
            cwd=repo_root, capture_output=True, text=True, check=False,
        ).stdout.strip()
    except FileNotFoundError:
        return []

    since_ref = tags or f"HEAD~100"  # fallback: last 100 commits

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{since_ref}..HEAD"],
            cwd=repo_root, capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return []

    files: List[Path] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # Match any of the test globs
        basename = Path(line).name
        for pattern in TEST_GLOBS:
            if _glob_match(basename, pattern):
                p = repo_root / line
                if p.exists():
                    files.append(p)
                break
    return files


def _glob_match(name: str, pattern: str) -> bool:
    """Simple glob: * = any chars."""
    regex = pattern.replace(".", r"\.").replace("*", r".*")
    return bool(re.fullmatch(regex, name))


# Patterns for extracting it.skip/test.skip with deferred markers.
SKIP_BLOCK_RE = re.compile(
    r"""
    (?:it|test)\.skip\s*\(          # it.skip( or test.skip(
    \s*(['"])((?:(?!\1).)+?)\1      # first arg: test title (quote-balanced)
    (?:                             # optional second string (deferral reason):
      \s*,\s*['"]([^'"]*@deferred[^'"]*)['"]
    )?
    """,
    re.X,
)

# Pattern for inline comment-style deferral above a skip block
SKIP_WITH_COMMENT_RE = re.compile(
    r"""
    //\s*@deferred\s+([^\n]+)       # comment like: // @deferred <reason>
    \s*\n\s*
    (?:it|test)\.skip\s*\(
    \s*['"]([^'"]+)['"]
    """,
    re.X,
)

# Pattern for deferred comment INSIDE the test body (most common pattern
# observed in Phase 10 Task 22: `it.skip('TS-06: ...', () => { // @deferred reason })`)
SKIP_WITH_BODY_COMMENT_RE = re.compile(
    r"""
    (?:it|test)\.skip\s*\(          # it.skip(
    \s*(['"])((?:(?!\1).)+?)\1      # first arg: test title (quote-balanced)
    \s*,\s*                          # comma separator
    (?:async\s+)?\(\s*\)\s*=>\s*\{  # arrow function header: () => {
    \s*                              # possible whitespace/newlines
    //\s*@deferred\s+([^\n]+)        # body comment: // @deferred <reason>
    """,
    re.X,
)

# Python pytest
PY_SKIP_RE = re.compile(
    r"@pytest\.mark\.skip\s*\(\s*reason\s*=\s*['\"]([^'\"]*@deferred[^'\"]*)['\"]\s*\)\s*\n"
    r"\s*def\s+test_([A-Za-z0-9_]+)",
)


def extract_deferred_from_file(path: Path) -> List[Dict]:
    """Return [{ts_id, defer_reason, test_title, source_file}, ...]."""
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    findings: List[Dict] = []

    # Pattern A: it.skip("TS-16 title", "@deferred reason", ...)
    # After regex update: groups are (quote, title, reason-group-or-none)
    for m in SKIP_BLOCK_RE.finditer(txt):
        title = m.group(2)
        reason = m.group(3)
        if not reason:
            continue
        ts_id = extract_ts_id(title)
        if not ts_id:
            continue
        clean_reason = reason.replace("@deferred", "").strip()
        findings.append({
            "ts_id": ts_id,
            "defer_reason": clean_reason,
            "defer_kind": classify_reason(clean_reason),
            "test_title": title,
            "source_file": str(path),
        })

    # Pattern B: // @deferred reason\nit.skip("TS-16 ...")
    # After regex update: groups are (reason, quote, title)
    for m in SKIP_WITH_COMMENT_RE.finditer(txt):
        reason = m.group(1).strip()
        title = m.group(3)
        ts_id = extract_ts_id(title)
        if not ts_id:
            continue
        findings.append({
            "ts_id": ts_id,
            "defer_reason": reason,
            "defer_kind": classify_reason(reason),
            "test_title": title,
            "source_file": str(path),
        })

    # Pattern D: it.skip('TS-NN ...', () => { // @deferred reason })
    # After regex update: groups are (quote, title, reason)
    for m in SKIP_WITH_BODY_COMMENT_RE.finditer(txt):
        title = m.group(2)
        reason = m.group(3).strip()
        ts_id = extract_ts_id(title)
        if not ts_id:
            continue
        findings.append({
            "ts_id": ts_id,
            "defer_reason": reason,
            "defer_kind": classify_reason(reason),
            "test_title": title,
            "source_file": str(path),
        })

    # Pattern C: Python pytest
    for m in PY_SKIP_RE.finditer(txt):
        reason = m.group(1).replace("@deferred", "").strip()
        test_fn = m.group(2)
        ts_id = extract_ts_id(test_fn)
        if not ts_id:
            continue
        findings.append({
            "ts_id": ts_id,
            "defer_reason": reason,
            "defer_kind": classify_reason(reason),
            "test_title": test_fn,
            "source_file": str(path),
        })

    return findings


def extract_ts_id(text: str) -> Optional[str]:
    """Find 'TS-NN' or 'ts_nn' inside a test title."""
    m = re.search(r"\bTS[-_](\d+)\b", text, re.I)
    if m:
        return f"TS-{m.group(1)}"
    return None


def classify_reason(reason: str) -> str:
    """Map reason text to defer_kind taxonomy."""
    r = reason.lower()
    if "depends_on_phase" in r or re.search(r"\bphase\s+\d+", r):
        return "depends_on_phase"
    if "codegen" in r or "playwright" in r:
        return "test-codegen"
    if "manual" in r:
        return "manual"
    if "faketime" in r or "time" in r:
        return "faketime"
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--output", help="Path to write JSON (default: <phase-dir>/.deferred-tests.json)")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    repo_root = Path(args.repo_root).resolve()
    out_path = Path(args.output) if args.output else phase_dir / ".deferred-tests.json"

    test_files = find_phase_test_files(phase_dir, repo_root)

    all_findings: List[Dict] = []
    for tf in test_files:
        all_findings.extend(extract_deferred_from_file(tf))

    result = {
        "phase": re.match(r"(\d+(?:\.\d+)*)", phase_dir.name).group(1) if re.match(r"(\d+(?:\.\d+)*)", phase_dir.name) else "",
        "scanned_files": len(test_files),
        "deferred_tests": all_findings,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"━━━ Deferred test markers scan ━━━")
    print(f"Phase:        {result['phase']}")
    print(f"Test files:   {len(test_files)}")
    print(f"Deferred:     {len(all_findings)}")
    print(f"Output:       {out_path}")
    print()
    if all_findings:
        by_kind: Dict[str, int] = {}
        for f in all_findings:
            by_kind[f["defer_kind"]] = by_kind.get(f["defer_kind"], 0) + 1
        print("By kind:")
        for k, v in sorted(by_kind.items()):
            print(f"  {k}: {v}")
        print()
        for f in all_findings[:10]:
            print(f"  {f['ts_id']} [{f['defer_kind']}] — {f['defer_reason'][:60]}")
        if len(all_findings) > 10:
            print(f"  ... and {len(all_findings) - 10} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
