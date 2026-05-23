#!/usr/bin/env python3
"""verify-visual-fidelity-coverage.py — B109 v4.71.2.

Verify generated Playwright specs include `toHaveScreenshot()` baseline
assertion for every goal with `visual_assertion` metadata (design ref
bound). Catches layout drift, padding crush, color rendering, font load
failures, image broken — design-vs-impl bugs UAT catches today.

Pre-B109: design refs declared in TEST-GOALS but codegen ignored them.
Specs never compared rendered UI to baseline.

Validator scans Playwright specs for:
  - `await expect(page).toHaveScreenshot(` OR
  - `await expect(<locator>).toHaveScreenshot(` AND
  - `maxDiffPixelRatio` or `maxDiffPixels` option (drift threshold) AND
  - Optional: `animations: 'disabled'` for stable diffs

Severity warn initially. Operator commits baseline snapshots
(`*-snapshots/*.png`) + flips to block once baselines stable.

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


_TO_HAVE_SCREENSHOT_RE = re.compile(r"toHaveScreenshot\s*\(", re.IGNORECASE)
_DIFF_THRESHOLD_RE = re.compile(
    r"(maxDiffPixelRatio|maxDiffPixels|threshold)\s*:",
)
_ANIMATION_DISABLE_RE = re.compile(
    r"animations\s*:\s*['\"]disabled['\"]",
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
    visual_steps = [
        s for s in (goal.get("steps") or [])
        if isinstance(s, dict) and s.get("visual_assertion")
    ]
    if not visual_steps:
        return {"goal_id": goal_id, "needs_visual": False, "findings": []}
    spec_text = _spec_text_for_goal(goal_id, specs)
    findings: list[str] = []
    if not spec_text:
        findings.append("no Playwright spec file references this goal")
        return {"goal_id": goal_id, "needs_visual": True, "findings": findings}
    has_screenshot = bool(_TO_HAVE_SCREENSHOT_RE.search(spec_text))
    if not has_screenshot:
        findings.append(
            f"goal has {len(visual_steps)} stage(s) with design_ref but "
            f"spec has no `toHaveScreenshot()` baseline assertion"
        )
        # No further checks if the screenshot call isn't there at all.
        return {"goal_id": goal_id, "needs_visual": True, "findings": findings}
    if not _DIFF_THRESHOLD_RE.search(spec_text):
        findings.append(
            "toHaveScreenshot present but no maxDiffPixelRatio / "
            "maxDiffPixels / threshold option — diff window not bounded"
        )
    if not _ANIMATION_DISABLE_RE.search(spec_text):
        findings.append(
            "toHaveScreenshot without `animations: 'disabled'` — animated "
            "elements cause flaky diffs (advisory; severity stays warn)"
        )
    return {"goal_id": goal_id, "needs_visual": True, "findings": findings}


def main() -> int:
    ap = argparse.ArgumentParser(prog="verify-visual-fidelity-coverage")
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
            if entry["needs_visual"]:
                audits.append(entry)
        total_findings = sum(len(a["findings"]) for a in audits)
        result = {
            "phase_dir": str(phase_dir),
            "goals_with_design_ref": len(audits),
            "spec_files_seen": len(specs),
            "total_findings": total_findings,
            "audits": audits,
            "severity": args.severity,
            "status": "PASS" if total_findings == 0 else "FAIL",
        }
        if args.json_out:
            print(json.dumps(result, indent=2))
        else:
            print(f"verify-visual-fidelity-coverage — {result['status']}")
            for a in audits:
                if a["findings"]:
                    print(f"  - {a['goal_id']}:")
                    for f in a["findings"]:
                        print(f"      * {f}")
        if result["status"] == "PASS":
            return 0
        return 1 if args.severity == "block" else 0
    except Exception as exc:
        print(f"verify-visual-fidelity-coverage: internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
