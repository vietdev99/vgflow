#!/usr/bin/env python3
"""edge-cases-to-spec.py — Convert EDGE-CASES/G-NN.md → Playwright spec.ts skeleton.

Mục đích: từ EDGE-CASES variants (sinh bởi blueprint), tạo `.spec.ts` skeleton
với `test.each([...variants])` per goal. AI fill phần body (selector, click,
fill, assertion) — script lo skeleton cứng (variant_id, expected_outcome,
priority, comment anchor cho coverage check).

Use cases:
1. Test codegen subagent (vg-test-codegen) gọi script này thay vì tự gen
   skeleton — đảm bảo deterministic format
2. Manual: developer chạy `python edge-cases-to-spec.py --phase N --goal G-04`
   để xem skeleton trước khi build code
3. Migration: legacy phase có EDGE-CASES nhưng không có spec → dùng để bootstrap

Usage:
  edge-cases-to-spec.py --phase 4.1 --goal G-04
    → in spec.ts skeleton lên stdout

  edge-cases-to-spec.py --phase 4.1 --all --output-dir tests/generated
    → ghi tất cả goals thành tests/generated/G-NN.spec.ts files

Flags:
  --phase N            Phase number (e.g., 4.1)
  --phase-dir DIR      Override phase dir resolution
  --goal G-NN          Single goal (default: all goals trong EDGE-CASES/)
  --all                Process all goals (default true if --goal absent)
  --output-dir DIR     Write per-goal .spec.ts files (default: stdout)
  --framework <name>   playwright | vitest | jest (default: playwright)
  --dry-run            Print plan only, don't write
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "validators"))
try:
    from _common import find_phase_dir  # type: ignore
except ImportError:
    def find_phase_dir(phase: str | None):
        if not phase:
            return None
        repo_root = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
        phases_dir = repo_root / ".vg" / "phases"
        if not phases_dir.exists():
            return None
        for d in phases_dir.iterdir():
            if d.is_dir() and (d.name.startswith(f"{phase}-") or d.name == phase):
                return d
        return None


VARIANT_ROW_RE = re.compile(
    r"^\|\s*(G-\d+-[a-z]\d+)\s*\|(.+?)\|", re.MULTILINE
)
GOAL_TITLE_RE = re.compile(r"^#\s+Edge Cases\s*[—-]\s*(G-\d+):\s*(.+?)$", re.MULTILINE)
SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)$", re.MULTILINE)
PRIORITY_RE = re.compile(r"\b(critical|high|medium|low)\b", re.IGNORECASE)


def _parse_goal_file(path: Path) -> dict:
    """Parse EDGE-CASES/G-NN.md → structured data."""
    text = path.read_text(encoding="utf-8")
    title_match = GOAL_TITLE_RE.search(text)
    goal_id = title_match.group(1) if title_match else path.stem
    goal_title = title_match.group(2).strip() if title_match else "(unknown)"

    # Extract variants grouped by section
    variants = []
    current_section = "default"
    for line in text.splitlines():
        # Section header
        sm = SECTION_HEADER_RE.match(line)
        if sm:
            current_section = sm.group(1).strip()
            continue
        # Variant row
        vm = re.match(r"^\|\s*(G-\d+-[a-z]\d+)\s*\|(.+?)\|", line)
        if vm:
            cells = [c.strip() for c in line.split("|")[1:-1]]
            variant_id = cells[0]
            input_or_scenario = cells[1] if len(cells) > 1 else ""
            expected = cells[2] if len(cells) > 2 else ""
            priority = ""
            for cell in reversed(cells):
                if PRIORITY_RE.match(cell or ""):
                    priority = cell.lower()
                    break
            variants.append({
                "variant_id": variant_id,
                "section": current_section,
                "input": input_or_scenario,
                "expected": expected,
                "priority": priority or "medium",
            })

    return {
        "goal_id": goal_id,
        "goal_title": goal_title,
        "variants": variants,
        "source_file": str(path),
    }


def _ts_string(s: str) -> str:
    """Escape string for embedding in TypeScript."""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")


def _render_playwright_spec(goal: dict) -> str:
    """Generate Playwright spec.ts skeleton for one goal."""
    goal_id = goal["goal_id"]
    title = goal["goal_title"]
    variants = goal["variants"]

    if not variants:
        return f"""// vg-goal: {goal_id}
// Goal: {title}
// Source: {goal["source_file"]}
//
// NO variants in EDGE-CASES — generate single-path test or skip.
import {{ test, expect }} from '@playwright/test';

