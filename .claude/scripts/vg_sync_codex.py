#!/usr/bin/env python3
"""
vg_sync_codex.py — Sync latest Claude vgflow commands -> codex SKILL.md mirrors.

Strategy:
  1. Read existing codex SKILL.md to preserve its <codex_skill_adapter> block
     (adapter is codex-specific: tool mappings, browser notes, Playwright pool).
  2. Read Claude .claude/commands/vg/{name}.md.
  3. Extract Claude body starting from <rules> (skip <NARRATION_POLICY>
     which is Claude-only).
  4. Combine: codex_frontmatter + <codex_skill_adapter>...</codex_skill_adapter>
     + Claude body.
  5. Write to BOTH .codex/skills/vg-{name}/SKILL.md and ~/.codex/skills/...

Usage:
  python vg_sync_codex.py              # dry-run, show plan
  python vg_sync_codex.py --apply      # do it
  python vg_sync_codex.py --only review,test,accept  # subset
  python vg_sync_codex.py --threshold 20  # skip skills with <20% size drift
"""
from __future__ import annotations

import sys
import re
import argparse
from pathlib import Path
from typing import Optional


def find_body_start(text: str) -> int:
    """Find character index where Claude body begins.
    Prefer <rules>, fall back to <objective>, then <process>.
    Skips <NARRATION_POLICY>...</NARRATION_POLICY> block if present.
    """
    # If NARRATION_POLICY present, body begins after it
    m_narr = re.search(r'</NARRATION_POLICY>\s*\n', text)
    if m_narr:
        # After NARRATION_POLICY, next structural tag:
        after = m_narr.end()
        m = re.search(r'<(rules|objective|process)>', text[after:])
        if m:
            return after + m.start()

    m = re.search(r'<(rules|objective|process)>', text)
    if m:
        return m.start()
    # Last resort: after frontmatter
    parts = text.split('\n---\n', 2)
    if len(parts) >= 3:
        return len(parts[0]) + len('\n---\n') + len(parts[1]) + len('\n---\n')
    return 0


def find_adapter_end(codex_text: str) -> Optional[int]:
    """Return char index right after </codex_skill_adapter>\\n (+ one trailing blank line)."""
    m = re.search(r'</codex_skill_adapter>\s*\n', codex_text)
    if not m:
        return None
    end = m.end()
    # Include trailing blank line if present
    rest = codex_text[end:]
    blank_m = re.match(r'\n', rest)
    if blank_m:
        end += blank_m.end()
    return end


def sync_one(claude_path: Path, codex_paths: list[Path], apply: bool) -> dict:
    """Sync one skill. Returns dict with old_size, new_size, action."""
    claude_text = claude_path.read_text(encoding='utf-8')
    body_start = find_body_start(claude_text)
    claude_body = claude_text[body_start:]

    # All codex mirrors should have same content — use first to extract header
    if not codex_paths or not codex_paths[0].exists():
        return {'skipped': 'codex mirror missing'}

    codex_text = codex_paths[0].read_text(encoding='utf-8')
    adapter_end = find_adapter_end(codex_text)
    if adapter_end is None:
        return {'skipped': 'no <codex_skill_adapter> block'}

    codex_header = codex_text[:adapter_end]
    new_content = codex_header + claude_body

    old_sizes = {str(p): p.stat().st_size if p.exists() else 0 for p in codex_paths}
    new_size = len(new_content.encode('utf-8'))

    if apply:
        for cp in codex_paths:
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(new_content, encoding='utf-8')

    return {
        'old_sizes': old_sizes,
        'new_size': new_size,
        'delta_pct': int((new_size - max(old_sizes.values(), default=1)) * 100 / max(max(old_sizes.values(), default=1), 1)),
        'action': 'applied' if apply else 'planned',
    }


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument('--apply', action='store_true', help='Actually write files (default: dry-run)')
    p.add_argument('--only', help='Comma-separated skill names (without vg- prefix)')
    p.add_argument('--threshold', type=int, default=0, help='Skip skills with abs(delta%%) < threshold')
    p.add_argument('--repo-root', default='.', help='Project root (default: cwd)')
    args = p.parse_args(argv)

    root = Path(args.repo_root).resolve()
    claude_dir = root / '.claude/commands/vg'
    codex_local = root / '.codex/skills'
    codex_home = Path.home() / '.codex/skills'

    only_set = None
    if args.only:
        only_set = set(x.strip() for x in args.only.split(','))

    # Discover skills — any claude command that has a codex mirror
    candidates = []
    for md in sorted(claude_dir.glob('*.md')):
        name = md.stem
        if name.startswith('_'):
            continue  # _shared, internal
        if only_set and name not in only_set:
            continue
        codex_paths = [
            codex_local / f'vg-{name}' / 'SKILL.md',
            codex_home / f'vg-{name}' / 'SKILL.md',
        ]
        # Skip if codex mirror doesn't exist (not all Claude commands have codex skills)
        if not codex_paths[0].exists():
            continue
        candidates.append((name, md, codex_paths))

    print(f"Found {len(candidates)} skill pairs to consider.")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Threshold: {args.threshold}% drift")
    print()

    applied = 0
    skipped = 0
    for name, claude_md, codex_paths in candidates:
        r = sync_one(claude_md, codex_paths, apply=False)  # dry-run first to get sizes
        if 'skipped' in r:
            skipped += 1
            continue
        delta = r['delta_pct']
        max_old = max(r['old_sizes'].values(), default=0)
        new = r['new_size']

        if abs(delta) < args.threshold:
            print(f"  ⏭  vg-{name:<25}  {max_old:>6} -> {new:>6}  ({delta:+d}%)  [below threshold]")
            skipped += 1
            continue

        if args.apply:
            sync_one(claude_md, codex_paths, apply=True)
            applied += 1
            print(f"  ✓ vg-{name:<25}  {max_old:>6} -> {new:>6}  ({delta:+d}%)  [APPLIED to {len(codex_paths)} dirs]")
        else:
            print(f"  ▸ vg-{name:<25}  {max_old:>6} -> {new:>6}  ({delta:+d}%)  [would apply]")
            applied += 1

    print()
    print(f"Summary: {applied} {'applied' if args.apply else 'planned'}, {skipped} skipped.")
    if not args.apply and applied > 0:
        print("Re-run with --apply to commit.")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
