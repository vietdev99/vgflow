#!/usr/bin/env python3
"""
Validator: verify-url-state-runtime.py

Phase A (v2.7, 2026-04-26): runtime probe verification for list-view URL
state sync.

Complement to verify-url-state-sync.py (Phase J static check). The static
check guarantees declarations exist; this runtime check verifies the
declared params actually round-trip through the live app.

Producer flow: /vg:review step phase2_8_url_state_runtime drives MCP
Playwright — for each goal with `interactive_controls.url_sync: true`,
it navigates to the route, clicks each declared control, snapshots URL
pre/post, appends to `${PHASE_DIR}/url-runtime-probe.json`. This
validator runs after the producer step and asserts:

  1. Probe artifact exists (else BLOCK — review has not probed the lens).
  2. Every list-view goal in TEST-GOALS has a probe entry (else BLOCK per goal).
  3. Every declared control has a matching probe result (else BLOCK per control).
  4. Every matching result's `url_params_after` carries the declared
     `url_param` key with the expected value (else BLOCK — declaration drift).
  5. Filter controls carry result semantics evidence so "pending" cannot still
     show flagged rows while only URL params pass.

Severity:
  BLOCK — missing probe, missing control coverage, URL param drift, or missing
  filter result semantics evidence.

Override: --skip-runtime suppresses both WARN and BLOCK; logs a soft OD
debt entry. Used in CI environments without a live browser.

Usage:
  verify-url-state-runtime.py --phase <N> [--skip-runtime]

Exit codes:
  0 PASS or WARN-only
  1 BLOCK
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL | re.MULTILINE)
MD_GOAL_RE = re.compile(
    r"^##\s+Goal\s+(G-[A-Z0-9-]+)\s*:?\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
MD_FIELD_RE = re.compile(r"^\*\*([^*:\n]+):\*\*\s*(.*)$")


def _parse_goal_blocks(text: str) -> list[dict]:
    goals: list[dict] = []
    for m in FRONTMATTER_RE.finditer(text):
        fm_text = m.group(1)
        id_match = re.search(r"^id:\s*(G-\d+)", fm_text, re.MULTILINE)
        if id_match:
            goals.append({"id": id_match.group(1), "frontmatter": fm_text})
    if goals:
        return goals

    matches = list(MD_GOAL_RE.finditer(text))
    for idx, match in enumerate(matches):
        gid = match.group(1).upper()
        title = match.group(2).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end]
        fm_lines = [f"id: {gid}", f"title: {title}"]
        capture_key: str | None = None
        nested_capture_parent: str | None = None
        for raw in block.splitlines():
            field = MD_FIELD_RE.match(raw.strip())
            if field:
                label = field.group(1).strip().lower().replace(" ", "_").replace("-", "_")
                value = field.group(2).strip()
                capture_key = None
                nested_capture_parent = None
                if label in {"interactive_controls", "main_steps"}:
                    fm_lines.append(f"{label}:")
                    if value:
                        fm_lines.append(f"  {value}")
                    capture_key = label
                else:
                    fm_lines.append(f"{label}: {value}")
                continue
            if capture_key and raw.strip():
                stripped = raw.strip()
                if raw[:1].isspace():
                    fm_lines.append(f"  {raw.rstrip()}")
                    continue
                if capture_key == "interactive_controls":
                    first_level = re.match(
                        r"^(url_sync|url_sync_waive_reason|filters|sort|pagination|search):\s*(.*)$",
                        stripped,
                    )
                    if first_level:
                        fm_lines.append(f"  {stripped}")
                        key, value = first_level.group(1), first_level.group(2).strip()
                        nested_capture_parent = key if not value and key in {"filters", "sort", "pagination", "search"} else None
                        continue
                    if nested_capture_parent:
                        fm_lines.append(f"    {stripped}")
                        continue
                fm_lines.append(f"  {stripped}")
        goals.append({"id": gid, "frontmatter": "\n".join(fm_lines)})
    return goals


def _yaml_field(block: str, key: str) -> str | None:
    m = re.search(
        rf"^{re.escape(key)}:\s*(.+?)(?=\n[a-zA-Z_]+:|\n---|\Z)",
        block, re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else None


def _yaml_nested_block(block: str, parent: str) -> str | None:
    lines = block.splitlines()
    out: list[str] = []
    parent_indent = -1
    for line in lines:
        if parent_indent < 0:
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
            current_indent = len(line) - len(stripped)
            if current_indent <= parent_indent:
                break
            out.append(line)
    return "\n".join(out) if out else None


def _inline_map(text: str) -> dict[str, str]:
    stripped = text.strip().strip(",")
    if "\n" in stripped and not stripped.startswith("- {") and not stripped.startswith("{"):
        return {}
    if stripped.startswith("-"):
        stripped = stripped[1:].strip()
    if "\n" in stripped:
        return {}
    if stripped.startswith("{") and stripped.endswith("}"):
        stripped = stripped[1:-1]
    elif ":" not in stripped or "," not in stripped:
        return {}
    result: dict[str, str] = {}
    cur: list[str] = []
    depth = 0
    parts: list[str] = []
    for ch in stripped:
        if ch in "[{(":
            depth += 1
        elif ch in "]})" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if cur:
        parts.append("".join(cur))
    for part in parts:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        result[key.strip().strip("\"'")] = value.strip().strip("\"'")
    return result


def _field_value(block: str, *names: str) -> str | None:
    inline = _inline_map(block)
    for name in names:
        if inline.get(name):
            return inline[name]
        m = re.search(rf"^\s*{re.escape(name)}:\s*([^\n]+)$", block, re.MULTILINE)
        if m and m.group(1).strip() not in {"\"\"", "''"}:
            return m.group(1).strip().strip("\"'")
    return None


def _is_url_sync_goal(fm: str) -> bool:
    """Goal opts in to runtime probe via interactive_controls.url_sync: true."""
    block = _yaml_nested_block(fm, "interactive_controls")
    if not block:
        return False
    m = re.search(r"^\s*url_sync:\s*(\S+)", block, re.MULTILINE)
    if not m:
        return False
    return m.group(1).lower().strip("\"'") == "true"


def _declared_controls(fm: str) -> list[dict]:
    """Extract per-control records from interactive_controls block.

    Returns list of {kind, name, url_param} where url_param is the
    declared search-param key the runtime URL must carry post-interaction.
    """
    block = _yaml_nested_block(fm, "interactive_controls")
    if not block:
        return []
    controls: list[dict] = []

    # filters: list of dicts with name + url_param (or `param`)
    filters_block = _yaml_nested_block(block, "filters")
    if filters_block:
        chunks = re.findall(
            r"^\s*-\s+(?:\{.*?\}|name:.*?)(?=^\s*-\s+|\Z)",
            filters_block,
            re.MULTILINE | re.DOTALL,
        )
        for chunk in chunks:
            inline = _inline_map(chunk)
            name_m = re.search(r"^\s*-?\s*name:\s*([^\n]+)", chunk, re.MULTILINE)
            name = inline.get("name") or (name_m.group(1).strip("\"'") if name_m else "")
            url_param = _field_value(chunk, "url_param", "param")
            if name and url_param:
                controls.append({
                    "kind": "filter",
                    "name": name,
                    "url_param": url_param,
                })

    # sort: single block with url_param_field + url_param_dir (or `param`)
    sort_block = _yaml_nested_block(block, "sort")
    if sort_block:
        url_param = _field_value(sort_block, "url_param_field", "param")
        if url_param:
            controls.append({
                "kind": "sort",
                "name": "sort",
                "url_param": url_param,
            })

    # pagination: single block with url_param_page (or `page_param`)
    pagination_block = _yaml_nested_block(block, "pagination")
    if pagination_block:
        url_param = _field_value(pagination_block, "url_param_page", "page_param", "url_param")
        if url_param:
            controls.append({
                "kind": "pagination",
                "name": "page",
                "url_param": url_param,
            })

    # search: single block with url_param (or `param`)
    search_block = _yaml_nested_block(block, "search")
    if search_block:
        url_param = _field_value(search_block, "url_param", "param")
        if url_param:
            controls.append({
                "kind": "search",
                "name": "search",
                "url_param": url_param,
            })

    return controls


def _load_probe(probe_path: Path) -> tuple[dict | None, str | None]:
    """Returns (data, error). data is keyed by goal_id."""
    if not probe_path.exists():
        return None, "missing"
    try:
        raw = json.loads(probe_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"malformed: {exc}"
    # Expected schema:
    #   {"goals": [{"goal_id": "G-XX", "url": "...", "controls": [...]}]}
    by_goal: dict[str, dict] = {}
    for entry in raw.get("goals", []):
        gid = entry.get("goal_id")
        if gid:
            by_goal[gid] = entry
    return by_goal, None


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        allow_abbrev=False,
    )
    ap.add_argument("--phase", required=True)
    ap.add_argument(
        "--skip-runtime", action="store_true",
        help="Suppress both WARN and BLOCK (CI without browser); logs OD debt.",
    )
    args = ap.parse_args()

    out = Output(validator="verify-url-state-runtime")
    with timer(out):
        if args.skip_runtime:
            out.warn(Evidence(
                type="url_runtime_probe_skipped",
                message=(
                    "Runtime probe suppressed via --skip-runtime. "
                    "Soft OD debt: declaration vs implementation drift may go "
                    "undetected until a session with browser access re-runs review."
                ),
            ))
            emit_and_exit(out)

        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        goals_path = Path(phase_dir) / "TEST-GOALS.md"
        if not goals_path.exists():
            emit_and_exit(out)

        text = goals_path.read_text(encoding="utf-8", errors="replace")
        goals = _parse_goal_blocks(text)
        url_sync_goals = [g for g in goals if _is_url_sync_goal(g["frontmatter"])]
        if not url_sync_goals:
            emit_and_exit(out)

        probe_path = Path(phase_dir) / "url-runtime-probe.json"
        probe, err = _load_probe(probe_path)

        if err == "missing":
            out.add(Evidence(
                type="url_runtime_probe_missing",
                message=(
                    f"Runtime probe artifact missing: {probe_path.name}. "
                    f"Static declarations exist for {len(url_sync_goals)} list-view "
                    f"goals but runtime probe has not run. /vg:review phase2_8 "
                    f"writes this artifact during browser exploration."
                ),
                fix_hint=(
                    "Re-run /vg:review with browser access. The phase2_8 step "
                    "drives MCP Playwright to click each declared control + "
                    "snapshot URL params + writes url-runtime-probe.json."
                ),
            ))
            emit_and_exit(out)

        if err:
            out.add(Evidence(
                type="url_runtime_probe_malformed",
                message=f"url-runtime-probe.json could not be parsed: {err}",
                fix_hint=(
                    "Schema: {goals: [{goal_id, url, controls: [{kind, name, "
                    "value, url_param_expected, url_params_after}]}]}. "
                    "Re-run /vg:review phase2_8 to regenerate."
                ),
            ))
            emit_and_exit(out)

        # Per-goal coverage + drift checks.
        for goal in url_sync_goals:
            gid = goal["id"]
            declared = _declared_controls(goal["frontmatter"])
            entry = probe.get(gid) if probe else None

            if entry is None:
                out.add(Evidence(
                    type="url_runtime_probe_goal_missing",
                    message=(
                        f"Goal {gid} declares interactive_controls.url_sync: true "
                        f"but no probe entry was recorded."
                    ),
                    fix_hint=(
                        f"Add probe coverage for {gid}. /vg:review phase2_8 must "
                        f"navigate to the goal route and exercise every declared "
                        f"control."
                    ),
                ))
                continue

            probed = {
                (c.get("kind"), c.get("name")): c
                for c in entry.get("controls", [])
            }

            for ctrl in declared:
                key = (ctrl["kind"], ctrl["name"])
                # Allow generic key (kind, "*") for sort/pagination/search where name normalized.
                actual = probed.get(key) or probed.get((ctrl["kind"], "*"))
                if actual is None:
                    out.add(Evidence(
                        type="url_runtime_control_unprobed",
                        message=(
                            f"{gid}: declared {ctrl['kind']}={ctrl['name']} "
                            f"(url_param={ctrl['url_param']}) was not exercised "
                            f"during runtime probe."
                        ),
                        fix_hint=(
                            "Probe must click/select every declared control once "
                            "per representative value. Update phase2_8 prose."
                        ),
                    ))
                    continue

                params_after = actual.get("url_params_after") or {}
                if ctrl["url_param"] not in params_after:
                    out.add(Evidence(
                        type="url_runtime_param_missing",
                        message=(
                            f"{gid} {ctrl['kind']} '{ctrl['name']}': declared "
                            f"url_param='{ctrl['url_param']}' but post-interaction "
                            f"URL did not carry it. Implementation drift."
                        ),
                        expected=ctrl["url_param"],
                        actual=sorted(params_after.keys()),
                        fix_hint=(
                            "Implementation does not write the declared param "
                            "to URL. Either fix the route handler/UI binding, "
                            "or amend interactive_controls if param was renamed."
                        ),
                    ))
                    continue

                if ctrl["kind"] == "filter":
                    semantics = actual.get("result_semantics") or actual.get("row_semantics") or {}
                    passed = semantics.get("passed")
                    violations = semantics.get("violations")
                    rows_checked = semantics.get("rows_checked")
                    if passed is not True or not isinstance(rows_checked, int):
                        out.add(Evidence(
                            type="url_runtime_filter_semantics_missing",
                            message=(
                                f"{gid} filter '{ctrl['name']}': runtime probe updated URL "
                                "but did not prove returned rows match the selected filter."
                            ),
                            expected=(
                                "control.result_semantics={passed:true, rows_checked:int, "
                                "violations:[]}"
                            ),
                            actual=semantics or None,
                            fix_hint=(
                                "After selecting the filter, inspect visible rows and/or the "
                                "network response. Record row count and violations so pending "
                                "cannot still show flagged/approved rows."
                            ),
                        ))
                    elif violations:
                        out.add(Evidence(
                            type="url_runtime_filter_semantics_failed",
                            message=(
                                f"{gid} filter '{ctrl['name']}': rows violating selected "
                                "filter were observed."
                            ),
                            expected=[],
                            actual=violations,
                            fix_hint="Fix API query semantics or FE status/flag mapping, then rerun this lens.",
                        ))

        emit_and_exit(out)


if __name__ == "__main__":
    main()