test.describe('{goal_id}: {title}', () => {{
  test('happy path', async ({{ page }}) => {{
    // TODO: AI fill default test body (no edge case variants declared)
  }});
}});
"""

    # Group by section for readable output
    sections: dict[str, list[dict]] = {}
    for v in variants:
        sections.setdefault(v["section"], []).append(v)

    out = []
    out.append(f"// vg-goal: {goal_id}")
    out.append(f"// Goal: {title}")
    out.append(f"// Source: {goal['source_file']}")
    out.append(f"// Variants: {len(variants)} ({sum(1 for v in variants if v['priority']=='critical')} critical)")
    out.append("//")
    out.append("// AI: fill body cho mỗi variant. Mỗi `test.each` row PHẢI:")
    out.append("//   1. Trigger input/scenario như column 'input'")
    out.append("//   2. Assert expected_outcome như column 'expected'")
    out.append("//   3. Reference variant_id trong test name (already done)")
    out.append("//")
    out.append("import { test, expect } from '@playwright/test';")
    out.append("")
    out.append(f"test.describe('{goal_id}: {_ts_string(title)}', () => {{")

    for section, sec_variants in sections.items():
        out.append(f"")
        out.append(f"  // ─── {section} ───")
        out.append(f"  test.each([")
        for v in sec_variants:
            out.append(f"    {{")
            out.append(f"      variant: '{v['variant_id']}',")
            out.append(f"      input: '{_ts_string(v['input'])}',")
            out.append(f"      expected: '{_ts_string(v['expected'])}',")
            out.append(f"      priority: '{v['priority']}',")
            out.append(f"    }},")
        out.append(f"  ])(")
        out.append(f"    '$variant — $input → $expected',")
        out.append(f"    async ({{ variant, input, expected, priority }}, {{ page }}) => {{")
        out.append(f"      // vg-edge-case: ${{variant}}  ← anchor cho coverage check (verify-edge-cases-contract.py)")
        out.append(f"      // TODO: AI fill body — replay scenario, trigger {section.lower()},")
        out.append(f"      //       assert expected_outcome matches actual response/UI state.")
        out.append(f"      // Skip if priority=low + --skip-low-edge-cases flag set:")
        out.append(f"      //   test.skip(priority === 'low' && process.env.VG_SKIP_LOW_EDGE_CASES === '1');")
        out.append(f"    }}")
        out.append(f"  );")

    out.append("});")
    return "\n".join(out)


def _render_vitest_spec(goal: dict) -> str:
    """Generate Vitest spec.ts skeleton (API-style, no browser)."""
    goal_id = goal["goal_id"]
    title = goal["goal_title"]
    variants = goal["variants"]

    if not variants:
        return f"""// vg-goal: {goal_id}
// Goal: {title}
// Source: {goal["source_file"]}
//
// NO variants — single-path test.
import {{ describe, test, expect }} from 'vitest';

describe('{goal_id}: {title}', () => {{
  test('happy path', async () => {{
    // TODO: AI fill
  }});
}});
"""

    sections: dict[str, list[dict]] = {}
    for v in variants:
        sections.setdefault(v["section"], []).append(v)

    out = []
    out.append(f"// vg-goal: {goal_id}")
    out.append(f"// Goal: {title}")
    out.append(f"// Source: {goal['source_file']}")
    out.append(f"// Variants: {len(variants)}")
    out.append("import { describe, test, expect } from 'vitest';")
    out.append("")
    out.append(f"describe('{goal_id}: {_ts_string(title)}', () => {{")
    for section, sec_variants in sections.items():
        out.append(f"")
        out.append(f"  describe('{_ts_string(section)}', () => {{")
        for v in sec_variants:
            out.append(f"    test('{v['variant_id']} — {_ts_string(v['expected'])[:60]}', async () => {{")
            out.append(f"      // vg-edge-case: {v['variant_id']}")
            out.append(f"      // input: {v['input']}")
            out.append(f"      // expected: {v['expected']}")
            out.append(f"      // priority: {v['priority']}")
            out.append(f"      // TODO: AI fill")
            out.append(f"    }});")
        out.append(f"  }});")
    out.append("});")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="EDGE-CASES → spec.ts skeleton")
    parser.add_argument("--phase", help="Phase number")
    parser.add_argument("--phase-dir", help="Override phase dir")
    parser.add_argument("--goal", help="Single goal ID (e.g., G-04)")
    parser.add_argument("--all", action="store_true", help="Process all goals (default if --goal absent)")
    parser.add_argument("--output-dir", help="Write per-goal .spec.ts files")
    parser.add_argument("--framework", default="playwright",
                        choices=["playwright", "vitest"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    phase_dir = Path(args.phase_dir) if args.phase_dir else find_phase_dir(args.phase)
    if not phase_dir or not phase_dir.exists():
        print(f"ERROR: phase dir not found for phase={args.phase}", file=sys.stderr)
        return 1

    edge_dir = phase_dir / "EDGE-CASES"
    if not edge_dir.exists():
        print(f"ERROR: EDGE-CASES/ not found at {edge_dir}", file=sys.stderr)
        return 2

    if args.goal:
        gfiles = [edge_dir / f"{args.goal}.md"]
        if not gfiles[0].exists():
            print(f"ERROR: {gfiles[0]} not found", file=sys.stderr)
            return 2
    else:
        gfiles = sorted(edge_dir.glob("G-*.md"))
        if not gfiles:
            print(f"ERROR: no G-*.md files in {edge_dir}", file=sys.stderr)
            return 2

    render = _render_playwright_spec if args.framework == "playwright" else _render_vitest_spec

    output_dir = Path(args.output_dir) if args.output_dir else None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    for gfile in gfiles:
        goal = _parse_goal_file(gfile)
        spec_content = render(goal)

        if args.dry_run:
            print(f"▸ would generate {goal['goal_id']}.spec.ts ({len(goal['variants'])} variants)")
            continue

        if output_dir:
            out_path = output_dir / f"{goal['goal_id']}.spec.ts"
            out_path.write_text(spec_content)
            print(f"✓ wrote {out_path}")
        else:
            print(f"// ════════════════ {goal['goal_id']}.spec.ts ════════════════")
            print(spec_content)
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
