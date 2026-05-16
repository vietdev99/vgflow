#!/usr/bin/env python3
"""
enrich-test-goals.py — v2.34.0 Phase 2c: review→test goal-enrichment back-flow.

The original /vg:review 4-step design:
  (1) Spawn Haiku/in-session Codex
  (2) Discover UI + draw map  ✓ writes to RUNTIME-MAP.json views[X].elements[]
  (3) Click many components   ✓ writes to scan-{view}.json
  (4) Enrich TEST-GOALS for test layer  ❌ MISSING — this script fills the gap

Reads scan-*.json + RUNTIME-MAP.json, classifies discovered elements
(actions/forms/modals/tables/tabs/menus), dedupes against existing
TEST-GOALS.md, emits TEST-GOALS-DISCOVERED.md with G-AUTO-* stubs.

Output schema mirrors TEST-GOAL-enriched-template.md so /vg:test codegen
can consume it identically.

Usage:
  enrich-test-goals.py --phase-dir .vg/phases/3
  enrich-test-goals.py --phase-dir <path> --json
  enrich-test-goals.py --phase-dir <path> --threshold 3   # min elements/view to require enrichment
  enrich-test-goals.py --phase-dir <path> --validate-only # exit 1 if enrichment incomplete

Exit codes:
  0 — TEST-GOALS-DISCOVERED.md written (or no enrichable elements found)
  1 — validate-only: enrichment incomplete (views with elements > threshold but no auto-goals)
  2 — config error
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


def view_slug(view_url: str) -> str:
    """Convert URL path to a goal-id-safe slug. /admin/topup-requests → admin-topup-requests"""
    s = view_url.strip("/").replace("/", "-")
    s = re.sub(r":[a-zA-Z_]+", "id", s)
    s = re.sub(r"[^a-zA-Z0-9-]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "root"


def name_slug(name: str) -> str:
    """Element name to slug. 'Add Site' → 'add-site'"""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "unnamed"


def load_existing_goals(phase_dir: Path) -> tuple[set[str], dict[str, list[str]]]:
    """Return (existing_goal_ids, declared_controls_per_view).
    declared_controls_per_view maps view→list of declared filter/sort/page names
    so we don't regenerate goals for things blueprint already specified.
    """
    tg_path = phase_dir / "TEST-GOALS.md"
    if not tg_path.is_file():
        return set(), {}

    text = tg_path.read_text(encoding="utf-8", errors="replace")
    ids: set[str] = set()
    declared: dict[str, list[str]] = {}

    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None  # type: ignore

    if yaml is not None:
        blocks: list[str] = []
        cur: list[str] = []
        in_block = False
        for line in text.splitlines():
            if line.strip() == "---":
                if in_block:
                    blocks.append("\n".join(cur))
                    cur = []
                    in_block = False
                else:
                    in_block = True
                continue
            if in_block:
                cur.append(line)
        for blob in blocks:
            try:
                data = yaml.safe_load(blob) or {}
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            gid = str(data.get("id", ""))
            if gid:
                ids.add(gid)
            ic = data.get("interactive_controls") or {}
            view_key = str(data.get("maps_to_view") or data.get("view") or "")
            if view_key and isinstance(ic, dict):
                names = []
                for f in ic.get("filters") or []:
                    if isinstance(f, dict) and "name" in f:
                        names.append(f"filter:{f['name']}")
                    elif isinstance(f, str):
                        names.append(f"filter:{f}")
                if ic.get("pagination"):
                    names.append("pagination")
                if ic.get("sort"):
                    names.append("sort")
                declared.setdefault(view_key, []).extend(names)

    if not ids:
        for m in re.finditer(r"\bG-[A-Z0-9-]+\b", text):
            ids.add(m.group(0))

    return ids, declared


def load_runtime_map(phase_dir: Path) -> dict:
    rm = phase_dir / "RUNTIME-MAP.json"
    if not rm.is_file():
        return {}
    try:
        return json.loads(rm.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_scans(phase_dir: Path) -> dict[str, dict]:
    """Load every scan-*.json under phase_dir. Returns {view_url: scan_data}."""
    scans: dict[str, dict] = {}
    for scan_file in phase_dir.glob("scan-*.json"):
        try:
            data = json.loads(scan_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        view = data.get("view")
        if view:
            scans[view] = data
    return scans


def classify_elements(view: str, scan: dict, runtime_view: dict,
                      declared_controls: list[str]) -> list[dict]:
    """Map raw scan output into goal stub dicts."""
    stubs: list[dict] = []
    vslug = view_slug(view)
    declared_set = set(declared_controls)

    seen_modal_triggers: set[str] = set()

    for r in scan.get("results", []):
        if r.get("outcome") == "modal_opened":
            name = r.get("name") or "unnamed"
            key = name_slug(name)
            if key in seen_modal_triggers:
                continue
            seen_modal_triggers.add(key)
            stubs.append({
                "id": f"G-AUTO-{vslug}-modal-{key}",
                "title": f"Modal '{name}' opens and closes correctly on {view}",
                "priority": "important",
                "surface": "ui",
                "source": "review.runtime_discovery",
                "evidence": {"scan_ref": r.get("ref"), "view": view},
                "trigger": f"Click '{name}' on {view}",
                "main_steps": [
                    {"S1": f"User on {view} as authenticated role"},
                    {"S2": f"Click element '{name}' (ref={r.get('ref')})"},
                    {"S3": "Modal renders with form/content visible"},
                    {"S4": "Close via cancel/X — modal dismissed, parent state unchanged"},
                ],
                "alternate_flows": [
                    {"name": "esc_close", "trigger": "Press Escape", "expected": "Modal dismisses, focus returns to trigger"},
                ],
            })

    for r in scan.get("results", []):
        for net in r.get("network") or []:
            method = net.get("method", "GET").upper()
            if method in ("POST", "PUT", "PATCH", "DELETE"):
                name = r.get("name") or "unnamed"
                key = name_slug(name)
                stubs.append({
                    "id": f"G-AUTO-{vslug}-mutation-{key}-{method.lower()}",
                    "title": f"{method} mutation triggered by '{name}' persists on {view}",
                    "priority": "critical",
                    "surface": "ui",
                    "source": "review.runtime_discovery",
                    "evidence": {
                        "scan_ref": r.get("ref"),
                        "view": view,
                        "endpoint": f"{method} {net.get('url')}",
                        "observed_status": net.get("status"),
                    },
                    "trigger": f"Click '{name}' on {view} (sends {method} {net.get('url')})",
                    "main_steps": [
                        {"S1": f"User on {view} as authenticated role"},
                        {"S2": f"Trigger '{name}' (observed during review: {method} {net.get('url')} → {net.get('status')})"},
                        {"S3": "API responds 2xx and UI reflects new state"},
                        {"S4": "Refresh — change persists (read-after-write check)"},
                    ],
                    "alternate_flows": [
                        {"name": "validation_fail", "trigger": "invalid input", "expected": "4xx response, inline error shown, no DB write"},
                        {"name": "auth_denied", "trigger": "anonymous or wrong role", "expected": "401/403, no state change"},
                    ],
                    "postcondition": [
                        f"persistent state change on resource targeted by {method} {net.get('url')}",
                    ],
                })
                break

    # B63: cross-view propagation → feature_chain goals.
    # For each observed_in_target=yes|partial entry, emit a feature_chain
    # goal with chain_steps stub. Goal-id derived from entity_canonical_id
    # + target_view_class (NOT raw path → stable across view renames).
    seen_propagations: set[str] = set()
    action_class_map = {
        "create": "visibility",
        "update": "status-cascade",
        "delete": "archive",
    }
    for obs in scan.get("cross_view_propagation_observations") or []:
        if not isinstance(obs, dict):
            continue
        if obs.get("observed_in_target") not in ("yes", "partial"):
            continue
        action = obs.get("action") or "create"
        action_class = action_class_map.get(action, "visibility")
        target_class = (obs.get("target_view_class") or "").strip()
        if not target_class:
            continue
        entity_canon = (obs.get("entity_canonical_id") or "").strip()
        if not entity_canon:
            # fallback: derive from source_view path
            sv = (obs.get("source_view") or "").strip("/")
            entity_canon = f"{name_slug(sv) or 'entity'}:{action}"
        # idempotent goal-id (audit ID-6 view-rename-stable)
        entity_slug = name_slug(entity_canon.split(":")[0])
        gid = f"G-AUTO-{entity_slug}-{action_class}-{target_class}"
        if gid in seen_propagations:
            continue
        seen_propagations.add(gid)
        stubs.append({
            "id": gid,
            "title": (
                f"Feature-chain: {action} on {obs.get('source_view')} "
                f"propagates to {target_class} ({obs.get('target_view')})"
            ),
            "priority": "important",
            "surface": "ui",
            "source": "review.runtime_discovery.cross_view",
            "goal_class": "feature_chain",
            "enables": [],
            "evidence": {
                "source_view": obs.get("source_view"),
                "target_view": obs.get("target_view"),
                "target_view_class": target_class,
                "entity_canonical_id": entity_canon,
                "observed_in_target": obs.get("observed_in_target"),
                "observed_count_delta": obs.get("observed_count_delta"),
                "limitations": obs.get("limitations") or [],
            },
            "trigger": f"{action.upper()} on {obs.get('source_view')}",
            "chain_steps": [
                {
                    "step_id": "S1",
                    "description": f"User on source view {obs.get('source_view')}",
                    "target_view_class": "source_view",
                    "expected_state": f"{action}_form_ready",
                    "downstream_effects": [],
                },
                {
                    "step_id": "S2",
                    "description": f"Perform {action} → server returns 2xx",
                    "target_view_class": "source_view_modal" if action == "create" else "source_view",
                    "expected_state": f"{action}_persisted",
                    "downstream_effects": [
                        f"entity {entity_canon} state change",
                    ],
                },
                {
                    "step_id": "S3",
                    "description": f"Navigate to {target_class} ({obs.get('target_view')})",
                    "target_view_class": target_class,
                    "expected_state": f"propagation_visible_in_{target_class}",
                    "downstream_effects": [
                        f"observed_count_delta={obs.get('observed_count_delta')}",
                    ],
                },
                {
                    "step_id": "S4",
                    "description": f"Re-open detail and assert state synced",
                    "target_view_class": "sibling_list",
                    "expected_state": "detail_reflects_source_mutation",
                    "downstream_effects": [],
                },
            ],
            "main_steps": [
                {"S1": f"User performs {action} on {obs.get('source_view')}"},
                {"S2": f"Navigate to {obs.get('target_view')} ({target_class})"},
                {"S3": f"Assert entity_id present (observed: {obs.get('observed_in_target')})"},
                {"S4": "Click → detail loads, mutation reflected end-to-end"},
            ],
            "postcondition": [
                f"feature chain {action} → {target_class} verified closed-loop",
            ],
        })

    for f in scan.get("forms", []):
        trigger = f.get("trigger", "unknown-form")
        key = name_slug(trigger)
        fields = f.get("fields") or []
        submit = f.get("submit_result") or {}
        persistence = f.get("persistence_probe") or {}
        stubs.append({
            "id": f"G-AUTO-{vslug}-form-{key}",
            "title": f"Form '{trigger}' validates + submits + persists on {view}",
            "priority": "critical",
            "surface": "ui",
            "source": "review.runtime_discovery",
            "evidence": {
                "view": view,
                "field_count": len(fields),
                "submit_status": submit.get("status"),
                "persistence_observed": persistence.get("persisted"),
            },
            "trigger": f"Open form via '{trigger}' on {view}",
            "main_steps": [
                {"S1": "Open form, fields render with correct types"},
                {"S2": f"Fill {len(fields)} field(s) including required={[fld['name'] for fld in fields if fld.get('required')]}"},
                {"S3": f"Submit — observe {submit.get('status', '20x')} response"},
                {"S4": f"Refresh — submitted record persists ({'verified' if persistence.get('persisted') else 'unverified during review'})"},
            ],
            "alternate_flows": [
                {"name": "missing_required", "trigger": "submit with required field empty", "expected": "inline errors, form stays open, no API call"},
                {"name": "duplicate_submit", "trigger": "rapid double-click submit", "expected": "second click ignored OR idempotent on server"},
            ],
            "postcondition": [
                "form-submitted entity created/updated in backing store",
                "form-driven UI state updated (list refresh / navigation)",
            ],
        })

    for t in scan.get("tables", []):
        row_count = t.get("row_count", 0)
        actions = t.get("actions_per_row") or []
        for action in actions:
            akey = name_slug(action)
            stubs.append({
                "id": f"G-AUTO-{vslug}-row-{akey}",
                "title": f"Row action '{action}' works on {view} table",
                "priority": "important",
                "surface": "ui",
                "source": "review.runtime_discovery",
                "evidence": {"view": view, "observed_rows": row_count, "action": action},
                "trigger": f"Click row action '{action}' on any row in {view}",
                "main_steps": [
                    {"S1": f"Table on {view} renders ≥1 row"},
                    {"S2": f"Click '{action}' on first row"},
                    {"S3": "Action invokes (modal opens / navigates / mutates)"},
                    {"S4": "Outcome reflects in UI (row removed/updated, or modal/page rendered)"},
                ],
                "alternate_flows": [
                    {"name": "auth_denied_for_role", "trigger": "user without permission for this action", "expected": "action hidden or shows 403 inline"},
                ],
            })

        if row_count > 0 and "pagination" not in declared_set:
            stubs.append({
                "id": f"G-AUTO-{vslug}-table-paging",
                "title": f"Table on {view} pagination state persists in URL",
                "priority": "important",
                "surface": "ui",
                "source": "review.runtime_discovery",
                "evidence": {"view": view, "observed_rows": row_count},
                "trigger": f"Navigate pages on {view} table",
                "main_steps": [
                    {"S1": f"Table on {view} loads page 1"},
                    {"S2": "Click next-page or page=2 link"},
                    {"S3": "URL updates with page param (e.g. ?page=2)"},
                    {"S4": "Refresh URL → page 2 loads directly (deep-link)"},
                    {"S5": "Browser back → returns to page 1"},
                ],
                "alternate_flows": [
                    {"name": "out_of_range", "trigger": "manually set page=999", "expected": "graceful empty state OR clamp to last page"},
                ],
            })

    for tab in scan.get("tabs", []):
        name = tab.get("name") or "unnamed"
        key = name_slug(name)
        stubs.append({
            "id": f"G-AUTO-{vslug}-tab-{key}",
            "title": f"Tab '{name}' on {view} renders panel content + persists in URL/state",
            "priority": "nice-to-have",
            "surface": "ui",
            "source": "review.runtime_discovery",
            "evidence": {"view": view, "tab_name": name, "elements_in_panel": tab.get("elements_in_panel")},
            "trigger": f"Click tab '{name}' on {view}",
            "main_steps": [
                {"S1": f"User on {view}"},
                {"S2": f"Click tab '{name}'"},
                {"S3": "Tab panel renders, sibling tabs hidden"},
                {"S4": "Refresh — selected tab persists (URL hash or state)"},
            ],
        })

    # Batch 40 + Batch 28 F13: auto-emit filter rigor stubs from scan-detected
    # filter widgets. Scanner (Batch 40) now emits scan.filters[] with
    # {name, kind, options}. Each becomes a G-AUTO-*-filter-* goal with
    # interactive_controls.filters[] frontmatter so /vg:test codegen renders
    # the D-16 14-case rigor pack and verify-filter-test-coverage.py finds it.
    for fw in scan.get("filters") or []:
        if not isinstance(fw, dict):
            continue
        fname = (fw.get("name") or "").strip()
        if not fname:
            continue
        fkey = name_slug(fname)
        if f"filter:{fname}" in declared_set:
            continue
        stubs.append({
            "id": f"G-AUTO-{vslug}-filter-{fkey}",
            "title": f"Filter '{fname}' on {view} — D-16 rigor pack (cardinality + boundary + URL sync + edge)",
            "priority": "important",
            "surface": "ui",
            "source": "review.runtime_discovery",
            "evidence": {
                "view": view,
                "filter_name": fname,
                "filter_kind": fw.get("kind"),
                "filter_ref": fw.get("ref"),
                "option_count": len(fw.get("options") or []) if fw.get("options") else None,
            },
            "interactive_controls": {
                "filters": [{
                    "name": fname,
                    "kind": fw.get("kind") or "text",
                    "options": fw.get("options") or [],
                }],
                "url_sync": True,
            },
            "trigger": f"Apply filter '{fname}' on {view}",
            "main_steps": [
                {"S1": f"User on {view} as authenticated role"},
                {"S2": f"Open filter '{fname}' control"},
                {"S3": "Select non-default value → list updates"},
                {"S4": "URL reflects filter param; refresh persists state"},
                {"S5": "Clear filter → list returns to default; URL param removed"},
            ],
            "alternate_flows": [
                {"name": "empty_result", "trigger": "filter to value with 0 matches",
                 "expected": "empty state shown, no errors"},
                {"name": "filter_sort_pagination",
                 "trigger": "apply filter while paginated/sorted",
                 "expected": "page resets to 1, sort preserved"},
                {"name": "xss_sanitize", "trigger": "filter value contains <script>",
                 "expected": "sanitized, no script exec, no API error"},
            ],
        })

    # Batch 40: auto-emit sort header rigor stubs
    for sh in scan.get("sort_headers") or []:
        if not isinstance(sh, dict):
            continue
        col = (sh.get("column") or "").strip()
        if not col:
            continue
        skey = name_slug(col)
        if f"sort:{col}" in declared_set:
            continue
        stubs.append({
            "id": f"G-AUTO-{vslug}-sort-{skey}",
            "title": f"Sort by '{col}' column on {view} — toggles asc/desc + URL persists",
            "priority": "nice-to-have",
            "surface": "ui",
            "source": "review.runtime_discovery",
            "evidence": {"view": view, "sort_column": col, "sort_ref": sh.get("ref")},
            "trigger": f"Click sort header '{col}' on {view}",
            "main_steps": [
                {"S1": f"Table on {view} loaded, default order"},
                {"S2": f"Click '{col}' header — order becomes asc"},
                {"S3": "URL reflects sort=col+dir"},
                {"S4": "Click again — order becomes desc"},
                {"S5": "Refresh — sort state persists from URL"},
            ],
        })

    # Batch 40: auto-emit pagination + search stubs if scan detected them
    pgn = scan.get("pagination") or {}
    if isinstance(pgn, dict) and pgn.get("present") and "pagination" not in declared_set:
        stubs.append({
            "id": f"G-AUTO-{vslug}-pagination-full",
            "title": f"Pagination on {view} — D-16 rigor pack (18 cases)",
            "priority": "important",
            "surface": "ui",
            "source": "review.runtime_discovery",
            "evidence": {
                "view": view,
                "controls": pgn.get("controls") or [],
                "current_page": pgn.get("current_page"),
                "total_pages": pgn.get("total_pages"),
                "url_sync_observed": pgn.get("url_sync"),
            },
            "interactive_controls": {
                "pagination": True,
                "url_sync": True,
            },
            "trigger": f"Navigate pages on {view}",
            "main_steps": [
                {"S1": f"Table on {view} loads page 1"},
                {"S2": "Next/prev/jump-to-page exercises navigation"},
                {"S3": "URL page param + deep-link verify"},
                {"S4": "Out-of-range → graceful clamp/empty"},
            ],
        })

    # Batch 43: accessibility findings → G-AUTO-a11y stubs.
    # Scanner runs axe-core (WCAG 2A + 2AA). Emit per-rule stub for
    # critical/serious findings only (moderate/minor = advisory, no stub).
    a11y_findings = scan.get("accessibility_findings") or []
    a11y_seen: set[str] = set()
    for finding in a11y_findings:
        if not isinstance(finding, dict):
            continue
        severity = (finding.get("severity") or "").lower()
        if severity not in ("critical", "serious"):
            continue
        rule = (finding.get("rule") or "").strip()
        if not rule or rule in a11y_seen:
            continue
        a11y_seen.add(rule)
        selector = finding.get("selector") or ""
        stubs.append({
            "id": f"G-AUTO-{vslug}-a11y-{name_slug(rule)}",
            "title": f"Accessibility: {rule} on {view} — WCAG {finding.get('wcag', '?')} ({severity})",
            "priority": "important" if severity == "critical" else "nice-to-have",
            "surface": "ui",
            "source": "review.runtime_discovery",
            "evidence": {
                "view": view,
                "axe_rule": rule,
                "wcag": finding.get("wcag"),
                "severity": severity,
                "selector": selector,
                "description": finding.get("description"),
                "help_url": finding.get("help_url"),
            },
            "trigger": f"Page loaded on {view}",
            "main_steps": [
                {"S1": f"Navigate to {view}"},
                {"S2": f"Run axe-core scan with WCAG 2A+2AA rules"},
                {"S3": f"Assert NO violation of rule '{rule}' on selector '{selector}'"},
                {"S4": "Manual review if violation re-appears: fix per help_url"},
            ],
        })

    # Batch 41: state observation stubs (empty / error_4xx / loading).
    # Scanner now actively probes these states; we emit per-state G-AUTO
    # stubs carrying the observed selector so spec generator binds
    # expect() to a real selector instead of guessing.
    state_obs = scan.get("state_observations") or {}
    state_map = [
        ("empty_state", "empty-state",
         f"Empty state on {view} renders friendly UI (no white-screen)",
         "Filter/search to zero matches"),
        ("error_state_4xx", "error-state",
         f"Error state on {view} (4xx) renders user-facing message + no crash",
         "Navigate to invalid id / unauthorized path"),
        ("loading_state", "loading-state",
         f"Loading state on {view} shows skeleton/spinner during fetch + no layout shift",
         "Throttle network → reload"),
    ]
    for state_key, slug, title, trigger in state_map:
        st = state_obs.get(state_key) or {}
        if not isinstance(st, dict) or not st.get("observed"):
            continue
        selector = st.get("selector") or ""
        if not selector:
            continue
        stubs.append({
            "id": f"G-AUTO-{vslug}-{slug}",
            "title": title,
            "priority": "important",
            "surface": "ui",
            "source": "review.runtime_discovery",
            "evidence": {
                "view": view,
                "state_kind": state_key,
                "selector": selector,
                "message_text": st.get("message_text"),
                "screenshot": st.get("screenshot"),
                "actual_status": st.get("actual_status"),
                "skeleton_visible_ms": st.get("skeleton_visible_ms"),
                "trigger_observed": st.get("trigger"),
            },
            "trigger": trigger + f" on {view}",
            "main_steps": [
                {"S1": f"User on {view} as authenticated role"},
                {"S2": trigger},
                {"S3": f"Element matching selector '{selector}' becomes visible"},
                {"S4": "No console errors; no white-screen; UI remains functional"},
            ],
        })

    for sr in scan.get("search") or []:
        if not isinstance(sr, dict):
            continue
        placeholder = (sr.get("placeholder") or "search").strip()
        skey = name_slug(placeholder[:30])
        stubs.append({
            "id": f"G-AUTO-{vslug}-search-{skey}",
            "title": f"Search '{placeholder}' on {view} — debounce + result narrowing + clear",
            "priority": "important",
            "surface": "ui",
            "source": "review.runtime_discovery",
            "evidence": {
                "view": view,
                "search_ref": sr.get("ref"),
                "placeholder": placeholder,
                "debounce_ms": sr.get("debounce_ms_observed"),
            },
            "trigger": f"Type search query on {view}",
            "main_steps": [
                {"S1": f"User on {view}"},
                {"S2": "Type 3-char query — wait debounce → list narrows"},
                {"S3": "Clear query — list returns to default"},
                {"S4": "Empty result query → empty state"},
            ],
        })

    return stubs


def render_markdown(stubs: list[dict], existing_count: int,
                    runtime_views: int, threshold: int) -> str:
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []
    lines.append(f"# TEST-GOALS-DISCOVERED.md")
    lines.append("")
    lines.append(f"_Generated: {now} by `/vg:review` Phase 2c (v2.34.0+)._")
    lines.append("")
    lines.append("Auto-emitted goal stubs from runtime UI discovery (Haiku/in-session Codex scans).")
    lines.append("Each stub maps to a real UI element observed during review. `/vg:test` codegen consumes")
    lines.append("this file alongside `TEST-GOALS.md`. Generated specs prefixed `auto-{goal-id}.spec.ts`.")
    lines.append("")
    lines.append(f"## Source")
    lines.append("")
    lines.append(f"- Existing TEST-GOALS.md: **{existing_count}** goals")
    lines.append(f"- Runtime views scanned: **{runtime_views}**")
    lines.append(f"- Auto-discovered goals: **{len(stubs)}**")
    lines.append(f"- Coverage threshold (min elements/view to require enrichment): {threshold}")
    lines.append("")
    lines.append("## Triage")
    lines.append("")
    lines.append("Auto-goals are **review-grade** (heuristically derived). Human triage on next blueprint:")
    lines.append("- Promote useful auto-goals → migrate to `TEST-GOALS.md` with proper IDs")
    lines.append("- Reject false-positives → add to `interactive_controls.exclude` in source goal")
    lines.append("- Keep `G-AUTO-*` IDs for repeat runs — script dedupes against existing IDs")
    lines.append("")
    lines.append("## Auto-emitted goals")
    lines.append("")

    for stub in stubs:
        lines.append("---")
        lines.append(f"id: {stub['id']}")
        lines.append(f"title: \"{stub['title']}\"")
        lines.append(f"priority: {stub['priority']}")
        lines.append(f"surface: {stub['surface']}")
        lines.append(f"source: {stub['source']}")
        lines.append(f"evidence:")
        for k, v in (stub.get("evidence") or {}).items():
            if v is not None:
                lines.append(f"  {k}: {json.dumps(v)}")
        lines.append(f"trigger: \"{stub.get('trigger', '')}\"")
        lines.append("main_steps:")
        for step in stub.get("main_steps") or []:
            for sk, sv in step.items():
                lines.append(f"  - {sk}: \"{sv}\"")
        if stub.get("alternate_flows"):
            lines.append("alternate_flows:")
            for af in stub["alternate_flows"]:
                lines.append(f"  - name: {af['name']}")
                lines.append(f"    trigger: \"{af['trigger']}\"")
                lines.append(f"    expected: \"{af['expected']}\"")
        if stub.get("postcondition"):
            lines.append("postcondition:")
            for pc in stub["postcondition"]:
                lines.append(f"  - \"{pc}\"")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--threshold", type=int, default=3,
                    help="Min elements per view that triggers required enrichment (default 3)")
    ap.add_argument("--validate-only", action="store_true",
                    help="Exit 1 if any view has elements >= threshold but TEST-GOALS-DISCOVERED has no goals for that view")
    ap.add_argument("--merge-recursive", action="store_true",
                    help="After writing G-AUTO-* stubs, append G-RECURSE-* stubs from "
                         "runs/goals-*.partial.yaml via aggregate_recursive_goals.py "
                         "(v2.40 Phase 2b-2.5 back-flow). Existing G-AUTO-* are preserved.")
    ap.add_argument("--recurse-mode", choices=["light", "deep", "exhaustive"],
                    default="light",
                    help="Forwarded to aggregate_recursive_goals.py --mode "
                         "(controls per-mode cap on G-RECURSE-* count). Ignored "
                         "unless --merge-recursive is set.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"\033[38;5;208mPhase dir not found: {phase_dir}\033[0m", file=sys.stderr)
        return 2

    existing_ids, declared_per_view = load_existing_goals(phase_dir)
    rmap = load_runtime_map(phase_dir)
    scans = load_scans(phase_dir)

    runtime_views = len(rmap.get("views", {}) or {})

    all_stubs: list[dict] = []
    per_view_stub_count: dict[str, int] = {}
    for view_url, scan in scans.items():
        runtime_view = (rmap.get("views") or {}).get(view_url) or {}
        declared = declared_per_view.get(view_url) or []
        stubs = classify_elements(view_url, scan, runtime_view, declared)
        stubs = [s for s in stubs if s["id"] not in existing_ids]
        per_view_stub_count[view_url] = len(stubs)
        all_stubs.extend(stubs)

    if args.validate_only:
        gaps: list[str] = []
        for view_url, scan in scans.items():
            element_count = (scan.get("elements_total") or 0)
            if element_count >= args.threshold and per_view_stub_count.get(view_url, 0) == 0:
                gaps.append(f"  {view_url}: {element_count} elements scanned, 0 auto-goals emitted")
        if gaps:
            print("\033[38;5;208mEnrichment gaps — these views had elements scanned but no goals derived:\033[0m")
            for g in gaps:
                print(g)
            return 1
        if not args.quiet:
            print(f"✓ Enrichment coverage OK ({len(all_stubs)} auto-goals across {len(scans)} views)")
        return 0

    body = render_markdown(all_stubs, len(existing_ids), runtime_views, args.threshold)
    out_path = phase_dir / "TEST-GOALS-DISCOVERED.md"
    tmp_path = out_path.with_suffix(".md.tmp")
    tmp_path.write_text(body, encoding="utf-8")
    tmp_path.replace(out_path)

    # ---------- Task 24: optional G-RECURSE-* merge ----------
    # Aggregator preserves existing content (auto-emitted recursive section is
    # bounded by ## Auto-emitted recursive probe goals + end marker), so it
    # appends to the file rather than overwriting Haiku-discovered G-AUTO-*.
    recurse_summary: dict | None = None
    if args.merge_recursive:
        runs_dir = phase_dir / "runs"
        agg = REPO_ROOT / "scripts" / "aggregate_recursive_goals.py"
        if not agg.is_file():
            if not args.quiet:
                print("\033[33maggregate_recursive_goals.py not found; skipping G-RECURSE-* merge\033[0m",
                      file=sys.stderr)
        elif not runs_dir.is_dir():
            if not args.quiet:
                print(f"\033[33mno runs/ subdir at {runs_dir}; skipping G-RECURSE-* merge\033[0m",
                      file=sys.stderr)
        else:
            import subprocess as _sp
            r = _sp.run(
                [sys.executable, str(agg),
                 "--phase-dir", str(phase_dir),
                 "--mode", args.recurse_mode,
                 "--output", str(out_path)],
                capture_output=True, text=True,
            )
            recurse_summary = {
                "exit_code": r.returncode,
                "stdout": r.stdout.strip(),
                "stderr": r.stderr.strip(),
            }
            if r.returncode != 0 and not args.quiet:
                print(f"\033[33maggregate_recursive_goals.py exit={r.returncode}: \033[0m"
                      f"{r.stderr.strip()}", file=sys.stderr)

    if args.json:
        payload = {
            "out_path": str(out_path.relative_to(REPO_ROOT).as_posix()) if str(out_path).startswith(str(REPO_ROOT)) else str(out_path),
            "auto_goals": len(all_stubs),
            "existing_goals": len(existing_ids),
            "runtime_views": runtime_views,
            "scans_processed": len(scans),
            "per_view_counts": per_view_stub_count,
        }
        if recurse_summary is not None:
            payload["recurse_merge"] = recurse_summary
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        print(f"✓ TEST-GOALS-DISCOVERED.md written")
        print(f"  Existing goals (TEST-GOALS.md): {len(existing_ids)}")
        print(f"  Auto-emitted goals: {len(all_stubs)}")
        print(f"  Views scanned: {len(scans)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
