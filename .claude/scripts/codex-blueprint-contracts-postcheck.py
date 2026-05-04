#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


REQUIRED_BINDINGS = {
    "PLAN:tasks",
    "INTERFACE-STANDARDS:error-shape",
    "INTERFACE-STANDARDS:response-envelope",
}


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
    api_path = Path(str(data.get("api_contracts_path") or env.phase_dir / "API-CONTRACTS.md"))
    if not api_path.is_absolute():
        api_path = env.repo_root / api_path
    if not api_path.exists():
        raise FileNotFoundError(f"API-CONTRACTS.md missing: {api_path}")
    actual_sha = hashlib.sha256(api_path.read_bytes()).hexdigest()
    expected_sha = str(data.get("api_contracts_sha256") or "")
    if actual_sha != expected_sha:
        raise RuntimeError(f"API-CONTRACTS.md sha256 mismatch: {actual_sha} != {expected_sha}")
    bindings = set(data.get("bindings_satisfied") or [])
    missing = sorted(REQUIRED_BINDINGS - bindings)
    if missing:
        raise RuntimeError(f"contracts return missing bindings_satisfied: {', '.join(missing)}")
    for key in ("test_goals_path", "crud_surfaces_path"):
        target = Path(str(data.get(key) or ""))
        if not target.is_absolute():
            target = env.repo_root / target
        if not target.exists():
            raise FileNotFoundError(f"{key} missing: {target}")
    return data


def validate_crud(env: VGEnv, arguments: str) -> dict[str, Any]:
    crud_path = env.phase_dir / "CRUD-SURFACES.md"
    if not crud_path.exists() and "--crossai-only" not in arguments:
        raise FileNotFoundError(f"CRUD-SURFACES.md missing: {crud_path}")
    if crud_path.exists() and crud_path.stat().st_size < 120 and "--crossai-only" not in arguments:
        raise RuntimeError(f"CRUD-SURFACES.md too small: {crud_path.stat().st_size} bytes")
    validator = env.repo_root / ".claude" / "scripts" / "validators" / "verify-crud-surface-contract.py"
    if not validator.exists() or not crud_path.exists():
        return {"skipped": True, "reason": "validator or CRUD-SURFACES.md missing"}
    out = env.phase_dir / ".tmp" / "crud-strictness.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = run_cmd(env, [env.python_bin, str(validator), "--phase", env.phase_number], check=False)
    out.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"CRUD-SURFACES validator failed; see {out}")
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except Exception:
        return {"returncode": proc.returncode, "raw": out.read_text(encoding="utf-8", errors="ignore")}


def rule3b(env: VGEnv) -> dict[str, Any]:
    goals_file = env.phase_dir / "TEST-GOALS.md"
    text = goals_file.read_text(encoding="utf-8")
    goal_pattern = re.compile(
        r"(^#{2,3}\s+(?:Goal\s+)?G-\d+[^\n]*)\n(.*?)(?=^#{2,3}\s+(?:Goal\s+)?G-\d+|\Z)",
        re.M | re.S,
    )
    missing: list[str] = []
    mutation_count = 0
    persistence_count = 0
    bad_na: list[str] = []
    for match in goal_pattern.finditer(text):
        header = match.group(1).strip()
        body = match.group(2)
        gid_match = re.search(r"G-\d+", header)
        gid = gid_match.group(0) if gid_match else "?"
        mut_match = re.search(r"\*\*Mutation evidence:\*\*\s*(.+?)(?=\n\s*\n|\n\*\*|\Z)", body, re.S)
        has_mutation = False
        if mut_match:
            value = mut_match.group(1).strip()
            if value.lower().startswith("n/a") and value != "N/A":
                bad_na.append(f"{gid}: use exact '**Mutation evidence:** N/A' and put explanation elsewhere")
            if value and not re.match(r"^(N/A|none|\u2014|-|_)\s*$", value, re.I):
                has_mutation = True
                mutation_count += 1
        has_persistence = bool(re.search(r"\*\*Persistence check:\*\*", body))
        if has_persistence:
            persistence_count += 1
        if has_mutation and not has_persistence:
            missing.append(gid)
    if bad_na:
        raise RuntimeError("Rule 3b N/A formatting violation: " + "; ".join(bad_na))
    if missing:
        raise RuntimeError("Rule 3b missing Persistence check: " + ", ".join(missing))
    return {"mutation_goals": mutation_count, "persistence_blocks": persistence_count}


