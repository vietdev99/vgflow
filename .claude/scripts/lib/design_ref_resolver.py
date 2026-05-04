#!/usr/bin/env python3
"""Shared design-ref resolution helpers for VG build/review gates.

The resolver is intentionally filesystem-first. A UI task that names a real
`<design-ref>` slug must receive concrete design bytes, regardless of whether
the project is on the v2.30 phase-local layout, the transitional `designs/`
scaffold folder, or the legacy project-level normalized directory.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")
NO_ASSET_RE = re.compile(r"^no-asset:(.{3,})$", re.IGNORECASE)
DESIGN_REF_RE = re.compile(r"<design-ref>([^<]+)</design-ref>", re.IGNORECASE)
DESIGN_REF_ATTR_RE = re.compile(
    r"<design-ref\b[^>]*\bslug\s*=\s*['\"]([^'\"]+)['\"][^>]*/?>",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DesignRefEntry:
    value: str
    kind: str  # slug | no_asset | descriptive


@dataclass(frozen=True)
class DesignRoot:
    path: Path
    tier: str


@dataclass(frozen=True)
class DesignAssets:
    slug: str
    screenshots: list[Path]
    structural: Path | None
    interactions: Path | None
    root: Path | None
    tier: str | None
    missing_candidates: list[Path]


def parse_config_file(config_path: Path | None) -> dict[str, str]:
    """Parse the simple vg.config.md subset used by design path lookup."""
    if not config_path or not config_path.exists():
        return {}
    text = config_path.read_text(encoding="utf-8", errors="ignore")
    if text.startswith("\ufeff"):
        text = text[1:]

    config: dict[str, str] = {}
    stack: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            m_section = re.match(r"^([a-z_][a-z0-9_]*):\s*$", line)
            if m_section:
                stack = [m_section.group(1)]
                continue
            m_value = _match_yaml_value(line)
            if m_value:
                key, value = m_value
                config[key] = value
                stack = []
            continue
        if stack:
            m_section = re.match(r"^\s+([a-z_][a-z0-9_]*):\s*$", line)
            if m_section:
                stack = [stack[0], m_section.group(1)]
                continue
            m_value = _match_yaml_value(line)
            if m_value:
                key, value = m_value
                config[".".join(stack + [key])] = value
    return config


def _match_yaml_value(line: str) -> tuple[str, str] | None:
    for pattern in (
        r'^\s*([a-z_][a-z0-9_]*):\s*"(.+?)"\s*(?:#.*)?$',
        r"^\s*([a-z_][a-z0-9_]*):\s*'(.+?)'\s*(?:#.*)?$",
        r"^\s*([a-z_][a-z0-9_]*):\s*(.+?)\s*(?:#.*)?$",
    ):
        m = re.match(pattern, line)
        if m:
            return m.group(1), m.group(2).strip()
    return None


def extract_design_ref_values(text: str) -> list[str]:
    """Return all design-ref raw values from content and slug-attribute forms."""
    values = [v.strip() for v in DESIGN_REF_RE.findall(text or "") if v.strip()]
    values.extend(v.strip() for v in DESIGN_REF_ATTR_RE.findall(text or "") if v.strip())
    return values


def classify_design_ref_values(raw_values: Iterable[str]) -> list[DesignRefEntry]:
    """Classify refs as real slugs, explicit no-asset gaps, or descriptors.

    Comma-separated refs are treated as multiple values. Whitespace splitting is
    retained only when every token is slug-like, preserving old PLAN fixtures
    without turning descriptive phrases like "Phase 7.13 pattern" into slugs.
    """
    entries: list[DesignRefEntry] = []
    for raw in raw_values:
        text = raw.strip()
        if not text:
            continue
        comma_parts = [p.strip() for p in text.split(",") if p.strip()]
        parts = comma_parts if len(comma_parts) > 1 else [text]
        for part in parts:
            if NO_ASSET_RE.match(part):
                entries.append(DesignRefEntry(part, "no_asset"))
            elif SLUG_RE.match(part):
                entries.append(DesignRefEntry(part, "slug"))
            else:
                tokens = [t.strip() for t in re.split(r"\s+", part) if t.strip()]
                if len(tokens) > 1 and all(SLUG_RE.match(t) for t in tokens):
                    entries.extend(DesignRefEntry(t, "slug") for t in tokens)
                else:
                    entries.append(DesignRefEntry(part, "descriptive"))
    return entries


def extract_design_ref_entries(text: str) -> list[DesignRefEntry]:
    return classify_design_ref_values(extract_design_ref_values(text))


def design_roots(
    repo_root: Path,
    *,
    phase_dir: Path | None = None,
    config: dict[str, str] | None = None,
    explicit_design_dir: Path | str | None = None,
) -> list[DesignRoot]:
    """Return candidate design roots in the canonical tier order."""
    repo_root = repo_root.resolve()
    config = config or {}
    roots: list[DesignRoot] = []
    seen: set[str] = set()

    def add(path: Path | str | None, tier: str) -> None:
        if not path:
            return
        p = Path(path)
        if not p.is_absolute():
            p = repo_root / p
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p.absolute())
        if key in seen:
            return
        seen.add(key)
        roots.append(DesignRoot(Path(key), tier))

    if phase_dir:
        phase = Path(phase_dir)
        if not phase.is_absolute():
            phase = repo_root / phase
        add(phase / "design", "phase")
        # Transitional scaffold layout from Phase 20 dogfood. Read-only alias.
        add(phase / "designs", "phase-legacy-designs")

    # Explicit design-dir from legacy CLIs is a hint, but phase-local roots win.
    add(explicit_design_dir, "explicit")

    shared = config.get("design_assets.shared_dir") or config.get("design_assets.output_dir")
    add(shared or ".vg/design-system", "shared")

    output_dir = config.get("design_assets.output_dir")
    if output_dir and output_dir != shared:
        add(output_dir, "legacy-config")
    add(".vg/design-normalized", "legacy")
    add(".planning/design-normalized", "legacy")
    return roots


def resolve_design_assets(
    slug: str,
    *,
    repo_root: Path,
    phase_dir: Path | None = None,
    config: dict[str, str] | None = None,
    explicit_design_dir: Path | str | None = None,
) -> DesignAssets:
    screenshots: list[Path] = []
    structural: Path | None = None
    interactions: Path | None = None
    root_hit: Path | None = None
    tier_hit: str | None = None
    missing_candidates: list[Path] = []

    for root in design_roots(
        repo_root,
        phase_dir=phase_dir,
        config=config,
        explicit_design_dir=explicit_design_dir,
    ):
        shots = _resolve_screenshots(root.path, slug)
        struct = _resolve_structural(root.path, slug)
        inter = _resolve_interactions(root.path, slug)
        if shots or struct or inter:
            screenshots = shots
            structural = struct
            interactions = inter
            root_hit = root.path
            tier_hit = root.tier
            break
        missing_candidates.extend(_missing_png_candidates(root.path, slug))

    return DesignAssets(
        slug=slug,
        screenshots=screenshots,
        structural=structural,
        interactions=interactions,
        root=root_hit,
        tier=tier_hit,
        missing_candidates=missing_candidates,
    )


def first_screenshot(assets: DesignAssets) -> Path | None:
    return assets.screenshots[0] if assets.screenshots else None


def _resolve_screenshots(root: Path, slug: str) -> list[Path]:
    candidates = [
        root / "screenshots" / f"{slug}.default.png",
        root / "screenshots" / f"{slug}.png",
        root / f"{slug}.default.png",
        root / f"{slug}.png",
    ]
    found: list[Path] = []
    for cand in candidates:
        if cand.exists() and cand.is_file() and cand not in found:
            found.append(cand.resolve())
    for folder in (root / "screenshots", root):
        if folder.exists():
            for variant in sorted(folder.glob(f"{slug}.*.png")):
                resolved = variant.resolve()
                if resolved not in found:
                    found.append(resolved)
    return found


def _resolve_structural(root: Path, slug: str) -> Path | None:
    for ext in ("html", "json", "xml"):
        for cand in (
            root / "refs" / f"{slug}.structural.{ext}",
            root / f"{slug}.structural.{ext}",
        ):
            if cand.exists() and cand.is_file():
                return cand.resolve()
    return None


def _resolve_interactions(root: Path, slug: str) -> Path | None:
    for cand in (root / "refs" / f"{slug}.interactions.md", root / f"{slug}.interactions.md"):
        if cand.exists() and cand.is_file():
            return cand.resolve()
    return None


def _missing_png_candidates(root: Path, slug: str) -> list[Path]:
    return [
        root / "screenshots" / f"{slug}.default.png",
        root / "screenshots" / f"{slug}.png",
        root / f"{slug}.png",
    ]
