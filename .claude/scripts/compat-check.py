#!/usr/bin/env python3
"""
compat-check.py — Scan VG workflow .md files for non-portable (GNU-only) patterns.

Scans .claude/commands/vg/ and .claude/commands/vg/_shared/ for patterns that
break on macOS/BSD. Reports file, line number, pattern found, and suggested fix.

Usage:
    python3 .claude/scripts/compat-check.py [--fix]
"""

import re
import sys
from pathlib import Path

# Patterns: (regex_to_match_in_line, pattern_name, suggested_fix)
PATTERNS = [
    (
        r'\bgrep\s+-([\w]*P[\w]*)\b',
        'grep -P (Perl regex)',
        'Use grep -E (extended regex) or sed -n with regex. BSD grep has no -P flag.',
    ),
    (
        r'\bstat\s+--format\b',
        'stat --format (GNU-only)',
        'Add fallback: stat --format="%s" FILE 2>/dev/null || stat -f "%z" FILE',
    ),
    (
        r'\bdate\s+-d\b',
        'date -d (GNU-only)',
        'Add fallback: date -d @EPOCH 2>/dev/null || date -r EPOCH. Or use Python datetime.',
    ),
    (
        r'\breadlink\s+-f\b',
        'readlink -f (GNU-only)',
        'Use realpath (POSIX) or python3 -c "import os; print(os.path.realpath(...))"',
    ),
    (
        r'\bfind\s+\S+\s+-maxdepth\b',
        'find with -maxdepth after path',
        'BSD find requires -maxdepth before other expressions. Verify order: find PATH -maxdepth N ...',
    ),
    (
        r'\bsed\s+-i\s+(?!-e)(?!"")(?!\'\')\S',
        'sed -i without backup suffix',
        'macOS sed requires: sed -i "" or sed -i \'\'. Use sed -i"" for cross-platform.',
    ),
    (
        r'\bsort\s+-([\w]*V[\w]*)\b',
        'sort -V (version sort, GNU-only)',
        'Use sort -t. -k1,1n -k2,2n or Python for version sorting.',
    ),
    (
        r'\bxargs\s+-r\b',
        'xargs -r (GNU-only)',
        'BSD xargs has no -r. Pipe through: if [ -s file ]; then xargs ... < file; fi',
    ),
]


def scan_file(filepath: Path) -> list[dict]:
    """Scan a single file for non-portable patterns."""
    findings = []
    try:
        lines = filepath.read_text(encoding='utf-8').splitlines()
    except Exception as e:
        print(f"WARNING: Cannot read {filepath}: {e}", file=sys.stderr)
        return findings

    for line_num, line in enumerate(lines, start=1):
        # Skip markdown comments and non-code lines (only scan inside ```bash blocks
        # and inline `backtick` commands, but for simplicity scan all lines that
        # look like they contain shell commands)
        stripped = line.strip()
        if not stripped or stripped.startswith('#') and not stripped.startswith('#!'):
            # Skip pure comment lines (but not shebangs)
            # Actually in .md files, # is a heading. Only skip if inside code block.
            pass

        for pattern_re, pattern_name, suggestion in PATTERNS:
            match = re.search(pattern_re, line)
            if match:
                findings.append({
                    'file': str(filepath),
                    'line': line_num,
                    'pattern': pattern_name,
                    'matched': match.group(0),
                    'suggestion': suggestion,
                    'context': stripped[:120],
                })
    return findings


def main():
    # Determine repo root from script location
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent  # .claude/scripts -> .claude -> repo

    scan_dirs = [
        repo_root / '.claude' / 'commands' / 'vg',
        repo_root / '.claude' / 'commands' / 'vg' / '_shared',
        repo_root / '.claude' / 'commands' / '_shared',
    ]

    all_findings = []
    scanned = 0

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for md_file in sorted(scan_dir.glob('*.md')):
            scanned += 1
            findings = scan_file(md_file)
            all_findings.extend(findings)

    # Also scan scripts (.py, .sh) in .claude/scripts/
    scripts_dir = repo_root / '.claude' / 'scripts'
    if scripts_dir.exists():
        for script_file in sorted(scripts_dir.glob('*.sh')):
            scanned += 1
            findings = scan_file(script_file)
            all_findings.extend(findings)

    # Report
    print(f"Scanned {scanned} files across {len(scan_dirs)} directories")
    print(f"Found {len(all_findings)} non-portable patterns\n")

    if not all_findings:
        print("All clear — no non-portable patterns detected.")
        return 0

    # Group by pattern for summary
    by_pattern: dict[str, list] = {}
    for f in all_findings:
        by_pattern.setdefault(f['pattern'], []).append(f)

    print("=" * 80)
    print("FINDINGS BY PATTERN")
    print("=" * 80)

    for pattern_name, items in sorted(by_pattern.items(), key=lambda x: -len(x[1])):
        print(f"\n--- {pattern_name} ({len(items)} occurrences) ---")
        print(f"    Fix: {items[0]['suggestion']}")
        for item in items:
            relpath = Path(item['file']).relative_to(repo_root)
            print(f"    {relpath}:{item['line']}  {item['matched']}")
            print(f"      > {item['context']}")

    print(f"\n{'=' * 80}")
    print(f"TOTAL: {len(all_findings)} findings in {scanned} files")
    print(f"Top 5 most impactful (by frequency):")
    for i, (pname, items) in enumerate(sorted(by_pattern.items(), key=lambda x: -len(x[1]))[:5], 1):
        print(f"  {i}. {pname}: {len(items)} occurrences")

    return 1 if all_findings else 0


if __name__ == '__main__':
    sys.exit(main())
