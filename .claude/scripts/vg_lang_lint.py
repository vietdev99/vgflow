#!/usr/bin/env python3
"""
vg_lang_lint.py — Lint check Việt hoá cho VG command narration (v1.14.0+ spec section 2.6)

Grep narration strings (echo/print) trong command files tìm thuật ngữ
tiếng Anh "forbidden" mà nên là tiếng Việt.

Rule (từ term-glossary.md v1.14.0+):
- Trạng thái/phán quyết: Verdict, Status → VN
- Động từ quy trình: Audit, Review, Deploy → VN
- Khái niệm: Scope, Gate, Blueprint, Checkpoint, Runbook → VN

KHÔNG lint:
- Command ID (/vg:review, --skip-foo)
- File name (SPECS.md, GOAL-COVERAGE-MATRIX.md)
- Format/protocol identifier (API, HTTP, JSON, Zod)
- Tiếng Anh trong markdown header nhưng không phải narration
- Comment code block (# ...) — chỉ lint output strings

Usage:
  python vg_lang_lint.py                  # lint toàn bộ .claude/commands/vg/
  python vg_lang_lint.py --file {path}    # lint 1 file
  python vg_lang_lint.py --fix            # (chưa implement — chỉ report)
  python vg_lang_lint.py --summary        # chỉ show tổng count per term
"""
from __future__ import annotations

import sys
import re
import argparse
from pathlib import Path
from collections import defaultdict

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# Forbidden EN terms trong narration (word-boundary match)
# (term, vietnamese suggestion, severity)
FORBIDDEN_TERMS = [
    # Trạng thái / phán quyết
    (r"\bVerdict\b",        "Kết quả / Phán quyết",  "HIGH"),
    (r"\bStatus:\s*BLOCKED\b", "Trạng thái: BỊ CHẶN",  "HIGH"),
    (r"\bBLOCKED\b(?![\w-])",  "BỊ CHẶN",               "MED"),
    (r"\bBlocked\b",        "Bị chặn",               "MED"),
    (r"\bDeferred\b",       "Hoãn lại",              "MED"),

    # Động từ quy trình
    (r"\bAudit\b",          "Rà soát",               "HIGH"),
    (r"\bAuditing\b",       "Đang rà soát",          "HIGH"),
    (r"\bReview\b(?!ing\b|ed\b|er\b)",  "Rà soát",   "LOW"),    # Review có thể là file name, low severity
    (r"\bRegression\b",     "Hồi quy",               "MED"),

    # Khái niệm
    (r"\bScope\b(?!-)",     "Phạm vi",               "MED"),
    (r"\bGate\b(?!way)",    "Cổng kiểm tra",         "HIGH"),
    (r"\bBlueprint\b",      "Bản thiết kế",          "MED"),
    (r"\bCheckpoint\b",     "Mốc kiểm tra",          "MED"),
    (r"\bRunbook\b",        "Sổ tay triển khai",     "HIGH"),
    (r"\bRollback\b",       "Khôi phục",             "MED"),
    (r"\bSmoke\s+test\b",   "Kiểm tra nhanh",        "LOW"),
    (r"\bHealth\s+check\b", "Kiểm tra trạng thái",   "LOW"),

    # Others
    (r"\bAggregator\b",     "Bộ tổng hợp",           "LOW"),
    (r"\bDeploy\b(?!ment\b|ing\b|ed\b)", "Triển khai", "LOW"),
    (r"\bPreflight\b",      "Tiền kiểm",             "LOW"),
]

# Patterns identify narration (echo/print strings, not comments/code)
NARRATION_PATTERNS = [
    re.compile(r'echo\s+"([^"]+)"'),        # bash echo "..."
    re.compile(r'echo\s+\'([^\']+)\''),     # bash echo '...'
    re.compile(r'print\(["\']([^"\']+)["\']\)'),   # python print("...")
    re.compile(r'print\(f["\']([^"\']+)["\']\)'),  # python print(f"...")
]

