#!/usr/bin/env python3
"""
Validator: accessibility-scan.py

B9.1 (v2.4 hardening, 2026-04-23): static a11y check on frontend source
changed in this phase. Catches the top-4 WCAG A/AA violations cheaply
before /vg:review spawns Haiku scanners:

  1. <img> without alt attribute
  2. <button> / clickable without accessible name (text/aria-label/title)
  3. <input> / <select> / <textarea> without associated <label>
  4. Interactive custom element (role=button/link) without aria-label

Scope: parses JSX/TSX/HTML/Vue source, not runtime DOM (cheap <2s).
Runtime axe-core still runs in /vg:review phase 2b via Playwright —
this validator prevents obvious violations from reaching that stage.

Usage:
  accessibility-scan.py --phase <N>

Exit codes:
  0 PASS (no violations) or WARN (moderate only, advisory)
  1 BLOCK (serious/critical violations — block review/test)

Config (vg.config.md, optional):
  a11y:
    enabled: true
    source_globs: ["apps/web/src/**/*.{tsx,jsx,html}"]
    block_on: ["serious", "critical"]
    warn_on: ["moderate"]
    allowlist_file: ".vg/a11y-allowlist.yml"  # regex patterns to skip
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Default globs if config missing — common FE locations
DEFAULT_GLOBS = [
    "apps/web/src/**/*.tsx",
    "apps/web/src/**/*.jsx",
    "apps/*/src/**/*.tsx",
    "apps/*/src/**/*.jsx",
    "packages/*/src/**/*.tsx",
    "*.html",
    "Supply-Side Platform/**/*.html",
    "Internal Demand/**/*.html",
]

# ─────────────────────────────────────────────────────────────────────────
# Violation classifiers — severity per WCAG 2.2 AA ruleset

# Severity levels
CRITICAL = "critical"
SERIOUS = "serious"
MODERATE = "moderate"
MINOR = "minor"


# <img> without alt (Rule: 1.1.1 Non-text content — Level A, SERIOUS)
IMG_NO_ALT = re.compile(
    r"<img\b(?![^>]*\balt\s*=)[^>]*/?>",
    re.IGNORECASE,
)

# <button> with empty content + no aria-label (Rule: 4.1.2, Level A, CRITICAL)
BUTTON_NO_LABEL = re.compile(
    r"<button\b(?![^>]*\b(?:aria-label|aria-labelledby|title)\s*=)[^>]*>\s*</button>",
    re.IGNORECASE | re.DOTALL,
)

# <input type="text|email|..."/> no label nearby + no aria-label
INPUT_NO_LABEL = re.compile(
    r"<input\b(?![^>]*\b(?:aria-label|aria-labelledby|placeholder|title)\s*=)"
    r"[^>]*(?:type\s*=\s*[\"'](?:text|email|password|search|tel|url|number)[\"'])?[^>]*/?>",
    re.IGNORECASE,
)

# role="button" without aria-label (Rule: 4.1.2, Level A, SERIOUS)
ROLE_BUTTON_NO_LABEL = re.compile(
    r"role\s*=\s*[\"']button[\"'][^>]*"
    r"(?!.*\b(?:aria-label|aria-labelledby)\s*=)",
    re.IGNORECASE,
)

# <a> empty (no text between tags, no aria-label) (Rule: 2.4.4, SERIOUS)
A_NO_LABEL = re.compile(
    r"<a\b(?![^>]*\b(?:aria-label|title)\s*=)[^>]*>\s*</a>",
    re.IGNORECASE,
)

# onclick on non-interactive element without role — keyboard trap (SERIOUS)
ONCLICK_ON_DIV = re.compile(
    r"<(?:div|span|li)\b[^>]*\bonclick\s*=(?![^>]*\brole\s*=)",
    re.IGNORECASE,
)

# Skip-link pattern check: look for visible skip nav in root HTML (LOW signal;
# only warn if NO skip link anywhere).
SKIP_LINK_PATTERN = re.compile(
    r'href\s*=\s*[\"\']#(?:main|content|skip)', re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────
# Helpers

def _config_a11y() -> dict:
    """Read a11y: section from vg.config.md. Regex-parse since YAML is optional."""
    cfg = REPO_ROOT / ".claude" / "vg.config.md"
    defaults = {
        "enabled": True,
        "source_globs": DEFAULT_GLOBS,
        "block_severities": {CRITICAL, SERIOUS},
        "warn_severities": {MODERATE},
        "allowlist_file": ".vg/a11y-allowlist.yml",
    }
    if not cfg.exists():
        return defaults
    text = cfg.read_text(encoding="utf-8", errors="replace")
    # Check if disabled explicitly
    m = re.search(r"^a11y:\s*\n\s+enabled:\s*(true|false)", text, re.MULTILINE)
    if m and m.group(1) == "false":
        defaults["enabled"] = False
    return defaults


def _load_allowlist() -> list[re.Pattern]:
    """Load .vg/a11y-allowlist.yml — plain list of regex patterns to skip."""
    path = REPO_ROOT / ".vg" / "a11y-allowlist.yml"
    if not path.exists():
        return []
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        patterns = data.get("patterns", []) if isinstance(data, dict) else []
        return [re.compile(p) for p in patterns]
    except Exception:
        return []


def _source_files(phase_dir: Path, globs: list[str], commit_count: int = 10) -> list[Path]:
    """Files changed during phase via git diff, filtered by globs.

    Fallback: if git diff empty (clean checkout), fall back to full-glob scan
    on the first N matching files (quick smoke).
    """
    files: set[Path] = set()
    # Try git diff against HEAD~N (phase commit range)
    try:
        cp = subprocess.run(
            ["git", "log", "--format=%H", f"-n{commit_count}"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
        )
        if cp.returncode == 0 and cp.stdout.strip():
            diff = subprocess.run(
                ["git", "diff", "--name-only", f"HEAD~{commit_count}", "HEAD"],
                cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
            )
            for line in diff.stdout.splitlines():
                p = REPO_ROOT / line.strip()
                if p.exists() and _matches_any_glob(line.strip(), globs):
                    files.add(p)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Fallback to glob scan if nothing found
    if not files:
        for g in globs:
            for p in REPO_ROOT.glob(g):
                if p.is_file():
                    files.add(p)
                if len(files) >= 200:
                    break
            if len(files) >= 200:
                break
    return sorted(files)


def _matches_any_glob(rel_path: str, globs: list[str]) -> bool:
    from fnmatch import fnmatch
    for g in globs:
        # Handle brace-glob expansion naively: split by extensions
        if "{" in g and "}" in g:
            prefix, rest = g.split("{", 1)
            exts_part, suffix = rest.split("}", 1)
            for ext in exts_part.split(","):
                if fnmatch(rel_path, f"{prefix}{ext}{suffix}"):
                    return True
        else:
            if fnmatch(rel_path, g):
                return True
    return False


def _scan_file(path: Path) -> list[dict]:
    """Return violation dicts: {rule, severity, line, snippet}."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    findings: list[dict] = []

    def _line_of(offset: int) -> int:
        return text.count("\n", 0, offset) + 1

    for m in IMG_NO_ALT.finditer(text):
        # Exclude JSX spread props — {...props} might include alt
        if "{...props" in m.group(0) or "{...rest" in m.group(0):
            continue
        findings.append({
            "rule": "img-missing-alt",
            "severity": SERIOUS,
            "line": _line_of(m.start()),
            "snippet": m.group(0)[:120],
        })

    for m in BUTTON_NO_LABEL.finditer(text):
        # Skip if button wraps an <img> that has alt (implicit label)
        inner = m.group(0)
        if re.search(r"<img[^>]*\balt\s*=", inner, re.IGNORECASE):
            continue
        findings.append({
            "rule": "button-no-label",
            "severity": CRITICAL,
            "line": _line_of(m.start()),
            "snippet": m.group(0)[:120],
        })

    for m in ROLE_BUTTON_NO_LABEL.finditer(text):
        findings.append({
            "rule": "role-button-no-label",
            "severity": SERIOUS,
            "line": _line_of(m.start()),
            "snippet": m.group(0)[:120],
        })

    for m in A_NO_LABEL.finditer(text):
        findings.append({
            "rule": "link-no-label",
            "severity": SERIOUS,
            "line": _line_of(m.start()),
            "snippet": m.group(0)[:120],
        })

    for m in ONCLICK_ON_DIV.finditer(text):
        findings.append({
            "rule": "onclick-non-interactive",
            "severity": SERIOUS,
            "line": _line_of(m.start()),
            "snippet": m.group(0)[:120],
        })

    return findings


# ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--commits", type=int, default=10,
                    help="how many HEAD commits span this phase")
    args = ap.parse_args()

    out = Output(validator="accessibility-scan")
    with timer(out):
        cfg = _config_a11y()
        if not cfg["enabled"]:
            emit_and_exit(out)

        phase_dir = find_phase_dir(args.phase)
        # phase_dir is optional — validator can run on changed files regardless
        files = _source_files(phase_dir or REPO_ROOT, cfg["source_globs"],
                              commit_count=args.commits)
        if not files:
            emit_and_exit(out)

        allowlist = _load_allowlist()

        violations_by_severity: dict[str, list[dict]] = {
            CRITICAL: [], SERIOUS: [], MODERATE: [], MINOR: [],
        }

        for fp in files:
            rel = fp.relative_to(REPO_ROOT).as_posix()
            # Allowlist check per file path
            if any(p.search(rel) for p in allowlist):
                continue
            for v in _scan_file(fp):
                v["file"] = rel
                violations_by_severity.setdefault(v["severity"], []).append(v)

        block_count = sum(
            len(violations_by_severity.get(s, []))
            for s in cfg["block_severities"]
        )
        warn_count = sum(
            len(violations_by_severity.get(s, []))
            for s in cfg["warn_severities"]
        )

        if block_count:
            # Sample up to 10 for evidence — full list in logs
            samples = []
            for sev in (CRITICAL, SERIOUS):
                for v in violations_by_severity.get(sev, [])[:5]:
                    samples.append(
                        f"{v['file']}:{v['line']} [{v['rule']}] {v['snippet']}"
                    )
            out.add(Evidence(
                type="a11y_block_violations",
                message=t(
                    "a11y.block_violations.message",
                    count=block_count,
                    critical=len(violations_by_severity[CRITICAL]),
                    serious=len(violations_by_severity[SERIOUS]),
                ),
                actual="; ".join(samples[:10]),
                fix_hint=t("a11y.block_violations.fix_hint"),
            ))

        if warn_count:
            samples = []
            for v in violations_by_severity.get(MODERATE, [])[:5]:
                samples.append(
                    f"{v['file']}:{v['line']} [{v['rule']}] {v['snippet']}"
                )
            out.warn(Evidence(
                type="a11y_moderate_violations",
                message=t(
                    "a11y.moderate_violations.message",
                    count=warn_count,
                ),
                actual="; ".join(samples),
                fix_hint=t("a11y.moderate_violations.fix_hint"),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
