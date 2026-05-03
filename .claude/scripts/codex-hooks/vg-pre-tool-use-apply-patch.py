#!/usr/bin/env python3
"""Block Codex apply_patch writes to VGFlow harness-controlled paths."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from vg_codex_hook_lib import compat_env, repo_root, safe_session_filename

PATCH_FILE_RE = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File:\s+(.+?)\s*$|^\*\*\* Move to:\s+(.+?)\s*$",
    re.MULTILINE,
)
PROTECTED_PATTERNS = (
    re.compile(r"(?:^|/)\.vg/runs/[^/]+/\.tasklist-projected\.evidence\.json$"),
    re.compile(r"(?:^|/)\.vg/runs/[^/]+/\.codex-spawn-manifest\.jsonl$"),
    re.compile(r"(?:^|/)\.vg/runs/[^/]+/\.spawn-count\.json$"),
    re.compile(r"(?:^|/)\.vg/runs/[^/]+/codex-spawns/.*"),
    re.compile(r"(?:^|/)\.vg/runs/[^/]+/evidence-.*\.json$"),
    re.compile(r"(?:^|/)\.vg/runs/[^/]+/.*evidence.*"),
    re.compile(r"(?:^|/)\.vg/phases/.*/\.step-markers/.*\.done$"),
    re.compile(r"(?:^|/)\.vg/events\.db$"),
    re.compile(r"(?:^|/)\.vg/events\.jsonl$"),
)


def _read_hook_input() -> dict[str, Any]:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def _tool_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("command", "patch", "input"):
            raw = value.get(key)
            if isinstance(raw, str):
                parts.append(raw)
        if not parts:
            try:
                parts.append(json.dumps(value, sort_keys=True))
            except Exception:
                pass
        return "\n".join(parts)
    return ""


def _patched_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in PATCH_FILE_RE.finditer(text):
        raw = match.group(1) or match.group(2) or ""
        cleaned = raw.strip().strip('"').strip("'")
        if cleaned:
            paths.append(cleaned)
    return paths


def _is_protected(path: str) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return any(pattern.search(normalized) for pattern in PROTECTED_PATTERNS)


def _active_run_id(root: Path, session_id: str | None) -> str:
    candidates = []
    if session_id:
        candidates.append(root / ".vg" / "active-runs" / f"{safe_session_filename(session_id)}.json")
    candidates.append(root / ".vg" / "current-run.json")
    for candidate in candidates:
        try:
            if candidate.is_file():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                run_id = data.get("run_id")
                if isinstance(run_id, str) and run_id:
                    return run_id
        except Exception:
            continue
    return "unknown"


def _write_block(root: Path, run_id: str, blocked_path: str) -> Path:
    gate_id = "PreToolUse-ApplyPatch-protected"
    block_dir = root / ".vg" / "blocks" / run_id
    block_dir.mkdir(parents=True, exist_ok=True)
    block_file = block_dir / f"{gate_id}.md"
    block_file.write_text(
        f"""# Block diagnostic - {gate_id}

## Cause
direct apply_patch write to protected path: {blocked_path}

This path holds harness-controlled evidence. Direct patch writes would forge
VGFlow's view of completed steps, events, or signed evidence.

## Required fix
- For evidence files: use `scripts/vg-orchestrator-emit-evidence-signed.py`
- For markers: use `vg-orchestrator mark-step <command> <step>`
- For events: use `vg-orchestrator emit-event <type> --payload <json>`

## After fix
```bash
vg-orchestrator emit-event vg.block.handled --gate {gate_id} \\
  --resolution "switched to signed helper"
```
""",
        encoding="utf-8",
    )
    return block_file


def _emit_block_event(root: Path, hook_input: dict[str, Any], cause: str) -> None:
    candidates = (
        root / ".claude" / "scripts" / "vg-orchestrator",
        root / "scripts" / "vg-orchestrator",
    )
    orch = next((candidate for candidate in candidates if (candidate / "__main__.py").exists()), None)
    if orch is None:
        return
    try:
        subprocess.run(
            [
                sys.executable,
                str(orch),
                "emit-event",
                "vg.block.fired",
                "--gate",
                "PreToolUse-ApplyPatch-protected",
                "--cause",
                cause,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(root),
            env=compat_env(hook_input, root),
        )
    except Exception:
        pass


def main() -> int:
    hook_input = _read_hook_input()
    text = _tool_text(hook_input.get("tool_input"))
    if not text:
        return 0
    protected = [path for path in _patched_paths(text) if _is_protected(path)]
    if not protected:
        return 0

    root = repo_root(hook_input)
    session_id = str(hook_input.get("session_id") or "")
    run_id = _active_run_id(root, session_id)
    blocked_path = protected[0]
    block_file = _write_block(root, run_id, blocked_path)
    cause = f"direct apply_patch write to protected path: {blocked_path}"
    _emit_block_event(root, hook_input, cause)
    sys.stderr.write(
        "PreToolUse-ApplyPatch-protected: "
        f"{cause}\n-> Read {block_file.relative_to(root)} for fix\n"
        "-> Use signed VGFlow helpers instead of patching harness evidence\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
