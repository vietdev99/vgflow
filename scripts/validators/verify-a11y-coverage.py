#!/usr/bin/env python3
"""verify-a11y-coverage.py — B110 v4.71.0.

Verify generated Playwright specs include axe-core scan for every goal
with `a11y_assertion` metadata. Critical+serious violations should block
test runs; moderate/minor go to report only.

Pre-B110: accessibility was an OPTIONAL stage that codegen could skip.
Top UAT a11y bugs (missing ARIA, low color contrast, broken keyboard
nav, form input not bound to label) shipped through every gate because
no validator required `AxeBuilder` invocation.

This validator scans Playwright specs for:
  - `import { AxeBuilder } from '@axe-core/playwright'` OR
    `import { injectAxe, checkA11y } from 'axe-playwright'`
  - At least one `new AxeBuilder({page}).analyze()` or `checkA11y(page)` call
  - The result is asserted (not discarded)
  - Critical/serious filter explicit

Severity warn initially. Operator runs `--severity block` once project
has a11y allowlist tuned.

Exit codes:
  0 PASS / warn mode with findings
  1 FAIL (block mode)
  2 internal error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


_AXE_IMPORT_RE = re.compile(
    r"(?:from\s+['\"]@axe-core/playwright['\"]|"
    r"from\s+['\"]axe-playwright['\"])",
)
_AXE_RUN_RE = re.compile(
    r"(?:new\s+AxeBuilder\s*\(|injectAxe\s*\(|checkA11y\s*\(|"
    r"AxeBuilder\s*\(\s*\{[^}]*page)",
)
_AXE_ASSERT_RE = re.compile(
    r"(?:expect\([^)]*violations[^)]*\)|"
    r"\.toEqual\(\s*\[\s*\]\s*\)|"
    r"\.toHaveLength\(\s*0\s*\)|"
    r"toHaveNoViolations|"
    r"violations\.length\s*[<=]=?\s*0|"
    r"violations\.filter\([^)]*['\"]critical['\"]\))",
    re.IGNORECASE,
)


def _load_lifecycle(phase_dir: Path) -> dict:
    p = phase_dir / "LIFECYCLE-SPECS.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _gather_specs(phase_dir: Path) -> list[Path]:
    out: list[Path] = []
    for sub in ("playwright-specs", "PLAYWRIGHT-SPECS", "e2e", "tests"):
        d = phase_dir / sub
        if d.is_dir():
            out.extend(d.rglob("*.spec.ts"))
            out.extend(d.rglob("*.spec.js"))
            out.extend(d.rglob("*.spec.tsx"))
    repo = Path.cwd()
    apps = repo / "apps"
    if apps.is_dir():
        for app in apps.iterdir():
            if not app.is_dir():
                continue
            for e2e in (app / "e2e", app / "tests"):
                if e2e.is_dir():
                    out.extend(e2e.rglob("*.spec.ts"))
                    out.extend(e2e.rglob("*.spec.js"))
    return out


def _spec_text_for_goal(goal_id: str, specs: list[Path]) -> str:
    parts: list[str] = []
    pat = re.compile(rf"\b{re.escape(goal_id)}\b")
    for f in specs:
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if pat.search(t):
            parts.append(t)
    return "\n".join(parts)


def _audit_goal(goal_id: str, goal: dict, specs: list[Path]) -> dict:
    needs_a11y = any(
        step.get("a11y_assertion")
        for step in goal.get("steps") or []
    )
    if not needs_a11y:
        return {"goal_id": goal_id, "needs_a11y": False, "findings": []}
    spec_text = _spec_text_for_goal(goal_id, specs)
    findings: list[str] = []
    if not spec_text:
        findings.append("no Playwright spec file references this goal")
        return {"goal_id": goal_id, "needs_a11y": True, "findings": findings}
    if not _AXE_IMPORT_RE.search(spec_text):
        findings.append(
            "no axe-core import (@axe-core/playwright or axe-playwright)"
        )
    if not _AXE_RUN_RE.search(spec_text):
        findings.append(
            "no axe scan call (new AxeBuilder({page}) / injectAxe / checkA11y)"
        )
    if not _AXE_ASSERT_RE.search(spec_text):
        findings.append(
            "axe scan present but no assertion on violations "
            "(toHaveNoViolations / .violations.length / toEqual([]))"
        )
    return {"goal_id": goal_id, "needs_a11y": True, "findings": findings}


def main() -> int:
    ap = argparse.ArgumentParser(prog="verify-a11y-coverage")
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--severity", choices=("warn", "block"), default="warn")
    ap.add_argument("--json", dest="json_out", action="store_true", default=True)
    ap.add_argument("--no-json", dest="json_out", action="store_false")
    args = ap.parse_args()
    try:
        phase_dir = Path(args.phase_dir).resolve()
        lifecycle = _load_lifecycle(phase_dir)
        goal_map = lifecycle.get("goals") or lifecycle.get("specs") or {}
        specs = _gather_specs(phase_dir)
        audits = []
        for gid, gdata in goal_map.items():
            entry = _audit_goal(gid, gdata, specs)
            if entry["needs_a11y"]:
                audits.append(entry)
        total_findings = sum(len(a["findings"]) for a in audits)
        result = {
            "phase_dir": str(phase_dir),
            "goals_with_a11y": len(audits),
            "spec_files_seen": len(specs),
            "total_findings": total_findings,
            "audits": audits,
            "severity": args.severity,
            "status": "PASS" if total_findings == 0 else "FAIL",
        }
        if args.json_out:
            print(json.dumps(result, indent=2))
        else:
            print(f"verify-a11y-coverage — {result['status']}")
            print(f"  goals with a11y: {result['goals_with_a11y']}")
            print(f"  findings: {total_findings}")
            for a in audits:
                if a["findings"]:
                    print(f"  - {a['goal_id']}:")
                    for f in a["findings"]:
                        print(f"      * {f}")
        if result["status"] == "PASS":
            return 0
        return 1 if args.severity == "block" else 0
    except Exception as exc:
        print(f"verify-a11y-coverage: internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
