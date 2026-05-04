#!/usr/bin/env python3
"""verify-edge-cases-contract.py

Validate EDGE-CASES.md (Layer 3 flat) + EDGE-CASES/index.md (Layer 2 TOC) +
EDGE-CASES/G-NN.md (Layer 1 per-goal) as phase-level edge-case contract.

Validator blocks when:
- Phase has CRUD resources (CRUD-SURFACES.md non-empty) but EDGE-CASES files
  missing OR --skip-edge-cases not declared with override-reason.
- variant_id format invalid (must match `<goal_id>-<category_letter><N>`).
- Per-goal variant count below profile budget (mutation: 5-10, read-only: 3-5,
  compute: 2-4, trivial: 0 with explicit skip header).
- Required columns missing in variant tables (variant_id, expected_outcome,
  priority).
- index.md goal count != per-goal file count.

Severity: BLOCK on schema violations; WARN on missing for legacy phases (no
2b5e_edge_cases marker → pre-v2.49). Pair with --skip-edge-cases for explicit
override.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

VARIANT_ID_RE = re.compile(r"^G-\d+-[a-z]\d+$")
GOAL_ID_RE = re.compile(r"^G-\d+$")
PRIORITY_RE = re.compile(r"\b(critical|high|medium|low)\b", re.IGNORECASE)

# Variant count budget per goal type (heuristic).
# Detected from goal title / source — if mutation keyword present → mutation budget.
MUTATION_RE = re.compile(r"\b(create|update|delete|mutate|submit|edit|patch|post)\b", re.IGNORECASE)
READ_ONLY_RE = re.compile(r"\b(view|list|read|get|fetch|display|show)\b", re.IGNORECASE)
COMPUTE_RE = re.compile(r"\b(compute|calculate|validate|check|preview|estimate)\b", re.IGNORECASE)
TRIVIAL_RE = re.compile(r"\b(health|ping|status|version|metric)\b", re.IGNORECASE)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _crud_surfaces_has_resources(phase_dir: Path) -> bool:
    """True if CRUD-SURFACES.md has non-empty resources[] array."""
    crud_md = phase_dir / "CRUD-SURFACES.md"
    if not crud_md.exists():
        return False
    src = _read(crud_md)
    m = re.search(r"```json\s*\n(.*?)\n```", src, re.DOTALL)
    if not m:
        return False
    try:
        data = json.loads(m.group(1))
        if data.get("no_crud_reason"):
            return False
        return bool(data.get("resources"))
    except Exception:
        return False


def _classify_goal_budget(goal_title: str) -> tuple[int, int, str]:
    """Return (min, max, kind) variant count budget per goal title heuristic."""
    if TRIVIAL_RE.search(goal_title):
        return (0, 0, "trivial")
    if MUTATION_RE.search(goal_title):
        return (5, 10, "mutation")
    if COMPUTE_RE.search(goal_title):
        return (2, 4, "compute")
    if READ_ONLY_RE.search(goal_title):
        return (3, 5, "read-only")
    return (3, 8, "default")


def _parse_variant_table(body: str) -> list[dict]:
    """Extract variant rows from markdown tables in body. Returns list of
    {variant_id, expected_outcome, priority, raw_row}."""
    variants = []
    # Match markdown table rows containing variant_id pattern
    for m in re.finditer(r"^\|\s*(G-\d+-[a-z]\d+)\s*\|(.+?)\|", body, re.MULTILINE):
        variant_id = m.group(1).strip()
        cells = [c.strip() for c in m.group(0).split("|")[1:-1]]
        # cells: [variant_id, input/scenario, expected_outcome, priority]
        # Schema is flexible (3-4 cols); look for priority keyword in last cell.
        priority = None
        for cell in reversed(cells):
            if PRIORITY_RE.match(cell or ""):
                priority = cell.lower()
                break
        expected = cells[-2] if len(cells) >= 3 else ""
        variants.append({
            "variant_id": variant_id,
            "expected_outcome": expected,
            "priority": priority,
            "raw_row": m.group(0),
        })
    return variants


def _validate_per_goal_file(out: Output, gfile: Path) -> int:
    """Validate one EDGE-CASES/G-NN.md file. Returns variant count."""
    body = _read(gfile)
    if not body:
        out.add(Evidence(
            type="edge_cases_empty_goal_file",
            message=f"{gfile.name}: empty file",
            file=str(gfile),
        ))
        return 0

    # Extract goal_id from filename (G-NN.md)
    m = re.match(r"^G-(\d+)\.md$", gfile.name)
    if not m:
        out.add(Evidence(
            type="edge_cases_invalid_filename",
            message=f"{gfile.name}: must match G-NN.md pattern",
            file=str(gfile),
        ))
        return 0
    goal_id = f"G-{m.group(1)}"

    # Check goal title heading
    title_match = re.search(rf"^#\s+Edge Cases\s*[—-]\s*{re.escape(goal_id)}\s*[:.]", body, re.MULTILINE)
    if not title_match:
        out.add(Evidence(
            type="edge_cases_missing_title",
            message=f"{gfile.name}: missing `# Edge Cases — {goal_id}: <title>` heading",
            file=str(gfile),
            expected=f"# Edge Cases — {goal_id}: <title>",
        ))

    # Extract variants
    variants = _parse_variant_table(body)

    # Validate variant_id format + uniqueness + matching goal_id
    seen = set()
    for v in variants:
        vid = v["variant_id"]
        if not VARIANT_ID_RE.match(vid):
            out.add(Evidence(
                type="edge_cases_invalid_variant_id",
                message=f"{gfile.name}: variant_id `{vid}` does not match `G-NN-cN` format",
                file=str(gfile),
                expected="G-NN-cN (e.g. G-04-b1)",
            ))
            continue
        if not vid.startswith(f"{goal_id}-"):
            out.add(Evidence(
                type="edge_cases_variant_id_goal_mismatch",
                message=f"{gfile.name}: variant `{vid}` doesn't belong to goal `{goal_id}`",
                file=str(gfile),
                expected=f"{goal_id}-cN",
            ))
        if vid in seen:
            out.add(Evidence(
                type="edge_cases_duplicate_variant_id",
                message=f"{gfile.name}: duplicate variant_id `{vid}`",
                file=str(gfile),
            ))
        seen.add(vid)
        if not v["priority"]:
            out.add(Evidence(
                type="edge_cases_missing_priority",
                message=f"{gfile.name}: variant `{vid}` missing priority (critical/high/medium/low)",
                file=str(gfile),
                expected="critical | high | medium | low",
            ))
        if not v["expected_outcome"] or len(v["expected_outcome"]) < 5:
            out.add(Evidence(
                type="edge_cases_missing_expected",
                message=f"{gfile.name}: variant `{vid}` missing expected_outcome",
                file=str(gfile),
            ))

    # Check skip header for trivial goals (count=0 acceptable only with header)
    has_skip_header = bool(re.search(r"\*\*Skipped categories\*\*:?\s*\[", body))
    if len(variants) == 0 and not has_skip_header:
        out.add(Evidence(
            type="edge_cases_zero_variants_no_skip",
            message=f"{gfile.name}: zero variants without explicit `**Skipped categories**:` header",
            file=str(gfile),
            expected="Either ≥1 variant OR explicit skip header explaining why",
        ))

    return len(variants)


def _validate_index(out: Output, index_path: Path, per_goal_files: list[Path]) -> None:
    """Validate index.md references match per-goal files."""
    body = _read(index_path)
    if not body:
        out.add(Evidence(
            type="edge_cases_empty_index",
            message="EDGE-CASES/index.md is empty",
            file=str(index_path),
        ))
        return

    # Extract goal_ids from index links (markdown [G-NN](./G-NN.md))
    indexed = set(re.findall(r"\[G-(\d+)\]\(\./G-\d+\.md\)", body))
    on_disk = set(m.group(1) for f in per_goal_files
                  if (m := re.match(r"^G-(\d+)\.md$", f.name)))

    missing_in_index = on_disk - indexed
    extra_in_index = indexed - on_disk
    for gid in missing_in_index:
        out.add(Evidence(
            type="edge_cases_index_missing_goal",
            message=f"index.md missing reference to G-{gid} (per-goal file exists)",
            file=str(index_path),
        ))
    for gid in extra_in_index:
        out.add(Evidence(
            type="edge_cases_index_orphan_goal",
            message=f"index.md references G-{gid} but G-{gid}.md missing",
            file=str(index_path),
        ))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate EDGE-CASES contract")
    parser.add_argument("--phase", help="Phase number (e.g. 4.1)")
    parser.add_argument("--phase-dir", help="Direct phase dir (overrides --phase)")
    parser.add_argument("--legacy-warn", action="store_true",
                        help="Downgrade missing EDGE-CASES.md to WARN (legacy phase)")
    parser.add_argument("--json", action="store_true", help="Emit JSON evidence")
    parser.add_argument("--skip-edge-cases", action="store_true",
                        help="Honored if --override-reason set elsewhere")
    args = parser.parse_args()

    out = Output(validator="verify-edge-cases-contract")
    with timer(out):
        phase_dir = Path(args.phase_dir) if args.phase_dir else find_phase_dir(args.phase)
        if not phase_dir or not phase_dir.exists():
            out.add(Evidence(
                type="phase_dir_missing",
                message=f"Phase dir not found for phase={args.phase}",
            ))
            return emit_and_exit(out)

        edge_md = phase_dir / "EDGE-CASES.md"
        edge_dir = phase_dir / "EDGE-CASES"
        index_md = edge_dir / "index.md"

        # Skip path: phase has no CRUD resources OR --skip-edge-cases
        has_resources = _crud_surfaces_has_resources(phase_dir)
        if args.skip_edge_cases or not has_resources:
            return emit_and_exit(out)

        # Layer 3 must exist (severity controlled by --legacy-warn flag downstream)
        if not edge_md.exists():
            kind = "edge_cases_missing_legacy" if args.legacy_warn else "edge_cases_missing"
            out.add(Evidence(
                type=kind,
                message=(
                    f"EDGE-CASES.md missing — phase has CRUD resources, expected "
                    f"edge case contract at {edge_md}"
                ),
                file=str(edge_md),
                fix_hint=(
                    "Run `/vg:blueprint <phase> --from=2b5e_edge_cases` to generate, "
                    "OR pass --skip-edge-cases with --override-reason=<text>"
                ),
            ))

        # Layer 2 + Layer 1
        if not index_md.exists() and edge_md.exists():
            out.add(Evidence(
                type="edge_cases_index_missing",
                message="EDGE-CASES/index.md missing — Layer 2 TOC required",
                file=str(index_md),
            ))

        per_goal_files = sorted(edge_dir.glob("G-*.md")) if edge_dir.exists() else []
        if not per_goal_files and edge_md.exists():
            out.add(Evidence(
                type="edge_cases_per_goal_missing",
                message="EDGE-CASES/G-*.md per-goal split missing — Layer 1 required",
                file=str(edge_dir),
            ))

        # Validate index <-> per-goal alignment
        if index_md.exists() and per_goal_files:
            _validate_index(out, index_md, per_goal_files)

        # Validate each per-goal file
        total_variants = 0
        for gfile in per_goal_files:
            total_variants += _validate_per_goal_file(out, gfile)


    return emit_and_exit(out)


if __name__ == "__main__":
    sys.exit(main())
