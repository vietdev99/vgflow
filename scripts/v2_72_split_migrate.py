"""v2.72.0 helper — split migrate.md by step boundaries (CRLF-preserving).

Usage:
  python scripts/v2_72_split_migrate.py <task>

Tasks:
  T1  preflight                lines covering 1_parse_args .. 3_backup_originals
  T2  enrich                   lines covering 4_enrich_context .. 5_generate_contracts
  T3  goals-plans              lines covering 6_generate_goals .. 7_attribute_plans
  T4  pipeline-and-validate    lines covering 8_write_pipeline_state .. 9_validate_and_report

Each task:
  - reads commands/vg/migrate.md (canonical)
  - locates the block boundaries by step tags
  - writes commands/vg/_shared/migrate/<name>.md with the extracted block
  - rewrites commands/vg/migrate.md, replacing the block with a slim routing entry
  - copies BOTH files byte-identically into .claude/commands/vg/...
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANON = REPO / "commands" / "vg" / "migrate.md"
MIRROR = REPO / ".claude" / "commands" / "vg" / "migrate.md"
SHARED_CANON = REPO / "commands" / "vg" / "_shared" / "migrate"
SHARED_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "migrate"

# Map of task name -> (sub-file basename, first step name, last step name, slim routing block)
TASKS = {
    "preflight": (
        "preflight",
        "1_parse_args",
        "3_backup_originals",
        ("### Preflight section (extracted v2.72.0 T1)\r\n"
         "\r\n"
         "Read `_shared/migrate/preflight.md` and follow it exactly.\r\n"
         "Includes 3 steps: 1_parse_args, 2_detect_artifacts, 3_backup_originals.\r\n"),
    ),
    "enrich": (
        "enrich",
        "4_enrich_context",
        "5_generate_contracts",
        ("### Enrich section (extracted v2.72.0 T2)\r\n"
         "\r\n"
         "Read `_shared/migrate/enrich.md` and follow it exactly.\r\n"
         "Includes 2 steps: 4_enrich_context, 5_generate_contracts.\r\n"),
    ),
    "goals-plans": (
        "goals-plans",
        "6_generate_goals",
        "7_attribute_plans",
        ("### Goals + plans (extracted v2.72.0 T3)\r\n"
         "\r\n"
         "Read `_shared/migrate/goals-plans.md` and follow it exactly.\r\n"
         "Includes 3 steps: 6_generate_goals, 6_5_link_plan_goals, 7_attribute_plans.\r\n"),
    ),
    "pipeline-and-validate": (
        "pipeline-and-validate",
        "8_write_pipeline_state",
        "9_validate_and_report",
        ("### Pipeline + validate (extracted v2.72.0 T4 — final)\r\n"
         "\r\n"
         "Read `_shared/migrate/pipeline-and-validate.md` and follow it exactly.\r\n"
         "Includes 3 steps: 8_write_pipeline_state, 8b_backfill_infra, 9_validate_and_report.\r\n"),
    ),
}


def _read_bytes(p: Path) -> bytes:
    return p.read_bytes()


def _write_bytes(p: Path, data: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def _find_step_offsets(data: bytes, step_name: str) -> int:
    """Return byte offset of `<step name="STEP_NAME">` line start."""
    pattern = f'<step name="{step_name}">'.encode("utf-8")
    idx = data.find(pattern)
    if idx == -1:
        raise SystemExit(f"step tag {step_name!r} not found in migrate.md")
    # Walk back to start of the line
    while idx > 0 and data[idx - 1] != ord('\n'):
        idx -= 1
    return idx


def _find_step_close(data: bytes, after_offset: int) -> int:
    """Find offset just past `</step>\r\n` after the given offset."""
    close_tag = b"</step>"
    idx = data.find(close_tag, after_offset)
    if idx == -1:
        raise SystemExit("</step> close tag not found")
    end = idx + len(close_tag)
    # Consume the trailing line ending (CRLF or LF)
    if data[end:end + 2] == b"\r\n":
        end += 2
    elif data[end:end + 1] == b"\n":
        end += 1
    return end


def split(task: str) -> None:
    if task not in TASKS:
        raise SystemExit(f"Unknown task {task!r}. Choose from: {list(TASKS)}")
    base, first_step, last_step, routing_text = TASKS[task]

    data = _read_bytes(CANON)

    start = _find_step_offsets(data, first_step)
    last_open = _find_step_offsets(data, last_step)
    end = _find_step_close(data, last_open)

    extracted = data[start:end]
    routing_bytes = routing_text.encode("utf-8")

    # The slim routing entry should produce a clean blank line afterward.
    # The extracted block already ended with `</step>\r\n`; after that there
    # was probably a blank line (`\r\n`) before the next `<step ...>` block.
    # We want the post-split file to keep that structure: routing_text +
    # the original separator that followed the extracted block.
    new_data = data[:start] + routing_bytes + data[end:]

    sub_path = SHARED_CANON / f"{base}.md"
    _write_bytes(sub_path, extracted)

    # Mirror sub-file
    mirror_sub = SHARED_MIRROR / f"{base}.md"
    _write_bytes(mirror_sub, extracted)

    # Write canonical migrate.md and mirror
    _write_bytes(CANON, new_data)
    _write_bytes(MIRROR, new_data)

    # Sanity diff
    canon_after = _read_bytes(CANON)
    mirror_after = _read_bytes(MIRROR)
    sub_after = _read_bytes(sub_path)
    mirror_sub_after = _read_bytes(mirror_sub)
    assert canon_after == mirror_after, "migrate.md mirror drift"
    assert sub_after == mirror_sub_after, f"{base}.md mirror drift"

    nl = canon_after.count(b"\n")
    print(f"[ok] task={task} extracted_bytes={len(extracted)} new_canon_lines={nl}")
    print(f"     sub_file={sub_path.relative_to(REPO)} ({len(extracted)} bytes)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: v2_72_split_migrate.py <preflight|enrich|goals-plans|pipeline-and-validate>")
    split(sys.argv[1])
