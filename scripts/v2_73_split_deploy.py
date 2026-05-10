"""v2.73.0 helper — split deploy.md by step boundaries (CRLF-preserving).

Usage:
  python scripts/v2_73_split_deploy.py <task>

Tasks:
  T1  preflight           steps 0_parse_and_validate .. 0a_env_select_and_confirm
  T2  execute             step  1_deploy_per_env
  T3  persist-and-close   steps 2_persist_summary .. complete

Each task:
  - reads commands/vg/deploy.md (canonical)
  - locates the block boundaries by step tags
  - writes commands/vg/_shared/deploy/<name>.md with the extracted block
  - rewrites commands/vg/deploy.md, replacing the block with a slim routing entry
  - copies BOTH files byte-identically into .claude/commands/vg/...
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANON = REPO / "commands" / "vg" / "deploy.md"
MIRROR = REPO / ".claude" / "commands" / "vg" / "deploy.md"
SHARED_CANON = REPO / "commands" / "vg" / "_shared" / "deploy"
SHARED_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "deploy"

# Map of task name -> (sub-file basename, first step name, last step name, slim routing block)
TASKS = {
    "preflight": (
        "preflight",
        "0_parse_and_validate",
        "0a_env_select_and_confirm",
        ("### Preflight section (extracted v2.73.0 T1)\r\n"
         "\r\n"
         "Read `_shared/deploy/preflight.md` and follow it exactly.\r\n"
         "Includes 2 steps: 0_parse_and_validate, 0a_env_select_and_confirm.\r\n"),
    ),
    "execute": (
        "execute",
        "1_deploy_per_env",
        "1_deploy_per_env",
        ("### Execute per-env (extracted v2.73.0 T2)\r\n"
         "\r\n"
         "Read `_shared/deploy/execute.md` and follow it exactly.\r\n"
         "Includes 1 step: 1_deploy_per_env.\r\n"),
    ),
    "persist-and-close": (
        "persist-and-close",
        "2_persist_summary",
        "complete",
        ("### Persist + close (extracted v2.73.0 T3 — final)\r\n"
         "\r\n"
         "Read `_shared/deploy/persist-and-close.md` and follow it exactly.\r\n"
         "Includes 2 steps: 2_persist_summary, complete.\r\n"),
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
        raise SystemExit(f"step tag {step_name!r} not found in deploy.md")
    while idx > 0 and data[idx - 1] != ord('\n'):
        idx -= 1
    return idx

def _find_step_close(data: bytes, after_offset: int) -> int:
    """Find offset just past `</step>\\r\\n` after the given offset."""
    close_tag = b"</step>"
    idx = data.find(close_tag, after_offset)
    if idx == -1:
        raise SystemExit("</step> close tag not found")
    end = idx + len(close_tag)
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

    new_data = data[:start] + routing_bytes + data[end:]

    sub_path = SHARED_CANON / f"{base}.md"
    _write_bytes(sub_path, extracted)

    mirror_sub = SHARED_MIRROR / f"{base}.md"
    _write_bytes(mirror_sub, extracted)

    _write_bytes(CANON, new_data)
    _write_bytes(MIRROR, new_data)

    canon_after = _read_bytes(CANON)
    mirror_after = _read_bytes(MIRROR)
    sub_after = _read_bytes(sub_path)
    mirror_sub_after = _read_bytes(mirror_sub)
    assert canon_after == mirror_after, "deploy.md mirror drift"
    assert sub_after == mirror_sub_after, f"{base}.md mirror drift"

    nl = canon_after.count(b"\n")
    print(f"[ok] task={task} extracted_bytes={len(extracted)} new_canon_lines={nl}")
    print(f"     sub_file={sub_path.relative_to(REPO)} ({len(extracted)} bytes)")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: v2_73_split_deploy.py <preflight|execute|persist-and-close>")
    split(sys.argv[1])
