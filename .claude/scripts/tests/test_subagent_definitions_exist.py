import yaml
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _frontmatter(path: Path) -> dict:
    body = path.read_text()
    assert body.startswith("---\n"), f"{path} missing YAML frontmatter"
    end = body.index("\n---\n", 4)
    return yaml.safe_load(body[4:end])


def test_planner_subagent():
    fm = _frontmatter(REPO / "agents/vg-blueprint-planner/SKILL.md")
    assert fm["name"] == "vg-blueprint-planner"
    assert fm["model"] == "opus"
    assert set(fm["tools"]) == {"Read", "Write", "Bash", "Grep"}


def test_contracts_subagent():
    fm = _frontmatter(REPO / "agents/vg-blueprint-contracts/SKILL.md")
    assert fm["name"] == "vg-blueprint-contracts"
    assert fm["model"] == "opus"
    assert set(fm["tools"]) == {"Read", "Write", "Bash", "Grep"}
