#!/usr/bin/env python3
"""
expand-test-goals-from-crud-surfaces.py — v2.36.0 closes #49.

Reads CRUD-SURFACES.md, enumerates per-resource × per-operation × per-role
× per-variant goals, dedupes against existing TEST-GOALS.md, emits
TEST-GOALS-EXPANDED.md with G-CRUD-* stubs.

Why this exists (#49):
  Blueprint generates TEST-GOALS.md at high-level (~67 goals for typical
  phase). CRUD-SURFACES.md declares ~200-300 verification points
  (operations × roles × filters × sorts × pages × states × row-actions
  × bulk-actions). Test layer cannot verify what blueprint never declared.

This is the planner-time complement to v2.34's runtime-time
TEST-GOALS-DISCOVERED.md. Together: 3-source goal layer.

  TEST-GOALS.md             ← manual high-level (blueprint primary)
  TEST-GOALS-EXPANDED.md    ← from CRUD-SURFACES variants (this script)
  TEST-GOALS-DISCOVERED.md  ← from runtime UI scans (v2.34)

Usage:
  expand-test-goals-from-crud-surfaces.py --phase-dir <path>
  expand-test-goals-from-crud-surfaces.py --phase-dir <path> --json
  expand-test-goals-from-crud-surfaces.py --phase-dir <path> --include-non-ui  # also emit api/data goals

Exit codes:
  0 — TEST-GOALS-EXPANDED.md written (or no resources to expand)
  1 — config/IO error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:50] or "x"


def load_crud_surfaces(phase_dir: Path) -> dict:
    p = phase_dir / "CRUD-SURFACES.md"
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"```json\s*\n(.+?)\n```", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def load_existing_goal_ids(phase_dir: Path) -> set[str]:
    ids: set[str] = set()
    for fname in ("TEST-GOALS.md", "TEST-GOALS-DISCOVERED.md"):
        p = phase_dir / fname
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"\bG-[A-Z0-9-_]+\b", text):
            ids.add(m.group(0))
    return ids


def expected_status(role: str, operation: str, scope: str, expected: dict) -> str:
    role_block = expected.get(role) or {}
    if isinstance(role_block, dict):
        v = role_block.get(operation)
        if v:
            return str(v)

    if role == "anon" and operation in {"create", "update", "delete"}:
        return "401"
    if role == "anon" and operation in {"list", "detail"}:
        return "401"
    if role == "user" and operation in {"create", "update", "delete"} and scope == "global":
        return "403"
    if role == "user" and scope == "owner-only":
        return "200 (owner-filtered)"
    return "200"


def goal_create_op(resource: dict, role: str, operation: str) -> dict:
    name = resource["name"]
    scope = resource.get("scope", "global")
    expected = resource.get("expected_behavior") or {}
    status = expected_status(role, operation, scope, expected)
    is_mutation = operation in {"create", "update", "delete"}

    return {
        "id": f"G-CRUD-{slug(name)}-{operation}-{role}",
        "title": f"{role} performs {operation} on {name} — expected {status}",
        "priority": "critical" if is_mutation else "important",
        "surface": "ui",
        "source": "blueprint.crud_surfaces_expansion",
        "maps_to_resource": name,
        "maps_to_role": role,
        "operation": operation,
        "scope": scope,
        "expected_status": status,
        "trigger": f"As {role}, attempt {operation} on {name}",
        "main_steps": [
            {"S1": f"Login as {role} (or unauthenticated for anon)"},
            {"S2": f"Navigate to {operation} surface for {name}"},
            {"S3": f"Trigger {operation} via UI affordance OR direct API"},
            {"S4": f"Verify response: {status}"},
            {"S5": f"If allowed: verify persistence (re-Read). If denied: verify state unchanged."},
        ],
    }


def goal_filter(resource: dict, role: str, filter_name: str) -> dict:
    name = resource["name"]
    return {
        "id": f"G-CRUD-{slug(name)}-list-{role}-filter-{slug(filter_name)}",
        "title": f"{role} filters {name} list by '{filter_name}', filter persists in URL",
        "priority": "important",
        "surface": "ui",
        "source": "blueprint.crud_surfaces_expansion",
        "maps_to_resource": name,
        "maps_to_role": role,
        "operation": "list",
        "variant": f"filter:{filter_name}",
        "trigger": f"Open {name} list, apply filter '{filter_name}'",
        "main_steps": [
            {"S1": f"List loads with default rows"},
            {"S2": f"Click filter '{filter_name}', select a value"},
            {"S3": f"URL updates to include filter param"},
            {"S4": f"List filters to matching rows"},
            {"S5": f"Refresh — filter persists from URL param (deep-link)"},
        ],
    }


def goal_sort(resource: dict, role: str, column: str) -> dict:
    name = resource["name"]
    return {
        "id": f"G-CRUD-{slug(name)}-list-{role}-sort-{slug(column)}",
        "title": f"{role} sorts {name} list by '{column}', sort persists in URL",
        "priority": "important",
        "surface": "ui",
        "source": "blueprint.crud_surfaces_expansion",
        "maps_to_resource": name,
        "maps_to_role": role,
        "operation": "list",
        "variant": f"sort:{column}",
        "trigger": f"Click column header '{column}' on {name} list",
        "main_steps": [
            {"S1": f"List loads"},
            {"S2": f"Click column header '{column}'"},
            {"S3": f"URL updates with sort param"},
            {"S4": f"Click again — direction toggles (asc → desc)"},
            {"S5": f"Refresh — sort persists from URL"},
        ],
    }


def goal_pagination(resource: dict, role: str) -> dict:
    name = resource["name"]
    return {
        "id": f"G-CRUD-{slug(name)}-list-{role}-paging",
        "title": f"{role} paginates {name} list, page state persists in URL",
        "priority": "important",
        "surface": "ui",
        "source": "blueprint.crud_surfaces_expansion",
        "maps_to_resource": name,
        "maps_to_role": role,
        "operation": "list",
        "variant": "pagination",
        "trigger": f"On {name} list, navigate to next page",
        "main_steps": [
            {"S1": f"List loads page 1"},
            {"S2": f"Click next-page or page=2 link"},
            {"S3": f"URL updates with page param"},
            {"S4": f"Refresh URL → page 2 loads directly (deep-link)"},
            {"S5": f"Browser back → returns to page 1"},
        ],
    }


def goal_state(resource: dict, role: str, state: str) -> dict:
    name = resource["name"]
    return {
        "id": f"G-CRUD-{slug(name)}-list-{role}-state-{slug(state)}",
        "title": f"{name} list renders '{state}' state correctly for {role}",
        "priority": "nice-to-have" if state in {"loading"} else "important",
        "surface": "ui",
        "source": "blueprint.crud_surfaces_expansion",
        "maps_to_resource": name,
        "maps_to_role": role,
        "variant": f"state:{state}",
        "trigger": f"Trigger '{state}' state on {name} list (manipulate API/data to induce)",
        "main_steps": [
            {"S1": f"Induce '{state}' condition (e.g. for empty: filter to no-match value; for error: stop API; for unauthorized: switch role)"},
            {"S2": f"List renders dedicated '{state}' UI (not generic blank or stack trace)"},
            {"S3": f"State has actionable affordance (retry button for error, clear-filter for zero_result, etc.)"},
        ],
    }


def goal_row_action(resource: dict, role: str, action: str) -> dict:
    name = resource["name"]
    return {
        "id": f"G-CRUD-{slug(name)}-row-{role}-{slug(action)}",
        "title": f"{role} executes row action '{action}' on {name}",
        "priority": "important",
        "surface": "ui",
        "source": "blueprint.crud_surfaces_expansion",
        "maps_to_resource": name,
        "maps_to_role": role,
        "variant": f"row_action:{action}",
        "trigger": f"As {role}, click row action '{action}' on a {name}",
        "main_steps": [
            {"S1": f"List shows ≥1 row"},
            {"S2": f"Click '{action}' on first row"},
            {"S3": f"Action invokes (modal opens / navigates / mutates)"},
            {"S4": f"Outcome reflects in UI"},
            {"S5": f"Other role gets denied or affordance hidden"},
        ],
    }


def goal_bulk_action(resource: dict, role: str, action: str) -> dict:
    name = resource["name"]
    return {
        "id": f"G-CRUD-{slug(name)}-bulk-{role}-{slug(action)}",
        "title": f"{role} executes bulk action '{action}' on {name}",
        "priority": "important",
        "surface": "ui",
        "source": "blueprint.crud_surfaces_expansion",
        "maps_to_resource": name,
        "maps_to_role": role,
        "variant": f"bulk_action:{action}",
        "trigger": f"As {role}, select N rows on {name} list, click bulk '{action}'",
        "main_steps": [
            {"S1": f"List shows ≥3 rows"},
            {"S2": f"Select all via checkbox-all or N individual checkboxes"},
            {"S3": f"Bulk action menu appears, click '{action}'"},
            {"S4": f"All N rows affected (verify count)"},
            {"S5": f"Partial failure handling — server returns 207/multi-status if applicable"},
        ],
    }


def expand(surfaces: dict, existing: set[str], include_non_ui: bool) -> list[dict]:
    out: list[dict] = []
    resources = surfaces.get("resources") or []
    for resource in resources:
        platforms = resource.get("platforms") or {}
        web = platforms.get("web") or {}
        list_block = web.get("list") or {}
        roles = (resource.get("base") or {}).get("roles") or ["admin"]
        operations = resource.get("operations") or []
        scope = resource.get("scope", "global")
        resource["scope"] = scope
        if "expected_behavior" not in resource:
            resource["expected_behavior"] = {}

        if not roles:
            continue

        for role in roles:
            for op in operations:
                out.append(goal_create_op(resource, role, op))

        for role in roles:
            data_controls = list_block.get("data_controls") or {}
            for f in data_controls.get("filters") or []:
                fname = f if isinstance(f, str) else f.get("name", "")
                if fname:
                    out.append(goal_filter(resource, role, fname))
            sort_block = data_controls.get("sort") or {}
            for col in sort_block.get("columns") or []:
                out.append(goal_sort(resource, role, col))
            if data_controls.get("pagination"):
                out.append(goal_pagination(resource, role))

            for state in list_block.get("states") or []:
                if state in {"loading", "empty", "zero_result", "error", "unauthorized", "offline"}:
                    out.append(goal_state(resource, role, state))

            table = list_block.get("table") or {}
            for ra in table.get("row_actions") or []:
                out.append(goal_row_action(resource, role, ra))
            for ba in table.get("bulk_actions") or []:
                out.append(goal_bulk_action(resource, role, ba))

    deduped: list[dict] = []
    seen_ids: set[str] = set()
    for g in out:
        if g["id"] in existing or g["id"] in seen_ids:
            continue
        seen_ids.add(g["id"])
        deduped.append(g)

    return deduped


def render_markdown(goals: list[dict], existing_count: int, resource_count: int) -> str:
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []
    lines.append("# TEST-GOALS-EXPANDED.md")
    lines.append("")
    lines.append(f"_Generated: {now} by `/vg:blueprint` Phase 2b6 (v2.36.0+)._")
    lines.append("")
    lines.append("Auto-emitted goal stubs from `CRUD-SURFACES.md` per resource × operation × role × variant. Closes issue #49.")
    lines.append("")
    lines.append("`/vg:test` codegen consumes 3 goal sources: `TEST-GOALS.md` (manual high-level), this file (planner expansion), and `TEST-GOALS-DISCOVERED.md` (runtime-discovered, v2.34).")
    lines.append("")
    lines.append("## Source")
    lines.append("")
    lines.append(f"- Existing goals (TEST-GOALS.md + DISCOVERED): **{existing_count}**")
    lines.append(f"- Resources expanded: **{resource_count}**")
    lines.append(f"- Auto-expanded goals: **{len(goals)}**")
    lines.append("")
    lines.append("## Triage")
    lines.append("")
    lines.append("- Promote useful G-CRUD-* goals → manual G-NN IDs in TEST-GOALS.md")
    lines.append("- Reject unrealistic ones → declare `CRUD-SURFACES.expansion_skip: [variant]`")
    lines.append("- Re-runnable: subsequent `/vg:blueprint` runs preserve manual additions, regenerate G-CRUD-*")
    lines.append("")
    lines.append("## Auto-expanded goals")
    lines.append("")

    for g in goals:
        lines.append("---")
        lines.append(f"id: {g['id']}")
        lines.append(f"title: \"{g['title']}\"")
        lines.append(f"priority: {g['priority']}")
        lines.append(f"surface: {g['surface']}")
        lines.append(f"source: {g['source']}")
        if g.get("maps_to_resource"):
            lines.append(f"maps_to_resource: {g['maps_to_resource']}")
        if g.get("maps_to_role"):
            lines.append(f"maps_to_role: {g['maps_to_role']}")
        if g.get("operation"):
            lines.append(f"operation: {g['operation']}")
        if g.get("variant"):
            lines.append(f"variant: \"{g['variant']}\"")
        if g.get("scope"):
            lines.append(f"scope: {g['scope']}")
        if g.get("expected_status"):
            lines.append(f"expected_status: \"{g['expected_status']}\"")
        lines.append(f"trigger: \"{g.get('trigger', '')}\"")
        lines.append("main_steps:")
        for step in g.get("main_steps") or []:
            for sk, sv in step.items():
                lines.append(f"  - {sk}: \"{sv}\"")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--include-non-ui", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"⛔ Phase dir not found: {phase_dir}", file=sys.stderr)
        return 1

    surfaces = load_crud_surfaces(phase_dir)
    resources = surfaces.get("resources") or []
    if not resources:
        if not args.quiet:
            print(f"  (no resources in CRUD-SURFACES.md — nothing to expand)")
        return 0

    existing = load_existing_goal_ids(phase_dir)
    goals = expand(surfaces, existing, args.include_non_ui)

    body = render_markdown(goals, len(existing), len(resources))
    out_path = phase_dir / "TEST-GOALS-EXPANDED.md"
    tmp = out_path.with_suffix(".md.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(out_path)

    if args.json:
        print(json.dumps({
            "out_path": str(out_path),
            "expanded_goals": len(goals),
            "resources": len(resources),
            "existing_goals": len(existing),
        }, indent=2))
    elif not args.quiet:
        print(f"✓ TEST-GOALS-EXPANDED.md written")
        print(f"  Resources: {len(resources)}")
        print(f"  Existing: {len(existing)} | Expanded: {len(goals)}")
        print(f"  Total goal layer: {len(existing) + len(goals)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
