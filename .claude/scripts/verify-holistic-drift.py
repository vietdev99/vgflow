#!/usr/bin/env python3
"""
verify-holistic-drift.py — Phase 15 D-12e holistic drift gate (review post-fix).

Wraps existing tooling — does NOT reimplement diff logic:
  - visual-diff.py compare    → pixelmatch screenshot drift (% per view)
  - verify-ui-structure.py    → AST drift (MISSING/UNEXPECTED/LAYOUT_SHIFT)
                                full-tree mode (no --scope)

Aggregates both into a single PASS/BLOCK decision per phase profile threshold
resolved via lib/threshold-resolver.py (D-08).

Catches container drift + cross-subtree integration drift that wave-scoped
verify-ui-structure.py (T3.6 with --scope) misses.

EXIT:
  0 — both visual + AST drift within profile threshold (PASS)
  2 — at least one exceeds threshold (BLOCK)
  1 — invocation/precondition error

USAGE:
  verify-holistic-drift.py --phase 7.14.3 \
      --expected-uimap .vg/phases/7.14.3/UI-MAP.md \
      --actual-uimap   .vg/phases/7.14.3/.holistic-asbuilt.json \
      --current-screenshots apps/web/e2e/screenshots/7.14.3/ \
      --baseline-screenshots apps/web/e2e/screenshots/baseline/7.14.3/

Optional flags forward-compat:
  --skip-visual    Skip visual diff (AST only — useful when no baseline yet)
  --skip-ast       Skip AST diff (visual only)
  --json           Aggregate report as JSON

Phase 15 design: this script orchestrates other validators to enforce D-12e
WITHOUT duplicating their logic. Threshold resolution is centralized in
lib/threshold-resolver.py. Future tweaks to drift detection happen in the
wrapped tools, propagating here automatically.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def _find_helper(name: str, search_paths: list[Path]) -> Path | None:
    for p in search_paths:
        if p.exists() and p.is_file():
            return p
    return None


def _resolve_helpers() -> dict:
    """Return paths to wrapped scripts. None if missing (caller decides skip vs error)."""
    here = Path(__file__).parent
    return {
        "visual_diff": _find_helper("visual-diff.py", [
            here / "visual-diff.py",
            REPO_ROOT / "scripts" / "visual-diff.py",
            REPO_ROOT / ".claude" / "scripts" / "visual-diff.py",
        ]),
        "verify_ui_structure": _find_helper("verify-ui-structure.py", [
            here / "verify-ui-structure.py",
            REPO_ROOT / "scripts" / "verify-ui-structure.py",
            REPO_ROOT / ".claude" / "scripts" / "verify-ui-structure.py",
        ]),
        "threshold_resolver": _find_helper("threshold-resolver.py", [
            here / "lib" / "threshold-resolver.py",
            REPO_ROOT / "scripts" / "lib" / "threshold-resolver.py",
            REPO_ROOT / ".claude" / "scripts" / "lib" / "threshold-resolver.py",
        ]),
    }


def _resolve_threshold(phase: str, helper: Path | None) -> tuple[float, str]:
    """Returns (fidelity_threshold, source_label)."""
    if helper is None:
        return 0.85, "hard_fallback (resolver not found)"
    try:
        r = subprocess.run(
            [sys.executable, str(helper), "--phase", phase, "--verbose"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            value = float(r.stdout.strip())
            return value, r.stderr.strip().splitlines()[-1] if r.stderr else "resolver"
    except (subprocess.TimeoutExpired, ValueError):
        pass
    return 0.85, "hard_fallback (resolver error)"


def _run_visual_diff(helper: Path, current_dir: Path, baseline_dir: Path,
                     fidelity_threshold: float, output_dir: Path) -> dict:
    """Run visual-diff.py compare. Returns {ok: bool, summary: str, exit_code, max_diff_pct}."""
    # visual-diff.py uses --threshold as % (2.0 = 2%). Convert fidelity (0-1)
    # to drift % (1 - fidelity = max acceptable fraction).
    drift_pct = round((1.0 - fidelity_threshold) * 100, 2)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "visual-diff.json"

    cmd = [
        sys.executable, str(helper), "compare",
        "--current", str(current_dir),
        "--baseline", str(baseline_dir),
        "--threshold", str(drift_pct),
        "--output", str(report_path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"ok": False, "summary": "visual-diff.py timed out (5min)",
                "exit_code": -1, "max_diff_pct": None, "report_path": None}

    summary = (r.stdout + r.stderr).strip().splitlines()
    summary_str = summary[-1] if summary else ""
    max_diff_pct = None
    if report_path.exists():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            views = data.get("views") or []
            if views:
                max_diff_pct = max(v.get("diff_pct", 0.0) for v in views)
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "ok": r.returncode == 0,
        "summary": summary_str or f"visual-diff exit {r.returncode}",
        "exit_code": r.returncode,
        "max_diff_pct": max_diff_pct,
        "report_path": str(report_path),
        "drift_threshold_pct": drift_pct,
    }


def _run_ast_diff(helper: Path, expected: Path, actual: Path,
                  phase: str) -> dict:
    """Run verify-ui-structure.py full-tree (no --scope). Returns {ok, summary, exit_code}."""
    cmd = [
        sys.executable, str(helper),
        "--expected", str(expected),
        "--actual", str(actual),
        "--phase", phase,           # threshold-resolver via D-08
        "--json",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"ok": False, "summary": "verify-ui-structure.py timed out (60s)",
                "exit_code": -1, "diff_summary": None}

    diff_summary = None
    try:
        data = json.loads(r.stdout)
        diff_summary = data.get("summary")
    except (json.JSONDecodeError, AttributeError):
        pass

    return {
        "ok": r.returncode == 0,
        "summary": (r.stderr.strip().splitlines()[-1] if r.stderr.strip() else
                    "AST drift within threshold" if r.returncode == 0 else
                    f"verify-ui-structure exit {r.returncode}"),
        "exit_code": r.returncode,
        "diff_summary": diff_summary,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--phase", required=True)
    ap.add_argument("--expected-uimap", help="Planner UI-MAP.md path")
    ap.add_argument("--actual-uimap", help="As-built UI-MAP JSON path (full tree)")
    ap.add_argument("--current-screenshots", help="Current run screenshots dir")
    ap.add_argument("--baseline-screenshots", help="Baseline screenshots dir")
    ap.add_argument("--skip-visual", action="store_true",
                    help="Skip visual diff (AST only)")
    ap.add_argument("--skip-ast", action="store_true",
                    help="Skip AST diff (visual only)")
    ap.add_argument("--output-dir", help="Where to write aggregated report (default: phase dir / .holistic/)")
    ap.add_argument("--json", action="store_true", help="Print aggregated JSON")
    args = ap.parse_args()

    helpers = _resolve_helpers()

    if args.skip_visual and args.skip_ast:
        print("\033[38;5;208mBoth --skip-visual and --skip-ast specified — nothing to verify\033[0m", file=sys.stderr)
        return 1

    fidelity, source = _resolve_threshold(args.phase, helpers["threshold_resolver"])
    if not args.json:
        print(f"ℹ Holistic drift gate — phase={args.phase} fidelity={fidelity} ({source})",
              file=sys.stderr)

    output_dir = Path(args.output_dir) if args.output_dir else (
        REPO_ROOT / ".vg" / "phases" / args.phase / ".holistic"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    visual_result = None
    ast_result = None

    if not args.skip_visual:
        if helpers["visual_diff"] is None:
            print("\033[33mvisual-diff.py not found — skipping visual layer\033[0m", file=sys.stderr)
        elif not args.current_screenshots or not args.baseline_screenshots:
            print("\033[33m--current-screenshots/--baseline-screenshots not provided — skipping visual layer\033[0m",
                  file=sys.stderr)
        else:
            visual_result = _run_visual_diff(
                helpers["visual_diff"],
                Path(args.current_screenshots),
                Path(args.baseline_screenshots),
                fidelity, output_dir,
            )

    if not args.skip_ast:
        if helpers["verify_ui_structure"] is None:
            print("\033[33mverify-ui-structure.py not found — skipping AST layer\033[0m", file=sys.stderr)
        elif not args.expected_uimap or not args.actual_uimap:
            print("\033[33m--expected-uimap/--actual-uimap not provided — skipping AST layer\033[0m",
                  file=sys.stderr)
        else:
            ast_result = _run_ast_diff(
                helpers["verify_ui_structure"],
                Path(args.expected_uimap), Path(args.actual_uimap),
                args.phase,
            )

    # Aggregate
    aggregated = {
        "phase": args.phase,
        "fidelity_threshold": fidelity,
        "threshold_source": source,
        "visual": visual_result,
        "ast": ast_result,
    }
    visual_ok = visual_result["ok"] if visual_result else True   # skip = pass-through
    ast_ok = ast_result["ok"] if ast_result else True
    aggregated["overall"] = "PASS" if (visual_ok and ast_ok) else "BLOCK"

    report_path = output_dir / "holistic-drift-report.json"
    report_path.write_text(json.dumps(aggregated, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(aggregated, indent=2))
    else:
        print(f"\n# Holistic Drift Report — phase {args.phase}\n")
        print(f"**Threshold:** fidelity={fidelity} ({source})")
        if visual_result:
            print(f"**Visual:** {visual_result['summary']} "
                  f"(max {visual_result['max_diff_pct']}% vs threshold {visual_result['drift_threshold_pct']}%)")
        else:
            print("**Visual:** skipped")
        if ast_result:
            print(f"**AST:** {ast_result['summary']}")
            if ast_result.get("diff_summary"):
                s = ast_result["diff_summary"]
                print(f"  expected_components={s.get('expected_components')} "
                      f"actual_components={s.get('actual_components')} "
                      f"missing={s.get('missing')} unexpected={s.get('unexpected')} "
                      f"layout_shift={s.get('layout_shift')}")
        else:
            print("**AST:** skipped")
        print(f"\n**Verdict:** {aggregated['overall']}")
        print(f"\n→ Report: {report_path}")

    if aggregated["overall"] == "BLOCK":
        if not args.json:
            print("\n⛔ BLOCK: holistic drift exceeded profile threshold. "
                  "Fix container/cross-subtree integration drift OR adjust "
                  "design_fidelity.profile in phase CONTEXT.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