def extended_rcrurd(env: VGEnv) -> dict[str, Any]:
    goals_dir = env.phase_dir / "TEST-GOALS"
    checked = 0
    missing: list[str] = []
    if not goals_dir.exists():
        return {"checked": 0, "missing": []}
    lib = env.repo_root / ".claude" / "scripts" / "lib"
    for goal_file in sorted(goals_dir.glob("G-*.md")):
        text = goal_file.read_text(encoding="utf-8", errors="ignore")
        if not re.search(r"^\*\*goal_type:\*\*\s*mutation", text, re.M):
            continue
        checked += 1
        proc = subprocess.run(
            [
                env.python_bin,
                "-c",
                (
                    "import sys; "
                    f"sys.path.insert(0, {str(lib)!r}); "
                    "from rcrurd_invariant import extract_from_test_goal_md; "
                    f"text=open({str(goal_file)!r}, encoding='utf-8').read(); "
                    "sys.exit(0 if extract_from_test_goal_md(text) is not None else 1)"
                ),
            ],
            cwd=env.repo_root,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            missing.append(str(goal_file))
    if missing:
        raise RuntimeError("Rule 3b extended missing yaml-rcrurd: " + ", ".join(missing))
    return {"checked": checked, "missing": missing}


def schema_test_goals(env: VGEnv) -> dict[str, Any]:
    validator = env.repo_root / ".claude" / "scripts" / "validators" / "verify-artifact-schema.py"
    if not validator.exists():
        raise FileNotFoundError(f"schema validator missing: {validator}")
    out = env.phase_dir / ".tmp" / "artifact-schema-test-goals.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = run_cmd(env, [env.python_bin, str(validator), "--phase", env.phase_number, "--artifact", "test-goals"], check=False)
    out.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"TEST-GOALS schema validation failed; see {out}")
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except Exception:
        return {"raw": out.read_text(encoding="utf-8", errors="ignore")}


def mark_complete(env: VGEnv) -> None:
    marker_dir = env.phase_dir / ".step-markers"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "2b_contracts.done").touch()
    (marker_dir / "2b5_test_goals.done").touch()
    orch = env.repo_root / ".claude" / "scripts" / "vg-orchestrator"
    if orch.exists():
        run_cmd(env, [env.python_bin, str(orch), "step-active", "2b5_test_goals"], check=False)
        run_cmd(env, [env.python_bin, str(orch), "mark-step", "blueprint", "2b_contracts"], check=False)
        run_cmd(env, [env.python_bin, str(orch), "mark-step", "blueprint", "2b5_test_goals"], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex-safe /vg:blueprint contracts post-spawn validation.")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--return-file", required=True, type=Path)
    parser.add_argument("--arguments", default="")
    parser.add_argument("--no-mark", action="store_true")
    args = parser.parse_args()

    env = build_env(args.phase)
    contracts_return = validate_return(env, args.return_file)
    crud = validate_crud(env, args.arguments)
    persistence = rule3b(env)
    rcrurd = extended_rcrurd(env)
    schema = schema_test_goals(env)
    if not args.no_mark:
        mark_complete(env)
    result = {
        "phase": env.phase_number,
        "phase_dir": str(env.phase_dir),
        "contracts_return": {
            "endpoint_count": contracts_return.get("endpoint_count"),
            "goal_count": contracts_return.get("goal_count"),
            "api_contracts_sha256": contracts_return.get("api_contracts_sha256"),
        },
        "crud_verdict": crud.get("verdict"),
        "rule3b": persistence,
        "rcrurd": rcrurd,
        "schema_verdict": schema.get("verdict"),
        "marked": not args.no_mark,
    }
    out = env.phase_dir / ".tmp" / "codex-blueprint-contracts-postcheck.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
