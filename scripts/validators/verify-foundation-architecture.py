#!/usr/bin/env python3
"""
Validator: verify-foundation-architecture.py

Phase D v2.5 (2026-04-23): FOUNDATION.md §9 "Architecture Lock" section check.

Reads .vg/FOUNDATION.md (legacy fallback to .planning/FOUNDATION.md) and
validates that section 9 is present and contains all 8 required subsections
with substantive content (≥3 non-empty bullet lines each).

The 8 required subsections:
  1. tech_stack        — lang/framework/DB/auth/deploy/CI matrix
  2. module_boundary   — apps/packages/shared + dependency direction rules
  3. folder_convention — route layout, test colocation, asset org
  4. cross_cutting     — logging, error handling, async pattern, i18n
  5. security_baseline — session/identity + server hardening + compliance flags
  6. perf_baseline     — p95 defaults, cache, bundle, CDN
  7. testing_baseline  — runner, E2E framework, coverage threshold, mock strategy
  8. code_style        — explicit imports, named exports, type annotations, etc.

Severity matrix:
- FOUNDATION.md missing entirely → SKIP with advisory (no phase-level block)
- §9 missing + phase >= phase_cutover (default 14) → HARD BLOCK
- §9 missing + phase < cutover → WARN (grandfather phases 0-13)
- Subsection missing in §9 + phase >= cutover → HARD BLOCK per subsection
- Subsection present but < 3 substantive bullet lines → WARN

Config read from .claude/vg.config.md:
  architecture.phase_cutover         (default: context_injection.phase_cutover = 14)
  architecture.required_subsections  (default: all 8)

Usage:
  verify-foundation-architecture.py --phase <N>

Exit codes:
  0 PASS or WARN (advisory only)
  1 BLOCK (§9 or subsection missing for phase >= cutover)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# ── Subsection keyword map ──────────────────────────────────────────────────
# Maps canonical subsection ID → list of keyword patterns that match the
# ### header text (case-insensitive). Any one match is sufficient.
SUBSECTION_KEYWORDS: dict[str, list[str]] = {
    "tech_stack":        ["tech stack", "technology stack", "tech-stack"],
    "module_boundary":   ["module boundary", "module-boundary", "module boundaries"],
    "folder_convention": ["folder convention", "folder-convention", "folder layout",
                          "directory convention", "directory structure"],
    "cross_cutting":     ["cross-cutting", "cross cutting", "crosscutting",
                          "cross_cutting"],
    "security_baseline": ["security baseline", "security-baseline"],
    "perf_baseline":     ["perf baseline", "perf-baseline", "performance baseline",
                          "performance-baseline"],
    "testing_baseline":  ["testing baseline", "testing-baseline", "test baseline",
                          "test-baseline"],
    "code_style":        ["code style", "code-style", "coding style",
                          "model-portable", "model portable"],
}

# Default display names for subsections (for human-readable messages)
SUBSECTION_DISPLAY: dict[str, str] = {
    "tech_stack":        "Tech Stack Matrix",
    "module_boundary":   "Module Boundary",
    "folder_convention": "Folder Convention",
    "cross_cutting":     "Cross-Cutting Concerns",
    "security_baseline": "Security Baseline",
    "perf_baseline":     "Performance Baseline",
    "testing_baseline":  "Testing Baseline",
    "code_style":        "Model-Portable Code Style",
}

# Minimum substantive bullet lines required per subsection
MIN_BULLETS = 3

# Regex: a markdown bullet line (-, *, + or numbered)
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\S")


def _read_config() -> dict:
    """Parse vg.config.md for architecture settings."""
    cfg = REPO_ROOT / ".claude" / "vg.config.md"
    defaults: dict = {
        "phase_cutover": 14,
        "required_subsections": list(SUBSECTION_KEYWORDS.keys()),
    }
    if not cfg.exists():
        return defaults

    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return defaults

    # Try architecture.phase_cutover first
    m = re.search(
        r"^architecture:\s*\n(?:[ \t]+.*\n)*?[ \t]+phase_cutover:\s*(\d+)",
        text, re.MULTILINE,
    )
    if m:
        defaults["phase_cutover"] = int(m.group(1))
    else:
        # Fall back to context_injection.phase_cutover
        m2 = re.search(
            r"^\s*phase_cutover:\s*(\d+)", text, re.MULTILINE,
        )
        if m2:
            defaults["phase_cutover"] = int(m2.group(1))

    # architecture.required_subsections — expect YAML list or comma-separated
    m3 = re.search(
        r"^architecture:\s*\n(?:[ \t]+.*\n)*?[ \t]+required_subsections:\s*\[([^\]]+)\]",
        text, re.MULTILINE,
    )
    if m3:
        items = [x.strip().strip("'\"") for x in m3.group(1).split(",")]
        valid = [x for x in items if x in SUBSECTION_KEYWORDS]
        if valid:
            defaults["required_subsections"] = valid

    return defaults


def _find_foundation() -> Path | None:
    """Locate FOUNDATION.md — .vg/ canonical first, .planning/ legacy fallback."""
    candidates = [
        REPO_ROOT / ".vg" / "FOUNDATION.md",
        REPO_ROOT / ".planning" / "FOUNDATION.md",
    ]
    # Also glob for any FOUNDATION.md under .planning/ (legacy tolerance)
    for p in (REPO_ROOT / ".planning").glob("FOUNDATION.md") if (
        REPO_ROOT / ".planning"
    ).exists() else []:
        if p not in candidates:
            candidates.append(p)

    for p in candidates:
        if p.exists():
            return p
    return None


def _find_section9(text: str) -> tuple[int, int] | None:
    """Return (start_line, end_line) of section 9 body (exclusive), or None.

    Matches headers like:
      ## 9. Architecture Lock
      ## 9 Architecture ...
      ## Section 9
      ## Architecture Lock  (fallback keyword scan)
    """
    lines = text.splitlines()
    section9_re = re.compile(
        r"^##\s+(?:9[.\s]|Section\s+9\b|Architecture\s+Lock\b)",
        re.IGNORECASE,
    )
    # Fallback: any ## header containing "architecture lock" or just "architecture"
    arch_fallback_re = re.compile(
        r"^##\s+.*architecture",
        re.IGNORECASE,
    )

    start = None
    for i, line in enumerate(lines):
        if section9_re.match(line) or (start is None and arch_fallback_re.match(line)):
            start = i
            break

    if start is None:
        return None

    # Section ends at next ## header (same or higher level)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^##\s+", lines[i]) and not re.match(r"^###\s+", lines[i]):
            end = i
            break

    return (start, end)


def _parse_subsections(lines: list[str], section_start: int, section_end: int,
                       required: list[str]) -> dict[str, list[str]]:
    """Parse ### subsection headers inside section 9.

    Returns dict: subsection_id → list of content lines (between this ### and next ###).
    Only subsections matching required list are returned.
    """
    result: dict[str, list[str]] = {}
    section_lines = lines[section_start:section_end]

    # Find all ### headers and their positions
    sub_positions: list[tuple[int, str]] = []  # (index_in_section, header_text)
    for i, line in enumerate(section_lines):
        m = re.match(r"^###\s+(.+)$", line)
        if m:
            sub_positions.append((i, m.group(1).strip()))

    # For each required subsection, try to match a header
    for sub_id in required:
        keywords = SUBSECTION_KEYWORDS.get(sub_id, [])
        matched_pos = None
        for pos, header_text in sub_positions:
            for kw in keywords:
                if kw.lower() in header_text.lower():
                    matched_pos = pos
                    break
            if matched_pos is not None:
                break

        if matched_pos is None:
            result[sub_id] = []  # subsection not found → empty
            continue

        # Collect lines until next ### or end of section
        content: list[str] = []
        for i in range(matched_pos + 1, len(section_lines)):
            if re.match(r"^###\s+", section_lines[i]):
                break
            content.append(section_lines[i])
        result[sub_id] = content

    return result


def _count_bullets(content_lines: list[str]) -> int:
    """Count substantive bullet lines in a subsection body."""
    return sum(1 for line in content_lines if BULLET_RE.match(line))


def _phase_as_float(phase_str: str) -> float:
    """Convert phase string to float for comparison (e.g. '7.6' → 7.6, '14' → 14.0)."""
    try:
        return float(phase_str)
    except (ValueError, TypeError):
        return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True,
                    help="Phase number (e.g. 14, 7.6, 09)")
    args = ap.parse_args()

    out = Output(validator="verify-foundation-architecture")

    with timer(out):
        cfg = _read_config()
        phase_cutover: int = cfg["phase_cutover"]
        required: list[str] = cfg["required_subsections"]
        phase_num = _phase_as_float(args.phase)
        is_cutover = phase_num >= phase_cutover

        # ── Step 1: locate FOUNDATION.md ───────────────────────────────────
        foundation_path = _find_foundation()
        if foundation_path is None:
            # SKIP — project may not have run /vg:project yet
            out.warn(Evidence(
                type="foundation_missing_advisory",
                message=t("foundation_arch.foundation_missing.message"),
                fix_hint=t("foundation_arch.foundation_missing.fix_hint"),
            ))
            # Override verdict to PASS (SKIP semantics — not a block)
            out.verdict = "PASS"
            emit_and_exit(out)
            return

        try:
            text = foundation_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            out.warn(Evidence(
                type="foundation_read_error",
                message=f"Cannot read FOUNDATION.md: {exc}",
                file=str(foundation_path),
            ))
            out.verdict = "PASS"
            emit_and_exit(out)
            return

        lines = text.splitlines()

        # ── Step 2: find section 9 ──────────────────────────────────────────
        section_range = _find_section9(text)

        if section_range is None:
            if is_cutover:
                # HARD BLOCK: phase >= cutover, §9 required
                out.add(Evidence(
                    type="foundation_section9_missing",
                    message=t(
                        "foundation_arch.section_missing.message",
                        phase=args.phase,
                        cutover=phase_cutover,
                    ),
                    file=str(foundation_path),
                    fix_hint=t(
                        "foundation_arch.section_missing.fix_hint",
                        phase=args.phase,
                    ),
                ))
            else:
                # WARN: grandfather for pre-cutover phases
                out.warn(Evidence(
                    type="foundation_section9_missing_preflight",
                    message=t(
                        "foundation_arch.section_missing.message",
                        phase=args.phase,
                        cutover=phase_cutover,
                    ),
                    file=str(foundation_path),
                    fix_hint=t(
                        "foundation_arch.section_missing.fix_hint",
                        phase=args.phase,
                    ),
                ))
            emit_and_exit(out)
            return

        sec_start, sec_end = section_range

        # ── Step 3: parse subsections ───────────────────────────────────────
        subsection_content = _parse_subsections(lines, sec_start, sec_end, required)

        missing_subsections: list[str] = []   # HARD BLOCK (cutover) / WARN (pre)
        empty_subsections: list[str] = []     # WARN (header present, < 3 bullets)

        for sub_id in required:
            content = subsection_content.get(sub_id, [])
            if not content:
                # No header matched → subsection missing
                missing_subsections.append(sub_id)
            else:
                bullet_count = _count_bullets(content)
                if bullet_count < MIN_BULLETS:
                    empty_subsections.append(sub_id)

        # ── Step 4: emit evidence ────────────────────────────────────────────
        if missing_subsections:
            names = ", ".join(
                SUBSECTION_DISPLAY.get(s, s) for s in missing_subsections
            )
            if is_cutover:
                out.add(Evidence(
                    type="foundation_subsection_missing",
                    message=t(
                        "foundation_arch.subsection_missing.message",
                        count=len(missing_subsections),
                        names=names,
                        phase=args.phase,
                    ),
                    file=str(foundation_path),
                    actual=names,
                    fix_hint=t(
                        "foundation_arch.subsection_missing.fix_hint",
                        names=names,
                    ),
                ))
            else:
                out.warn(Evidence(
                    type="foundation_subsection_missing_preflight",
                    message=t(
                        "foundation_arch.subsection_missing.message",
                        count=len(missing_subsections),
                        names=names,
                        phase=args.phase,
                    ),
                    file=str(foundation_path),
                    actual=names,
                    fix_hint=t(
                        "foundation_arch.subsection_missing.fix_hint",
                        names=names,
                    ),
                ))

        if empty_subsections:
            names = ", ".join(
                SUBSECTION_DISPLAY.get(s, s) for s in empty_subsections
            )
            out.warn(Evidence(
                type="foundation_subsection_empty",
                message=t(
                    "foundation_arch.subsection_empty.message",
                    count=len(empty_subsections),
                    names=names,
                    min_bullets=MIN_BULLETS,
                ),
                file=str(foundation_path),
                actual=names,
                fix_hint=t(
                    "foundation_arch.subsection_empty.fix_hint",
                    min_bullets=MIN_BULLETS,
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
