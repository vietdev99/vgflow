#!/usr/bin/env python3
"""
spawn-crud-roundtrip.py — v2.35.0 CRUD round-trip lens dispatcher.

Manager script: for each (resource × role) declared in CRUD-SURFACES.md
where `kit: crud-roundtrip` applies, spawn a Gemini Flash worker via
`gemini -p` non-interactive mode. Worker runs the 8-step round-trip
documented in `commands/vg/_shared/transition-kits/crud-roundtrip.md`
and writes a run artifact JSON.

Worker invocation per (resource × role):

  gemini -p "<lens prompt + context block>" \
    -m gemini-2.5-flash \
    --approval-mode yolo \
    --allowed-mcp-server-names playwright1

Why Gemini Flash:
  - $0.075/M input vs Haiku 4.5 $1.00/M = 13x cheaper
  - Already MCP-configured (5 playwright servers in ~/.gemini/settings.json)
  - Already cross-CLI plumbing in VG (crossai-invoke.md)

Outputs:
  ${PHASE_DIR}/runs/{resource}-{role}.json   (run artifact per worker)
  ${PHASE_DIR}/runs/INDEX.json               (manager index of all spawns)

Usage:
  spawn-crud-roundtrip.py --phase-dir <path>
  spawn-crud-roundtrip.py --phase-dir <path> --resource topup_requests --role admin
  spawn-crud-roundtrip.py --phase-dir <path> --dry-run                # print plan only
  spawn-crud-roundtrip.py --phase-dir <path> --concurrency 3          # parallel workers
  spawn-crud-roundtrip.py --phase-dir <path> --cost-cap 1.00          # exit 1 if estimated cost exceeds USD

Exit codes:
  0 — all workers spawned (failures recorded in INDEX.json)
  1 — config error (CRUD-SURFACES missing, no resources)
  2 — arg error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_crud_surfaces(phase_dir: Path) -> dict:
    csv = phase_dir / "CRUD-SURFACES.md"
    if not csv.is_file():
        return {}
    text = csv.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"```json\s*\n(.+?)\n```", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def load_tokens(phase_dir: Path) -> dict:
    candidates = [
        phase_dir / ".review-fixtures" / "tokens.local.yaml",
        REPO_ROOT / ".review-fixtures" / "tokens.local.yaml",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}


def load_kit_prompt(repo_root: Path) -> str:
    kit_path = repo_root / ".claude" / "commands" / "vg" / "_shared" / "transition-kits" / "crud-roundtrip.md"
    if not kit_path.is_file():
        kit_path = repo_root / "commands" / "vg" / "_shared" / "transition-kits" / "crud-roundtrip.md"
    if not kit_path.is_file():
        return ""
    return kit_path.read_text(encoding="utf-8")


def build_worker_prompt(kit_text: str, resource: dict, role: str, role_token: dict | None,
                        run_id: str, output_path: str, base_url: str | None) -> str:
    expected_for_role = (resource.get("expected_behavior") or {}).get(role) or {}
    forbidden = resource.get("forbidden_side_effects") or []
    scope = resource.get("scope", "global")

    context_block = {
        "run_id": run_id,
        "resource": resource.get("name"),
        "role": role,
        "scope": scope,
        "auth_token": role_token.get("token") if role_token else None,
        "actor": role_token or {"user_id": None, "tenant_id": None},
        "base_url": base_url,
        "expected_behavior": expected_for_role,
        "forbidden_side_effects": forbidden,
        "platforms_web": (resource.get("platforms") or {}).get("web") or {},
        "platforms_backend": (resource.get("platforms") or {}).get("backend") or {},
        "delete_policy": resource.get("base", {}).get("delete_policy") or {},
        "lifecycle_states": (resource.get("base") or {}).get("business_flow", {}).get("lifecycle_states") or [],
        "object_level_auth": (resource.get("expected_behavior") or {}).get("object_level") or {},
        "output_path": output_path,
    }

    return (
        kit_text
        + "\n\n---\n\n## CONTEXT (provided per spawn)\n\n```json\n"
        + json.dumps(context_block, indent=2)
        + "\n```\n\nWrite the run artifact JSON to `OUTPUT_PATH`. Do not write anywhere else. Return briefly when done.\n"
    )


def spawn_worker(prompt: str, model: str, mcp_server: str, timeout: int,
                 debug_log_path: Path | None = None) -> dict:
    cmd = [
        "gemini",
        "-p", prompt,
        "-m", model,
        "--approval-mode", "yolo",
        "--allowed-mcp-server-names", mcp_server,
    ]
    started = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if debug_log_path:
            cmd_redacted = [
                "gemini",
                "-p", f"<REDACTED {len(prompt)} chars>",
                "-m", model,
                "--approval-mode", "yolo",
                "--allowed-mcp-server-names", mcp_server,
            ]
            debug_log_path.write_text(
                f"=== CMD ===\n{' '.join(cmd_redacted)}\n"
                f"=== EXIT {result.returncode} duration={round(time.time()-started,1)}s ===\n"
                f"=== STDOUT (full, {len(result.stdout)} chars) ===\n{result.stdout}\n"
                f"=== STDERR (full, {len(result.stderr)} chars) ===\n{result.stderr}\n",
                encoding="utf-8",
            )
        return {
            "exit_code": result.returncode,
            "stdout_tail": (result.stdout or "")[-2000:],
            "stderr_tail": (result.stderr or "")[-2000:],
            "duration_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout_tail": "", "stderr_tail": "TIMEOUT", "duration_seconds": timeout}
    except FileNotFoundError:
        return {"exit_code": -1, "stdout_tail": "", "stderr_tail": "gemini CLI not found in PATH", "duration_seconds": 0}


def estimate_cost(workflows: int, avg_tokens: int = 20000, price_per_million: float = 0.075) -> float:
    return (workflows * avg_tokens / 1_000_000.0) * price_per_million


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--resource", default=None, help="Filter to specific resource")
    ap.add_argument("--role", default=None, help="Filter to specific role")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--mcp-server", default="playwright1")
    ap.add_argument("--timeout", type=int, default=600, help="Per-worker timeout seconds")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--cost-cap", type=float, default=None, help="Abort if estimated cost exceeds USD")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--debug", action="store_true",
                    help="Capture full stdout/stderr + redacted prompt summary to runs/.debug-{run_id}.log")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"⛔ Phase dir not found: {phase_dir}", file=sys.stderr)
        return 2

    if args.debug:
        print("DEBUG MODE active — would write logs to runs/.debug-*.log")

    surfaces = load_crud_surfaces(phase_dir)
    resources = surfaces.get("resources") or []
    if not resources:
        if args.dry_run:
            print(f"  (no resources declared in {phase_dir}/CRUD-SURFACES.md)")
            return 0
        print(f"⛔ No resources in {phase_dir}/CRUD-SURFACES.md", file=sys.stderr)
        return 1

    tokens = load_tokens(phase_dir)
    kit_text = load_kit_prompt(REPO_ROOT)
    if not kit_text:
        print("⛔ crud-roundtrip.md kit prompt not found", file=sys.stderr)
        return 1

    base_url = None
    cfg_path = REPO_ROOT / ".claude" / "vg.config.md"
    if cfg_path.is_file():
        cfg_text = cfg_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"\bbase_url:\s*[\"']?([^\"'\s]+)", cfg_text)
        if m:
            base_url = m.group(1)

    plan: list[dict] = []
    for resource in resources:
        if resource.get("kit") != "crud-roundtrip":
            continue
        if args.resource and resource.get("name") != args.resource:
            continue
        for role in (resource.get("base", {}).get("roles") or ["admin", "user", "anon"]):
            if args.role and role != args.role:
                continue
            plan.append({"resource": resource, "role": role})

    if not plan:
        print(f"  (no (resource × role) pairs to dispatch)")
        return 0

    estimated = estimate_cost(len(plan))
    if not args.quiet:
        print(f"▸ Plan: {len(plan)} workflow(s), estimated cost ~${estimated:.3f} (Gemini Flash)")
    if args.cost_cap and estimated > args.cost_cap:
        print(f"⛔ Estimated cost ${estimated:.3f} > --cost-cap ${args.cost_cap}", file=sys.stderr)
        return 1

    runs_dir = phase_dir / "runs"
    if not args.dry_run:
        runs_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        for entry in plan:
            print(f"  WOULD SPAWN: {entry['resource']['name']} × {entry['role']}")
        return 0

    index: list[dict] = []

    def run_one(entry: dict) -> dict:
        resource = entry["resource"]
        role = entry["role"]
        run_id = f"{resource['name']}-{role}-{uuid.uuid4().hex[:8]}"
        output_path = str((runs_dir / f"{resource['name']}-{role}.json").resolve())

        prompt = build_worker_prompt(
            kit_text, resource, role, tokens.get(role),
            run_id, output_path, base_url,
        )

        spawn_started = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        debug_path = (runs_dir / f".debug-{run_id}.log") if args.debug else None
        spawn_result = spawn_worker(prompt, args.model, args.mcp_server, args.timeout, debug_path)
        spawn_completed = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        artifact_present = Path(output_path).is_file()

        return {
            "run_id": run_id,
            "resource": resource["name"],
            "role": role,
            "output_path": output_path,
            "artifact_present": artifact_present,
            "spawn_started": spawn_started,
            "spawn_completed": spawn_completed,
            **spawn_result,
        }

    failures = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = [ex.submit(run_one, e) for e in plan]
        for fut in as_completed(futures):
            r = fut.result()
            index.append(r)
            if not args.quiet:
                marker = "✓" if r["artifact_present"] else "✗"
                print(f"  {marker} {r['resource']} × {r['role']} ({r['duration_seconds']}s, exit={r['exit_code']})")
            if not r["artifact_present"]:
                failures += 1

    index_path = runs_dir / "INDEX.json"
    index_path.write_text(json.dumps({
        "schema_version": "1",
        "phase_dir": str(phase_dir),
        "model": args.model,
        "concurrency": args.concurrency,
        "estimated_cost_usd": estimated,
        "spawned": len(index),
        "artifacts_present": sum(1 for r in index if r["artifact_present"]),
        "failures": failures,
        "results": index,
    }, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps({"index_path": str(index_path), "failures": failures}, indent=2))
    elif not args.quiet:
        print(f"\n✓ Index written: {index_path}")
        print(f"  Workflows: {len(index)} | Artifacts present: {len(index) - failures} | Failed: {failures}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
