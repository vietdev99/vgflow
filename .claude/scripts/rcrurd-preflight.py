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

from runtime.rcrurd_gate import (  # noqa: E402
    LifecycleGateError, run_post_state_with_retry, run_pre_state,
)


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
    ap.add_argument("--severity", choices=["block", "warn"], default="block")
    ap.add_argument("--mode", choices=["pre", "post"], default="pre",
                    help="pre = pre_state at review entry (default); "
                         "post = post_state after action (Codex-HIGH-1 wiring)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="Comma-separated goal IDs to check")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--vg-config", default=None)
    ap.add_argument("--capture-snapshot", default=None,
                    help="In --mode pre, persist payloads to this JSON path so "
                         "--mode post can compute increased_by_at_least deltas "
                         "against the actual pre-action state (Codex-HIGH-1-bis).")
    ap.add_argument("--pre-snapshot", default=None,
                    help="In --mode post, read pre-state payloads from this "
                         "JSON path (written by an earlier --mode pre invocation "
                         "with --capture-snapshot). Without it, increased_by_at_least "
                         "deltas use post-action GET as 'pre' which is wrong.")
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
        if not isinstance(lifecycle, dict):
            continue
        # Mode determines which leg of the lifecycle to assert
        required_key = "pre_state" if args.mode == "pre" else "post_state"
        if required_key not in lifecycle:
            continue
        plan.append({"goal": gid, "lifecycle": lifecycle})

    if not plan:
        leg = "pre_state" if args.mode == "pre" else "post_state"
        print(json.dumps({"verdict": "PASS",
                           "reason": f"no fixtures declare {leg}"}))
        return 0

    if args.dry_run:
        leg_key = "pre_state" if args.mode == "pre" else "post_state"
        print(json.dumps({
            "verdict": "DRY_RUN",
            "mode": args.mode,
            "would_check": [
                {"goal": p["goal"],
                 "endpoint": p.get("lifecycle", {}).get(leg_key, {}).get("endpoint")}
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

    # Codex-HIGH-1-bis: load pre-snapshot for post mode (real pre-action state)
    pre_snapshot: dict[str, dict] = {}
    if args.mode == "post" and args.pre_snapshot:
        snap_path = Path(args.pre_snapshot)
        if snap_path.exists():
            try:
                pre_snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pre_snapshot = {}

    # Codex-HIGH-1-bis: capture pre-snapshot in pre mode for downstream post mode
    capture_snapshot: dict[str, dict] = {} if (
        args.mode == "pre" and args.capture_snapshot
    ) else {}

    results = []
    failed_count = 0
    for entry in plan:
        if "error" in entry:
            results.append({"goal": entry["goal"], "passed": False,
                             "errors": [entry["error"]]})
            failed_count += 1
            continue
        try:
            if args.mode == "pre":
                res = run_pre_state(entry["goal"], entry["lifecycle"], get_fn)
                results.append({
                    "goal": res.goal_id,
                    "passed": res.pre_state_passed,
                    "skipped": res.skipped_reason,
                    "errors": res.pre_state_failures,
                })
                if not res.pre_state_passed and res.skipped_reason is None:
                    failed_count += 1
                # Capture for downstream post mode (Codex-HIGH-1-bis)
                if args.capture_snapshot:
                    pre_block = entry["lifecycle"].get("pre_state") or {}
                    if pre_block.get("endpoint") and pre_block.get("role"):
                        try:
                            capture_snapshot[entry["goal"]] = get_fn(
                                pre_block["role"], pre_block["endpoint"],
                            )
                        except Exception:
                            pass  # best-effort
            else:  # post
                # Codex-HIGH-1-bis fix: prefer the pre-snapshot from
                # before the action ran. Falling back to a fresh GET
                # would sample post-action state, breaking
                # increased_by_at_least delta semantics.
                pre_payload = pre_snapshot.get(entry["goal"]) if pre_snapshot else None
                if pre_payload is None:
                    # Fallback: best-effort live read (may be wrong for
                    # delta assertions; equality assertions still work).
                    pre_block = entry["lifecycle"].get("pre_state") or {}
                    if pre_block.get("endpoint") and pre_block.get("role"):
                        try:
                            pre_payload = get_fn(pre_block["role"],
                                                  pre_block["endpoint"])
                        except Exception:
                            pre_payload = None
                res = run_post_state_with_retry(
                    entry["goal"], entry["lifecycle"], get_fn,
                    pre_payload=pre_payload,
                )
                results.append({
                    "goal": res.goal_id,
                    "passed": res.post_state_passed,
                    "skipped": res.skipped_reason,
                    "errors": res.post_state_failures,
                    "pre_snapshot_used": pre_payload is not None and
                        pre_snapshot.get(entry["goal"]) is not None,
                })
                if not res.post_state_passed and res.skipped_reason is None:
                    failed_count += 1
        except LifecycleGateError as e:
            results.append({"goal": entry["goal"], "passed": False,
                             "errors": [str(e)]})
            failed_count += 1

    # Persist pre-snapshot for downstream post mode (Codex-HIGH-1-bis)
    if args.mode == "pre" and args.capture_snapshot and capture_snapshot:
        snap_path = Path(args.capture_snapshot)
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(
            json.dumps(capture_snapshot, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if failed_count == 0:
        print(json.dumps({
            "verdict": "PASS",
            "mode": args.mode,
            "phase": args.phase,
            "checked": len(plan),
            "results": results,
            "snapshot_captured": bool(args.mode == "pre" and capture_snapshot),
            "pre_snapshot_loaded": bool(args.mode == "post" and pre_snapshot),
        }, indent=2))
        return 0

    verdict = "BLOCK" if args.severity == "block" else "WARN"
    print(json.dumps({
        "verdict": verdict,
        "mode": args.mode,
        "phase": args.phase,
        "failed": failed_count,
        "checked": len(plan),
        "results": results,
    }, indent=2))
    return 1 if verdict == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
