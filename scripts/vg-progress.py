#!/usr/bin/env python3
"""
vg-progress.py — Deterministic phase status scanner for /vg:progress.

Replaces LLM-driven scan-and-guess with grep-based ground truth:
  1. Reads PIPELINE-STATE.json if present (authoritative)
  2. Falls back to artifact existence + content verdicts
  3. Outputs JSON consumed by progress.md renderer

Exit 0 always. Errors embedded in output JSON.

Usage:
  python vg-progress.py                      # all phases
  python vg-progress.py --phase 07.10.2      # single phase
  python vg-progress.py --planning .vg       # custom planning dir
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Force UTF-8 stdout/stderr on Windows (default cp1252/cp1258 crashes on emoji ✅🔄⬜❌).
# Python 3.7+ supports reconfigure(); no-op elsewhere.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# --- Verdict detection ---
# Markdown decorations vary: `**Verdict:** ACCEPTED`, `## Verdict: PASSED`,
# `- **Overall Verdict: PASSED**`, `status: "ACCEPTED"`, `Status: complete`.
# Approach: normalize each line by stripping `*`, `#`, `-`, whitespace, quotes
# around the signal word, then match the trio (keyword, separator, value).

VERDICT_KEYWORDS = ("verdict", "status", "uat result", "overall verdict")


def _normalize_line(line: str) -> str:
    """Strip markdown decoration for verdict detection."""
    # Remove leading markdown list/heading markers
    line = re.sub(r"^\s*[#\-*>]+\s*", "", line)
    # Strip bold/italic/quote marks throughout
    line = line.replace("**", "").replace("__", "").replace('"', "").replace("'", "")
    return line.strip()


def _extract_frontmatter(text: str) -> str | None:
    """Return YAML frontmatter block between leading --- fences, or None."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, min(len(lines), 40)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


def _scan_verdicts(text: str) -> list[tuple[str, str]]:
    """Return list of (keyword, value) pairs.

    Priority order:
      1. YAML frontmatter (authoritative — overall verdict)
      2. First ~100 body lines (summary/verdict sections)
    Ignores per-test `status:` lines deeper in file.
    """
    out: list[tuple[str, str]] = []

    def harvest(scope: str) -> None:
        for raw in scope.splitlines():
            n = _normalize_line(raw)
            if ":" not in n:
                continue
            lhs, _, rhs = n.partition(":")
            lhs_low = lhs.strip().lower()
            if not any(k in lhs_low for k in VERDICT_KEYWORDS):
                continue
            value = rhs.strip().split()[0].rstrip(",;.").upper() if rhs.strip() else ""
            out.append((lhs_low, value))

    fm = _extract_frontmatter(text)
    if fm is not None:
        harvest(fm)
        if out:
            return out  # frontmatter wins

    # Fallback: scan first 100 lines of body (title, summary, verdict blocks
    # usually live there; per-test `status:` lines are deeper in tables).
    head = "\n".join(text.splitlines()[:100])
    harvest(head)
    return out

# Matrix summary line: "Ready: 36 | Blocked: 0 | Unreachable: 0"
MATRIX_COUNTS = re.compile(
    r"Ready:\s*(\d+)\s*\|\s*Blocked:\s*(\d+)\s*\|\s*Unreachable:\s*(\d+)",
    re.IGNORECASE,
)


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def uat_status(uat_file: Path) -> str:
    """Return ACCEPTED | FAILED | UNKNOWN | MISSING."""
    if not uat_file.exists():
        return "MISSING"
    verdicts = _scan_verdicts(read_text(uat_file))
    # Check failures first (stronger signal)
    for _, v in verdicts:
        if v in ("FAILED", "REJECTED"):
            return "FAILED"
    for _, v in verdicts:
        if v in ("ACCEPTED", "PASSED", "COMPLETE"):
            return "ACCEPTED"
    return "UNKNOWN"


