#!/usr/bin/env python3
"""verify-codex-mirror-equivalence.py — N10 fix from build-vs-blueprint audit.

Hashes the post-adapter content of each `.codex/skills/vg-<name>/SKILL.md`
mirror against the post-frontmatter content of its source
`.claude/commands/vg/<name>.md`, after stripping codex-specific
adornments. Exits non-zero if any pair drifts.

Why: the regular `sync.sh --check` line-level diff reports thousands of
"differing" lines because the Codex adapter block prepends ~80 lines to
every mirror. Real functional drift is invisible inside that noise.
This verifier ignores the offset and compares only what executors run.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands" / "vg"
MIRRORS_DIR = REPO_ROOT / ".codex" / "skills"

ADAPTER_CLOSE = re.compile(r"</codex_skill_adapter>\s*\n")


def strip_source_frontmatter(text: str) -> str:
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
        return text
    return text[match.end() :].lstrip("\n")


def normalize(text: str) -> str:
    cleaned = "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n")
    return cleaned + "\n" if cleaned else ""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_pairs() -> list[tuple[Path, Path, str]]:
    pairs: list[tuple[Path, Path, str]] = []
    if not COMMANDS_DIR.exists() or not MIRRORS_DIR.exists():
        return pairs
    for src in sorted(COMMANDS_DIR.glob("*.md")):
        if src.name.startswith("_"):
            continue
        skill_name = "vg-" + src.stem
        mirror = MIRRORS_DIR / skill_name / "SKILL.md"
        if mirror.exists():
            pairs.append((src, mirror, skill_name))
    return pairs


def main(argv: list[str]) -> int:
    verbose = "-v" in argv or "--verbose" in argv
    json_out = "--json" in argv

    pairs = find_pairs()
    if not pairs:
        print("No (source, mirror) pairs found. Check repo layout.", file=sys.stderr)
        return 2

    drift: list[dict[str, object]] = []
    for src, mirror, skill in pairs:
        src_text = normalize(strip_source_frontmatter(src.read_text(encoding="utf-8")))
        mir_text = normalize(strip_mirror_adapter(mirror.read_text(encoding="utf-8")))
        src_hash = sha256(src_text)
        mir_hash = sha256(mir_text)
        if verbose:
            tag = "OK " if src_hash == mir_hash else "DIFF"
            print(f"  [{tag}] {skill}  src={src_hash[:12]} mirror={mir_hash[:12]}")
        if src_hash != mir_hash:
            drift.append(
                {
                    "skill": skill,
                    "source": str(src.relative_to(REPO_ROOT)),
                    "mirror": str(mirror.relative_to(REPO_ROOT)),
                    "src_sha256": src_hash,
                    "mirror_sha256": mir_hash,
                    "src_bytes": len(src_text),
                    "mirror_bytes": len(mir_text),
                    "delta_bytes": len(mir_text) - len(src_text),
                }
            )

    if json_out:
        import json as _json

        print(
            _json.dumps(
                {"checked": len(pairs), "drift_count": len(drift), "drift": drift},
                indent=2,
            )
        )
        return 1 if drift else 0

    print(f"Checked {len(pairs)} skill mirror pair(s).")
    if not drift:
        print("✓ All mirrors functionally equivalent to source.")
        return 0

    print(f"✗ {len(drift)} mirror(s) drift — functional content differs from source:")
    for entry in drift:
        delta = entry["delta_bytes"]
        sign = "+" if delta >= 0 else ""
        print(f"  ✗ {entry['skill']}")
        print(f"      source : {entry['source']} ({entry['src_bytes']}B sha={str(entry['src_sha256'])[:12]})")
        print(f"      mirror : {entry['mirror']} ({entry['mirror_bytes']}B sha={str(entry['mirror_sha256'])[:12]}) Δ={sign}{delta}B")
    print()
    print("Fix: re-run /vg:sync to regenerate mirrors from source, then re-run /vg:sync --verify.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
