"""R6 Task 16 — wording/UX cleanup tests.

Two minor fixes:

1. specs.md HARD-GATE downgraded from "Each step is gated by hooks /
   Skipping ANY step will be blocked" to "Marker-tracked steps emit
   step-active + mark-step (those listed in must_touch_markers)".
   Reality: only some steps emit markers, not all 9.

2. Accept override-resolution-gate BLOCK message gained an explicit
   pointer to ${PLANNING_DIR}/OVERRIDE-DEBT.md so the user can `cat`
   the register to inspect entries.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SPECS_MD = REPO / "commands/vg/specs.md"
ACCEPT_GATES_MD = REPO / "commands/vg/_shared/accept/gates.md"


def test_specs_hard_gate_no_universal_step_claim():
    """Specs HARD-GATE must NOT claim every/all/each step is hook-gated.

    Reality: only steps listed in `must_touch_markers` emit markers.
    Audit (R6 Task 16) downgraded to "Marker-tracked steps emit ..."
    """
    text = SPECS_MD.read_text()
    # Normalize whitespace so multi-line wording matches as a single string.
    flat = " ".join(text.split())
    lower = flat.lower()

    # The exact pre-fix wording must be gone.
    assert "each step is gated by hooks" not in lower, (
        "specs.md still contains 'Each step is gated by hooks' — R6 Task 16 "
        "downgraded this to 'Marker-tracked steps emit step-active + mark-step'."
    )
    assert "skipping any step will be blocked" not in lower, (
        "specs.md still contains 'Skipping ANY step will be blocked' — "
        "R6 Task 16 narrowed to marker-tracked steps only."
    )

    # The replacement wording must be present (whitespace-normalized).
    assert "marker-tracked steps" in lower, (
        "specs.md HARD-GATE missing 'Marker-tracked steps' replacement wording."
    )
    assert "must_touch_markers" in text, (
        "specs.md HARD-GATE should reference must_touch_markers as the "
        "authoritative list of marker-tracked steps."
    )


def test_accept_override_debt_block_points_to_file():
    """Accept override-resolution-gate BLOCK message must include OVERRIDE-DEBT.md path.

    Pre-fix the message just listed entries inline without telling the user
    where to inspect the canonical register. R6 Task 16 added an explicit
    pointer so user can `cat ${PLANNING_DIR}/OVERRIDE-DEBT.md`.
    """
    text = ACCEPT_GATES_MD.read_text()

    # Locate the BLOCK message block.
    block_idx = text.find("Override resolution gate BLOCKED")
    assert block_idx != -1, (
        "accept/gates.md missing 'Override resolution gate BLOCKED' BLOCK message."
    )

    # Search a window around the block (back a few lines for path
    # variable assignment, forward for the echoed pointer line).
    window = text[max(0, block_idx - 500) : block_idx + 1500]
    assert "OVERRIDE-DEBT.md" in window, (
        "Override resolution gate BLOCK message must point to "
        "${PLANNING_DIR}/OVERRIDE-DEBT.md so user knows where to inspect debt entries."
    )
    assert "Debt register:" in window, (
        "BLOCK message should label the file path with 'Debt register:' "
        "so it's discoverable in console output."
    )
