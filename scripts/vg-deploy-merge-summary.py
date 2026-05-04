#!/usr/bin/env python3
"""Merge per-env deploy results into DEPLOY-STATE.json + print summary.

Extracted from commands/vg/deploy.md Step 2 to keep that slim entry under
the 500-line cap. Reads .tmp/deploy-results.json (list of {env, sha,
deployed_at, health, deploy_log, previous_sha?, dry_run?}) and merges into
${PHASE_DIR}/DEPLOY-STATE.json under deployed.{env} (preserving
preferred_env_for + any unrelated future keys). Prints summary table and
emits result_payload JSON on a single line on stdout (last line) so the
shell wrapper in deploy.md can capture it for telemetry.

Usage:
  vg-deploy-merge-summary.py --phase <N> --phase-dir <path> [--results-json <path>]

Output:
  Multiple lines of human-readable summary, then a final line:
    RESULT_PAYLOAD={"phase":"<n>","ok_envs":[...],"failed_envs":[...],"total":N}
  Exit code 0 always (telemetry decision belongs to caller).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--phase", required=True)
    p.add_argument("--phase-dir", required=True)
    p.add_argument("--results-json", default=None,
                   help="Defaults to <phase-dir>/.tmp/deploy-results.json")
    args = p.parse_args()

    phase_dir = Path(args.phase_dir)
    results_path = Path(args.results_json) if args.results_json else \
        phase_dir / ".tmp" / "deploy-results.json"

    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))["results"]
    except Exception as exc:
        print(f"ERROR: cannot read results from {results_path}: {exc}",
              file=sys.stderr)
        return 1

    state_path = phase_dir / "DEPLOY-STATE.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) \
        if state_path.exists() else {"phase": args.phase}
    state.setdefault("deployed", {})

    ok_envs, fail_envs = [], []
    for r in results:
        env = r["env"]
        state["deployed"][env] = {
            "sha": r["sha"],
            "deployed_at": r["deployed_at"],
            "health": r["health"],
            "deploy_log": r["deploy_log"],
            "previous_sha": r.get("previous_sha", ""),
            "dry_run": r.get("dry_run", False),
        }
        if r["health"] in ("ok", "dry-run"):
            ok_envs.append(env)
        else:
            fail_envs.append(env)

    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Deploy summary — phase {args.phase}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    for r in results:
        icon = "✓" if r["health"] in ("ok", "dry-run") else "⛔"
        prev = f" (prev: {r['previous_sha']})" if r.get("previous_sha") else ""
        dry = " [DRY-RUN]" if r.get("dry_run") else ""
        print(f"  {icon} {r['env']:10} sha={r['sha']} health={r['health']}{prev}{dry}")
    print(f"  → DEPLOY-STATE.json updated ({len(ok_envs)} ok, {len(fail_envs)} failed)")
    print()
    if ok_envs:
        print("  Next: review/test/roam will see these envs as Recommended option")
        print(f"    /vg:review {args.phase}    (env gate auto-suggests one of: {ok_envs})")

    payload = {
        "phase": args.phase,
        "ok_envs": ok_envs,
        "failed_envs": fail_envs,
        "total": len(results),
    }
    print(f"RESULT_PAYLOAD={json.dumps(payload)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
