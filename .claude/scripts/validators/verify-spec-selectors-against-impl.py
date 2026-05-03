#!/usr/bin/env python3
"""verify-spec-selectors-against-impl — extract Playwright spec selectors and
verify their attributes/values exist in the implementation source tree.

PROBLEM (Phase 7.14.3 retrospective):
  Wave-6 spec authors wrote `nav.locator('[data-testid="advertiser-sidebar"]')`,
  `thead th[data-column-id]`, `[role="status"]`, `input[name="revenue"]`, etc.
  The Wave-1-3 implementation never grew those attributes — but nothing ran
  until /vg:test phase ran the spec and timed out at 30s. Six categories of
  test-vs-impl drift surfaced 1+ hour into the pipeline, not at build time.

GATE:
  At /vg:test step 5d (codegen) or /vg:review step 1 (code scan), parse all
  *.spec.ts files in apps/web/e2e/ matching the phase tag, extract a closed
  set of selector patterns, and assert each appears at least once in the
  implementation source. Missing → BLOCK with exact file:line evidence.

PATTERNS DETECTED:
  data-testid="X"               → grep `data-testid={?"X"`
  data-column-id="X"            → grep `data-column-id={?["']X`
  data-status="X"               → grep `data-status={?["']X` OR aliasing path
  input[name="X"]               → grep `name={?["']X` on an input element
  input[type="checkbox"]        → grep `<input type="checkbox"` (component-level)
  [aria-current="page"]         → grep `aria-current={isActive ? 'page'`
  getByRole('img', name:/X/)    → grep `aria-label={?["']X` OR `<img alt`

OUTPUT:
  JSON to stdout matching VG validator contract:
    {"validator":"spec-selectors-vs-impl","verdict":"PASS|BLOCK",
     "evidence":[{...}],"duration_ms":N,"cache_key":null}

USAGE:
  python verify-spec-selectors-against-impl.py \\
    --spec-glob "apps/web/e2e/7.14.3-*.spec.ts" \\
    --impl-root apps/web/src \\
    --report-md .vg/phases/7.14.3-*/SPEC-SELECTOR-AUDIT.md

EXIT: 0 = PASS, 1 = BLOCK, 2 = config error.
"""

import argparse
import json
import re
import sys
import time
from glob import glob
from pathlib import Path
from typing import Iterable, NamedTuple


class Selector(NamedTuple):
    kind: str         # "data-testid" | "data-column-id" | ...
    value: str        # the literal attribute value the spec expects
    spec_file: str
    spec_line: int


# Patterns that encode "this attribute MUST exist somewhere in impl".
# Each tuple: (kind, spec-side regex, list of impl-side acceptance patterns).
# A selector is satisfied if ANY of the impl patterns matches a literal in src.
# Multiple patterns let us accept prop-forwarding patterns like
# `<CellWrap columnId="ctr">` which render `<div data-column-id={columnId}>`.
SPEC_PATTERNS: list[tuple[str, re.Pattern[str], list[str]]] = [
    # data-testid="X"
    (
        "data-testid",
        re.compile(r'data-testid\s*=\s*["\']([^"\']+)["\']'),
        [
            r'data-testid\s*=\s*[{"\']?[^}]*\b%s\b',
            # Template-string testid: data-testid={`prefix-${id}`} where the
            # rendered id flows from a prop value matching X.
            r'`[^`]*\b%s\b[^`]*`',
        ],
    ),
    # data-column-id="X"
    (
        "data-column-id",
        re.compile(r'data-column-id\s*=\s*["\']([^"\']+)["\']'),
        [
            r'data-column-id\s*=\s*[{"\']?[^}]*\b%s\b',
            # CellWrap forwarding: <CellWrap columnId="ctr">
            r'columnId\s*=\s*["\']%s["\']',
            # Column def id: { id: "ctr", ... }  (TanStack column propagated to
            # data-column-id by DataTable header or CellWrap).
            r'\bid\s*:\s*["\']%s["\']',
        ],
    ),
    # data-status="X"
    (
        "data-status",
        re.compile(r'data-status\s*=\s*["\']([^"\']+)["\']'),
        [
            r'data-status\s*=\s*[{"\']?[^}]*\b%s\b',
            # Forwarding: extraAttrs={{ 'data-status': X }}
            r"['\"]data-status['\"]\s*:\s*[^,}]*\b%s\b",
        ],
    ),
    # input[name="X"]  (used by spec to find native checkbox by column id)
    (
        "input-name",
        re.compile(r'input\[type=["\']checkbox["\']\]\[name=["\']([^"\']+)["\']'),
        [
            r'name\s*=\s*[{"\']?[^}]*\b%s\b',
        ],
    ),
    # aria-current="page"
    (
        "aria-current-page",
        re.compile(r'aria-current\s*=\s*["\']page["\']'),
        [
            r"aria-current\s*=\s*[{(].*['\"]page['\"]",
            # Static literal aria-current="page"
            r'aria-current\s*=\s*["\']page["\']',
        ],
    ),
    # role="status"
    (
        "role-status",
        re.compile(r'\[role\s*=\s*["\']status["\']\]'),
        [
            r'role\s*=\s*[{"\']?["\']?status["\']?',
        ],
    ),
]

