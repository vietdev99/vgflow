from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_scope_slim_at_or_below_600_lines():
    """Spec §1.5 goal: ≤500 target, ≤600 hard ceiling (buffer for STEP entries + Red Flags table)."""
    p = REPO / "commands" / "vg" / "scope.md"
    assert p.exists(), f"{p} missing"
    lines = p.read_text().splitlines()
    assert len(lines) <= 600, f"scope.md has {len(lines)} lines, exceeds 600 ceiling"
