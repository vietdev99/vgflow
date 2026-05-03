#!/usr/bin/env python3
"""
VG Bootstrap — Learn Dedupe (v2.5 Phase H)

Pre-surface dedupe: candidates with similar titles get merged to avoid
showing the user near-duplicate rules at /vg:accept time.

Usage:
    python learn-dedupe.py                      # dry-run: show what would merge
    python learn-dedupe.py --apply              # rewrite CANDIDATES.md atomically
    python learn-dedupe.py --threshold 0.7      # custom similarity threshold
    python learn-dedupe.py --candidates-path /path/to/CANDIDATES.md
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional


# ─── Repo root resolution ────────────────────────────────────────────────────

def _repo_root() -> Path:
    env = os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env)
    p = Path(__file__).resolve()
    for parent in [p.parent, p.parent.parent, p.parent.parent.parent]:
        if (parent / ".claude" / "vg.config.md").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _repo_root()
BOOTSTRAP_DIR = REPO_ROOT / ".vg" / "bootstrap"
CONFIG_PATH = REPO_ROOT / ".claude" / "vg.config.md"


# ─── Config loading ──────────────────────────────────────────────────────────

def _load_dedupe_threshold(candidates_path: Optional[Path] = None) -> float:
    """Load dedupe_title_similarity from vg.config.md bootstrap section."""
    default = 0.8

    if not CONFIG_PATH.exists():
        return default

    text = CONFIG_PATH.read_text(encoding="utf-8", errors="replace")
    in_bootstrap = False

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("bootstrap:"):
            in_bootstrap = True
            continue
        if in_bootstrap:
            if stripped.startswith("---") or (line and not line[0].isspace() and ":" in line and not stripped.startswith("#")):
                break
            if "dedupe_title_similarity:" in stripped:
                v = stripped.partition(":")[2].strip().split("#")[0].strip()
                try:
                    return float(v)
                except ValueError:
                    return default

    return default


# ─── CANDIDATES.md parser (block-aware) ─────────────────────────────────────

class CandidateBlock:
    """Represents a single candidate including its raw fenced block text."""
    def __init__(self, candidate_id: str, title: str, raw_block: str,
                 start_fence: int, end_fence: int):
        self.id = candidate_id
        self.title = title
        self.raw_block = raw_block          # content inside the ```yaml...``` fences
        self.start_fence = start_fence      # char offset of opening ```yaml
        self.end_fence = end_fence          # char offset just after closing ```


def _parse_yaml_value(block_text: str, key: str) -> str:
    """Extract a top-level scalar value from YAML-like block text."""
    # Try ruamel.yaml first
    try:
        import ruamel.yaml
        y = ruamel.yaml.YAML()
        import io
        data = y.load(io.StringIO(block_text))
        if data and key in data:
            return str(data[key])
    except Exception:
        pass

    # Try pyyaml
    try:
        import yaml
        data = yaml.safe_load(block_text)
        if data and key in data:
            return str(data[key])
    except Exception:
        pass

    # Regex fallback
    m = re.search(rf"^{re.escape(key)}\s*:\s*['\"]?(.+?)['\"]?\s*$",
                  block_text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return ""


def _parse_candidate_blocks(candidates_path: Path) -> tuple[str, list[CandidateBlock]]:
    """Parse CANDIDATES.md and return (full_text, list_of_CandidateBlocks)."""
    if not candidates_path.exists():
        return "", []

    text = candidates_path.read_text(encoding="utf-8", errors="replace")
    blocks: list[CandidateBlock] = []

    # Match fenced ```yaml ... ``` blocks
    fence_pattern = re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL)
    for m in fence_pattern.finditer(text):
        block_text = m.group(1)
        if not re.search(r"^\s*id\s*:", block_text, re.MULTILINE):
            continue

        cid = _parse_yaml_value(block_text, "id")
        if not cid.startswith("L-"):
            continue

        title = _parse_yaml_value(block_text, "title")
        blocks.append(CandidateBlock(
            candidate_id=cid,
            title=title,
            raw_block=block_text,
            start_fence=m.start(),
            end_fence=m.end(),
        ))

    return text, blocks


# ─── Similarity ──────────────────────────────────────────────────────────────

def title_similarity(a: str, b: str) -> float:
    """Compute similarity between two candidate titles."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ─── Grouping ────────────────────────────────────────────────────────────────

