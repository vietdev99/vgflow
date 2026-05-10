"""v2.75.0 T1-T3 — split commands/vg/specs.md into _shared/specs/*.md sub-files.

Same pattern as scripts/v274_split_scope_review.py.
"""
from __future__ import annotations

from pathlib import Path
import sys


GROUPS = {
    "preflight": {
        "title": "### Preflight section (extracted v2.75.0 T1)",
        "shared_rel": "_shared/specs/preflight.md",
        "steps": ["create_task_tracker", "parse_args", "check_existing"],
        "blurb": "Includes 3 steps: create_task_tracker, parse_args, check_existing.",
    },
    "mode-and-draft": {
        "title": "### Mode + guided + draft (extracted v2.75.0 T2)",
        "shared_rel": "_shared/specs/mode-and-draft.md",
        "steps": ["choose_mode", "guided_questions", "generate_draft"],
        "blurb": "Includes 3 steps: choose_mode, guided_questions, generate_draft.",
    },
    "write-and-commit": {
        "title": "### Write + interface standards + commit (extracted v2.75.0 T3 — final)",
        "shared_rel": "_shared/specs/write-and-commit.md",
        "steps": [
            "write_specs",
            "write_interface_standards",
            "commit_and_next",
        ],
        "blurb": "Includes 3 steps: write_specs, write_interface_standards, commit_and_next.",
    },
}


CANONICAL_FILE = Path("commands/vg/specs.md")
MIRROR_FILE = Path(".claude/commands/vg/specs.md")
CANONICAL_VG_DIR = Path("commands/vg")
MIRROR_VG_DIR = Path(".claude/commands/vg")


def find_step_block(data: bytes, step_name: str) -> tuple[int, int]:
    open_tag = f'<step name="{step_name}">'.encode("ascii")
    close_tag = b"</step>"
    start = data.find(open_tag)
    if start < 0:
        raise SystemExit(f"missing opening tag for step {step_name!r}")
    close_search_from = start + len(open_tag)
    close = data.find(close_tag, close_search_from)
    if close < 0:
        raise SystemExit(f"unclosed step {step_name!r}")
    end = close + len(close_tag)
    if data[end:end + 2] == b"\r\n":
        end += 2
    elif data[end:end + 1] == b"\n":
        end += 1
    return start, end


def split_group(group_key: str) -> tuple[int, int, int]:
    if group_key not in GROUPS:
        raise SystemExit(f"unknown group {group_key!r}; valid: {list(GROUPS)}")
    g = GROUPS[group_key]

    raw = CANONICAL_FILE.read_bytes()
    lines_before = raw.count(b"\n")

    spans: list[tuple[int, int]] = []
    for step in g["steps"]:
        spans.append(find_step_block(raw, step))

    for (s1, e1), (s2, _e2) in zip(spans, spans[1:]):
        between = raw[e1:s2]
        if between.strip() != b"":
            raise SystemExit(
                f"non-whitespace content between steps {g['steps']} for group "
                f"{group_key!r} — refusing to split blindly. Found: {between!r}"
            )

    block_start = spans[0][0]
    block_end = spans[-1][1]
    extracted = raw[block_start:block_end]

    sub_header = (
        f"<!-- v2.75.0 T1-T3 extraction — verbatim step blocks from "
        f"commands/vg/specs.md -->\r\n"
        f"<!-- Group: {group_key} | Steps: {', '.join(g['steps'])} -->\r\n"
        f"\r\n"
        f"<process>\r\n"
        f"\r\n"
    ).encode("utf-8")
    sub_footer = b"\r\n</process>\r\n"
    sub_body = sub_header + extracted + sub_footer

    steps_csv = ", ".join(g["steps"])
    routing = (
        f"{g['title']}\r\n"
        f"\r\n"
        f"Read `{g['shared_rel']}` and follow it exactly.\r\n"
        f"{g['blurb']}\r\n"
        f"\r\n"
        f"Step coverage: {steps_csv}.\r\n"
        f"\r\n"
    ).encode("utf-8")

    new_raw = raw[:block_start] + routing + raw[block_end:]
    lines_after = new_raw.count(b"\n")

    canonical_sub = CANONICAL_VG_DIR / Path(g["shared_rel"])
    canonical_sub.parent.mkdir(parents=True, exist_ok=True)
    canonical_sub.write_bytes(sub_body)

    mirror_sub = MIRROR_VG_DIR / Path(g["shared_rel"])
    mirror_sub.parent.mkdir(parents=True, exist_ok=True)
    mirror_sub.write_bytes(sub_body)

    CANONICAL_FILE.write_bytes(new_raw)
    MIRROR_FILE.write_bytes(new_raw)

    sub_lines = sub_body.count(b"\n")
    return lines_before, lines_after, sub_lines


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 scripts/v275_split_specs.py <group>", file=sys.stderr)
        print(f"valid groups: {list(GROUPS)}", file=sys.stderr)
        return 2
    group_key = argv[1]
    before, after, sub = split_group(group_key)
    print(
        f"{group_key}: specs.md {before} -> {after} lines | "
        f"sub-file {GROUPS[group_key]['shared_rel']} = {sub} lines"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
