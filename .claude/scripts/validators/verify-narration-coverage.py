#!/usr/bin/env python3
"""verify-narration-coverage — detect hardcoded English in Evidence fields.

Per validator-narration-guide.md (B8.0, 2026-04-23):
  "Evidence.message and Evidence.fix_hint MUST be t(key, ...) — never raw
   strings."

This validator AST-scans every `.claude/scripts/validators/*.py` file and
reports each Evidence() call where `message=`, `fix_hint=`, or `summary=`
is a raw string literal (not a call to `t()`).

Observed problem: user ran flows in a different project + saw validator
output in English even though narration.locale was "vi". Root cause: many
validators predate B8.0 and still hardcode Evidence(message="...") without
routing through t(). Guide exists but no automated check catches drift.

Output format matches other validators — JSON verdict + Evidence list.
Intended to run as a dev-time gate, not per-phase (expensive AST parse of
every validator). Wire via `/vg:doctor --narration` eventually.

Usage:
  python verify-narration-coverage.py [--root <dir>] [--json-only]

Exit codes:
  0 — all Evidence fields go through t() or are raw-data types (actual/expected)
  1 — ≥1 validator has hardcoded message/fix_hint/summary
  2 — unrecoverable error
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

# Fields in Evidence() that must go through t() per the guide.
# summary appears in some validator Output blocks — treat same as message.
PROSE_FIELDS = {"message", "fix_hint", "summary"}

# Files to skip — _common + _i18n themselves define the helpers.
SKIP_BASENAMES = {"_common.py", "_i18n.py", "__init__.py"}


def find_evidence_calls(tree: ast.AST) -> list[ast.Call]:
    """Collect every Evidence(...) call node in the tree."""
    hits: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name == "Evidence":
                hits.append(node)
    return hits


def is_t_call(node: ast.expr) -> bool:
    """True if node is a call to t(...) — the i18n helper."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "t":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "t":
        return True
    return False


def is_raw_string(node: ast.expr) -> bool:
    """True if node is a literal string (hardcoded prose)."""
    # Python 3.8+ uses ast.Constant for all literals
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    # f-strings — JoinedStr is still raw prose, just with interpolation
    if isinstance(node, ast.JoinedStr):
        return True
    return False


def is_conditional_expr(node: ast.expr) -> bool:
    """True if node is a ternary — `"A" if cond else t("key")` style.
    We flag these as mixed — any raw-string branch is a violation.
    """
    return isinstance(node, ast.IfExp)


def audit_evidence_call(
    call: ast.Call, source_lines: list[str]
) -> list[dict]:
    """Return list of findings for this Evidence() call."""
    findings: list[dict] = []
    for kw in call.keywords:
        if kw.arg not in PROSE_FIELDS:
            continue
        value = kw.value
        if is_t_call(value):
            continue  # compliant
        if is_raw_string(value):
            line = call.lineno
            snippet = ""
            if 0 < line <= len(source_lines):
                snippet = source_lines[line - 1].strip()[:120]
            findings.append({
                "type": "hardcoded_prose",
                "field": kw.arg,
                "line": line,
                "snippet": snippet,
            })
        elif is_conditional_expr(value):
            # Check both branches
            raw_branches = []
            for branch_name, branch in (
                ("body", value.body),
                ("orelse", value.orelse),
            ):
                if is_raw_string(branch):
                    raw_branches.append(branch_name)
            if raw_branches:
                findings.append({
                    "type": "conditional_raw_branch",
                    "field": kw.arg,
                    "line": call.lineno,
                    "snippet": (
                        source_lines[call.lineno - 1].strip()[:120]
                        if 0 < call.lineno <= len(source_lines) else ""
                    ),
                    "raw_branches": raw_branches,
                })
        # else: variable reference, function call other than t() — ambiguous.
        # Report as soft-warn so human can audit manually.
        elif isinstance(value, (ast.Name, ast.Call, ast.Attribute)):
            # Only flag variable refs/calls where the variable name suggests
            # prose (not data). Heuristic: skip if name matches data-patterns.
            name_str = ast.unparse(value) if hasattr(ast, "unparse") else ""
            data_patterns = (
                "path", "file", "sha", "id", "count", "len", "n_",
                "expected", "actual", "str(", "repr(",
            )
            if not any(p in name_str.lower() for p in data_patterns):
                findings.append({
                    "type": "indirect_prose_suspected",
                    "field": kw.arg,
                    "line": call.lineno,
                    "snippet": name_str[:120],
                    "note": "variable/call ref — verify it resolves to t()",
                })
    return findings