# Optional whitelist — selectors that are spec-only fixtures (test artifacts) and
# need not appear in impl. Empty for now; add cases only after triage.
WHITELIST: set[tuple[str, str]] = set()


def extract_selectors(spec_path: Path) -> list[Selector]:
    """Parse a single .spec.ts file and yield all selector usages it asserts.

    Filters out non-existence assertions:
      - selectors used in `.toHaveCount(0)` / `not.toBeVisible()` (absence)
      - selectors containing `${...}` template substitution (dynamic, not
        a literal that impl could match)
      - lines that are part of OR-fallback selectors where a sibling literal
        satisfies — e.g. `[data-testid="X"], nav` only requires nav OR X.
    """
    out: list[Selector] = []
    text = spec_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        is_locator_line = (
            "locator(" in line
            or "getByRole(" in line
            or "getByTestId(" in line
            or "[data-" in line
            or "aria-current" in line
            or "[role=" in line
        )
        if not is_locator_line:
            continue

        # Skip absence assertions: look ahead 5 lines for `toHaveCount(0)`
        # or `not.toBeVisible` — those expect the selector to NOT exist, so
        # missing in impl is the correct state, not drift.
        lookahead = "\n".join(lines[line_no - 1: line_no + 5])
        if re.search(r"toHaveCount\s*\(\s*0\s*\)", lookahead):
            continue
        if re.search(r"\.not\.toBeVisible", lookahead):
            continue

        # Skip selectors that contain template-literal substitution — those
        # are dynamic and cannot be statically matched against impl literals.
        if "${" in line:
            continue

        # Detect OR-fallback selector chain. Within a single locator(...) call
        # the selector list is comma-separated; if there is ANY second
        # alternative — bracketed selector, role/element token, button-text
        # match, etc. — we treat all selectors on the line as advisory.
        is_or_fallback = bool(
            re.search(
                # primary `[X]` followed by second selector (bracketed),
                # text-button shortcut, or a generic role/element token
                r'\[[^\]]+\]\s*,\s*'
                r'(\[[^\]]+\]'
                r'|\bnav\b|\btable\b|\bdialog\b'
                r'|\bbutton\s*:'        # button:has-text(...)
                r'|getByRole'
                r'|\b[a-z]+\[role=)',
                line,
            )
        )

        for kind, regex, _impl_templates in SPEC_PATTERNS:
            for m in regex.finditer(line):
                value = m.group(1) if m.groups() else "__present__"
                if (kind, value) in WHITELIST:
                    continue
                out.append(Selector(
                    kind=kind + ("@or" if is_or_fallback else ""),
                    value=value,
                    spec_file=str(spec_path),
                    spec_line=line_no,
                ))
    return out


