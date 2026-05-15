#!/usr/bin/env python3
"""Batch 38: verify every CONTEXT D-XX is referenced in ≥1 spec body.

User complaint: "test cũng không bám theo test specs" — decisions in
phase CONTEXT.md may not translate to test assertions. Without this
gate, phases can ship with spec sets that don't cover the architectural
decisions driving the phase.

Pipeline gate:
1. Parse CONTEXT.md for D-XX decision IDs + expected_assertion fields
2. Scan generated .spec.ts files in CODEGEN-MANIFEST.json for D-XX mentions
3. Per decision: at least one spec must cite D-XX (in comment, fixture,
   or test name)
4. FAIL listing uncovered decisions

Usage:
  verify-decision-to-spec-coverage.py --phase 7
  verify-decision-to-spec-coverage.py --phase 7 --strict   # all D-XX covered
  verify-decision-to-spec-coverage.py --phase 7 --allow-uncovered=D-03,D-05
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

DECISION_RE = re.compile(r"\bD-\d+\b")


def _find_phase_dir(phase: str, override: str | None = None) -> Path:
    if override:
        return Path(override)
    for root in (Path(".vg/phases"), Path("dev-phases"), Path("phases")):
        if not root.is_dir():
            continue
        for p in root.iterdir():
            if p.is_dir() and (p.name == phase or p.name.startswith(f"{phase}-")):
                return p
    raise SystemExit(f"phase dir not found for {phase}")


def _parse_context_decisions(phase_dir: Path) -> set[str]:
    """Find all D-XX IDs declared in CONTEXT.md."""
    ctx = phase_dir / "CONTEXT.md"
    if not ctx.is_file():
        return set()
    text = ctx.read_text(encoding="utf-8", errors="replace")
    decisions: set[str] = set()
    for m in DECISION_RE.finditer(text):
        decisions.add(m.group(0))
    return decisions


def _spec_files(phase_dir: Path) -> list[Path]:
    """Spec files: from CODEGEN-MANIFEST.json if present, else glob."""
    manifest = phase_dir / "CODEGEN-MANIFEST.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        specs = data.get("playwright_specs") or data.get("specs") or []
        out: list[Path] = []
        for entry in specs:
            path = entry.get("path") if isinstance(entry, dict) else str(entry)
            if not path:
                continue
            p = Path(path)
            if not p.is_absolute():
                # Try multiple roots
                for root in (Path.cwd(), phase_dir, phase_dir.parent.parent.parent):
                    cand = root / path
                    if cand.is_file():
                        p = cand
                        break
            if p.is_file():
                out.append(p)
        return out
    # Fallback glob
    return list(Path("tests").rglob("*.spec.ts")) + list(Path("tests").rglob("*.spec.js"))


def _decisions_covered(spec_files: list[Path]) -> set[str]:
    """Union of D-XX IDs cited across all spec files."""
    covered: set[str] = set()
    for sf in spec_files:
        try:
            text = sf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in DECISION_RE.finditer(text):
            covered.add(m.group(0))
    return covered


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir")
    ap.add_argument("--strict", action="store_true",
                    help="FAIL if any D-XX uncovered (default: warn only)")
    ap.add_argument("--allow-uncovered",
                    help="comma-separated D-IDs allowed to be uncovered (debt)")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    decisions = _parse_context_decisions(phase_dir)
    if not decisions:
        print(f"ℹ Batch 38: no D-XX decisions in CONTEXT.md at {phase_dir} — nothing to verify")
        return 0

    specs = _spec_files(phase_dir)
    if not specs:
        print(f"⛔ Batch 38: no spec files found for phase {args.phase}", file=sys.stderr)
        return 1

    covered = _decisions_covered(specs)
    uncovered = sorted(decisions - covered)
    allowed: set[str] = set()
    if args.allow_uncovered:
        allowed = {s.strip() for s in args.allow_uncovered.split(",") if s.strip()}

    real_uncovered = [d for d in uncovered if d not in allowed]

    print(f"Batch 38: {len(decisions)} decisions in CONTEXT, {len(covered)} covered, "
          f"{len(uncovered)} uncovered ({len(real_uncovered)} after allow-list)")

    if real_uncovered:
        print(f"  uncovered: {', '.join(real_uncovered)}", file=sys.stderr)
        for d in real_uncovered:
            print(f"    {d}: no spec file mentions this decision", file=sys.stderr)
        if args.strict:
            print(f"⛔ Batch 38 --strict: {len(real_uncovered)} decision(s) uncovered", file=sys.stderr)
            return 1
        print(f"⚠ Batch 38: {len(real_uncovered)} uncovered (warn; use --strict to BLOCK)",
              file=sys.stderr)
    else:
        print(f"✓ Batch 38: all {len(decisions)} decisions covered by spec(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
