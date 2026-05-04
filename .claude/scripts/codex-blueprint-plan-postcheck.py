#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from codex_vg_env import VGEnv, build_env  # noqa: E402


REQUIRED_BINDINGS = {"CONTEXT:decisions", "INTERFACE-STANDARDS:error-shape"}


def load_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8", errors="ignore").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def run_cmd(env: VGEnv, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc_env = os.environ.copy()
    proc_env.update({k: str(v) for k, v in env.as_dict().items()})
    return subprocess.run(
        args,
        cwd=env.repo_root,
        env=proc_env,
        text=True,
        capture_output=True,
        check=check,
    )


def validate_return(env: VGEnv, return_file: Path) -> dict[str, Any]:
    data = load_json(return_file)
    plan_path = Path(str(data.get("path") or env.phase_dir / "PLAN.md"))
    if not plan_path.is_absolute():
        plan_path = env.repo_root / plan_path
    if not plan_path.exists():
        raise FileNotFoundError(f"PLAN.md missing: {plan_path}")
    if plan_path.stat().st_size < 500:
        raise RuntimeError(f"PLAN.md too small: {plan_path.stat().st_size} bytes")

    actual_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    expected_sha = str(data.get("sha256") or "")
    if actual_sha != expected_sha:
        raise RuntimeError(f"PLAN.md sha256 mismatch: {actual_sha} != {expected_sha}")

    bindings = set(data.get("bindings_satisfied") or [])
    missing = sorted(REQUIRED_BINDINGS - bindings)
    if missing:
        raise RuntimeError(f"planner return missing bindings_satisfied: {', '.join(missing)}")
    return data


def org_check(env: VGEnv) -> dict[str, Any]:
    plan_files = sorted(glob.glob(str(env.phase_dir / "PLAN*.md")))
    if not plan_files:
        raise RuntimeError("ORG check: no PLAN*.md found")
    plan_text = "\n".join(Path(path).read_text(encoding="utf-8", errors="ignore") for path in plan_files)
    plan_lower = plan_text.lower()
    dimensions: dict[int, dict[str, Any]] = {
        1: {
            "name": "Infra",
            "critical": False,
            "patterns": [
                r"\binstall\s+(clickhouse|redis|kafka|mongodb|postgres|nginx|haproxy)",
                r"\bansible\b.*\b(playbook|role)\b",
                r"\bprovision\b",
                r"\bn/a\s*[\u2014-].*no\s+new\s+(infra|service)",
                r"\b(infra|service)\s+(existing|already|unchanged)",
                r"infra:\s*n/a",
            ],
        },
        2: {
            "name": "Env",
            "critical": False,
            "patterns": [
                r"\b(env|environment)\s+(var|variable|vars)",
                r"\.env\b",
                r"\bsecret(s)?\b.*\b(add|new|rotate)",
                r"\bvault\b",
                r"\bn/a\s*[\u2014-].*no\s+new\s+env",
                r"env:\s*n/a",
            ],
        },
        3: {
            "name": "Deploy",
            "critical": True,
            "patterns": [
                r"\bdeploy\s+(to|on)\b",
                r"\brsync\b",
                r"\bpm2\s+(reload|restart|start)",
                r"\bsystemctl\s+(restart|start)",
                r"\bbuild\s+(and|then)\s+(deploy|restart)",
                r"\brun\s+on\s+(target|vps|sandbox)",
                r"deploy:\s*local command equivalent",
            ],
        },
        4: {
            "name": "Smoke",
            "critical": False,
            "patterns": [
                r"\bsmoke\s+(test|check)",
                r"\bhealth\s+check",
                r"\b/health\b",
                r"\bcurl\b.*\b(health|status|ping)",
                r"\bverif(y|ying)\s+(alive|running|up)",
                r"smoke:\s*local command equivalent",
            ],
        },
        5: {
            "name": "Integration",
            "critical": False,
            "patterns": [
                r"\bintegration\s+(test|with)",
                r"\bE2E\b",
                r"\bconsumer\s+receives\b",
                r"\bend[-\s]to[-\s]end\b",
                r"\b(works|working)\s+with\s+(existing|phase)",
                r"integration:\s*n/a",
            ],
        },
        6: {
            "name": "Rollback",
            "critical": True,
            "patterns": [
                r"\brollback\b",
                r"\brecover(y|y path)?\b",
                r"\bgit\s+(revert|reset)",
                r"\brestore\s+(from|backup|previous)",
                r"\brollback\s+plan",
                r"\bn/a\s*[\u2014-].*(additive|backward|no\s+rollback\s+needed)",
            ],
        },
    }
    results: dict[str, Any] = {"dimensions": {}, "missing_critical": [], "missing_non_critical": []}
    for num, dim in dimensions.items():
        addressed = any(re.search(pattern, plan_lower, re.I) for pattern in dim["patterns"])
        results["dimensions"][str(num)] = {
            "name": dim["name"],
            "critical": dim["critical"],
            "addressed": addressed,
        }
        if not addressed:
            bucket = "missing_critical" if dim["critical"] else "missing_non_critical"
            results[bucket].append(f"{num}.{dim['name']}")

    out = env.phase_dir / ".org-check-result.json"
    out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if results["missing_critical"]:
        raise RuntimeError("Rule 6 missing critical ORG dims: " + ", ".join(results["missing_critical"]))
    return results


def run_schema(env: VGEnv) -> dict[str, Any]:
    validator = env.repo_root / ".claude" / "scripts" / "validators" / "verify-artifact-schema.py"
    if not validator.exists():
        raise FileNotFoundError(f"schema validator missing: {validator}")
    out = env.phase_dir / ".tmp" / "artifact-schema-plan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = run_cmd(env, [env.python_bin, str(validator), "--phase", env.phase_number, "--artifact", "plan"], check=False)
    out.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"PLAN schema validation failed; see {out}")
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except Exception:
        return {"raw": out.read_text(encoding="utf-8", errors="ignore")}


def mark_complete(env: VGEnv) -> None:
    marker_dir = env.phase_dir / ".step-markers"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "2a_plan.done").touch()
    orch = env.repo_root / ".claude" / "scripts" / "vg-orchestrator"
    if orch.exists():
        run_cmd(env, [env.python_bin, str(orch), "mark-step", "blueprint", "2a_plan"], check=False)
        run_cmd(
            env,
            [
                env.python_bin,
                str(orch),
                "emit-event",
                "blueprint.plan_written",
                "--payload",
                json.dumps({"phase": env.phase_number}),
            ],
            check=False,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex-safe /vg:blueprint planner post-spawn validation.")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--return-file", required=True, type=Path)
    parser.add_argument("--no-mark", action="store_true")
    args = parser.parse_args()

    env = build_env(args.phase)
    planner_return = validate_return(env, args.return_file)
    org = org_check(env)
    schema = run_schema(env)
    if not args.no_mark:
        mark_complete(env)
    result = {
        "phase": env.phase_number,
        "phase_dir": str(env.phase_dir),
        "planner_return": {
            "task_count": planner_return.get("task_count"),
            "wave_count": planner_return.get("wave_count"),
            "sha256": planner_return.get("sha256"),
        },
        "org_missing_critical": org["missing_critical"],
        "org_missing_non_critical": org["missing_non_critical"],
        "schema_verdict": schema.get("verdict"),
        "marked": not args.no_mark,
    }
    out = env.phase_dir / ".tmp" / "codex-blueprint-plan-postcheck.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
