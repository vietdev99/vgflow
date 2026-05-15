#!/usr/bin/env python3
"""Batch 60: end-to-end seed-chain status report.

Runs every validator in the B36→B59 chain for a phase and prints a
PASS/FAIL table per layer. Useful diagnostic when sandbox deploy
surfaces issues that don't match any single batch's failure mode.

Layers checked:
  1. LIFECYCLE-SPECS.json present + parseable (B36+37)
  2. EDGE-CASES/ directory + per-goal .md (B48)
  3. EDGE-CASES/VARIANTS.json schema + coverage (B56)
  4. SEED-RECIPE.md present + variant coverage (B51)
  5. tests/_helpers/seed-recipes.{ts,js} stub (B55)
  6. scan-*.json present + signal coverage (B58 — informational only)
  7. Spec body seed binding (B52, when spec dir present)

Exit codes:
  0 — all layers PASS
  1 — at least one layer FAIL (only when --strict)
  By default warn-mode: exit 0 with table to stdout.

Usage:
  seed-chain-status.py --phase 7
  seed-chain-status.py --phase 7 --strict   # exit 1 on FAIL
  seed-chain-status.py --phase 7 --json     # machine-readable
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
VALIDATORS = SCRIPTS / "validators"


def _find_phase_dir(phase: str, override: str | None = None) -> Path:
    if override:
        return Path(override)
    for root in (Path(".vg/phases"), Path("dev-phases"), Path("phases")):
        if not root.is_dir():
            continue
        for p in root.iterdir():
            if p.is_dir() and (p.name == phase or p.name.startswith(f"{phase}-")):
                return p
    raise SystemExit(f"phase dir not found for {phase}")


def _run_validator(script: Path, phase: str, phase_dir: Path,
                   extra: list[str] | None = None) -> dict:
    """Run a validator. Returns {ok, stdout, stderr, rc}."""
    if not script.is_file():
        return {"ok": None, "rc": -1, "stdout": "",
                "stderr": f"validator missing: {script}"}
    cmd = [sys.executable, str(script), "--phase", phase, "--phase-dir", str(phase_dir)]
    if extra:
        cmd += extra
    # Force UTF-8 decoding to avoid cp1258/cp1252 charmap errors on
    # Windows when validator stdout has unicode (✓, ⛔, etc).
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "").strip(),
            "stderr": (r.stderr or "").strip()}


def _check_layer_1_lifecycle(phase_dir: Path) -> dict:
    """LIFECYCLE-SPECS.json exists + parseable."""
    p = phase_dir / "LIFECYCLE-SPECS.json"
    if not p.is_file():
        return {"ok": False, "detail": "LIFECYCLE-SPECS.json missing"}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"ok": False, "detail": f"malformed JSON: {e}"}
    goal_count = len(doc.get("goals") or {})
    return {"ok": True, "detail": f"{goal_count} goals"}


def _check_layer_2_edge_cases(phase_dir: Path) -> dict:
    """EDGE-CASES/ directory + at least one G-NN.md."""
    d = phase_dir / "EDGE-CASES"
    if not d.is_dir():
        return {"ok": False, "detail": "EDGE-CASES/ directory missing"}
    files = list(d.glob("G-*.md"))
    if not files:
        return {"ok": False, "detail": "no G-*.md files in EDGE-CASES/"}
    return {"ok": True, "detail": f"{len(files)} per-goal .md files"}


def _check_layer_3_variants(phase: str, phase_dir: Path) -> dict:
    """VARIANTS.json schema + coverage vs LIFECYCLE."""
    val = VALIDATORS / "verify-variants-json.py"
    r = _run_validator(val, phase, phase_dir, ["--strict"])
    if r["ok"] is None:
        return {"ok": None, "detail": r["stderr"]}
    if r["ok"]:
        return {"ok": True, "detail": r["stdout"].splitlines()[-1] if r["stdout"] else ""}
    return {"ok": False, "detail": (r["stdout"] + " " + r["stderr"])[:200].strip()}


def _check_layer_4_recipes(phase: str, phase_dir: Path) -> dict:
    """SEED-RECIPE.md + variant coverage."""
    val = VALIDATORS / "verify-seed-recipe-coverage.py"
    r = _run_validator(val, phase, phase_dir, ["--strict", "--allow-placeholders"])
    if r["ok"] is None:
        return {"ok": None, "detail": r["stderr"]}
    if r["ok"]:
        return {"ok": True, "detail": r["stdout"].splitlines()[-1] if r["stdout"] else ""}
    return {"ok": False, "detail": (r["stdout"] + " " + r["stderr"])[:200].strip()}


def _check_layer_5_helper(phase: str, phase_dir: Path) -> dict:
    """tests/_helpers/seed-recipes.ts coverage."""
    val = VALIDATORS / "verify-seed-helper-stub.py"
    r = _run_validator(val, phase, phase_dir, ["--strict"])
    if r["ok"] is None:
        return {"ok": None, "detail": r["stderr"]}
    if r["ok"]:
        return {"ok": True, "detail": r["stdout"].splitlines()[-1] if r["stdout"] else ""}
    return {"ok": False, "detail": (r["stdout"] + " " + r["stderr"])[:200].strip()}


def _check_layer_6_scan_goal(phase: str, phase_dir: Path) -> dict:
    """Informational: scan→goal coverage gaps."""
    val = VALIDATORS / "verify-scan-goal-coverage.py"
    r = _run_validator(val, phase, phase_dir, [])  # default warn mode
    if r["ok"] is None:
        return {"ok": None, "detail": r["stderr"]}
    out = r["stdout"]
    # Count gaps (always exit 0 in default mode)
    return {"ok": True, "detail": out.splitlines()[-1] if out else "no scans"}


def _check_layer_7_spec_binding(phase: str, phase_dir: Path) -> dict:
    """Optional: spec binding when CODEGEN-MANIFEST exists."""
    if not (phase_dir / "CODEGEN-MANIFEST.json").is_file():
        return {"ok": None, "detail": "CODEGEN-MANIFEST.json not present (specs not generated)"}
    val = VALIDATORS / "verify-spec-seed-binding.py"
    r = _run_validator(val, phase, phase_dir, ["--strict"])
    if r["ok"] is None:
        return {"ok": None, "detail": r["stderr"]}
    if r["ok"]:
        return {"ok": True, "detail": r["stdout"].splitlines()[-1] if r["stdout"] else ""}
    return {"ok": False, "detail": (r["stdout"] + " " + r["stderr"])[:200].strip()}


def _render_table(results: list[dict]) -> str:
    """Render layer results as a Markdown table."""
    lines = [
        "| Layer | Status | Detail |",
        "|---|---|---|",
    ]
    for r in results:
        if r["ok"] is None:
            status = "SKIP"
        else:
            status = "PASS" if r["ok"] else "FAIL"
        detail = (r.get("detail") or "").replace("|", "\\|")
        lines.append(f"| {r['name']} | {status} | {detail} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any FAIL layer (default: warn-mode)")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON instead of table")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    phase = args.phase

    results = [
        {"name": "1. LIFECYCLE-SPECS (B36)",     **_check_layer_1_lifecycle(phase_dir)},
        {"name": "2. EDGE-CASES dir (B48)",      **_check_layer_2_edge_cases(phase_dir)},
        {"name": "3. VARIANTS.json (B56)",       **_check_layer_3_variants(phase, phase_dir)},
        {"name": "4. SEED-RECIPE.md (B51)",      **_check_layer_4_recipes(phase, phase_dir)},
        {"name": "5. helper stub (B55)",         **_check_layer_5_helper(phase, phase_dir)},
        {"name": "6. scan→goal coverage (B58)",  **_check_layer_6_scan_goal(phase, phase_dir)},
        {"name": "7. spec seed binding (B52)",   **_check_layer_7_spec_binding(phase, phase_dir)},
    ]

    if args.json:
        print(json.dumps({"phase": phase, "phase_dir": str(phase_dir),
                          "results": results}, indent=2))
    else:
        print(f"# Seed-chain status — phase {phase}")
        print(f"_phase_dir: {phase_dir}_")
        print("")
        print(_render_table(results))
        print("")
        pass_count = sum(1 for r in results if r["ok"] is True)
        fail_count = sum(1 for r in results if r["ok"] is False)
        skip_count = sum(1 for r in results if r["ok"] is None)
        print(f"Summary: {pass_count} PASS, {fail_count} FAIL, {skip_count} SKIP")

    if args.strict and any(r["ok"] is False for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
