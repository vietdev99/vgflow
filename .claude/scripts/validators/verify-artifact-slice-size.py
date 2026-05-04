#!/usr/bin/env python3
"""Task 43 — verify per-slice ≤5K-token BLOCK validator (Bug K, M3).

Scans all per-unit slice directories under ${PHASE_DIR}:
  - PLAN/task-NN.md
  - API-CONTRACTS/<slug>.md
  - TEST-GOALS/G-NN.md
  - CRUD-SURFACES/<resource>.md
  - WORKFLOW-SPECS/WF-NN.md
Plus index.md files in each of the above directories.

Token-counting: tiktoken cl100k_base (MANDATORY per Codex round-2
Amendment C). Naive char-heuristic underestimates Vietnamese content.

Exit codes:
- 0 = OK or override accepted
- 1 = BLOCK (oversized slice) or tiktoken-import failure
- 2 = wrong invocation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# MANDATORY import — loud-fail if missing.
try:
    import tiktoken
except ImportError as exc:
    sys.stderr.write(
        f"BLOCK: tiktoken is MANDATORY for slice-size validation.\n"
        f"  Reason: Vietnamese diacritics tokenize at ~2 chars/token; the\n"
        f"  naive char-count heuristic underestimates real token count by\n"
        f"  ~50%, allowing oversized prompts to slip past as 'OK'.\n"
        f"  Fix: pip install tiktoken>=0.7\n"
        f"  Underlying error: {exc}\n"
    )
    sys.exit(1)


_ENCODING = tiktoken.get_encoding("cl100k_base")

PER_UNIT_LIMIT = 5000
INDEX_LIMIT = 1000

SLICE_DIRS = (
    ("PLAN", "task-*.md"),
    ("API-CONTRACTS", "*.md"),
    ("TEST-GOALS", "G-*.md"),
    ("CRUD-SURFACES", "*.md"),
    ("WORKFLOW-SPECS", "WF-*.md"),
)


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _scan(phase_dir: Path) -> list[tuple[Path, int, int]]:
    """Return list of (file, token_count, limit) for files exceeding their limit."""
    findings: list[tuple[Path, int, int]] = []
    for sub, pattern in SLICE_DIRS:
        d = phase_dir / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob(pattern)):
            if f.name == "index.md":
                continue
            tokens = _count_tokens(f.read_text(encoding="utf-8"))
            if tokens > PER_UNIT_LIMIT:
                findings.append((f, tokens, PER_UNIT_LIMIT))
        idx = d / "index.md"
        if idx.exists():
            tokens = _count_tokens(idx.read_text(encoding="utf-8"))
            if tokens > INDEX_LIMIT:
                findings.append((idx, tokens, INDEX_LIMIT))
    return findings


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--phase-dir", required=True)
    p.add_argument("--allow-oversized-slice", action="store_true")
    p.add_argument("--override-reason", default="")
    p.add_argument("--override-debt-path", default="")
    args = p.parse_args()

    phase_dir = Path(args.phase_dir)
    if not phase_dir.is_dir():
        print(f"ERROR: --phase-dir not a directory: {phase_dir}", file=sys.stderr)
        return 2

    findings = _scan(phase_dir)
    if not findings:
        return 0

    if args.allow_oversized_slice:
        if not args.override_reason:
            print("ERROR: --allow-oversized-slice requires --override-reason", file=sys.stderr)
            return 2
        debt = {
            "scope": "artifact-slice-oversized",
            "reason": args.override_reason,
            "findings": [
                {"path": str(f.relative_to(phase_dir)), "tokens": tokens, "limit": limit}
                for f, tokens, limit in findings
            ],
        }
        if args.override_debt_path:
            Path(args.override_debt_path).write_text(json.dumps(debt, indent=2), encoding="utf-8")
        print(f"OVERRIDE accepted ({len(findings)} oversized slices logged to override-debt)")
        return 0

    print("BLOCK: artifact slice size violations:")
    for f, tokens, limit in findings:
        rel = f.relative_to(phase_dir)
        print(f"  - {rel}: {tokens} tokens > {limit} limit")
    print("Fix: split the slice into smaller units, OR pass --allow-oversized-slice "
          "--override-reason='<text>' for legacy phases.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
