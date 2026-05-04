#!/usr/bin/env python3
"""
verify-view-decomposition.py — P19 D-02 gate.

After /vg:blueprint step 2b6c emits ${PHASE_DIR}/VIEW-COMPONENTS.md from
vision-Read PNG of every <design-ref> slug in PLAN, validate the output:

  - For each slug section in VIEW-COMPONENTS.md: ≥3 distinct components
  - No component name in a banlist of generic terms (div, container,
    wrapper, section alone, layout alone, root, page) — must be semantic
  - Every component has non-empty position field (x,y,w,h%)

The gate's purpose is to catch the failure mode where the vision agent
emits a stub like "[{name:'page', position:''}]" instead of doing the
real decomposition.

USAGE
  python verify-view-decomposition.py \
    --phase-dir .vg/phases/07.10-... \
    [--manifest .vg/design-normalized/manifest.json] \
    [--require true|false] \
    [--output report.json]

EXIT
  0 — PASS or SKIP (no slugs in PLAN, or VIEW-COMPONENTS.md absent + require=false)
  1 — BLOCK (VIEW-COMPONENTS.md missing while required, or any section fails checks)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

GENERIC_NAMES = {
    "div",
    "container",
    "wrapper",
    "section",
    "layout",
    "root",
    "page",
    "main",
    "body",
    "content",
    "block",
    "element",
    "node",
}
MIN_COMPONENTS_PER_SLUG = 3


def parse_view_components(text: str) -> dict[str, list[dict]]:
    """Parse `## {slug}` sections with markdown table rows into dict[slug] -> [rows]."""
    sections: dict[str, list[dict]] = {}
    current: str | None = None
    headers: list[str] | None = None
    seen_separator = False
    for raw in text.splitlines():
        line = raw.strip()
        m_h2 = re.match(r"^##\s+([A-Za-z0-9][A-Za-z0-9_-]+)\s*$", line)
        if m_h2:
            current = m_h2.group(1)
            headers = None
            seen_separator = False
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if headers is None:
                headers = [c.lower() for c in cells]
                continue
            if not seen_separator:
                # second pipe row is the markdown table separator (---|---)
                if all(set(c) <= set("-: ") for c in cells):
                    seen_separator = True
                    continue
                # else fall through and treat as data
                seen_separator = True
            row = dict(zip(headers, cells))
            if row:
                sections[current].append(row)
    return sections


def violations_for_section(slug: str, rows: list[dict]) -> list[str]:
    issues: list[str] = []
    if len(rows) < MIN_COMPONENTS_PER_SLUG:
        issues.append(
            f"only {len(rows)} components listed (min {MIN_COMPONENTS_PER_SLUG})"
        )
    for row in rows:
        name = (row.get("component") or row.get("name") or "").strip()
        position = (row.get("position (x,y,w,h%)") or row.get("position") or "").strip()
        if not name:
            issues.append("row missing component name")
            continue
        norm = re.sub(r"[^a-z]", "", name.lower())
        if norm in GENERIC_NAMES:
            issues.append(f"generic name not allowed: {name!r}")
        if not position or position in {"-", "n/a", "(root)", ""}:
            # (root) is allowed for AppShell/page-level only when explicitly named
            if name.lower() not in {"appshell", "approot"}:
                issues.append(f"{name}: position field empty/placeholder ({position!r})")
    return issues


def slugs_in_plan(phase_dir: Path) -> set[str]:
    slugs: set[str] = set()
    slug_re = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")
    for plan in sorted(phase_dir.glob("*PLAN*.md")):
        try:
            text = plan.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for raw in re.findall(r"<design-ref>([^<]+)</design-ref>", text):
            for r in re.split(r"[,\s]+", raw.strip()):
                r = r.strip()
                if r and slug_re.match(r):
                    slugs.add(r)
    return slugs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--require", default="true", choices=["true", "false"])
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    vc_path = phase_dir / "VIEW-COMPONENTS.md"

    plan_slugs = slugs_in_plan(phase_dir)

    result: dict = {
        "phase_dir": str(phase_dir),
        "view_components": str(vc_path),
        "verdict": "SKIP",
        "violations": {},
        "missing_slugs": [],
        "plan_slugs": sorted(plan_slugs),
    }

    if not plan_slugs:
        result["reason"] = "no SLUG-form <design-ref> in PLAN — view-decomposition not applicable"
        return _emit(result, args)

    if not vc_path.exists():
        if args.require == "false":
            result["reason"] = "VIEW-COMPONENTS.md not found and require=false"
            return _emit(result, args)
        result["verdict"] = "BLOCK"
        result["reason"] = (
            f"VIEW-COMPONENTS.md missing while {len(plan_slugs)} design slug(s) in PLAN"
        )
        return _emit(result, args)

    text = vc_path.read_text(encoding="utf-8", errors="ignore")
    sections = parse_view_components(text)

    for slug in plan_slugs:
        if slug not in sections:
            result["missing_slugs"].append(slug)
            continue
        issues = violations_for_section(slug, sections[slug])
        if issues:
            result["violations"][slug] = issues

    if result["missing_slugs"] or result["violations"]:
        result["verdict"] = "BLOCK"
        bits = []
        if result["missing_slugs"]:
            bits.append(f"{len(result['missing_slugs'])} slug(s) missing from VIEW-COMPONENTS")
        if result["violations"]:
            total = sum(len(v) for v in result["violations"].values())
            bits.append(f"{total} violation(s) across {len(result['violations'])} slug(s)")
        result["reason"] = "; ".join(bits)
    else:
        result["verdict"] = "PASS"
        result["component_counts"] = {s: len(sections[s]) for s in plan_slugs}

    return _emit(result, args)


def _emit(result: dict, args) -> int:
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if result["verdict"] in ("PASS", "SKIP") else 1


if __name__ == "__main__":
    sys.exit(main())