def audit_file(path: Path) -> tuple[list[dict], int]:
    """Audit one validator file. Returns (findings, evidence_call_count)."""
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as e:
        return ([{
            "type": "read_error",
            "file": str(path),
            "error": str(e),
        }], 0)

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return ([{
            "type": "parse_error",
            "file": str(path),
            "error": f"line {e.lineno}: {e.msg}",
        }], 0)

    source_lines = source.splitlines()
    calls = find_evidence_calls(tree)
    all_findings: list[dict] = []
    for call in calls:
        for finding in audit_evidence_call(call, source_lines):
            finding["file"] = str(path.relative_to(path.parents[2])) if (
                len(path.parents) >= 3
            ) else str(path)
            all_findings.append(finding)
    return (all_findings, len(calls))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--root",
        default=".claude/scripts/validators",
        help="Directory to scan (default: .claude/scripts/validators)",
    )
    p.add_argument(
        "--json-only",
        action="store_true",
        help="Emit only machine-readable JSON (for CI consumers)",
    )
    p.add_argument(
        "--skip-indirect",
        action="store_true",
        help="Skip indirect_prose_suspected findings (reduce noise during bulk migration)",
    )
    # v2.6 (2026-04-25): orchestrator-injected --phase ignored (scans all)
    p.add_argument("--phase", help="(orchestrator-injected; ignored)")
    args = p.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"\033[38;5;208mScan root not a directory: {root}\033[0m", file=sys.stderr)
        return 2

    all_findings: list[dict] = []
    total_calls = 0
    total_files = 0
    for py_file in sorted(root.glob("*.py")):
        if py_file.name in SKIP_BASENAMES:
            continue
        total_files += 1
        findings, call_count = audit_file(py_file)
        total_calls += call_count
        if args.skip_indirect:
            findings = [
                f for f in findings
                if f.get("type") != "indirect_prose_suspected"
            ]
        all_findings.extend(findings)

    # Group by file for human-readable summary
    by_file: dict[str, list[dict]] = {}
    for f in all_findings:
        by_file.setdefault(f.get("file", "?"), []).append(f)

    hardcoded = [f for f in all_findings if f["type"] == "hardcoded_prose"]
    conditional = [
        f for f in all_findings if f["type"] == "conditional_raw_branch"
    ]
    indirect = [
        f for f in all_findings if f["type"] == "indirect_prose_suspected"
    ]

    verdict = "PASS" if (not hardcoded and not conditional) else "BLOCK"

    result = {
        "validator": "narration-coverage",
        "verdict": verdict,
        "summary": {
            "files_scanned": total_files,
            "evidence_calls": total_calls,
            "hardcoded_prose": len(hardcoded),
            "conditional_raw_branch": len(conditional),
            "indirect_prose_suspected": len(indirect),
        },
        "findings_by_file": by_file,
    }

    if args.json_only:
        print(json.dumps(result))
    else:
        print("━━━ Narration coverage audit ━━━")
        print(
            f"  Files scanned:           {total_files}\n"
            f"  Evidence() calls total:  {total_calls}\n"
            f"  Hardcoded prose:         {len(hardcoded)} (BLOCK)\n"
            f"  Conditional raw branch:  {len(conditional)} (BLOCK)\n"
            f"  Indirect suspected:      {len(indirect)} (WARN)\n"
        )
        if hardcoded or conditional:
            print("Violations (phải fix — mỗi Evidence phải qua t(key,...)):")
            for f_path, flist in sorted(by_file.items()):
                bad = [
                    f for f in flist
                    if f["type"] in ("hardcoded_prose", "conditional_raw_branch")
                ]
                if not bad:
                    continue
                print(f"\n  {f_path}")
                for f in bad[:10]:
                    print(
                        f"    L{f['line']:>4} [{f['type']}] "
                        f"{f['field']}=… | {f.get('snippet','')}"
                    )
                if len(bad) > 10:
                    print(f"    … +{len(bad) - 10} more")
        print(f"\nVerdict: {verdict}")
        print(
            "\nBối cảnh: Rule B8.0 (2026-04-23) yêu cầu Evidence.message và\n"
            "Evidence.fix_hint PHẢI đi qua _i18n.t() — nếu không, user sẽ\n"
            "thấy message tiếng Anh dù locale config là 'vi'. Fix từng file:\n"
            "  1. Thêm key vào narration-strings-validators.yaml (có cả vi + en)\n"
            "  2. Thay Evidence(message=\"foo\") → Evidence(message=t(\"my_validator.foo.message\"))\n"
            "  3. Re-run validator này → verdict PASS.\n"
        )

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
