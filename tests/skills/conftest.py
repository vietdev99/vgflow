"""Shared fixtures for VG skill (commands/vg/*.md) static tests."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMANDS_DIR = REPO_ROOT / "commands" / "vg"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    fm = yaml.safe_load(text[4:end])
    body = text[end + 5:]
    return (fm or {}), body


@pytest.fixture
def skill_loader():
    def _load(name: str) -> dict:
        path = COMMANDS_DIR / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"skill {name} not at {path}")
        text = path.read_text()
        fm, body = _split_frontmatter(text)
        return {
            "name": name,
            "path": path,
            "text": text,
            "lines": text.count("\n") + (0 if text.endswith("\n") else 1),
            "frontmatter": fm,
            "body": body,
        }
    return _load


@pytest.fixture
def agent_loader():
    def _load(name: str) -> dict:
        # Agents may be stored as `<name>.md` OR as `<name>/` directory.
        md_path = AGENTS_DIR / f"{name}.md"
        dir_path = AGENTS_DIR / name
        path = md_path if md_path.exists() else (dir_path / "agent.md" if (dir_path / "agent.md").exists() else None)
        if path is None or not path.exists():
            raise FileNotFoundError(f"agent {name} not at {md_path} or {dir_path}/agent.md")
        text = path.read_text()
        fm, body = _split_frontmatter(text)
        return {"name": name, "path": path, "text": text, "frontmatter": fm, "body": body}
    return _load


def grep_count(body: str, pattern: str) -> int:
    return len(re.findall(pattern, body, flags=re.MULTILINE))
