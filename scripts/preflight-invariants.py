#!/usr/bin/env python3
"""Live preflight runner — RFC v9 PR-C wiring (replaces stub count_fn=0).

Walks ENV-CONTRACT.md data_invariants + api_index, authenticates via
recipe_executor, counts entities matching each invariant's `where`
filter, emits BLOCK if any invariant is short.

Output JSON:
  {"verdict": "PASS"|"BLOCK", "gaps": [{...InvariantGap...}], "errors": [...]}

Exit codes:
  0 — PASS (all invariants satisfied)
  1 — BLOCK (one or more gaps)
  2 — config / setup error (missing api_index, bad creds, network)

Usage:
  scripts/preflight-invariants.py --phase 3.2 --base-url https://sandbox.example.com
  scripts/preflight-invariants.py --phase 3.2 --dry-run        # show what'd be checked
  scripts/preflight-invariants.py --phase 3.2 --severity warn  # downgrade BLOCK→WARN
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime.api_index import (  # noqa: E402
    ApiIndexError,
    count_fn_factory,
    parse_api_index,
)
from runtime.preflight import (  # noqa: E402
    PreflightError,
    fix_hint,
    parse_env_contract,
    verify_invariants,
)


def _find_phase_dir(repo: Path, phase: str) -> Path | None:
    phases_dir = repo / ".vg" / "phases"
    if not phases_dir.exists():
        return None
    for prefix_candidate in (phase, _zero_pad(phase)):
        matches = sorted(phases_dir.glob(f"{prefix_candidate}-*"))
        if matches:
            return matches[0]
    return None


def _zero_pad(phase: str) -> str:
    if "." in phase and not phase.split(".")[0].startswith("0"):
        head, _, tail = phase.partition(".")
        return f"{head.zfill(2)}.{tail}"
    return phase


def _load_credentials_map(config_path: Path | None) -> dict:
    """Read credentials_map from project vg.config.md or env override.

    Returns the raw mapping {role: {kind, ...}} without secrets transformation.
    Caller (RecipeRunner) handles auth dispatch.
    """
    if config_path and config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        # Extract YAML block under `credentials:` heading
        import re
        m = re.search(
            r"^credentials:\s*\n(?P<body>(?:[ \t].*\n)+)",
            text, re.MULTILINE,
        )
        if m:
            try:
                import yaml
                full = yaml.safe_load("credentials:\n" + m.group("body"))
                if isinstance(full, dict):
                    return full.get("credentials") or {}
            except (ImportError, Exception):
                pass
    # Fallback: VG_CREDENTIALS_JSON env var (for CI / scripted use)
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
    ap.add_argument("--base-url", help="Sandbox API root URL (overrides env)")
    ap.add_argument("--severity", choices=["block", "warn"], default="block")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse + report what'd be checked; do NOT call API")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--vg-config", default=None,
                    help="Path to vg.config.md (default: $REPO_ROOT/.claude/vg.config.md)")
    args = ap.parse_args()

    repo = Path(args.repo_root or os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    phase_dir = _find_phase_dir(repo, args.phase)
    if phase_dir is None:
        print(json.dumps({
            "verdict": "ERROR",
            "error": f"phase '{args.phase}' not found at {repo / '.vg/phases'}",
        }))
        return 2

    env_contract = phase_dir / "ENV-CONTRACT.md"
    if not env_contract.exists():
        # No invariants declared → trivial PASS (PR-C is opt-in)
        print(json.dumps({"verdict": "PASS", "reason": "no ENV-CONTRACT.md"}))
        return 0

    try:
        invariants = parse_env_contract(env_contract)
    except PreflightError as e:
        print(json.dumps({"verdict": "ERROR", "error": str(e)}))
        return 2

    if not invariants:
        print(json.dumps({"verdict": "PASS", "reason": "no data_invariants block"}))
        return 0

    try:
        api_index = parse_api_index(env_contract)
    except ApiIndexError as e:
        print(json.dumps({
            "verdict": "ERROR",
            "error": f"api_index parse: {e}",
        }))
        return 2

    if args.dry_run:
        print(json.dumps({
            "verdict": "DRY_RUN",
            "invariants": len(invariants),
            "api_index_resources": list(api_index),
            "would_check": [
                {"id": inv.get("id"), "resource": inv.get("resource"),
                 "where": inv.get("where")}
                for inv in invariants
            ],
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
                f"VG_CREDENTIALS_JSON env var. Without auth we cannot count."
            ),
        }))
        return 2

    # Need RecipeRunner instance for the count_fn closure
    try:
        from runtime.recipe_executor import RecipeRunner
    except ImportError as e:
        print(json.dumps({
            "verdict": "ERROR",
            "error": f"recipe_executor import failed: {e} (install requests>=2.31)",
        }))
        return 2

    runner = RecipeRunner(
        base_url=base_url,
        env="sandbox",
        credentials_map=credentials_map,
    )
    try:
        count_fn = count_fn_factory(api_index, runner)
        gaps = verify_invariants(invariants, count_fn)
    except (ApiIndexError, PreflightError) as e:
        print(json.dumps({"verdict": "ERROR", "error": str(e)}))
        return 2

    if not gaps:
        print(json.dumps({
            "verdict": "PASS",
            "invariants_checked": len(invariants),
            "phase": args.phase,
        }))
        return 0

    verdict = "BLOCK" if args.severity == "block" else "WARN"
    print(json.dumps({
        "verdict": verdict,
        "phase": args.phase,
        "gaps": [{**asdict(g), "fix_hint": fix_hint(g)} for g in gaps],
    }, indent=2))
    return 1 if verdict == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