def sandbox_status(sb_file: Path) -> str:
    """Return PASSED | GAPS_FOUND | FAILED | UNKNOWN | MISSING."""
    if not sb_file.exists():
        return "MISSING"
    verdicts = _scan_verdicts(read_text(sb_file))
    for _, v in verdicts:
        if v == "FAILED":
            return "FAILED"
    for _, v in verdicts:
        if v == "GAPS_FOUND":
            return "GAPS_FOUND"
    for _, v in verdicts:
        if v in ("PASSED", "COMPLETE", "ACCEPTED"):
            return "PASSED"
    return "UNKNOWN"


def matrix_gate(matrix_file: Path) -> dict[str, Any]:
    """Return dict with ready/blocked/unreachable counts and gate PASS/FAIL."""
    if not matrix_file.exists():
        return {"present": False}
    text = read_text(matrix_file)
    m = MATRIX_COUNTS.search(text)
    if not m:
        return {"present": True, "parsed": False}
    ready, blocked, unreachable = (int(x) for x in m.groups())
    gate = "PASS" if (blocked == 0 and unreachable == 0) else "FAIL"
    return {
        "present": True,
        "parsed": True,
        "ready": ready,
        "blocked": blocked,
        "unreachable": unreachable,
        "total": ready + blocked + unreachable,
        "gate": gate,
    }


def first_match(dir_path: Path, patterns: list[str]) -> Path | None:
    for pat in patterns:
        for p in dir_path.glob(pat):
            if p.is_file():
                return p
    return None


def any_match(dir_path: Path, patterns: list[str]) -> bool:
    return first_match(dir_path, patterns) is not None


def count_matches(dir_path: Path, patterns: list[str]) -> int:
    n = 0
    for pat in patterns:
        n += sum(1 for p in dir_path.glob(pat) if p.is_file())
    return n


def scan_phase(phase_dir: Path) -> dict[str, Any]:
    name = phase_dir.name
    phase_num_match = re.match(r"^(\d+(?:\.\d+)*)", name)
    phase_num = phase_num_match.group(1) if phase_num_match else name

    # --- Artifact detection ---
    artifacts = {
        "specs": (phase_dir / "SPECS.md").exists(),
        "context": (phase_dir / "CONTEXT.md").exists(),
        "plan": any_match(phase_dir, ["PLAN.md", "PLAN*.md", "*-PLAN*.md"]),
        "api_contracts": (phase_dir / "API-CONTRACTS.md").exists(),
        "test_goals": (phase_dir / "TEST-GOALS.md").exists(),
        "summary": any_match(phase_dir, ["SUMMARY.md", "SUMMARY*.md", "*-SUMMARY*.md"]),
        "runtime_map": (phase_dir / "RUNTIME-MAP.json").exists(),
        "goal_matrix": (phase_dir / "GOAL-COVERAGE-MATRIX.md").exists(),
        "sandbox": any_match(phase_dir, ["SANDBOX-TEST.md", "*SANDBOX-TEST.md"]),
        "uat": any_match(phase_dir, ["UAT.md", "*UAT.md", "*HUMAN-UAT*.md"]),
        "pipeline_state": (phase_dir / "PIPELINE-STATE.json").exists(),
    }

    # --- Content verdicts ---
    sb_file = first_match(phase_dir, ["SANDBOX-TEST.md", "*SANDBOX-TEST.md"])
    uat_file = first_match(phase_dir, ["UAT.md", "*UAT.md", "*HUMAN-UAT*.md"])
    matrix_file = phase_dir / "GOAL-COVERAGE-MATRIX.md"

    content = {
        "sandbox": sandbox_status(sb_file) if sb_file else "MISSING",
        "uat": uat_status(uat_file) if uat_file else "MISSING",
        "matrix": matrix_gate(matrix_file),
    }

    # --- Pipeline state (authoritative if present) ---
    state = None
    if artifacts["pipeline_state"]:
        try:
            state = json.loads(read_text(phase_dir / "PIPELINE-STATE.json"))
        except json.JSONDecodeError as e:
            state = {"_error": f"parse failed: {e}"}

    # --- Compute step status icons per step ---
    steps = compute_steps(artifacts, content, state)

    # --- Monotonic invariant ---
    # If a later step is DONE, earlier steps must be DONE too (phase couldn't
    # have reached that gate otherwise). Promotes upstream from 🔄/❌ → ✅ when
    # matrix format is unusual but UAT already accepted the phase.
    _apply_monotonic(steps)

    # --- Determine current step + next command ---
    step_order = ["specs", "scope", "blueprint", "build", "review", "test", "accept"]
    done_count = sum(1 for s in step_order if steps[s]["status"] == "done")
    current = next((s for s in step_order if steps[s]["status"] not in ("done", "skipped")), None)

    # Label
    failed = [s for s in step_order if steps[s]["status"] == "failed"]
    in_progress = [s for s in step_order if steps[s]["status"] == "in_progress"]
    if all(steps[s]["status"] in ("done", "skipped") for s in step_order):
        label = "DONE"
    elif failed:
        label = "BLOCKED"
    elif in_progress or current == "specs":
        label = "NOT_STARTED" if not any(steps[s]["status"] == "done" for s in step_order) else "IN_PROGRESS"
    else:
        label = "IN_PROGRESS"

    # Next command from current step
    next_cmd_map = {
        "specs": f"/vg:specs {phase_num}",
        "scope": f"/vg:scope {phase_num}",
        "blueprint": f"/vg:blueprint {phase_num}",
        "build": f"/vg:build {phase_num}",
        "review": f"/vg:review {phase_num}",
        "test": f"/vg:test {phase_num}",
        "accept": f"/vg:accept {phase_num}",
    }
    next_cmd = next_cmd_map.get(current, "—") if current else "—"

    return {
        "phase": phase_num,
        "dir": str(phase_dir).replace("\\", "/"),
        "name": name,
        "artifacts": artifacts,
        "content": content,
        "pipeline_state": state,
        "steps": steps,
        "done_count": done_count,
        "total_steps": len(step_order),
        "label": label,
        "current_step": current,
        "next_command": next_cmd,
    }