# Exempt contexts (false positives)
EXEMPT_CONTEXTS = [
    re.compile(r"^#"),                              # markdown header
    re.compile(r"```"),                             # code fence (entering/leaving)
    re.compile(r"^\s*(?:\*\s+)?`[A-Z_]+\.md`"),     # filename reference
    re.compile(r"</?[a-z-]+>"),                     # XML-ish tags (<step>, <narration>, ...)
]


def extract_narration_strings(text: str) -> list[tuple[int, str]]:
    """Return list of (line_number, narration_string) tuples."""
    results = []
    in_code_fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        # Track code fences
        if line.strip().startswith("```"):
            in_code_fence = not in_code_fence
            continue

        # Skip markdown headers (but still lint code inside code fences)
        if not in_code_fence and line.lstrip().startswith("#"):
            continue

        # Inside code fence → try narration patterns
        if in_code_fence:
            for pat in NARRATION_PATTERNS:
                for m in pat.finditer(line):
                    results.append((lineno, m.group(1)))

    return results


def lint_file(path: Path) -> dict:
    """Lint 1 file, return dict {term: [(lineno, narration, ...)]}."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}

    narrations = extract_narration_strings(text)
    violations = defaultdict(list)

    for lineno, narr in narrations:
        for pat, vn_suggest, severity in FORBIDDEN_TERMS:
            for m in re.finditer(pat, narr):
                violations[m.group(0)].append({
                    "file":       str(path),
                    "line":       lineno,
                    "narration":  narr[:80],
                    "suggestion": vn_suggest,
                    "severity":   severity,
                })

    return dict(violations)


def lint_dir(cmd_dir: Path) -> dict:
    """Lint all .md files trong cmd_dir."""
    all_violations = defaultdict(list)
    for md in cmd_dir.rglob("*.md"):
        # Skip bản thân spec file (chứa bảng tra dùng EN)
        if "term-glossary" in md.name or "V1.14.0-SPEC" in md.name:
            continue
        file_v = lint_file(md)
        for term, hits in file_v.items():
            all_violations[term].extend(hits)
    return dict(all_violations)


def print_report(violations: dict, summary_only: bool = False) -> int:
    if not violations:
        print("✓ Không phát hiện thuật ngữ EN nào cần Việt hoá.")
        return 0

    total = sum(len(hits) for hits in violations.values())
    print(f"━━━ VG Language Lint Report ━━━")
    print(f"Found {total} matches across {len(violations)} forbidden terms.")
    print()

    # Sort by severity
    severity_order = {"HIGH": 0, "MED": 1, "LOW": 2}

    def sort_key(item):
        term, hits = item
        sev = hits[0]["severity"] if hits else "LOW"
        return (severity_order.get(sev, 3), -len(hits))

    sorted_violations = sorted(violations.items(), key=sort_key)

    # Summary table
    print(f"{'Severity':<10} {'Term':<20} {'Count':<8} {'Suggestion'}")
    print(f"{'-'*10} {'-'*20} {'-'*8} {'-'*40}")
    for term, hits in sorted_violations:
        if not hits:
            continue
        sev = hits[0]["severity"]
        suggest = hits[0]["suggestion"]
        print(f"{sev:<10} {term:<20} {len(hits):<8} {suggest}")

    if summary_only:
        return 1 if total > 0 else 0

    # Detail: top 3 examples per term
    print()
    print("━━━ Detail ━━━")
    for term, hits in sorted_violations:
        if not hits:
            continue
        print(f"\n{term} ({hits[0]['severity']}) → {hits[0]['suggestion']}")
        for h in hits[:3]:
            print(f"  {h['file']}:{h['line']}")
            print(f"    \"{h['narration']}\"")
        if len(hits) > 3:
            print(f"  ... và {len(hits) - 3} match nữa.")

    return 1  # Non-zero exit cho CI


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Lint Việt hoá cho VG command narration")
    p.add_argument("--file", help="Lint 1 file cụ thể")
    p.add_argument("--dir", default=".claude/commands/vg", help="Directory scan (default: .claude/commands/vg)")
    p.add_argument("--summary", action="store_true", help="Chỉ show summary table, không detail")
    args = p.parse_args(argv)

    if args.file:
        v = lint_file(Path(args.file))
    else:
        v = lint_dir(Path(args.dir))

    return print_report(v, summary_only=args.summary)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
