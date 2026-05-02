from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# Per-ref line ceiling. Anthropic recommends ≤500 lines per SKILL.md / ref.
# Three refs documented exceptions because hold heavy step bash from backup
# until helper extraction:
# - verify.md: 2d_validation_gate alone is 655 lines source (8 Python validator
#   gates + auto-fix loop + CrossAI consensus review verdict dispatch).
# - plan-overview.md: 2a_plan setup (graphify brief, deploy-lessons brief,
#   R5 size gate) + 2a5_cross_system_check (5 grep checks + caller graph build).
# - contracts-overview.md: 2b/2b5/2b5a/2b5d/2b7 orchestration (Codex CLI lane
#   + flow detect dependency-chain DFS).
# Future extraction to dedicated helpers would shrink each ≤350.
REFS = {
    "preflight.md":            500,
    "design.md":               500,
    "plan-overview.md":        650,  # 2a + 2a5 documented exception
    "plan-delegation.md":      500,
    "contracts-overview.md":   650,  # 2b + 2b5 + 2b5a + 2b5d + 2b7 exception
    "contracts-delegation.md": 500,
    "verify.md":               800,  # 2d_validation_gate exception
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
