#!/usr/bin/env python3
"""
VG Bootstrap — Phase Metadata Emitter (Phase C helper)

Computes scope-evaluation metadata for a given phase so bootstrap-loader and
override-revalidate have the inputs they need. Fallback when phase-recon.md
artifacts are incomplete.

Reads (in priority order):
  1. {phase_dir}/SPECS.md — look for `surfaces:` field
  2. {phase_dir}/.phase-recon.json — from /vg:_shared/phase-recon
  3. git diff HEAD~20..HEAD -- apps/ packages/ — last N commits touched paths
  4. Scan PLAN*.md / API-CONTRACTS.md for POST/PUT/PATCH/DELETE method declarations

Emits env-var export lines or JSON (--emit).

Usage (from a vg command):
    eval "$(python .claude/scripts/phase-metadata.py --phase 07.8 --emit env)"
    # → sets PHASE_SURFACES, PHASE_TOUCHED_PATHS, PHASE_HAS_MUTATION,
    #   PHASE_UI_AUDIT_REQUIRED, PHASE_IS_API_ONLY

Always exit 0 — never block caller. Missing data → defaults (empty / false).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=5)
    except Exception:
        return ""


def find_phase_dir(planning_dir: Path, phase: str) -> Path | None:
    """Locate phase directory — supports both `07.8` and `07.8-video-ads-vast` forms."""
    phases = planning_dir / "phases"
    if not phases.exists():
        return None
    # Exact or prefix match
    for d in phases.iterdir():
        if not d.is_dir():
            continue
        name = d.name
        if name == phase or name.startswith(f"{phase}-") or name.startswith(f"{phase.replace('.', '_')}-"):
            return d
    return None


def parse_surfaces(phase_dir: Path) -> list[str]:
    specs = phase_dir / "SPECS.md"
    if not specs.exists():
        return []
    text = specs.read_text(encoding="utf-8", errors="replace")
    # Look for `surfaces: [web, api]` or `surfaces:\n  - web\n  - api`
    m = re.search(r"^surfaces:\s*\[([^\]]+)\]", text, re.MULTILINE)
    if m:
        return [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]

    m = re.search(r"^surfaces:\s*\n((?:\s+-\s+\S+\n?)+)", text, re.MULTILINE)
    if m:
        return [ln.strip()[2:].strip().strip("'\"") for ln in m.group(1).splitlines() if ln.strip()]

    # Fallback: infer from touched paths later
    return []


def parse_touched_paths(phase_dir: Path) -> list[str]:
    """Get touched path globs — from phase-recon JSON if present, else git diff."""
    recon = phase_dir / ".phase-recon.json"
    if recon.exists():
        try:
            data = json.loads(recon.read_text(encoding="utf-8"))
            if isinstance(data.get("touched_paths"), list):
                return data["touched_paths"]
        except Exception:
            pass

    # Fallback: git log touching apps/** packages/** since phase dir creation
    out = _run(["git", "log", "--name-only", "--pretty=format:", "-20", "--", "apps/", "packages/"])
    paths = sorted({line.strip() for line in out.splitlines() if line.strip()})
    return paths[:200]  # cap


def infer_surfaces_from_paths(touched: list[str]) -> list[str]:
    """Infer surfaces from touched_paths when SPECS doesn't declare."""
    inferred = set()
    for p in touched:
        if p.startswith("apps/web"):
            inferred.add("web")
        elif p.startswith("apps/api"):
            inferred.add("api")
        elif p.startswith("apps/rtb-engine"):
            inferred.add("rtb")
        elif p.startswith("apps/workers"):
            inferred.add("workers")
        elif p.startswith("packages/"):
            inferred.add("shared")
    return sorted(inferred)


_MUTATION_METHODS = re.compile(r"\b(POST|PUT|PATCH|DELETE)\b")


def detect_has_mutation(phase_dir: Path) -> bool:
    """Detect mutations from API-CONTRACTS.md, PLAN*.md, CONTEXT.md."""
    for pattern in ("API-CONTRACTS.md", "PLAN*.md", "CONTEXT.md"):
        for f in phase_dir.glob(pattern):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                if _MUTATION_METHODS.search(text):
                    return True
            except Exception:
                continue
    return False


def detect_ui_audit(phase_dir: Path, surfaces: list[str]) -> bool:
    if "web" in surfaces:
        return True
    # Look for UI-SPEC/UI-MAP artifacts
    for f in phase_dir.glob("UI-*.md"):
        if f.exists():
            return True
    return False


def build_metadata(planning_dir: Path, phase: str) -> dict:
    phase_dir = find_phase_dir(planning_dir, phase)
    if phase_dir is None:
        return {
            "phase": phase,
            "phase_dir": None,
            "surfaces": [],
            "touched_paths": [],
            "has_mutation": False,
            "ui_audit_required": False,
            "is_api_only": False,
            "found": False,
        }

    touched = parse_touched_paths(phase_dir)
    surfaces = parse_surfaces(phase_dir) or infer_surfaces_from_paths(touched)
    has_mutation = detect_has_mutation(phase_dir)
    ui_audit = detect_ui_audit(phase_dir, surfaces)
    is_api_only = "api" in surfaces and "web" not in surfaces

    return {
        "phase": phase,
        "phase_dir": str(phase_dir),
        "surfaces": surfaces,
        "touched_paths": touched,
        "has_mutation": has_mutation,
        "ui_audit_required": ui_audit,
        "is_api_only": is_api_only,
        "found": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="VG phase metadata emitter")
    ap.add_argument("--phase", required=True)
    ap.add_argument("--planning", default=".vg")
    ap.add_argument("--emit", choices=["env", "json"], default="env")
    args = ap.parse_args()

    meta = build_metadata(Path(args.planning), args.phase)

    if args.emit == "json":
        print(json.dumps(meta, indent=2, ensure_ascii=False))
    else:
        # Shell-safe env var export
        print(f'export PHASE_SURFACES="{",".join(meta["surfaces"])}"')
        print(f'export PHASE_TOUCHED_PATHS="{",".join(meta["touched_paths"][:20])}"')
        print(f'export PHASE_HAS_MUTATION="{str(meta["has_mutation"]).lower()}"')
        print(f'export PHASE_UI_AUDIT_REQUIRED="{str(meta["ui_audit_required"]).lower()}"')
        print(f'export PHASE_IS_API_ONLY="{str(meta["is_api_only"]).lower()}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
