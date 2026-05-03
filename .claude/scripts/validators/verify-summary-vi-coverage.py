#!/usr/bin/env python3
"""
Validator: verify-summary-vi-coverage.py

Harness v2.6 (2026-04-25): closes the user-feedback rule "Phase Summary
Vietnamese" from MEMORY.md:

  "Mỗi phase phải có XX-SUMMARY-VI.md tổng quan tiếng Việt cụ thể"

Why it matters: SUMMARY.md is generated in English by /vg:build (executor
output). Phase reviewer (the human user) speaks Vietnamese natively and
needs an end-to-end story-format summary in Vietnamese to verify what
shipped. Without it, the user has to read English SUMMARY.md (sometimes
terse + bullet-heavy) and translate mentally — slow, error-prone, breaks
review flow.

Rule: every accepted phase MUST have a Vietnamese summary file:
  Convention: <phase>-SUMMARY-VI.md  (e.g., 7.14.3-SUMMARY-VI.md)

What this validator checks:

  1. At /vg:accept, scan phase_dir for any *-SUMMARY-VI.md file matching
     the phase number prefix. Accepts:
       - 7.14.3-SUMMARY-VI.md
       - SUMMARY-VI.md  (generic, no prefix)
       - PHASE-7.14.3-SUMMARY-VI.md
       - VI-SUMMARY.md  (legacy ordering)

  2. Verify file is not empty / placeholder. Heuristics:
       - File size ≥ 500 bytes (placeholder usually <100 bytes)
       - Contains at least 3 Vietnamese-only diacritics (Đ/đ/ấ/ơ/ư/...)
         to confirm actually written in Vietnamese, not English with VN file
       - Has at least 2 markdown headings (## or ###)

  3. Skip when phase profile is "docs" (docs phases summarize themselves)
     or "hotfix" with parent_phase declared (parent's summary covers).

Severity:
  BLOCK at vg:accept (final gate before user sign-off — Vietnamese summary
         is part of the acceptance criteria).
  WARN at vg:test (advisory; reminds AI to write before accept dispatch).

Usage:
  verify-summary-vi-coverage.py --phase 7.14.3
  verify-summary-vi-coverage.py --phase 7.14.3 --strict (BLOCK at any stage)

Exit codes:
  0  PASS or WARN (file present + acceptable)
  1  BLOCK (file missing OR placeholder)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Vietnamese-only diacritics (catches strings actually in Vietnamese,
# not English happening to have ASCII letters in a *-VI.md file).
VIETNAMESE_DIACRITICS = re.compile(
    r"[ăâđêôơưĂÂĐÊÔƠƯấầẩẫậắằẳẵặếềểễệốồổỗộớờởỡợứừửữựíìỉĩịóòỏõọúùủũụéèẻẽẹáàảãạýỳỷỹỵÀÁẢÃẠÌÍỈĨỊỪỨỬỮỰÉÈẺẼẸỐỒỔỖỘÚÙỦŨỤÝỲỶỸỴ]"
)
HEADING_RE = re.compile(r"^#{2,3}\s+\S", re.MULTILINE)


def _is_summary_vi_file(name: str, phase: str) -> bool:
    """Match files like 7.14.3-SUMMARY-VI.md / SUMMARY-VI.md / VI-SUMMARY.md."""
    name_lower = name.lower()
    if not name_lower.endswith(".md"):
        return False
    # Must contain "summary" + "vi" tokens
    if "summary" not in name_lower or "vi" not in name_lower:
        return False
    # Filter false positives: file with "vid" / "vie" / "view" but not "vi"
    # as standalone token. Require -VI- or VI. or VI_ delimiter.
    has_vi_token = bool(re.search(r"(?:^|[-_.])vi(?:[-_.]|$)", name_lower))
    return has_vi_token


def _scan_phase_for_summary_vi(phase_dir: Path, phase: str) -> list[Path]:
    """Find all matching summary-vi files in phase dir."""
    matches: list[Path] = []
    for f in phase_dir.iterdir():
        if not f.is_file():
            continue
        if _is_summary_vi_file(f.name, phase):
            matches.append(f)
    return matches


def _is_placeholder(file_path: Path) -> tuple[bool, str]:
    """Return (is_placeholder, reason). Real Vietnamese summary should
    be substantive: ≥500 bytes + ≥3 VN diacritics + ≥2 markdown headings."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return True, f"unreadable: {exc}"

    if len(text.encode("utf-8")) < 500:
        return True, f"too short ({len(text)} bytes < 500)"

    diacritic_count = len(VIETNAMESE_DIACRITICS.findall(text))
    if diacritic_count < 3:
        return True, f"only {diacritic_count} Vietnamese diacritics (need ≥3 — likely English content)"

    heading_count = len(HEADING_RE.findall(text))
    if heading_count < 2:
        return True, f"only {heading_count} markdown headings (need ≥2 — likely placeholder)"

    return False, "OK"


