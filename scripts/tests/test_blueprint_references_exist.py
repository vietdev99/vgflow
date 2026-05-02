from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# Per-ref line ceiling. Anthropic recommends ≤500 lines per SKILL.md / ref
# file. verify.md exceeds because 2d_validation_gate alone is 655 lines source
# (8 deterministic Python validator gates + auto-fix loop + CrossAI consensus
# review with verdict dispatch). Documented in verify.md header. Future
# extraction to vg-validation-gate.py helper would shrink verify.md ≤350.
REFS = {
    "preflight.md":            500,
    "design.md":               500,
    "plan-overview.md":        500,
    "plan-delegation.md":      500,
    "contracts-overview.md":   500,
    "contracts-delegation.md": 500,
    "verify.md":               800,  # documented exception per file header
    "close.md":                500,
}


def test_all_blueprint_refs_exist():
    base = REPO / "commands/vg/_shared/blueprint"
    for ref, ceiling in REFS.items():
        p = base / ref
        assert p.exists(), f"missing ref: {p}"
        assert p.stat().st_size > 100, f"ref {p} too small ({p.stat().st_size} bytes)"
        lines = p.read_text().splitlines()
        assert len(lines) <= ceiling, f"ref {p} exceeds {ceiling} lines (got {len(lines)})"
