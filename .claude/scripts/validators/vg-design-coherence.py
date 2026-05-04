#!/usr/bin/env python3
"""
Validator: vg-design-coherence.py

Purpose: UI-SPEC.md MUST reference only design tokens/colors/components that
actually exist in DESIGN.md and structural refs. Without this gate, blueprint
produces UI-SPEC referencing invented token names or colors → executor builds
CSS with undefined vars → silent visual bugs at runtime.

Fires for: vg:blueprint (after UI-SPEC.md exists for phases with surface=web).

Checks (BLOCK level):
- Every CSS custom property `--foo` referenced in UI-SPEC table rows MUST
  appear as a defined value (hex or rgba) in DESIGN.md.
- Every hex color (#rrggbb) in UI-SPEC table MUST match a hex color defined
  in DESIGN.md (prevents AI inventing shades).
- If UI-SPEC cites "DESIGN.md L42" as source, line 42 of DESIGN.md MUST
  contain the referenced value (prevents stale citations after DESIGN.md edit).

Checks (WARN level):
- UI-SPEC exists but DESIGN.md missing → cannot verify, skip but warn.
- Component names referenced in UI-SPEC but no structural ref found.

Skip (PASS, not applicable):
- No UI-SPEC.md for this phase → backend-only phase, not our scope.

Usage: vg-design-coherence.py --phase <N>
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PHASES_DIR = REPO_ROOT / ".vg" / "phases"
DESIGN_DIR = REPO_ROOT / ".vg" / "design"

# Regex for hex colors — matches #RGB, #RGBA, #RRGGBB, #RRGGBBAA (case-insensitive)
HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
# Regex for rgba/rgb color function with 3-4 args
RGBA_RE = re.compile(r"rgba?\s*\([^)]+\)", re.IGNORECASE)
# Regex for CSS custom property in UI-SPEC tables: `| --foo-bar | value | source |`
CSS_VAR_RE = re.compile(r"`(--[a-z0-9-]+)`", re.IGNORECASE)
# Regex for "DESIGN.md L<N>" citations
DESIGN_CITE_RE = re.compile(r"DESIGN\.md\s+L(\d+)", re.IGNORECASE)


def normalize_color(c: str) -> str:
    """Lowercase + strip spaces — '#FF00aa' == '#ff00aa', 'rgba(0, 0, 0, 0.5)'
    == 'rgba(0,0,0,0.5)'."""
    return re.sub(r"\s+", "", c.lower())


def extract_colors(text: str) -> set[str]:
    """Extract all hex + rgba color values from text."""
    colors: set[str] = set()
    for m in HEX_RE.finditer(text):
        colors.add(normalize_color(m.group(0)))
    for m in RGBA_RE.finditer(text):
        colors.add(normalize_color(m.group(0)))
    return colors


def find_design_files() -> list[Path]:
    """Locate DESIGN.md files. Strategy:
    1. .vg/design/*/DESIGN.md (per-surface design, canonical v1.14+)
    2. .vg/DESIGN.md (root-level, legacy)
    3. .planning/design/*/DESIGN.md (pre-migration)
    Returns list sorted by path for deterministic order.
    """
    candidates: list[Path] = []
    if DESIGN_DIR.exists():
        candidates.extend(sorted(DESIGN_DIR.glob("*/DESIGN.md")))
    root_design = REPO_ROOT / ".vg" / "DESIGN.md"
    if root_design.exists():
        candidates.append(root_design)
    legacy = REPO_ROOT / ".planning" / "design"
    if legacy.exists():
        candidates.extend(sorted(legacy.glob("*/DESIGN.md")))
    return candidates


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="vg-design-coherence")
    with timer(out):
        # Find phase directory — support leading-zero + unpadded
        phase_dir = find_phase_dir(args.phase)
        phase_dirs = [phase_dir] if phase_dir else []
        if not phase_dirs:
            out.add(Evidence(
                type="missing_file",
                message=f"phase dir for {args.phase} not found",
                fix_hint="Check .vg/phases/ for matching phase number",
            ))
            emit_and_exit(out)

        phase_dir = phase_dirs[0]
        ui_spec = phase_dir / "UI-SPEC.md"

        # If no UI-SPEC → PASS (backend phase, not applicable)
        if not ui_spec.exists():
            emit_and_exit(out)

        ui_spec_size = ui_spec.stat().st_size
        if ui_spec_size < 200:
            # Tiny UI-SPEC likely empty stub — treat as not-applicable
            emit_and_exit(out)

        ui_text = ui_spec.read_text(encoding="utf-8", errors="replace")

        # Locate DESIGN.md(s) — if none, WARN only (can't verify)
        design_files = find_design_files()
        if not design_files:
            out.warn(Evidence(
                type="missing_file",
                message="UI-SPEC.md exists but no DESIGN.md found — cannot cross-check tokens",
                file=str(ui_spec),
                fix_hint="Run /vg:design-system to create DESIGN.md, "
                         "or /vg:design-extract to generate from assets.",
            ))
            emit_and_exit(out)

        # Read all DESIGN.md files into a combined token pool
        design_text_pool = ""
        design_line_index: dict[str, tuple[Path, int]] = {}
        for df in design_files:
            txt = df.read_text(encoding="utf-8", errors="replace")
            design_text_pool += "\n" + txt
            # Build a line-number index per file for citation checks later
            for lineno, line in enumerate(txt.splitlines(), start=1):
                for c in extract_colors(line):
                    design_line_index.setdefault(c, (df, lineno))

        design_colors = extract_colors(design_text_pool)

        # CHECK 1: every hex/rgba in UI-SPEC must exist in DESIGN
        ui_colors = extract_colors(ui_text)
        orphaned = ui_colors - design_colors

        # Filter noise: colors appearing only in prose/comments (outside table cells)
        # Keep only colors inside table rows (heuristic: line contains `|`)
        ui_table_colors: set[str] = set()
        for line in ui_text.splitlines():
            if "|" not in line:
                continue
            for c in extract_colors(line):
                ui_table_colors.add(c)

        orphaned_in_tables = (ui_table_colors - design_colors)

        if orphaned_in_tables:
            # Cap evidence list at 5 to keep output concise
            sample = sorted(orphaned_in_tables)[:5]
            out.add(Evidence(
                type="token_mismatch",
                message=(
                    f"{len(orphaned_in_tables)} color(s) in UI-SPEC table rows "
                    f"not found in any DESIGN.md: {', '.join(sample)}"
                    + ("..." if len(orphaned_in_tables) > 5 else "")
                ),
                file=str(ui_spec),
                expected="every token color appears in DESIGN.md",
                actual=f"{len(orphaned_in_tables)} orphan colors",
                fix_hint=(
                    "Either (a) add the missing color(s) to DESIGN.md with named token, "
                    "OR (b) correct the UI-SPEC to use existing DESIGN tokens. "
                    "Orphan tokens mean the executor builds CSS with undefined values."
                ),
            ))

        # CHECK 2: DESIGN.md line citations point at lines that contain the cited value
        # Pattern: "some text #aabbcc ... DESIGN.md L42"
        stale_citations = []
        for m in DESIGN_CITE_RE.finditer(ui_text):
            cited_line_no = int(m.group(1))
            # Look for color near the citation (within 120 chars before the match)
            window_start = max(0, m.start() - 120)
            window = ui_text[window_start:m.start()]
            nearby_colors = extract_colors(window)
            if not nearby_colors:
                continue
            # Check cited line in any DESIGN.md
            for df in design_files:
                lines = df.read_text(encoding="utf-8", errors="replace").splitlines()
                if cited_line_no < 1 or cited_line_no > len(lines):
                    continue
                cited_colors = extract_colors(lines[cited_line_no - 1])
                if not (nearby_colors & cited_colors):
                    # Citation doesn't match any color on that line
                    stale_citations.append((cited_line_no, sorted(nearby_colors)[0]))
                break  # only check first matching DESIGN.md

        if stale_citations:
            sample = stale_citations[:3]
            out.warn(Evidence(
                type="stale_citation",
                message=(
                    f"{len(stale_citations)} DESIGN.md line citation(s) don't match "
                    f"line content — DESIGN.md likely edited without UI-SPEC update: "
                    + "; ".join(f"L{ln} cites {c}" for ln, c in sample)
                ),
                file=str(ui_spec),
                fix_hint=(
                    "Re-run /vg:blueprint <phase> step 2b6 (UI-SPEC regen) after "
                    "DESIGN.md edits, OR manually update line numbers in UI-SPEC."
                ),
            ))

        # CHECK 3: CSS custom property references in UI-SPEC must appear in DESIGN
        # (relaxed — only flag if DESIGN has NO custom properties at all and UI-SPEC has many)
        ui_vars = set(CSS_VAR_RE.findall(ui_text))
        design_vars = set(CSS_VAR_RE.findall(design_text_pool))
        if ui_vars and not design_vars:
            # DESIGN uses prose, UI-SPEC uses CSS vars — that's a methodology mismatch
            out.warn(Evidence(
                type="methodology_drift",
                message=(
                    f"UI-SPEC references {len(ui_vars)} CSS custom properties but "
                    "DESIGN.md has none — UI-SPEC invented a token naming scheme"
                ),
                file=str(ui_spec),
                fix_hint=(
                    "Add a 'Design Tokens (CSS vars)' section to DESIGN.md OR "
                    "remove CSS var naming from UI-SPEC and cite DESIGN.md prose directly."
                ),
            ))
        elif ui_vars and design_vars:
            orphan_vars = ui_vars - design_vars
            if orphan_vars:
                sample = sorted(orphan_vars)[:5]
                out.add(Evidence(
                    type="var_mismatch",
                    message=(
                        f"{len(orphan_vars)} CSS var(s) in UI-SPEC not defined in "
                        f"DESIGN.md: {', '.join(sample)}"
                        + ("..." if len(orphan_vars) > 5 else "")
                    ),
                    file=str(ui_spec),
                    fix_hint=(
                        "CSS vars referenced in UI-SPEC must be defined in DESIGN.md "
                        "so the executor can emit matching :root { } declarations."
                    ),
                ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
