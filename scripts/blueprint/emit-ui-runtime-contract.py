#!/usr/bin/env python3
"""
emit-ui-runtime-contract.py — v3.2.0 (#173 Stage 2)

Generator for ${PHASE_DIR}/UI-RUNTIME-CONTRACT.md + .json. Closes the
root cause Issue #173 dogfood exposed: UI-heavy phases passed
build/review with Tailwind token drift and missing Playwright lifecycle
specs because no contract listed the runtime invariants the design
demanded.

Sources (all optional; missing inputs degrade contract sections):
  - ${PHASE_DIR}/VIEW-COMPONENTS.md     → surface_name + slug rows
  - ${PHASE_DIR}/UI-SPEC/*.md           → verbatim markup grep for brand-/theme-/bg-brand-/text-brand-
  - ${PHASE_DIR}/ENV-CONTRACT.md        → target.base_url, auth host (best-effort YAML parse)
  - ${PHASE_DIR}/TEST-GOALS.md          → goal_type:mutation count → min_spec_count
  - ${PHASE_DIR}/PLAN*.md               → grep for routes ('/path' or `route: /path`)
  - ${PHASE_DIR}/.phase-profile         → skip when not web-fullstack/web-frontend-only

Skip conditions:
  - .phase-profile says backend-only / cli-tool / library          → exit 0 (no contract written)
  - PLAN has zero .tsx/.jsx/.vue/.svelte/.css references          → exit 0 (no contract written)
  - VIEW-COMPONENTS.md AND UI-SPEC/ both missing                  → write stub contract with skip_reason

Outputs:
  - ${PHASE_DIR}/UI-RUNTIME-CONTRACT.json  (canonical, schema-validated)
  - ${PHASE_DIR}/UI-RUNTIME-CONTRACT.md    (human-readable wrapper, embeds JSON in ```json fence)

Exit codes:
  0 — contract written (or skip path taken)
  2 — config error (e.g., phase dir missing)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Tailwind brand-token grep: captures brand-{name}, bg-brand-{shade}, text-brand-{shade},
# theme-{name}. Anchored to word boundaries so we don't pick up arbitrary substrings.
TAILWIND_BRAND_RE = re.compile(
    r"\b(?:bg-|text-|border-|ring-|fill-|stroke-)?(?:brand|theme)-[a-z0-9-]+",
    re.IGNORECASE,
)

# Markdown table row pattern for VIEW-COMPONENTS.md:
#   | Component | Type | Parent | Position (x,y,w,h%) | Children |
VIEW_COMPONENTS_ROW_RE = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|",
    re.MULTILINE,
)

# Slug header in VIEW-COMPONENTS.md: `## <slug>`
VIEW_COMPONENTS_SLUG_RE = re.compile(r"^##\s+([a-z0-9-_]+)\s*$", re.MULTILINE | re.IGNORECASE)

# Route discovery: routes in PLAN/SUMMARY text. Conservative — single-segment paths
# like `/sites`, `/users/:id`, etc. Skips URLs (http(s)://...) and code-block fences.
ROUTE_RE = re.compile(r"(?<![a-zA-Z0-9_/])(/[a-z][a-z0-9_-]*(?:/:?[a-z][a-z0-9_-]*)*)\b")

# Mutation-goal heuristic in TEST-GOALS.md. Matches several common forms:
#   **Goal type:** mutation   (colon inside bold)
#   **Goal type**: mutation   (colon outside bold)
#   Goal type: mutation       (plain)
#   goal_type: mutation       (YAML frontmatter / fenced metadata)
MUTATION_GOAL_RE = re.compile(
    r"(?:Goal\s+type[\s:\*]+|goal_type\s*:\s*)mutation\b",
    re.IGNORECASE,
)

WEB_PROFILES = {"web-fullstack", "web-frontend-only", "web-frontend", "web"}

FE_FILE_EXTS = (".tsx", ".jsx", ".vue", ".svelte", ".css", ".scss")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def detect_phase_profile(phase_dir: Path) -> str:
    """Return profile string from .phase-profile (YAML-ish), or ''."""
    profile_path = phase_dir / ".phase-profile"
    if not profile_path.is_file():
        return ""
    text = _read(profile_path)
    m = re.search(r"^\s*phase_profile\s*:\s*([a-z0-9-_]+)", text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip().lower() if m else ""


def count_fe_tasks(phase_dir: Path) -> int:
    """Count PLAN.md task lines referencing FE file extensions."""
    n = 0
    for p in sorted(phase_dir.glob("PLAN*.md")):
        text = _read(p)
        for ext in FE_FILE_EXTS:
            n += text.count(ext)
    return n


def extract_tailwind_tokens(phase_dir: Path) -> list[dict]:
    """Grep UI-SPEC/*.md + VIEW-COMPONENTS.md for brand/theme tokens.

    Returns deduplicated list, sorted by class_name. Each entry carries
    evidence_source (first source observed) + occurrences count.
    """
    found: dict[str, dict] = OrderedDict()

    def _scan(path: Path, label: str):
        text = _read(path)
        if not text:
            return
        for m in TAILWIND_BRAND_RE.finditer(text):
            cls = m.group(0)
            if cls.lower() not in found:
                found[cls.lower()] = {
                    "class_name": cls,
                    "evidence_source": label,
                    "occurrences": 1,
                }
            else:
                found[cls.lower()]["occurrences"] += 1

    _scan(phase_dir / "VIEW-COMPONENTS.md", "VIEW-COMPONENTS.md")
    ui_spec_dir = phase_dir / "UI-SPEC"
    if ui_spec_dir.is_dir():
        for p in sorted(ui_spec_dir.glob("*.md")):
            if p.name == "index.md":
                continue
            _scan(p, f"UI-SPEC/{p.name}")
    # Fallback: flat UI-SPEC.md (legacy pre-D1 phases)
    flat_ui_spec = phase_dir / "UI-SPEC.md"
    if flat_ui_spec.is_file() and not ui_spec_dir.is_dir():
        _scan(flat_ui_spec, "UI-SPEC.md")

    return sorted(found.values(), key=lambda x: x["class_name"].lower())


def extract_first_viewport_surfaces(phase_dir: Path) -> list[dict]:
    """Parse VIEW-COMPONENTS.md per-slug component tables.

    Picks first-viewport candidates: AppShell, Sidebar, TopBar, MainContent,
    Header, NavBar, Layout (case-insensitive name match against canonical
    layout class). Parent must be empty/null/root (root-level surface).
    """
    surfaces: list[dict] = []
    vc_path = phase_dir / "VIEW-COMPONENTS.md"
    text = _read(vc_path)
    if not text:
        return surfaces

    # Split text into per-slug sections via the `## <slug>` header.
    sections = []
    last_pos = 0
    last_slug = None
    for m in VIEW_COMPONENTS_SLUG_RE.finditer(text):
        if last_slug is not None:
            sections.append((last_slug, text[last_pos:m.start()]))
        last_slug = m.group(1)
        last_pos = m.end()
    if last_slug is not None:
        sections.append((last_slug, text[last_pos:]))

    layout_names = {"appshell", "sidebar", "topbar", "maincontent", "header", "navbar", "layout"}

    for slug, body in sections:
        for row in VIEW_COMPONENTS_ROW_RE.finditer(body):
            name, type_, parent, position, _children = (g.strip() for g in row.groups())
            if name.lower() in {"component", "---"}:  # header / separator rows
                continue
            if not name:
                continue
            if name.lower() not in layout_names:
                continue
            # Root-level surface only (parent empty or "null" or "(root)")
            if parent and parent.lower() not in {"", "null", "(root)", "—", "-"}:
                continue
            surfaces.append({
                "surface_name": name,
                "slug": slug,
                "expected_layout": position or None,
                "computed_style_assertions": [],
            })
    return surfaces


def extract_route_inventory(phase_dir: Path) -> list[dict]:
    """Grep PLAN*.md for route paths. Conservative — single-segment only."""
    routes: dict[str, dict] = OrderedDict()
    for p in sorted(phase_dir.glob("PLAN*.md")):
        text = _read(p)
        # Strip code fences to avoid false positives from URLs / shell commands
        text_no_code = re.sub(r"```.*?```", "", text, flags=re.S)
        for m in ROUTE_RE.finditer(text_no_code):
            path = m.group(1)
            # Filter obvious non-route paths (file paths with extensions, version specs)
            if any(seg.startswith(".") for seg in path.split("/")):
                continue
            if path.endswith((".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte", ".css", ".md", ".json", ".py", ".sh")):
                continue
            if path not in routes:
                routes[path] = {"path": path, "source": f"PLAN ({p.name})", "auth_required": True}
    return list(routes.values())


def parse_env_contract(phase_dir: Path) -> dict:
    """Best-effort YAML parse of ENV-CONTRACT.md ```yaml block.

    Returns dict with status + extracted scalars. Always returns status key.
    """
    out: dict = {
        "status": "missing",
        "base_url": None,
        "auth_host": None,
        "cookie_domain": None,
        "disposable_seed_data": None,
        "third_party_stubs_count": None,
    }
    env_path = phase_dir / "ENV-CONTRACT.md"
    if not env_path.is_file():
        return out
    text = _read(env_path)
    out["status"] = "present"
    # Try YAML codeblock first
    m = re.search(r"```yaml\s*\n(.+?)\n```", text, re.S)
    body = m.group(1) if m else text
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(body) or {}
    except Exception:
        data = {}

    # base_url under target.base_url
    target = data.get("target") if isinstance(data, dict) else None
    if isinstance(target, dict):
        out["base_url"] = target.get("base_url")
        out["auth_host"] = target.get("auth_host") or target.get("login_host")
        out["cookie_domain"] = target.get("cookie_domain")
    # disposable_seed_data may be a top-level boolean
    if isinstance(data, dict):
        if "disposable_seed_data" in data:
            out["disposable_seed_data"] = bool(data.get("disposable_seed_data"))
        stubs = data.get("third_party_stubs")
        if isinstance(stubs, list):
            out["third_party_stubs_count"] = len(stubs)
        elif isinstance(stubs, dict):
            out["third_party_stubs_count"] = len(stubs)

    # Regex fallback for scalars if YAML parse failed or fields missing
    if out["base_url"] is None:
        rm = re.search(r"^\s*base_url\s*:\s*['\"]?([^'\"\n]+)", body, re.MULTILINE)
        if rm:
            out["base_url"] = rm.group(1).strip()
    if out["auth_host"] is None:
        rm = re.search(r"^\s*auth_host\s*:\s*['\"]?([^'\"\n]+)", body, re.MULTILINE)
        if rm:
            out["auth_host"] = rm.group(1).strip()
    if out["cookie_domain"] is None:
        rm = re.search(r"^\s*cookie_domain\s*:\s*['\"]?([^'\"\n]+)", body, re.MULTILINE)
        if rm:
            out["cookie_domain"] = rm.group(1).strip()

    return out


def count_mutation_goals(phase_dir: Path) -> int:
    """Count goal_type:mutation entries in TEST-GOALS.md (flat) + TEST-GOALS/G-*.md."""
    n = 0
    flat = phase_dir / "TEST-GOALS.md"
    if flat.is_file():
        n += len(MUTATION_GOAL_RE.findall(_read(flat)))
    per_goal_dir = phase_dir / "TEST-GOALS"
    if per_goal_dir.is_dir():
        for p in per_goal_dir.glob("G-*.md"):
            n += len(MUTATION_GOAL_RE.findall(_read(p)))
    return n


def compose_acceptance_criteria(
    tokens: list[dict],
    surfaces: list[dict],
    routes: list[dict],
    env: dict,
    min_specs: int,
) -> list[str]:
    """Human-readable bullets summarizing the contract."""
    bullets: list[str] = []
    if tokens:
        bullets.append(
            f"Generated CSS at /vg:build close must contain {len(tokens)} brand/theme "
            f"token classes (grep evidence: {', '.join(t['class_name'] for t in tokens[:3])}"
            f"{', …' if len(tokens) > 3 else ''})."
        )
    else:
        bullets.append(
            "No brand/theme tokens detected in UI-SPEC + VIEW-COMPONENTS — Tailwind "
            "token gate will be skipped for this phase."
        )
    if surfaces:
        bullets.append(
            f"{len(surfaces)} first-viewport surface(s) ({', '.join(sorted({s['surface_name'] for s in surfaces}))}) "
            "must render with computed-style assertions verified during /vg:review."
        )
    if routes:
        bullets.append(
            f"{len(routes)} route(s) declared in PLAN. /vg:review hard-blocks if any "
            "discovered route is absent from this inventory."
        )
    if env["status"] == "present":
        auth_part = f"auth_host={env['auth_host']}" if env.get("auth_host") else "no auth_host declared"
        cookie_part = f"cookie_domain={env['cookie_domain']}" if env.get("cookie_domain") else "no cookie_domain declared"
        bullets.append(
            f"Env contract: base_url={env.get('base_url') or 'unset'}, {auth_part}, {cookie_part}. "
            "Review classifies auth/cookie/host failures as ENV_MISMATCH (Stage 1 #173 taxonomy)."
        )
    else:
        bullets.append("Env contract MISSING — env-host failures cannot be auto-classified as ENV_MISMATCH.")
    if min_specs > 0:
        bullets.append(
            f"At /vg:build close, ≥{min_specs} Playwright/lifecycle spec(s) must exist "
            f"(one per goal_type=mutation goal). Missing → matrix status TEST_SPEC_MISSING "
            f"and /vg:test-spec --regen path triggers before review can pass."
        )
    else:
        bullets.append("No mutation goals declared — Playwright lifecycle spec count gate skipped.")
    return bullets


def emit_markdown_wrapper(contract: dict) -> str:
    """Render the human-readable Markdown wrapper that embeds the JSON."""
    lines: list[str] = []
    lines.append(f"# UI Runtime Contract — Phase {contract.get('phase_id', '?')}")
    lines.append("")
    lines.append(f"**Generated:** {contract['generated_at']}")
    lines.append("**Schema:** schemas/ui-runtime-contract.v1.json")
    lines.append("**Source:** /vg:blueprint step 2b6d_ui_runtime_contract (#173 Stage 2)")
    lines.append("")
    if contract.get("skip_reason"):
        lines.append(f"> ⚠ **Stub contract** — `skip_reason`: {contract['skip_reason']}")
        lines.append("")
    lines.append("## Acceptance criteria")
    lines.append("")
    for bullet in contract["acceptance_criteria"]:
        lines.append(f"- {bullet}")
    lines.append("")
    lines.append("## Required Tailwind / brand tokens")
    lines.append("")
    if contract["required_tailwind_tokens"]:
        lines.append("| Class | Evidence | Occurrences |")
        lines.append("|---|---|---|")
        for t in contract["required_tailwind_tokens"]:
            lines.append(f"| `{t['class_name']}` | {t['evidence_source']} | {t['occurrences']} |")
    else:
        lines.append("(none detected — gate skipped)")
    lines.append("")
    lines.append("## First-viewport surfaces")
    lines.append("")
    if contract["first_viewport_surfaces"]:
        lines.append("| Surface | Slug | Expected layout |")
        lines.append("|---|---|---|")
        for s in contract["first_viewport_surfaces"]:
            lines.append(f"| {s['surface_name']} | {s['slug']} | {s.get('expected_layout') or '—'} |")
    else:
        lines.append("(no root-level layout surfaces detected in VIEW-COMPONENTS.md)")
    lines.append("")
    lines.append("## Route inventory")
    lines.append("")
    if contract["route_inventory"]:
        lines.append("| Path | Source | Auth required |")
        lines.append("|---|---|---|")
        for r in contract["route_inventory"]:
            lines.append(f"| `{r['path']}` | {r['source']} | {r.get('auth_required', True)} |")
    else:
        lines.append("(none — grep PLAN*.md found no route paths)")
    lines.append("")
    lines.append("## Env contract")
    lines.append("")
    env = contract["env_contract"]
    lines.append(f"- **status:** {env['status']}")
    lines.append(f"- **base_url:** `{env.get('base_url') or 'unset'}`")
    lines.append(f"- **auth_host:** `{env.get('auth_host') or 'unset'}`")
    lines.append(f"- **cookie_domain:** `{env.get('cookie_domain') or 'unset'}`")
    if env.get("disposable_seed_data") is not None:
        lines.append(f"- **disposable_seed_data:** {env['disposable_seed_data']}")
    if env.get("third_party_stubs_count") is not None:
        lines.append(f"- **third_party_stubs_count:** {env['third_party_stubs_count']}")
    lines.append("")
    lines.append("## Min spec count")
    lines.append("")
    msc = contract["min_spec_count"]
    lines.append(f"- **count:** {msc['count']}")
    lines.append(f"- **source:** {msc['source']}")
    lines.append("")
    lines.append("## Machine-readable contract")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(contract, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def build_contract(phase_dir: Path, phase_id: str) -> dict:
    """Assemble the contract dict from phase artifacts."""
    profile = detect_phase_profile(phase_dir)
    fe_tasks = count_fe_tasks(phase_dir)

    # Skip-stub logic: phase is genuinely non-UI
    if profile and profile not in WEB_PROFILES:
        return {
            "version": "1",
            "phase_id": phase_id,
            "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_artifacts": {},
            "required_tailwind_tokens": [],
            "first_viewport_surfaces": [],
            "route_inventory": [],
            "env_contract": {"status": "skipped"},
            "min_spec_count": {"count": 0, "source": "skipped (non-web profile)"},
            "acceptance_criteria": [
                f"Phase profile is '{profile}' — UI runtime contract not applicable."
            ],
            "skip_reason": f"phase_profile={profile} (non-web)",
        }

    if fe_tasks == 0:
        return {
            "version": "1",
            "phase_id": phase_id,
            "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_artifacts": {},
            "required_tailwind_tokens": [],
            "first_viewport_surfaces": [],
            "route_inventory": [],
            "env_contract": {"status": "skipped"},
            "min_spec_count": {"count": 0, "source": "skipped (no FE tasks)"},
            "acceptance_criteria": [
                "Phase has zero FE file references (.tsx/.jsx/.vue/.svelte/.css) in PLAN — UI runtime contract skipped."
            ],
            "skip_reason": "no FE tasks in PLAN*.md",
        }

    tokens = extract_tailwind_tokens(phase_dir)
    surfaces = extract_first_viewport_surfaces(phase_dir)
    routes = extract_route_inventory(phase_dir)
    env = parse_env_contract(phase_dir)
    mut_count = count_mutation_goals(phase_dir)
    min_specs = {
        "count": mut_count,
        "source": "TEST-GOALS.md goal_type:mutation count",
    }
    acceptance = compose_acceptance_criteria(tokens, surfaces, routes, env, mut_count)

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(REPO_ROOT))
        except ValueError:
            return str(p)

    return {
        "version": "1",
        "phase_id": phase_id,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_artifacts": {
            "view_components": _rel(phase_dir / "VIEW-COMPONENTS.md") if (phase_dir / "VIEW-COMPONENTS.md").exists() else None,
            "ui_spec_dir": _rel(phase_dir / "UI-SPEC") if (phase_dir / "UI-SPEC").is_dir() else None,
            "env_contract": _rel(phase_dir / "ENV-CONTRACT.md") if (phase_dir / "ENV-CONTRACT.md").exists() else None,
            "test_goals": _rel(phase_dir / "TEST-GOALS.md") if (phase_dir / "TEST-GOALS.md").exists() else None,
            "plan": ",".join(_rel(p) for p in sorted(phase_dir.glob("PLAN*.md"))) or None,
        },
        "required_tailwind_tokens": tokens,
        "first_viewport_surfaces": surfaces,
        "route_inventory": routes,
        "env_contract": env,
        "min_spec_count": min_specs,
        "acceptance_criteria": acceptance,
        "skip_reason": None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--phase-dir", help="Absolute path to phase directory.")
    g.add_argument("--phase", help="Phase number; resolved against dev-phases/ or .vg/phases/.")
    ap.add_argument("--json-only", action="store_true", help="Only write .json (skip .md wrapper).")
    ap.add_argument("--stdout", action="store_true", help="Print JSON to stdout instead of writing files.")
    args = ap.parse_args()

    if args.phase_dir:
        phase_dir = Path(args.phase_dir).resolve()
        phase_id = phase_dir.name
    else:
        # Best-effort phase lookup — tolerate missing phase
        candidates = list(REPO_ROOT.glob(f"dev-phases/{args.phase}*")) + list(REPO_ROOT.glob(f".vg/phases/{args.phase}*"))
        if not candidates:
            print(f"\033[38;5;208mNo phase dir found for phase={args.phase}\033[0m", file=sys.stderr)
            return 2
        phase_dir = candidates[0]
        phase_id = phase_dir.name

    if not phase_dir.is_dir():
        print(f"\033[38;5;208mPhase dir not found: {phase_dir}\033[0m", file=sys.stderr)
        return 2

    contract = build_contract(phase_dir, phase_id)

    if args.stdout:
        print(json.dumps(contract, indent=2, ensure_ascii=False))
        return 0

    json_path = phase_dir / "UI-RUNTIME-CONTRACT.json"
    json_path.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if not args.json_only:
        md_path = phase_dir / "UI-RUNTIME-CONTRACT.md"
        md_path.write_text(emit_markdown_wrapper(contract), encoding="utf-8")
        print(f"✓ UI-RUNTIME-CONTRACT.md written ({len(contract['required_tailwind_tokens'])} tokens, "
              f"{len(contract['first_viewport_surfaces'])} surfaces, {len(contract['route_inventory'])} routes)")
    else:
        print(f"✓ UI-RUNTIME-CONTRACT.json written (json-only mode)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
