#!/usr/bin/env python3
"""B63: verify scanner cross_view_propagation observations cover CRUD.

For every CRUD-creating resource in CRUD-SURFACES.md, at least one
scan-*.json under phase_dir must have:
  cross_view_propagation_observations[] entry where:
    - entity_canonical_id matches resource (or source_view contains
      resource slug)
    - action=create
    - observed_in_target in {yes, partial}

Waiver: `.vg/scanner-overrides.yaml` with `skip_cross_view: true` per
resource OR global `cross_view_scan: disabled`.

Usage:
  verify-cross-view-coverage.py --phase 7
  verify-cross-view-coverage.py --phase 7 --strict
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


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


RESOURCE_RE = re.compile(r"^(?:##\s+|resource:\s+)([\w_-]+)", re.M)
CREATE_METHOD_RE = re.compile(r'"method"\s*:\s*"POST"|method:\s*POST', re.I)


def _parse_crud_resources(phase_dir: Path) -> set[str]:
    surfaces = phase_dir / "CRUD-SURFACES.md"
    if surfaces.is_file():
        text = surfaces.read_text(encoding="utf-8", errors="replace")
    else:
        sd = phase_dir / "CRUD-SURFACES"
        if not sd.is_dir():
            return set()
        text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                          for p in sd.glob("*.md"))
    resources: set[str] = set()
    last_r: str | None = None
    last_start = 0
    chunks: list[tuple[str, str]] = []
    for m in RESOURCE_RE.finditer(text):
        if last_r is not None:
            chunks.append((last_r, text[last_start:m.start()]))
        last_r = m.group(1)
        last_start = m.end()
    if last_r is not None:
        chunks.append((last_r, text[last_start:]))
    for resource, block in chunks:
        if CREATE_METHOD_RE.search(block):
            resources.add(resource)
    return resources


def _parse_overrides(phase_dir: Path) -> dict:
    """Parse .vg/scanner-overrides.yaml (tiny subset).
    Returns {global_disabled: bool, skip_resources: set[str]}.
    """
    candidates = [
        phase_dir / ".vg" / "scanner-overrides.yaml",
        phase_dir.parent.parent / ".vg" / "scanner-overrides.yaml",
        Path(".vg") / "scanner-overrides.yaml",
    ]
    out = {"global_disabled": False, "skip_resources": set()}
    for c in candidates:
        if c.is_file():
            text = c.read_text(encoding="utf-8", errors="replace")
            if re.search(r"cross_view_scan:\s*disabled", text):
                out["global_disabled"] = True
            for m in re.finditer(r"skip_cross_view\[?([\w_-]*)\]?\s*:\s*true", text):
                if m.group(1):
                    out["skip_resources"].add(m.group(1))
                else:
                    out["global_disabled"] = True
            break
    return out


def _load_scan_observations(phase_dir: Path) -> list[dict]:
    """Collect cross_view_propagation_observations from all scans."""
    obs: list[dict] = []
    for scan_file in sorted(phase_dir.glob("scan-*.json")):
        try:
            doc = json.loads(scan_file.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        for entry in doc.get("cross_view_propagation_observations") or []:
            if isinstance(entry, dict):
                obs.append(entry)
    return obs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    resources = _parse_crud_resources(phase_dir)
    if not resources:
        print(f"ℹ B63: no CRUD resources with POST — no cross-view required")
        return 0

    overrides = _parse_overrides(phase_dir)
    if overrides["global_disabled"]:
        print(f"ℹ B63: cross_view_scan disabled globally (scanner-overrides.yaml) — skipping")
        return 0

    observations = _load_scan_observations(phase_dir)

    # Resource→observation matching: substring on entity_canonical_id or source_view.
    # Check waiver FIRST so phases with override but no scan still PASS.
    covered: set[str] = set()
    for resource in resources:
        if resource in overrides["skip_resources"]:
            covered.add(resource)
            continue
        rname = resource.lower()
        for obs in observations:
            if obs.get("action") != "create":
                continue
            if obs.get("observed_in_target") not in ("yes", "partial"):
                continue
            ec = (obs.get("entity_canonical_id") or "").lower()
            sv = (obs.get("source_view") or "").lower()
            if rname in ec or rname in sv:
                covered.add(resource)
                break

    uncovered = sorted(resources - covered)
    # Report no observations distinctly only if there are uncovered resources
    if uncovered and not observations:
        print(f"⛔ B63: no scan-*.json with cross_view_propagation_observations[] found",
              file=sys.stderr)
    print(f"B63: {len(resources)} CRUD resource(s), {len(observations)} cross-view obs, "
          f"{len(uncovered)} uncovered")
    if uncovered:
        for r in uncovered:
            print(f"  UNCOVERED: resource '{r}' has no CREATE cross_view_propagation "
                  f"(scanner did not navigate post-mutation OR enable "
                  f"skip_cross_view[{r}]: true in .vg/scanner-overrides.yaml)",
                  file=sys.stderr)
        if args.strict:
            return 1
        print(f"⚠ B63: warn-mode (use --strict to BLOCK)", file=sys.stderr)
    else:
        print(f"✓ B63: every CRUD resource has cross-view propagation observation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
