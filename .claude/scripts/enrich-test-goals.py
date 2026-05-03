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
