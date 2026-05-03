#!/usr/bin/env python3
"""
Validator: verify-design-extractor-output.py — Phase 15 D-01

Asserts /vg:design-extract produced complete, schema-valid output for every
file in .planning/design-source/. Closes silent-skip gap where design refs
appear in PLAN but were never normalized → executor builds blind.

Logic:
  1. Locate slug-registry.json under design_assets.output_dir
     (default .planning/design-normalized/, OR fallback to manifest.json
     since current /vg:design-extract emits manifest.json — slug-registry is
     Phase 15 nomenclature, manifest.json maps to it 1:1).
  2. Walk source directory listed in vg.config.md design_assets.paths globs.
  3. Per source file: assert matching entry in registry/manifest.
  4. Per entry: assert outputs exist (screenshots[], structural[_json],
     interactions if applicable).
  5. If structural_json present: parse + light schema check
     (format_version "1.0", source_format enum, root.tag string).

Usage:  verify-design-extractor-output.py --phase 7.14.3
        verify-design-extractor-output.py --output-dir .planning/design-normalized
Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

VALID_SOURCE_FORMATS = {
    "html", "png-structural",
    "pencil-mcp", "pencil-xml",
    "penboard-mcp", "penboard-pb",
}


def _read_design_assets_paths() -> tuple[Path, list[str]]:
    """Returns (output_dir, paths globs) from vg.config.md design_assets block."""
    repo = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    config = None
    for c in [repo / ".claude" / "vg.config.md", repo / "vg.config.md",
              repo / "vg.config.template.md"]:
        if c.exists():
            config = c
            break
    if config is None:
        return repo / ".planning" / "design-normalized", []
    text = config.read_text(encoding="utf-8", errors="ignore")
    block = re.search(r"^design_assets:\s*\n((?:[ \t]+.*\n?)+)", text, re.MULTILINE)
    if not block:
        return repo / ".planning" / "design-normalized", []
    body = block.group(1)
    out_dir_m = re.search(r"^\s+output_dir:\s*[\"']?([^\"'\n#]+)[\"']?",
                          body, re.MULTILINE)
    output_dir = (repo / out_dir_m.group(1).strip()
                  if out_dir_m else repo / ".planning" / "design-normalized")
    paths_m = re.search(r"^\s+paths:\s*\n((?:\s+-\s+.*\n?)+)", body, re.MULTILINE)
    globs: list[str] = []
    if paths_m:
        for ln in paths_m.group(1).splitlines():
            mg = re.match(r"^\s+-\s+[\"']?([^\"'\n#]+)[\"']?", ln)
            if mg:
                globs.append(mg.group(1).strip())
    return output_dir, globs


def _load_registry(output_dir: Path) -> tuple[dict, str]:
    """Returns (registry_dict, source) — slug-registry.json or manifest.json."""
    for name in ("slug-registry.json", "manifest.json"):
        p = output_dir / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")), name
            except json.JSONDecodeError:
                continue
    return {}, ""


def _registry_has_source(registry: dict, source_path: Path) -> dict | None:
    """Lookup by source path. Handles both Phase 15 slug-registry shape +
    legacy manifest.json shape (assets[].path)."""
    src_str = str(source_path)
    src_basename = source_path.name
    # Phase 15 shape
    slugs = registry.get("slugs") or {}
    for entry in slugs.values():
        sp = entry.get("source_path", "")
        if sp == src_str or sp.endswith(src_basename):
            return entry
    # Legacy manifest shape
    for asset in registry.get("assets") or []:
        ap = asset.get("path", "")
        if ap == src_str or ap.endswith(src_basename):
            return asset
    return None


def _validate_structural_json(path: Path, asset_name: str) -> list[Evidence]:
    out: list[Evidence] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        out.append(Evidence(
            type="malformed_content",
            message=f"structural_json unparseable for {asset_name}: {e}",
            file=str(path),
        ))
        return out
    if data.get("format_version") != "1.0":
        out.append(Evidence(
            type="schema_violation",
            message=f"structural_json {asset_name}: format_version != '1.0'",
            file=str(path), expected="1.0", actual=data.get("format_version"),
        ))
    sf = data.get("source_format")
    if sf not in VALID_SOURCE_FORMATS:
        out.append(Evidence(
            type="schema_violation",
            message=f"structural_json {asset_name}: invalid source_format {sf!r}",
            file=str(path), expected=sorted(VALID_SOURCE_FORMATS), actual=sf,
        ))
    root = data.get("root") or {}
    if not isinstance(root.get("tag"), str):
        out.append(Evidence(
            type="schema_violation",
            message=f"structural_json {asset_name}: root.tag not a string",
            file=str(path),
        ))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", help="Optional — limits source scope to phase")
    ap.add_argument("--output-dir", help="Override design_assets.output_dir from vg.config.md")
    args = ap.parse_args()

    out = Output(validator="design-extractor-output")
    with timer(out):
        output_dir, source_globs = _read_design_assets_paths()
        if args.output_dir:
            output_dir = Path(args.output_dir).resolve()

        if not output_dir.exists():
            out.add(Evidence(
                type="missing_file",
                message=f"design_assets.output_dir does not exist: {output_dir}",
                fix_hint="Run /vg:design-extract to populate. Confirm vg.config.md design_assets.output_dir.",
            ))
            emit_and_exit(out)

        registry, registry_source = _load_registry(output_dir)
        if not registry:
            out.add(Evidence(
                type="missing_file",
                message=f"Neither slug-registry.json nor manifest.json found in {output_dir}",
                fix_hint="Run /vg:design-extract to generate manifest. /vg:design-extract --refresh forces rebuild.",
            ))
            emit_and_exit(out)

        # Collect source files via globs (or scan output entries if no globs)
        repo_root = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
        source_files: list[Path] = []
        for g in source_globs:
            matched = list(repo_root.glob(g))
            source_files.extend(p for p in matched if p.is_file())
        if not source_files:
            # Fallback: scan registry for declared source paths
            for entry in (registry.get("slugs") or {}).values():
                sp = entry.get("source_path")
                if sp and Path(sp).exists():
                    source_files.append(Path(sp))
            for asset in registry.get("assets") or []:
                ap = asset.get("path")
                if ap and Path(ap).exists():
                    source_files.append(Path(ap))
        source_files = list({str(p): p for p in source_files}.values())  # dedupe

        if not source_files:
            out.warn(Evidence(
                type="info",
                message="No design source files matched globs OR registry — nothing to verify.",
            ))
            emit_and_exit(out)

        # Per-file checks
        for src in source_files:
            entry = _registry_has_source(registry, src)
            if entry is None:
                out.add(Evidence(
                    type="missing_file",
                    message=f"Source file {src.name} has no entry in {registry_source}",
                    file=str(src),
                    fix_hint=("Re-run /vg:design-extract to inventory + normalize. "
                              "If file is intentionally excluded, remove from "
                              "design_assets.paths globs."),
                ))
                continue

            screenshots = entry.get("screenshots") or []
            if not screenshots:
                out.add(Evidence(
                    type="missing_file",
                    message=f"Asset {src.name}: no screenshots in registry entry",
                    file=str(src),
                    fix_hint="Verify normalizer handler ran successfully. Check entry.error/warning fields.",
                ))
            else:
                for s in screenshots:
                    sp = output_dir / s
                    if not sp.exists():
                        out.add(Evidence(
                            type="missing_file",
                            message=f"Asset {src.name}: screenshot path missing on disk",
                            file=str(sp),
                        ))

            sj_rel = entry.get("structural_json") or entry.get("structural")
            if sj_rel and sj_rel.endswith(".json"):
                sj_path = output_dir / sj_rel
                if not sj_path.exists():
                    out.add(Evidence(
                        type="missing_file",
                        message=f"Asset {src.name}: structural_json path missing on disk",
                        file=str(sj_path),
                    ))
                else:
                    out.evidence.extend(_validate_structural_json(sj_path, src.name))
                    if any(e.type in ("schema_violation", "malformed_content")
                           for e in out.evidence):
                        if out.verdict == "PASS":
                            out.verdict = "BLOCK"

            if entry.get("error"):
                out.add(Evidence(
                    type="malformed_content",
                    message=f"Asset {src.name}: registry entry recorded error: {entry['error']}",
                    file=str(src),
                ))

        if not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message=f"All {len(source_files)} design source(s) extracted + schema-valid",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
