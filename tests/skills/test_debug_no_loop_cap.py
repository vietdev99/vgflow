"""debug.md Step 3 fix loop MUST NOT have a hard iteration cap.

Rule 2: 'AskUserQuestion-driven loop — no max iterations'. Capping the
loop violates the rule. This test asserts NO forbidden cap patterns
appear in Step 3 body.
"""
import re


FORBIDDEN_CAP_PATTERNS = [
    r"max(?:\s+|\s*=\s*|imum\s+)\d+\s+iteration",
    r"\d+\s+iteration\s+max",
    r"hard[-\s]?cap\w*\s+(?:at\s+|of\s+)?\d+",
    r"iteration[_\s]?count\s*[<≤]=?\s*\d+",
    r"iteration\s*[<≤]=?\s*\d+",
]


def test_debug_step3_has_no_cap(skill_loader):
    skill = skill_loader("debug")
    body = skill["body"]
    step3_match = re.search(
        r"^## Step 3(.*?)^## Step 4",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert step3_match, "Step 3 section not found in debug.md"
    step3 = step3_match.group(1)
    found_caps = []
    for pattern in FORBIDDEN_CAP_PATTERNS:
        if re.search(pattern, step3, flags=re.IGNORECASE):
            found_caps.append(pattern)
    assert not found_caps, (
        f"Step 3 contains forbidden iteration cap pattern(s): {found_caps}. "
        f"Rule 2 requires no max iterations (AskUserQuestion-driven)."
    )
