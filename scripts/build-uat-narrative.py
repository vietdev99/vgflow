#!/usr/bin/env python3
"""
build-uat-narrative.py — Phase 15 D-10 generator (auto-fired by /vg:accept step 4b).

Reads phase artifacts and emits ${PHASE_DIR}/UAT-NARRATIVE.md with structured
prompts per D-XX decision, G-XX goal, and design-ref binding.

Each prompt has 4 required fields per D-05 (entry, navigation, precondition,
expected_behavior) — or 6 for design-ref variant per D-07 (+ region,
+ screenshot_compare). All strings interpolated via {{uat_*}} keys from
narration-strings.yaml (D-18 strict reuse) — no hardcoded literals.

Sources (per D-06):
  - CONTEXT.md → decisions (D-XX) with title + rationale
  - TEST-GOALS.md / test-goals.v1.json → goals (G-XX) + interactive_controls
  - design-normalized/manifest.json (or slug-registry.json) → design-ref slugs
  - vg.config.md → environments.local port-role mapping + narration.locale
  - accounts seed file (configurable path) → role credentials

Usage: build-uat-narrative.py --phase 7.14.3 [--output <path>]
Output: writes ${PHASE_DIR}/UAT-NARRATIVE.md, prints summary to stdout
Exit:   0 on success, 1 on precondition error (missing template/strings/phase)

Note: this generator is INTENTIONALLY minimal — it produces the narrative
skeleton with best-effort source data extraction. Manual UAT-NARRATIVE-OVERRIDES.md
(if present in phase dir) is appended verbatim AFTER generated content for
human-curated additions.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


# ── Phase + path helpers ─────────────────────────────────────────────────

def find_phase_dir(phase: str) -> Optional[Path]:
    """Resolve phase id → phase directory under .vg/phases/. Mirrors
    validators/_common.find_phase_dir but inlined for script independence."""
    phases_dir = REPO_ROOT / ".vg" / "phases"
    if not phase or not phases_dir.exists():
        return None
    for cand in sorted(phases_dir.iterdir()):
        if not cand.is_dir():
            continue
        n = cand.name
        if n == phase or n.startswith(f"{phase}-") or n == phase.zfill(2):
            return cand
    return None


def _find_vg_config() -> Optional[Path]:
    for c in (REPO_ROOT / ".claude" / "vg.config.md",
              REPO_ROOT / "vg.config.md",
              REPO_ROOT / "vg.config.template.md"):
        if c.exists():
            return c
    return None


def _find_narration_strings() -> Optional[Path]:
    for c in (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "narration-strings.yaml",
              REPO_ROOT / "commands" / "vg" / "_shared" / "narration-strings.yaml"):
        if c.exists():
            return c
    return None


def _find_template(name: str) -> Optional[Path]:
    for c in (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "templates" / name,
              REPO_ROOT / "commands" / "vg" / "_shared" / "templates" / name):
        if c.exists():
            return c
    return None


# ── narration-strings.yaml (lightweight parse) ──────────────────────────

def load_narration(locale: str = "vi") -> dict[str, str]:
    """Returns {key: rendered_string_for_locale}. Fallback to 'en' if locale
    missing. Empty dict if file missing — caller should warn."""
    path = _find_narration_strings()
    if not path:
        return {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    out: dict[str, str] = {}
    current_key: Optional[str] = None
    current_body: dict[str, str] = {}

    def flush():
        nonlocal current_key, current_body
        if current_key:
            val = current_body.get(locale) or current_body.get("en") or ""
            out[current_key] = val
        current_key = None
        current_body = {}

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m_key = re.match(r"^([a-z_][a-z0-9_]*)\s*:\s*$", line)
        if m_key:
            flush()
            current_key = m_key.group(1)
            continue
        m_loc = re.match(r"^\s+([a-z]{2})\s*:\s*[\"']?(.+?)[\"']?\s*$", line)
        if m_loc and current_key:
            current_body[m_loc.group(1)] = m_loc.group(2)
    flush()
    return out


# ── vg.config.md (extract environments + accounts path + locale) ────────

def load_vg_config() -> dict:
    path = _find_vg_config()
    if not path:
        return {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    cfg: dict = {}

    # narration.locale
    m = re.search(
        r"^narration:\s*\n(?:[ \t]+.*\n)*?\s+locale:\s*[\"']?([a-z]{2})[\"']?",
        text, re.MULTILINE,
    )
    cfg["locale"] = m.group(1) if m else "vi"

    # environments.local — extract dev_command + base_url-ish fields per role
    env_block = re.search(
        r"^environments:\s*\n((?:[ \t]+.*\n?)+)", text, re.MULTILINE,
    )
    cfg["environments"] = {}
    if env_block:
        body = env_block.group(1)
        # local: subblock
        local_m = re.search(
            r"^\s+local:\s*\n((?:[ \t]{4,}.*\n?)+)", body, re.MULTILINE,
        )
        if local_m:
            local_body = local_m.group(1)
            cfg["environments"]["local"] = _parse_kv_block(local_body)

    # design_assets.output_dir + accounts seed candidate paths
    assets = re.search(
        r"^design_assets:\s*\n((?:[ \t]+.*\n?)+)", text, re.MULTILINE,
    )
    if assets:
        m = re.search(r"^\s+output_dir:\s*[\"']?([^\"'\n#]+)", assets.group(1),
                      re.MULTILINE)
        if m:
            cfg["design_output_dir"] = m.group(1).strip()

    # ports section if present (free-form key per role → port number)
    ports_m = re.search(
        r"^ports:\s*\n((?:[ \t]+.*\n?)+?)(?=^[a-z_]+:|\Z)",
        text, re.MULTILINE,
    )
    if ports_m:
        cfg["ports"] = _parse_kv_block(ports_m.group(1))

    return cfg


def _parse_kv_block(body: str) -> dict:
    out = {}
    for line in body.splitlines():
        m = re.match(r"^\s+([a-z_][a-z0-9_]*)\s*:\s*[\"']?([^\"'\n#]+?)[\"']?\s*$",
                     line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


# ── Port-role default mapping (per CLAUDE.md / RTB convention) ──────────

DEFAULT_PORT_ROLES = {
    "5173": "admin",
    "5174": "publisher",
    "5175": "advertiser",
    "5176": "demand_admin",
}


def derive_port_role_map(cfg: dict) -> dict[str, str]:
    """Returns {role: port}. Prefer config.ports; fall back to default."""
    if cfg.get("ports"):
        return {role: port for port, role in cfg["ports"].items()}
    return {role: port for port, role in DEFAULT_PORT_ROLES.items()}


# ── Accounts seed file lookup ───────────────────────────────────────────

ACCOUNT_SEED_CANDIDATES = (
    "apps/api/seed/accounts.json",
    "apps/api/seed/test-accounts.json",
    "prisma/seed/accounts.json",
    "seed/accounts.json",
    ".vg/seeds/accounts.json",
)


def load_accounts() -> dict[str, dict]:
    """Returns {role: {email, password, ...}} from first found seed file."""
    for cand in ACCOUNT_SEED_CANDIDATES:
        p = REPO_ROOT / cand
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            # data may be list or dict
            if isinstance(data, list):
                return {a.get("role", a.get("name", f"acct{i}")): a
                        for i, a in enumerate(data) if isinstance(a, dict)}
            if isinstance(data, dict):
                # Could be {role: {...}} OR {accounts: [...]}
                if "accounts" in data and isinstance(data["accounts"], list):
                    return {a.get("role", a.get("name", f"acct{i}")): a
                            for i, a in enumerate(data["accounts"])
                            if isinstance(a, dict)}
                return data
    return {}


# ── Phase artifacts (CONTEXT decisions + TEST-GOALS) ────────────────────

DECISION_HEADER_RE = re.compile(
    r"^##\s+(D-\d+(?:\.\d+)?)\s*:\s*(.+?)\s*$", re.MULTILINE,
)
GOAL_HEADER_RE = re.compile(
    r"^##\s+(G-\d+(?:\.\d+)?)\s*:\s*(.+?)\s*$", re.MULTILINE,
)


def parse_decisions(context_md: str) -> list[dict]:
    """Extract decisions from CONTEXT.md as list of {id, title, rationale_excerpt}."""
    out = []
    matches = list(DECISION_HEADER_RE.finditer(context_md))
    for i, m in enumerate(matches):
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(context_md)
        body = context_md[body_start:body_end].strip()
        # First non-empty paragraph as rationale excerpt (max 200 chars)
        first_para = next((p.strip() for p in body.split("\n\n") if p.strip()), "")
        excerpt = first_para[:200].rstrip() + ("…" if len(first_para) > 200 else "")
        out.append({"id": m.group(1), "title": m.group(2).strip(),
                    "rationale_excerpt": excerpt})
    return out


def parse_goals_from_md(test_goals_md: str) -> list[dict]:
    out = []
    matches = list(GOAL_HEADER_RE.finditer(test_goals_md))
    for i, m in enumerate(matches):
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(test_goals_md)
        body = test_goals_md[body_start:body_end].strip()
        first_para = next((p.strip() for p in body.split("\n\n") if p.strip()), "")
        excerpt = first_para[:200].rstrip() + ("…" if len(first_para) > 200 else "")
        out.append({"id": m.group(1), "title": m.group(2).strip(),
                    "title_excerpt": excerpt})
    return out


def parse_goals_from_json(test_goals_json: dict) -> list[dict]:
    out = []
    for g in test_goals_json.get("goals", []):
        if not isinstance(g, dict):
            continue
        out.append({
            "id": g.get("id", "G-?"),
            "title": g.get("title", g.get("name", "")),
            "acceptance_criteria": g.get("acceptance_criteria", []),
            "precondition": g.get("precondition"),
            "interactive_controls": g.get("interactive_controls", {}),
            "role": g.get("role"),
        })
    return out


def load_test_goals(phase_dir: Path) -> tuple[list[dict], dict]:
    """Returns (goals, ic_block_global). If JSON exists, use it; else parse MD."""
    json_path = phase_dir / "test-goals.v1.json"
    md_path = phase_dir / "TEST-GOALS.md"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            goals = parse_goals_from_json(data)
            ic = data.get("interactive_controls", {})
            return goals, ic
        except json.JSONDecodeError:
            pass
    if md_path.exists():
        text = md_path.read_text(encoding="utf-8", errors="ignore")
        # Try to extract embedded ```json``` block first
        m = re.search(r"```json\s*\n([\s\S]*?)\n```", text)
        if m:
            try:
                data = json.loads(m.group(1))
                return parse_goals_from_json(data), data.get("interactive_controls", {})
            except json.JSONDecodeError:
                pass
        return parse_goals_from_md(text), {}
    return [], {}


def load_design_refs(phase_dir: Path, design_output_dir: str) -> list[dict]:
    """Read slug-registry / manifest, also scan PLAN for <design-ref slug='...'/>."""
    out_dir = REPO_ROOT / design_output_dir
    refs: list[dict] = []
    for name in ("slug-registry.json", "manifest.json"):
        p = out_dir / name
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if "slugs" in data:
            for slug, entry in (data["slugs"] or {}).items():
                refs.append({"slug": slug, "screenshots": entry.get("screenshots", []),
                             "source_path": entry.get("source_path")})
        for asset in data.get("assets") or []:
            slug = asset.get("slug")
            if not slug:
                continue
            refs.append({"slug": slug, "screenshots": asset.get("screenshots", []),
                         "source_path": asset.get("path")})
        break
    return refs


# ── Template rendering ──────────────────────────────────────────────────

INTERP_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)?)\s*\}\}")


def render_template(template: str, narration: dict, vars_: dict) -> str:
    def repl(m):
        key = m.group(1)
        if key.startswith("var."):
            v = vars_.get(key[4:], "")
            return str(v) if v is not None else ""
        # narration uat_* key
        if key in narration:
            return narration[key]
        return f"⛔[unresolved:{key}]"
    return INTERP_RE.sub(repl, template)


# ── Main builder ────────────────────────────────────────────────────────

def build_prompt_vars(prompt_id: str, prompt_title: str, *,
                      entry_url: str, role: str, account: dict,
                      navigation: str, precondition: str,
                      expected: str,
                      design_ref_block: str = "") -> dict:
    return {
        "prompt_id": prompt_id,
        "prompt_title": prompt_title,
        "entry_url": entry_url,
        "role": role,
        "account_email": account.get("email", "(no-email-in-seed)"),
        "account_password": account.get("password", "(no-password-in-seed)"),
        "navigation_steps": navigation or "_(navigate per phase context)_",
        "precondition": precondition or "_(no specific precondition)_",
        "expected_behavior": expected or "_(see decision/goal description)_",
        "design_ref_block": design_ref_block,
    }


def render_design_ref_block(narration: dict, design_ref_template: str,
                            region: str, screenshot_path: str) -> str:
    return render_template(design_ref_template, narration, {
        "region": region or "_(region not specified)_",
        "screenshot_path": screenshot_path or "_(no screenshot)_",
    })


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--phase", required=True)
    ap.add_argument("--output", help="Override default ${PHASE_DIR}/UAT-NARRATIVE.md")
    ap.add_argument("--locale", help="Override narration.locale (default: from vg.config.md)")
    args = ap.parse_args()

    phase_dir = find_phase_dir(args.phase)
    if not phase_dir:
        print(f"⛔ Phase dir not found for {args.phase}", file=sys.stderr)
        return 1

    template_path = _find_template("uat-narrative-prompt.md.tmpl")
    design_block_template_path = _find_template("uat-narrative-design-ref-block.md.tmpl")
    if not template_path:
        print("⛔ Template uat-narrative-prompt.md.tmpl not found in templates/",
              file=sys.stderr)
        return 1

    template = template_path.read_text(encoding="utf-8")
    design_block_template = (design_block_template_path.read_text(encoding="utf-8")
                              if design_block_template_path else "")

    cfg = load_vg_config()
    locale = args.locale or cfg.get("locale", "vi")
    narration = load_narration(locale)
    if not narration:
        print(f"⚠ narration-strings.yaml not found / empty — uat_* keys will fail to interpolate",
              file=sys.stderr)

    accounts = load_accounts()
    role_to_port = derive_port_role_map(cfg)
    base_url = "http://localhost"  # default; can be overridden by env config

    # Source data
    context_md = (phase_dir / "CONTEXT.md").read_text(encoding="utf-8", errors="ignore") \
        if (phase_dir / "CONTEXT.md").exists() else ""
    decisions = parse_decisions(context_md)
    goals, ic_global = load_test_goals(phase_dir)
    design_refs = load_design_refs(phase_dir, cfg.get("design_output_dir",
                                                       ".planning/design-normalized"))

    # Default account/role pick: first available
    default_role = next(iter(role_to_port.keys()), "admin")
    default_account = accounts.get(default_role, {})

    rendered_blocks: list[str] = []

    # Decisions
    for d in decisions:
        port = role_to_port.get(default_role, "5173")
        vars_ = build_prompt_vars(
            prompt_id=d["id"],
            prompt_title=d["title"],
            entry_url=f"{base_url}:{port}",
            role=default_role,
            account=default_account,
            navigation="_(per decision context — confirm path in CONTEXT.md or app shell)_",
            precondition="_(see decision rationale)_",
            expected=d["rationale_excerpt"] or "_(see CONTEXT.md for full rationale)_",
        )
        rendered_blocks.append(render_template(template, narration, vars_))

    # Goals
    for g in goals:
        role = g.get("role") or default_role
        port = role_to_port.get(role, role_to_port.get(default_role, "5173"))
        account = accounts.get(role, default_account)
        ic = g.get("interactive_controls") or {}
        nav = ic.get("entry_path") if isinstance(ic, dict) else None
        vars_ = build_prompt_vars(
            prompt_id=g["id"],
            prompt_title=g.get("title") or g.get("title_excerpt") or "(no title)",
            entry_url=f"{base_url}:{port}{nav or ''}",
            role=role,
            account=account,
            navigation=nav or "_(per goal description)_",
            precondition=g.get("precondition") or "_(no specific precondition declared)_",
            expected=", ".join(g.get("acceptance_criteria") or [])[:300]
                      or g.get("title_excerpt", "_(see goal description)_"),
        )
        rendered_blocks.append(render_template(template, narration, vars_))

    # Design refs
    for dr in design_refs:
        port = role_to_port.get(default_role, "5173")
        screenshot = (dr.get("screenshots") or [None])[0] or ""
        design_block_rendered = render_design_ref_block(
            narration, design_block_template,
            region="_(specify focus region from design source)_",
            screenshot_path=screenshot,
        ) if design_block_template else ""
        vars_ = build_prompt_vars(
            prompt_id=f"design-ref: {dr['slug']}",
            prompt_title=f"Design fidelity check — {dr['slug']}",
            entry_url=f"{base_url}:{port}",
            role=default_role,
            account=default_account,
            navigation="_(navigate to view shown in screenshot)_",
            precondition="_(default seed state OK; no special precondition)_",
            expected="_(rendered UI structurally matches reference screenshot per profile threshold)_",
            design_ref_block=design_block_rendered,
        )
        rendered_blocks.append(render_template(template, narration, vars_))

    # Assemble document
    header = (
        f"# UAT Narrative — phase {args.phase}\n\n"
        f"**Generated:** {__import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  \n"
        f"**Locale:** {locale}  \n"
        f"**Prompts:** {len(rendered_blocks)} "
        f"({len(decisions)} decisions, {len(goals)} goals, {len(design_refs)} design-refs)\n\n"
        f"> Auto-generated by `/vg:accept` step 4b (Phase 15 D-10). All strings\n"
        f"> resolved via `narration-strings.yaml` per D-18 strict reuse policy.\n"
        f"> For human additions, create `UAT-NARRATIVE-OVERRIDES.md` in this phase\n"
        f"> directory — it will be appended below.\n\n"
        f"---\n\n"
    )

    body = "\n".join(rendered_blocks) if rendered_blocks else \
        "_(No decisions, goals, or design-refs found. UAT narrative empty.)_\n"

    # Append overrides if present
    overrides_path = phase_dir / "UAT-NARRATIVE-OVERRIDES.md"
    overrides = ""
    if overrides_path.exists():
        overrides = (
            f"\n---\n\n## Manual additions (from UAT-NARRATIVE-OVERRIDES.md)\n\n"
            + overrides_path.read_text(encoding="utf-8", errors="ignore")
        )

    output_path = Path(args.output) if args.output else phase_dir / "UAT-NARRATIVE.md"
    output_path.write_text(header + body + overrides, encoding="utf-8")

    print(f"✓ UAT-NARRATIVE.md written: {output_path}")
    print(f"  Prompts: {len(rendered_blocks)}")
    print(f"    decisions:    {len(decisions)}")
    print(f"    goals:        {len(goals)}")
    print(f"    design-refs:  {len(design_refs)}")
    if overrides:
        print(f"  Manual overrides appended from UAT-NARRATIVE-OVERRIDES.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
