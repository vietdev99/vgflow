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

  1. Probe artifact exists (else WARN — review hasn't probed yet).
  2. Every list-view goal in TEST-GOALS has a probe entry (else WARN per goal).
  3. Every declared control has a matching probe result (else WARN per control).
  4. Every matching result's `url_params_after` carries the declared
     `url_param` key with the expected value (else BLOCK — declaration drift).

Severity:
  WARN — probe artifact missing OR coverage gap (no probe for declared control)
  BLOCK — runtime URL params do not match declaration (declaration drift)

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


def _parse_goal_blocks(text: str) -> list[dict]:
    goals: list[dict] = []
    for m in FRONTMATTER_RE.finditer(text):
        fm_text = m.group(1)
        id_match = re.search(r"^id:\s*(G-\d+)", fm_text, re.MULTILINE)
        if id_match:
            goals.append({"id": id_match.group(1), "frontmatter": fm_text})
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
        items = re.split(r"^\s*-\s+name:", filters_block, flags=re.MULTILINE)
        for raw in items[1:]:
            chunk = "name:" + raw
            name_m = re.search(r"^name:\s*(\S+)", chunk, re.MULTILINE)
            up_m = re.search(
                r"^\s*(?:url_param|param):\s*(\S+)", chunk, re.MULTILINE,
            )
            if name_m and up_m:
                controls.append({
                    "kind": "filter",
                    "name": name_m.group(1).strip("\"'"),
                    "url_param": up_m.group(1).strip("\"'"),
                })

    # sort: single block with url_param_field + url_param_dir (or `param`)
    sort_block = _yaml_nested_block(block, "sort")
    if sort_block:
        field_m = re.search(
            r"^\s*(?:url_param_field|param):\s*(\S+)",
            sort_block, re.MULTILINE,
        )
        if field_m:
            controls.append({
                "kind": "sort",
                "name": "sort",
                "url_param": field_m.group(1).strip("\"'"),
            })

    # pagination: single block with url_param_page (or `page_param`)
    pagination_block = _yaml_nested_block(block, "pagination")
    if pagination_block:
        page_m = re.search(
            r"^\s*(?:url_param_page|page_param):\s*(\S+)",
            pagination_block, re.MULTILINE,
        )
        if page_m:
            controls.append({
                "kind": "pagination",
                "name": "page",
                "url_param": page_m.group(1).strip("\"'"),
            })

    # search: single block with url_param (or `param`)
    search_block = _yaml_nested_block(block, "search")
    if search_block:
        sp_m = re.search(
            r"^\s*(?:url_param|param):\s*(\S+)",
            search_block, re.MULTILINE,
        )
        if sp_m:
            controls.append({
                "kind": "search",
                "name": "search",
                "url_param": sp_m.group(1).strip("\"'"),
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
            out.warn(Evidence(
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
                out.warn(Evidence(
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
                    out.warn(Evidence(
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

        emit_and_exit(out)


if __name__ == "__main__":
    main()