def _apply_monotonic(steps: dict[str, dict]) -> None:
    """If step N is done, promote all steps < N to done (invariant: phase
    couldn't reach step N otherwise). Source is upgraded to 'inferred'."""
    order = ["specs", "scope", "blueprint", "build", "review", "test", "accept"]
    last_done = -1
    for i, s in enumerate(order):
        if steps[s]["status"] == "done":
            last_done = i
    if last_done <= 0:
        return
    for i in range(last_done):
        s = order[i]
        if steps[s]["status"] not in ("done", "skipped"):
            prev_reason = steps[s].get("reason", "")
            steps[s].update({
                "status": "done",
                "icon": "✅",
                "source": "inferred",
                "reason": f"inferred from downstream {order[last_done]}=done" + (f" (was: {prev_reason})" if prev_reason else ""),
            })


def compute_steps(
    artifacts: dict, content: dict, state: dict | None
) -> dict[str, dict[str, str]]:
    """Compute status per step. Prefer PIPELINE-STATE if available."""
    step_order = ["specs", "scope", "blueprint", "build", "review", "test", "accept"]

    # State-driven path
    if state and "steps" in state and not state.get("_error"):
        result = {}
        for s in step_order:
            entry = state["steps"].get(s, {"status": "pending"})
            status = entry.get("status", "pending")
            # Normalize to our vocab
            if status == "done":
                icon = "✅"
            elif status == "skipped":
                icon = "⏭"
            elif status == "in_progress":
                icon = "🔄"
            elif status == "failed":
                icon = "❌"
            else:
                icon = "⬜"
            result[s] = {
                "status": status,
                "icon": icon,
                "source": "state",
                "reason": entry.get("reason", ""),
            }
        return result

    # Artifact + content fallback
    def mk(status: str, icon: str, reason: str = "") -> dict:
        return {"status": status, "icon": icon, "source": "artifact", "reason": reason}

    result = {}

    # Step 0: specs
    result["specs"] = mk("done", "✅") if artifacts["specs"] else mk("pending", "⬜")

    # Step 1: scope
    result["scope"] = mk("done", "✅") if artifacts["context"] else mk("pending", "⬜")

    # Step 2: blueprint — require PLAN + API-CONTRACTS
    if artifacts["plan"] and artifacts["api_contracts"]:
        result["blueprint"] = mk("done", "✅")
    elif artifacts["plan"] or artifacts["api_contracts"]:
        result["blueprint"] = mk("in_progress", "🔄", "partial")
    else:
        result["blueprint"] = mk("pending", "⬜")

    # Step 3: build
    result["build"] = mk("done", "✅") if artifacts["summary"] else mk("pending", "⬜")

    # Step 4: review — RUNTIME-MAP + matrix gate=PASS
    matrix = content["matrix"]
    if artifacts["runtime_map"] and matrix.get("gate") == "PASS":
        result["review"] = mk("done", "✅", f"matrix {matrix.get('ready')}/{matrix.get('total')} PASS")
    elif artifacts["runtime_map"] and matrix.get("gate") == "FAIL":
        result["review"] = mk(
            "failed",
            "❌",
            f"matrix gate FAIL: {matrix.get('blocked',0)} blocked, {matrix.get('unreachable',0)} unreachable",
        )
    elif artifacts["runtime_map"]:
        result["review"] = mk("in_progress", "🔄", "runtime-map present, matrix unclear")
    else:
        result["review"] = mk("pending", "⬜")

    # Step 5: test — sandbox verdict
    sb = content["sandbox"]
    if sb == "PASSED":
        result["test"] = mk("done", "✅")
    elif sb == "GAPS_FOUND":
        result["test"] = mk("in_progress", "🔄", "gaps found")
    elif sb == "FAILED":
        result["test"] = mk("failed", "❌")
    elif sb == "UNKNOWN":
        result["test"] = mk("in_progress", "🔄", "verdict unclear")
    else:
        result["test"] = mk("pending", "⬜")

    # Step 6: accept — UAT verdict
    uat = content["uat"]
    if uat == "ACCEPTED":
        result["accept"] = mk("done", "✅")
    elif uat == "FAILED":
        result["accept"] = mk("failed", "❌")
    elif uat == "UNKNOWN":
        result["accept"] = mk("in_progress", "🔄", "UAT present, verdict unclear")
    else:
        result["accept"] = mk("pending", "⬜")

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic phase scanner for /vg:progress")
    ap.add_argument("--planning", default=".vg", help="planning dir (default .vg)")
    ap.add_argument("--phase", help="scan single phase (matches dir prefix)")
    ap.add_argument("--output", choices=["json", "text"], default="json")
    args = ap.parse_args()

    planning = Path(args.planning)
    phases_dir = planning / "phases"
    if not phases_dir.is_dir():
        print(json.dumps({"error": f"phases dir not found: {phases_dir}"}))
        return 0

    # Read STATE.md current_phase if present
    state_md = planning / "STATE.md"
    current_phase = None
    if state_md.exists():
        text = read_text(state_md)
        m = re.search(r"Phase:\s*([\d\.]+)", text)
        if m:
            current_phase = m.group(1)

    phase_dirs = sorted([d for d in phases_dir.iterdir() if d.is_dir()], key=lambda d: natural_key(d.name))
    if args.phase:
        phase_dirs = [d for d in phase_dirs if d.name.startswith(args.phase + "-") or d.name == args.phase]

    phases = [scan_phase(d) for d in phase_dirs]

    out = {
        "planning_dir": str(planning).replace("\\", "/"),
        "current_phase_from_state": current_phase,
        "phase_count": len(phases),
        "phases": phases,
    }

    if args.output == "json":
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        for p in phases:
            pipeline = " → ".join(
                f"{p['steps'][s]['icon']} {s}"
                for s in ["specs", "scope", "blueprint", "build", "review", "test", "accept"]
            )
            print(f"Phase {p['phase']}: {p['name']}   [{p['done_count']}/7]  {p['label']}")
            print(f"  Pipeline: {pipeline}")
            print(f"  Next: {p['next_command']}")
            print()

    return 0


def natural_key(s: str):
    """Sort '07.2' before '07.10'."""
    parts = re.split(r"(\d+)", s)
    return [int(p) if p.isdigit() else p for p in parts]


if __name__ == "__main__":
    sys.exit(main())
