#!/usr/bin/env python3
"""
Validator: verify-uimap-schema.py — Phase 15 D-15

Enforces 5-field-per-node schema lock on UI-MAP.md JSON code block.

Required fields per node (per schemas/ui-map.v1.json):
  1. tag                   — string, ≥1 char (component/element name)
  2. classes               — array of strings (Tailwind utility-bound or component)
  3. children_count_order  — object {count: int≥0, order: array of string}
  4. props_bound           — object (data prop name → source binding)
  5. text_content_static   — string OR null (null = dynamic)

Validator:
  1. Locate UI-MAP.md in phase dir.
  2. Extract first ```json``` code block.
  3. Validate root node + walk all descendants.
  4. Per missing required field → BLOCK with node path + fix hint.

Usage:  verify-uimap-schema.py --phase 7.14.3
Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REQUIRED_FIELDS = (
    ("tag", str, "minLength=1"),
    ("classes", list, "array of strings"),
    ("children_count_order", dict, "{count: int, order: array}"),
    ("props_bound", dict, "object (may be empty)"),
    ("text_content_static", (str, type(None)), "string OR null"),
)


def _extract_json_block(md_path: Path) -> tuple[dict | None, int | None]:
    """Returns (parsed_json, line_number_of_block_start) or (None, line_or_None)."""
    if not md_path.exists():
        return None, None
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"```json\s*\n([\s\S]*?)\n```", text)
    if not m:
        return None, None
    line_no = text[:m.start()].count("\n") + 1
    try:
        return json.loads(m.group(1)), line_no
    except json.JSONDecodeError:
        return None, line_no


def _validate_node(node: dict, path: str, out: Output, file_str: str) -> None:
    if not isinstance(node, dict):
        out.add(Evidence(
            type="schema_violation",
            message=f"Node at {path} is not an object (got {type(node).__name__})",
            file=file_str, actual=type(node).__name__,
        ))
        return

    for field_name, expected_type, hint in REQUIRED_FIELDS:
        if field_name not in node:
            out.add(Evidence(
                type="schema_violation",
                message=f"Node at {path} missing required field '{field_name}' ({hint})",
                file=file_str,
                expected=hint,
                fix_hint=(
                    f"Add `\"{field_name}\":` to this node. See "
                    f"schemas/ui-map.v1.json for full 5-field-per-node spec (D-15)."
                ),
            ))
            continue
        val = node[field_name]
        if not isinstance(val, expected_type):
            type_names = (expected_type.__name__ if isinstance(expected_type, type)
                          else " | ".join(t.__name__ for t in expected_type))
            out.add(Evidence(
                type="schema_violation",
                message=(f"Node at {path} field '{field_name}' wrong type "
                         f"(got {type(val).__name__}, expected {type_names})"),
                file=file_str, expected=type_names, actual=type(val).__name__,
            ))

    # tag minLength=1 check
    tag = node.get("tag")
    if isinstance(tag, str) and not tag.strip():
        out.add(Evidence(
            type="schema_violation",
            message=f"Node at {path} has empty 'tag' string",
            file=file_str,
        ))

    # classes: each element must be string
    classes = node.get("classes")
    if isinstance(classes, list):
        for i, c in enumerate(classes):
            if not isinstance(c, str):
                out.add(Evidence(
                    type="schema_violation",
                    message=f"Node at {path} classes[{i}] not a string",
                    file=file_str, actual=type(c).__name__,
                ))

    # children_count_order: must have count + order
    cco = node.get("children_count_order")
    if isinstance(cco, dict):
        for sub in ("count", "order"):
            if sub not in cco:
                out.add(Evidence(
                    type="schema_violation",
                    message=f"Node at {path}.children_count_order missing '{sub}'",
                    file=file_str,
                ))
        if isinstance(cco.get("count"), bool) or not isinstance(cco.get("count"), int):
            if cco.get("count") is not None:
                out.add(Evidence(
                    type="schema_violation",
                    message=f"Node at {path}.children_count_order.count must be int",
                    file=file_str, actual=type(cco.get("count")).__name__,
                ))
        elif cco.get("count", 0) < 0:
            out.add(Evidence(
                type="schema_violation",
                message=f"Node at {path}.children_count_order.count must be ≥0",
                file=file_str, actual=cco["count"],
            ))
        if not isinstance(cco.get("order"), list):
            if cco.get("order") is not None:
                out.add(Evidence(
                    type="schema_violation",
                    message=f"Node at {path}.children_count_order.order must be array",
                    file=file_str,
                ))

    # Recurse into children if present
    children = node.get("children")
    if isinstance(children, list):
        for i, child in enumerate(children):
            _validate_node(child, f"{path}.children[{i}]", out, file_str)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="uimap-schema")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            out.add(Evidence(type="missing_file",
                             message=f"Phase dir not found for {args.phase}"))
            emit_and_exit(out)

        ui_map_path = phase_dir / "UI-MAP.md"
        if not ui_map_path.exists():
            out.add(Evidence(
                type="missing_file",
                message="UI-MAP.md not found",
                file=str(ui_map_path),
                fix_hint=(
                    "Run /vg:blueprint step 2b6b_ui_map. If phase has no UI changes, "
                    "set phase_has_ui_changes: false in CONTEXT.md frontmatter."
                ),
            ))
            emit_and_exit(out)

        data, line_no = _extract_json_block(ui_map_path)
        if data is None:
            out.add(Evidence(
                type="malformed_content",
                message="UI-MAP.md has no parseable ```json``` code block",
                file=str(ui_map_path),
                line=line_no,
                fix_hint=(
                    "UI-MAP.md MUST contain a fenced ```json``` block with the planner "
                    "tree. See schemas/ui-map.v1.json + commands/vg/_shared/templates/"
                    "UI-MAP-template.md for shape."
                ),
            ))
            emit_and_exit(out)

        if "version" not in data:
            out.add(Evidence(
                type="schema_violation",
                message="UI-MAP top-level missing 'version' field",
                file=str(ui_map_path),
                expected='"version": "1"',
            ))
        elif data.get("version") != "1":
            out.add(Evidence(
                type="schema_violation",
                message=f"UI-MAP version mismatch (got {data.get('version')!r})",
                file=str(ui_map_path), expected="1", actual=data.get("version"),
            ))

        root = data.get("root")
        if root is None:
            out.add(Evidence(
                type="schema_violation",
                message="UI-MAP missing required 'root' node",
                file=str(ui_map_path),
            ))
            emit_and_exit(out)

        _validate_node(root, "root", out, str(ui_map_path))

        if not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message="UI-MAP schema valid — all nodes pass 5-field-per-node lock",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
