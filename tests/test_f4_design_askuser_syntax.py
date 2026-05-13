"""tests/test_f4_design_askuser_syntax.py — F4 AskUserQuestion bash syntax."""
from __future__ import annotations
import re
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]

CASES = [
    REPO / "commands" / "vg" / "design-scaffold.md",
    REPO / "commands" / "vg" / "design-reverse.md",
]


def _bash_blocks(text):
    """Yield each ```bash ... ``` block contents."""
    return re.findall(r"```bash\n(.*?)\n```", text, flags=re.S)


def test_askuserquestion_not_inside_bash_block():
    failures = []
    for path in CASES:
        body = path.read_text(encoding="utf-8")
        for i, block in enumerate(_bash_blocks(body)):
            if "AskUserQuestion:" in block:
                failures.append(f"{path.name} bash block #{i+1}: AskUserQuestion: directive present")
    assert not failures, (
        "F4: AskUserQuestion: tool-call directive must NOT appear inside ```bash blocks "
        "(invalid bash syntax). Move to plain prose or non-bash code fence:\n  " +
        "\n  ".join(failures)
    )
