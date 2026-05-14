#!/usr/bin/env python3
"""scaffold-detector.py — Batch 24

Audits markdown files in commands/vg/ for scaffold/drift anti-patterns.
8 patterns A-H codified from Batches 9/14/15/18/19/22 findings.

Emits JSON report with per-finding file:line + pattern + snippet.
--threshold N: exit 1 if findings count > N (CI gate).
Default --threshold -1: advisory only (always exit 0).

Patterns implemented at first ship: A, C, F, G, H.
Patterns B, D, E require cross-file analysis — deferred to future enhancement.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


# Pattern definitions: (pattern_id, severity, name, description, detector_fn)
PATTERNS = [
    ("A", "high", "agent_comment_only",
     "Agent(subagent_type=...) inside bash fence with no file gate after"),
    ("B", "medium", "marker_no_evidence",
     "mark-step <X> without file existence check in same block [DEFERRED: cross-file]"),
    ("C", "high", "failure_swallow",
     "|| true on run-complete/validate/verify line"),
    ("D", "medium", "orphan_must_write",
     "must_write declares file X but no validator reads it [DEFERRED: cross-file]"),
    ("E", "high", "agent_read_only_file_expect",
     "Agent SKILL.md missing Write but caller expects file output [DEFERRED: cross-file]"),
    ("F", "high", "tool_directive_in_bash",
     "Agent( / SlashCommand: / AskUserQuestion: inside bash fence"),
    ("G", "medium", "unconditional_marker",
     "touch *.done in else branch without validation"),
    ("H", "low", "glob_bypass",
     "Glob *.spec.ts / *.json where canonical manifest exists"),
]


BASH_FENCE_RE = re.compile(r"```bash\n(.*?)\n```", re.DOTALL)


def _detect_pattern_A(text: str, path: Path) -> list[dict]:
    """Agent(subagent_type=...) inside bash fence with no file gate after."""
    findings = []
    for m in BASH_FENCE_RE.finditer(text):
        block = m.group(1)
        line_offset = text[:m.start()].count("\n") + 1
        # Find Agent( occurrences in bash block (commented out with #)
        for am in re.finditer(r"#\s*Agent\(subagent_type", block):
            block_line = block[:am.start()].count("\n")
            line_num = line_offset + block_line + 1
            # Check next 800 chars in block for [ -f ... ] or is_file or exists check
            tail = block[am.end():am.end() + 800]
            has_gate = bool(re.search(r"\[\s*-f\s|\[\s*!\s*-f\s|is_file\(|exists\(", tail))
            if not has_gate:
                findings.append({
                    "pattern": "A",
                    "file": str(path),
                    "line": line_num,
                    "snippet": block[am.start():am.start() + 120].strip(),
                })
    return findings


def _detect_pattern_C(text: str, path: Path) -> list[dict]:
    """|| true on run-complete / validate / verify lines."""
    findings = []
    for ln, line in enumerate(text.splitlines(), 1):
        if "|| true" in line and re.search(
            r"\b(run-complete|validate|verify|check-contract)\b", line
        ):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            findings.append({
                "pattern": "C",
                "file": str(path),
                "line": ln,
                "snippet": stripped[:120],
            })
    return findings


def _detect_pattern_F(text: str, path: Path) -> list[dict]:
    """Tool directive (Agent(/SlashCommand:/AskUserQuestion:) inside bash fence."""
    findings = []
    for m in BASH_FENCE_RE.finditer(text):
        block = m.group(1)
        line_offset = text[:m.start()].count("\n") + 1
        for dm in re.finditer(
            r"^\s*(AskUserQuestion:|SlashCommand:|Agent\()", block, re.MULTILINE
        ):
            # Skip if the line itself is commented out
            block_line_start = block.rfind("\n", 0, dm.start()) + 1
            prefix = block[block_line_start:dm.start()]
            if prefix.strip().startswith("#"):
                continue
            block_line = block[:dm.start()].count("\n")
            line_num = line_offset + block_line + 1
            findings.append({
                "pattern": "F",
                "file": str(path),
                "line": line_num,
                "snippet": dm.group(0).strip()[:120],
            })
    return findings


def _detect_pattern_G(text: str, path: Path) -> list[dict]:
    """touch *.done in else branch without validation."""
    findings = []
    # Find else { ... touch *.done ... } blocks (bash if/else/fi)
    else_blocks = re.finditer(r"\belse\b\s*\n((?:.*\n){1,15}?)\bfi\b", text)
    for m in else_blocks:
        block = m.group(1)
        if re.search(r"touch\s+[^\n]*\.done", block):
            # Check if any validation present in same block
            if not re.search(
                r"\[\s*-f|is_file|exists\(|verify|validator", block
            ):
                line_num = text[:m.start()].count("\n") + 1
                findings.append({
                    "pattern": "G",
                    "file": str(path),
                    "line": line_num,
                    "snippet": "else { ... touch .done ... fi (no validation)",
                })
    return findings


def _detect_pattern_H(text: str, path: Path) -> list[dict]:
    """Glob *.spec.ts / *.json where canonical manifest exists."""
    findings = []
    lines = text.splitlines()
    for ln, line in enumerate(lines, 1):
        # Only flag *.spec.ts globs where CODEGEN-MANIFEST is absent in the file
        if re.search(r"\*\.spec\.[tj]s\b", line):
            # Skip comment lines
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            # Check if CODEGEN-MANIFEST referenced anywhere in the file
            if "CODEGEN-MANIFEST" not in text:
                findings.append({
                    "pattern": "H",
                    "file": str(path),
                    "line": ln,
                    "snippet": stripped[:120],
                })
    return findings


DETECTORS = [
    _detect_pattern_A,
    _detect_pattern_C,
    _detect_pattern_F,
    _detect_pattern_G,
    _detect_pattern_H,
]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Scaffold/drift anti-pattern detector (Batch 24)"
    )
    ap.add_argument("--scan-dir", required=True, type=Path,
                    help="Directory to scan")
    ap.add_argument("--glob", default="**/*.md",
                    help="File glob pattern (default: **/*.md)")
    ap.add_argument(
        "--threshold", type=int, default=-1,
        help=(
            "Exit 1 if findings count > threshold. "
            "Default -1 = advisory only (always exit 0)."
        ),
    )
    ap.add_argument("--json", action="store_true",
                    help="Emit structured JSON report to stdout")
    args = ap.parse_args()

    findings: list[dict] = []
    scan_dir = args.scan_dir.resolve()
    for path in sorted(scan_dir.glob(args.glob)):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for det in DETECTORS:
            findings.extend(det(text, path))

    by_pattern: dict[str, int] = {}
    for f in findings:
        pat = f["pattern"]
        by_pattern[pat] = by_pattern.get(pat, 0) + 1

    report = {
        "scan_dir": str(scan_dir),
        "total_findings": len(findings),
        "by_pattern": by_pattern,
        "findings": findings,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Scaffold detector: {len(findings)} finding(s) in {scan_dir}")
        for f in findings[:30]:
            print(f"  [{f['pattern']}] {f['file']}:{f['line']}: {f['snippet']}")
        if len(findings) > 30:
            print(
                f"  ... +{len(findings) - 30} more (use --json for full report)"
            )

    if args.threshold >= 0 and len(findings) > args.threshold:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
