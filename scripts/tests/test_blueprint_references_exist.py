from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REFS = [
    "preflight.md",
    "design.md",
    "plan-overview.md",
    "plan-delegation.md",
    "contracts-overview.md",
    "contracts-delegation.md",
    "verify.md",
    "close.md",
]


def test_all_blueprint_refs_exist():
    base = REPO / "commands/vg/_shared/blueprint"
    for ref in REFS:
        p = base / ref
        assert p.exists(), f"missing ref: {p}"
        assert p.stat().st_size > 100, f"ref {p} too small ({p.stat().st_size} bytes)"
        lines = p.read_text().splitlines()
        assert len(lines) <= 500, f"ref {p} exceeds 500 lines (got {len(lines)})"
