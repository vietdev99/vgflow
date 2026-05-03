#!/usr/bin/env python3
"""Blueprint design preflight.

Runs before /vg:blueprint planning. If a phase appears to contain UI work, the
blueprint step must make design pixels available proactively instead of relying
on the operator to remember a separate /vg:design-scaffold call.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
from design_ref_resolver import parse_config_file  # noqa: E402

MOCKUP_EXTS = {
    ".pen",
    ".penboard",
    ".flow",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".fig",
    ".xml",
    ".pb",
}
FE_PATH_RE = re.compile(
    r"(apps/(admin|merchant|vendor|web)/|packages/ui/src/(components|theme)/|\.(tsx|jsx|vue|svelte)\b)",
    re.IGNORECASE,
)
UI_TEXT_RE = re.compile(
    r"\b(UI Components?|frontend|front-end|web app|screen|view|dashboard|modal|wizard|sidebar|topbar|app shell|layout)\b|giao diện",
    re.IGNORECASE,
)


def parse_config_array(config_path: Path, dotted: str) -> list[str]:
    if not config_path.exists() or "." not in dotted:
        return []
    top, field = dotted.split(".", 1)
    lines = config_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    values: list[str] = []
    in_top = False
    in_field = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(rf"^{re.escape(top)}:\s*$", line):
            in_top = True
            in_field = False
            continue
        if in_top and re.match(r"^[a-z_][a-z0-9_]*:", line):
            break
        if in_top and re.match(rf"^\s+{re.escape(field)}:\s*$", line):
            in_field = True
            continue
        m_inline = re.match(rf"^\s+{re.escape(field)}:\s*\[(.*?)\]\s*$", line)
        if in_top and m_inline:
            inner = m_inline.group(1).strip()
            return [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
        if in_field:
            m_item = re.match(r"^\s+-\s*(.*?)\s*$", line)
            if m_item:
                item = m_item.group(1).strip().strip("'\"")
                if item and not item.startswith("#"):
                    values.append(item)
                continue
            if not line.startswith(" "):
                break
            if re.match(r"^\s+[a-z_][a-z0-9_]*:", line):
                break
    return values


def phase_text_paths(phase_dir: Path) -> list[Path]:
    names = ["CONTEXT.md", "SCOPE.md", "SPECS.md", "SPEC.md", "ROADMAP.md", "SUMMARY.md"]
    paths = [phase_dir / name for name in names]
    paths.extend(sorted(phase_dir.glob("*PLAN*.md")))
    return [p for p in paths if p.exists()]


def detect_ui_phase(phase_dir: Path) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    for path in phase_text_paths(phase_dir):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if FE_PATH_RE.search(text):
            evidence.append(f"{path.name}: FE file path")
        elif UI_TEXT_RE.search(text):
            evidence.append(f"{path.name}: UI keyword")
    return bool(evidence), evidence


def is_mockup(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in MOCKUP_EXTS


def list_mockups(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if is_mockup(root) else []
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if is_mockup(p))


def expand_config_sources(repo_root: Path, config_path: Path) -> list[Path]:
    sources: list[Path] = []
    for raw in parse_config_array(config_path, "design_assets.paths"):
        pattern = Path(raw)
        pattern_str = str(pattern if pattern.is_absolute() else repo_root / pattern)
        matches = [Path(p) for p in glob.glob(pattern_str, recursive=True)]
        if matches:
            sources.extend(matches)
        else:
            sources.append(Path(pattern_str))
    for rel in ("designs", "design", "mockups", "ui-mockups", ".vg/designs", ".planning/designs"):
        sources.append(repo_root / rel)
    return sources


def collect_source_mockups(repo_root: Path, phase_dir: Path, config_path: Path) -> list[Path]:
    phase_design = (phase_dir / "design").resolve()
    phase_designs = (phase_dir / "designs").resolve()
    found: list[Path] = []
    seen: set[str] = set()
    for source in expand_config_sources(repo_root, config_path):
        for mockup in list_mockups(source):
            resolved = mockup.resolve()
            if phase_design in resolved.parents or phase_designs in resolved.parents:
                continue
            key = str(resolved)
            if key not in seen:
                seen.add(key)
                found.append(resolved)
    return found


def copy_mockups_to_phase(mockups: list[Path], phase_design_dir: Path) -> list[dict]:
    phase_design_dir.mkdir(parents=True, exist_ok=True)
    imported: list[dict] = []
    for src in mockups:
        dst = phase_design_dir / src.name
        if dst.exists() and dst.resolve() != src.resolve():
            stem, suffix = src.stem, src.suffix
            i = 2
            while dst.exists():
                dst = phase_design_dir / f"{stem}-{i}{suffix}"
                i += 1
        if dst.exists() and dst.resolve() == src.resolve():
            continue
        shutil.copy2(src, dst)
        imported.append({"from": str(src), "to": str(dst.resolve())})
    return imported


def manifest_stale(phase_design_dir: Path, mockups: list[Path]) -> bool:
    manifest = phase_design_dir / "manifest.json"
    if not manifest.exists():
        return bool(mockups)
    try:
        manifest_mtime = manifest.stat().st_mtime
    except OSError:
        return bool(mockups)
    return any(p.stat().st_mtime > manifest_mtime for p in mockups if p.exists())


def has_shared_or_legacy_manifest(repo_root: Path, config: dict[str, str]) -> bool:
    candidates = [
        config.get("design_assets.shared_dir"),
        config.get("design_assets.output_dir"),
        ".vg/design-system",
        ".vg/design-normalized",
        ".planning/design-normalized",
    ]
    for cand in candidates:
        if not cand:
            continue
        p = Path(cand)
        if not p.is_absolute():
            p = repo_root / p
        if (p / "manifest.json").exists():
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--config", default=".claude/vg.config.md")
    ap.add_argument("--apply", action="store_true", help="copy discovered raw mockups into PHASE_DIR/design")
    ap.add_argument("--output", default=None)
    ap.add_argument(
        "--allow-shared-mockup-reuse",
        action="store_true",
        help=(
            "Treat presence of shared/legacy manifest as proof of design coverage "
            "(v2.42.3+ default is strict: each phase needs per-phase mockups). "
            "Use ONLY when the phase legitimately reuses unchanged Phase 1 slugs "
            "(e.g., login form unchanged across milestones)."
        ),
    )
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    phase_dir = Path(args.phase_dir)
    if not phase_dir.is_absolute():
        phase_dir = (repo_root / phase_dir).resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    config = parse_config_file(config_path)

    phase_design_dir = phase_dir / "design"
    phase_raw_dir = phase_dir / "designs"
    has_ui, ui_evidence = detect_ui_phase(phase_dir)
    before_mockups = list_mockups(phase_design_dir) + list_mockups(phase_raw_dir)
    source_mockups = collect_source_mockups(repo_root, phase_dir, config_path)
    imported: list[dict] = []
    if has_ui and args.apply and not before_mockups and source_mockups:
        imported = copy_mockups_to_phase(source_mockups, phase_design_dir)

    phase_mockups = list_mockups(phase_design_dir) + list_mockups(phase_raw_dir)
    phase_manifest = phase_design_dir / "manifest.json"
    shared_manifest = has_shared_or_legacy_manifest(repo_root, config)

    # v2.42.3 — strict per-phase mockup requirement.
    # Pre-v2.42.3 logic let phases pass scaffold check whenever ANY shared/legacy
    # manifest existed (e.g. .vg/design-normalized/manifest.json from initial
    # Phase 1 design extract). That silent-passed every subsequent phase, so
    # builds shipped with AI-imagined UI even when phase had zero per-phase mockups.
    # New default: each UI phase needs its own per-phase mockups. Override with
    # --allow-shared-mockup-reuse for legitimate shared-slug reuse (e.g., login
    # form unchanged across milestones).
    if args.allow_shared_mockup_reuse and shared_manifest:
        needs_scaffold = has_ui and not phase_mockups and not shared_manifest
    else:
        needs_scaffold = has_ui and not phase_mockups
    needs_extract = has_ui and bool(phase_mockups) and (
        not phase_manifest.exists() or manifest_stale(phase_design_dir, phase_mockups)
    )

    result = {
        "phase_dir": str(phase_dir),
        "phase_design_dir": str(phase_design_dir),
        "has_ui": has_ui,
        "ui_evidence": ui_evidence,
        "phase_mockup_count": len(phase_mockups),
        "source_mockup_count": len(source_mockups),
        "source_mockups": [str(p) for p in source_mockups[:50]],
        "imported": imported,
        "imported_count": len(imported),
        "phase_manifest": str(phase_manifest),
        "phase_manifest_exists": phase_manifest.exists(),
        "shared_or_legacy_manifest_exists": shared_manifest,
        "needs_scaffold": needs_scaffold,
        "needs_extract": needs_extract,
        "verdict": "NEEDS_SCAFFOLD" if needs_scaffold else "PASS",
    }

    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        out = Path(args.output)
        if not out.is_absolute():
            out = repo_root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
