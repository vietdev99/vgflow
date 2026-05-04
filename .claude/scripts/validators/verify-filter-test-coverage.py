#!/usr/bin/env python3
"""
Validator: verify-filter-test-coverage.py — Phase 15 D-16

Asserts the codegen extension (vg-codegen-interactive skill, Phase 15 T6.1)
generated the full Filter + Pagination Test Rigor Pack per declared
interactive controls in TEST-GOALS.

Matrix expected (per D-16 lock):
  Filter  — 14 cases per filter control:
    coverage:        cardinality_enum, pairwise_combinatorial, boundary_values, empty_state    (4)
    stress:          toggle_storm, spam_click_debounce, in_flight_cancellation                  (3)
    state_integrity: filter_sort_pagination, url_sync, cross_route_persistence                  (3)
    edge:            xss_sanitize, empty_result, error_500_handling                             (3)
    + reserved: 1 buffer for future addition
  Pagination — 18 cases per pagination control (filter + URL sync subgroup):
    navigation:        next, prev, first, last, jump_to_page, page_size_dropdown               (6)
    url_sync:          paste_query_reload, filter_change_resets_page                            (2)
    envelope_contract: meta_total, meta_page, meta_limit, meta_has_next                         (4)
    display:           x_y_of_z_label, empty_single_page, last_partial_page                     (3)
    stress:            spam_next, in_flight_cancel                                              (2)
    edge:              out_of_range_zero, out_of_range_negative, cursor_based_integrity        (1 mandatory + 2 optional)

Logic:
  1. Read TEST-GOALS.md / test-goals.v1.json from phase dir.
  2. Per interactive_controls.filters[*].name → expect 14 test files
     matching tests/<feature>/filter-*.spec.* OR similar pattern.
  3. Per interactive_controls.pagination → expect 18 test files.
  4. Count generated files in phase test output dir.
  5. Shortfall → BLOCK with per-control breakdown.

Usage:  verify-filter-test-coverage.py --phase 7.14.3 [--tests-glob tests/**/*.spec.ts]
Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

# Expected source-level test() blocks per control (D-16 lock):
#   Filter: 13 explicit (cardinality_enum is loop-driven so 1 block × N values
#           at runtime; pairwise + boundary + empty_state + 3 stress + 3
#           state-integrity + 3 edge = 13). 14th slot is reserved for future
#           additions and not enforced.
#   Pagination: 18 mandatory (6 navigation + 2 url_sync + 4 envelope +
#           3 display + 2 stress + 1 edge mandatory). The 2 optional edge
#           sub-cases (negative + cursor) gate behind opts.includeOptional.
EXPECTED_FILTER_CASES = 13
EXPECTED_PAGINATION_CASES = 18

# Default tests glob — projects override via --tests-glob or vg.config.md test_strategy
DEFAULT_TESTS_GLOB = "**/*.{spec,test}.{ts,tsx,js,jsx,mjs,py}"


def _load_test_goals(phase_dir: Path) -> dict:
    # Prefer JSON for structured access; fallback to MD parse if needed.
    json_path = phase_dir / "test-goals.v1.json"
    if json_path.exists():
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    md_path = phase_dir / "TEST-GOALS.md"
    if md_path.exists():
        text = md_path.read_text(encoding="utf-8", errors="ignore")
        # Extract first ```json``` code block
        m = re.search(r"```json\s*\n([\s\S]*?)\n```", text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    return {}


def _count_tests_for_control(
    repo_root: Path, control_name: str, glob_pattern: str, kind: str
) -> int:
    """Count `test(...)` blocks across all spec files whose names mention the
    control slug AND the kind ("filter" / "pagination").

    The Wave 6 codegen layout (vg-codegen-interactive T6.1) emits 4 filter
    group files + 6 pagination group files per control, each containing N
    `test(...)` blocks for its sub-cases. Total blocks per control = 14
    filter + 18 pagination per the D-16 matrix lock.

    Block detection regex matches both `test('...'` and `test("..."` plus
    Playwright `test.skip / test.only` variants. The block name MUST
    contain the kind keyword (`filter` or `pagination`) so cross-control
    tests don't double-count.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", control_name.lower()).strip("-")
    if not slug:
        return 0
    block_re = re.compile(
        r"\btest(?:\.skip|\.only|\.fixme)?\s*\(\s*[`'\"]([^`'\"]+)[`'\"]"
    )
    blocks = 0
    expanded = _expand_braces(glob_pattern)
    for pattern in expanded:
        for p in repo_root.glob(pattern):
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in block_re.finditer(text):
                name = m.group(1).lower()
                if slug in name and kind in name:
                    blocks += 1
    return blocks


def _expand_braces(pattern: str) -> list[str]:
    m = re.search(r"\{([^{}]+)\}", pattern)
    if not m:
        return [pattern]
    options = m.group(1).split(",")
    expanded = [pattern[:m.start()] + opt + pattern[m.end():] for opt in options]
    out: list[str] = []
    for e in expanded:
        out.extend(_expand_braces(e))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--tests-glob", default=DEFAULT_TESTS_GLOB,
                    help="Glob pattern (relative to repo root) for test files")
    args = ap.parse_args()

    out = Output(validator="filter-test-coverage")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            out.add(Evidence(type="missing_file",
                             message=f"Phase dir not found for {args.phase}"))
            emit_and_exit(out)

        goals = _load_test_goals(phase_dir)
        ic = goals.get("interactive_controls", {}) if isinstance(goals, dict) else {}

        filters = ic.get("filters", []) or []
        pagination = ic.get("pagination") or {}

        if not filters and not pagination:
            out.evidence.append(Evidence(
                type="info",
                message="No interactive_controls.filters/pagination declared in TEST-GOALS — nothing to verify.",
            ))
            emit_and_exit(out)

        repo_root = Path.cwd()  # validator run from project root

        for f in filters:
            name = (f.get("name") or "").strip() if isinstance(f, dict) else str(f)
            if not name:
                continue
            count = _count_tests_for_control(repo_root, name, args.tests_glob, "filter")
            if count < EXPECTED_FILTER_CASES:
                out.add(Evidence(
                    type="count_below_threshold",
                    message=(f"Filter '{name}' has {count} test() block(s); "
                             f"expected ≥ {EXPECTED_FILTER_CASES} per D-16 matrix"),
                    expected=EXPECTED_FILTER_CASES,
                    actual=count,
                    fix_hint=(
                        "Run /vg:test step 5d_codegen to generate filter tests via "
                        "vg-codegen-interactive skill (Phase 15 T6.1)."
                    ),
                ))

        if pagination:
            # pagination block may name itself or use first filter as anchor
            name = pagination.get("name") if isinstance(pagination, dict) else "pagination"
            name = name or "pagination"
            count = _count_tests_for_control(repo_root, name, args.tests_glob, "pagination")
            if count < EXPECTED_PAGINATION_CASES:
                out.add(Evidence(
                    type="count_below_threshold",
                    message=(f"Pagination '{name}' has {count} test() block(s); "
                             f"expected ≥ {EXPECTED_PAGINATION_CASES} per D-16 matrix"),
                    expected=EXPECTED_PAGINATION_CASES,
                    actual=count,
                    fix_hint=(
                        "Run /vg:test step 5d_codegen to generate pagination tests "
                        "(navigation+url_sync+envelope+display+stress+edge per D-16)."
                    ),
                ))

        if not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message=(f"Filter+pagination test coverage matches D-16 matrix "
                         f"({len(filters)} filter + "
                         f"{1 if pagination else 0} pagination)"),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
