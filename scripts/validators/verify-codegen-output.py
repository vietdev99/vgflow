#!/usr/bin/env python3
"""
Validator: verify-codegen-output.py

v2.7 Phase B (2026-04-26): output gate for the `vg-codegen-interactive`
skill. Runs after Sonnet returns a Playwright .spec.ts file and BEFORE
the orchestrator writes it to disk.

Asserts the spec is structurally compliant with SPEC-B § 3 + § 4 + § 6:

  1. Header line begins with `// AUTO-GENERATED` (BLOCK on miss).
  2. Imports include the 7 required helpers from a path matching
     `helpers/interactive` (BLOCK on any missing).
  3. No raw `page.locator(` outside the import block (BLOCK on hit) —
     all selectors must go through helpers.
  4. Test count matches the deterministic formula
     filter_value_tests + filter_reload_tests + sort_dir_tests
     + pagination_tests + search_tests
     computed from the input interactive_controls YAML (BLOCK on drift).
  5. No `waitForLoadState('networkidle')` (BLOCK).
  6. No `page.evaluate(` (WARN — escape hatch flagged for review).
  7. ROUTE constant matches the `--route` arg (BLOCK).
  8. Every `expectAssertion(rows, '<expr>', ...)` uses one of the 5
     SPEC-B § 4 DSL grammar forms (BLOCK on unsupported expr).
  9. File basename matches `{goal_id slug}.url-state.spec.ts` where
     slug = goal_id.lower() (BLOCK on mismatch).

Usage:
  verify-codegen-output.py \
    --spec-path <path-to-spec.ts> \
    --goal-id <G-XXX> \
    --route <url> \
    --interactive-controls-yaml <path-to-yaml>

Exit codes:
  0 PASS or WARN-only
  1 BLOCK
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

REQUIRED_HELPERS = [
    "applyFilter",
    "applySort",
    "applyPagination",
    "applySearch",
    "readUrlParams",
    "readVisibleRows",
    "expectAssertion",
]

# DSL grammar — must match interactive-helpers.template.ts exactly.
DSL_PATTERNS = [
    re.compile(r"^rows\[\*\]\.[a-zA-Z_][a-zA-Z0-9_]*\s*===\s*param$"),
    re.compile(r"^rows\[\*\]\.[a-zA-Z_][a-zA-Z0-9_]*\.includes\(param\)$"),
    re.compile(r"^rows\[\*\]\.[a-zA-Z_][a-zA-Z0-9_]*\s+in\s+\[.+\]$"),
    re.compile(r"^rows\s+monotonically\s+ordered\s+by\s+[a-zA-Z_][a-zA-Z0-9_]*$"),
    re.compile(r"^rows\.length\s*<=\s*\d+$"),
]


def _slugify(goal_id: str) -> str:
    return goal_id.lower()


def _expected_test_count(controls: dict) -> int:
    """SPEC-B § 3 deterministic formula."""
    if not controls:
        return 0
    n = 0
    filters = controls.get("filters") or []
    for f in filters:
        values = f.get("values") or []
        n += len(values)        # one test per value
        n += 1                  # plus one reload-persists test per filter
    sort_block = controls.get("sort")
    if sort_block:
        # sort can be a list of column blocks or a single dict
        if isinstance(sort_block, list):
            for s in sort_block:
                directions = s.get("directions") or []
                n += len(directions)
        elif isinstance(sort_block, dict):
            directions = sort_block.get("directions") or []
            n += len(directions)
    if controls.get("pagination"):
        n += 1
    if controls.get("search"):
        n += 1
    return n


def _strip_imports(text: str) -> tuple[str, str]:
    """Split file into (imports_block, body). Imports = consecutive top
    `import {...} from '...';` statements + leading comments/blank lines."""
    lines = text.splitlines(keepends=True)
    end = 0
    in_import = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//") or stripped == "":
            end = i + 1
            continue
        if stripped.startswith("import "):
            in_import = True
            end = i + 1
            # multi-line import — consume until ';' encountered
            if ";" not in stripped:
                for j in range(i + 1, len(lines)):
                    end = j + 1
                    if ";" in lines[j]:
                        break
            continue
        if in_import:
            break
    return "".join(lines[:end]), "".join(lines[end:])


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0] if __doc__ else "verify-codegen-output",
        allow_abbrev=False,
    )
    ap.add_argument("--spec-path", required=True)
    ap.add_argument("--goal-id", required=True)
    ap.add_argument("--route", required=True)
    ap.add_argument("--interactive-controls-yaml", required=True)
    args = ap.parse_args()

    out = Output(validator="verify-codegen-output")
    with timer(out):
        spec_path = Path(args.spec_path)
        if not spec_path.exists():
            out.add(Evidence(
                type="codegen_output_missing",
                message=f"Spec file not found: {spec_path}",
                fix_hint="Check vg-codegen-interactive returned content and orchestrator wrote it to a temp path before invoking validator.",
            ))
            emit_and_exit(out)

        # Check 9: filename match.
        expected_basename = f"{_slugify(args.goal_id)}.url-state.spec.ts"
        if spec_path.name != expected_basename:
            out.add(Evidence(
                type="codegen_filename_mismatch",
                message=(
                    f"Spec basename '{spec_path.name}' does not match expected "
                    f"'{expected_basename}' (goal_id slug + .url-state.spec.ts)."
                ),
                expected=expected_basename,
                actual=spec_path.name,
                fix_hint="Re-prompt codegen with the correct output_path or rename before write.",
            ))

        text = spec_path.read_text(encoding="utf-8", errors="replace")
        imports_block, body = _strip_imports(text)

        # Check 1: AUTO-GENERATED header.
        first_nonblank = next(
            (ln for ln in text.splitlines() if ln.strip()),
            "",
        )
        if not first_nonblank.lstrip().startswith("// AUTO-GENERATED"):
            out.add(Evidence(
                type="codegen_missing_auto_generated_header",
                message=(
                    "Spec must start with `// AUTO-GENERATED` header so editors "
                    "and reviewers know not to hand-edit it."
                ),
                fix_hint="Re-prompt codegen — first line must begin `// AUTO-GENERATED ...`.",
            ))

        # Check 2: required helper imports.
        missing_helpers = [
            h for h in REQUIRED_HELPERS
            if not re.search(rf"\b{re.escape(h)}\b", imports_block)
        ]
        if missing_helpers:
            out.add(Evidence(
                type="codegen_missing_helper_import",
                message=(
                    f"Required helpers missing from import block: "
                    f"{', '.join(missing_helpers)}"
                ),
                expected=REQUIRED_HELPERS,
                actual=[h for h in REQUIRED_HELPERS if h not in missing_helpers],
                fix_hint="Re-prompt codegen — every spec must import the 7 helpers from `helpers/interactive`.",
            ))

        # Confirm the import path looks like helpers/interactive.
        if "helpers/interactive" not in imports_block:
            out.add(Evidence(
                type="codegen_helper_import_path_wrong",
                message=(
                    "Helper import path must include 'helpers/interactive' "
                    "(e.g. ../helpers/interactive)."
                ),
                fix_hint="Re-prompt codegen — only the canonical helper path is allowed.",
            ))

        # Check 3: no raw page.locator( in body.
        if re.search(r"\bpage\.locator\s*\(", body):
            out.add(Evidence(
                type="codegen_raw_locator_in_body",
                message=(
                    "Raw `page.locator(` found outside the import block. "
                    "All selectors must go through helpers."
                ),
                fix_hint="Re-prompt codegen — replace direct locators with applyFilter/applySort/etc.",
            ))

        # Check 4: deterministic test count.
        controls_yaml_path = Path(args.interactive_controls_yaml)
        controls: dict | None = None
        if controls_yaml_path.exists():
            try:
                raw = yaml.safe_load(
                    controls_yaml_path.read_text(encoding="utf-8")
                )
                # Accept either a bare interactive_controls block or a
                # full goal frontmatter wrapping it.
                if isinstance(raw, dict):
                    controls = raw.get("interactive_controls") or raw
            except yaml.YAMLError as exc:
                out.add(Evidence(
                    type="codegen_input_yaml_malformed",
                    message=f"interactive_controls YAML failed to parse: {exc}",
                    fix_hint="Caller must pass a parseable YAML file.",
                ))

        expected_n = _expected_test_count(controls or {})
        actual_tests = re.findall(r"^\s*test\(\s*[`'\"]", body, re.MULTILINE)
        actual_n = len(actual_tests)
        if expected_n > 0 and actual_n != expected_n:
            out.add(Evidence(
                type="codegen_test_count_mismatch",
                message=(
                    f"Spec contains {actual_n} test() blocks but the "
                    f"interactive_controls YAML implies {expected_n} per the "
                    f"deterministic formula (filter values + filter reloads + "
                    f"sort directions + pagination + search)."
                ),
                expected=expected_n,
                actual=actual_n,
                fix_hint="Re-prompt codegen with explicit count breakdown so Sonnet emits the missing/extra cases.",
            ))

        # Check 5: forbid networkidle.
        if "waitForLoadState('networkidle')" in body or 'waitForLoadState("networkidle")' in body:
            out.add(Evidence(
                type="codegen_networkidle_forbidden",
                message=(
                    "waitForLoadState('networkidle') is forbidden — SPA polls "
                    "never settle and tests hang."
                ),
                fix_hint="Re-prompt codegen — wait for explicit URL change or DOM signal instead.",
            ))

        # Check 6: page.evaluate is a soft escape hatch (WARN only).
        if "page.evaluate(" in body:
            out.warn(Evidence(
                type="codegen_page_evaluate_warning",
                message=(
                    "page.evaluate( found — generated specs should read state "
                    "from the DOM via helpers, not via in-page JS."
                ),
                fix_hint="Prefer readUrlParams / readVisibleRows over page.evaluate when possible.",
            ))

        # Check 7: ROUTE constant matches --route arg.
        route_match = re.search(
            r"^\s*const\s+ROUTE\s*=\s*['\"]([^'\"]+)['\"]",
            text, re.MULTILINE,
        )
        if not route_match:
            out.add(Evidence(
                type="codegen_route_constant_missing",
                message="No `const ROUTE = '...';` declaration found in spec.",
                fix_hint="Re-prompt codegen — every spec must declare ROUTE constant per SPEC-B § 3.",
            ))
        elif route_match.group(1) != args.route:
            out.add(Evidence(
                type="codegen_route_mismatch",
                message=(
                    f"Spec ROUTE='{route_match.group(1)}' does not match "
                    f"--route='{args.route}' from RUNTIME-MAP."
                ),
                expected=args.route,
                actual=route_match.group(1),
                fix_hint="Re-prompt codegen with the correct route from RUNTIME-MAP[goal_id].url.",
            ))

        # Check 8: every expectAssertion uses a DSL grammar form.
        for m in re.finditer(
            r"expectAssertion\s*\(\s*rows\s*,\s*['\"`]([^'\"`]+)['\"`]",
            body,
        ):
            expr = m.group(1).strip()
            if not any(p.match(expr) for p in DSL_PATTERNS):
                out.add(Evidence(
                    type="codegen_unsupported_assertion_dsl",
                    message=(
                        f"expectAssertion expression '{expr}' is not in the "
                        f"5 supported DSL grammar forms (SPEC-B § 4)."
                    ),
                    actual=expr,
                    fix_hint="Re-prompt codegen — use one of: rows[*].FIELD === param, rows[*].FIELD.includes(param), rows[*].FIELD in [...], rows monotonically ordered by FIELD, rows.length <= N.",
                ))

        emit_and_exit(out)


if __name__ == "__main__":
    main()
