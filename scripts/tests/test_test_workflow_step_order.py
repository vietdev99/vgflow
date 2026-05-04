"""R6 Task 5: Test fix-loop ordering (option b — codegen → fix-loop unidirectional).

After R6 Task 5 (decision: option b), fix-loop.md must not return to 5d codegen.
Next step after fix-loop is STEP 7 (regression+security).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIX_LOOP = REPO_ROOT / "commands/vg/_shared/test/fix-loop.md"
TEST_ENTRY = REPO_ROOT / "commands/vg/test.md"


def test_fix_loop_does_not_return_to_5d():
    """fix-loop.md must not redirect back to 5d codegen (option b — unidirectional)."""
    body = FIX_LOOP.read_text()
    # No "skip to 5d", "proceed to 5d", "return ... 5d codegen"
    forbidden_patterns = [
        r"skip to 5d",
        r"proceed to 5d",
        r"return to .* 5d codegen",
        r"-> 5d \(codegen\)",
        r"STEP 7 \(5d codegen\)",
    ]
    found = [p for p in forbidden_patterns if re.search(p, body, re.IGNORECASE)]
    assert not found, (
        f"fix-loop.md still references 5d codegen as next step "
        f"(option b — codegen → fix-loop is unidirectional): {found}"
    )


def test_fix_loop_proceeds_to_step_7_regression():
    """fix-loop.md must mention STEP 7 (regression+security) as next step."""
    body = FIX_LOOP.read_text()
    assert re.search(r"STEP 7", body), (
        "fix-loop.md must reference STEP 7 (regression+security) as next step"
    )
    # And the reference must be associated with regression OR security wording
    # somewhere in the file (not just bare "STEP 7")
    assert re.search(r"regression|security", body, re.IGNORECASE), (
        "fix-loop.md must mention regression or security context for next step"
    )


def test_test_entry_orders_codegen_before_fix_loop():
    """commands/vg/test.md: STEP 5 codegen MUST come before STEP 6 fix-loop."""
    body = TEST_ENTRY.read_text()
    step5_match = re.search(r"^### STEP 5 .*codegen", body, re.MULTILINE)
    step6_match = re.search(r"^### STEP 6 .*fix.loop", body, re.MULTILINE | re.IGNORECASE)
    assert step5_match, "test.md must have STEP 5 codegen heading"
    assert step6_match, "test.md must have STEP 6 fix-loop heading"
    assert step5_match.start() < step6_match.start(), (
        "STEP 5 codegen must come before STEP 6 fix-loop in test.md"
    )


def test_test_entry_orders_fix_loop_before_regression():
    """commands/vg/test.md: STEP 6 fix-loop MUST come before STEP 7 regression."""
    body = TEST_ENTRY.read_text()
    step6_match = re.search(r"^### STEP 6 .*fix.loop", body, re.MULTILINE | re.IGNORECASE)
    step7_match = re.search(r"^### STEP 7 .*regression", body, re.MULTILINE | re.IGNORECASE)
    assert step6_match, "test.md must have STEP 6 fix-loop heading"
    assert step7_match, "test.md must have STEP 7 regression heading"
    assert step6_match.start() < step7_match.start(), (
        "STEP 6 fix-loop must come before STEP 7 regression in test.md"
    )
