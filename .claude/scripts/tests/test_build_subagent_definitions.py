import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, f"{path} missing YAML frontmatter"
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def test_task_executor_definition():
    p = REPO / "agents/vg-build-task-executor/SKILL.md"
    assert p.exists(), f"missing {p}"
    fm = _frontmatter(p)
    assert fm.get("name") == "vg-build-task-executor"
    assert fm.get("description", "").startswith('"'), "description must be quoted (R1a YAML lesson)"
    body = p.read_text()
    # Must NOT include Agent in tools (no nested spawn)
    tools_line = fm.get("tools", "")
    assert "Agent" not in tools_line, f"task-executor must not have Agent tool (no nested spawn). tools={tools_line}"
    # Must include HARD-GATE
    assert "<HARD-GATE>" in body, "task-executor missing HARD-GATE block"
    # Must reference vg-binding requirement
    assert "vg-binding" in body, "task-executor missing vg-binding citation requirement"
    # Must reference BUILD-LOG/task- per-task log (R1a UX baseline Req 1)
    assert "BUILD-LOG/task-" in body, "task-executor missing BUILD-LOG per-task log requirement"


def test_post_executor_definition():
    p = REPO / "agents/vg-build-post-executor/SKILL.md"
    assert p.exists(), f"missing {p}"
    fm = _frontmatter(p)
    assert fm.get("name") == "vg-build-post-executor"
    assert fm.get("description", "").startswith('"'), "description must be quoted"
    body = p.read_text()
    tools_line = fm.get("tools", "")
    assert "Agent" not in tools_line, f"post-executor must not have Agent tool. tools={tools_line}"
    assert "<HARD-GATE>" in body, "post-executor missing HARD-GATE block"
    # Read-only verifier
    assert "READ-ONLY" in body or "read-only" in body, "post-executor must declare READ-ONLY semantic"
    # Must concat BUILD-LOG (R1a UX baseline Req 1)
    assert "BUILD-LOG.md" in body and "BUILD-LOG/index.md" in body, "post-executor must concat 3-layer BUILD-LOG"
