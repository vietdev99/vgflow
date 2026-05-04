"""
threshold-resolver.py — Phase 15 D-08 helper.

Resolve effective drift fidelity threshold for a phase. Used by:
  - verify-ui-structure.py (T3.6 wave-scoped drift, D-03/D-12b)
  - verify-holistic-drift.py (T3.7 holistic drift, D-12e)

Resolution order:
  1. Phase CONTEXT.md frontmatter `design_fidelity.threshold_override` (numeric, 0.0-1.0)
  2. Phase CONTEXT.md frontmatter `design_fidelity.profile` → vg.config.md
     `design_fidelity.thresholds.<profile>` mapping
  3. vg.config.md `design_fidelity.default_profile` mapping (default 'default')
  4. Hard fallback 0.85 + warning emit (for missing/malformed config)

Profile thresholds (per Phase 15 D-08 lock 2026-04-27):
  prototype: 0.70
  default:   0.85
  production: 0.95

CLI:
  python threshold-resolver.py --phase 7.14.3
  → prints resolved threshold to stdout (single float line, e.g. "0.85")
  → exit 0 always (helper never blocks; emits warning to stderr if fallback used)

Library API:
  from threshold_resolver import resolve_threshold
  result = resolve_threshold(phase="7.14.3")
  result.threshold  # float
  result.source     # "override" | "profile" | "default_profile" | "hard_fallback"
  result.profile    # str | None
  result.warning    # str | None
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HARD_FALLBACK_THRESHOLD = 0.85
HARD_FALLBACK_REASON = (
    "design_fidelity config missing or malformed; using built-in fallback 0.85. "
    "Add design_fidelity block to vg.config.md and design_fidelity.profile to "
    "phase CONTEXT.md frontmatter."
)


@dataclass
class ResolvedThreshold:
    threshold: float
    source: str       # "override" | "profile" | "default_profile" | "hard_fallback"
    profile: Optional[str] = None
    warning: Optional[str] = None


def _repo_root() -> Path:
    return Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def _read_text(p: Path) -> str:
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _extract_frontmatter(md: str) -> str:
    """Return YAML frontmatter content (between leading --- delimiters), else ''."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", md, re.DOTALL)
    return m.group(1) if m else ""


def _parse_design_fidelity_block(text: str) -> dict:
    """Lightweight parse of design_fidelity: section. Avoids yaml dependency.

    Recognizes:
      design_fidelity:
        profile: <str>
        threshold_override: <float>
        thresholds:
          prototype: <float>
          default:   <float>
          production: <float>
        default_profile: <str>
    Returns flat dict; missing keys absent.
    """
    out: dict = {}
    block_match = re.search(
        r"^design_fidelity:\s*\n((?:[ \t]+.*\n?)+)",
        text, re.MULTILINE,
    )
    if not block_match:
        return out
    body = block_match.group(1)

    def _scalar(key: str):
        m = re.search(rf"^\s+{re.escape(key)}:\s*[\"']?([^\"'\n#]+)[\"']?\s*(?:#.*)?$",
                      body, re.MULTILINE)
        if m:
            return m.group(1).strip()
        return None

    profile = _scalar("profile")
    if profile:
        out["profile"] = profile

    override_str = _scalar("threshold_override")
    if override_str:
        try:
            out["threshold_override"] = float(override_str)
        except ValueError:
            pass

    default_profile = _scalar("default_profile")
    if default_profile:
        out["default_profile"] = default_profile

    # thresholds: nested block — parse each numeric line under it
    thr_match = re.search(r"thresholds:\s*\n((?:[ \t]+.*\n?)+?)(?=^[ \t]{0,4}[a-z_]+:|\Z)",
                          body, re.MULTILINE)
    if thr_match:
        thr_body = thr_match.group(1)
        thresholds: dict = {}
        for m in re.finditer(r"^\s+([a-z_][a-z0-9_]*)\s*:\s*([0-9.]+)", thr_body, re.MULTILINE):
            try:
                thresholds[m.group(1)] = float(m.group(2))
            except ValueError:
                continue
        if thresholds:
            out["thresholds"] = thresholds

    return out