def group_by_similarity(blocks: list[CandidateBlock],
                        threshold: float) -> list[list[CandidateBlock]]:
    """Group candidates where title similarity >= threshold.
    Simple greedy grouping: each candidate joins the first group whose
    representative (first member) is similar enough, or starts a new group.
    """
    groups: list[list[CandidateBlock]] = []

    for block in blocks:
        placed = False
        for group in groups:
            sim = title_similarity(group[0].title, block.title)
            if sim >= threshold:
                group.append(block)
                placed = True
                break
        if not placed:
            groups.append([block])

    return groups


# ─── Merge ───────────────────────────────────────────────────────────────────

def _merge_evidence_lines(blocks: list[CandidateBlock]) -> list[str]:
    """Collect all evidence sub-blocks from secondary candidates to merge into primary."""
    merged_evidence: list[str] = []
    for block in blocks[1:]:  # skip primary (first)
        text = block.raw_block
        # Find evidence: section in YAML block — everything after "evidence:" until next top-level key
        ev_match = re.search(r"^evidence\s*:(.*?)(?=^\w|\Z)", text,
                             re.DOTALL | re.MULTILINE)
        if ev_match:
            ev_text = ev_match.group(1).strip()
            if ev_text:
                merged_evidence.append(ev_text)
    return merged_evidence


def _add_merged_metadata(primary_block_text: str,
                         merged_ids: list[str],
                         extra_evidence: list[str]) -> str:
    """Inject dedupe_source field and merged evidence into primary block."""
    lines = primary_block_text.rstrip().splitlines()

    # Check if dedupe_source already exists
    has_dedupe_source = any(l.strip().startswith("dedupe_source:") for l in lines)

    # Inject dedupe_source before the last non-empty line if not present
    if not has_dedupe_source and merged_ids:
        source_line = f"dedupe_source: [{', '.join(merged_ids)}]"
        lines.append(source_line)

    # Merge evidence if any
    if extra_evidence:
        # Find evidence: section and append to it, or add a new one
        found_ev = False
        result_lines = []
        i = 0
        while i < len(lines):
            result_lines.append(lines[i])
            if lines[i].strip().startswith("evidence:") and not found_ev:
                found_ev = True
                # Add extra evidence items
                for ev in extra_evidence:
                    for ev_line in ev.splitlines():
                        result_lines.append("  " + ev_line)
            i += 1

        if not found_ev:
            # No existing evidence section — add one
            result_lines.append("evidence:")
            for ev in extra_evidence:
                for ev_line in ev.splitlines():
                    result_lines.append("  " + ev_line)

        return "\n".join(result_lines) + "\n"

    return "\n".join(lines) + "\n"


