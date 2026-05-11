#!/usr/bin/env python3
"""
verify-ui-runtime-contract.py — v3.3.0 (#173 Stage 3)

Consumes UI-RUNTIME-CONTRACT.json (emitted by /vg:blueprint step
2b6d_ui_runtime_contract in v3.2.0). Enforces two runtime invariants
during /vg:build STEP 6.5 pre-test-gate:

  1. Token gate — every `required_tailwind_tokens[].class_name` must
     appear in the compiled CSS bundle. Default search glob:
       apps/*/dist/**/*.css
       apps/*/build/**/*.css
       packages/*/dist/**/*.css
       dist/**/*.css
       build/**/*.css
     Override via config `paths.dist_css_glob` (comma-separated).
     Missing → severity=BLOCK by default.

  2. Spec-count gate — count Playwright / vitest / jest spec files
     vs `min_spec_count.count`. Default search glob:
       apps/*/tests/**/*.{spec,test}.{ts,tsx,js,jsx}
       apps/*/e2e/**/*.{spec,test}.{ts,tsx,js,jsx}
       tests/**/*.{spec,test}.{ts,tsx,js,jsx}
       e2e/**/*.{spec,test}.{ts,tsx,js,jsx}
     Override via config `paths.spec_glob`.
     count < min → severity=BLOCK by default; diagnostic suggests
     /vg:test-spec --regen before review can pass.

Skip conditions (exit 0 with PASS, no enforcement):
  - UI-RUNTIME-CONTRACT.json missing (legacy phase / pre-v3.2.0)
  - contract.skip_reason populated (backend-only / no FE tasks)
  - --severity warn (config-driven downgrade)

Usage:
  verify-ui-runtime-contract.py --phase-dir <path>
  verify-ui-runtime-contract.py --phase <number>
  verify-ui-runtime-contract.py --phase <number> --severity warn

Exit codes:
  0 — PASS or WARN (validator non-blocking)
  1 — BLOCK
  2 — config error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

DEFAULT_CSS_GLOBS = [
    "apps/*/dist/**/*.css",
    "apps/*/build/**/*.css",
    "packages/*/dist/**/*.css",
    "dist/**/*.css",
    "build/**/*.css",
]
DEFAULT_SPEC_GLOBS = [
    "apps/*/tests/**/*.spec.ts",
    "apps/*/tests/**/*.spec.tsx",
    "apps/*/tests/**/*.test.ts",
    "apps/*/tests/**/*.test.tsx",
    "apps/*/e2e/**/*.spec.ts",
    "apps/*/e2e/**/*.spec.tsx",
    "tests/**/*.spec.ts",
    "tests/**/*.spec.tsx",
    "tests/**/*.test.ts",
    "tests/**/*.test.tsx",
    "e2e/**/*.spec.ts",
    "e2e/**/*.spec.tsx",
]


def load_contract(phase_dir: Path) -> dict | None:
    p = phase_dir / "UI-RUNTIME-CONTRACT.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def collect_paths(root: Path, globs: list[str]) -> list[Path]:
    """Collect files from a glob list relative to root."""
    out: list[Path] = []
    seen: set[Path] = set()
    for g in globs:
        for p in root.glob(g):
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def grep_token_in_files(token: str, files: list[Path]) -> Path | None:
    """Return first file containing the literal token, or None."""
    needle = token.lower()
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace").lower()
        except Exception:
            continue
        if needle in text:
            return f
    return None


def check_tokens(contract: dict, repo_root: Path, css_globs: list[str], output: Output) -> None:
    tokens = contract.get("required_tailwind_tokens") or []
    if not tokens:
        output.evidence.append(Evidence(
            type="ui_runtime_contract_tokens_empty",
            message="Contract declares no required_tailwind_tokens — token gate skipped.",
        ))
        return

    css_files = collect_paths(repo_root, css_globs)
    if not css_files:
        output.add(Evidence(
            type="ui_runtime_contract_no_css_bundle",
            message=(
                f"No compiled CSS found under any of: {', '.join(css_globs)}. "
                "Run the FE build (e.g. `npm run build`) before /vg:build pre-test-gate "
                "or override the glob via `paths.dist_css_glob` config."
            ),
            severity="HIGH",
            fix_hint="Build CSS bundle first (npm run build / vite build) so token gate has something to scan.",
        ))
        return

    missing: list[dict] = []
    for t in tokens:
        cls = t.get("class_name", "")
        if not cls:
            continue
        hit = grep_token_in_files(cls, css_files)
        if hit is None:
            missing.append(t)

    if missing:
        output.add(Evidence(
            type="ui_runtime_contract_token_missing",
            message=(
                f"{len(missing)} required Tailwind/brand token(s) absent from compiled CSS: "
                f"{', '.join(t['class_name'] for t in missing[:5])}"
                f"{', …' if len(missing) > 5 else ''}"
            ),
            file=f"<css glob>: {', '.join(css_globs)}",
            expected=f"each class appears in at least one bundle file",
            actual=f"{len(missing)}/{len(tokens)} tokens missing",
            severity="HIGH",
            fix_hint=(
                "Add the token to Tailwind theme.extend in tailwind.config.{ts,js} OR "
                "ensure UI-SPEC verbatim markup uses the production class name. "
                "Re-run build → re-run /vg:build STEP 6.5."
            ),
        ))
    else:
        output.evidence.append(Evidence(
            type="ui_runtime_contract_tokens_ok",
            message=f"All {len(tokens)} required tokens found in compiled CSS bundle.",
        ))


def check_spec_count(contract: dict, repo_root: Path, spec_globs: list[str], output: Output) -> None:
    msc = contract.get("min_spec_count") or {}
    min_count = int(msc.get("count", 0))
    if min_count <= 0:
        output.evidence.append(Evidence(
            type="ui_runtime_contract_min_spec_skipped",
            message="Contract declares min_spec_count=0 — spec-count gate skipped.",
        ))
        return

    spec_files = collect_paths(repo_root, spec_globs)
    actual = len(spec_files)
    if actual < min_count:
        deficit = min_count - actual
        output.add(Evidence(
            type="ui_runtime_contract_spec_count_low",
            message=(
                f"Phase shipped {actual} Playwright/lifecycle spec(s) but contract requires "
                f"≥{min_count} (one per goal_type=mutation goal). Deficit: {deficit}."
            ),
            file=f"<spec glob>: {', '.join(spec_globs)}",
            expected=f"≥{min_count} spec files",
            actual=f"{actual} spec files",
            severity="HIGH",
            fix_hint=(
                f"Mark missing goals as Status=TEST_SPEC_MISSING in GOAL-COVERAGE-MATRIX "
                f"and run /vg:test-spec --regen before rerunning /vg:review. Override with "
                f"--skip-ui-runtime-contract + override-reason if intentional."
            ),
        ))
    else:
        output.evidence.append(Evidence(
            type="ui_runtime_contract_spec_count_ok",
            message=f"{actual} spec(s) present, ≥{min_count} required.",
        ))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--phase-dir")
    g.add_argument("--phase")
    ap.add_argument("--repo-root", default=str(REPO_ROOT))
    ap.add_argument("--severity", choices=["warn", "block"], default="block")
    ap.add_argument("--css-glob", action="append", default=[],
                    help="Override CSS bundle glob (repeatable). Default = collected built-in list.")
    ap.add_argument("--spec-glob", action="append", default=[],
                    help="Override spec glob (repeatable). Default = collected built-in list.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    output = Output(validator="ui-runtime-contract")

    with timer(output):
        if args.phase_dir:
            phase_dir = Path(args.phase_dir).resolve()
        else:
            phase_dir = find_phase_dir(args.phase)
            if not phase_dir:
                print(f"\033[38;5;208mPhase dir not found for phase={args.phase}\033[0m", file=sys.stderr)
                return 2

        if not phase_dir.is_dir():
            print(f"\033[38;5;208mPhase dir not found: {phase_dir}\033[0m", file=sys.stderr)
            return 2

        contract = load_contract(phase_dir)
        if contract is None:
            output.evidence.append(Evidence(
                type="ui_runtime_contract_missing",
                message=(
                    f"UI-RUNTIME-CONTRACT.json missing in {phase_dir}. Legacy phase "
                    "(pre-v3.2.0) — gate skipped. Re-run /vg:blueprint step "
                    "2b6d_ui_runtime_contract to emit."
                ),
            ))
            if args.json:
                print(output.to_json())
            else:
                print(f"⚠ {output.evidence[-1].message}")
            return 0

        skip_reason = contract.get("skip_reason")
        if skip_reason:
            output.evidence.append(Evidence(
                type="ui_runtime_contract_skipped",
                message=f"Contract skipped: {skip_reason}",
            ))
            if args.json:
                print(output.to_json())
            else:
                print(f"ℹ Contract skipped: {skip_reason}")
            return 0

        css_globs = args.css_glob or DEFAULT_CSS_GLOBS
        spec_globs = args.spec_glob or DEFAULT_SPEC_GLOBS

        check_tokens(contract, repo_root, css_globs, output)
        check_spec_count(contract, repo_root, spec_globs, output)

    # Severity downgrade — operator config can flip BLOCK → WARN
    if args.severity == "warn" and output.verdict == "BLOCK":
        output.verdict = "WARN"

    if args.json:
        print(output.to_json())
    else:
        if output.verdict == "BLOCK":
            print(f"\033[38;5;208mUI-RUNTIME-CONTRACT gate: BLOCK\033[0m")
            for e in output.evidence:
                if e.type.endswith(("_ok", "_skipped", "_empty")):
                    continue
                print(f"  [{e.type}] {e.message}")
                if e.fix_hint:
                    print(f"    hint: {e.fix_hint}")
        elif output.verdict == "WARN":
            print(f"\033[33mUI-RUNTIME-CONTRACT gate: WARN\033[0m")
            for e in output.evidence:
                print(f"  [{e.type}] {e.message}")
        else:
            print("✓ UI-RUNTIME-CONTRACT gate: PASS")
            for e in output.evidence:
                print(f"  [{e.type}] {e.message}")

    if output.verdict == "BLOCK":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
