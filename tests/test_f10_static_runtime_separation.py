"""tests/test_f10_static_runtime_separation.py — F10 count labeling."""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLOSE = REPO / "commands" / "vg" / "_shared" / "review" / "close.md"


def test_recap_distinguishes_static_vs_runtime():
    body = CLOSE.read_text(encoding="utf-8")
    # Recap template must label inventory counts differently from runtime counts.
    has_label_distinction = (
        "Static" in body and ("Runtime" in body or "Visited" in body)
    ) or "inventory" in body.lower() and "visited" in body.lower()
    assert has_label_distinction, (
        "F10: review close.md recap must distinguish static inventory "
        "(routes/models/services counts from grep) vs runtime visited "
        "counts (views toured, scans observed). Currently presents both as "
        "depth proof."
    )