def apply_merges(full_text: str, groups: list[list[CandidateBlock]]) -> str:
    """Rewrite full_text with merged blocks. Secondary candidates are removed,
    primary gets dedupe_source field + merged evidence."""
    # Process groups in reverse order of start_fence to avoid offset drift
    merge_groups = [g for g in groups if len(g) >= 2]

    # Build a set of fence ranges to remove (secondary candidates)
    to_remove: set[tuple[int, int]] = set()
    # Build a map of primary block start → new block text
    replacements: dict[int, tuple[int, str]] = {}  # start → (end, new_block_text)

    for group in merge_groups:
        primary = group[0]
        secondary_ids = [b.id for b in group[1:]]
        extra_evidence = _merge_evidence_lines(group)

        new_inner = _add_merged_metadata(primary.raw_block, secondary_ids, extra_evidence)
        new_fence = f"```yaml\n{new_inner}```"
        replacements[primary.start_fence] = (primary.end_fence, new_fence)

        for sec in group[1:]:
            to_remove.add((sec.start_fence, sec.end_fence))

    # Apply changes — work from end of file to start to preserve offsets
    all_changes: list[tuple[int, int, str]] = []
    for start, (end, new_text) in replacements.items():
        all_changes.append((start, end, new_text))
    for start, end in to_remove:
        all_changes.append((start, end, ""))

    # Sort by start position descending to avoid offset drift
    all_changes.sort(key=lambda x: x[0], reverse=True)

    result = full_text
    for start, end, replacement in all_changes:
        # Clean up surrounding whitespace for removed blocks
        if replacement == "":
            # Remove the block including trailing newline(s)
            # Extend end to consume blank line after the block
            while end < len(result) and result[end] == "\n":
                end += 1
        result = result[:start] + replacement + result[end:]

    return result


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="VG Bootstrap Learn — Pre-surface Dedupe (v2.5 Phase H)"
    )
    ap.add_argument("--apply", action="store_true",
                    help="Rewrite CANDIDATES.md atomically with merged blocks")
    ap.add_argument("--threshold", type=float, default=None,
                    help="Title similarity threshold (default: from config or 0.8)")
    ap.add_argument("--candidates-path",
                    help="Path to CANDIDATES.md (default: .vg/bootstrap/CANDIDATES.md)")
    ap.add_argument("--emit", choices=["text", "json"], default="text",
                    help="Output format for dry-run (default: text)")
    args = ap.parse_args()

    candidates_path = Path(args.candidates_path) if args.candidates_path else BOOTSTRAP_DIR / "CANDIDATES.md"

    threshold = args.threshold if args.threshold is not None else _load_dedupe_threshold(candidates_path)

    full_text, blocks = _parse_candidate_blocks(candidates_path)

    if not blocks:
        if args.emit == "json":
            print(json.dumps({"groups": [], "merge_count": 0, "threshold": threshold}))
        else:
            print(f"No candidates found in {candidates_path}")
        return 0

    groups = group_by_similarity(blocks, threshold)
    merge_groups = [g for g in groups if len(g) >= 2]

    if args.emit == "json":
        output = {
            "threshold": threshold,
            "total_candidates": len(blocks),
            "total_groups": len(groups),
            "merge_count": len(merge_groups),
            "groups": [],
        }
        for g in groups:
            group_data = {
                "size": len(g),
                "will_merge": len(g) >= 2,
                "members": [],
            }
            for i, b in enumerate(g):
                sim = title_similarity(g[0].title, b.title) if i > 0 else 1.0
                group_data["members"].append({
                    "id": b.id,
                    "title": b.title,
                    "similarity_to_primary": round(sim, 3),
                    "role": "primary" if i == 0 else "secondary",
                })
            output["groups"].append(group_data)
        print(json.dumps(output, indent=2))
    else:
        # Text dry-run output
        print(f"Dedupe dry-run — threshold={threshold}")
        print(f"Total candidates: {len(blocks)}")
        print(f"Merge groups found: {len(merge_groups)}")

        if not merge_groups:
            print("No merges needed.")
        else:
            for g in merge_groups:
                primary = g[0]
                print(f"\n  Group (primary: {primary.id})")
                print(f"    {primary.id} [{primary.title!r}]  ← SURVIVOR")
                for sec in g[1:]:
                    sim = title_similarity(primary.title, sec.title)
                    print(f"    {sec.id} [{sec.title!r}]  similarity={sim:.3f}  → MERGED INTO {primary.id}")

    if args.apply:
        if not merge_groups:
            print("\nNothing to merge.")
            return 0

        new_text = apply_merges(full_text, groups)

        # Atomic write via temp file + rename
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=candidates_path.parent,
            prefix=".tmp-candidates-",
            suffix=".md",
            delete=False,
        )
        try:
            tmp.write(new_text)
            tmp.close()
            Path(tmp.name).replace(candidates_path)
            print(f"\nApplied {len(merge_groups)} merge(s) to {candidates_path}")
        except Exception as e:
            Path(tmp.name).unlink(missing_ok=True)
            print(f"Error writing {candidates_path}: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
