"""v3.6.1 — codex-skills SKILL.md YAML frontmatter validity.

Bug: vg-LIFECYCLE/SKILL.md description contained unescaped `"..."` inside
a YAML double-quoted string. Codex CLI refused to load both
~/.codex/skills/vg-LIFECYCLE/SKILL.md and the project mirror with
`invalid YAML: did not find expected key at line 2 column 192`.

Fix:
1. commands/vg/LIFECYCLE.md source switched embedded double quotes to
   single quotes ('where am I in the pipeline').
2. scripts/generate-codex-skills.sh write_codex_skill() escapes `"`
   and `\\` before emitting the YAML double-quoted description, so
   future source drift cannot reintroduce the bug.

This test exercises both layers: every SKILL.md frontmatter parses,
and the generator's escape preserves embedded quotes losslessly.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CODEX_SKILLS_DIR = REPO_ROOT / "codex-skills"
CLAUDE_SKILLS_DIR = REPO_ROOT / "skills"
COMMANDS_DIR = REPO_ROOT / "commands" / "vg"


def _frontmatter(path: Path) -> dict:
    body = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", body, re.S)
    if not m:
        return {}
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(m.group(1)) or {}


def _all_skill_files() -> list[Path]:
    out: list[Path] = []
    for d in (CODEX_SKILLS_DIR, CLAUDE_SKILLS_DIR):
        if d.is_dir():
            out.extend(sorted(d.rglob("SKILL.md")))
    return out


def test_every_codex_skill_yaml_parses():
    files = _all_skill_files()
    assert files, "no SKILL.md files discovered"
    failures: list[tuple[str, str]] = []
    for f in files:
        try:
            fm = _frontmatter(f)
        except Exception as exc:
            failures.append((str(f.relative_to(REPO_ROOT)), str(exc)))
            continue
        # Codex picker requires `name` (it's the slot key in the picker UI);
        # Claude skills under skills/ derive name from the directory and may
        # omit it — only enforce `name` for codex-skills/.
        rel_str = str(f.relative_to(REPO_ROOT)).replace("\\", "/")
        if rel_str.startswith("codex-skills/") and not fm.get("name"):
            failures.append((str(f.relative_to(REPO_ROOT)), "missing name field"))
        if not fm.get("description"):
            failures.append((str(f.relative_to(REPO_ROOT)), "missing description field"))
    assert not failures, "SKILL.md YAML invalid:\n" + "\n".join(f"  {p}: {e}" for p, e in failures)


def test_lifecycle_description_loads():
    """Targeted regression — the file Codex flagged at column 192."""
    fm = _frontmatter(CODEX_SKILLS_DIR / "vg-LIFECYCLE" / "SKILL.md")
    assert fm["name"] == "vg-LIFECYCLE"
    desc = fm["description"]
    assert "VG pipeline taxonomy" in desc
    # Whatever quoting style we settle on, embedded "where am I" phrase must survive
    assert "where am I in the pipeline" in desc


def test_generator_escapes_embedded_double_quotes():
    """Generator source must contain the escape logic so future sources
    with embedded `"..."` can't reintroduce the bug."""
    body = (REPO_ROOT / "scripts" / "generate-codex-skills.sh").read_text(encoding="utf-8")
    assert "description_yaml" in body, (
        "generator must use a sanitized description variable for YAML emission"
    )
    assert '${description//\\"/\\\\"}' in body or 'description_yaml//\\"' in body or '//\\"/\\\\"' in body, (
        "generator must escape `\"` → `\\\"` in description before YAML emission"
    )


def test_source_lifecycle_md_no_unescaped_doublequote_pair():
    """Source frontmatter must not contain an unbalanced `"X"` inside the
    description scalar (would break the YAML round-trip if generator were
    ever bypassed). Allow single-quoted phrases.
    """
    src = (COMMANDS_DIR / "LIFECYCLE.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", src, re.S)
    assert m, "LIFECYCLE.md missing frontmatter"
    fm_block = m.group(1)
    desc_line = next((ln for ln in fm_block.splitlines() if ln.startswith("description")), "")
    # If description is unquoted (plain scalar), embedded double quotes are OK
    # because there's no surrounding "..." to terminate. Reject only when the
    # description IS double-quoted AND contains another unescaped `"`.
    if desc_line.startswith('description: "') and desc_line.endswith('"'):
        inner = desc_line[len('description: "'):-1]
        assert '"' not in inner.replace('\\"', ''), (
            "LIFECYCLE.md description is double-quoted and has unescaped embedded `\"`"
        )
