#!/usr/bin/env python3
"""
Validator: verify-url-state-sync.py

Phase J (v2.8.4, 2026-04-26): list-view URL state sync declaration check.

Purpose: every goal with surface=ui that touches a list / table / grid view
MUST declare an `interactive_controls` block in TEST-GOALS.md frontmatter.
This block specifies how filter / sort / pagination / search state is synced
to URL search params (mandatory dashboard UX baseline — see executor R7).

Static-only check: validates declaration completeness. Live browser probe
(click each control, assert URL update + reload-survives) is implemented
separately at /vg:review phase 2.7 once RUNTIME-MAP is available.

Severity matrix (config-driven via ui_state_conventions.severity_phase_cutover):
- phase < cutover (default 14) → WARN (grandfather legacy phases)
- phase >= cutover → BLOCK (mandatory for new phases)

Detection: a goal triggers this check when ANY of:
  1. surface contains "ui"
  2. main_steps OR title mentions list/table/grid/danh sách/bảng
  3. trigger mentions GET /<plural-noun> (e.g. GET /campaigns)

Block conditions (mandatory phase):
  - List-view detected + interactive_controls block missing → BLOCK
  - url_sync: false + url_sync_waive_reason empty/missing → BLOCK
  - filter declared without values OR url_param OR assertion → BLOCK
  - sort declared without columns OR url_param_field OR url_param_dir → BLOCK
  - pagination declared without page_size OR url_param_page → BLOCK
  - search declared without url_param OR debounce_ms → BLOCK

Usage:
  verify-url-state-sync.py --phase <N>

Exit codes:
  0 PASS or WARN-only
  1 BLOCK
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL | re.MULTILINE)

# Patterns indicating a list / table / grid view goal.
LIST_KEYWORD_RE = re.compile(
    r"\b(list|table|grid|danh\s*sách|bảng|paginate|paging|filter\s*chip|"
    r"sort\s+(by|column))\b",
    re.IGNORECASE,
)

# GET /<plural-noun> — strong signal of a list endpoint goal.
GET_LIST_PATH_RE = re.compile(
    r"\bGET\s+(/[a-zA-Z0-9_/{}-]*[a-zA-Z]s)\b",
    re.IGNORECASE,
)

# Default cutover when config not loadable.
DEFAULT_PHASE_CUTOVER = 14


def _read_config_cutover() -> int:
    """Read ui_state_conventions.severity_phase_cutover from vg.config.md.
    Falls back to DEFAULT_PHASE_CUTOVER on any read/parse error.
    """
    cfg = REPO_ROOT / ".claude" / "vg.config.md"
    if not cfg.exists():
        return DEFAULT_PHASE_CUTOVER
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return DEFAULT_PHASE_CUTOVER
    m = re.search(
        r"^ui_state_conventions:.*?severity_phase_cutover:\s*(\d+)",
        text, re.DOTALL | re.MULTILINE,
    )
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return DEFAULT_PHASE_CUTOVER


def _phase_major(phase: str) -> int:
    """Return major part of phase id as int. '7.14.3' → 7, '14' → 14, '07.12' → 7.
    Returns -1 on parse failure (treat as legacy).
    """
    if not phase:
        return -1
    head = phase.split(".")[0]
    head = head.lstrip("0") or "0"
    try:
        return int(head)
    except ValueError:
        return -1


def _parse_goal_blocks(text: str) -> list[dict]:
    """Split TEST-GOALS.md into per-goal frontmatter sections."""
    goals: list[dict] = []
    for m in FRONTMATTER_RE.finditer(text):
        fm_text = m.group(1)
        id_match = re.search(r"^id:\s*(G-\d+)", fm_text, re.MULTILINE)
        if id_match:
            goals.append({
                "id": id_match.group(1),
                "frontmatter": fm_text,
            })
    return goals


def _yaml_field(block: str, key: str) -> str | None:
    """Extract top-level key value from frontmatter-like YAML."""
    m = re.search(
        rf"^{re.escape(key)}:\s*(.+?)(?=\n[a-zA-Z_]+:|\n---|\Z)",
        block, re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else None


def _yaml_nested_block(block: str, parent: str) -> str | None:
    """Extract the indented sub-block of a parent key.

    Handles both top-level (`parent:` at column 0) and nested (`  parent:`
    inside another block) anchors. Returns lines under parent: with their
    indent preserved relative to the document, NOT dedented — downstream
    regex must accept any indent level.
    """
    lines = block.splitlines()
    out: list[str] = []
    parent_indent = -1
    for line in lines:
        if parent_indent < 0:
            # Look for `[indent]parent:` line. Allow inline value or block-form.
            m = re.match(rf"^(\s*){re.escape(parent)}:\s*(.*)$", line)
            if m:
                inline_value = m.group(2).strip()
                if inline_value:
                    return inline_value
                parent_indent = len(m.group(1))
                continue
        else:
            stripped = line.lstrip()
            if not stripped:
                out.append(line)
                continue
            # End of block when indent returns to <= parent_indent.
            current_indent = len(line) - len(stripped)
            if current_indent <= parent_indent:
                break
            out.append(line)
    return "\n".join(out) if out else None


def _is_list_view_goal(fm: str) -> bool:
    """Detect list/table/grid goals via surface + keyword + endpoint signals."""
    surface = (_yaml_field(fm, "surface") or "").lower()
    if "ui" not in surface:
        return False
    title = _yaml_field(fm, "title") or ""
    main_steps = _yaml_field(fm, "main_steps") or ""
    trigger = _yaml_field(fm, "trigger") or ""
    combined = f"{title}\n{main_steps}\n{trigger}"
    if LIST_KEYWORD_RE.search(combined):
        return True
    if GET_LIST_PATH_RE.search(combined):
        return True
    return False


def _check_control_complete(
    control_name: str, sub_block: str, required_fields: tuple[str, ...]
) -> list[str]:
    """Check that a control sub-block (filters[i], pagination, search, sort)
    has all required fields. Returns list of missing field names.
    """
    missing: list[str] = []
    for field in required_fields:
        # Look for `field:` line with non-empty value.
        m = re.search(
            rf"^\s*{re.escape(field)}:\s*([^\n]*)$",
            sub_block, re.MULTILINE,
        )
        if not m or not m.group(1).strip() or m.group(1).strip() in ("\"\"", "''"):
            missing.append(field)
    return missing


def _audit_goal(fm: str) -> dict:
    """Run all interactive_controls checks on a single goal frontmatter.

    Returns dict with categories of issues:
      block_missing: bool — interactive_controls absent
      url_sync_waive_invalid: bool — url_sync false but no reason
      filter_incomplete: list[dict]
      pagination_incomplete: list[str]  (missing field names)
      search_incomplete: list[str]
      sort_incomplete: list[str]
    """
    result = {
        "block_missing": False,
        "url_sync_waive_invalid": False,
        "filter_incomplete": [],
        "pagination_incomplete": [],
        "search_incomplete": [],
        "sort_incomplete": [],
    }

    block = _yaml_nested_block(fm, "interactive_controls")
    if not block or not block.strip():
        result["block_missing"] = True
        return result

    # url_sync handling
    url_sync_m = re.search(r"^\s*url_sync:\s*(\S+)", block, re.MULTILINE)
    if url_sync_m and url_sync_m.group(1).lower().strip("\"'") == "false":
        reason_m = re.search(
            r"^\s*url_sync_waive_reason:\s*(.+?)$", block, re.MULTILINE,
        )
        if not reason_m or not reason_m.group(1).strip().strip("\"'"):
            result["url_sync_waive_invalid"] = True
        # When waived, skip the per-control completeness checks.
        return result

    # filters: list of dicts. Each item separator is `- name:` line.
    filters_block = _yaml_nested_block(block, "filters")
    if filters_block:
        # Split into items by "- name:" anchors. Each item runs until next anchor.
        item_starts = [m.start() for m in
                       re.finditer(r"^\s*-\s+name:", filters_block, re.MULTILINE)]
        item_starts.append(len(filters_block))
        for i in range(len(item_starts) - 1):
            chunk = filters_block[item_starts[i]:item_starts[i + 1]]
            # name already anchors the chunk; only verify values + assertion.
            missing = _check_control_complete(
                "filters", chunk,
                required_fields=("values", "assertion"),
            )
            if missing:
                # Get filter name for better error
                name_m = re.search(r"^\s*-\s+name:\s*(\S+)", chunk, re.MULTILINE)
                fname = name_m.group(1).strip("\"' ") if name_m else "<anonymous>"
                result["filter_incomplete"].append({
                    "name": fname, "missing": missing,
                })

    # pagination, search, sort: single dicts (not lists)
    pagination_block = _yaml_nested_block(block, "pagination")
    if pagination_block:
        # v2.8.4 Phase J — pagination UI pattern fields are MANDATORY
        # alongside URL state fields. Missing UI pattern means executor
        # likely shipped plain prev/next which is BANNED.
        result["pagination_incomplete"] = _check_control_complete(
            "pagination", pagination_block,
            required_fields=(
                "page_size", "url_param_page", "assertion",
                "ui_pattern", "show_total_records", "show_total_pages",
            ),
        )
        # Verify ui_pattern value is the locked convention.
        ui_pat_m = re.search(
            r"^\s*ui_pattern:\s*[\"']?([^\"'#\n]+)[\"']?\s*$",
            pagination_block, re.MULTILINE,
        )
        if ui_pat_m:
            value = ui_pat_m.group(1).strip()
            allowed = ("first-prev-numbered-window-next-last", "infinite-scroll")
            if value not in allowed:
                result["pagination_incomplete"].append(
                    f"ui_pattern={value} (must be one of {allowed})"
                )

    search_block = _yaml_nested_block(block, "search")
    if search_block:
        result["search_incomplete"] = _check_control_complete(
            "search", search_block,
            required_fields=("url_param", "debounce_ms", "assertion"),
        )

    sort_block = _yaml_nested_block(block, "sort")
    if sort_block:
        result["sort_incomplete"] = _check_control_complete(
            "sort", sort_block,
            required_fields=("columns", "url_param_field", "url_param_dir",
                             "assertion"),
        )

    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="verify-url-state-sync")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        if not goals_path.exists():
            emit_and_exit(out)

        text = goals_path.read_text(encoding="utf-8", errors="replace")
        goals = _parse_goal_blocks(text)
        if not goals:
            emit_and_exit(out)

        cutover = _read_config_cutover()
        phase_major = _phase_major(args.phase)
        is_mandatory = phase_major >= 0 and phase_major >= cutover
        # When phase isn't a parseable number (unusual), default to mandatory
        # to avoid silent skipping.
        if phase_major < 0:
            is_mandatory = True

        list_view_goals: list[dict] = []
        block_missing: list[dict] = []
        waive_invalid: list[dict] = []
        filter_issues: list[dict] = []
        pagination_issues: list[dict] = []
        search_issues: list[dict] = []
        sort_issues: list[dict] = []

        for goal in goals:
            fm = goal["frontmatter"]
            gid = goal["id"]
            if not _is_list_view_goal(fm):
                continue
            list_view_goals.append({"goal": gid})

            audit = _audit_goal(fm)
            title = (_yaml_field(fm, "title") or "").strip("\"' \n")[:60]

            if audit["block_missing"]:
                block_missing.append({"goal": gid, "title": title})
                continue
            if audit["url_sync_waive_invalid"]:
                waive_invalid.append({"goal": gid, "title": title})
                continue
            for fi in audit["filter_incomplete"]:
                filter_issues.append({
                    "goal": gid, "filter": fi["name"],
                    "missing": fi["missing"],
                })
            if audit["pagination_incomplete"]:
                pagination_issues.append({
                    "goal": gid,
                    "missing": audit["pagination_incomplete"],
                })
            if audit["search_incomplete"]:
                search_issues.append({
                    "goal": gid,
                    "missing": audit["search_incomplete"],
                })
            if audit["sort_incomplete"]:
                sort_issues.append({
                    "goal": gid,
                    "missing": audit["sort_incomplete"],
                })

        # Emit evidence — all failures share the same severity decision
        # (BLOCK if mandatory phase, WARN if grandfather).
        emit = (lambda ev: out.add(ev)) if is_mandatory else (lambda ev: out.warn(ev))

        if not list_view_goals:
            # No list/table/grid goals → nothing to check, PASS quietly.
            emit_and_exit(out)

        if block_missing:
            sample = "; ".join(
                f"{g['goal']}: {g['title']}" for g in block_missing[:5]
            )
            emit(Evidence(
                type="url_state_block_missing",
                message=(
                    f"List-view goal(s) missing interactive_controls block: "
                    f"{len(block_missing)}. URL state sync is mandatory for "
                    f"list/table/grid views (executor R7) — refresh, share-link, "
                    f"and back/forward navigation depend on it."
                ),
                actual=sample,
                fix_hint=(
                    "Add interactive_controls to TEST-GOALS.md per goal. See "
                    ".claude/commands/vg/_shared/templates/TEST-GOAL-enriched-template.md"
                    " section 'v2.8.4 Phase J' for schema. Declare filters/pagination/"
                    "search/sort with url_param + assertion fields."
                ),
            ))

        if waive_invalid:
            sample = "; ".join(
                f"{g['goal']}: {g['title']}" for g in waive_invalid[:5]
            )
            emit(Evidence(
                type="url_state_waive_invalid",
                message=(
                    f"Goal(s) with url_sync: false but missing url_sync_waive_reason: "
                    f"{len(waive_invalid)}. Waiving the URL-sync requirement requires "
                    f"explicit reason for OD audit trail."
                ),
                actual=sample,
                fix_hint=(
                    "Add url_sync_waive_reason: \"<why state is local-only>\" to "
                    "interactive_controls. Validator only accepts non-empty quoted "
                    "string. Reason will be logged as soft OD entry."
                ),
            ))

        if filter_issues:
            sample = "; ".join(
                f"{f['goal']} filter '{f['filter']}': missing {f['missing']}"
                for f in filter_issues[:5]
            )
            emit(Evidence(
                type="url_state_filter_incomplete",
                message=(
                    f"Filter declarations missing required fields: "
                    f"{len(filter_issues)}. Each filter needs name, values, "
                    f"assertion."
                ),
                actual=sample,
                fix_hint=(
                    "For each filter add: name (data attr/test id), values "
                    "(allowed list), url_param (default = name), assertion "
                    "(rows match + URL synced + reload preserves)."
                ),
            ))

        if pagination_issues:
            sample = "; ".join(
                f"{p['goal']}: missing {p['missing']}"
                for p in pagination_issues[:5]
            )
            emit(Evidence(
                type="url_state_pagination_incomplete",
                message=(
                    f"Pagination block missing required fields: "
                    f"{len(pagination_issues)}. Need page_size + url_param_page + "
                    f"assertion."
                ),
                actual=sample,
                fix_hint=(
                    "pagination:\n  page_size: 20\n  url_param_page: page\n"
                    "  assertion: \"page2 first row != page1 first row; URL ?page=2 "
                    "synced; reload page=2 preserves\""
                ),
            ))

        if search_issues:
            sample = "; ".join(
                f"{s['goal']}: missing {s['missing']}"
                for s in search_issues[:5]
            )
            emit(Evidence(
                type="url_state_search_incomplete",
                message=(
                    f"Search block missing required fields: "
                    f"{len(search_issues)}. Need url_param + debounce_ms + "
                    f"assertion."
                ),
                actual=sample,
                fix_hint=(
                    "search:\n  url_param: q\n  debounce_ms: 300\n"
                    "  assertion: \"type query → debounce → URL ?q=... synced; "
                    "result rows contain query (case-insensitive)\""
                ),
            ))

        if sort_issues:
            sample = "; ".join(
                f"{s['goal']}: missing {s['missing']}"
                for s in sort_issues[:5]
            )
            emit(Evidence(
                type="url_state_sort_incomplete",
                message=(
                    f"Sort block missing required fields: "
                    f"{len(sort_issues)}. Need columns + url_param_field + "
                    f"url_param_dir + assertion."
                ),
                actual=sample,
                fix_hint=(
                    "sort:\n  columns: [created_at, name, status]\n"
                    "  url_param_field: sort\n  url_param_dir: dir\n"
                    "  assertion: \"click header toggles asc↔desc; URL synced; "
                    "ORDER BY holds\""
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
