"""R4 Accept Pilot — assert 10 refs + 3 nested dirs + per-ref line ceilings."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Per-ref line ceiling. Mirrors blueprint pilot's ladder.
# Most refs ≤500. Audit ref combines 3 sub-steps so allowance is higher.
# Gates ref has 5 fail-fast gates inline (preserved verbatim).
REFS = {
    "preflight.md":                       500,
    "gates.md":                           700,  # 5 gates inline (preserved verbatim)
    "uat/checklist-build/overview.md":    300,
    "uat/checklist-build/delegation.md":  300,
    "uat/narrative.md":                   300,
    "uat/interactive.md":                 400,  # 6 sections + AskUserQuestion shape
    "uat/quorum.md":                      400,  # quorum + rationalization-guard
    "audit.md":                           700,  # 6b + 6c + 6_write_uat_md combined
    "cleanup/overview.md":                400,
    "cleanup/delegation.md":              300,
}

NESTED_DIRS = [
    "uat/",
    "uat/checklist-build/",
    "cleanup/",
]


def test_all_accept_refs_exist():
    base = REPO / "commands/vg/_shared/accept"
    for ref, ceiling in REFS.items():
        p = base / ref
        assert p.exists(), f"missing ref: {p}"
        assert p.stat().st_size > 100, f"ref {p} too small ({p.stat().st_size} bytes)"
        lines = p.read_text().splitlines()
        assert len(lines) <= ceiling, f"ref {p} exceeds {ceiling} lines (got {len(lines)})"


def test_nested_dirs_exist():
    base = REPO / "commands/vg/_shared/accept"
    for d in NESTED_DIRS:
        p = base / d
        assert p.is_dir(), f"missing nested dir: {p}"


def test_refs_use_imperative_hard_gate():
    """Every ref must signal imperative pattern (HARD-GATE / MUST / DO NOT)."""
    base = REPO / "commands/vg/_shared/accept"
    for ref in REFS:
        p = base / ref
        body = p.read_text()
        # At least one of the imperative markers must appear (case-insensitive)
        lower = body.lower()
        has_imperative = (
            "<hard-gate>" in lower
            or " must " in lower
            or "do not " in lower
            or "must not" in lower
        )
        assert has_imperative, (
            f"ref {p} lacks imperative language (HARD-GATE / MUST / DO NOT / must not)"
        )
