#!/usr/bin/env python3
"""Walk FIXTURES/*.yaml + run pre_state assertions (RFC v9 PR-D2 stub-2 fix).

For every fixture with a `lifecycle.pre_state` block, authenticate via
recipe_executor and run the GET + assert_jsonpath. Failure = data not in
declared start state, fixtures not idempotently set up, or seed data
drifted. Fail-fast at /vg:review entry before browser scan.

Output JSON:
  {"verdict": "PASS"|"BLOCK"|"WARN", "results": [{...}], "errors": [...]}

Exit:
  0 — PASS or WARN
  1 — BLOCK
  2 — config / setup error

Usage:
  scripts/rcrurd-preflight.py --phase 3.2 --base-url https://sandbox.example.com
  scripts/rcrurd-preflight.py --phase 3.2 --severity warn
  scripts/rcrurd-preflight.py --phase 3.2 --dry-run
  scripts/rcrurd-preflight.py --phase 3.2 --only G-10,G-11
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import yaml
except ImportError:
    print(json.dumps({"verdict": "ERROR", "error": "PyYAML required"}))
    sys.exit(2)

from runtime.rcrurd_gate import run_pre_state, LifecycleGateError  # noqa: E402


def _find_phase_dir(repo: Path, phase: str) -> Path | None:
    phases_dir = repo / ".vg" / "phases"
    if not phases_dir.exists():
        return None
    for prefix in (phase, _zero_pad(phase)):
        matches = sorted(phases_dir.glob(f"{prefix}-*"))
        if matches:
            return matches[0]
    return None


def _zero_pad(phase: str) -> str:
    if "." in phase and not phase.split(".")[0].startswith("0"):
        head, _, tail = phase.partition(".")
        return f"{head.zfill(2)}.{tail}"
    return phase


def _load_credentials_map(config_path: Path | None) -> dict:
    if config_path and config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        import re
        m = re.search(
            r"^credentials:\s*\n(?P<body>(?:[ \t].*\n)+)",
            text, re.MULTILINE,
        )
        if m:
            try:
                full = yaml.safe_load("credentials:\n" + m.group("body"))
                if isinstance(full, dict):
                    return full.get("credentials") or {}
            except Exception:
                pass
    env_creds = os.environ.get("VG_CREDENTIALS_JSON")
    if env_creds:
        try:
            return json.loads(env_creds)
        except json.JSONDecodeError:
            pass
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--base-url", help="Sandbox API root URL (or VG_BASE_URL)")
    ap.add_argument("--severity", choices=["block", "warn"], default="warn")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="Comma-separated goal IDs to check")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--vg-config", default=None)
    args = ap.parse_args()

    repo = Path(args.repo_root or os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    phase_dir = _find_phase_dir(repo, args.phase)
    if phase_dir is None:
        print(json.dumps({
            "verdict": "ERROR",
            "error": f"phase '{args.phase}' not found",
        }))
        return 2

    fixtures_dir = phase_dir / "FIXTURES"
    if not fixtures_dir.exists():
        print(json.dumps({"verdict": "PASS", "reason": "no FIXTURES dir"}))
        return 0

    only = {g.strip() for g in args.only.split(",")} if args.only else None
    fixture_files = sorted(fixtures_dir.glob("*.yaml"))
    if not fixture_files:
        print(json.dumps({"verdict": "PASS", "reason": "no fixture yaml files"}))
        return 0

    plan: list[dict] = []
    for fp in fixture_files:
        gid = fp.stem
        if only and gid not in only:
            continue
        try:
            recipe = yaml.safe_load(fp.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            plan.append({"goal": gid, "error": f"yaml parse: {e}"})
            continue
        if not isinstance(recipe, dict):
            plan.append({"goal": gid, "error": "not an object"})
            continue
        lifecycle = recipe.get("lifecycle")
        if not isinstance(lifecycle, dict) or "pre_state" not in lifecycle:
            continue  # no pre_state to check
        plan.append({"goal": gid, "lifecycle": lifecycle})

    if not plan:
        print(json.dumps({"verdict": "PASS",
                           "reason": "no fixtures declare pre_state"}))
        return 0

    if args.dry_run:
        print(json.dumps({
            "verdict": "DRY_RUN",
            "would_check": [
                {"goal": p["goal"],
                 "endpoint": p.get("lifecycle", {}).get("pre_state", {}).get("endpoint")}
                for p in plan if "lifecycle" in p
            ],
            "errors": [p for p in plan if "error" in p],
        }, indent=2))
        return 0

    base_url = args.base_url or os.environ.get("VG_BASE_URL")
    if not base_url:
        print(json.dumps({
            "verdict": "ERROR",
            "error": "no --base-url and VG_BASE_URL not set",
        }))
        return 2

    config_path = Path(args.vg_config) if args.vg_config else \
        (repo / ".claude" / "vg.config.md")
    credentials_map = _load_credentials_map(config_path)
    if not credentials_map:
        print(json.dumps({
            "verdict": "ERROR",
            "error": (
                f"credentials_map empty — load from {config_path} OR set "
                f"VG_CREDENTIALS_JSON env var."
            ),
        }))
        return 2

    try:
        from runtime.recipe_executor import RecipeRunner
    except ImportError as e:
        print(json.dumps({
            "verdict": "ERROR",
            "error": f"recipe_executor import failed: {e}",
        }))
        return 2

    runner = RecipeRunner(
        base_url=base_url,
        env="sandbox",
        credentials_map=credentials_map,
    )

    def get_fn(role: str, endpoint: str) -> dict:
        auth = runner._auth_context(role)
        url = base_url.rstrip("/") + endpoint
        resp = auth.session.get(url, timeout=runner.request_timeout)
        if resp.status_code >= 400:
            raise RuntimeError(f"{resp.status_code}: {resp.text[:120]}")
        try:
            return resp.json() if resp.text else {}
        except Exception:
            return {}

    results = []
    failed_count = 0
    for entry in plan:
        if "error" in entry:
            results.append({"goal": entry["goal"], "passed": False,
                             "errors": [entry["error"]]})
            failed_count += 1
            continue
        try:
            res = run_pre_state(entry["goal"], entry["lifecycle"], get_fn)
            results.append({
                "goal": res.goal_id,
                "passed": res.pre_state_passed,
                "skipped": res.skipped_reason,
                "errors": res.pre_state_failures,
            })
            if not res.pre_state_passed and res.skipped_reason is None:
                failed_count += 1
        except LifecycleGateError as e:
            results.append({"goal": entry["goal"], "passed": False,
                             "errors": [str(e)]})
            failed_count += 1

    if failed_count == 0:
        print(json.dumps({
            "verdict": "PASS",
            "phase": args.phase,
            "checked": len(plan),
            "results": results,
        }, indent=2))
        return 0

    verdict = "BLOCK" if args.severity == "block" else "WARN"
    print(json.dumps({
        "verdict": verdict,
        "phase": args.phase,
        "failed": failed_count,
        "checked": len(plan),
        "results": results,
    }, indent=2))
    return 1 if verdict == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
