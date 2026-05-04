#!/usr/bin/env python3
"""verify_manual_run_artifacts.py — Phase 2b-2.5 manual-run sanity gate (Task 21).

Reads ``<phase_dir>/recursive-prompts/<tool>/EXPECTED-OUTPUTS.md`` (produced by
``scripts/generate_recursive_prompts.py``) and confirms every expected
``runs/<tool>/recursive-*.json`` artifact:

  1. exists,
  2. parses as JSON, and
  3. carries the v3 run-artifact skeleton (``lens``, ``steps[]`` with
     ``evidence_ref`` on each step, non-empty ``network_log``, ``verdict``).

v2.40.2 change: artifacts now live under ``recursive-prompts/<tool>/`` per
tool, and outputs under ``runs/<tool>/``. Pass ``--tool gemini``,
``--tool codex``, or ``--tool both`` (default) to scope verification.

Backward compat: when ``recursive-prompts/EXPECTED-OUTPUTS.md`` exists at the
legacy single-dir path AND no per-tool subdir is present, fall back to
verifying that file (preserves pre-v2.40.2 manual runs in flight).

Severity is BLOCK on any miss — exit code 1 with a structured stderr report.
On success the script prints a summary to stdout and exits 0.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# v3 run-artifact required fields. Mirrors the inline skeleton documented in
# commands/vg/_shared/transition-kits/_TEMPLATE.md.
REQUIRED_TOP_KEYS: set[str] = {"lens", "steps", "network_log", "verdict"}

SUPPORTED_TOOLS: tuple[str, ...] = ("gemini", "codex")


# ---------------------------------------------------------------------------
# EXPECTED-OUTPUTS.md parsing
# ---------------------------------------------------------------------------
# Match a backtick-quoted relative path on each list line. Format produced by
# generate_recursive_prompts.py is:
#     - 1. lens=`...` element_class=`...` selector=`...` → `runs/.../foo.json`
_PATH_RE = re.compile(r"`([^`]+\.json)`\s*$", re.M)


def parse_expected_outputs(md_path: Path) -> list[str]:
    """Extract the trailing JSON path from each line of EXPECTED-OUTPUTS.md."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    paths: list[str] = []
    for line in text.splitlines():
        m = _PATH_RE.search(line)
        if m:
            paths.append(m.group(1).strip())
    return paths


# ---------------------------------------------------------------------------
# Artifact validation
# ---------------------------------------------------------------------------
def validate_artifact(path: Path) -> tuple[bool, str]:
    """Return (ok, reason). ``reason`` is empty when ``ok`` is True."""
    if not path.is_file():
        return False, "missing file"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"unreadable: {exc}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON: {exc.msg}"
    if not isinstance(data, dict):
        return False, "schema: top-level value is not an object"

    missing = REQUIRED_TOP_KEYS - data.keys()
    if missing:
        return False, f"schema: missing required keys {sorted(missing)}"

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        return False, "schema: steps[] missing or empty"
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return False, f"schema: steps[{i}] is not an object"
        if "evidence_ref" not in step:
            return False, f"schema: steps[{i}].evidence_ref missing"

    network_log = data.get("network_log")
    if not isinstance(network_log, list) or not network_log:
        return False, "schema: network_log empty"

    verdict = data.get("verdict")
    if verdict not in {"pass", "fail", "inconclusive"}:
        return False, f"schema: verdict must be pass|fail|inconclusive, got {verdict!r}"

    return True, ""


# ---------------------------------------------------------------------------
# Per-tool / legacy expected-outputs locator
# ---------------------------------------------------------------------------
def _expected_md_for_tool(phase_dir: Path, tool: str) -> Path:
    return phase_dir / "recursive-prompts" / tool / "EXPECTED-OUTPUTS.md"


def _legacy_expected_md(phase_dir: Path) -> Path:
    return phase_dir / "recursive-prompts" / "EXPECTED-OUTPUTS.md"


