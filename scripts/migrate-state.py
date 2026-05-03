#!/usr/bin/env python3
"""
migrate-state.py — Phase state migrator for VG harness skill-version drift.

Problem
=======
When the VG harness upgrades and a skill adds new <step> blocks (or wires
mark-step where it wasn't wired before), phases that already ran the OLD
skill miss the new markers. /vg:accept then BLOCKs on must_touch_markers
contract violations even though the pipeline actually ran end-to-end —
artifacts (PLAN.md, REVIEW-FEEDBACK.md, SANDBOX-TEST.md, etc.) prove it.

This script detects + backfills marker drift retroactively. Idempotent.
Logs a single override-debt entry per phase per apply run.

Companion to Tier B (skill-version stamping at /vg:scope) — when /vg:scope
writes .contract-pins.json on first scope, future upgrades won't drift.
This script handles the legacy phases that pre-date the pin mechanism.

Usage
=====
    /vg:migrate-state --scan                  # read-only project-wide table
    /vg:migrate-state {phase}                 # auto-default = --apply on phase
    /vg:migrate-state {phase} --dry-run       # preview, no writes
    /vg:migrate-state --apply-all             # batch fix every phase
    /vg:migrate-state {phase} --json          # machine-readable scan output

Exit codes
==========
    0 = nothing to migrate, OR migration applied successfully
    1 = drift detected (--scan/--dry-run only) — re-run with --apply to fix
    2 = invalid args / phase not found / IO error
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PHASES_DIR = REPO_ROOT / ".vg" / "phases"
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands" / "vg"
OVERRIDE_DEBT_FILE = REPO_ROOT / ".vg" / "OVERRIDE-DEBT.md"

# Commands that have phase-scoped step markers worth tracking. Excludes
# project-wide commands (sync, project, doctor, etc.) and helpers (_shared).
TRACKED_COMMANDS = ("scope", "blueprint", "build", "review", "test", "accept")

# Per-command artifact evidence — at least one path must exist (relative to
# phase dir) for migrate-state to consider that command "actually ran" for
# this phase. Without evidence, missing markers are a mystery (pipeline
# never ran), so we DON'T backfill blindly.
ARTIFACT_EVIDENCE: dict[str, tuple[str, ...]] = {
    "scope": ("CONTEXT.md", "DISCUSSION-LOG.md"),
    # Multi-plan phases (e.g. 07.13) use NN-PLAN.md / NN-SUMMARY.md naming
    # alongside the canonical filename, so accept both as evidence.
    "blueprint": ("PLAN.md", "*-PLAN.md", "API-CONTRACTS.md", "TEST-GOALS.md"),
    "build": ("SUMMARY.md", "*-SUMMARY.md", ".build-progress.json"),
    "review": ("REVIEW-FEEDBACK.md", "RUNTIME-MAP.json", "RUNTIME-MAP.md"),
    "test": ("SANDBOX-TEST.md",),
    "accept": ("UAT.md",),
}

# Step-name pattern: enforce identifier-like contents to skip false matches
# from doc-comments (e.g. literal "<step name=...>" inside a paragraph).
STEP_NAME_RE = re.compile(r'<step name="([A-Za-z0-9_][A-Za-z0-9_-]*)"')

# ---------------------------------------------------------------------------
# Skill parsing
# ---------------------------------------------------------------------------


def parse_skill_steps(command: str) -> list[str]:
    """Return ordered step names declared in .claude/commands/vg/{command}.md."""
    skill = COMMANDS_DIR / f"{command}.md"
    if not skill.exists():
        return []
    text = skill.read_text(encoding="utf-8")
    # Preserve declaration order; dedupe.
    seen: set[str] = set()
    ordered: list[str] = []
    for m in STEP_NAME_RE.finditer(text):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def has_artifact_evidence(phase_dir: Path, command: str) -> tuple[bool, list[str]]:
    """True if any expected artifact for `command` exists in phase_dir.

    Patterns containing `*` are treated as glob expressions to match
    multi-plan phases (e.g. `07.13-01-PLAN.md`).
    """
    candidates = ARTIFACT_EVIDENCE.get(command, ())
    found: list[str] = []
    for cand in candidates:
        if "*" in cand:
            matches = list(phase_dir.glob(cand))
            if matches:
                found.append(cand)
        elif (phase_dir / cand).exists():
            found.append(cand)
    return (bool(found), found)


def existing_markers(phase_dir: Path, command: str) -> set[str]:
    marker_dir = phase_dir / ".step-markers" / command
    if not marker_dir.is_dir():
        return set()
    return {p.stem for p in marker_dir.glob("*.done")}


def detect_drift_for_phase(phase_dir: Path) -> dict[str, Any]:
    """Inspect a single phase, return drift breakdown."""
    phase_id = phase_dir.name
    out: dict[str, Any] = {
        "phase": phase_id,
        "phase_dir": str(phase_dir),
        "commands": {},
        "totals": {"missing_markers": 0, "ran_commands": 0, "skipped_commands": 0},
    }
    for cmd in TRACKED_COMMANDS:
        steps = parse_skill_steps(cmd)
        if not steps:
            continue
        ran, evidence = has_artifact_evidence(phase_dir, cmd)
        present = existing_markers(phase_dir, cmd)
        missing = [s for s in steps if s not in present]
        cmd_entry = {
            "skill_steps": len(steps),
            "markers_present": sorted(present),
            "markers_missing": missing,
            "evidence_artifacts": evidence,
            "evidence_seen": ran,
        }
        if ran:
            out["totals"]["ran_commands"] += 1
            out["totals"]["missing_markers"] += len(missing)
        else:
            out["totals"]["skipped_commands"] += 1
        out["commands"][cmd] = cmd_entry
    return out


def scan_all_phases() -> list[dict[str, Any]]:
    if not PHASES_DIR.is_dir():
        return []
    return [detect_drift_for_phase(p) for p in sorted(PHASES_DIR.iterdir())
            if p.is_dir()]


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def _git_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_marker(
    phase_dir: Path, command: str, step: str, *, git_sha: str, ts: str
) -> Path:
    marker_dir = phase_dir / ".step-markers" / command
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / f"{step}.done"
    body = (
        f"migration-backfill|{phase_dir.name}|{command}/{step}|{git_sha}|"
        f"{ts}|skill-version-drift\n"
    )
    marker.write_text(body, encoding="utf-8")
    return marker


def next_od_id() -> str:
    if not OVERRIDE_DEBT_FILE.exists():
        return "OD-1"
    text = OVERRIDE_DEBT_FILE.read_text(encoding="utf-8")
    nums = [int(m.group(1)) for m in re.finditer(r"^- id: OD-(\d+)", text, re.MULTILINE)]
    return f"OD-{(max(nums) + 1) if nums else 1}"


def append_override_debt(
    phase_id: str, summary: dict[str, Any], git_sha: str, ts: str
) -> str:
    od_id = next_od_id()
    backfill_count = sum(len(c["markers_missing"])
                         for c in summary["commands"].values()
                         if c["evidence_seen"])
    by_cmd = ", ".join(
        f"{cmd}={len(c['markers_missing'])}"
        for cmd, c in summary["commands"].items()
        if c["evidence_seen"] and c["markers_missing"]
    ) or "none"
    reason = (
        f"Phase {phase_id} skill-version drift backfill: {backfill_count} "
        f"marker(s) backfilled across commands [{by_cmd}]. Pipeline ran "
        f"with older skill version that did not wire mark-step per <step> "
        f"close; artifacts on disk confirm execution. /vg:migrate-state "
        f"applied at {ts}. Markers written to "
        f".vg/phases/{phase_id}/.step-markers/{{command}}/ with content "
        f"'migration-backfill|{phase_id}|...|skill-version-drift'. "
        f"verify-step-markers gate is preserved (validators see complete "
        f"marker set). OD entry stays active as historical drift record."
    )
    entry = (
        f"\n- id: {od_id}\n"
        f"  logged_at: {ts}\n"
        f"  command: vg:migrate-state\n"
        f'  phase: "{phase_id}"\n'
        f"  flag: skill-version-drift-marker-backfill\n"
        f'  reason: "{reason}"\n'
        f"  git_sha: {git_sha}\n"
        f"  status: active\n"
    )
    with OVERRIDE_DEBT_FILE.open("a", encoding="utf-8") as f:
        f.write(entry)
    return od_id


def _write_contract_pin_if_missing(phase_dir: Path, dry_run: bool) -> str | None:
    """Tier B companion — when migrate-state applies on a legacy phase that
    has no .contract-pins.json yet, snapshot the current skill contracts
    into a pin so this phase locks at the current harness version going
    forward (best we can do retroactively). Returns "would-write",
    "wrote", "exists", or None.
    """
    pin_file = phase_dir / ".contract-pins.json"
    if pin_file.exists():
        return "exists"
    if dry_run:
        return "would-write"
    pin_script = REPO_ROOT / ".claude" / "scripts" / "vg-contract-pins.py"
    if not pin_script.exists():
        return None
    try:
        subprocess.run(
            [sys.executable, str(pin_script), "write", phase_dir.name],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except Exception:
        return None
    return "wrote" if pin_file.exists() else None


def apply_phase(
    phase_dir: Path, *, dry_run: bool, summary: dict[str, Any] | None = None
) -> dict[str, Any]:
    summary = summary or detect_drift_for_phase(phase_dir)
    phase_id = phase_dir.name
    git_sha = _git_sha()
    ts = _iso_now()
    actions: list[dict[str, str]] = []
    for cmd, info in summary["commands"].items():
        if not info["evidence_seen"]:
            continue
        for step in info["markers_missing"]:
            if dry_run:
                actions.append({"action": "would-create", "command": cmd,
                                "step": step})
            else:
                marker = write_marker(phase_dir, cmd, step,
                                      git_sha=git_sha, ts=ts)
                actions.append({"action": "created", "command": cmd,
                                "step": step,
                                "path": str(marker.relative_to(REPO_ROOT))})

    od_id: str | None = None
    if not dry_run and actions:
        od_id = append_override_debt(phase_id, summary, git_sha, ts)
    elif dry_run and actions:
        od_id = "would-log-OD"

    # Tier B: write contract pin for legacy phases (best-effort, doesn't
    # affect markers_backfilled count). Only triggers when migrate-state
    # actually applies (skip on no-drift idempotent re-runs).
    pin_status: str | None = None
    if actions:
        pin_status = _write_contract_pin_if_missing(phase_dir, dry_run)

    return {
        "phase": phase_id,
        "dry_run": dry_run,
        # Count both "created" (apply mode) and "would-create" (dry-run mode)
        # so callers see consistent drift counts regardless of mode.
        "markers_backfilled": len(actions),
        "actions": actions,
        "override_debt_id": od_id,
        "contract_pin": pin_status,
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def render_scan_table(rows: list[dict[str, Any]]) -> str:
    out: list[str] = []
    out.append("Phase                                              ran  skip  miss")
    out.append("-" * 75)
    drift_total = 0
    for r in rows:
        miss = r["totals"]["missing_markers"]
        if miss:
            drift_total += 1
        out.append(
            f"{r['phase']:<50} {r['totals']['ran_commands']:>4} "
            f"{r['totals']['skipped_commands']:>5} {miss:>5}"
        )
    out.append("-" * 75)
    out.append(f"{len(rows)} phase(s) scanned, {drift_total} with drift")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def resolve_phase_dir(phase_arg: str) -> Path | None:
    if not phase_arg:
        return None
    candidates = [PHASES_DIR / phase_arg]
    if not candidates[0].exists():
        # Allow shorthand like "7.14.3" matching "7.14.3-..."
        prefix_matches = [p for p in PHASES_DIR.iterdir()
                          if p.is_dir() and p.name == phase_arg]
        if not prefix_matches:
            prefix_matches = [p for p in PHASES_DIR.iterdir()
                              if p.is_dir() and p.name.startswith(phase_arg + "-")]
        if len(prefix_matches) == 1:
            candidates = prefix_matches
        elif len(prefix_matches) > 1:
            print(f"⛔ Ambiguous phase '{phase_arg}' — matches:",
                  file=sys.stderr)
            for m in prefix_matches:
                print(f"   {m.name}", file=sys.stderr)
            return None
    if not candidates[0].is_dir():
        print(f"\033[38;5;208mPhase not found: {phase_arg}\033[0m", file=sys.stderr)
        return None
    return candidates[0]


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("phase", nargs="?", help="phase id (e.g. 7.14.3 or full name)")
    p.add_argument("--scan", action="store_true",
                   help="read-only project-wide drift table")
    p.add_argument("--apply", action="store_true",
                   help="backfill markers + log override-debt (default if phase given)")
    p.add_argument("--apply-all", action="store_true",
                   help="apply across every phase")
    p.add_argument("--dry-run", action="store_true",
                   help="preview without writing")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON")
    args = p.parse_args(argv)

    if not PHASES_DIR.is_dir():
        print(f"\033[38;5;208mPhase directory not found: {PHASES_DIR}\033[0m", file=sys.stderr)
        return 2

    # Mode resolution
    if args.scan or (args.phase is None and not args.apply_all):
        rows = scan_all_phases()
        if args.json:
            print(json.dumps({"scan": rows}, indent=2))
        else:
            print(render_scan_table(rows))
        drift_count = sum(1 for r in rows if r["totals"]["missing_markers"])
        return 1 if drift_count else 0

    if args.apply_all:
        rows = scan_all_phases()
        results = []
        for r in rows:
            if r["totals"]["missing_markers"] == 0:
                continue
            phase_dir = Path(r["phase_dir"])
            results.append(apply_phase(phase_dir, dry_run=args.dry_run,
                                       summary=r))
        if args.json:
            print(json.dumps({"applied": results}, indent=2))
        else:
            total = sum(x["markers_backfilled"] for x in results)
            print(f"{'Would backfill' if args.dry_run else 'Backfilled'} "
                  f"{total} marker(s) across {len(results)} phase(s)")
            for r in results:
                if r["markers_backfilled"]:
                    print(f"  {r['phase']}: {r['markers_backfilled']} marker(s)"
                          f"  OD={r['override_debt_id']}")
        return 0

    # Single-phase apply
    phase_dir = resolve_phase_dir(args.phase)
    if not phase_dir:
        return 2
    summary = detect_drift_for_phase(phase_dir)
    result = apply_phase(phase_dir, dry_run=args.dry_run, summary=summary)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["markers_backfilled"] == 0:
            print(f"✓ {result['phase']}: no drift (already in sync)")
        else:
            verb = "Would backfill" if args.dry_run else "Backfilled"
            print(f"{verb} {result['markers_backfilled']} marker(s) in "
                  f"{result['phase']}")
            for a in result["actions"]:
                print(f"  {a['action']:>12}  {a['command']}/{a['step']}")
            if result["override_debt_id"]:
                print(f"  Override-debt: {result['override_debt_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