def _find_context_md(phase: str) -> Optional[Path]:
    repo = _repo_root()
    phases_dir = repo / ".vg" / "phases"
    if not phases_dir.exists() or not phase:
        return None
    # exact-then-prefix match (mirrors find_phase_dir behavior)
    for candidate in sorted(phases_dir.iterdir()):
        if not candidate.is_dir():
            continue
        name = candidate.name
        if name == phase or name.startswith(f"{phase}-") or name == phase.zfill(2):
            ctx = candidate / "CONTEXT.md"
            if ctx.exists():
                return ctx
    return None


def _find_vg_config() -> Optional[Path]:
    repo = _repo_root()
    for candidate in [
        repo / ".claude" / "vg.config.md",        # installed project
        repo / "vg.config.md",                    # alt layout
        repo / "vg.config.template.md",           # vgflow-repo dev
    ]:
        if candidate.exists():
            return candidate
    return None


def resolve_threshold(phase: str) -> ResolvedThreshold:
    """Resolve effective drift fidelity threshold per D-08 order."""
    config_text = _read_text(_find_vg_config()) if _find_vg_config() else ""
    config_fidelity = _parse_design_fidelity_block(config_text)

    context_text = _read_text(_find_context_md(phase)) if phase else ""
    context_fidelity = _parse_design_fidelity_block(_extract_frontmatter(context_text))

    # 1. inline override on phase CONTEXT
    override = context_fidelity.get("threshold_override")
    if isinstance(override, (int, float)):
        if config_text and not _config_allows_override(config_text):
            return ResolvedThreshold(
                threshold=float(override), source="override",
                profile=context_fidelity.get("profile"),
                warning=("threshold_override applied despite vg.config.md "
                         "design_fidelity.threshold_override_allowed=false"),
            )
        return ResolvedThreshold(
            threshold=float(override), source="override",
            profile=context_fidelity.get("profile"),
        )

    thresholds = config_fidelity.get("thresholds") or {}

    # 2. profile mapping from CONTEXT
    profile = context_fidelity.get("profile")
    if profile and profile in thresholds:
        return ResolvedThreshold(
            threshold=float(thresholds[profile]), source="profile",
            profile=profile,
        )

    # 3. default_profile from config
    default_profile = config_fidelity.get("default_profile") or "default"
    if default_profile in thresholds:
        warning = None
        if not profile:
            warning = (f"phase CONTEXT missing design_fidelity.profile; "
                       f"falling back to vg.config default_profile='{default_profile}'")
        return ResolvedThreshold(
            threshold=float(thresholds[default_profile]),
            source="default_profile", profile=default_profile, warning=warning,
        )

    # 4. hard fallback
    return ResolvedThreshold(
        threshold=HARD_FALLBACK_THRESHOLD, source="hard_fallback",
        profile=None, warning=HARD_FALLBACK_REASON,
    )


def _config_allows_override(config_text: str) -> bool:
    m = re.search(
        r"^design_fidelity:\s*\n(?:[ \t]+.*\n)*?\s+threshold_override_allowed:\s*(true|false)",
        config_text, re.MULTILINE | re.IGNORECASE,
    )
    if not m:
        return True  # default permissive
    return m.group(1).lower() == "true"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    ap.add_argument("--phase", required=True)
    ap.add_argument("--verbose", action="store_true",
                    help="Print resolved source + warning to stderr")
    args = ap.parse_args(argv)

    result = resolve_threshold(args.phase)
    if args.verbose:
        print(f"source={result.source} profile={result.profile or '-'} "
              f"threshold={result.threshold}", file=sys.stderr)
    if result.warning:
        print(f"\033[33mthreshold-resolver: {result.warning}\033[0m", file=sys.stderr)
    print(result.threshold)
    return 0


if __name__ == "__main__":
    sys.exit(main())