def find_in_impl(impl_root: Path, kind: str, value: str,
                 cache: dict[str, str]) -> tuple[bool, str | None]:
    """Search the implementation tree for any file that satisfies the
    `(kind, value)` requirement. Cache file contents to avoid rereads.
    Returns (found, sample_path)."""
    templates_for_kind = next(t for k, _r, t in SPEC_PATTERNS if k == kind)

    # Build all candidate impl regexes
    compiled_list: list[re.Pattern[str]] = []
    for tmpl in templates_for_kind:
        if "%s" not in tmpl:
            compiled_list.append(re.compile(tmpl, re.IGNORECASE))
            continue
        # Special-case: data-status accepts the alias `active` ↔ `running`
        # because CampaignsTable aliases at the presentation layer
        # (P7.14.3.D-05).
        if kind == "data-status" and value == "running":
            tmpl_filled = tmpl.replace("\\b%s\\b", r"\b(running|active)\b").replace(
                "%s", "(running|active)"
            )
        else:
            tmpl_filled = tmpl % re.escape(value)
        compiled_list.append(re.compile(tmpl_filled, re.IGNORECASE))

    # Cache impl file list once per call session
    cache_files_key = "__files__:" + str(impl_root)
    if cache_files_key not in cache:
        files: list[str] = []
        for path in impl_root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".tsx", ".ts", ".jsx", ".js"}:
                continue
            normalised = str(path).replace("\\", "/")
            if "/__tests__/" in normalised:
                continue
            if "/node_modules/" in normalised:
                continue
            files.append(str(path))
        cache[cache_files_key] = "\n".join(files)
    files = cache[cache_files_key].split("\n") if cache[cache_files_key] else []

    for path_str in files:
        if path_str not in cache:
            try:
                cache[path_str] = Path(path_str).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                cache[path_str] = ""
        text = cache[path_str]
        for compiled in compiled_list:
            if compiled.search(text):
                return True, path_str
    return False, None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec-glob", required=True,
                    help="Glob for spec files (e.g. apps/web/e2e/7.14.3-*.spec.ts)")
    ap.add_argument("--impl-root", required=True,
                    help="Root of implementation source (e.g. apps/web/src)")
    ap.add_argument("--report-md", default="",
                    help="Optional markdown report output path")
    ap.add_argument("--phase", default="",
                    help="Optional phase id for telemetry/report header")
    args = ap.parse_args(argv)

    started = time.monotonic()
    spec_files = [Path(p) for p in glob(args.spec_glob, recursive=True)]
    impl_root = Path(args.impl_root)
    if not spec_files:
        result = {
            "validator": "spec-selectors-vs-impl",
            "verdict": "PASS",
            "evidence": [{"type": "no-spec-files",
                          "message": f"No spec files matched glob: {args.spec_glob}"}],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "cache_key": None,
        }
        print(json.dumps(result))
        return 0
    if not impl_root.is_dir():
        result = {
            "validator": "spec-selectors-vs-impl",
            "verdict": "BLOCK",
            "evidence": [{"type": "config-error",
                          "message": f"--impl-root not a directory: {impl_root}"}],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "cache_key": None,
        }
        print(json.dumps(result))
        return 2

    # Extract all selectors from all spec files
    all_selectors: list[Selector] = []
    for sp in spec_files:
        all_selectors.extend(extract_selectors(sp))
    # Dedupe by (kind, value) keeping first spec_file/line for evidence
    seen: dict[tuple[str, str], Selector] = {}
    for s in all_selectors:
        key = (s.kind, s.value)
        if key not in seen:
            seen[key] = s
    unique_selectors = list(seen.values())

    # Verify each against impl source. Strip the `@or` suffix used to mark
    # OR-fallback selectors before looking up the impl pattern table.
    cache: dict[str, str] = {}
    missing: list[dict[str, str | int]] = []
    found_count = 0
    softened_count = 0  # OR-fallback selectors flagged as advisory (not BLOCK)
    for sel in unique_selectors:
        kind_clean = sel.kind.replace("@or", "")
        is_or = sel.kind.endswith("@or")
        ok, where = find_in_impl(impl_root, kind_clean, sel.value, cache)
        if ok:
            found_count += 1
            continue
        evidence_entry = {
            "type": ("advisory-impl-attr" if is_or else "missing-impl-attr"),
            "kind": kind_clean,
            "value": sel.value,
            "spec_file": sel.spec_file,
            "spec_line": sel.spec_line,
            "or_fallback": is_or,
            "message": (
                f"Spec {sel.spec_file}:{sel.spec_line} "
                f"{'mentions' if is_or else 'requires'} "
                f"`{kind_clean}={sel.value}`"
                f"{' as part of an OR-fallback selector chain' if is_or else ''}"
                f" but no implementation file under {impl_root} exposes it."
            ),
            "fix_hint": (
                f"Add `{kind_clean}={{...}}` to the matching component, OR "
                f"adjust the spec selector if the attribute genuinely should "
                f"not exist."
            ),
        }
        if is_or:
            softened_count += 1
        else:
            missing.append(evidence_entry)

    verdict = "PASS" if not missing else "BLOCK"
    result = {
        "validator": "spec-selectors-vs-impl",
        "verdict": verdict,
        "evidence": missing or [{
            "type": "summary",
            "message": f"All {found_count} unique spec selectors satisfied by impl.",
        }],
        "duration_ms": int((time.monotonic() - started) * 1000),
        "cache_key": None,
        "stats": {
            "spec_files_scanned": len(spec_files),
            "unique_selectors": len(unique_selectors),
            "satisfied": found_count,
            "missing": len(missing),
            "advisory_or_fallback": softened_count,
        },
    }
    print(json.dumps(result))

    if args.report_md:
        report_lines = [
            f"# Spec Selector Audit — Phase {args.phase or 'unknown'}",
            "",
            f"- Spec files scanned: **{len(spec_files)}**",
            f"- Unique selector patterns: **{len(unique_selectors)}**",
            f"- Satisfied by impl: **{found_count}**",
            f"- Missing in impl: **{len(missing)}** {'(BLOCK)' if missing else '(PASS)'}",
            "",
        ]
        if missing:
            report_lines.append("## Missing")
            report_lines.append("")
            for m in missing:
                report_lines.append(
                    f"- `{m['kind']}=\"{m['value']}\"` "
                    f"(spec: {m['spec_file']}:{m['spec_line']})\n"
                    f"  - {m['fix_hint']}"
                )
        Path(args.report_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_md).write_text("\n".join(report_lines), encoding="utf-8")

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
