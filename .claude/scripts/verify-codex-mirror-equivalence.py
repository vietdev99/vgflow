#!/usr/bin/env python3
"""Verify functional equivalence between VG command sources and Codex skills.

The Codex mirror prepends a Codex adapter block, so line-by-line diffs are
noisy. This verifier compares only the workflow body:

  source repo mode:
    commands/vg/<name>.md                -> codex-skills/vg-<name>/SKILL.md
    skills/<name>/SKILL.md               -> codex-skills/<name>/SKILL.md

  installed project mode:
    .claude/commands/vg/<name>.md        -> .codex/skills/vg-<name>/SKILL.md
    .claude/skills/<name>/SKILL.md       -> .codex/skills/<name>/SKILL.md
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

ADAPTER_CLOSE = re.compile(r"</codex_skill_adapter>\s*\n", re.S)


def _has_source_repo_layout(root: Path) -> bool:
    return (root / "commands" / "vg").is_dir() and (root / "codex-skills").is_dir()


def _has_installed_layout(root: Path) -> bool:
    return (
        (root / ".claude" / "commands" / "vg").is_dir()
        and (root / ".codex" / "skills").is_dir()
    )


def resolve_repo_root() -> Path:
    env = os.environ.get("REPO_ROOT")
    if env:
        return Path(env).resolve()

    candidates = [Path.cwd().resolve()]
    script = Path(__file__).resolve()
    candidates.extend([script.parent, *script.parents])

    for candidate in candidates:
        if _has_source_repo_layout(candidate) or _has_installed_layout(candidate):
            return candidate

    return Path.cwd().resolve()


REPO_ROOT = resolve_repo_root()


def strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "\n".join(lines[idx + 1 :]).lstrip("\n")
    return text


def strip_mirror_adapter(text: str) -> str:
    match = ADAPTER_CLOSE.search(text)
    if not match:
        return strip_frontmatter(text)
    return text[match.end() :].lstrip("\n")


def normalize(text: str) -> str:
    cleaned = "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n")
    return cleaned + "\n" if cleaned else ""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_repo_pairs(root: Path) -> list[tuple[Path, Path, str]]:
    pairs: list[tuple[Path, Path, str]] = []
    commands_dir = root / "commands" / "vg"
    mirrors_dir = root / "codex-skills"

    for src in sorted(commands_dir.glob("*.md")):
        name = src.stem
        if name.startswith("_") or name.endswith("-insert"):
            continue
        skill_name = f"vg-{name}"
        mirror = mirrors_dir / skill_name / "SKILL.md"
        if mirror.exists():
            pairs.append((src, mirror, skill_name))

    for skill_name in _support_skill_names(root / "skills"):
        src = root / "skills" / skill_name / "SKILL.md"
        mirror = mirrors_dir / skill_name / "SKILL.md"
        if src.exists() and mirror.exists():
            pairs.append((src, mirror, skill_name))

    return pairs


def _installed_pairs(root: Path) -> list[tuple[Path, Path, str]]:
    pairs: list[tuple[Path, Path, str]] = []
    commands_dir = root / ".claude" / "commands" / "vg"
    mirrors_dir = root / ".codex" / "skills"

    for src in sorted(commands_dir.glob("*.md")):
        name = src.stem
        if name.startswith("_") or name.endswith("-insert"):
            continue
        skill_name = f"vg-{name}"
        mirror = mirrors_dir / skill_name / "SKILL.md"
        if mirror.exists():
            pairs.append((src, mirror, skill_name))

    for skill_name in _support_skill_names(root / ".claude" / "skills"):
        src = root / ".claude" / "skills" / skill_name / "SKILL.md"
        mirror = mirrors_dir / skill_name / "SKILL.md"
        if src.exists() and mirror.exists():
            pairs.append((src, mirror, skill_name))

    return pairs


def _support_skill_names(skills_dir: Path) -> list[str]:
    if not skills_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in skills_dir.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def find_pairs() -> list[tuple[Path, Path, str]]:
    if _has_source_repo_layout(REPO_ROOT):
        return _source_repo_pairs(REPO_ROOT)
    if _has_installed_layout(REPO_ROOT):
        return _installed_pairs(REPO_ROOT)
    return []


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str]) -> int:
    verbose = "-v" in argv or "--verbose" in argv
    json_out = "--json" in argv

    pairs = find_pairs()
    if not pairs:
        print(
            f"No source/mirror pairs found under {REPO_ROOT}. Check repo layout.",
            file=sys.stderr,
        )
        return 2

    drift: list[dict[str, object]] = []
    for src, mirror, skill in pairs:
        src_text = normalize(strip_frontmatter(src.read_text(encoding="utf-8")))
        mir_text = normalize(strip_mirror_adapter(mirror.read_text(encoding="utf-8")))
        src_hash = sha256(src_text)
        mir_hash = sha256(mir_text)

        if verbose:
            tag = "OK " if src_hash == mir_hash else "DIFF"
            print(f"  [{tag}] {skill} src={src_hash[:12]} mirror={mir_hash[:12]}")

        if src_hash != mir_hash:
            drift.append(
                {
                    "skill": skill,
                    "source": _rel(src),
                    "mirror": _rel(mirror),
                    "src_sha256": src_hash,
                    "mirror_sha256": mir_hash,
                    "src_bytes": len(src_text),
                    "mirror_bytes": len(mir_text),
                    "delta_bytes": len(mir_text) - len(src_text),
                }
            )

    if json_out:
        print(
            json.dumps(
                {
                    "repo_root": str(REPO_ROOT),
                    "checked": len(pairs),
                    "drift_count": len(drift),
                    "drift": drift,
                },
                indent=2,
            )
        )
        return 1 if drift else 0

    print(f"Checked {len(pairs)} skill mirror pair(s).")
    if not drift:
        print("OK: all mirrors functionally equivalent to source.")
        return 0

    print(f"DRIFT: {len(drift)} mirror(s) functionally differ from source:")
    for entry in drift:
        delta = entry["delta_bytes"]
        sign = "+" if delta >= 0 else ""
        print(f"  - {entry['skill']}")
        print(
            f"    source: {entry['source']} "
            f"({entry['src_bytes']}B sha={str(entry['src_sha256'])[:12]})"
        )
        print(
            f"    mirror: {entry['mirror']} "
            f"({entry['mirror_bytes']}B sha={str(entry['mirror_sha256'])[:12]}) "
            f"delta={sign}{delta}B"
        )
    print()
    print("Fix: run `bash scripts/generate-codex-skills.sh --force` and re-run this verifier.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
