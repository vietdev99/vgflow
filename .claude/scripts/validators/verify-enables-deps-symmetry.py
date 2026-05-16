#!/usr/bin/env python3
"""B62-pre (audit ID-2): verify enables[] vs Dependencies[] symmetry.

B62 adds `enables: [G-XX]` (forward) edge field to TEST-GOAL frontmatter.
Existing `Dependencies: [G-XX]` field encodes backward edge. If both
populated inconsistently, FLOW-SPEC walker (contracts-overview.md
lines 549-602) loops or double-counts chains.

Truth-source rule: `Dependencies[]` is CANONICAL. `enables[]` is a
forward-edge declaration that MUST be consistent with the corresponding
`Dependencies[]` on the target goal.

For each goal G-A with `enables: [G-B]`:
  assert G-B has `Dependencies` containing G-A.

For each goal G-A with `Dependencies: [G-B]`:
  no symmetric requirement on G-B (forward is optional, backward
  is canonical — gradual migration friendly).

Usage:
  verify-enables-deps-symmetry.py --phase 7
  verify-enables-deps-symmetry.py --phase 7 --strict
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path


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


# Match goal heading "## G-XX" or "### G-XX" + capture id
GOAL_HEADING_RE = re.compile(r"^#{2,3}\s+(G-[\w.-]+)\b", re.M)
# Match frontmatter-like fields: `**Dependencies:** G-01, G-02` or `enables: [G-01, G-02]`
DEPS_FIELD_RE = re.compile(
    r"(?:\*\*)?[Dd]ependencies:?(?:\*\*)?\s*\[?([^\]\n]*)\]?",
    re.M,
)
ENABLES_FIELD_RE = re.compile(
    r"(?:\*\*)?enables:?(?:\*\*)?\s*\[?([^\]\n]*)\]?",
    re.M,
)
GOAL_ID_RE = re.compile(r"\bG-[\w.-]+\b")


def _parse_field_values(block: str, field_name: str) -> list[str]:
    """Extract goal-ids from a field that may be inline OR YAML block-list.

    NF-2 fix: support both styles.
      Inline:  `Dependencies: [G-01, G-02]` or `Dependencies: G-01, G-02`
      Block:   `Dependencies:\\n  - G-01\\n  - G-02`
    """
    out: list[str] = []
    # Match field line (with optional **bold**), capture rest of line + continuation
    field_re = re.compile(
        rf"(?:\*\*)?{re.escape(field_name)}:?(?:\*\*)?\s*(.*?)(?=^\S|^##|\Z)",
        re.M | re.DOTALL | re.I,
    )
    for m in field_re.finditer(block):
        # Limit lookahead to ~10 lines max to avoid greedy match across goals
        snippet = m.group(1)[:600]
        # Stop at next top-level (non-indented) line that's NOT a `- G-` row
        lines = snippet.split("\n")
        chunk_lines: list[str] = []
        first_line = lines[0] if lines else ""
        chunk_lines.append(first_line)
        for ln in lines[1:]:
            stripped = ln.lstrip()
            if not stripped:
                continue
            # YAML block-list item OR indented continuation
            if ln.startswith((" ", "\t", "-")) or stripped.startswith("- "):
                chunk_lines.append(ln)
                continue
            # New field or heading → stop
            break
        chunk = "\n".join(chunk_lines)
        out.extend(GOAL_ID_RE.findall(chunk))
    return out


def _parse_goals(text: str) -> dict[str, dict]:
    """Parse TEST-GOALS.md into {goal_id: {enables: [...], deps: [...]}}.

    Splits text by goal headings (## G-XX). Per block, extracts
    Dependencies + enables in BOTH inline list AND YAML block-list form
    (NF-2 fix from codex replay audit).
    """
    goals: dict[str, dict] = {}
    matches = list(GOAL_HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        gid = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]
        deps = _parse_field_values(block, "Dependencies")
        enables = _parse_field_values(block, "enables")
        # Dedupe + filter self-reference
        goals[gid] = {
            "deps": sorted(set(d for d in deps if d != gid)),
            "enables": sorted(set(e for e in enables if e != gid)),
        }
    return goals


def _check_symmetry(goals: dict[str, dict]) -> list[str]:
    """Return list of asymmetry messages."""
    errors: list[str] = []
    for gid, fields in goals.items():
        for target in fields["enables"]:
            if target not in goals:
                errors.append(
                    f"{gid}.enables=[{target}] but goal {target} not in TEST-GOALS.md"
                )
                continue
            if gid not in goals[target]["deps"]:
                errors.append(
                    f"{gid}.enables=[{target}] but {target}.Dependencies does NOT contain {gid}"
                )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any asymmetry (default: warn)")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    candidates = [
        phase_dir / "TEST-GOALS.md",
        phase_dir / "TEST-GOALS-DISCOVERED.md",
        phase_dir / "TEST-GOALS-EXPANDED.md",
    ]
    bodies: list[str] = []
    for c in candidates:
        if c.is_file():
            # tolerate mixed encodings — em-dash in old phases may be cp1252
            bodies.append(c.read_text(encoding="utf-8", errors="replace"))
    if not bodies:
        print(f"ℹ B62-pre: no TEST-GOALS*.md in {phase_dir} — skipping")
        return 0

    aggregated = "\n".join(bodies)
    goals = _parse_goals(aggregated)
    if not goals:
        print(f"ℹ B62-pre: no goal headings found — skipping")
        return 0

    errors = _check_symmetry(goals)
    enables_count = sum(1 for g in goals.values() if g["enables"])
    deps_count = sum(1 for g in goals.values() if g["deps"])
    print(f"B62-pre: {len(goals)} goal(s), {enables_count} with enables[], "
          f"{deps_count} with Dependencies[]; {len(errors)} asymmetries")
    if errors:
        for e in errors:
            print(f"  ASYMMETRY: {e}", file=sys.stderr)
        if args.strict:
            return 1
        print(f"⚠ B62-pre: warn-mode (use --strict to BLOCK)", file=sys.stderr)
    else:
        print(f"✓ B62-pre: enables[]/Dependencies[] symmetry OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
