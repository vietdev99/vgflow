import json, os, subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1].parent / "scripts/hooks/vg-pre-tool-use-write.sh"

PROTECTED = [
    ".vg/runs/r1/.tasklist-projected.evidence.json",
    ".vg/runs/r1/evidence-something.json",
    ".vg/phases/01-foo/.step-markers/blueprint/2a_plan.done",
    ".vg/events.db",
    ".vg/events.jsonl",
]
ALLOWED = [
    "src/app/page.tsx",
    "docs/notes.md",
    ".vg/runs/r1/tasklist-contract.json",  # contract is NOT protected (orchestrator writes it directly via emit-tasklist.py)
]


def _run_hook(file_path: str, tool_name: str = "Write"):
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"file_path": file_path}})
    return subprocess.run(
        ["bash", str(HOOK)],
        input=payload, capture_output=True, text=True,
    )


def test_protected_paths_blocked():
    for path in PROTECTED:
        result = _run_hook(path, "Write")
        assert result.returncode == 2, f"expected block for {path}, got rc={result.returncode}"
        assert "vg-orchestrator-emit-evidence-signed" in result.stderr.lower() or "protected" in result.stderr.lower()


def test_protected_paths_blocked_for_edit():
    for path in PROTECTED:
        result = _run_hook(path, "Edit")
        assert result.returncode == 2, f"expected block for {path} (Edit)"


def test_allowed_paths_pass():
    for path in ALLOWED:
        result = _run_hook(path, "Write")
        assert result.returncode == 0, f"expected pass for {path}, got rc={result.returncode}, stderr={result.stderr}"
