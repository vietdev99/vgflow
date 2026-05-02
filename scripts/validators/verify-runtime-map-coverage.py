#!/usr/bin/env python3
"""
verify-runtime-map-coverage.py — v2.35.0 closes #51 invariant 2.

Hard invariant: every UI-surface goal in TEST-GOALS.md has BOTH:
  1. views[X].elements.length > 0 in RUNTIME-MAP.json
  2. goal_sequences[id].steps.length > 0 in RUNTIME-MAP.json

Catches the verdict-gate gap where review claims PASS but RUNTIME-MAP
has empty elements / no replay steps (issue #51 root cause).

Supports two TEST-GOALS.md formats:
  - YAML frontmatter blocks (`--- ... ---`)
  - Markdown headers (`## Goal G-XX: title` + `**Field:** value` lines)

v2.45 fail-closed-validators (PR fix/fail-closed-validators-coverage-fabrication):
  - Added markdown parser for `## Goal G-XX` format. Previously YAML-only —
    Phase 3.2 used markdown and validator silently passed on 0 parsed goals.
  - FAIL CLOSED on unparseable TEST-GOALS.md. Previously returned 0 with
    advisory message "(no parseable goals — passing)".

Usage:
  verify-runtime-map-coverage.py --phase-dir <path>
  verify-runtime-map-coverage.py --phase-dir <path> --severity warn

Exit codes:
  0 — all UI goals covered (or severity=warn)
  1 — gap found (severity=block) OR TEST-GOALS unparseable (was 0 — fixed)
  2 — config error (RUNTIME-MAP or TEST-GOALS missing)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
sys.path.insert(0, str(Path(__file__).parent))
from _common import find_phase_dir  # noqa: E402

# Markdown goal header: `## Goal G-12: title (P3.D-46)`
GOAL_HEADER_RE = re.compile(r"^##\s+Goal\s+(G-[A-Z0-9-]+)\s*:?\s*(.*)$", re.IGNORECASE)
# Field line: `**Surface:** ui`
FIELD_LINE_RE = re.compile(r"^\*\*([A-Za-z][A-Za-z _-]*?)\s*:\*\*\s*(.*)$")


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _normalize_field_key(label: str) -> str:
    return label.strip().lower().replace(" ", "_").replace("-", "_")


def _parse_yaml_blocks(text: str) -> list[dict]:
    try:
        import yaml
    except ImportError:
        return []

    blocks: list[str] = []
    cur: list[str] = []
    in_block = False
    for line in text.splitlines():
        if line.strip() == "---":
            if in_block:
                blocks.append("\n".join(cur))
                cur = []
                in_block = False
            else:
                in_block = True
            continue
        if in_block:
            cur.append(line)

    out: list[dict] = []
    for blob in blocks:
        try:
            data = yaml.safe_load(blob) or {}
        except Exception:
            continue
        if isinstance(data, dict) and str(data.get("id", "")).startswith("G-"):
            out.append(data)
    return out


def _parse_markdown_goals(text: str) -> list[dict]:
    """Parse `## Goal G-XX: title` headers + subsequent `**Field:** value` lines.

    Stops a goal block at next `## ` header or `---` separator. Surface defaults
    to 'ui' to mirror legacy behavior — explicit `**Surface:** api` etc.
    overrides.
    """
    out: list[dict] = []
    cur: dict | None = None

    def _flush():
        if cur and cur.get("id"):
            out.append(cur.copy())

    for raw in text.splitlines():
        line = raw.rstrip()
        m_header = GOAL_HEADER_RE.match(line)
        if m_header:
            _flush()
            cur = {"id": m_header.group(1).upper(), "title": m_header.group(2).strip()}
            continue
        if cur is None:
            continue
        # End-of-block separators
        if line.startswith("## ") or line.strip() == "---":
            _flush()
            cur = None
            continue
        m_field = FIELD_LINE_RE.match(line)
        if m_field:
            key = _normalize_field_key(m_field.group(1))
            val = m_field.group(2).strip()
            # Field name aliases for downstream consumers
            if key == "surface":
                cur["surface"] = val.lower()
            elif key in {"maps_to_view", "view"}:
                cur["maps_to_view"] = val
            else:
                cur[key] = val
    _flush()
    return out


def parse_test_goals(path: Path) -> tuple[list[dict], str]:
    """Return (goals, format_used). format_used in {'yaml', 'markdown', 'none'}."""
    if not path.is_file():
        return [], "none"
    text = path.read_text(encoding="utf-8", errors="replace")

    yaml_goals = _parse_yaml_blocks(text)
    if yaml_goals:
        return yaml_goals, "yaml"

    md_goals = _parse_markdown_goals(text)
    if md_goals:
        return md_goals, "markdown"

    return [], "none"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--phase-dir")
    src.add_argument("--phase")
    ap.add_argument("--severity", choices=["warn", "block"], default="block")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve() if args.phase_dir else find_phase_dir(args.phase)
    if phase_dir is None:
        print(f"⛔ Phase dir not found for phase: {args.phase}", file=sys.stderr)
        return 2
    if not phase_dir.is_dir():
        print(f"⛔ Phase dir not found: {phase_dir}", file=sys.stderr)
        return 2

    rmap = load_json(phase_dir / "RUNTIME-MAP.json")
    if not rmap:
        print(f"⛔ RUNTIME-MAP.json missing in {phase_dir}", file=sys.stderr)
        return 2

    goals_path = phase_dir / "TEST-GOALS.md"
    if not goals_path.is_file():
        print(f"⛔ TEST-GOALS.md missing in {phase_dir}", file=sys.stderr)
        return 2

    goals, fmt = parse_test_goals(goals_path)
    if not goals:
        # FAIL CLOSED (was: return 0 silently). Unparseable TEST-GOALS means
        # we cannot enforce the invariant. Treat as a gap.
        msg = (
            f"⛔ TEST-GOALS.md unparseable — neither YAML frontmatter blocks nor "
            f"`## Goal G-XX` markdown headers found in {goals_path}. Validator "
            f"cannot enforce coverage invariant. Fix the file format then re-run."
        )
        if args.json:
            print(json.dumps({
                "phase_dir": str(phase_dir),
                "ui_goals_total": 0,
                "gaps": [],
                "gate_pass": False,
                "severity": args.severity,
                "error": "test_goals_unparseable",
            }, indent=2))
        elif not args.quiet:
            print(msg)
        return 1 if args.severity == "block" else 0

    views = rmap.get("views") or {}
    sequences = rmap.get("goal_sequences") or {}

    gaps: list[dict] = []
    for goal in goals:
        gid = goal.get("id")
        surface = (goal.get("surface") or "ui").lower()
        if surface not in {"ui", "ui-mobile"}:
            continue

        view_url = goal.get("maps_to_view") or goal.get("view")
        view_data = views.get(view_url) if view_url else None
        elements = (view_data or {}).get("elements") if isinstance(view_data, dict) else None
        elements_count = len(elements) if isinstance(elements, list) else 0

        seq = sequences.get(gid) or {}
        steps = seq.get("steps") if isinstance(seq, dict) else None
        steps_count = len(steps) if isinstance(steps, list) else 0

        if steps_count == 0:
            # Missing goal_sequences entirely — covers the Phase 3.2 case where
            # 40/67 goals had no sequence recorded but matrix said READY.
            reason = "no_sequence_in_runtime_map"
        elif elements_count == 0 and view_url:
            reason = "elements_empty"
        else:
            continue

        gaps.append({
            "goal_id": gid,
            "surface": surface,
            "view": view_url,
            "elements_count": elements_count,
            "steps_count": steps_count,
            "reason": reason,
        })

    ui_goals_total = sum(
        1 for g in goals if (g.get("surface") or "ui").lower() in {"ui", "ui-mobile"}
    )

    payload = {
        "phase_dir": str(phase_dir),
        "format": fmt,
        "ui_goals_total": ui_goals_total,
        "gaps": gaps,
        "gate_pass": len(gaps) == 0,
        "severity": args.severity,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        if not gaps:
            print(
                f"✓ Runtime-map coverage OK ({ui_goals_total} UI goals via {fmt}, "
                f"all have elements + steps)"
            )
        else:
            tag = "⛔" if args.severity == "block" else "⚠ "
            print(f"{tag} Runtime-map coverage: {len(gaps)}/{ui_goals_total} gap(s) (format={fmt})")
            for g in gaps:
                print(
                    f"   {g['goal_id']} on {g['view'] or '<no-view>'}: {g['reason']} "
                    f"(elements={g['elements_count']}, steps={g['steps_count']})"
                )

    if gaps and args.severity == "block":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
