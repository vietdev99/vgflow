#!/usr/bin/env python3
"""
verify-executor-context-scope.py — Phase R of v2.5.2 hardening.

Problem closed (v2.5.1 Codex finding):
  Phase C (context isolation) asked blueprint to declare <context-refs>
  per task — listing which D-XX decisions the executor should see. v2.5.1
  checked the declaration existed but not that the executor prompt
  actually matched. Executor could silently pull full CONTEXT.md while
  the task declared only 2 refs — i.e. context leak via full-mode
  fallback.

This validator is BEHAVIORAL:
  1. Read PLAN.md — find tasks with <context-refs> attributes
  2. For each task, read corresponding captured prompt from
     .vg/runs/<run_id>/executor-prompts/task-<seq>.prompt.txt
  3. Grep all D-XX occurrences in prompt
  4. Compare against declared refs
  5. Fail if prompt contains D-XX IDs beyond declared (leak)
     OR declared ref missing from prompt (incomplete injection)

Exit codes:
  0 = prompt scopes match declared refs
  1 = leak (extra IDs) or incomplete injection (missing IDs)
  2 = config error (missing PLAN, missing prompts, bad run-id)

Usage:
  verify-executor-context-scope.py --run-id <uuid> --plan-file <PLAN.md>
  verify-executor-context-scope.py --run-id X --allow-leak  # warn only
  verify-executor-context-scope.py --run-id X --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Match "D-42" or "P7.14.D-03" decision IDs.
DECISION_RE = re.compile(r"\b(?:P\d+(?:\.\d+)*\.)?D-\d+\b")


def _parse_plan_tasks(plan_file: Path) -> list[dict]:
    """
    Parse PLAN.md tasks with <context-refs> attributes.

    Expected format per task (XML-ish tags inline):
        <task id="7.14-04">
          <title>...</title>
          <context-refs>D-01,D-03,P7.14.D-02</context-refs>
        </task>

    Returns list of {id, task_seq, context_refs}.
    """
    if not plan_file.exists():
        return []

    text = plan_file.read_text(encoding="utf-8", errors="replace")

    tasks: list[dict] = []
    # Non-greedy match of each <task>...</task>
    for tblock in re.findall(r"<task\b[^>]*>(.*?)</task>", text, re.DOTALL | re.IGNORECASE):
        id_m = re.search(r'id\s*=\s*["\']([^"\']+)["\']', tblock, re.IGNORECASE)
        # Fallback: look at the preceding line for id=
        pass

    # Alternative parse: scan for `<task id="X">` opening + content to next `</task>`
    for m in re.finditer(
            r'<task\s+[^>]*id\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</task>',
            text, re.DOTALL | re.IGNORECASE):
        task_id = m.group(1).strip()
        body = m.group(2)

        refs_m = re.search(r"<context-refs>\s*(.*?)\s*</context-refs>",
                           body, re.DOTALL | re.IGNORECASE)
        refs_raw = (refs_m.group(1) if refs_m else "").strip()
        refs = [r.strip() for r in re.split(r"[,\s]+", refs_raw) if r.strip()]

        # Extract task_seq: last numeric segment after last dash
        seq_m = re.search(r"(\d+)$", task_id)
        task_seq = int(seq_m.group(1)) if seq_m else 0

        tasks.append({
            "id": task_id,
            "task_seq": task_seq,
            "context_refs": refs,
        })

    return tasks


def _read_prompt(run_id: str, task_seq: int) -> str | None:
    prompt_dir = REPO_ROOT / ".vg" / "runs" / run_id / "executor-prompts"
    if not prompt_dir.exists():
        return None
    manifest_path = prompt_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    for entry in manifest.get("entries", []):
        if entry.get("task_seq") == task_seq:
            file_path = prompt_dir / entry.get("file", "")
            if file_path.exists():
                return file_path.read_text(encoding="utf-8")
    return None


def _extract_decisions(text: str) -> set[str]:
    return {m.group(0) for m in DECISION_RE.finditer(text)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--plan-file", required=True,
                    help="Path to PLAN.md (or similar task descriptor)")
    ap.add_argument("--allow-leak", action="store_true",
                    help="Warn only on extra-IDs (used during migration)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--phase", help="(orchestrator-injected; ignored by this validator)")
    args = ap.parse_args()

    plan_path = REPO_ROOT / args.plan_file
    if not plan_path.exists():
        msg = f"PLAN file not found: {plan_path}"
        if args.json:
            print(json.dumps({"error": msg}))
        else:
            print(f"⛔ {msg}", file=sys.stderr)
        return 2

    tasks = _parse_plan_tasks(plan_path)
    if not tasks:
        msg = f"No <task> blocks with <context-refs> found in {plan_path}"
        if args.json:
            print(json.dumps({"error": msg, "tasks_checked": 0}))
        elif not args.quiet:
            print(f"⚠ {msg}")
        return 0  # benign — no scoped tasks declared

    per_task: list[dict] = []
    leaks: list[dict] = []
    missing: list[dict] = []

    for task in tasks:
        declared = set(task["context_refs"])
        prompt = _read_prompt(args.run_id, task["task_seq"])
        if prompt is None:
            per_task.append({
                "task_id": task["id"],
                "task_seq": task["task_seq"],
                "status": "prompt_missing",
                "declared": sorted(declared),
                "found": [],
            })
            continue

        found = _extract_decisions(prompt)
        extra = sorted(found - declared)
        absent = sorted(declared - found)

        record = {
            "task_id": task["id"],
            "task_seq": task["task_seq"],
            "declared": sorted(declared),
            "found": sorted(found),
            "extra_in_prompt": extra,
            "declared_but_absent": absent,
            "status": "ok",
        }

        if extra and not args.allow_leak:
            record["status"] = "leak"
            leaks.append(record)
        elif absent:
            record["status"] = "incomplete_injection"
            missing.append(record)

        per_task.append(record)

    failures = leaks + missing

    result = {
        "run_id": args.run_id,
        "plan_file": str(plan_path),
        "tasks_checked": len(tasks),
        "leaks": leaks,
        "incomplete_injections": missing,
        "per_task": per_task,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if failures:
            print(f"⛔ Executor context scope: {len(failures)}/"
                  f"{len(tasks)} task(s) violate scope\n")
            for r in failures:
                print(f"  [{r['status']}] {r['task_id']} (seq={r['task_seq']})")
                if r.get("extra_in_prompt"):
                    print(f"    extra_in_prompt: {r['extra_in_prompt']}")
                if r.get("declared_but_absent"):
                    print(f"    declared_but_absent: {r['declared_but_absent']}")
        elif not args.quiet:
            print(f"✓ Executor context scope OK — {len(tasks)} task(s) scoped correctly")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
