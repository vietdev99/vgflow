#!/usr/bin/env python3
"""
verify-i18n-vs-testid.py — v2.43.5

Validator for /vg:review (post-build sanity).

Asserts: components calling i18n functions (t() / $t() / useTranslation /
$_) on user-facing UI text MUST also have a `data-testid` attribute. If a
component renders translated text without testid, test specs are forced to
text-match → fragile to i18n rotation.

Triggered by:
  - vg.config.md > test_ids.enabled: true
  - Phase reached /vg:review (post-build, pre-test)

Outcome:
  - PASS  → every i18n-using interactive component has testid
  - WARN  → list components with i18n + no testid (advisory)
  - FAIL  → if test_ids.enforce_i18n_pairing: "block"

Usage:
  verify-i18n-vs-testid.py --phase-dir <path>
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

# i18n function call patterns (framework-agnostic)
I18N_PATTERNS = [
    re.compile(r'\bt\s*\(\s*[\'"]'),               # React i18next t('...')
    re.compile(r'\$t\s*\(\s*[\'"]'),               # Vue $t('...')
    re.compile(r'\$_\s*\(\s*[\'"]'),               # Svelte i18n $_('...')
    re.compile(r'useTranslation\s*\('),            # React hook
    re.compile(r'i18n\.t\s*\(\s*[\'"]'),           # explicit i18n.t
    re.compile(r'\bI18nText\b'),                   # custom React component
]

INTERACTIVE_TAGS = re.compile(
    r'<(button|a|input|select|textarea|form|tr\b|tab|dialog)\b',
    re.IGNORECASE,
)
TESTID_PATTERN = re.compile(r'data-testid\s*=', re.IGNORECASE)

UI_FILE_GLOB = re.compile(
    r'(apps|packages)/[^/]+/src/.*\.(tsx|jsx|vue|svelte)$'
)


def scan_file(path: Path) -> dict | None:
    """Returns {has_i18n, has_testid, has_interactive, lines} or None if not UI."""
    if not UI_FILE_GLOB.search(str(path)):
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return None

    has_i18n = any(p.search(content) for p in I18N_PATTERNS)
    has_testid = bool(TESTID_PATTERN.search(content))
    has_interactive = bool(INTERACTIVE_TAGS.search(content))

    return {
        "has_i18n": has_i18n,
        "has_testid": has_testid,
        "has_interactive": has_interactive,
    }


def find_changed_files(phase_dir: Path) -> list[Path]:
    """Read SUMMARY.md or PLAN files_modified to find what this phase touched."""
    candidates: list[Path] = []
    summary = phase_dir / "SUMMARY.md"
    plan = phase_dir / "PLAN.md"
    repo_root = Path.cwd()

    text = ""
    if summary.exists():
        text += summary.read_text(encoding="utf-8")
    if plan.exists():
        text += plan.read_text(encoding="utf-8")

    # Match file paths in apps/packages
    seen = set()
    for m in re.finditer(r'(apps|packages)/[^\s)]+\.(tsx|jsx|vue|svelte)', text):
        rel = m.group(0)
        if rel in seen:
            continue
        seen.add(rel)
        candidates.append(repo_root / rel)
    return candidates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--severity", default="warn", choices=["warn", "block"])
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    files = find_changed_files(phase_dir)

    if not files:
        print("SKIP: no UI files referenced in SUMMARY.md or PLAN.md")
        return 0

    violations = []
    scanned = 0
    for f in files:
        result = scan_file(f)
        if not result:
            continue
        scanned += 1
        # Only flag if file has i18n + interactive but no testid
        if result["has_i18n"] and result["has_interactive"] and not result["has_testid"]:
            violations.append(f.relative_to(Path.cwd()))

    if not violations:
        print(f"PASS: {scanned} UI files scanned, all i18n-using interactive "
              f"components have testid")
        return 0

    print(f"\033[33m{len(violations)}/{scanned} UI files use i18n on interactive elements \033[0m"
          f"WITHOUT data-testid:")
    for v in violations:
        print(f"  \033[38;5;208m{v}\033[0m")
    print("")
    print("Why this matters: test specs codegen will fall back to getByText() with")
    print("Vietnamese strings. Next i18n update will silently break those specs.")
    print("")
    print("Fix: add `data-testid=\"<page>-<element>\"` (English, kebab-case) to each")
    print("interactive element in these files. Update PLAN.md <test_ids> retroactively.")

    if args.severity == "block":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