def _verify_one(phase_dir: Path, expected_md: Path) -> dict[str, Any]:
    """Return per-source verification report (no IO on stderr — caller renders)."""
    report: dict[str, Any] = {
        "expected_md": str(expected_md),
        "expected": [],
        "missing": [],
        "invalid": [],
        "ok": [],
    }
    if not expected_md.is_file():
        report["blocked"] = True
        report["reason"] = f"EXPECTED-OUTPUTS.md not found at {expected_md}"
        return report

    expected_paths = parse_expected_outputs(expected_md)
    report["expected"] = expected_paths
    for rel in expected_paths:
        full = phase_dir / rel
        if not full.is_file():
            report["missing"].append(rel)
            continue
        ok, reason = validate_artifact(full)
        if ok:
            report["ok"].append(rel)
        else:
            report["invalid"].append({"path": rel, "reason": reason})
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="verify_manual_run_artifacts.py",
        description="BLOCK gate: every EXPECTED-OUTPUTS.md path must exist + be v3-valid.",
    )
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument(
        "--tool",
        choices=[*SUPPORTED_TOOLS, "both"],
        default="both",
        help="Verify a single tool's per-tool subdir (gemini|codex), or "
             "'both' (default) to require both completed.",
    )
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON report on stdout.")
    return ap


def _emit_human(report: dict[str, Any]) -> None:
    """Pretty-print the per-source report."""
    if report.get("blocked"):
        print(f"BLOCK: {report.get('reason', 'unknown')}")
        return
    expected_paths = report["expected"]
    if report["missing"] or report["invalid"]:
        print(
            f"BLOCK [{report.get('label','')}]: "
            f"{len(report['missing'])} missing, "
            f"{len(report['invalid'])} invalid, "
            f"{len(report['ok'])} OK out of {len(expected_paths)} expected."
        )
        for rel in report["missing"]:
            print(f"  missing: {rel}")
        for entry in report["invalid"]:
            print(f"  invalid: {entry['path']} — {entry['reason']}")
    else:
        print(
            f"OK [{report.get('label','')}]: all {len(expected_paths)} "
            "manual-run artifacts present and v3-valid."
        )


def _is_blocked(report: dict[str, Any]) -> bool:
    if report.get("blocked"):
        return True
    return bool(report["missing"] or report["invalid"])


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        sys.stderr.write(f"phase dir not found: {phase_dir}\n")
        return 2

    payload: dict[str, Any] = {
        "phase_dir": str(phase_dir),
        "tool": args.tool,
        "reports": [],
    }

    if args.tool in SUPPORTED_TOOLS:
        per_tool_md = _expected_md_for_tool(phase_dir, args.tool)
        legacy_md = _legacy_expected_md(phase_dir)
        # Per-tool subdir is the v2.40.2 canonical layout. Fall back to legacy
        # only if the per-tool subdir doesn't exist AND legacy file does
        # (preserves in-flight pre-2.40.2 manual runs).
        if not per_tool_md.is_file() and legacy_md.is_file():
            report = _verify_one(phase_dir, legacy_md)
            report["label"] = f"{args.tool} (legacy fallback)"
        else:
            report = _verify_one(phase_dir, per_tool_md)
            report["label"] = args.tool
        payload["reports"].append(report)
    else:  # both
        for tool in SUPPORTED_TOOLS:
            md = _expected_md_for_tool(phase_dir, tool)
            report = _verify_one(phase_dir, md)
            report["label"] = tool
            payload["reports"].append(report)

    blocked = any(_is_blocked(r) for r in payload["reports"])
    payload["blocked"] = blocked

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        if not payload["reports"]:
            print("BLOCK: no reports produced")
        for r in payload["reports"]:
            _emit_human(r)
        if blocked:
            for r in payload["reports"]:
                if r.get("blocked"):
                    sys.stderr.write(
                        f"BLOCK: {r.get('reason', 'unknown')} "
                        f"(label={r.get('label','')})\n"
                    )

    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
