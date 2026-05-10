#!/usr/bin/env python3
"""
verify-route-inventory.py — v3.4.0 (#173 Stage 4)

Hard-blocks /vg:review when the runtime-discovered route set diverges
from the contract route inventory:

  - UI-RUNTIME-CONTRACT.json route_inventory[].path   (blueprint declared)
  - RUNTIME-MAP.json views[<view_url>]                (browser observed)

Two divergence classes:
  - UNDECLARED — view discovered at runtime but absent from contract
  - UNREACHED  — contract declared route but no view scanned for it

Either class → BLOCK by default. severity=warn downgrades to WARN.

Closes Issue #173 acceptance criterion:
  "/vg:review --with-deep-scan blocks when route inventory ... artifacts
   are missing."

Skip conditions (PASS, no enforcement):
  - UI-RUNTIME-CONTRACT.json missing (legacy phase / pre-v3.2.0)
  - contract.skip_reason populated (backend-only / no FE tasks)
  - RUNTIME-MAP.json missing AND contract.route_inventory empty

Usage:
  verify-route-inventory.py --phase-dir <path>
  verify-route-inventory.py --phase <number> [--severity warn]

Exit codes:
  0 — PASS or WARN
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
from _common import Evidence, Output, timer, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Strip query string + fragment from URLs (RUNTIME-MAP keys may be full URLs
# from browser navigation including ?param=...). For comparison we want the
# pathname only.
URL_PATH_RE = re.compile(r"^(?:[a-z]+://[^/]+)?(/[^?#]*)", re.IGNORECASE)
# Convert numeric path segments to `:id` placeholder so /sites/42 matches
# the contract's /sites/:id declaration.
NUMERIC_SEGMENT_RE = re.compile(r"/\d+(?=/|$)")
# Same for UUIDs (8-4-4-4-12 hex).
UUID_SEGMENT_RE = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)", re.IGNORECASE)


def normalize_path(raw: str) -> str:
    """Reduce a URL or path string to its canonical comparable form."""
    if not raw:
        return ""
    m = URL_PATH_RE.match(raw)
    path = m.group(1) if m else raw
    # Strip trailing slash (but keep root "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    # Replace numeric / UUID segments with :id so /sites/42 == /sites/:id
    path = NUMERIC_SEGMENT_RE.sub("/:id", path)
    path = UUID_SEGMENT_RE.sub("/:id", path)
    return path.lower()


def load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_contract(phase_dir: Path) -> dict | None:
    return load_json(phase_dir / "UI-RUNTIME-CONTRACT.json")


def load_runtime_map(phase_dir: Path) -> dict | None:
    return load_json(phase_dir / "RUNTIME-MAP.json")


def collect_contract_routes(contract: dict) -> set[str]:
    out: set[str] = set()
    for r in contract.get("route_inventory") or []:
        p = r.get("path") or ""
        if p:
            out.add(normalize_path(p))
    return out


def collect_runtime_routes(rmap: dict) -> set[str]:
    out: set[str] = set()
    views = rmap.get("views") or {}
    if isinstance(views, dict):
        for k in views.keys():
            n = normalize_path(k)
            if n and n.startswith("/"):
                out.add(n)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--phase-dir")
    g.add_argument("--phase")
    ap.add_argument("--severity", choices=["warn", "block"], default="block")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    output = Output(validator="route-inventory")

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
                type="route_inventory_no_contract",
                message=(
                    "UI-RUNTIME-CONTRACT.json missing — legacy phase. Route inventory "
                    "gate skipped. Re-run /vg:blueprint step 2b6d_ui_runtime_contract to emit."
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
                type="route_inventory_skipped",
                message=f"Contract skip_reason: {skip_reason}",
            ))
            if args.json:
                print(output.to_json())
            else:
                print(f"ℹ {output.evidence[-1].message}")
            return 0

        contract_routes = collect_contract_routes(contract)
        rmap = load_runtime_map(phase_dir)
        if rmap is None and not contract_routes:
            output.evidence.append(Evidence(
                type="route_inventory_empty",
                message="No contract routes declared and no RUNTIME-MAP.json — skip.",
            ))
            if args.json:
                print(output.to_json())
            else:
                print("ℹ Route inventory empty — skip.")
            return 0

        runtime_routes = collect_runtime_routes(rmap or {})

        undeclared = sorted(runtime_routes - contract_routes)
        unreached = sorted(contract_routes - runtime_routes)

        if undeclared:
            output.add(Evidence(
                type="route_inventory_undeclared",
                message=(
                    f"{len(undeclared)} route(s) discovered at runtime but absent from "
                    f"UI-RUNTIME-CONTRACT.route_inventory: "
                    f"{', '.join(undeclared[:5])}"
                    f"{', …' if len(undeclared) > 5 else ''}"
                ),
                file="UI-RUNTIME-CONTRACT.json",
                expected="every runtime route declared in route_inventory[]",
                actual=f"{len(undeclared)} undeclared",
                severity="HIGH",
                fix_hint=(
                    "Either: (a) add the discovered routes to PLAN.md so /vg:blueprint "
                    "step 2b6d_ui_runtime_contract picks them up on re-run; or (b) treat "
                    "the runtime route as scope creep — file an amendment."
                ),
            ))

        if unreached:
            output.add(Evidence(
                type="route_inventory_unreached",
                message=(
                    f"{len(unreached)} contract route(s) declared but no view scanned for "
                    f"them at runtime: {', '.join(unreached[:5])}"
                    f"{', …' if len(unreached) > 5 else ''}"
                ),
                file="UI-RUNTIME-CONTRACT.json",
                expected="every contract route discovered during browser scan",
                actual=f"{len(unreached)} unreached",
                severity="HIGH",
                fix_hint=(
                    "Routes were declared but not visited. Re-run /vg:review with deeper "
                    "discovery (--mode=full) OR remove the unreached routes from PLAN if "
                    "they were dropped from scope."
                ),
            ))

        if not undeclared and not unreached:
            output.evidence.append(Evidence(
                type="route_inventory_match",
                message=(
                    f"Route inventory matches runtime: {len(contract_routes)} route(s) "
                    f"declared, all observed during scan."
                ),
            ))

    if args.severity == "warn" and output.verdict == "BLOCK":
        output.verdict = "WARN"

    if args.json:
        print(output.to_json())
    else:
        if output.verdict == "BLOCK":
            print(f"\033[38;5;208mRoute inventory gate: BLOCK\033[0m")
            for e in output.evidence:
                if e.type in ("route_inventory_match",):
                    continue
                print(f"  [{e.type}] {e.message}")
                if e.fix_hint:
                    print(f"    hint: {e.fix_hint}")
        elif output.verdict == "WARN":
            print(f"\033[33mRoute inventory gate: WARN\033[0m")
            for e in output.evidence:
                print(f"  [{e.type}] {e.message}")
        else:
            print("✓ Route inventory gate: PASS")
            for e in output.evidence:
                print(f"  [{e.type}] {e.message}")

    if output.verdict == "BLOCK":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