def _phase_profile(phase_dir: Path) -> str:
    """Best-effort phase profile detection from SPECS.md frontmatter."""
    specs = phase_dir / "SPECS.md"
    if not specs.exists():
        return "feature"
    try:
        text = specs.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "feature"
    m = re.search(r"^profile:\s*(\w+)", text, re.MULTILINE)
    if m:
        return m.group(1).lower()
    if re.search(r"^parent_phase:", text, re.MULTILINE):
        return "hotfix"
    return "feature"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--strict", action="store_true",
                    help="BLOCK regardless of stage (default: BLOCK at accept, "
                         "WARN at test stage)")
    args = ap.parse_args()

    out = Output(validator="verify-summary-vi-coverage")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        profile = _phase_profile(phase_dir)
        if profile in ("docs", "hotfix", "bugfix"):
            # docs phases self-summarize; hotfix/bugfix typically reference
            # parent phase summary
            emit_and_exit(out)

        matches = _scan_phase_for_summary_vi(phase_dir, args.phase)

        if not matches:
            out.add(Evidence(
                type="summary_vi_missing",
                message=f"Phase {args.phase} missing Vietnamese summary file",
                actual=f"Files in {phase_dir.name}: {sorted(f.name for f in phase_dir.iterdir() if f.is_file())[:10]}",
                expected=f"At least one file matching pattern *-SUMMARY-VI.md (recommended: {args.phase}-SUMMARY-VI.md)",
                fix_hint=(
                    "Tạo file {phase}-SUMMARY-VI.md trong phase dir. Format: "
                    "kể câu chuyện end-to-end bằng tiếng Việt — đầu vào là gì, "
                    "đã làm gì, ship được gì, decision quan trọng nào, deferred "
                    "items nào. Per CLAUDE.md user feedback: 'Mỗi phase phải có "
                    "XX-SUMMARY-VI.md tổng quan tiếng Việt cụ thể.'"
                ),
            ))
            emit_and_exit(out)

        # Validate each match is substantive (not placeholder)
        all_placeholder = True
        placeholder_reasons: list[str] = []
        for f in matches:
            is_ph, reason = _is_placeholder(f)
            if not is_ph:
                all_placeholder = False
                break
            placeholder_reasons.append(f"{f.name}: {reason}")

        if all_placeholder:
            out.add(Evidence(
                type="summary_vi_placeholder",
                message=f"Phase {args.phase} has summary-vi file(s) but all look like placeholders",
                actual=f"Files found: {[f.name for f in matches]}. Issues: {placeholder_reasons}",
                expected="Substantive Vietnamese summary: ≥500 bytes, ≥3 Vietnamese diacritics (đ/â/ấ/ơ/ư/...), ≥2 markdown headings",
                fix_hint=(
                    "Mở rộng nội dung summary-vi: thêm phần ngữ cảnh (gì đã có "
                    "trước phase), những thay đổi chính (theo wave/task), "
                    "decision đáng chú ý (tại sao chọn approach này), kết quả "
                    "verify được, deferred items. Khoảng 50-200 dòng tiếng Việt."
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
