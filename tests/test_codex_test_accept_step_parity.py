from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\n.*?\n---\n\n?", "", text, count=1, flags=re.S)


def _strip_codex_only_blocks(text: str) -> str:
    text = _strip_frontmatter(text)
    text = re.sub(
        r"<codex_skill_adapter>.*?</codex_skill_adapter>\n\n?",
        "",
        text,
        count=1,
        flags=re.S,
    )
    text = re.sub(
        r"<HARD-GATE-CODEX>.*?</HARD-GATE-CODEX>\n\n?",
        "",
        text,
        count=1,
        flags=re.S,
    )
    return text


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()).strip() + "\n"


def _workflow_body(path: Path) -> str:
    return _normalize(_strip_frontmatter(path.read_text(encoding="utf-8")))


def _codex_workflow_body(path: Path) -> str:
    return _normalize(_strip_codex_only_blocks(path.read_text(encoding="utf-8")))


def _step_sequence(text: str) -> list[str]:
    steps = re.findall(r"^### (STEP [^\n]+)", text, flags=re.M)
    steps += re.findall(r'<step name="([^"]+)">', text)
    return steps


def test_codex_test_accept_and_test_spec_bodies_match_claude_source() -> None:
    for name in ("test", "accept", "test-spec", "roam"):
        source = _workflow_body(REPO_ROOT / "commands" / "vg" / f"{name}.md")
        codex = _codex_workflow_body(
            REPO_ROOT / "codex-skills" / f"vg-{name}" / "SKILL.md"
        )
        assert codex == source, (
            f"codex-skills/vg-{name}/SKILL.md must match "
            f"commands/vg/{name}.md after removing Codex adapter blocks"
        )


def test_codex_test_accept_and_test_spec_step_order_matches_claude() -> None:
    for name in ("test", "accept", "test-spec", "roam"):
        source = _workflow_body(REPO_ROOT / "commands" / "vg" / f"{name}.md")
        codex = _codex_workflow_body(
            REPO_ROOT / "codex-skills" / f"vg-{name}" / "SKILL.md"
        )
        assert _step_sequence(codex) == _step_sequence(source)
