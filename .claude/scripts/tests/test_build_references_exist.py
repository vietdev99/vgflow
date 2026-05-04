from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Per-ref ceiling. R1a precedent — verify.md ref needed an exception.
# R2 build refs: large extracts (waves-overview, post-execution-overview, close) need higher ceilings.
# Document EACH exception's reason inline.
REFS = {
    "preflight.md":                500,
    "context.md":                  500,
    "validate-blueprint.md":       500,
    "waves-overview.md":          1350,  # extracted from backup step 8; R2 round-2 + Codex spawn parity keep orchestration local to the heavy spawn site
    "waves-delegation.md":         500,
    "post-execution-overview.md":  980,  # extracted from backup step 9 (896 lines); R2 round-2 expanded post-spawn validator to enforce BUILD-LOG sha + index + sub-files (closes A4/E2/C5 drift)
    "post-execution-delegation.md": 500,
    "crossai-loop.md":             500,
    "close.md":                    600,  # combines step 10 + 12 (90 + 395 = 485 source), wrapper at 539
}


def test_all_build_refs_exist():
    base = REPO / "commands/vg/_shared/build"
    for ref, ceiling in REFS.items():
        p = base / ref
        assert p.exists(), f"missing ref: {p}"
        assert p.stat().st_size > 100, f"ref {p} too small ({p.stat().st_size} bytes)"
        lines = p.read_text().splitlines()
        assert len(lines) <= ceiling, f"ref {p} exceeds {ceiling} lines (got {len(lines)})"
