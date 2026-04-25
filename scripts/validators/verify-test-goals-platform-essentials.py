#!/usr/bin/env python3
"""verify-test-goals-platform-essentials — platform-aware coverage gate.

PROBLEM (Phase 7.14.3 retrospective):
  TEST-GOALS.md generated for the campaigns table covered shell layout, column
  count, status icons, inline edit happy path. It MISSED:
    - filter row interactions (5 dropdowns + apply)
    - pagination (page next/prev, page size, deep-link state)
    - column visibility persistence Layer 4 (reload + state persist)
    - mutation 4-layer verification (toast text + API 2xx + console no-error
      + RELOAD + re-read + diff pre/post — the "ghost-save" guard)
    - state-machine guards (edit cell on non-active row should be DISABLED,
      not "open editor + 400 + revert")

  Each gap surfaced as a phantom bug at runtime: clicking a paused row's
  budget cell red-toasts, paged column visibility didn't survive reload, etc.
  Markdown rules in /vg:blueprint step 2b5 told the planner to "consider"
  these — AI lazy-read and skipped.

GATE:
  At /vg:blueprint step 2b5 (TEST-GOALS generation) + /vg:review step 1
  (code scan), assert that for every UI surface this phase touches, the
  TEST-GOALS frontmatter includes goals covering the platform's MANDATORY
  essentials. Missing → BLOCK with concrete fix-hint.

PLATFORMS COVERED:
  web-fullstack, web-frontend-only       — table/list/form essentials
  web-backend-only                        — API contract + 4-layer mutation
  mobile-rn, mobile-flutter, mobile-native — pull-to-refresh, infinite-scroll,
                                            tap-target-44px, deep-link
  desktop-electron, desktop-tauri         — context menu, keyboard shortcuts,
                                            window state persist
  cli-tool                                — exit-code, stderr, idempotency
  library                                  — public-api exports + types
  server-setup, server-management         — health-check, smoke deploy, rollback

INPUTS:
  --phase-dir         path to .vg/phases/{N}-{slug}/ (must contain SPECS.md
                      + TEST-GOALS.md)
  --config            path to .claude/vg.config.md (for profile/surfaces lookup)

OUTPUT:
  VG-contract JSON to stdout. Exit 0 = PASS, 1 = BLOCK, 2 = config error.
  Optional --report-md writes a human-readable gap analysis.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Platform-specific essentials registry. Extend as new platforms onboard.
# Each list is the MINIMUM coverage; phase-specific TEST-GOALS may add more.
# ---------------------------------------------------------------------------

PLATFORM_REGISTRY: dict[str, dict[str, list[str]]] = {
    # Modern web SPA / SSR — anything with React/Vue/Svelte/Solid + tables.
    "web-fullstack": {
        "table_or_list": [
            "filter-row-applies-server-query",
            "pagination-next-prev-deep-link",
            "pagination-page-size-persists",
            "column-count-and-order-locked",
            "default-sort-deterministic",
            "empty-state-when-no-data",
            "loading-state-while-fetching",
        ],
        "form_or_inline_edit": [
            "submit-success-toast-text-match",
            "submit-success-api-2xx-shape",
            "submit-success-console-no-error",
            "submit-success-RELOAD-state-persist",  # Layer 4 — anti ghost-save
            "submit-validation-error-toast-text",
            "submit-validation-error-cell-revert",
            "submit-state-guard-disabled-affordance",  # state-machine guard
        ],
        "navigation": [
            "sidebar-active-aria-current",
            "deep-link-survives-reload",
            "back-button-restores-state",
        ],
        "auth_protected_route": [
            "redirect-to-login-when-unauth",
            "preserves-returnUrl-after-login",
            "logout-clears-session-and-redirects",
        ],
    },
    "web-frontend-only": "alias:web-fullstack",
    "web-backend-only": {
        "endpoint_mutation": [
            "happy-path-2xx-with-expected-shape",
            "validation-error-4xx-with-message",
            "auth-error-401-when-no-token",
            "authz-error-403-when-wrong-role",
            "idempotency-replay-no-duplicate",  # critical for billing/auth
            "rate-limit-429-when-exceeded",
        ],
        "endpoint_read": [
            "happy-path-2xx-with-expected-shape",
            "auth-error-401-when-no-token",
            "pagination-via-page-and-limit",
            "filter-via-query-params",
            "sort-via-query-params",
        ],
    },
    "mobile-rn": {
        "list_screen": [
            "pull-to-refresh-fetches-fresh-data",
            "infinite-scroll-loads-next-page",
            "row-tap-navigates-to-detail",
            "tap-target-min-44px",
            "empty-state-when-no-data",
            "offline-cached-shows-stale-data",
        ],
        "form_or_inline_edit": [
            "submit-success-toast-or-banner",
            "submit-success-api-2xx-shape",
            "submit-validation-error-banner-text",
            "submit-success-RELOAD-state-persist",
            "submit-state-guard-disabled-affordance",
        ],
        "navigation": [
            "deep-link-opens-correct-screen",
            "back-gesture-pops-stack",
        ],
    },
    "mobile-flutter": "alias:mobile-rn",
    "mobile-native": "alias:mobile-rn",
    "desktop-electron": {
        "table_or_list": [
            "filter-row-applies-query",
            "pagination-or-virtual-scroll",
            "column-count-and-order-locked",
            "context-menu-right-click",
            "keyboard-shortcuts-documented",
        ],
        "form_or_inline_edit": [
            "submit-success-toast-text-match",
            "submit-success-RELOAD-state-persist",
            "submit-state-guard-disabled-affordance",
        ],
        "window_state": [
            "size-and-position-persist",
            "menu-bar-actions-fire-correctly",
        ],
    },
    "desktop-tauri": "alias:desktop-electron",
    "cli-tool": {
        "command": [
            "happy-path-exit-code-0",
            "error-path-non-zero-exit-with-stderr-message",
            "rerun-idempotent-no-side-effect-drift",
            "help-flag-prints-usage",
            "json-output-mode-when-piped",
        ],
    },
    "library": {
        "public_api": [
            "exports-match-package-json-types-field",
            "tree-shakeable-no-side-effects-on-import",
            "version-bump-matches-changeset",
        ],
    },
    "server-setup": {
        "infra_phase": [
            "health-check-200-after-deploy",
            "rollback-procedure-tested",
            "env-vars-documented",
            "smoke-test-after-restart",
        ],
    },
    "server-management": "alias:server-setup",
}


def resolve_platform(platform: str) -> dict[str, list[str]]:
    """Resolve aliases. Returns the underlying essentials map."""
    entry = PLATFORM_REGISTRY.get(platform)
    if entry is None:
        return {}
    if isinstance(entry, str) and entry.startswith("alias:"):
        return resolve_platform(entry.split(":", 1)[1])
    return entry  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Heuristic detection of which "categories" a phase touches.
# Read SPECS.md + scope CONTEXT.md to infer.
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "table_or_list": [
        "table", "list", "grid", "campaigns", "rows", "data table",
        "pagination", "filter", "sort",
    ],
    "form_or_inline_edit": [
        "edit", "form", "input", "field", "submit", "create", "update",
        "inline edit", "mutation",
    ],
    "navigation": [
        "sidebar", "nav", "menu", "route", "deep link", "breadcrumb",
    ],
    "auth_protected_route": [
        "login", "logout", "session", "auth", "protected", "permission",
    ],
    "endpoint_mutation": [
        "POST ", "PUT ", "PATCH ", "DELETE ", "endpoint write", "mutation api",
    ],
    "endpoint_read": [
        "GET ", "endpoint read", "list endpoint", "fetch", "query api",
    ],
    "list_screen": [
        "screen", "scroll list", "infinite scroll", "pull to refresh",
    ],
    "window_state": [
        "window", "menubar", "tray", "context menu", "shortcut",
    ],
    "command": [
        "command", "cli", "argv", "stdin", "stdout", "exit code",
    ],
    "public_api": [
        "export", "package", "library", "public api",
    ],
    "infra_phase": [
        "deploy", "infra", "ansible", "systemd", "pm2", "rollback",
        "health check", "vps", "server",
    ],
}


def detect_categories(specs_text: str, context_text: str) -> set[str]:
    """Heuristic: which categories does this phase touch?"""
    blob = (specs_text + "\n" + context_text).lower()
    out: set[str] = set()
    for cat, kws in CATEGORY_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in blob:
                out.add(cat)
                break
    return out


# ---------------------------------------------------------------------------
# Parse TEST-GOALS.md to extract listed goals.
# Format: numbered/bulleted goals with id `G-XX` + title.
# ---------------------------------------------------------------------------

GOAL_LINE = re.compile(r"^\s*[-*]?\s*\*?\*?G-(\d+)\*?\*?\s*[:.\-]\s*(.+)$",
                       re.IGNORECASE)
# Support both `## G-01: title` and `## Goal G-01: title (...)`.
GOAL_HEADING = re.compile(
    r"^#+\s+(?:Goal\s+)?G-(\d+)\b\s*[:.\-]?\s*(.*)$",
    re.IGNORECASE,
)


def parse_goals(text: str) -> list[tuple[str, str]]:
    """Return list of (goal_id, title) tuples."""
    goals: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        m = GOAL_LINE.match(line) or GOAL_HEADING.match(line)
        if not m:
            continue
        gid, title = f"G-{m.group(1).zfill(2)}", m.group(2).strip().lower()
        if gid in seen:
            continue
        seen.add(gid)
        goals.append((gid, title))
    return goals


# ---------------------------------------------------------------------------
# Match each essential to at least one goal.
# Uses keyword overlap heuristic — any goal title containing 2+ tokens of
# the essential name (split on `-`) counts as covering it.
# ---------------------------------------------------------------------------


def essential_tokens(essential: str) -> set[str]:
    return {t for t in re.split(r"[-_\s]+", essential.lower()) if len(t) >= 3}


def find_covering_goal(essential: str, goals: list[tuple[str, str]]) -> str | None:
    needed = essential_tokens(essential)
    if not needed:
        return None
    for gid, title in goals:
        title_tokens = set(re.split(r"[\s,.\-_/()]+", title.lower()))
        overlap = needed & title_tokens
        if len(overlap) >= max(2, len(needed) // 2):
            return gid
    return None


# ---------------------------------------------------------------------------
# Read project config to determine profile + surface for this phase.
# ---------------------------------------------------------------------------


PROFILE_RE = re.compile(r"^profile\s*:\s*[\"']?([^\"'\s#]+)", re.MULTILINE)
SURFACES_RE = re.compile(r"^surfaces\s*:", re.MULTILINE)
SURFACE_TYPE_RE = re.compile(
    r"^\s+([\w-]+):\s*\n(?:\s+#.*\n)*\s+type\s*:\s*[\"']?([^\"'\s#]+)",
    re.MULTILINE,
)


def read_project_profile(config_path: Path) -> str:
    if not config_path.exists():
        return "web-fullstack"
    text = config_path.read_text(encoding="utf-8")
    m = PROFILE_RE.search(text)
    return m.group(1) if m else "web-fullstack"


def read_phase_platform(specs_text: str, project_profile: str) -> str:
    """If SPECS declares `surface:` or `platform:`, prefer that. Otherwise
    fall back to project profile."""
    m = re.search(r"^(?:surface|platform)\s*:\s*[\"']?([\w-]+)",
                  specs_text, re.MULTILINE | re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return project_profile


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--phase-dir", required=True,
                    help="Phase directory (e.g. .vg/phases/7.14.3-...)")
    ap.add_argument("--config", default=".claude/vg.config.md")
    ap.add_argument("--report-md", default="")
    ap.add_argument("--strict", action="store_true",
                    help="Treat advisory categories as BLOCK too.")
    args = ap.parse_args(argv)

    started = time.monotonic()
    phase_dir = Path(args.phase_dir)
    if not phase_dir.is_dir():
        print(json.dumps({
            "validator": "test-goals-platform-essentials",
            "verdict": "BLOCK",
            "evidence": [{"type": "config-error",
                          "message": f"phase-dir not found: {phase_dir}"}],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "cache_key": None,
        }))
        return 2

    specs_path = phase_dir / "SPECS.md"
    test_goals_path = phase_dir / "TEST-GOALS.md"
    context_path = phase_dir / "CONTEXT.md"

    if not specs_path.exists() or not test_goals_path.exists():
        print(json.dumps({
            "validator": "test-goals-platform-essentials",
            "verdict": "BLOCK",
            "evidence": [{"type": "missing-artifact",
                          "message": (
                              f"Expected SPECS.md + TEST-GOALS.md in {phase_dir}; "
                              f"got SPECS={specs_path.exists()}, "
                              f"TEST-GOALS={test_goals_path.exists()}"
                          )}],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "cache_key": None,
        }))
        return 1

    specs_text = specs_path.read_text(encoding="utf-8", errors="ignore")
    test_goals_text = test_goals_path.read_text(encoding="utf-8", errors="ignore")
    context_text = context_path.read_text(encoding="utf-8", errors="ignore") \
        if context_path.exists() else ""

    project_profile = read_project_profile(Path(args.config))
    phase_platform = read_phase_platform(specs_text, project_profile)
    essentials_map = resolve_platform(phase_platform)
    if not essentials_map:
        print(json.dumps({
            "validator": "test-goals-platform-essentials",
            "verdict": "PASS",
            "evidence": [{"type": "unknown-platform",
                          "message": (
                              f"Platform '{phase_platform}' has no essentials "
                              f"registry — skipping. Add to PLATFORM_REGISTRY "
                              f"to enforce."
                          )}],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "cache_key": None,
            "stats": {"platform": phase_platform},
        }))
        return 0

    detected = detect_categories(specs_text, context_text)
    goals = parse_goals(test_goals_text)

    missing: list[dict[str, str]] = []
    covered: list[dict[str, str]] = []
    for cat, items in essentials_map.items():
        if cat not in detected:
            continue
        for essential in items:
            gid = find_covering_goal(essential, goals)
            if gid is None:
                missing.append({
                    "type": "missing-essential",
                    "platform": phase_platform,
                    "category": cat,
                    "essential": essential,
                    "message": (
                        f"Platform '{phase_platform}' category '{cat}' "
                        f"requires a TEST-GOAL covering "
                        f"'{essential}' but none of the {len(goals)} declared "
                        f"goals match."
                    ),
                    "fix_hint": (
                        f"Add a goal whose title mentions tokens of "
                        f"'{essential.replace('-', ' ')}'. Example: "
                        f"`G-NN: {essential.replace('-', ' ').title()} — "
                        f"<concrete acceptance criterion>`"
                    ),
                })
            else:
                covered.append({
                    "category": cat,
                    "essential": essential,
                    "covering_goal": gid,
                })

    verdict = "PASS" if not missing else "BLOCK"
    result = {
        "validator": "test-goals-platform-essentials",
        "verdict": verdict,
        "evidence": missing or [{
            "type": "summary",
            "message": (
                f"All {len(covered)} platform-mandatory essentials covered "
                f"by goals."
            ),
        }],
        "duration_ms": int((time.monotonic() - started) * 1000),
        "cache_key": None,
        "stats": {
            "platform": phase_platform,
            "project_profile": project_profile,
            "categories_detected": sorted(detected),
            "goals_parsed": len(goals),
            "essentials_required": sum(
                len(items) for cat, items in essentials_map.items()
                if cat in detected
            ),
            "essentials_covered": len(covered),
            "essentials_missing": len(missing),
        },
    }
    print(json.dumps(result))

    if args.report_md:
        lines = [
            f"# TEST-GOALS Platform-Essentials Audit — {phase_dir.name}",
            "",
            f"- Phase platform: **{phase_platform}**",
            f"- Project profile: **{project_profile}**",
            f"- Categories detected: {', '.join(sorted(detected)) or '(none)'}",
            f"- Goals declared: **{len(goals)}**",
            f"- Essentials required: **{result['stats']['essentials_required']}**",
            f"- Covered: **{len(covered)}**",
            f"- Missing: **{len(missing)}** {'(BLOCK)' if missing else '(PASS)'}",
            "",
        ]
        if missing:
            lines.append("## Missing")
            lines.append("")
            for m in missing:
                lines.append(
                    f"- `[{m['category']}] {m['essential']}` — {m['fix_hint']}"
                )
            lines.append("")
        if covered:
            lines.append("## Covered")
            lines.append("")
            for c in covered:
                lines.append(
                    f"- `[{c['category']}] {c['essential']}` → {c['covering_goal']}"
                )
        Path(args.report_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_md).write_text("\n".join(lines), encoding="utf-8")

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
