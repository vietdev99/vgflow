"""phase_pad.py — F6 Batch 12

Shared phase-number padding. Replaces hardcoded `zfill(2)` calls that break
at phase 100+ or sub-phase notation like '07.10.1'.

- Default width: 2 (preserves backward compat for phases 1-99)
- Env override: VG_PHASE_PAD_WIDTH (e.g. "3" for projects expecting 100+ phases)
- Sub-phase notation: applies padding to top-level segment only
"""
from __future__ import annotations
import os


def phase_pad(phase: "int | str", width: "int | None" = None) -> str:
    """Pad phase number to width. Handles ints, strings, and sub-phase notation.

    Examples:
      phase_pad(7) -> '07'
      phase_pad(100) -> '100' (NOT truncated)
      phase_pad('07.10.1') -> '07.10.1' (passthrough)
      phase_pad('5.2') -> '05.2' (top-level padded)
      phase_pad(7, width=3) -> '007'
    """
    if width is None:
        try:
            width = int(os.environ.get("VG_PHASE_PAD_WIDTH", "2"))
        except (TypeError, ValueError):
            width = 2

    s = str(phase).strip()
    if "." in s:
        head, _, tail = s.partition(".")
        return f"{_pad_segment(head, width)}.{tail}"
    return _pad_segment(s, width)


def _pad_segment(seg: str, width: int) -> str:
    """Pad a numeric segment to width. Never truncate when seg exceeds width."""
    if not seg.isdigit():
        return seg
    n = int(seg)
    return str(n).zfill(max(width, len(str(n))))


__all__ = ["phase_pad"]
